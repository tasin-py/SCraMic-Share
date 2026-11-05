"""Sends frames to the UnityCapture camera filter ("ScramicShare Cam").

The filter (MIT, https://github.com/schellingb/UnityCapture) only exists in a process that has
the camera open. It makes a shared memory block, and we write each picture into it.
"""
import ctypes
import struct
from ctypes import wintypes

import numpy as np

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenMutexA.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCSTR)
kernel32.OpenMutexA.restype = wintypes.HANDLE
kernel32.CreateEventA.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCSTR)
kernel32.CreateEventA.restype = wintypes.HANDLE
kernel32.OpenEventA.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCSTR)
kernel32.OpenEventA.restype = wintypes.HANDLE
kernel32.OpenFileMappingA.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCSTR)
kernel32.OpenFileMappingA.restype = wintypes.HANDLE
kernel32.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

SYNCHRONIZE, EVENT_MODIFY_STATE, FILE_MAP_WRITE = 0x00100000, 0x0002, 0x0002
WAIT_OBJECT_0, WAIT_ABANDONED = 0, 0x80
HEADER = struct.Struct("<7i")     # width, height, stride, format, resize mode, mirror mode, timeout
SIZE_AT, DATA_AT = 0, 32          # the size limit comes first, then HEADER at 4, then the pixels
FORMAT_UINT8, RESIZE_LINEAR, MIRROR_NONE = 0, 1, 0
TIMEOUT_MS = 2147483447           # effectively never: the filter's own "no signal" message stays away


class UnityCam:
    def __init__(self):
        self.mutex = self.want = self.sent = self.mapping = None
        self.view = None
        self.pixels = None

    def _open(self):
        """False while no app has the camera open: there is nothing to write to yet."""
        if self.view:
            return True
        if not self.mutex:
            self.mutex = kernel32.OpenMutexA(SYNCHRONIZE, False, b"UnityCapture_Mutx")
            if not self.mutex:
                return False
        if not self._lock():
            return False
        try:
            if not self.want:
                self.want = kernel32.CreateEventA(None, False, False, b"UnityCapture_Want")
            if not self.sent:
                self.sent = kernel32.OpenEventA(EVENT_MODIFY_STATE, False, b"UnityCapture_Sent")
            if not self.mapping:
                self.mapping = kernel32.OpenFileMappingA(FILE_MAP_WRITE, False, b"UnityCapture_Data")
            if self.want and self.sent and self.mapping:
                self.view = kernel32.MapViewOfFile(self.mapping, FILE_MAP_WRITE, 0, 0, 0)
        finally:
            kernel32.ReleaseMutex(self.mutex)
        return bool(self.view)

    def _lock(self):
        return kernel32.WaitForSingleObject(self.mutex, 1000) in (WAIT_OBJECT_0, WAIT_ABANDONED)

    def send(self, frame):
        """Takes an RGB picture (height, width, 3). True if it was written."""
        if not self._open():
            return False
        h, w = frame.shape[:2]
        size = w * h * 4
        if struct.unpack_from("<I", ctypes.string_at(self.view + SIZE_AT, 4))[0] < size:
            return False
        if self.pixels is None or self.pixels.shape[:2] != (h, w):
            self.pixels = np.full((h, w, 4), 255, dtype=np.uint8)
        self.pixels[:, :, :3] = frame[::-1]    # the filter reads the bottom row first
        if not self._lock():
            return False
        try:
            ctypes.memmove(self.view + 4, HEADER.pack(w, h, w, FORMAT_UINT8, RESIZE_LINEAR, MIRROR_NONE, TIMEOUT_MS), HEADER.size)
            ctypes.memmove(self.view + DATA_AT, self.pixels.ctypes.data, size)
        finally:
            kernel32.ReleaseMutex(self.mutex)
        kernel32.SetEvent(self.sent)
        return True

    def close(self):
        if self.view:
            kernel32.UnmapViewOfFile(self.view)
        for h in (self.mapping, self.sent, self.want, self.mutex):
            if h:
                kernel32.CloseHandle(h)
        self.mutex = self.want = self.sent = self.mapping = None
        self.view = None

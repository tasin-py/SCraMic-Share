"""Sends frames to the UnityCapture camera filter ("ScramicShare Cam").

The filter (MIT, https://github.com/schellingb/UnityCapture) only exists in a process that has
the camera open. It makes a shared memory block, and we write each picture into it.

Each app using the camera asks for a picture (the "want" event), then waits for the "sent" event. That event
wakes only one waiting app per signal, so two apps using the camera would take turns, each getting half the
pictures. So we answer each request with exactly one signal: at once if an app is late for the newest picture,
or when the next picture is ready. How many apps are late is worked out from how many took each recent picture.
"""
import ctypes
import struct
import threading
import time
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
        self.waiting = 0              # requests waiting for the next picture
        self.late = 0                 # apps that haven't had the newest picture yet
        self.taken = 0                # how many took the newest picture
        self.apps, self.apps_at = 1, 0.0     # the most that took a recent picture, and when
        self.asked = False            # an app asked since the last wanted()
        self.count_lock = threading.Lock()
        self.counter = None
        self.closing = False

    def _answer_requests(self):
        while not self.closing:
            if kernel32.WaitForSingleObject(self.want, 200) != WAIT_OBJECT_0:
                continue
            with self.count_lock:
                self.asked = True
                late = self.late > 0
                if late:
                    self.late -= 1
                    self.taken += 1
                else:
                    self.waiting += 1
            if late:
                kernel32.SetEvent(self.sent)

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
                self.counter = threading.Thread(target=self._answer_requests, daemon=True, name="vcam-requests")
                self.counter.start()
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
        if self.pixels is None or self.pixels.shape[:2] != (h, w):
            self.pixels = np.full((h, w, 4), 255, dtype=np.uint8)
        self.pixels[:, :, :3] = frame[::-1]    # the filter reads the bottom row first
        return self._write(self.pixels.ctypes.data, w, h)

    def send_rgba(self, data, w, h):
        """Takes the bytes of an RGBA picture that already starts with its bottom row. True if it was written."""
        if len(data) != w * h * 4 or not self._open():
            return False
        return self._write(data, w, h)

    def _write(self, pixels, w, h):
        size = w * h * 4
        if struct.unpack_from("<I", ctypes.string_at(self.view + SIZE_AT, 4))[0] < size:
            return False
        if not self._lock():
            return False
        try:
            ctypes.memmove(self.view + 4, HEADER.pack(w, h, w, FORMAT_UINT8, RESIZE_LINEAR, MIRROR_NONE, TIMEOUT_MS), HEADER.size)
            ctypes.memmove(self.view + DATA_AT, pixels, size)
        finally:
            kernel32.ReleaseMutex(self.mutex)
        self._release()
        return True

    def _release(self):
        """A new picture is ready: answers the requests waiting for it. Apps that ask later get it when they ask."""
        now = time.monotonic()
        with self.count_lock:
            if self.taken >= self.apps or now - self.apps_at > 1:
                self.apps, self.apps_at = max(1, self.taken), now
            n, self.waiting = self.waiting, 0
            self.taken = n
            self.late = max(0, self.apps - n)
        for _ in range(n):
            kernel32.SetEvent(self.sent)

    def repeat(self):
        """Shows the last picture again."""
        if self.view:
            self._release()

    def wanted(self):
        """True if an app asked for a picture since the last call: the filter signals this for each frame it fetches."""
        with self.count_lock:
            asked, self.asked = self.asked, False
        return asked

    def close(self):
        self.closing = True
        if self.counter:
            self.counter.join()
        if self.view:
            kernel32.UnmapViewOfFile(self.view)
        for h in (self.mapping, self.sent, self.want, self.mutex):
            if h:
                kernel32.CloseHandle(h)
        self.mutex = self.want = self.sent = self.mapping = None
        self.view = None

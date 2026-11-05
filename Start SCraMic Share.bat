@echo off
cd /d "%~dp0"

python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 goto no_python

python -c "import PySide6, aiohttp, qrcode, cryptography, mss, PIL, numpy" >nul 2>nul
if errorlevel 1 goto no_libraries

start "" pythonw scramicshare.py
exit /b

:no_python
title SCraMic Share
echo.
echo SCraMic Share can't start because Python 3.10 or newer wasn't found.
echo.
echo The easiest fix is to download the installer, which doesn't need Python:
echo https://github.com/tasin-py/SCraMic-Share/releases
echo.
pause
exit /b 1

:no_libraries
title SCraMic Share
echo.
echo SCraMic Share can't start because some of its Python libraries are missing.
echo.
echo To add them, run this once in this folder:
echo pip install -r requirements.txt
echo.
pause
exit /b 1

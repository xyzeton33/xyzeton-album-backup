@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
REM ============================================================
REM  XYZETONAlbumBackup - Windows build script
REM  Copyright (C) 2026 XYZETON. GPL-3.0-or-later.
REM  Requires: Python 3.12 (must be runnable as "py -3.12")
REM  Output:   dist\XYZETONAlbumBackup\      (the app)
REM            dist\XYZETONAlbumBackup_vX.zip (upload this)
REM            dist\SHA256.txt               (publish next to the download)
REM
REM  NOTE: kept 100 percent ASCII on purpose - non-ASCII text inside a
REM  .bat can be corrupted depending on the console code page.
REM ============================================================

echo ------------------------------------------------------------
echo [0/6] Checking that every required file is here...
set MISSING=
for %%F in (gui.py album_export.py probe.py conftest.py LICENSE THIRD_PARTY_NOTICES.md README_ja.md README_en.md) do (
  if not exist "%%F" (
    echo   MISSING: %%F
    set MISSING=1
  )
)
if defined MISSING (
  echo.
  echo   The files listed above are not in this folder:
  echo     %CD%
  echo   Download them and put them next to build.bat, then run this again.
  goto :err
)

dir /b test_*.py >nul 2>&1
if errorlevel 1 (
  echo   MISSING: no test_*.py files found in this folder.
  set MISSING=1
)

echo Source files that will be built (check the version here):
findstr /C:"VERSION = " gui.py
if errorlevel 1 (
  echo   gui.py not found or has no VERSION line. Is this the right folder?
  goto :err
)
findstr /C:"MEDIA_TYPES = " album_export.py >nul
if errorlevel 1 (
  echo   album_export.py looks OLD - it has no MEDIA_TYPES. Overwrite it with the latest file.
  goto :err
)
echo   All required files are present.
echo ------------------------------------------------------------

echo [1/6] Creating a clean virtual environment...
if exist .venv rmdir /s /q .venv
py -3.12 -m venv .venv
if errorlevel 1 goto :err
call .venv\Scripts\activate.bat

echo [2/6] Installing dependencies...
REM --no-cache-dir: a locked/unreadable cached wheel causes "Permission denied".
python -m pip install --no-cache-dir --upgrade pip >nul
REM Pin the versions that were verified on a real iPhone, so a rebuild months
REM from now produces the same behaviour. Bump these only after re-testing.
python -m pip install --no-cache-dir pymobiledevice3==11.3.1 customtkinter==6.0.0 pyinstaller==6.22.2
if errorlevel 1 goto :err

echo [2.5/6] Running device-free tests (pytest)...
python -m pip install --no-cache-dir pytest >nul
REM Collect every test_*.py automatically. pytest skips dist, build and .venv
python -m pytest -q -rs > "%TEMP%\iab_pytest_result.txt" 2>&1
set PYTEST_RC=%errorlevel%
type "%TEMP%\iab_pytest_result.txt"
if not "%PYTEST_RC%"=="0" (
  echo.
  echo   TESTS FAILED. Do not ship this build.
  echo   Scroll up to see which test failed, and fix it first.
  goto :err
)

REM A skipped test is an untested test. Symlink tests are skipped on PCs where
REM Developer Mode is off, so a release build must have zero skips.
REM To build anyway for personal use: run "set ALLOW_SKIP=1" before build.bat.
findstr /r /c:"[0-9][0-9]* skipped" "%TEMP%\iab_pytest_result.txt" >nul
if errorlevel 1 goto :noskip
if defined ALLOW_SKIP (
  echo.
  echo   WARNING: some tests were SKIPPED. ALLOW_SKIP is set, so the build continues.
  echo   Do NOT publish this build.
  goto :noskip
)
echo.
echo   SOME TESTS WERE SKIPPED, so part of the safety checks did not run.
echo   Turn on Developer Mode:
echo     Settings - Privacy and security - For developers - Developer Mode
echo   then run build.bat again.
echo   (For a personal build only: run "set ALLOW_SKIP=1" first.)
goto :err
:noskip

REM Unused optional dependencies of pymobiledevice3 (FFmpeg via av, Pillow, jedi, IPython)
REM are excluded. The tool never imports them, and bundling them would require
REM shipping their license texts (FFmpeg is LGPL). See THIRD_PARTY_NOTICES.md.
echo [3/6] Building the exe (this can take a few minutes)...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --onedir --windowed --name XYZETONAlbumBackup --collect-all pymobiledevice3 --collect-all customtkinter --exclude-module av --exclude-module PIL --exclude-module jedi --exclude-module IPython --add-data "album_export.py;." --add-data "LICENSE;." --add-data "README_ja.md;." --add-data "README_en.md;." gui.py
if errorlevel 1 goto :err

echo [4/6] Copying bundled files (source code included per GPL)...
mkdir dist\XYZETONAlbumBackup\source 2>nul
mkdir dist\XYZETONAlbumBackup\source\tests 2>nul
copy /y album_export.py dist\XYZETONAlbumBackup\source\ >nul
copy /y gui.py          dist\XYZETONAlbumBackup\source\ >nul
copy /y probe.py        dist\XYZETONAlbumBackup\source\ >nul
copy /y conftest.py     dist\XYZETONAlbumBackup\source\ >nul
copy /y build.bat       dist\XYZETONAlbumBackup\source\ >nul
copy /y test_*.py       dist\XYZETONAlbumBackup\source\tests\ >nul
copy /y LICENSE dist\XYZETONAlbumBackup\ >nul
copy /y README_ja.md dist\XYZETONAlbumBackup\ >nul
copy /y README_en.md dist\XYZETONAlbumBackup\ >nul
copy /y THIRD_PARTY_NOTICES.md dist\XYZETONAlbumBackup\ >nul
if exist docs (
  mkdir dist\XYZETONAlbumBackup\docs 2>nul
  copy /y docs\*.md dist\XYZETONAlbumBackup\docs\ >nul
)

echo [5/6] Creating the distribution zip...
set VER=
for /f "tokens=3 delims= " %%a in ('findstr /C:"VERSION = " gui.py') do set VER=%%~a
if "%VER%"=="" set VER=unknown
set ZIP=dist\XYZETONAlbumBackup_v%VER%.zip
if exist "%ZIP%" del /q "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\XYZETONAlbumBackup\*' -DestinationPath '%ZIP%' -Force"
if not exist "%ZIP%" goto :err

echo [6/6] Computing SHA-256 (publish this next to the download)...
set HASH=
for /f "skip=1 tokens=*" %%h in ('certutil -hashfile "%ZIP%" SHA256') do (
  if not defined HASH set HASH=%%h
)
set HASH=!HASH: =!
> dist\SHA256.txt echo XYZETONAlbumBackup_v%VER%.zip
>> dist\SHA256.txt echo SHA-256: !HASH!
>> dist\SHA256.txt echo Built: %DATE%

echo.
echo ============================================================
echo Done.  version %VER%
echo   app  : dist\XYZETONAlbumBackup\XYZETONAlbumBackup.exe
echo   zip  : %ZIP%
echo   hash : dist\SHA256.txt
echo   SHA-256: !HASH!
echo.
echo Upload the zip to GitHub Releases / BOOTH,
echo and publish the SHA-256 next to the download link.
echo ============================================================
pause
exit /b 0

:err
echo.
echo ============================================================
echo Build FAILED - no dist folder was created.
echo Read the message above: it names the file or step that failed.
echo ============================================================
pause
exit /b 1

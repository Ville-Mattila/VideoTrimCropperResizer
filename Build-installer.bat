@echo off
REM Builds dist\Leike-Setup.exe with Inno Setup.
REM Requires: dist\Leike.exe (run Build-exe.bat first),
REM           ffmpeg.exe on PATH, and Inno Setup 6 installed.
cd /d "%~dp0"

if not exist "dist\Leike.exe" (
  echo [!] Build the app first: run Build-exe.bat
  exit /b 1
)

set "FFMPEG="
for /f "delims=" %%i in ('where ffmpeg 2^>nul') do if not defined FFMPEG set "FFMPEG=%%i"
if not defined FFMPEG (
  echo [!] ffmpeg.exe not found on PATH.
  exit /b 1
)

REM Assemble the staging folder from tracked sources + the built exe.
set "STAGE=installer\staging"
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%\licenses"
copy /y "dist\Leike.exe" "%STAGE%\" >nul
copy /y "%FFMPEG%" "%STAGE%\ffmpeg.exe" >nul
copy /y "LICENSE" "%STAGE%\LICENSE.txt" >nul
copy /y "THIRD_PARTY_NOTICES.md" "%STAGE%\THIRD_PARTY_NOTICES.txt" >nul
copy /y "licenses\ffmpeg-GPLv3.txt" "%STAGE%\licenses\" >nul

set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo [!] ISCC.exe not found. Install Inno Setup 6 ^(winget install JRSoftware.InnoSetup^).
  exit /b 1
)

"%ISCC%" "installer\Leike.iss"
echo.
echo Done. Installer is dist\Leike-Setup.exe

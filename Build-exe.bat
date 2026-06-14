@echo off
REM Rebuilds dist\Leike.exe from leike.py
cd /d "%~dp0"
REM python-mpv is bundled so the in-app "Enable playback" button can load a
REM downloaded libmpv. libmpv itself is NOT bundled (fetched on demand).
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name Leike ^
  --icon leike.ico ^
  --add-data "leike.ico;." ^
  --collect-all tkinterdnd2 ^
  --hidden-import mpv ^
  leike.py
echo.
echo Done. The exe is in the "dist" folder.
pause

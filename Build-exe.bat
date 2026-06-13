@echo off
REM Rebuilds dist\Leike.exe from leike.py
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name Leike ^
  --collect-all tkinterdnd2 ^
  --collect-all sv_ttk ^
  leike.py
echo.
echo Done. The exe is in the "dist" folder.
pause

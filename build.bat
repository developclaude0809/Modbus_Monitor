@echo off
REM --- Clean ---
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM --- Build with MSVC (no clang) ---
REM Note: app.py automatically includes logic.py, view_v1.py, and theme.py via imports
REM       No need to explicitly include them - Nuitka follows imports automatically
python -m nuitka app.py ^
  --onefile ^
  --windows-disable-console ^
  --output-filename=Monitor.exe ^
  --windows-icon-from-ico=icon\Icon_Monitor_App.ico ^
  --enable-plugin=pyqt5 ^
  --include-data-files=icon\Icon_Monitor_App.ico=icon\Icon_Monitor_App.ico ^
  --include-data-dir=assets\fonts=assets\fonts ^
  --lto=yes ^
  --assume-yes-for-downloads ^
  --msvc=latest

echo.
echo Done: .\Monitor.exe
pause

@echo off
cd /d "%~dp0"
if not exist ".python312\python.exe" goto nopy
".python312\python.exe" main.py
goto end
:nopy
echo [ERROR] Python 3.12 not found in .python312 folder. See README.md.
:end
pause

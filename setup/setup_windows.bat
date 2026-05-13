@echo off
cd /d "%~dp0.."

echo === Camera Viewer - Setup Windows ===

python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q
pip install -r requirements.txt -q

echo.
echo Setup completato!
echo.
echo Per avviare:   .venv\Scripts\activate && python main.py
echo Per buildare:  build_windows.bat
pause

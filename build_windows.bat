@echo off
setlocal enabledelayedexpansion

set APP_NAME=Camera Viewer
set DIST_DIR=dist
set EXE_PATH=%DIST_DIR%\%APP_NAME%.exe

echo =^> Building %APP_NAME%.exe ...
.venv\Scripts\pyinstaller camera_viewer_windows.spec --noconfirm
if errorlevel 1 goto :error

echo =^> Build completato: %EXE_PATH%

:: ── Copia config se AppData è vuoto ──────────────────────────────────────────
set APPDATA_DIR=%APPDATA%\Camera Viewer
if not exist "%APPDATA_DIR%" mkdir "%APPDATA_DIR%"
if exist "config.json" (
    if not exist "%APPDATA_DIR%\config.json" (
        echo =^> Copiando config.json in AppData ...
        copy "config.json" "%APPDATA_DIR%\config.json"
    )
)

echo.
echo Done:
for %%A in ("%EXE_PATH%") do echo   EXE : %EXE_PATH% (%%~zA bytes)
echo.
goto :end

:error
echo.
echo ERRORE durante il build.
exit /b 1

:end

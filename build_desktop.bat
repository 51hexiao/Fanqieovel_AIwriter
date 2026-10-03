@echo off
cd /d "%~dp0"

rem ---- close running app (exe file is locked while running) ----
taskkill /f /im FanqieWorkbench.exe >nul 2>&1

python -m pip install -q pyinstaller

rem ---- backup user data (config/db/login) before wiping dist ----
set "DUSER=%TEMP%\fanqie_user_data"
if exist dist\FanqieWorkbench (
  if exist "%DUSER%" rmdir /s /q "%DUSER%"
  mkdir "%DUSER%"
  for %%F in (config.json data.db data.db-shm data.db-wal sensitive.txt selectors.json app.log) do (
    if exist "dist\FanqieWorkbench\%%F" copy /y "dist\FanqieWorkbench\%%F" "%DUSER%" >nul
  )
  if exist "dist\FanqieWorkbench\browser_profile" robocopy "dist\FanqieWorkbench\browser_profile" "%DUSER%\browser_profile" /e /nfl /ndl /njh /njs >nul
)

python -m PyInstaller --noconfirm --clean --windowed --name FanqieWorkbench --add-data "static;static" --collect-all uvicorn --collect-all webview --collect-all pythonnet --collect-all clr_loader --collect-all pydantic --collect-all playwright desktop.py

rem ---- restore user data ----
if exist "%DUSER%" (
  if not exist dist\FanqieWorkbench mkdir dist\FanqieWorkbench
  for %%F in (config.json data.db data.db-shm data.db-wal sensitive.txt selectors.json app.log) do (
    if exist "%DUSER%\%%F" copy /y "%DUSER%\%%F" "dist\FanqieWorkbench\" >nul
  )
  if exist "%DUSER%\browser_profile" robocopy "%DUSER%\browser_profile" "dist\FanqieWorkbench\browser_profile" /e /nfl /ndl /njh /njs >nul
  rmdir /s /q "%DUSER%"
)

echo.
echo Build OK: dist\FanqieWorkbench\FanqieWorkbench.exe
pause

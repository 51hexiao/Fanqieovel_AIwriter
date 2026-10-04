@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---- close running app (exe file is locked while running) ----
taskkill /f /im FanqieWorkbench.exe >nul 2>&1
rem 给文件锁释放留时间，避免备份复制到半开的库
ping -n 3 127.0.0.1 >nul

rem ---- 常驻发布助手浏览器锁着 browser_profile：只关助手（按命令行识别，不碰日常 Edge）----
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object {($_.Name -eq 'msedge.exe') -and ($_.CommandLine -like '*browser_profile*')} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
ping -n 3 127.0.0.1 >nul

python -m pip install -q pyinstaller

rem ---- checkpoint WAL：把 -wal 里已提交的数据合并进主库文件，主库自成一体 ----
if exist dist\FanqieWorkbench\data.db (
  python -c "import sqlite3;c=sqlite3.connect(r'dist\FanqieWorkbench\data.db',timeout=15);print('wal_checkpoint:',c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone());c.close()" 2>nul
)

rem ---- timestamped backup (never auto-deleted) ----
for /f "delims=" %%i in ('python -c "import time;print(time.strftime('%%Y%%m%%d_%%H%%M%%S'))"') do set "TS=%%i"
set "BK=%TEMP%\fanqie_backup_%TS%"
set "HADDB=0"
if exist dist\FanqieWorkbench\data.db set "HADDB=1"
if exist dist\FanqieWorkbench (
  mkdir "%BK%" 2>nul
  for %%F in (config.json data.db data.db-shm data.db-wal sensitive.txt selectors.json app.log) do (
    if exist "dist\FanqieWorkbench\%%F" copy /y "dist\FanqieWorkbench\%%F" "%BK%\" >nul
  )
  if exist "dist\FanqieWorkbench\browser_profile" robocopy "dist\FanqieWorkbench\browser_profile" "%BK%\browser_profile" /e /nfl /ndl /njh /njs /r:1 /w:1 >nul
)

rem ---- 铁律：dist 里有库就必须先备份成功，否则绝不进入会清空 dist 的构建 ----
if "%HADDB%"=="1" if not exist "%BK%\data.db" (
  echo.
  echo ============================================================
  echo  [ABORT] data.db backup failed ^(file locked?^). Build cancelled,
  echo  dist folder is NOT touched. Close the app and retry.
  echo ============================================================
  pause
  exit /b 1
)
echo Backup kept at: %BK%

python -m PyInstaller --noconfirm --clean --windowed --name FanqieWorkbench --add-data "static;static" --collect-all uvicorn --collect-all webview --collect-all pythonnet --collect-all clr_loader --collect-all pydantic --collect-all playwright desktop.py
set "RC=%errorlevel%"

rem ---- restore user data (always, even if the build failed) ----
if exist "%BK%" (
  if not exist dist\FanqieWorkbench mkdir dist\FanqieWorkbench
  for %%F in (config.json data.db data.db-shm data.db-wal sensitive.txt selectors.json app.log) do (
    if exist "%BK%\%%F" copy /y "%BK%\%%F" "dist\FanqieWorkbench\" >nul
  )
  if exist "%BK%\browser_profile" robocopy "%BK%\browser_profile" "dist\FanqieWorkbench\browser_profile" /e /nfl /ndl /njh /njs /r:1 /w:1 >nul
)

rem ---- 恢复后校验：库必须存在且通过完整性检查 ----
set "DBOK=1"
if "%HADDB%"=="1" if not exist dist\FanqieWorkbench\data.db set "DBOK=0"
if exist dist\FanqieWorkbench\data.db (
  python -c "import sqlite3;c=sqlite3.connect(r'dist\FanqieWorkbench\data.db',timeout=15);r=c.execute('PRAGMA integrity_check').fetchone()[0];c.close();exit(0 if r=='ok' else 1)" 2>nul
  if errorlevel 1 set "DBOK=0"
)
if "%DBOK%"=="0" (
  echo.
  echo ============================================================
  echo  [WARNING] data.db missing or FAILED integrity check after
  echo  restore. Do NOT start the app yet. Manual copy needed from:
  echo    %BK%
  echo ============================================================
  pause
  exit /b 1
)

echo.
if not "%RC%"=="0" (
  echo Build FAILED ^(rc=%RC%^) but user data restored OK. Backup kept at: %BK%
) else (
  echo Build OK: dist\FanqieWorkbench\FanqieWorkbench.exe
  echo Backup kept at: %BK%
)
pause

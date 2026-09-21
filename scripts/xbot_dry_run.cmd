@echo off
REM XBot - DRY-RUN (hicbir hesabi engellemez, sadece rapor eder)
REM Windows Gorev Zamanlayici bu dosyayi cagirir.
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
python -m xbot run --headless --rapor >> "logs\gorev.log" 2>&1
exit /b %ERRORLEVEL%

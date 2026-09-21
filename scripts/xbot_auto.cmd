@echo off
REM XBot - AUTO (YUKSEK kararli hesaplari GERCEKTEN engeller)
REM Once dry-run ile gunlerce dene, sonucu begenirsen bunu zamanla.
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
python -m xbot run --auto --headless --rapor >> "logs\gorev.log" 2>&1
exit /b %ERRORLEVEL%

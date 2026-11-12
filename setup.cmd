@echo off
rem setup.cmd - Windows entry: runs setup.ps1 (installs .venv from uv.lock and stamps the lock hash).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
exit /b %ERRORLEVEL%

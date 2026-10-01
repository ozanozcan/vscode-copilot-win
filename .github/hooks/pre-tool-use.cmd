@echo off
if /i not "%COPILOT_AGENT_HOST_HOOKS%"=="1" exit /b 0
py -3 "%~dp0pre-tool-use.py"
exit /b %ERRORLEVEL%
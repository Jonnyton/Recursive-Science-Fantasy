@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title AutoResearch Fantasy v4 Launcher

call :load_env

if not exist "evaluate.py" (
    echo [ERROR] evaluate.py not found in %cd%
    exit /b 1
)

curl -s --connect-timeout 3 http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Ollama is not running. Start it with: ollama serve
    exit /b 1
)

python -c "import openai, anthropic" >nul 2>&1
if errorlevel 1 (
    echo Installing Python packages...
    pip install openai anthropic edge-tts -q >nul 2>&1
    if errorlevel 1 (
        pip install openai anthropic edge-tts -q --user >nul 2>&1
    )
)

set "ARGS=%*"
if "%~1"=="" (
    if "%ANTHROPIC_API_KEY%"=="" (
        set "ARGS=--scenarios 1"
    ) else (
        set "ARGS=--pass2 --scenarios 1"
    )
)

echo.
echo Launching: python evaluate.py !ARGS!
echo.
python evaluate.py !ARGS!
exit /b %ERRORLEVEL%

:load_env
if not exist ".env" goto :eof
for /f "usebackq delims=" %%L in (".env") do (
    set "line=%%L"
    if defined line if not "!line:~0,1!"=="#" (
        for /f "tokens=1,* delims==" %%a in ("!line!") do (
            if not "%%a"=="" set "%%a=%%b"
        )
    )
)
goto :eof

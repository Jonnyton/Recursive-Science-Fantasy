@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title AutoResearch Fantasy v4 Setup

call :load_env

echo.
echo   ================================================
echo     AutoResearch Fantasy v4 - Readiness Check
echo   ================================================
echo.

if not exist "evaluate.py" (
    echo   [ERROR] evaluate.py not found in %cd%
    exit /b 1
)
echo   [OK] Evaluator found

python -c "import openai, anthropic" >nul 2>&1
if errorlevel 1 (
    echo   Installing Python packages...
    pip install openai anthropic edge-tts -q >nul 2>&1
    if errorlevel 1 (
        pip install openai anthropic edge-tts -q --user >nul 2>&1
    )
)
python -c "import openai, anthropic" >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python dependencies are missing. Install openai, anthropic, edge-tts.
    exit /b 1
)
echo   [OK] Python dependencies available

curl -s --connect-timeout 3 http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Ollama is not running. Start it with: ollama serve
    exit /b 1
)
echo   [OK] Ollama is running

curl -s http://localhost:11434/api/tags 2>nul | findstr /i "qwen3.5" >nul 2>&1
if errorlevel 1 (
    echo   [WARN] qwen3.5 is not installed. Run: ollama pull qwen3.5
) else (
    echo   [OK] qwen3.5 model available
)

if "%ANTHROPIC_API_KEY%"=="" (
    echo   [WARN] ANTHROPIC_API_KEY is not set. Frontier ratchet is disabled.
) else (
    echo   [OK] ANTHROPIC_API_KEY loaded
)

echo.
echo   Ready.
echo.
echo   Local-only smoke test:
echo     python evaluate.py --scenarios 1
echo.
echo   Full ratchet run:
echo     python evaluate.py --pass2 --scenarios 1
echo.
echo   Bootstrap missing baselines:
echo     python evaluate.py --bootstrap-missing 2
echo.
echo   Or use:
echo     start.bat
echo.
exit /b 0

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

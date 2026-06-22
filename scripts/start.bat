@echo off
REM One-command setup + launch for the Sandboxed AI Assistant (Windows).
REM
REM   scripts\start.bat
REM
REM Checks .env, creates required directories, then launches the hardened
REM container with docker compose.

setlocal enableextensions
cd /d "%~dp0.."

echo.
echo  Sandboxed AI Assistant - startup
echo  --------------------------------

REM 1. Docker present?
where docker >nul 2>&1
if errorlevel 1 (
  echo [X] Docker is not installed or not on PATH.
  echo     Install Docker Desktop: https://www.docker.com/products/docker-desktop/
  exit /b 1
)

REM 1b. Docker daemon running?
docker info >nul 2>&1
if errorlevel 1 (
  echo [X] Docker is installed but the daemon isn't responding.
  echo     Start Docker Desktop and try again.
  exit /b 1
)

REM 2. .env present? If not, create from template (no secrets needed in V1).
if not exist ".env" (
  echo [i] No .env found - creating one from .env.example ^(V1 needs no API key^).
  copy /y ".env.example" ".env" >nul
  echo [OK] Created .env
) else (
  echo [OK] .env found
)

REM 3. Ensure required writable directories exist.
if not exist "data\uploads" mkdir "data\uploads"
if not exist "data\chroma" mkdir "data\chroma"
if not exist "data\model_cache" mkdir "data\model_cache"
if not exist "logs" mkdir "logs"
echo [OK] Data and log directories ready

REM 4. Launch.
echo.
echo  Building and starting the container ^(first build downloads the model once^)...
echo  When it's up, open:  http://localhost:8501
echo.
docker compose up --build

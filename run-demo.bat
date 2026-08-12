@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem ===================================================================
rem  AI Cost-Quality Control Plane - one-shot Windows setup and launch
rem
rem  Installs every Python and Node dependency, seeds ATLAS, then starts
rem  all four services in their own windows and opens the browser.
rem
rem  Usage:  run-demo.bat [options]
rem
rem    /reinstall   rebuild the venv and reinstall node_modules
rem    /noatlas     control plane only (skip the ATLAS agent + its UI)
rem    /noseed      skip seeding ATLAS with 21 days of run history
rem    /notest      skip the promotion-engine unit tests
rem    /setuponly   install everything, do not start any service
rem ===================================================================

set "ROOT=%~dp0"
pushd "%ROOT%" || (echo Could not enter "%ROOT%". & exit /b 1)

set "REINSTALL="
set "NOATLAS="
set "NOSEED="
set "NOTEST="
set "SETUPONLY="

:parseargs
if "%~1"=="" goto endargs
if /i "%~1"=="/reinstall" set "REINSTALL=1"
if /i "%~1"=="/noatlas"   set "NOATLAS=1"
if /i "%~1"=="/noseed"    set "NOSEED=1"
if /i "%~1"=="/notest"    set "NOTEST=1"
if /i "%~1"=="/setuponly" set "SETUPONLY=1"
shift
goto parseargs
:endargs

echo.
echo ===================================================================
echo   AI Cost-Quality Control Plane
echo   minimize cost subject to quality ^>= floor and latency ^<= ceiling
echo ===================================================================
echo.

rem ---------------------------------------------------------------
rem  1/7  Locate a Python interpreter
rem
rem  Every dependency is a version floor over pure-Python packages -
rem  no numpy, no compiled extension of our own - so 3.13 resolves
rem  cleanly. The py launcher is tried first because a bare "python"
rem  on PATH is often the Microsoft Store stub.
rem ---------------------------------------------------------------
echo [1/7] Locating Python...

set "PY="
for %%C in ("py -3.13" "py -3" "python" "python3") do (
    if not defined PY (
        cmd /c %%~C -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 set "PY=%%~C"
    )
)

if not defined PY goto nopython

for /f "tokens=2" %%v in ('cmd /c %PY% --version 2^>^&1') do set "PYVER=%%v"
for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
    set "PYMAJ=%%a"
    set "PYMIN=%%b"
)
if !PYMAJ! lss 3 goto oldpython
if !PYMAJ! equ 3 if !PYMIN! lss 11 goto oldpython
echo       using %PY%  (Python !PYVER!)

rem ---------------------------------------------------------------
rem  2/7  Node
rem ---------------------------------------------------------------
echo [2/7] Locating Node...

where node >nul 2>&1
if !errorlevel! neq 0 (
    echo.
    echo   ERROR: Node.js not found on PATH. Install Node 18 or newer
    echo   from https://nodejs.org and re-run this script.
    echo.
    goto fail
)
for /f "delims=" %%v in ('node --version') do set "NODEVER=%%v"
echo       node !NODEVER!

rem ---------------------------------------------------------------
rem  3/7  Python virtual environment
rem
rem  One venv at backend\.venv serves both the control plane and
rem  ATLAS - ATLAS's requirements are a strict subset, so there is
rem  nothing to conflict.
rem ---------------------------------------------------------------
echo [3/7] Python environment...

set "VENV=%ROOT%backend\.venv"
set "VPY=%VENV%\Scripts\python.exe"

if defined REINSTALL if exist "%VENV%" (
    echo       /reinstall - removing the existing venv
    rmdir /s /q "%VENV%"
)

if not exist "%VPY%" (
    echo       creating venv at backend\.venv
    cmd /c %PY% -m venv "%VENV%"
    if !errorlevel! neq 0 goto fail
) else (
    echo       reusing venv at backend\.venv
)

echo       upgrading pip
"%VPY%" -m pip install --quiet --upgrade pip setuptools wheel
if !errorlevel! neq 0 goto fail

echo       installing control plane requirements
"%VPY%" -m pip install --quiet -r "%ROOT%backend\requirements.txt"
if !errorlevel! neq 0 goto fail

if not defined NOATLAS (
    echo       installing ATLAS requirements
    "%VPY%" -m pip install --quiet -r "%ROOT%agent-atlas\backend\requirements.txt"
    if !errorlevel! neq 0 goto fail
)

rem ---------------------------------------------------------------
rem  4/7  Node packages
rem ---------------------------------------------------------------
echo [4/7] Node packages...

call :npmsetup "%ROOT%frontend" "control plane UI"
if !errorlevel! neq 0 goto fail

if not defined NOATLAS (
    call :npmsetup "%ROOT%agent-atlas\frontend" "ATLAS terminal"
    if !errorlevel! neq 0 goto fail
)

rem ---------------------------------------------------------------
rem  5/7  Unit tests - the promotion engine is the one place tests
rem       are mandatory, so a green run here is the real smoke test.
rem ---------------------------------------------------------------
if defined NOTEST (
    echo [5/7] Tests skipped ^(/notest^)
) else (
    echo [5/7] Running promotion-engine tests...
    pushd "%ROOT%backend"
    set "PYTHONPATH=."
    "%VPY%" -m pytest tests -q
    if !errorlevel! neq 0 (
        echo.
        echo   WARNING: tests did not pass. Continuing anyway - the demo
        echo   reads committed fixtures and will still start.
        echo.
    )
    set "PYTHONPATH="
    popd
)

rem ---------------------------------------------------------------
rem  6/7  Seed ATLAS with operating history
rem
rem  The control plane seeds itself from committed fixtures on first
rem  request. ATLAS starts empty, so Act 1 of the demo needs this.
rem  ATLAS_SPEED=0 removes the simulated per-step delay.
rem ---------------------------------------------------------------
if defined NOATLAS goto skipseed
if defined NOSEED (
    echo [6/7] ATLAS seeding skipped ^(/noseed^)
    goto skipseed
)
echo [6/7] Seeding ATLAS with 21 days of run history...
echo       this is the slow step - allow a minute or two
pushd "%ROOT%agent-atlas\backend"
set "PYTHONPATH=."
set "ATLAS_SPEED=0"
"%VPY%" -m atlas.batch --mode both --days 21 --clear
if !errorlevel! neq 0 (
    echo.
    echo   WARNING: ATLAS seeding failed. ATLAS will start empty - you can
    echo   still run single executions from its terminal UI.
    echo.
)
set "PYTHONPATH="
set "ATLAS_SPEED="
popd
:skipseed

if defined SETUPONLY (
    echo.
    echo Setup complete. Re-run without /setuponly to start the services.
    goto done
)

rem ---------------------------------------------------------------
rem  7/7  Launch
rem
rem  Each service gets its own window so logs stay readable and any one
rem  can be restarted without killing the rest. start /D sets the
rem  working directory, which keeps every path inside the command
rem  relative and free of nested quotes.
rem
rem  "set PYTHONPATH=.&&" has no space before the && on purpose: with
rem  one, the variable would carry a trailing space into sys.path.
rem ---------------------------------------------------------------
echo [7/7] Starting services...

start "Control plane API 8000" /D "%ROOT%backend" cmd /k "set PYTHONPATH=.&& .venv\Scripts\uvicorn.exe app.main:app --port 8000"
echo       control plane API   http://127.0.0.1:8000/docs

start "Control plane UI 5173" /D "%ROOT%frontend" cmd /k "npm run dev"
echo       control plane UI    http://localhost:5173

if not defined NOATLAS (
    start "ATLAS API 8100" /D "%ROOT%agent-atlas\backend" cmd /k "set PYTHONPATH=.&& ..\..\backend\.venv\Scripts\uvicorn.exe atlas.server:app --port 8100"
    echo       ATLAS API           http://127.0.0.1:8100/docs
    start "ATLAS terminal 5174" /D "%ROOT%agent-atlas\frontend" cmd /k "npm run dev"
    echo       ATLAS terminal      http://localhost:5174
)

echo.
echo       waiting for the control plane to answer...
set "READY="
for /l %%i in (1,1,40) do (
    if not defined READY (
        curl -s -o nul -f http://127.0.0.1:8000/api/v1/spine >nul 2>&1
        if !errorlevel! equ 0 (
            set "READY=1"
        ) else (
            timeout /t 2 /nobreak >nul
        )
    )
)

if defined READY (
    echo       up - opening the browser
    start "" http://localhost:5173
) else (
    echo.
    echo   The API did not answer within 80 seconds. Check the
    echo   "Control plane API" window for the reason, then open
    echo   http://localhost:5173 by hand.
    echo.
)

:done
echo.
echo ===================================================================
if not defined SETUPONLY (
    echo   Running. Start on the Promotion board - that screen is the pitch.
    echo.
    echo   Reset the demo data:
    echo     curl -X POST http://127.0.0.1:8000/api/v1/admin/reset
    echo.
    echo   Stop everything: close the four service windows, or run
    echo     taskkill /FI "WINDOWTITLE eq Control plane*" /T /F
    echo     taskkill /FI "WINDOWTITLE eq ATLAS*" /T /F
)
echo ===================================================================
echo.
popd
pause
exit /b 0

rem ---------------------------------------------------------------
rem  helper: install node packages for one project
rem ---------------------------------------------------------------
:npmsetup
set "DIR=%~1"
set "WHAT=%~2"
if defined REINSTALL if exist "%DIR%\node_modules" (
    echo       /reinstall - removing %WHAT% node_modules
    rmdir /s /q "%DIR%\node_modules"
)
if exist "%DIR%\node_modules" (
    echo       %WHAT% already installed
    exit /b 0
)
echo       installing %WHAT%
pushd "%DIR%"
if exist package-lock.json (
    call npm ci --no-audit --no-fund
) else (
    call npm install --no-audit --no-fund
)
set "RC=%errorlevel%"
popd
if not "%RC%"=="0" (
    echo.
    echo   ERROR: npm install failed in %DIR%
    echo.
)
exit /b %RC%

:nopython
echo.
echo   ERROR: no Python found on PATH.
echo.
echo   You said you have 3.13 - it is most likely installed without the
echo   "py" launcher, or was not added to PATH. Either re-run the Python
echo   installer with "Add python.exe to PATH" ticked, or set PY by hand
echo   near the top of this script, for example:
echo.
echo     set "PY=C:\Users\you\AppData\Local\Programs\Python\Python313\python.exe"
echo.
goto fail

:oldpython
echo.
echo   ERROR: found Python !PYVER!, but this project needs 3.11 or newer.
echo   Install 3.13 from https://python.org and re-run this script.
echo.
goto fail

:fail
echo.
echo Setup failed. Nothing was started.
echo.
popd
pause
exit /b 1

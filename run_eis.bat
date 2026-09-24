@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Gamry EIS toolkit
set "ENV_NAME=gamry-eis"
set "PY="
set "CONDA_BAT="

rem ---------------------------------------------------------------
rem  1. Find conda (Anaconda / Miniconda), even if it is not on PATH
rem ---------------------------------------------------------------
for %%P in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%LOCALAPPDATA%\anaconda3" "%ProgramData%\miniconda3" "%ProgramData%\anaconda3" "%USERPROFILE%\miniforge3" "%LOCALAPPDATA%\miniforge3") do (
  if not defined CONDA_BAT if exist "%%~P\condabin\conda.bat" set "CONDA_BAT=%%~P\condabin\conda.bat"
)
if not defined CONDA_BAT for /f "delims=" %%C in ('where conda.bat 2^>nul') do if not defined CONDA_BAT set "CONDA_BAT=%%C"
if not defined CONDA_BAT goto :plain_python

echo Using conda: %CONDA_BAT%
call "%CONDA_BAT%" env list | findstr /r /c:"^%ENV_NAME% " >nul
if not errorlevel 1 goto :activate
echo.
echo First run: creating the Python environment "%ENV_NAME%". This takes a few minutes and needs internet.
echo Prvo pokretanje: pravim Python okruzenje "%ENV_NAME%". Traje nekoliko minuta, potreban je internet.
echo.
call "%CONDA_BAT%" env create -n %ENV_NAME% -f environment.yml
if errorlevel 1 goto :fail
:activate
call "%CONDA_BAT%" activate %ENV_NAME%
if errorlevel 1 goto :fail
set "PY=python"
goto :check_packages

rem ---------------------------------------------------------------
rem  2. No conda: use a normal Python install
rem ---------------------------------------------------------------
:plain_python
python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY goto :no_python
echo Using Python: %PY%

:check_packages
%PY% -c "import numpy, scipy, matplotlib, pandas, openpyxl, yaml, docx" >nul 2>nul
if not errorlevel 1 goto :run
echo Installing the required Python packages...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :fail

rem ---------------------------------------------------------------
rem  3. Run
rem ---------------------------------------------------------------
:run
if exist config.yaml goto :analyse
%PY% run_eis.py --init
if errorlevel 1 goto :fail
echo.
echo Edit config.yaml: names, legends, circuit. Save it, close Notepad, then run this file again.
echo Izmenite config.yaml: imena, legende, kolo. Sacuvajte, zatvorite Notepad i ponovo pokrenite ovaj fajl.
start "" notepad config.yaml
goto :end

:analyse
%PY% run_eis.py config.yaml
if errorlevel 1 goto :fail
goto :end

:no_python
echo.
echo Python was not found. Install Miniconda from https://docs.conda.io/en/latest/miniconda.html
echo and run this file again.
echo Python nije pronadjen. Instalirajte Minicondu sa gornje adrese i ponovo pokrenite ovaj fajl.
goto :end

:fail
echo.
echo Something went wrong. See the messages above.
echo Doslo je do greske. Pogledajte poruke iznad.

:end
echo.
pause

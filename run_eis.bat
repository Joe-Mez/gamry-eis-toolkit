@echo off
cd /d "%~dp0"
if not exist config.yaml (
  python run_eis.py --init
  if exist config.yaml (
    echo.
    echo Edit config.yaml: names, legends, circuit. Save it, close Notepad, then run this file again.
    echo Izmenite config.yaml: imena, legende, kolo. Sacuvajte, zatvorite Notepad i ponovo pokrenite ovaj fajl.
    notepad config.yaml
  )
) else (
  python run_eis.py config.yaml
)
pause

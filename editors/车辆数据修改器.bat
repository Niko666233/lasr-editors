@echo off
rem ============================================================
rem  LASR vehicle data editor - double-click launcher
rem  (the save editor ships as a self-contained exe; this one
rem   needs a Python with the "unicorn" module, because it runs
rem   the game's own FLZD compressor/decompressor.)
rem ============================================================
setlocal
set HERE=%~dp0
set VENV=%HERE%..\.capenv\Scripts\pythonw.exe
set VENVC=%HERE%..\.capenv\Scripts\python.exe

if exist "%VENV%" (
  start "" "%VENV%" "%HERE%vehicle_editor.pyw" %*
  goto :eof
)

where py >nul 2>nul
if errorlevel 1 goto :nopython
py -3 -c "import unicorn" >nul 2>nul
if errorlevel 1 goto :nounicorn
start "" pyw -3 "%HERE%vehicle_editor.pyw" %*
goto :eof

:nounicorn
echo.
echo  Python was found, but the 'unicorn' module is missing.
echo  Install it once with:
echo.
echo      py -3 -m pip install unicorn
echo.
echo  (the tool needs it to decompress/recompress the game's
echo   FLZD containers with the game's own code)
echo.
pause
goto :eof

:nopython
echo.
echo  No Python found. Either install Python 3.11+ from python.org
echo  and run:  py -3 -m pip install unicorn
echo  or use the project virtualenv at ..\.capenv\Scripts\
echo.
pause

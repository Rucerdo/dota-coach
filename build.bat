@echo off
REM Genera dist\DotaCoach.exe. La configuracion esta en toolsuild_exe.py.
cd /d "%~dp0"
.venv\Scripts\python -m pip install -q -r requirements-dev.txt || goto :error
.venv\Scripts\python toolsuild_exe.py || goto :error
goto :eof
:error
echo Error en la compilacion.
exit /b 1

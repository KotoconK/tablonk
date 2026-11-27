@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 tablonk.py
    exit /b
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw tablonk.py
    exit /b
)
echo Python no esta instalado. Ejecuta crear_exe.bat primero.
pause

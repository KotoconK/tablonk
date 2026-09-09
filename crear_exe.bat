@echo off
setlocal

echo ============================================
echo   Generando TablonK.exe
echo ============================================
echo.
echo Este script se ejecuta en Windows, con Python instalado,
echo y con tablonk.py en esta misma carpeta.
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] No se encontro Python en el PATH.
    echo Instala Python desde https://www.python.org/downloads/
    echo marcando la casilla "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)

if not exist "tablonk.py" (
    echo [ERROR] No encuentro tablonk.py en esta carpeta.
    echo Copia este .bat junto al script y vuelve a intentarlo.
    pause
    exit /b 1
)

echo Instalando/actualizando PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [ERROR] Fallo al instalar PyInstaller.
    pause
    exit /b 1
)

echo.
echo Compilando el .exe (puede tardar un minuto)...
python -m PyInstaller --onefile --windowed --name "TablonK" tablonk.py
rem Si tienes un icono .ico propio, anade a la linea de arriba:  --icon "mi_icono.ico"

if errorlevel 1 (
    echo.
    echo [ERROR] Algo fallo durante la compilacion. Revisa los mensajes de arriba.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Listo! El ejecutable esta en:
echo   dist\TablonK.exe
echo ============================================
echo.
echo Esa es la unica carpeta/archivo que necesitas compartir.
echo Las carpetas "build" y el archivo TablonK.spec se pueden
echo borrar despues: no hacen falta para repartir el programa.
echo.
pause

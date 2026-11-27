@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo    TablonK Advance - Compilar ejecutable
echo ============================================
echo.
echo Se genera TablonKAdvance.exe en esta carpeta.
echo Usa el mismo config.json, assets\ y proyectos que TablonK.
echo.

where py >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python 3 no esta instalado en el PATH.
        echo Instala Python desde https://www.python.org/downloads/
        pause
        exit /b 1
    )
    set "PY=python"
)

for %%F in (tablonk.py whiteboard.py calendar_view.py events_view.py event_detail.py event_dialogs.py events_store.py rich_notes.py project_files.py icons.py ui_common.py updater.py settings_view.py version.py tablonk.ico) do (
    if not exist "%%F" (
        echo ERROR: falta %%F
        pause
        exit /b 1
    )
)

echo Instalando librerias para imagenes y para generar el exe...
%PY% -m pip install --upgrade "Pillow>=10" "pyinstaller>=6"
if errorlevel 1 (
    echo ERROR: no se pudieron instalar las dependencias.
    pause
    exit /b 1
)

echo.
echo Compilando ejecutable Windows...
%PY% -m PyInstaller --onefile --windowed --clean --noconfirm --name "TablonKAdvance" --icon "tablonk.ico" --add-data "tablonk.ico;." --distpath "." --collect-submodules PIL "tablonk.py"
if errorlevel 1 (
    echo ERROR: la compilacion ha fallado.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   EXITO: TablonKAdvance.exe (en esta carpeta)
echo ============================================
echo Puedes borrar el antiguo TablonK.exe: tus datos siguen en config.json.
echo.
pause

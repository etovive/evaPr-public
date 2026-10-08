@echo off
echo === Configurando acceso directo de eduCAd (evaPr) ===

set "APP_DIR=%~dp0"
set "SHORTCUT_NAME=evaPr.lnk"
set "DESKTOP_DIR=%USERPROFILE%\Desktop"
set "BINARY=%APP_DIR%dist\evaPr.exe"

REM Usa "python -m pip" en vez de "pip" a secas: el comando "pip" puede no estar
REM en el PATH o apuntar a otro Python distinto del que ejecuta "python".

if exist "%BINARY%" (
    echo [1/2] Modo instalador: usando el ejecutable ya compilado.
    set "TARGET_PATH=%BINARY%"
    set "WORKING_DIR=%APP_DIR%dist"
    set "ICON_PATH=%APP_DIR%dist\logo-evaPr.ico"
    goto :shortcut
)

echo [1/2] No hay ejecutable compilado: se usara el codigo fuente.
echo        (para compilarlo, ejecuta build_installer.bat)

python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Falta tkinter en este Python. Reinstala Python desde python.org
    echo        marcando "tcl/tk and IDLE" durante la instalacion.
    pause
    exit /b 1
)

python -c "import cairosvg, PIL, reportlab, pypdf, ezdxf, svgpathtools" >nul 2>&1
if errorlevel 1 (
    echo [AVISO] Faltan dependencias. Intentando instalarlas...
    python -m pip install -r "%APP_DIR%requirements.txt"
    if errorlevel 1 (
        echo.
        echo [ERROR] No se pudieron instalar las dependencias.
        echo        Si tu Python esta protegido, prueba con:
        echo          python -m pip install --user -r "%APP_DIR%requirements.txt"
        echo        o crea un entorno virtual:
        echo          python -m venv .venv
        echo          .venv\Scripts\pip install -r "%APP_DIR%requirements.txt"
        pause
        exit /b 1
    )
)

REM Lanzador .cmd: ejecuta el codigo fuente con el Python del sistema.
set "LAUNCHER=%APP_DIR%launcher\evaPr.cmd"
if not exist "%APP_DIR%launcher" mkdir "%APP_DIR%launcher"
> "%LAUNCHER%" echo @echo off
>> "%LAUNCHER%" echo cd /d "%APP_DIR:~0,-1%"
>> "%LAUNCHER%" echo python "%APP_DIR%evaPr.py" %%*
set "TARGET_PATH=%LAUNCHER%"
set "WORKING_DIR=%APP_DIR:~0,-1%"
set "ICON_PATH=%APP_DIR%logo-evaPr.ico"

:shortcut
echo.
echo [2/2] Creando acceso directo en el escritorio...

powershell -Command "$WShell = New-Object -ComObject WScript.Shell; $Shortcut = $WShell.CreateShortcut('%DESKTOP_DIR%\%SHORTCUT_NAME%'); $Shortcut.TargetPath = '%TARGET_PATH%'; $Shortcut.WorkingDirectory = '%WORKING_DIR%'; $Shortcut.IconLocation = '%ICON_PATH%'; $Shortcut.Save()"

if not exist "%DESKTOP_DIR%\%SHORTCUT_NAME%" (
    echo [ERROR] No se pudo crear el acceso directo.
    pause
    exit /b 1
)

echo.
echo === Listo ===
echo Se creo el acceso directo "evaPr" en tu escritorio.
pause
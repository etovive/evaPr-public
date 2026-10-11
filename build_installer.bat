@echo off
REM ============================================================================
REM  evaPr (eduCAd) - Build del instalador de Windows
REM ============================================================================
REM  1. Compila evaPr.exe con PyInstaller (evaPr_win.spec) en dist\
REM  2. Genera el instalador NSIS (installer.nsi) en dist_installer\
REM  3. INSTALA evaPr automaticamente en este equipo (accesos directos +
REM     entrada en "Programas"), sin ningun paso manual adicional.
REM
REM  Requisitos:
REM    - Python 3.10 o superior
REM    - NSIS 3.x con "makensis" en el PATH
REM
REM  Usa requirements.txt. El resultado (dist_installer\evaPr-Setup-*.exe)
REM  es el unico archivo que hay que repartir: instala la app sin necesitar
REM  Python.
REM
REM  Uso: doble clic en build_installer.bat
REM ============================================================================

setlocal enabledelayedexpansion
chcp 65001 >nul

set "APP_DIR=%~dp0"
set "STAGE=%APP_DIR%dist"
REM Modo ONEDIR: PyInstaller deja la app en dist\evaPr\ (exe + _internal + svgs + config)
set "APP_STAGE=%STAGE%\evaPr"
set "OUTDIR=%APP_DIR%dist_installer"
set "SPEC=%APP_DIR%evaPr_win.spec"

cd /d "%APP_DIR%"

echo ===========================================================
echo   evaPr - Compilacion del instalador de Windows
echo ===========================================================
echo.

REM --- 0. Comprobaciones previas ---------------------------------------------
REM Busca Python de varias formas: el lanzador "py", "python" y "python3".
set "PY="
where py      >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python  >nul 2>&1 && set "PY=python" )
if not defined PY ( where python3 >nul 2>&1 && set "PY=python3" )
if not defined PY (
    echo [ERROR] No se encontro Python en el PATH ^(ni "py", ni "python", ni "python3"^).
    echo         Instala Python 3.10+ desde https://www.python.org/downloads/
    echo         y marca "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)
echo [INFO] Python: %PY%

REM Pillow, cairosvg y ezdxf ya no soportan Python 3.9: compilar con 3.9 falla
REM con errores de "no matching distribution".
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Se necesita Python 3.10 o superior.
    pause
    exit /b 1
)

REM Se usa requirements.txt (el unico archivo de dependencias).
if not exist "%APP_DIR%requirements.txt" (
    echo [ERROR] No se encontro requirements.txt.
    pause
    exit /b 1
)

%PY% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [AVISO] PyInstaller no esta instalado. Instalando dependencias...
    %PY% -m pip install -r "%APP_DIR%requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Fallo la instalacion de dependencias.
        pause
        exit /b 1
    )
)

REM --- NSIS: localizar o INSTALAR automaticamente (sin intervencion) ---
REM  1) En el PATH.  2) En las carpetas de instalacion habituales.
REM  3) Si falta, se instala en silencio con winget (Windows 10/11).
REM Se usa goto (no bloques con parentesis) para evitar problemas al expandir
REM "%ProgramFiles(x86)%", que ya lleva parentesis.
set "MAKENSIS="
where makensis >nul 2>&1 && set "MAKENSIS=makensis"
if not defined MAKENSIS if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set "MAKENSIS=%ProgramFiles(x86)%\NSIS\makensis.exe"
if not defined MAKENSIS if exist "%ProgramFiles%\NSIS\makensis.exe" set "MAKENSIS=%ProgramFiles%\NSIS\makensis.exe"
if defined MAKENSIS goto :nsis_ok

echo [AVISO] NSIS no esta instalado. Instalando automaticamente con winget...
where winget >nul 2>&1 || goto :nsis_manual
winget install --id NSIS.NSIS -e --silent --accept-package-agreements --accept-source-agreements

REM Tras instalar, volver a buscar: la sesion actual no recarga el PATH.
set "MAKENSIS="
where makensis >nul 2>&1 && set "MAKENSIS=makensis"
if not defined MAKENSIS if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set "MAKENSIS=%ProgramFiles(x86)%\NSIS\makensis.exe"
if not defined MAKENSIS if exist "%ProgramFiles%\NSIS\makensis.exe" set "MAKENSIS=%ProgramFiles%\NSIS\makensis.exe"
if defined MAKENSIS goto :nsis_ok

:nsis_manual
echo [ERROR] No se pudo instalar NSIS automaticamente.
echo         Instala NSIS 3.x desde https://nsis.sourceforge.io/Main.html
pause
exit /b 1

:nsis_ok
echo [INFO] NSIS: %MAKENSIS%

REM --- 1. Version de la app (leida de config/settings.py) --------------------
set "APP_VER="
for /f "tokens=2 delims== " %%v in ('findstr /b /c:"APP_VERSION =" "%APP_DIR%config\settings.py"') do set "APP_VER=%%~v"
if not defined APP_VER set "APP_VER=0.700.1.2"

echo [INFO] Version detectada: %APP_VER%
echo.

REM --- 2. Limpieza del area de compilacion ----------------------------------
echo [1/5] Limpiando compilaciones anteriores...
if exist "%STAGE%"  rmdir /s /q "%STAGE%"
if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
mkdir "%STAGE%"
mkdir "%OUTDIR%"
echo.

REM --- 3. PyInstaller --------------------------------------------------------
echo [2/5] Compilando evaPr.exe con PyInstaller...
%PY% -m PyInstaller "%SPEC%" --noconfirm --distpath "%STAGE%" --workpath "%APP_DIR%build\evaPr_win"

if not exist "%APP_STAGE%\evaPr.exe" (
    echo.
    echo [ERROR] PyInstaller no genero evaPr.exe en %APP_STAGE%. Revisa los mensajes anteriores.
    pause
    exit /b 1
)

REM El spec deja svgs\ y config\ junto al .exe; quitamos la cache de PNG que
REM el renderizador de SVG genera al usar el programa (se regenera sola).
if exist "%APP_STAGE%\svgs" (
    for /d %%d in ("%APP_STAGE%\svgs\*") do (
        if exist "%%~fd\.cache" rmdir /s /q "%%~fd\.cache"
    )
    if exist "%APP_STAGE%\svgs\.cache" rmdir /s /q "%APP_STAGE%\svgs\.cache"
)

REM El .ico y el .png deben estar junto al .exe (accesos directos e iconos)
if not exist "%APP_STAGE%\logo-evaPr.ico" (
    echo [AVISO] Copiando logo-evaPr.ico desde la raiz del proyecto...
    copy /y "%APP_DIR%logo-evaPr.ico" "%APP_STAGE%\logo-evaPr.ico" >nul
)
if not exist "%APP_STAGE%\logo-evaPr.png" (
    echo [AVISO] Copiando logo-evaPr.png desde la raiz del proyecto...
    copy /y "%APP_DIR%logo-evaPr.png" "%APP_STAGE%\logo-evaPr.png" >nul
)
if not exist "%APP_STAGE%\config\medidas.json" (
    echo.
    echo [ERROR] No se encontro config\medidas.json en %APP_STAGE%. Revisa evaPr_win.spec.
    pause
    exit /b 1
)

REM Cairo: cairosvg carga libcairo-2.dll en tiempo de ejecucion y PyInstaller no
REM la empaqueta. Este paso copia la DLL y toda su cadena de dependencias junto
REM al ejecutable, de modo que el instalador sea "full" y funcione en equipos
REM SIN GTK ni Cairo instalados. Localiza la DLL en GTK3-Runtime, MSYS2 o PATH
REM (o la ruta indicada en CAIRO_DLL_DIR).
%PY% "%APP_DIR%bundle_cairo_dlls.py" --dest "%APP_STAGE%"
if not exist "%APP_STAGE%\libcairo-2.dll" (
    echo.
    echo [AVISO] No se encontro libcairo-2.dll en el sistema.
    echo         Los botones con SVG y la exportacion vectorial a PDF no
    echo         funcionaran en equipos sin Cairo instalado.
    echo         Instala GTK3-Runtime:
    echo           https://github.com/tschoonj/GTK-for-Windows-Runtime-Installer
    echo         y ejecuta este archivo de nuevo.
    echo.
)
echo.

REM --- 4. NSIS ---------------------------------------------------------------
echo [3/5] Generando el instalador con NSIS...

REM Tamano instalado en KB (solo cosmetico: lo muestra "Agregar o quitar programas")
set "STAGE_NT=%STAGE:~0,-1%"
set "APP_SIZE_KB=0"
for /f "usebackq delims=" %%s in (`powershell -NoProfile -Command "$t=0; foreach($f in [System.IO.Directory]::EnumerateFiles('!STAGE_NT!','*','AllDirectories')){$t+=$f.Length}; [int]($t/1KB)"`) do set "APP_SIZE_KB=%%s"

REM Modo ONEDIR: la app vive en dist\evaPr\ (exe + _internal + svgs + config),
REM por eso SRC_DIR apunta a esa carpeta.
"%MAKENSIS%" -DSRC_DIR=dist\evaPr -DAPP_VER=%APP_VER% -DAPP_SIZE_KB=%APP_SIZE_KB% -DOUT_FILE="dist_installer\evaPr-Setup-%APP_VER%.exe" "%APP_DIR%installer.nsi"

if not exist "%OUTDIR%\evaPr-Setup-%APP_VER%.exe" (
    echo.
    echo [ERROR] NSIS no genero el instalador. Revisa los mensajes anteriores.
    pause
    exit /b 1
)
echo.

REM --- 5. Instalar en este equipo (automatico) -------------------------------
REM Instala la version recien compilada SIN pedir ningun paso manual: crea la
REM carpeta, los accesos directos (Escritorio y Menu de Inicio), la entrada en
REM "Programas" (Agregar o quitar) y el desinstalador. El modo /S es silencioso.
echo [4/5] Instalando evaPr en este equipo...
start /wait "" "%OUTDIR%\evaPr-Setup-%APP_VER%.exe" /S
if errorlevel 1 (
    echo [AVISO] La instalacion automatica devolvio un codigo distinto de 0.
)
if not exist "%LOCALAPPDATA%\Programs\evaPr\evaPr.exe" (
    echo [ERROR] No se pudo instalar evaPr en "%%LOCALAPPDATA%%\Programs\evaPr".
    pause
    exit /b 1
)
echo.

REM --- 6. Resumen ------------------------------------------------------------
echo [5/5] Listo. Instalador generado E INSTALADO:
echo        Instalador: %OUTDIR%\evaPr-Setup-%APP_VER%.exe
echo        App instalada en: %LOCALAPPDATA%\Programs\evaPr
echo.
echo ===========================================================
echo   Compilacion e instalacion completadas
echo ===========================================================
echo.
echo evaPr esta instalada en:
echo    %LOCALAPPDATA%\Programs\evaPr
echo.
echo Ya tienes el acceso directo en el Escritorio y en el Menu de
echo Inicio, y la entrada en "Aplicaciones instaladas". No hace falta
echo ningun paso adicional.
echo.
echo El instalador tambien quedo en:
echo    %OUTDIR%\evaPr-Setup-%APP_VER%.exe
echo (para llevarlo a otros equipos).
echo.

pause
endlocal

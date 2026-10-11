@echo off
REM ============================================================================
REM  evaPr (eduCAd) — Build del instalador de Windows
REM ============================================================================
REM  1. Compila evaPr.exe con PyInstaller (evaPr_win.spec) en dist\
REM  2. Genera el instalador NSIS (installer.nsi) en dist_installer\
REM
REM  Requisitos:
REM    - Python 3.10 o superior
REM    - NSIS 3.x con "makensis" en el PATH
REM
REM  Usa requirements-lock.txt (versiones fijadas) para que el instalador que
REM  distribuyes sea reproducible. El resultado (dist_installer\evaPr-Setup-*.exe)
REM  es el unico archivo que hay que repartir: instala la app sin necesitar
REM  Python.
REM
REM  Uso: doble clic en build_installer.bat
REM ============================================================================

setlocal enabledelayedexpansion
chcp 65001 >nul

set "APP_DIR=%~dp0"
set "STAGE=%APP_DIR%dist"
set "OUTDIR=%APP_DIR%dist_installer"
set "SPEC=%APP_DIR%evaPr_win.spec"

cd /d "%APP_DIR%"

echo ===========================================================
echo   evaPr - Compilacion del instalador de Windows
echo ===========================================================
echo.

REM --- 0. Comprobaciones previas ---------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro "python" en el PATH.
    pause
    exit /b 1
)

REM Pillow, cairosvg y ezdxf ya no soportan Python 3.9: compilar con 3.9 falla
REM con errores de "no matching distribution".
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Se necesita Python 3.10 o superior y tienes ^(python -V^).
    pause
    exit /b 1
)

REM Para COMPILAR se usan las versiones fijadas, no los rangos de
REM requirements.txt: así el instalador que se distribuye es reproducible.
if not exist "%APP_DIR%requirements-lock.txt" (
    echo [ERROR] No se encontro requirements-lock.txt.
    pause
    exit /b 1
)

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [AVISO] PyInstaller no esta instalado. Instalando versiones fijadas...
    python -m pip install -r "%APP_DIR%requirements-lock.txt"
    if errorlevel 1 (
        echo [ERROR] Fallo la instalacion de dependencias.
        pause
        exit /b 1
    )
)

where makensis >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro "makensis" en el PATH.
    echo         Instala NSIS 3.x desde https://nsis.sourceforge.io/Main.html
    echo         y vuelve a ejecutar este archivo.
    pause
    exit /b 1
)

REM --- 1. Version de la app (leida de config/settings.py) --------------------
set "APP_VER="
for /f "tokens=2 delims==" %%v in ('findstr /b /c:"APP_VERSION =" "%APP_DIR%config\settings.py"') do set "APP_VER=%%~v"
if not defined APP_VER set "APP_VER=0.700.1.2"

echo [INFO] Version detectada: %APP_VER%
echo.

REM --- 2. Limpieza del area de compilacion ----------------------------------
echo [1/4] Limpiando compilaciones anteriores...
if exist "%STAGE%"  rmdir /s /q "%STAGE%"
if exist "%OUTDIR%" rmdir /s /q "%OUTDIR%"
mkdir "%STAGE%"
mkdir "%OUTDIR%"
echo.

REM --- 3. PyInstaller --------------------------------------------------------
echo [2/4] Compilando evaPr.exe con PyInstaller...
python -m PyInstaller "%SPEC%" --noconfirm --distpath "%STAGE%" --workpath "%APP_DIR%build\evaPr_win"

if not exist "%STAGE%\evaPr.exe" (
    echo.
    echo [ERROR] PyInstaller no genero evaPr.exe. Revisa los mensajes anteriores.
    pause
    exit /b 1
)

REM El spec deja svgs\ y config\ junto al .exe; quitamos la cache de PNG que
REM el renderizador de SVG genera al usar el programa (se regenera sola).
if exist "%STAGE%\svgs" (
    for /d %%d in ("%STAGE%\svgs\*") do (
        if exist "%%~fd\.cache" rmdir /s /q "%%~fd\.cache"
    )
    if exist "%STAGE%\svgs\.cache" rmdir /s /q "%STAGE%\svgs\.cache"
)

REM El .ico y el .png deben estar junto al .exe (accesos directos e iconos)
if not exist "%STAGE%\logo-evaPr.ico" (
    echo [AVISO] Copiando logo-evaPr.ico desde la raiz del proyecto...
    copy /y "%APP_DIR%logo-evaPr.ico" "%STAGE%\logo-evaPr.ico" >nul
)
if not exist "%STAGE%\logo-evaPr.png" (
    echo [AVISO] Copiando logo-evaPr.png desde la raiz del proyecto...
    copy /y "%APP_DIR%logo-evaPr.png" "%STAGE%\logo-evaPr.png" >nul
)
if not exist "%STAGE%\config\medidas.json" (
    echo.
    echo [ERROR] No se encontro config\medidas.json en %STAGE%. Revisa evaPr_win.spec.
    pause
    exit /b 1
)

if not exist "%STAGE%\libcairo-2.dll" (
    echo.
    echo [AVISO] No hay libcairo-2.dll en la carpeta de compilacion.
    echo         cairosvg la carga en tiempo de ejecucion y PyInstaller no la
    echo         empaqueta. Si el equipo donde se prueba el instalador no tiene
    echo         Cairo en el PATH, los botones con SVG y la exportacion
    echo         vectorial a PDF no funcionaran.
    echo         Copia libcairo-2.dll ^(y sus DLL dependientes\) en
    echo         "%STAGE%" y ejecuta este archivo de nuevo.
    echo.
)
echo.

REM --- 4. NSIS ---------------------------------------------------------------
echo [3/4] Generando el instalador con NSIS...

REM Tamano instalado en KB (solo cosmetico: lo muestra "Agregar o quitar programas")
set "STAGE_NT=%STAGE:~0,-1%"
set "APP_SIZE_KB=0"
for /f "usebackq delims=" %%s in (`powershell -NoProfile -Command "$t=0; foreach($f in [System.IO.Directory]::EnumerateFiles('!STAGE_NT!','*','AllDirectories')){$t+=$f.Length}; [int]($t/1KB)"`) do set "APP_SIZE_KB=%%s"

makensis -DSRC_DIR=dist -DAPP_VER=%APP_VER% -DAPP_SIZE_KB=%APP_SIZE_KB% -DOUT_FILE="dist_installer\evaPr-Setup-%APP_VER%.exe" "%APP_DIR%installer.nsi"

if not exist "%OUTDIR%\evaPr-Setup-%APP_VER%.exe" (
    echo.
    echo [ERROR] NSIS no genero el instalador. Revisa los mensajes anteriores.
    pause
    exit /b 1
)
echo.

REM --- 5. Resumen ------------------------------------------------------------
echo [4/4] Instalador generado:
echo        %OUTDIR%\evaPr-Setup-%APP_VER%.exe
echo.
echo ===========================================================
echo   Compilacion completada
echo ===========================================================
echo.
echo El instalador instala evaPr en:
echo    %%LOCALAPPDATA%%\Programs\evaPr
echo.
echo svgs\ y config\ se empaquetan tal cual, junto al ejecutable.
echo.

pause
endlocal

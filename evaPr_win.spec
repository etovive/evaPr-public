# -*- mode: python ; coding: utf-8 -*-
# evaPr_win.spec - Spec de PyInstaller especifico para Windows
# Usa logo-evaPr.ico para el icono del ejecutable .exe
# Las carpetas 'config' y 'svgs' se instalan JUNTO al ejecutable.
#
# Se compila en modo ONEDIR (carpeta), NO onefile. En onefile PyInstaller
# descomprime y extrae TODO (~75 MB) a %TEMP%\_MEIxxxx en CADA arranque y
# Windows Defender lo escanea, lo que hace el inicio lento (~2-3 s extra).
# En onedir el ejecutable es pequeno y carga las librerias desde _internal\
# sin extraer nada: el arranque es mucho mas rapido. El instalador NSIS ya
# instala en una carpeta, asi que onedir encaja sin problemas.
#
# Salida:  dist\evaPr\evaPr.exe  +  dist\evaPr\_internal\  +  svgs\ y config\

import shutil
import os

added_files = [
    ('logo-evaPr.png', '.'),
    ('assets/bitcoin-donation-qr.png', 'assets'),
]

a = Analysis(
    ['evaPr.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'cairosvg',
        'PIL.ImageTk',
        'PIL.Image',
        'PIL._tkinter_finder',
        'PIL._imaging',
        'PIL.ImageDraw',
        'PIL.ImageFilter',
        'reportlab',
        'reportlab.graphics',
        'reportlab.platypus',
        'reportlab.lib.pagesizes',
        'pypdf',
        'ezdxf',
        'svgpathtools',
    ],
    hookspath=[],
    hooksconfig={},
    # Permite que libcairo-2.dll (cairosvg) se cargue desde la carpeta del .exe
    runtime_hooks=['pyi_dll_path.py'],
    # La app es Tkinter puro: no usa Qt. PySide6/PyQt5/PyQt6 pueden estar
    # instalados en la maquina que compila y PyInstaller ABORTA al detectar dos
    # bindings de Qt ("attempt to collect multiple Qt bindings packages").
    # NO excluir nada de la stdlib: ezdxf importa 'unittest' en tiempo de
    # ejecucion y excluirlo rompe la exportacion a DXF.
    excludes=[
        'PySide6', 'PyQt5', 'PyQt6', 'shiboken6',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, compress=9)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='evaPr',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,           # Strip puede romper binarios en Windows
    upx=False,
    upx_exclude=[],
    console=False,         # Sin ventana de consola en Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Usar .ico para Windows (mejor soporte de iconos en Explorer y barra de tareas)
    icon='logo-evaPr.ico',
    version_file=None,
)

# El runtime (Python, librerias, .pyd, DLLs empaquetadas, datos) va a la carpeta
# "_internal" junto al .exe: la app los localiza via sys._MEIPASS.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='evaPr',
)

# --- Post-build: copiar carpetas externas junto al ejecutable ----------------
# dist/evaPr/svgs y dist/evaPr/config deben estar al lado de dist/evaPr/evaPr.exe
_dist = os.path.join(DISTPATH, 'evaPr')

for _folder in ('svgs', 'config'):
    _src = os.path.join(SPECPATH, _folder)
    _dst = os.path.join(_dist, _folder)
    if os.path.exists(_src):
        if os.path.exists(_dst):
            shutil.rmtree(_dst)
        shutil.copytree(_src, _dst)
        print(f"[post-build] Copiado: {_src} -> {_dst}")

_logo_src = os.path.join(SPECPATH, 'logo-evaPr.png')
_logo_dst = os.path.join(_dist, 'logo-evaPr.png')
if os.path.exists(_logo_src) and not os.path.exists(_logo_dst):
    shutil.copy2(_logo_src, _logo_dst)
    print(f"[post-build] Copiado: logo-evaPr.png -> {_logo_dst}")

# El .ico vive en la raiz del repo (es la fuente para el acceso directo y el
# icono de la ventana; PyInstaller ademas lo incrusta en el .exe)
_ico_src = os.path.join(SPECPATH, 'logo-evaPr.ico')
_ico_dst = os.path.join(_dist, 'logo-evaPr.ico')
if os.path.exists(_ico_src) and not os.path.exists(_ico_dst):
    shutil.copy2(_ico_src, _ico_dst)
    print(f"[post-build] Copiado: logo-evaPr.ico -> {_ico_dst}")
else:
    print(f"[post-build] AVISO: no se encontro logo-evaPr.ico en {_ico_src}")
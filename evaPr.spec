# -*- mode: python ; coding: utf-8 -*-
import shutil
import os

# Las carpetas 'config' y 'svgs' se instalan JUNTO al ejecutable, no dentro de él.
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
    runtime_hooks=[],
    # La app es Tkinter puro: no usa Qt. PySide6/PyQt5/PyQt6 llegan al entorno
    # de compilacion por otros motivos y PyInstaller ABORTA si detecta dos
    # bindings de Qt a la vez ("attempt to collect multiple Qt bindings").
    # Excluyendolos el build no depende de lo que haya instalado en la maquina.
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='evaPr',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo-evaPr.png',
)

# ─── Post-build: copiar carpetas externas junto al binario ───────────────────
# dist/svgs y dist/config deben estar al lado de dist/evaPr
_dist = os.path.join(DISTPATH, 'evaPr') if os.path.isdir(os.path.join(DISTPATH, 'evaPr')) else DISTPATH

for _folder in ('svgs', 'config'):
    _src = os.path.join(SPECPATH, _folder)
    _dst = os.path.join(_dist, _folder)
    if os.path.exists(_src):
        if os.path.exists(_dst):
            shutil.rmtree(_dst)
        shutil.copytree(_src, _dst)
        print(f"[post-build] Copiado: {_src} → {_dst}")

_logo_src = os.path.join(SPECPATH, 'logo-evaPr.png')
_logo_dst = os.path.join(_dist, 'logo-evaPr.png')
if os.path.exists(_logo_src) and not os.path.exists(_logo_dst):
    shutil.copy2(_logo_src, _logo_dst)
    print(f"[post-build] Copiado: logo-evaPr.png → {_logo_dst}")

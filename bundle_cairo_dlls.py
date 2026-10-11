#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bundle_cairo_dlls.py — empaqueta libcairo-2.dll y sus dependencias.

cairosvg usa cairocffi, que carga "libcairo-2.dll" de forma dinamica; por eso
PyInstaller NO la detecta ni la incluye. Este script localiza esa DLL en el
sistema, calcula su cadena completa de dependencias y las copia junto al
ejecutable (carpeta dist) para que el instalador las empaquete y la app
funcione en equipos SIN Cairo ni GTK instalados.

Uso:
    python bundle_cairo_dlls.py                 # copia a dist\
    python bundle_cairo_dlls.py --dest dist
    python bundle_cairo_dlls.py --cairo-dir "C:\\ruta\\con\\libcairo-2.dll"

El origen se puede forzar con --cairo-dir o con la variable CAIRO_DLL_DIR.
"""

import argparse
import os
import shutil
import sys

SYSTEM_EXTRA = {"msimg32.dll", "usp10.dll"}  # siempre presentes en Windows

# Respaldo por si 'pefile' no esta disponible: dependencias habituales de
# cairo en GTK (recopiladas de la cadena real). Puede variar entre versiones,
# por eso se prefiere el calculo automatico con pefile.
FALLBACK = [
    "libcairo-2.dll", "libpixman-1-0.dll", "libpng16-16.dll", "zlib1.dll",
    "libfontconfig-1.dll", "libfreetype-6.dll", "libexpat-1.dll",
    "libbz2-1.dll", "libbrotlicommon.dll", "libbrotlidec.dll",
    "libglib-2.0-0.dll", "libpcre-1.dll", "libintl-8.dll", "libiconv-2.dll",
    "libharfbuzz-0.dll", "libgraphite2.dll", "libgcc_s_seh-1.dll",
    "libstdc++-6.dll", "libwinpthread-1.dll",
]


def find_cairo_bin(explicit=None):
    candidates = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("CAIRO_DLL_DIR"):
        candidates.append(os.environ["CAIRO_DLL_DIR"])
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidates += [
        os.path.join(pf, "GTK3-Runtime Win64", "bin"),
        os.path.join(pfx86, "GTK3-Runtime Win32", "bin"),
        r"C:\msys64\mingw64\bin",
        r"C:\msys64\ucrt64\bin",
    ]
    candidates += os.environ.get("PATH", "").split(os.pathsep)
    for d in candidates:
        if d and os.path.isfile(os.path.join(d, "libcairo-2.dll")):
            return os.path.abspath(d)
    return None


def compute_closure(bin_dir):
    """Devuelve la lista de DLLs (nombres) de bin_dir que necesita libcairo-2.dll."""
    try:
        import pefile
    except ImportError:
        return None

    index = {e.lower(): e for e in os.listdir(bin_dir)}
    found = set()
    visited = set()

    def walk(dll):
        key = dll.lower()
        if key in visited:
            return
        visited.add(key)
        if key in SYSTEM_EXTRA:
            return
        real = index.get(key)
        if not real:
            return  # DLL del sistema (o no presente en bin_dir)
        found.add(real)
        try:
            pe = pefile.PE(os.path.join(bin_dir, real), fast_load=True)
            pe.parse_data_directories(
                directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
                if entry.dll:
                    walk(entry.dll.decode("ascii", "ignore"))
            pe.close()
        except Exception as exc:  # pragma: no cover
            print("  [aviso] no se pudo leer %s: %s" % (real, exc))

    walk("libcairo-2.dll")
    return sorted(found)


def main():
    ap = argparse.ArgumentParser(description="Empaqueta libcairo-2.dll y dependencias.")
    ap.add_argument("--dest", default="dist", help="carpeta destino (por defecto dist)")
    ap.add_argument("--cairo-dir", default=None, help="carpeta que contiene libcairo-2.dll")
    args = ap.parse_args()

    cairo_dir = find_cairo_bin(args.cairo_dir)
    if not cairo_dir:
        print("[ERROR] No se encontro libcairo-2.dll.")
        print("        Instala GTK3-Runtime (https://github.com/tschoonj/GTK-for-Windows-Runtime-Installer)")
        print("        o pasa --cairo-dir / define CAIRO_DLL_DIR.")
        return 1

    names = compute_closure(cairo_dir)
    if names is None:
        print("[AVISO] 'pefile' no esta instalado; usando lista de respaldo.")
        names = [n for n in FALLBACK if os.path.isfile(os.path.join(cairo_dir, n))]

    os.makedirs(args.dest, exist_ok=True)
    copied = 0
    for name in names:
        src = os.path.join(cairo_dir, name)
        if not os.path.isfile(src):
            print("  [aviso] falta %s en %s" % (name, cairo_dir))
            continue
        shutil.copy2(src, os.path.join(args.dest, name))
        copied += 1

    print("[INFO] Cairo empaquetado: %d DLLs desde %s -> %s" % (copied, cairo_dir, args.dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())

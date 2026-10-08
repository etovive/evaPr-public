"""
Runtime hook de PyInstaller (Windows).

cairosvg -> cairocffi carga "libcairo-2.dll" de forma dinámica, por lo que
PyInstaller no la empaqueta sola (y en un equipo limpio la app se quedaría sin
botones ni exportación vectorial a PDF).

Este hook se ejecuta ANTES que el script principal y añade la carpeta del
ejecutable al orden de búsqueda de DLL, de modo que baste con dejar
libcairo-2.dll (y sus dependencias) junto a evaPr.exe.

No tiene efecto si la aplicación no está empaquetada o si la DLL ya está
disponible por el PATH del sistema.
"""

import os
import sys

def _add_dll_dirs():
    if not getattr(sys, "frozen", False):
        return
    if not hasattr(os, "add_dll_directory"):  # solo existe en Windows
        return

    candidates = [os.path.dirname(os.path.realpath(sys.executable))]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(meipass)

    handles = []
    for path in candidates:
        if not path or not os.path.isdir(path):
            continue
        try:
            handles.append(os.add_dll_directory(path))
        except OSError:
            pass

    # Los handles deben seguir vivos: si se recolectan, la ruta se descarta.
    sys._evaPr_dll_dirs = handles

_add_dll_dirs()

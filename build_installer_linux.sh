#!/usr/bin/env bash
# =============================================================================
#  evaPr (eduCAd) — Compilación del instalador de Windows desde Linux
# =============================================================================
#  NSIS es cross-compiler: makensis genera un instalador .exe para Windows
#  compilándolo en Linux. Lo único que NO se puede hacer aquí es el ejecutable
#  (PyInstaller no hace cross-compile).
#
#  Uso:
#    1) En Windows:  python -m PyInstaller evaPr_win.spec --noconfirm ^
#                      --distpath dist --workpath build\evaPr_win
#       (o ejecutar build_installer.bat, que además genera el instalador)
#    2) Copiar esa carpeta dist\ a este repositorio.
#    3) Aquí:       ./build_installer_linux.sh
#
#  Requisitos: makensis  (en Arch/CachyOS: sudo pacman -S nsis)
# =============================================================================

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

STAGE="dist"
OUTDIR="dist_installer"

echo "==========================================================="
echo "  evaPr - Compilacion del instalador (NSIS sobre Linux)"
echo "==========================================================="
echo

# --- 0. Comprobaciones -------------------------------------------------------
command -v makensis >/dev/null 2>&1 || {
    echo "[ERROR] No se encontro 'makensis' en el PATH."
    echo "        Arch/CachyOS: sudo pacman -S nsis"
    echo "        Ubuntu/Debian: sudo apt install nsis"
    echo "        Fedora:        sudo dnf install nsis"
    exit 1
}

[ -d "$STAGE" ] || {
    echo "[ERROR] No existe $STAGE/."
    echo "        Compila primero evaPr.exe en Windows y copia esa carpeta aqui."
    exit 1
}

[ -f "$STAGE/evaPr.exe" ] || {
    echo "[ERROR] No se encontro $STAGE/evaPr.exe."
    echo "        Compila primero evaPr.exe en Windows y copia esa carpeta aqui."
    exit 1
}

# PyInstaller no hace cross-compile: si el .exe no es PE, el instalador
# arrancaria con un binario que Windows no puede ejecutar.
if ! file -b "$STAGE/evaPr.exe" | grep -qi "PE32"; then
    echo "[ERROR] $STAGE/evaPr.exe no es un ejecutable de Windows:"
    file -b "$STAGE/evaPr.exe"
    exit 1
fi

for req in "logo-evaPr.ico" "logo-evaPr.png" "config/medidas.json"; do
    [ -f "$STAGE/$req" ] || { echo "[ERROR] Falta $STAGE/$req"; exit 1; }
done
[ -d "$STAGE/svgs" ] || { echo "[ERROR] Falta $STAGE/svgs/"; exit 1; }

# --- 1. Datos de compilación -------------------------------------------------
APP_VER="$(sed -n 's/^APP_VERSION = "\(.*\)"$/\1/p' config/settings.py | head -1)"
APP_VER="${APP_VER:-0.700}"

# --- 2. Limpieza de cachés ---------------------------------------------------
# El renderizador de SVG guarda PNG dentro de svgs/; no deben ir en el instalador.
find "$STAGE/svgs" -type d -name ".cache" -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true

# El tamaño se mide DESPUÉS de limpiar la caché: si no, "Agregar o quitar
# programas" muestra un tamaño mayor del que ocupa realmente.
APP_SIZE_KB="$(du -sk "$STAGE" | cut -f1)"

echo "[INFO] Version:      $APP_VER"
echo "[INFO] Payload:      $STAGE ($(du -sh "$STAGE" | cut -f1))"
echo "[INFO] svgs:         $(find "$STAGE/svgs" -type f | wc -l) archivos"
echo

# --- 3. Compilación ----------------------------------------------------------
mkdir -p "$OUTDIR"
OUT_FILE="$OUTDIR/evaPr-Setup-$APP_VER.exe"

echo "[1/2] Compilando con makensis..."
makensis \
    -DSRC_DIR="$STAGE" \
    -DAPP_VER="$APP_VER" \
    -DAPP_SIZE_KB="$APP_SIZE_KB" \
    -DOUT_FILE="$OUT_FILE" \
    installer.nsi

[ -f "$OUT_FILE" ] || { echo "[ERROR] makensis no genero $OUT_FILE"; exit 1; }

echo
echo "[2/2] Instalador generado:"
echo "       $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"
echo
echo "==========================================================="
echo "  Listo. El instalador instala en %LOCALAPPDATA%\Programs\evaPr"
echo "==========================================================="

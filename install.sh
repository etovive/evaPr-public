#!/bin/bash
# =============================================================================
#  evaPr (eduCAd) — Instalador para Linux
# =============================================================================
#  Uso:
#     ./install.sh              instala (idempotente, se puede repetir)
#     ./install.sh --uninstall  desinstala
#     ./install.sh --build      fuerza recompilar el ejecutable con PyInstaller
#
#  No hace falta ningún paso previo: el script instala las librerías del
#  sistema que falten (tkinter y libcairo), las dependencias de Python, crea
#  un acceso directo en el menú y un comando `evaPr` en ~/.local/bin.
#
#  Si el repositorio trae un ejecutable ya compilado en dist/evaPr, se usa ese
#  en lugar del código fuente y no hace falta ningún entorno virtual.
#
#  Requisitos mínimos: Python 3.10 o superior.
# =============================================================================

set -e

GREEN='\033[0;32m'; BLUE='\033[0;34m'; RED='\033[0;31m'
YELLOW='\033[1;33m';   NC='\033[0m'

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/evaPr"
BIN_DIR="$HOME/.local/bin"
ICON_DIR="$HOME/.local/share/icons"
APP_MENU_DIR="$HOME/.local/share/applications"
VENV_DIR="$INSTALL_DIR/venv"
BINARY_SRC="$APP_DIR/dist/evaPr"

say()  { echo -e "$1"; }
ok()   { echo -e "${GREEN}$1${NC}"; }
warn() { echo -e "${YELLOW}$1${NC}"; }
err()  { echo -e "${RED}$1${NC}"; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- 0. Desinstalación --------------------------------------------------------
if [ "${1:-}" = "--uninstall" ]; then
    echo
    say "Desinstalando eduCAd (evaPr)..."
    rm -rf  "$INSTALL_DIR"
    rm -f   "$BIN_DIR/evaPr"
    rm -f   "$APP_MENU_DIR/evaPr.desktop"
    rm -f   "$ICON_DIR/evaPr.png"
    have update-desktop-database && update-desktop-database "$APP_MENU_DIR" 2>/dev/null || true
    ok "Desinstalado. Tus proyectos (.ecad) no se han tocado."
    exit 0
fi

FORCE_BUILD=0
[ "${1:-}" = "--build" ] && FORCE_BUILD=1

echo
say "${BLUE}=== Instalador de eduCAd (evaPr) ===${NC}"
echo

# --- 1. Comprobaciones básicas ------------------------------------------------
if ! have python3; then
    err "[ERROR] No se encontró python3 en el sistema."
    echo "  Ubuntu/Debian: sudo apt install python3"
    echo "  Fedora:        sudo dnf install python3"
    echo "  Arch:          sudo pacman -S python"
    exit 1
fi

PY_OK="$(python3 -c 'import sys; print(1 if sys.version_info >= (3,10) else 0)')"
if [ "$PY_OK" != "1" ]; then
    err "[ERROR] Se necesita Python 3.10 o superior y tienes $(python3 -V 2>&1)."
    echo "  Ubuntu/Debian: sudo apt install python3.10"
    echo "  Arch:          sudo pacman -S python310"
    exit 1
fi
ok "Python $(python3 -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"

# --- 2. Instalador de paquetes del sistema -----------------------------------
# Solo hace falta para librerías que Python no trae: tkinter y libcairo.
# El resto de dependencias van por pip (paso 4).
SUDO=""
if [ "$(id -u)" != "0" ]; then
    have sudo && SUDO="sudo"
fi

pkg_install() {
    # $1 = lista de paquetes para el gestor detectado
    if [ -z "$SUDO" ]; then
        return 1
    fi
    if have apt-get; then
        $SUDO apt-get update -qq >/dev/null 2>&1 || true
        $SUDO apt-get install -y -qq $1 >/dev/null 2>&1
    elif have dnf; then
        $SUDO dnf install -y -q $1 >/dev/null 2>&1
    elif have pacman; then
        $SUDO pacman -S --needed --noconfirm $1 >/dev/null 2>&1
    elif have zypper; then
        $SUDO zypper install -y -q $1 >/dev/null 2>&1
    elif have apk; then
        $SUDO apk add --no-cache $1 >/dev/null 2>&1
    else
        return 1
    fi
}

# Detecta el gestor y devuelve los nombres de paquete para [tkinter] [cairo]
pkg_names() {
    if have apt-get; then echo "python3-tk libcairo2"
    elif have dnf; then    echo "python3-tkinter cairo"
    elif have pacman; then echo "tk cairo"
    elif have zypper; then echo "python3-tk libcairo2"
    elif have apk; then    echo "python3-tk cairo"
    else echo ""; fi
}

NEED=""
if ! python3 -c "import tkinter" >/dev/null 2>&1; then NEED="$NEED tkinter"; fi
if ! python3 -c "import ctypes.util,sys; sys.exit(0 if ctypes.util.find_library('cairo') else 1)" >/dev/null 2>&1; then
    NEED="$NEED libcairo"
fi

if [ -n "$NEED" ]; then
    warn "Faltan librerías del sistema:$NEED"
    NAMES="$(pkg_names)"
    if [ -n "$NAMES" ] && pkg_install "$NAMES"; then
        ok "Librerías del sistema instaladas."
    elif [ -z "$SUDO" ]; then
        warn "No hay sudo, no se pueden instalar automáticamente. Instálalas tú con:"
        echo "    $NAMES"
    else
        warn "No se pudieron instalar automáticamente. Instálalas tú con:"
        echo "    $NAMES"
    fi
else
    ok "Librerías del sistema (tkinter, libcairo) presentes."
fi

# El intérprete base debe poder crear entornos virtuales (Debian lo separa).
if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c "import ensurepip" >/dev/null 2>&1; then
    warn "Falta el soporte de entornos virtuales de Python."
    VPKG="python3-venv"
    have pacman && VPKG="python"
    pkg_install "$VPKG" || warn "No se pudo instalar automáticamente: sudo apt install $VPKG"
fi

# --- 3. Decidir cómo ejecutar la app -----------------------------------------
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$ICON_DIR" "$APP_MENU_DIR"
USE_BINARY=0

if [ "$FORCE_BUILD" = "1" ]; then
    warn "Compilando el ejecutable con PyInstaller (puede tardar varios minutos)..."
    # El build usa un entorno AISLADO en ~/.cache. Si compila con el Python del
    # sistema, el ejecutable arrastra todo lo que haya instalado en la maquina
    # (en una prueba: 23 MB de scipy y 6 de matplotlib, que no son dependencia),
    # PyInstaller aborta si encuentra dos bindings de Qt, y el resultado no es
    # reproducible. El venv queda FUERA del repositorio.
    BUILD_VENV="${XDG_CACHE_HOME:-$HOME/.cache}/evaPr/build-venv"
    mkdir -p "$(dirname "$BUILD_VENV")"
    if [ ! -x "$BUILD_VENV/bin/python" ]; then
        say "Creando entorno de compilación aislado..."
        python3 -m venv "$BUILD_VENV" || {
            err "[ERROR] No se pudo crear el entorno de compilación."
            exit 1
        }
    fi
    "$BUILD_VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    "$BUILD_VENV/bin/python" -m pip install --quiet -r "$APP_DIR/requirements.txt" || {
        err "[ERROR] No se pudieron instalar las dependencias de compilación."
        exit 1
    }
    ( cd "$APP_DIR" && "$BUILD_VENV/bin/python" -m PyInstaller evaPr.spec --noconfirm ) || {
        err "[ERROR] La compilación falló."; exit 1; }
    [ -f "$BINARY_SRC" ] || { err "[ERROR] No se generó $BINARY_SRC"; exit 1; }
    USE_BINARY=1
    ok "Compilación completada ($(du -h "$BINARY_SRC" | cut -f1))."
elif [ -f "$BINARY_SRC" ] && [ ! "$APP_DIR/evaPr.py" -nt "$BINARY_SRC" ]; then
    USE_BINARY=1
    ok "Se usa el ejecutable compilado (dist/evaPr)."
elif [ -f "$BINARY_SRC" ]; then
    warn "El código fuente es más nuevo que el ejecutable; se instala desde fuente."
    warn "  Para recompilar: ./install.sh --build"
else
    warn "No hay ejecutable compilado; se instala desde el código fuente."
fi

# --- 4. Dependencias de Python + lanzador ------------------------------------
if [ "$USE_BINARY" = "1" ]; then
    cp "$BINARY_SRC" "$INSTALL_DIR/evaPr"
    chmod +x "$INSTALL_DIR/evaPr"
    LAUNCHER="$INSTALL_DIR/evaPr"
    ok "Ejecutable instalado."
else
    say "Preparando entorno con las dependencias de Python..."
    [ -d "$VENV_DIR" ] || python3 -m venv "$VENV_DIR" || {
        err "[ERROR] No se pudo crear el entorno virtual en $VENV_DIR"
        exit 1
    }
    "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    "$VENV_DIR/bin/python" -m pip install --quiet -r "$APP_DIR/requirements.txt" || {
        err "[ERROR] Falló la instalación de dependencias."
        exit 1
    }
    ok "Dependencias de Python instaladas."

    LAUNCHER="$INSTALL_DIR/evaPr"
    cat > "$LAUNCHER" <<EOF
#!/bin/bash
cd "$APP_DIR"
exec "$VENV_DIR/bin/python" "$APP_DIR/evaPr.py" "\$@"
EOF
    chmod +x "$LAUNCHER"
fi

# --- 5. Recursos, comando y acceso directo ------------------------------------
if [ ! -d "$INSTALL_DIR/svgs" ]; then
    cp -r "$APP_DIR/svgs" "$INSTALL_DIR/svgs"
else
    rsync -a --update "$APP_DIR/svgs/" "$INSTALL_DIR/svgs/" 2>/dev/null || \
        cp -ru "$APP_DIR/svgs/." "$INSTALL_DIR/svgs/"
fi
if [ ! -d "$INSTALL_DIR/config" ]; then
    cp -r "$APP_DIR/config" "$INSTALL_DIR/config"
else
    # -u solo sobrescribe si el origen es más nuevo; nunca se pisa config.json,
    # que es la configuración del usuario. Se ignoran carpetas como __pycache__.
    for f in "$APP_DIR/config/"*; do
        [ -f "$f" ] || continue
        fname="$(basename "$f")"
        [ "$fname" != "config.json" ] && cp -u "$f" "$INSTALL_DIR/config/$fname"
    done
    true
fi

ln -sf "$LAUNCHER" "$BIN_DIR/evaPr"
cp "$APP_DIR/logo-evaPr.png" "$ICON_DIR/evaPr.png"
cp "$APP_DIR/logo-evaPr.png" "$INSTALL_DIR/logo-evaPr.png"

if [ "$USE_BINARY" = "1" ]; then
    DESKTOP_PATH="$INSTALL_DIR"
else
    DESKTOP_PATH="$APP_DIR"
fi

cat > "$APP_MENU_DIR/evaPr.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=eduCAd (evaPr)
Comment=Diagramador de Circuitos Eléctricos Industriales
Exec=$LAUNCHER
Icon=$ICON_DIR/evaPr.png
Terminal=false
Categories=Education;Engineering;
Keywords=circuit;electric;industry;
StartupNotify=true
Path=$DESKTOP_PATH
EOF
chmod +x "$APP_MENU_DIR/evaPr.desktop"
have update-desktop-database && update-desktop-database "$APP_MENU_DIR" 2>/dev/null || true

# --- 6. Comprobación final ----------------------------------------------------
echo
if [ "$USE_BINARY" = "1" ]; then
    ok "Instalación completada."
else
    MISSING="$("$VENV_DIR/bin/python" - <<'PYEOF'
import importlib.util
mods = ["tkinter", "cairosvg", "PIL", "reportlab", "pypdf", "ezdxf", "svgpathtools"]
missing = []
for m in mods:
    try:
        if importlib.util.find_spec(m) is None:
            missing.append(m)
    except Exception:
        missing.append(m)
print(" ".join(missing))
PYEOF
)"
    if [ -n "$MISSING" ]; then
        err "[AVISO] Faltan estos módulos: $MISSING"
        err "La aplicación puede fallar al arrancar. Reinstala con:"
        echo "    $VENV_DIR/bin/pip install -r $APP_DIR/requirements.txt"
    else
        ok "Instalación completada y verificada."
    fi
fi

echo
say "${BLUE}=== Listo ===${NC}"
echo "  Comando:     evaPr"
echo "  Menú:        eduCAd (evaPr)"
echo "  Desinstalar: $APP_DIR/install.sh --uninstall"
if [ "$USE_BINARY" != "1" ]; then
    echo "  Nota:        si mueves o borras el repositorio, vuelve a ejecutar este script."
fi
echo
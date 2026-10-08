import copy
import json
import os
import platform
import sys
from pathlib import Path
from urllib.parse import quote

# Configuración de archivos
def _get_config_path():
    """Determina la ruta del archivo de configuración según el sistema operativo."""
    if platform.system() == "Windows":
        return Path(os.getenv("APPDATA", Path.home())) / "evaPr" / "config.json"
    return Path.home() / ".config" / "evaPr" / "config.json"

CONFIG_FILE = _get_config_path()

# Recursos externos (svgs/, config/medidas.json) que viajan junto al ejecutable
def _get_app_dir():
    """Carpeta base de la aplicación. Espejo de utils.utils.get_app_dir().

    Se replica aquí para no importar utils (que arrastra tkinter) desde el
    módulo de configuración.
    """
    if getattr(sys, "frozen", False):
        return Path(os.path.realpath(sys.executable)).parent
    return Path(__file__).resolve().parent.parent

def _get_default_svg_path():
    """Ruta por defecto de la biblioteca de SVG.

    Prioriza la carpeta 'svgs' ubicada junto al ejecutable (instalador en
    Windows o repositorio en desarrollo) para que la aplicación sea portable.
    Si no existe, recurre a la carpeta del usuario.
    """
    app_svgs = _get_app_dir() / "svgs"
    if app_svgs.is_dir():
        return str(app_svgs)
    docs = "Documents" if platform.system() == "Windows" else "Documentos"
    return str(Path.home() / docs / "evaPr" / "svgs")

APP_VERSION = "0.700"
APP_VERSION_LABEL = "v0.700"

PAYPAL_DONATION_URL = "https://paypal.me/etovivePr"

# Bitcoin: dirección de recepción de la wallet (Electrum).
# Acepta los formatos P2PKH (1...), P2SH (3...) y bech32 (bc1...).
# Si queda vacía, el botón de Bitcoin se oculta en el diálogo "Acerca de".
BTC_DONATION_ADDRESS = "bc1q8w7h0qldqfz4y0vtyjd87r55lxk2c7227khm5v"

# Nota que se precarga en la wallet al abrir la URI BIP21
BTC_DONATION_MESSAGE = "Donaciones evaPr"

def get_btc_donation_uri():
    """URI BIP21 de donación: bitcoin:<direccion>?message=<nota>.

    Pegarla en Electrum abre la solicitud de pago con la nota ya escrita.
    Devuelve "" si no hay dirección configurada.
    """
    address = (BTC_DONATION_ADDRESS or "").strip()
    if not address:
        return ""
    uri = f"bitcoin:{address}"
    message = (BTC_DONATION_MESSAGE or "").strip()
    if message:
        uri += f"?message={quote(message, safe='')}"
    return uri

# Configuración por defecto
DEFAULT_CONFIG = {
    "canvas_color": "#fff9e6",
    "grid_size": 20,
    "grid_visible": True,
    # Aceptación del aviso legal (ver config/disclaimer.py). Vacío = pendiente
    "disclaimer_accepted_version": "",
    "disclaimer_accepted_date": "",
    "wire_numbering_enabled": False,
    "wire_numbering_type": "Numeración por Bloques de Motor",
    # Código de color asignado a cada conductor en el apantallamiento (IEC)
    "cable_color_map": {
        "L1": "BK",
        "L2": "RD",
        "L3": "BU",
        "N": "GY",
        "PE": "GNYE"
    },
    "work_dir": str(Path.home() / "Documents" / "Proyectos") if platform.system() == "Windows" else str(Path.home() / "Documentos" / "Proyectos"),
    "svg_path": _get_default_svg_path(),
    "pdf_template": "",
    "window_width": 1024,
    "window_height": 768,
    "auto_conexion_enabled": True,
    "proximity_preview_enabled": False,
    "invertir_deteccion": False,
    "snap_to_grid_enabled": False,
    "enable_move_connections": True,
    "guide_lines_enabled": True,  # Activar por defecto para testing
    "pdf_config": {
        "proyecto": "",
        "dibujado_por": "",
        "revisado_por": "",
        "aprobado_por": "",
        "empresa": "",
        "direccion": "",
        "escala": "1:1",
        "version": "0.700",
        "formato": "A4",  # A4 o A3
        "pdf_template": ""  # Ruta y nombre de la plantilla .pte a usar
    },
    "button_rendering": {
        "default_size": [48, 48],
        "interpolation": "LANCZOS",
        "background_color": None,
        "quality": "high"
    },
    "components": {
        "Motors": [
            {"svg": "motor-3pPE.svg", "name": "Motor 3P+PE"},
            {"svg": "motor-3p.svg", "name": "Motor 3P"},
            {"svg": "motor-1pC.svg", "name": "Motor 1P+C"},
            {"svg": "motor-1p.svg", "name": "Motor 1P"}
        ],
        "Protection": [
            {"svg": "motor-circuit-breaker-3p.svg", "name": "MCB 3P"},
            {"svg": "motor-circuit-breaker-2p.svg", "name": "MCB 2P"}
        ],
        "Connection": [
            {"svg": "fase.svg", "name": "Fase"},
            {"svg": "conxn.svg", "name": "Conexión Salida"},
            {"svg": "conxn2.svg", "name": "Conexión Entrada"},
            {"svg": "T.svg", "name": "Tierra"}
        ],
        "Drivers": [
            {"svg": "vdf-e.svg", "name": "Variador de Velocidad"}
        ],
        "Auxiliares": [
            {"svg": "light.svg", "name": "Luz"}
        ]
    }
}

# Constantes de la aplicación
class AppConstants:
    """Constantes utilizadas en la aplicación."""

    # DIMENSIONES DEL CANVAS (Formato A3 a 300 DPI)
    CANVAS_WIDTH = 3273      # Ancho A3 a 300 DPI
    CANVAS_HEIGHT = 4725     # Alto A3 a 300 DPI

    # ESCALA: Canvas A3 a 300 DPI -> 1mm = 300/25.4 px
    MM_TO_PX = 300 / 25.4  # ≈ 11.81 px por mm

    # Tolerancias y dimensiones
    CLICK_TOLERANCE = 15  # Tolerancia para selección de líneas (píxeles)
    COMPONENT_TOLERANCE = 5  # Tolerancia para puntos de componentes (píxeles)

    # Fuentes
    DEFAULT_FONT_FAMILY = "Arial"
    UI_FONT_FAMILY = "Open Sans Light" if platform.system() == "Linux" else "Segoe UI"
    MONO_FONT_FAMILY = "Courier New"

    COLORS = {
        'SELECTED': 'red',
        'HIGHLIGHTED': 'blue',
        'NORMAL': 'black',
        'POINT_SELECTED': 'green',
        'POINT_NORMAL': '#808080',
        'PREVIEW': '#87CEEB'
    }

    # Configuración de líneas por defecto
    DEFAULT_LINE_STYLE = {
        'width': 0.5,
        'color': 'black',
        'dash': ''
    }

    # Patrones de dash disponibles
    DASH_PATTERNS = {
        "": "",           # Continuo
        "(3, 3)": (3, 3), # Punteado
        "(8, 4)": (8, 4), # Cortado
        "(10, 5)": (10, 5)  # Verde PE - Tierra
    }

    # Hojas que son reportes estáticos (no editables por el usuario)
    NON_EDITABLE_SHEETS = [
        "Lista de Materiales",
        "Resumen de Gabinete",
        "Plano de Borner",
        "Prescripciones de Seguridad",
        "Tabla de Cableado"
    ]

    # Hojas que se excluyen de las referencias cruzadas (reportes + diagramas especiales)
    # NOTA: "Hoja de Gabinete 2D" es editable pero no debe llevar referencias cruzadas.
    CROSS_REF_EXCLUDED_SHEETS = NON_EDITABLE_SHEETS + ["Hoja de Gabinete 2D"]

def resolve_svg_path(config, persist=True):
    """Verifica que 'svg_path' apunte a una carpeta existente y la repara si no.

    Una instalación movida, o un config.json heredado de una versión anterior,
    dejan la ruta en blanco y la paleta de componentes aparece vacía.
    """
    configured = str(config.get("svg_path", "") or "").strip()
    if configured and Path(configured).is_dir():
        return configured

    fallback = _get_default_svg_path()
    if configured != fallback:
        config["svg_path"] = fallback
        if persist:
            save_config(config)
    return fallback

def load_config():
    """Carga la configuración desde el archivo JSON."""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)

            # Asegurar que los componentes y pdf_config existan
            if "components" not in config:
                config["components"] = copy.deepcopy(DEFAULT_CONFIG["components"])

            if "pdf_config" not in config:
                config["pdf_config"] = copy.deepcopy(DEFAULT_CONFIG["pdf_config"])

            resolve_svg_path(config)
            return config
    except (json.JSONDecodeError, FileNotFoundError):
        pass

    # Si no se puede cargar, crear archivo con configuración por defecto
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)

    return copy.deepcopy(DEFAULT_CONFIG)

def save_config(config):
    """Guarda la configuración en el archivo JSON."""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"⚠️ Error guardando configuración: {e}")
        return False

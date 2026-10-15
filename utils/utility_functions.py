import math
from config.settings import AppConstants

def is_near_segment(x, y, x1, y1, x2, y2, tolerance=None):
    """
    Verifica si un punto está cerca de un segmento de línea.

    Args:
        x, y: Coordenadas del punto
        x1, y1, x2, y2: Coordenadas del segmento
        tolerance: Tolerancia en píxeles (por defecto usa constante)

    Returns:
        bool: True si el punto está cerca del segmento
    """
    if tolerance is None:
        tolerance = AppConstants.CLICK_TOLERANCE

    distance = distance_point_to_segment(x, y, x1, y1, x2, y2)
    return distance <= tolerance

def project_point_on_segment(px, py, x1, y1, x2, y2):
    """
    Proyección de un punto sobre un segmento: distancia mínima y punto más cercano.
    Fuente única de la geometría punto-segmento (antes duplicada en evaPr,
    segment_operations y event_handlers).

    Args:
        px, py: Coordenadas del punto
        x1, y1, x2, y2: Coordenadas del segmento

    Returns:
        tuple: (distancia mínima, (closest_x, closest_y))
    """
    # Vector del segmento
    dx = x2 - x1
    dy = y2 - y1

    if dx == 0 and dy == 0:
        # El "segmento" es realmente un punto
        return math.sqrt((px - x1)**2 + (py - y1)**2), (x1, y1)

    # Proyección del punto en la línea
    t = ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)

    # Clamp t al rango [0, 1]
    t = max(0, min(1, t))

    # Punto más cercano en el segmento
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy

    # Distancia
    dist = math.sqrt((px - closest_x)**2 + (py - closest_y)**2)
    return dist, (closest_x, closest_y)

def distance_point_to_segment(px, py, x1, y1, x2, y2):
    """
    Calcula la distancia de un punto a un segmento de línea.

    Args:
        px, py: Coordenadas del punto
        x1, y1, x2, y2: Coordenadas del segmento

    Returns:
        float: Distancia mínima del punto al segmento
    """
    return project_point_on_segment(px, py, x1, y1, x2, y2)[0]

def parse_dash_pattern(dash_str):
    """
    Convierte string de patrón dash a formato tkinter.

    Args:
        dash_str: String que representa el patrón (ej: "(3, 3)" o "3,3")

    Returns:
        tuple o "": Patrón de dash para tkinter o string vacío
    """
    try:
        if not dash_str or dash_str == "":
            return ""

        # Procesar diferentes formatos posibles
        if isinstance(dash_str, str):
            # Remover paréntesis y espacios
            clean_str = dash_str.strip("()").replace(" ", "")
            if clean_str:
                # Dividir por comas y convertir a enteros
                parts = [int(x) for x in clean_str.split(",") if x.isdigit()]
                if parts:
                    return tuple(parts)
        return ""
    except:
        return ""

_DARK_COLORS = ["#0f0f23", "#1e1e1e", "#2d2d2d", "#000000", "#1a1a1a", "#333333"]

# Mapeo de colores para tema oscuro (original -> oscuro)
_COLOR_MAP_TO_DARK = {
    "black": "#ffffff",
    "#000000": "#ffffff",
    "white": "#ffffff",
    "#ffffff": "#ffffff",
    "blue": "#87CEEB",
    "#0000ff": "#87CEEB",
    "#000080": "#4169E1",
    "#0080ff": "#00BFFF",
    "#333333": "#cccccc",
    "#666666": "#999999",
    "#cccccc": "#444444",
    "#999999": "#666666",
}

# Mapeo inverso: revertir colores adaptados al modo oscuro (oscuro -> original)
_COLOR_MAP_FROM_DARK = {v: k for k, v in _COLOR_MAP_TO_DARK.items()}

def _is_dark_bg(canvas_bg):
    """Determina si un color de fondo es oscuro."""
    if not canvas_bg:
        return False
    return canvas_bg.lower() in _DARK_COLORS

def adapt_color_for_display(color, canvas_bg=None):
    """
    Adapta un color para la visualización según el modo activo.

    Args:
        color: Color original (string)
        canvas_bg: Color de fondo del canvas para detectar tema.
                   Si es None, retorna el color sin cambios (seguro por defecto).

    Returns:
        str: Color adaptado para el tema actual
    """
    if not color:
        return color

    if canvas_bg is None:
        return color

    is_dark_theme = _is_dark_bg(canvas_bg)

    if is_dark_theme:
        return _COLOR_MAP_TO_DARK.get(color, color)
    else:
        return _COLOR_MAP_FROM_DARK.get(color, color)

def _bom_name_sort_key(name):
    """Clave de orden natural para una referencia (K1 < K2 < K10)."""
    s = str(name or "")
    digits = ''.join(ch for ch in s if ch.isdigit())
    prefix = s[0] if s else ""
    try:
        number = int(digits) if digits else 0
    except ValueError:
        number = 0
    return (prefix, number, s)

def sort_bom_entries(grouped_data):
    """
    Ordena las claves de un BOM agrupado por (descripción, especificaciones)
    según las REFERENCIAS de cada grupo (no por la descripción).
    Lógica compartida entre BOMGenerator (reports.py) y PdfExporter (pdf_exporter.py).

    Args:
        grouped_data: dict { (desc, specs): [refs...] }

    Returns:
        list: claves ordenadas por la referencia natural más baja del grupo,
              con (descripción, especificaciones) como desempate.
    """
    valid_keys = [k for k in grouped_data.keys() if k[0] or k[1]]

    def _group_key(k):
        names = grouped_data.get(k) or []
        if names:
            first = min(names, key=_bom_name_sort_key)
            return (_bom_name_sort_key(first), str(k[0]), str(k[1]))
        return (("", 0, ""), str(k[0]), str(k[1]))

    return sorted(valid_keys, key=_group_key)

def sort_bom_references(names):
    """
    Ordena referencias de un BOM con orden natural (K1, K2, K10, no K1, K10, K2).

    Args:
        names: lista de referencias (str)

    Returns:
        list: nueva lista ordenada (conserva la original).
    """
    try:
        return sorted(names, key=_bom_name_sort_key)
    except Exception:
        return sorted(names)

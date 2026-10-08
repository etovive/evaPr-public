import xml.etree.ElementTree as ET
import re
from pathlib import Path
import tkinter as tk
import json
import os
import sys

def get_app_dir():
    """Retorna el directorio base externo donde reside el ejecutable y las carpetas config/svgs."""
    if getattr(sys, 'frozen', False):
        return Path(os.path.realpath(sys.executable)).parent
    else:
        return Path(__file__).parent.parent

def get_resource_dir():
    """Retorna el directorio de recursos internos (empaquetados)."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    else:
        return Path(__file__).parent.parent

# MEDIDAS POR DEFECTO (Fallback si no están en medidas.json)
DEFAULT_ENGINEERING_SPECS = {
    "BREAKER_1P": [18, 90],
    "BREAKER_2P": [36, 90],
    "BREAKER_3P": [54, 90],
    "BREAKER_4P": [72, 90],
    "FUSE_SWITCH_1P": [18, 83],
    "FUSE_SWITCH_2P": [36, 83],
    "FUSE_SWITCH_3P": [54, 83],
    "FUSE_SWITCH_4P": [72, 83],
    "BREAKER_MOLDEADO_PEQUENO": [105, 130],
    "BREAKER_MOLDEADO_GRANDE": [140, 180],
    "CONTACTOR_PEQUENO": [45, 80],
    "CONTACTOR_GRANDE": [90, 120],
    "RELE_TERMICO": [45, 85],
    "RELE_AUXILIAR": [12, 70],
    "RELE_SLIM": [6, 90],
    "PLC_CPU": [100, 100],
    "PLC_MODULO": [40, 100],
    "PLC_DVP20SX2": [70, 90],
    "PLC_DVP16SP": [25, 90],
    "FUENTE_PEQUENA": [40, 125],
    "FUENTE_GRANDE": [60, 125],
    "POWER_SUPPLY_DC": [60, 120],
    "POWER_SUPPLY_AC": [50, 60],
    "FUENTE_ALTA_POTENCIA": [85, 125],
    "VFD_PEQUENO": [70, 150],
    "VFD_GRANDE": [150, 250],
    "VFD_ALTA_POTENCIA": [180, 300],
    "PILOTO_BOTON": [30, 30],
    "SETA_EMERGENCIA": [45, 45],
    "BORNA": [6, 45],
    "TRANSFORMADOR": [85, 105],
    "PANTALLA": [90, 90],
    "DEFAULT": [40, 40],
    "BORNA_BLOCK_2F": [45, 50],
    "BORNA_BLOCK_3F": [45, 60],
    "BORNA_BLOCK_4F": [45, 90]
}

def get_svg_dimensions(svg_path):
    """
    Detecta las dimensiones reales de un archivo SVG.
    Retorna (width, height) en píxeles, o None si hay error.
    """
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()

        # Función para convertir unidades a píxeles
        def parse_dimension(value_str):
            if not value_str:
                return None

            # Remover espacios y convertir a string
            value_str = str(value_str).strip()

            # Si es un número puro, asumir píxeles
            if value_str.replace('.', '').replace('-', '').isdigit():
                return float(value_str)

            # Extraer número y unidad
            match = re.match(r'([0-9.-]+)\s*([a-zA-Z%]*)', value_str)
            if not match:
                return None

            number = float(match.group(1))
            unit = match.group(2).lower() if match.group(2) else 'px'

            # Conversión de unidades a píxeles (96 DPI estándar)
            conversion = {
                'px': 1.0,
                'pt': 96.0/72.0,  # 1 pt = 1/72 inch
                'pc': 96.0/6.0,   # 1 pc = 1/6 inch
                'mm': 96.0/25.4,  # 1 mm = 1/25.4 inch
                'cm': 96.0/2.54,  # 1 cm = 1/2.54 inch
                'in': 96.0,       # 1 inch = 96 px
                '%': 1.0          # % se maneja diferente
            }

            return number * conversion.get(unit, 1.0)

        # Intentar obtener width y height del elemento root
        width = root.get('width')
        height = root.get('height')

        if width and height:
            width_px = parse_dimension(width)
            height_px = parse_dimension(height)
            if width_px and height_px:
                return (width_px, height_px)

        # Si no hay dimensiones, buscar en viewBox
        viewbox = root.get('viewBox')
        if viewbox:
            # viewBox = "x y width height"
            vb_parts = viewbox.split()
            if len(vb_parts) == 4:
                width = float(vb_parts[2])
                height = float(vb_parts[3])
                return (width, height)

        # Fallback: buscar en elementos rect o svg children
        svg_element = root.find('.//{http://www.w3.org/2000/svg}rect')
        if svg_element is not None:
            svg_element = root.find('.//rect')  # Sin namespace

        if svg_element is not None:
            rect_width = svg_element.get('width')
            rect_height = svg_element.get('height')
            if rect_width and rect_height:
                width_px = parse_dimension(rect_width)
                height_px = parse_dimension(rect_height)
                if width_px and height_px:
                    return (width_px, height_px)

        # Fallback: usar límites razonables
        return (100, 100)

    except Exception as e:
                # Error parseando SVG {svg_path}: {e}")
        return None

def clamp_size(size, min_size=8, max_size=1024):
    """
    Limita el tamaño a un rango aceptable manteniendo proporciones.
    1024px permite que componentes grandes respeten su tamaño real del SVG.
    """
    if not size or len(size) != 2:
        return None

    width, height = size

    # Si ya está en el rango aceptable, devolverlo sin cambios
    if min_size <= width <= max_size and min_size <= height <= max_size:
        return (width, height)

    # Calcular factor de escala para que quepa en el rango
    scale_w = max_size / width if width > max_size else (min_size / width if width < min_size else 1.0)
    scale_h = max_size / height if height > max_size else (min_size / height if height < min_size else 1.0)

    # Usar el factor más restrictivo para mantener proporciones
    scale = min(scale_w, scale_h)

    new_width = max(min_size, min(max_size, int(width * scale)))
    new_height = max(min_size, min(max_size, int(height * scale)))

    return (new_width, new_height)

def get_component_real_size_static(svg_file, category, svg_path):
    """
    Función helper para detectar tamaño real de un componente SVG.
    Puede ser llamada sin instancia de aplicación.
    """
    real_size = None
    try:
        medidas = load_medidas_config()
        # 1. Prioridad: Medida específica en JSON para este archivo SVG
        especificas = medidas.get("medidas_especificas_svg", {})
        if svg_file in especificas:
            return especificas[svg_file]

        # 2. Medida real del archivo SVG si existe
        folder = category.lower() if category else ""
        full_svg_path = Path(svg_path) / folder / svg_file
        if full_svg_path.exists():
            real_size = get_svg_dimensions(full_svg_path)
            if real_size:
                return clamp_size(real_size, min_size=8, max_size=1024)
    except Exception:
        pass

    # Fallback por categoría si no se pudo detectar
    if not real_size:
        medidas = load_medidas_config()
        predeterminados = medidas.get("predeterminados_categoria_canvas", {})

        # Mapeo de categorías (Inglés -> Español para compatibilidad)
        mapeo_categorias = {
            "Motors": "Motores",
            "Protection": "Proteccion",
            "Connection": "Conexion",
            "Controllers": "Controladores",
            "Sensors": "Sensors",
            "Pilot_Lights": "Pilot_Lights"
        }

        cat_es = mapeo_categorias.get(category, category)
        real_size = predeterminados.get(cat_es, medidas.get("predeterminados_generales", {}).get("tamano_componente_canvas", [64, 64]))

    return real_size

_medidas_cache = None

def load_medidas_config():
    """Carga la configuración de medidas desde el archivo JSON centralizado.
    El resultado se cachea en memoria y se invalida al volver a ejecutar la carga.
    """
    global _medidas_cache
    if _medidas_cache is not None:
        return _medidas_cache

    config_dir = get_app_dir() / "config"
    medidas_file = config_dir / "medidas.json"

    if not medidas_file.exists():
        _medidas_cache = {
            "especificaciones_ingenieria": {"DEFAULT": [40, 40]},
            "predeterminados_categoria_canvas": {}
        }
        return _medidas_cache

    try:
        with open(medidas_file, "r", encoding="utf-8") as f:
            _medidas_cache = json.load(f)
    except Exception:
        _medidas_cache = {
            "especificaciones_ingenieria": {"DEFAULT": [40, 40]},
            "predeterminados_categoria_canvas": {}
        }
    return _medidas_cache

def get_svg_title(svg_path):
    """
    Extrae el contenido de la etiqueta <title> de un archivo SVG.
    """
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
        # Buscar la etiqueta title (puede estar en el root o hijos directos)
        # Manejar namespaces si es necesario
        ns = {'svg': 'http://www.w3.org/2000/svg'}
        title_elem = root.find('svg:title', ns)
        if title_elem is None:
            # Reintentar sin namespace
            title_elem = root.find('title')

        if title_elem is not None and title_elem.text:
            return title_elem.text.strip()
    except Exception:
        pass
    return None

def get_engineering_size(svg_file, category, label_data=None):
    """
    Retorna las dimensiones reales de ingeniería (ancho, alto) en mm.
    Lee de medidas.json y centraliza la lógica.
    """
    medidas = load_medidas_config()
    specs = medidas.get("especificaciones_ingenieria", {})

    # Función interna para obtener medida con fallback centralizado
    def get_dim(key):
        return specs.get(key, DEFAULT_ENGINEERING_SPECS.get(key, [40, 40]))

    svg = str(svg_file or "").lower()
    cat = str(category or "").lower()
    data = label_data or {}

    # Extraer info de etiquetas (Tag y Descripción) para detección inteligente
    name = str(data.get('name', '')).lower()
    desc = str(data.get('description', '')).lower()

    # Combinado para búsquedas
    search_text = f"{svg} {cat} {name} {desc}"

    # -1. Prioridad absoluta por archivo SVG (Evita falsos positivos por descripciones)
    if 'power_supply_ac' in svg: return get_dim('POWER_SUPPLY_AC')
    if 'power_supply_dc' in svg: return get_dim('POWER_SUPPLY_DC')

    # 0. Interfaz de Puerta
    if any(x in search_text for x in ['mushroom', 'emergency', 'emergencia', 'seta']):
        return get_dim('SETA_EMERGENCIA')

    if any(x in search_text for x in ['selector', 'perilla']):
        return medidas.get("predeterminados_generales", {}).get("tamano_ingenieria_mm", [32, 32])

    if any(x in search_text for x in ['pilot', 'boton', 'piloto', 'light', 'pushbutton', 'buzzer', 'sirena', 'alarma', 'switch-1p-no', 'switch-1p-nc']):
        return get_dim('PILOTO_BOTON')

    if any(x in search_text for x in ['breaker', 'disyuntor', 'protección', 'protec', 'fusible', 'fuse', 'diferencial', 'guardamotor', 'switch', 'interruptor', 'seccionador']):
        is_fuse_switch = 'fuse-switch' in svg or 'disconnector' in svg

        # 0a. Maniobra y relés que viven en categoría "Protection" pero NO son protecciones.
        # El nombre del ARCHIVO es autoritativo por encima de la categoría.
        if 'contactor' in svg:
            return get_dim('CONTACTOR_GRANDE' if 'grande' in svg else 'CONTACTOR_PEQUENO')
        if any(x in svg for x in ('rele-thermal', 'thermal-overload', 'rele-termico')):
            return get_dim('RELE_TERMICO')
        if any(x in svg or x in search_text for x in ('slim', 'rsl', 'hf41f', '34.51')):
            return get_dim('RELE_SLIM')
        if any(x in svg for x in ('rele-auxiliar', 'auxiliar', 'relay', 'contactor-auxiliar')) or 'aux' in search_text:
            return get_dim('RELE_AUXILIAR')

        # Caja moldeada: identificada por amperios >= 80
        try:
            amp = float(''.join(filter(lambda x: x.isdigit() or x == '.', str(data.get('amperios', '0')))))
        except:
            amp = 0
        if amp >= 80:
            if amp > 250:
                return get_dim('BREAKER_MOLDEADO_GRANDE')
            return get_dim('BREAKER_MOLDEADO_PEQUENO')

        # PRIORIDAD 1: Identificación explícita de polos en el NOMBRE DEL ARCHIVO
        # (autoritativo; refleja el símbolo real). El label_data['pole_count'] solo
        # se usa como respaldo, porque en versiones anteriores se persistía el conteo
        # de componentes con el mismo tag en lugar del número real de polos.
        if '1p' in svg or '1-p' in svg or svg == 'circuit-breaker-thermal-magnetic.svg':
            return get_dim('FUSE_SWITCH_1P' if is_fuse_switch else 'BREAKER_1P')

        if '2p' in svg or '2-p' in svg:
            return get_dim('FUSE_SWITCH_2P' if is_fuse_switch else 'BREAKER_2P')

        if '3p' in svg or '3-p' in svg:
            return get_dim('FUSE_SWITCH_3P' if is_fuse_switch else 'BREAKER_3P')

        if '4p' in svg or '4-p' in svg:
            return get_dim('FUSE_SWITCH_4P' if is_fuse_switch else 'BREAKER_4P')

        # Respaldos derivados (nunca deben anular el nombre del archivo)
        if 'guardamotor' in name or 'guardamotor' in cat or data.get('pole_count', 0) == 3:
            return get_dim('FUSE_SWITCH_3P' if is_fuse_switch else 'BREAKER_3P')
        if 'diferencial' in name or 'diferencial' in cat or 'diferencial' in svg or data.get('pole_count', 0) == 2:
            return get_dim('FUSE_SWITCH_2P' if is_fuse_switch else 'BREAKER_2P')
        if data.get('pole_count', 0) >= 4:
            return get_dim('FUSE_SWITCH_4P' if is_fuse_switch else 'BREAKER_4P')
        if data.get('pole_count', 0) == 1:
            return get_dim('FUSE_SWITCH_1P' if is_fuse_switch else 'BREAKER_1P')

        return get_dim('FUSE_SWITCH_1P' if is_fuse_switch else 'BREAKER_1P')

    if any(x in search_text for x in ['contactor', 'maniobra', 'rele', 'relay', 'auxiliar', 'slim', 'rsl', 'hf41f', '34.51']):
        if 'thermal' in search_text or 'térmico' in search_text:
            return get_dim('RELE_TERMICO')

        # Casos especiales: Relés Slim (RSL, HF41F, etc)
        if any(x in search_text for x in ['slim', 'rsl', 'hf41f', '34.51']):
            return get_dim('RELE_SLIM')

        if 'small' in search_text or 'aux' in search_text:
            return get_dim('RELE_AUXILIAR')
        return get_dim('CONTACTOR_PEQUENO')

    # 3. PLC y Controladores
    if any(x in search_text for x in ['plc', 'control', 'cpu', 'modbus', 'logo', 'zelio']):
        # Casos específicos Delta DVP
        if 'dvp20sx2' in search_text: return get_dim('PLC_DVP20SX2')
        if 'dvp16sp' in search_text: return get_dim('PLC_DVP16SP')

        if any(x in search_text for x in ['cpu', 'comp', 'main', 'base']):
            return get_dim('PLC_CPU')
        return get_dim('PLC_MODULO')

    # 4. Transformadores
    if 'transfo' in search_text:
        return get_dim('TRANSFORMADOR')

    # 5. Fuentes de Alimentación
    if any(x in search_text for x in ['power', 'fuente', 'supply', 'dr-']):
        if 'power_supply_ac' in svg: return get_dim('POWER_SUPPLY_AC')
        if 'dc' in search_text: return get_dim('POWER_SUPPLY_DC')
        if 'ac' in search_text: return get_dim('POWER_SUPPLY_AC')

        pot_str = str(data.get('potencia', '0')).lower()
        try:
            val = float(''.join(filter(lambda x: x.isdigit() or x == '.', pot_str)))
            if val > 480: return get_dim('FUENTE_ALTA_POTENCIA')
            return get_dim('FUENTE_GRANDE') if val > 240 else get_dim('FUENTE_PEQUENA')
        except: return get_dim('FUENTE_PEQUENA')

    if any(x in search_text for x in ['driver', 'variador', 'sst', 'soft starter', 'vfd', 'inverter']):
        pot_str = str(data.get('potencia', '0')).lower()
        try:
            val = float(''.join(filter(lambda x: x.isdigit() or x == '.', pot_str)))
            if val > 15: return get_dim('VFD_ALTA_POTENCIA')
            return get_dim('VFD_GRANDE') if val > 5.5 else get_dim('VFD_PEQUENO')
        except: return get_dim('VFD_PEQUENO')

    # 7. Visualizadores
    if any(x in cat or x in svg or x in name for x in ['lcd', 'display', 'screen', 'pantalla']):
        return get_dim('PANTALLA')

    if cat == 'block_terminal':
        try:
            bornas = int(str(data.get('bt_bornas', '1')).strip() or '1')
            filas = int(str(data.get('bt_filas', '1')).strip() or '1')
            borna_w, borna_h = get_dim('BORNA')
            return [bornas * borna_w, filas * borna_h]
        except (ValueError, TypeError):
            return get_dim('BORNA')

    # 9. Bornas individuales
    if any(x in search_text for x in ['borner', 'terminal', 'conex', 'block']):
        if 'block' in search_text:
            if '4f' in search_text or '4-f' in search_text: return get_dim('BORNA_BLOCK_4F')
            if '3f' in search_text or '3-f' in search_text: return get_dim('BORNA_BLOCK_3F')
            if '2f' in search_text or '2-f' in search_text: return get_dim('BORNA_BLOCK_2F')
        return get_dim('BORNA')

    return get_dim('DEFAULT')

class ToolTip:
    """
    Muestra un mensaje al pasar el mouse sobre un widget.
    Implementación minimalista para evitar interferencias.
    """
    def __init__(self, widget, text, condition_callback=None):
        self.widget = widget
        self.text = text
        self.condition_callback = condition_callback
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return

        # Verificar condición si existe
        if self.condition_callback and not self.condition_callback():
            return

        x, y, _cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(1)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="yellow", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()

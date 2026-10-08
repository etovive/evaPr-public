import io
from pathlib import Path
import math

# Imports necesarios desde módulos ya existentes
try:
    from PIL import Image, ImageTk
    try:
        import cairosvg
        SVG_SUPPORT = True
    except ImportError:
        SVG_SUPPORT = False
        cairosvg = None
except ImportError:
    SVG_SUPPORT = False
    Image = None
    ImageTk = None
    cairosvg = None

import re
import xml.etree.ElementTree as ET
import zlib

from models.connection_point import ConnectionPoint, serialize_connection_points, parse_connection_points
from utils.utility_functions import adapt_color_for_display, _is_dark_bg
from core.label_manager import LabelManager
from ui.label_renderer import LabelRenderer
from config.settings import AppConstants

def draw_component_points(canvas, component):
    """
    Dibuja los puntos de conexión de un componente en el canvas (tag único por componente).
    Fuente única compartida entre Component y JunctionComponent.
    """
    component_tag = f"points_{id(component)}"
    canvas.delete(component_tag)
    component.point_ids = []

    zoom = getattr(canvas, 'zoom_level', 1.0)
    for i, (x, y, point) in enumerate(component.get_connection_points_global()):
        # Mantener colores funcionales para puntos de conexión (NO adaptar)
        fill_color = "red" if point.connected else "green"
        outline_color = adapt_color_for_display("black", canvas.cget("bg"))

        point_id = canvas.create_oval(
            x * zoom - 2, y * zoom - 2,
            x * zoom + 2, y * zoom + 2,
            fill=fill_color, outline=outline_color,
            tags=component_tag
        )
        component.point_ids.append(point_id)

# ---------------------------------------------------------------------------
# CACHÉ DE RENDERIZADO SVG
#
# load_image() rasteriza el SVG con cairosvg: cada llamada cuesta entre 15 y 60 ms.
# Durante la simulación decenas de componentes cambian de estado en el MISMO tick
# (además del reset integral al detener), lo que congelaba la interfaz varios
# cientos de milisegundos: los clicks se encolaban y parecían no hacer nada.
#
# Se cachean las etapas caras, con clave derivada del ESTADO que las alimenta:
#   1. _SVG_TEXT_CACHE  (path, mtime)              -> texto crudo del archivo
#   2. _PNG_CACHE       (crc32(SVG), ancho, alto)  -> bytes PNG rasterizados
#   3. _RASTER_CACHE    clave de estado + giro      -> (image_data, photo, size)
# Si el estado vuelve a un valor ya visto (p. ej. OFF -> ON -> OFF), el render es
# prácticamente gratis. La clave incluye todo lo que leen las rutinas _apply_*
# (label_data, is_active, modo de activación, dirección del motor, posición del
# selector, fondo del canvas, mtime del archivo...), de modo que un cambio de
# estado real siempre obliga a re-renderizar.
# ---------------------------------------------------------------------------
_SVG_TEXT_CACHE = {}    # (path, mtime) -> str
_PNG_CACHE = {}         # (crc32, w, h) -> bytes
_RASTER_CACHE = {}      # clave de estado + rotación -> (image_data, photo, size)

_CACHE_LIMITS = {
    'text': 256,
    'png': 1024,
    'raster': 4096,
}


def _cache_put(cache, key, value, limit):
    """Inserta respetando el límite: si se pasa, descarta la entrada más antigua."""
    if len(cache) >= limit:
        cache.pop(next(iter(cache)))
    cache[key] = value


def _freeze_state(value):
    """Convierte cualquier valor de label_data en una clave hashable y estable."""
    if isinstance(value, dict):
        return tuple(sorted(((str(k), _freeze_state(v)) for k, v in value.items())))
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze_state(v) for v in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)

class Component:
    def __init__(self, canvas, svg_file, name, size, x, y, svg_path, category, config, is_preview=False):
        self.canvas = canvas
        self.svg_file = svg_file
        self.name = name
        self.original_size = [size[0], size[1]]
        self.size = [size[0], size[1]]
        self.x = x
        self.y = y
        self.rotation = 0
        self.conn_points = []
        self._selected = False
        self.selection_id = None
        self._highlight_image_data = None  # Cache para la imagen de contorno
        self.canvas_id = None
        self.point_ids = []
        self.category = category
        self.config = config
        self.svg_path = svg_path
        self.is_preview = is_preview # FLAG PARA IDENTIFICAR COMPONENTES DE PREVIEW
        self._is_moving = False # FLAG DE MOVIMIENTO PARA OPTIMIZAR SELECCIÓN

        #  SIMULACIÓN: Atributos para simulación
        # El estado de simulación es sólo de ejecución: nunca se serializa a .ecad
        self.simulation_state = None # Estado de simulación en curso
        self.activation_type = None # Tipo de activación
        self.is_active = None        # NO APLICAR NADA HASTA QUE SE SETEE EXPLÍCITAMENTE

        # Caché para get_connection_points_global (se invalida por firma de estado)
        self._points_cache = None
        self._points_cache_key = None

        # Caché de una entrada para la imagen escalada (clave: imagen, rotación, reflejos, zoom)
        self._scaled_image_cache = None

        # MOTOR: Atributos específicos para motores eléctricos
        _fname = (svg_file or '').lower()
        if 'motor' in _fname:
            self.motor_direction  = 0        # 0=parado, 1=CW, -1=CCW
            self.voltage          = 0        # Voltaje real aplicado (V)
            self.current_volt_pct = 0.0      # % de voltaje aplicado (0-100)
            self.current_freq     = 0.0      # Frecuencia aplicada (Hz)
            self.is_driven        = False    # True si lo controla un driver externo
            self.motor_fault      = None     # None|'OVERVOLTAGE'|'PHASE_LOSS'|'BURNED'|'LOCKED_ROTOR'
            self.motor_temp       = 'NORMAL' # 'NORMAL'|'HOT'|'CRITICAL'
            # Voltaje nominal según tipo de motor
            if 'motor-1p.svg' in _fname:        # M2: monofásico sin capacitor
                self.nominal_voltage = 110
            elif 'motor-1pc.svg' in _fname:     # M5: monofásico con capacitor / 2 velocidades
                self.nominal_voltage = 110
            elif 'motor-1p-dosi.svg' in _fname: # M4: bomba dosificadora (110V o 220V)
                self.nominal_voltage = 220
            elif 'motor-3p.svg' in _fname:      # M1: trifásico estándar
                self.nominal_voltage = 220
            elif 'motor-3pt.svg' in _fname:    # M3: trifásico con PE
                self.nominal_voltage = 220
            elif 'motor-3p-st.svg' in _fname:   # M6: trifásico 6 bornes Y/Δ
                self.nominal_voltage = 220
            else:
                self.nominal_voltage = 220      # fallback trifásico

        # DETECTAR TIPO DE COMPONENTE ESPECIAL (PRIMERO)
        self.component_type = self._detect_special_component_type()

        # SISTEMA DE ETIQUETAS - Inicializar usando LabelManager
        self.label_data = LabelManager.get_default_label_data(self)
        self.label_data['name'] = LabelManager.suggest_name(self, self.canvas)

        # Valores predeterminados específicos para Fuente DC/AC
        if self.svg_file and "power_supply_dc" in self.svg_file.lower():
            self.label_data.update({'voltaje': '24', 'amperios': '10', 'potencia': '240'})
        elif self.svg_file and "power_supply_ac" in self.svg_file.lower():
            self.label_data.update({'voltaje': '24V AC', 'amperios': '10', 'potencia': '240'})

        # Intentar cargar terminales iniciales desde el SVG si no hay datos guardados
        if not self.label_data['terminals'] and SVG_SUPPORT:
             self.label_data['terminals'] = self.extract_terminal_labels_from_svg()
        self.label_ids = []  # IDs de elementos de etiqueta en canvas

        self.load_image(svg_path)
        self.detect_connection_points()

        # Dibujar componente solo si el canvas tiene los atributos necesarios
        try:
            self.draw()
        except AttributeError as e:
            if "scale_factor" in str(e):
                                # Canvas no tiene scale_factor - saltando draw() para {self.name}")
                pass
            else:
                                # Error en draw para {self.name}: {e}")
                pass
        except Exception as e:
                            # Error inesperado en draw() para {self.name}: {e}")
            pass

        try:
            self.draw_label()
        except Exception as e:
                            # Error en draw_label para {self.name}: {e}")
            pass

        # SIMULACIÓN: Detectar tipo de activación desde el SVG
        self.component_activation_mode = self._detect_activation_mode_from_svg()

        # Solo agregar toggle_state si es un componente MANUAL
        if self.component_activation_mode == "manual":
            def toggle_state_method(self):
                """Alterna el estado de activación del componente (ON/OFF o cicla posiciones)."""
                # Detectar si es un selector de múltiples posiciones
                available_positions = self._get_available_positions()

                if len(available_positions) > 2:
                    # Selector de múltiples posiciones: ciclar entre OFF, ON-2, ON-3, etc.
                    current_pos = getattr(self, 'current_position', 0)
                    next_pos = (current_pos + 1) % len(available_positions)
                    self.current_position = next_pos
                    self.is_active = next_pos > 0
                else:
                    self.is_active = not self.is_active

                if self.activation_type and hasattr(self.activation_type, 'toggle'):
                    self.activation_type.toggle()
                if self.svg_file:
                    self.load_image(self.svg_path)
                    self.draw()
            self.toggle_state = toggle_state_method.__get__(self, self.__class__)

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, value):
        if self._selected != value:
            self._selected = value
            self.update_selection_visual()

    def update_selection_visual(self):
        """Actualiza el visual de selección (círculo punteado)"""
        # No dibujar círculo si el componente está en movimiento (evita lag)
        # El círculo ya fue borrado en move(), así que solo saltamos el dibujo
        if hasattr(self, '_is_moving') and self._is_moving:
            return  # Salir sin dibujar el círculo

        # Limpiar selección previa
        if self.selection_id:
            try:
                self.canvas.delete(self.selection_id)
            except Exception:
                pass
            self.selection_id = None

        # Si está seleccionado, dibujar círculo
        if self._selected:
            try:
                # Calcular centro y radio
                # Usar dimensiones visuales (con zoom)
                zoom = self.canvas.zoom_level
                w = self.size[0] * zoom
                h = self.size[1] * zoom
                x = self.x * zoom
                y = self.y * zoom

                center_x = x + w / 2
                center_y = y + h / 2

                # Radio para cubrir todo el componente (diagonal / 2)
                radius = (math.sqrt(w**2 + h**2) / 2) + 5

                x1 = center_x - radius
                y1 = center_y - radius
                x2 = center_x + radius
                y2 = center_y + radius

                self.selection_id = self.canvas.create_oval(
                    x1, y1, x2, y2,
                    outline="#0080ff", width=1, dash=(4, 4), fill="", tags="selection_circle"
                )
            except Exception:
                pass

    def _detect_special_component_type(self):
        """Detecta si es un componente de conexión especial - OPTIMIZADO O(1)"""
        if not self.svg_file:
            return "normal"

        # Diccionario de lookup O(1) en lugar de elif chain O(5)
        svg_name = self.svg_file.lower()

        # Mapeo directo de archivos SVG a tipos de componentes
        component_type_map = {
            "fase.svg": "fase",
            "conxn.svg": "conxn",
            "conxn2.svg": "conxn2",
            "t.svg": "tierra"
        }

        # Verificar si es un archivo borner (borner-1.svg, borner-2.svg, etc.)
        if "borner" in svg_name:
            return "borner"

        # Lookup O(1) en lugar de 5 comparaciones secuenciales
        return component_type_map.get(svg_name, "normal")

    def _apply_fase_specific_colors(self, svg_content):
        """
        Aplica colores específicos al SVG según el tipo de fase.

        Args:
            svg_content: Contenido SVG como string

        Returns:
            str: Contenido SVG con colores aplicados
        """
        # Determinar si este componente es una fase que necesita colores específicos
        phase_name = self.label_data.get('name', '') if hasattr(self, 'label_data') else ''
        phase_name = phase_name.upper() if phase_name else ''

        if phase_name not in ["N", "PE"]:  # Solo aplicar colores específicos para N y PE
            return svg_content

        # Color objetivo según el tipo de fase
        if phase_name == "N":  # Neutro - azul sólido
            target_color = "#0000ff"  # Azul
        elif phase_name == "PE":  # Protección tierra - verde
            target_color = "#008000"  # Verde
        else:
            return svg_content

        # Para modo oscuro, adaptar el color
        canvas_bg = self.canvas.cget("bg")
        if _is_dark_bg(canvas_bg):  # Modo oscuro
            if phase_name == "N":
                target_color = "#87CEEB"  # Azul claro para modo oscuro
            elif phase_name == "PE":
                target_color = "#32CD32"  # Verde claro para modo oscuro

        # REEMPLAZO AGGRESSIVO: Reemplazar TODOS los colores por el color específico
        # Esto asegura que cualquier elemento en el SVG se coloree correctamente
        color_replacements = [
            ('black', target_color),
            ('white', target_color),  # CRÍTICO: También reemplazar 'white' (convertido desde 'black' en modo oscuro)
            ('#000000', target_color),
            ('#ffffff', target_color),  # CRÍTICO: También reemplazar '#ffffff' (convertido desde '#000000' en modo oscuro)
            ('#000', target_color),
            ('#fff', target_color),    # CRÍTICO: También reemplazar '#fff' (convertido desde '#000' en modo oscuro)
            ('fill="black"', f'fill="{target_color}"'),
            ('fill="white"', f'fill="{target_color}"'),  # CRÍTICO: Para modo oscuro
            ('stroke="black"', f'stroke="{target_color}"'),
            ('stroke="white"', f'stroke="{target_color}"'),  # CRÍTICO: Para modo oscuro
            ('color="black"', f'color="{target_color}"'),
            ('color="white"', f'color="{target_color}"'),  # CRÍTICO: Para modo oscuro
            ('fill="#000000"', f'fill="{target_color}"'),
            ('fill="#ffffff"', f'fill="{target_color}"'),  # CRÍTICO: Para modo oscuro
            ('stroke="#000000"', f'stroke="{target_color}"'),
            ('stroke="#ffffff"', f'stroke="{target_color}"'),  # CRÍTICO: Para modo oscuro
            ('color="#000000"', f'color="{target_color}"'),
            ('color="#ffffff"', f'color="{target_color}"'),  # CRÍTICO: Para modo oscuro
            ('fill="#000"', f'fill="{target_color}"'),
            ('fill="#fff"', f'fill="{target_color}"'),  # CRÍTICO: Para modo oscuro
            ('stroke="#000"', f'stroke="{target_color}"'),
            ('stroke="#fff"', f'stroke="{target_color}"'),  # CRÍTICO: Para modo oscuro
            ('color="#000"', f'color="{target_color}"'),
            ('color="#fff"', f'color="{target_color}"'),  # CRÍTICO: Para modo oscuro
            # También incluir rgb(0,0,0) y rgb(255,255,255)
            ('fill="rgb(0,0,0)"', f'fill="{target_color}"'),
            ('fill="rgb(255,255,255)"', f'fill="{target_color}"'),  # CRÍTICO: Para modo oscuro
            ('stroke="rgb(0,0,0)"', f'stroke="{target_color}"'),
            ('stroke="rgb(255,255,255)"', f'stroke="{target_color}"'),  # CRÍTICO: Para modo oscuro
            ('color="rgb(0,0,0)"', f'color="{target_color}"'),
            ('color="rgb(255,255,255)"', f'color="{target_color}"'),  # CRÍTICO: Para modo oscuro
        ]

        for old_color, new_color in color_replacements:
            svg_content = svg_content.replace(old_color, new_color)

        return svg_content

    def _apply_layer_visibility(self, svg_content):
        """
        Aplica visibilidad de capas SVG según el estado del componente.
        Soporta: ON/OFF (manual), ACTIVA/DESACTIVA (automático), ON-R/ON-L/OFF (motor)
        
        Args:
            svg_content: Contenido SVG original
            
        Returns:
            str: Contenido SVG con visibilidad modificada
        """
        # CAPA LOTTO: Controlada por el check "LOTTO" del editor de etiquetas.
        # Se aplica SIEMPRE (aunque is_active sea None) y solo si el SVG la tiene.
        if re.search(r'inkscape:label="LOTTO"', svg_content, re.IGNORECASE):
            lotto_enabled = self.label_data.get('lotto', False)
            display_lotto = "inline" if lotto_enabled else "none"
            pattern_style = r'(<g[^>]*?inkscape:label="LOTTO"[^>]*?)style\s*=\s*"display:[^"]*"'
            if re.search(pattern_style, svg_content, re.IGNORECASE):
                svg_content = re.sub(
                    pattern_style,
                    rf'\1style="display:{display_lotto}"',
                    svg_content, flags=re.IGNORECASE)
            else:
                pattern_no_style = r'(<g[^>]*?inkscape:label="LOTTO"[^>]*?)>'
                svg_content = re.sub(
                    pattern_no_style,
                    rf'\1 style="display:{display_lotto}">',
                    svg_content, flags=re.IGNORECASE)

        # Si no hay estado de activación asignado (None), omitir forzar visibilidad y dejar el SVG original
        is_active = getattr(self, 'is_active', None)

        if is_active is None:
            return self._apply_burner_phase_layers(svg_content)

        # Detectar modo de activación
        activation_mode = getattr(self, 'component_activation_mode', None)

        # Para motores, manejar ACTIVA-L, ACTIVA-R, DESACTIVA
        if activation_mode == "motor":
            motor_direction = getattr(self, 'motor_direction', 0)  # -1=izq, 0=parado, 1=der

            if motor_direction == 1:  # Girando a la derecha
                svg_content = re.sub(r'(<g[^>]*?(?:inkscape:label="ACTIVA-R"|id="layer_activa-r")[^>]*)style="display:[^"]*"', r'\1style="display:inline"', svg_content, flags=re.IGNORECASE)
                svg_content = re.sub(r'(<g[^>]*?(?:inkscape:label="ACTIVA-L"|id="layer_activa-l")[^>]*)style="display:[^"]*"', r'\1style="display:none"', svg_content, flags=re.IGNORECASE)
                svg_content = re.sub(r'(<g[^>]*?(?:inkscape:label="DESACTIVA"|id="layer_desactiva")[^>]*)style="display:[^"]*"', r'\1style="display:none"', svg_content, flags=re.IGNORECASE)
            elif motor_direction == -1:  # Girando a la izquierda
                svg_content = re.sub(r'(<g[^>]*?(?:inkscape:label="ACTIVA-L"|id="layer_activa-l")[^>]*)style="display:[^"]*"', r'\1style="display:inline"', svg_content, flags=re.IGNORECASE)
                svg_content = re.sub(r'(<g[^>]*?(?:inkscape:label="ACTIVA-R"|id="layer_activa-r")[^>]*)style="display:[^"]*"', r'\1style="display:none"', svg_content, flags=re.IGNORECASE)
                svg_content = re.sub(r'(<g[^>]*?(?:inkscape:label="DESACTIVA"|id="layer_desactiva")[^>]*)style="display:[^"]*"', r'\1style="display:none"', svg_content, flags=re.IGNORECASE)
            else:  # Parado (motor_direction == 0)
                svg_content = re.sub(r'(<g[^>]*?(?:inkscape:label="DESACTIVA"|id="layer_desactiva")[^>]*)style="display:[^"]*"', r'\1style="display:inline"', svg_content, flags=re.IGNORECASE)
                svg_content = re.sub(r'(<g[^>]*?(?:inkscape:label="ACTIVA-L"|id="layer_activa-l")[^>]*)style="display:[^"]*"', r'\1style="display:none"', svg_content, flags=re.IGNORECASE)
                svg_content = re.sub(r'(<g[^>]*?(?:inkscape:label="ACTIVA-R"|id="layer_activa-r")[^>]*)style="display:[^"]*"', r'\1style="display:none"', svg_content, flags=re.IGNORECASE)

            return svg_content

        # Helper interno para cambiar visibilidad de capas de forma robusta
        def set_layer_display(label, display_val):
            nonlocal svg_content
            # Patrón seguro: busca <g ... label="..." ... > y captura hasta el final del tag >
            # [^>]*? garantiza que no salimos del tag <g ... >
            # re.IGNORECASE para máxima compatibilidad

            # Caso 1: Tiene atributo style
            pattern_style = rf'(<g[^>]*?(?:inkscape:label="{label}"|id="layer_{label.lower().replace(" ", "")}")[^>]*?)style\s*=\s*"display:[^"]*"'
            if re.search(pattern_style, svg_content, re.IGNORECASE):
                svg_content = re.sub(pattern_style, rf'\1style="display:{display_val}"', svg_content, flags=re.IGNORECASE)
                return

            # Caso 2: Tiene atributo style pero sin display o con otros estilos
            pattern_any_style = rf'(<g[^>]*?(?:inkscape:label="{label}"|id="layer_{label.lower().replace(" ", "")}")[^>]*?style\s*=\s*")([^"]*)(")'
            if re.search(pattern_any_style, svg_content, re.IGNORECASE):
                # Limpiar cualquier display existente y agregar el nuevo
                def cleanup_style(m):
                    clean = re.sub(r'display:[^;]+;?', '', m.group(2))
                    return f'{m.group(1)}{clean};display:{display_val}{m.group(3)}'
                svg_content = re.sub(pattern_any_style, cleanup_style, svg_content, flags=re.IGNORECASE)
                return

            # Caso 3: No tiene atributo style, insertarlo antes del cierre >
            pattern_no_style = rf'(<g[^>]*?(?:inkscape:label="{label}"|id="layer_{label.lower().replace(" ", "")}")[^>]*?)>'
            if re.search(pattern_no_style, svg_content, re.IGNORECASE):
                svg_content = re.sub(pattern_no_style, rf'\1 style="display:{display_val}">', svg_content, flags=re.IGNORECASE)

        # 1. Manejar ON / OFF (Manual)
        if activation_mode == "manual":
            set_layer_display("ON", "inline" if is_active else "none")
            set_layer_display("OFF", "none" if is_active else "inline")

        # 2. Manejar Selectores Multi-posición
        current_position = getattr(self, 'current_position', 0)
        positions = self._get_available_positions() if hasattr(self, '_get_available_positions') else []
        if len(positions) > 2:
            for i, pos in enumerate(positions):
                set_layer_display(pos, "inline" if i == current_position else "none")
            return svg_content # Fin para selectores

        # 3. Manejar ACTIVA / DESACTIVA (Automático / Drivers)
        if activation_mode == "automatic":
            set_layer_display("ACTIVA", "inline" if is_active else "none")
            set_layer_display("DESACTIVA", "none" if is_active else "inline")

            # Capa especial RUN (ACTIVA 2) para arrancadores
            is_running = getattr(self, 'layer_running', False)
            set_layer_display("ACTIVA 2", "inline" if is_running else "none")

            # Capa especial ANALOGICA para variadores
            is_analog = self.label_data.get('vdf_analog_enabled', False)
            set_layer_display("ANALOGICA", "inline" if is_analog else "none")

        svg_content = self._apply_burner_phase_layers(svg_content)

        return svg_content

    def _apply_burner_phase_layers(self, svg_content):
        """
        Applies PE/N layer visibility to burner SVG content.
        Called from _apply_layer_visibility.
        
        Args:
            svg_content: SVG content string
            
        Returns:
            str: Modified SVG content with layer visibility applied
        """
        if self.component_type != 'borner':
            return svg_content

        # Get layer states (default to both OFF)
        layer_states = getattr(self, 'burner_layer_states', {'PE': False, 'N': False})

        # Apply PE layer visibility (support both id="PE" and inkscape:label="PE")
        pe_display = "inline" if layer_states.get('PE', False) else "none"
        svg_content = re.sub(
            r'(<g[^>]*?(?:id="PE"|inkscape:label="PE")[^>]*?)style="display:[^"]*"',
            rf'\1style="display:{pe_display}"',
            svg_content,
            flags=re.IGNORECASE
        )
        # If no style attribute exists, add it
        if ('id="PE"' in svg_content or 'inkscape:label="PE"' in svg_content) and f'display:{pe_display}' not in svg_content:
            svg_content = re.sub(
                r'(<g[^>]*?(?:id="PE"|inkscape:label="PE")[^>]*?)>',
                rf'\1 style="display:{pe_display}">',
                svg_content,
                flags=re.IGNORECASE
            )

        # Apply N layer visibility (support both id="N" and inkscape:label="N")
        n_display = "inline" if layer_states.get('N', False) else "none"
        svg_content = re.sub(
            r'(<g[^>]*?(?:id="N"|inkscape:label="N")[^>]*?)style="display:[^"]*"',
            rf'\1style="display:{n_display}"',
            svg_content,
            flags=re.IGNORECASE
        )
        # If no style attribute exists, add it
        if ('id="N"' in svg_content or 'inkscape:label="N"' in svg_content) and f'display:{n_display}' not in svg_content:
            svg_content = re.sub(
                r'(<g[^>]*?(?:id="N"|inkscape:label="N")[^>]*?)>',
                rf'\1 style="display:{n_display}">',
                svg_content,
                flags=re.IGNORECASE
            )

        return svg_content

    def _detect_activation_mode_from_svg(self):
        """
        Detecta el modo de activación del componente leyendo las capas del SVG.
        
        Returns:
            str: "manual" (ON/OFF), "motor" (ACTIVA-L/ACTIVA-R/DESACTIVA), "automatic" (ACTIVA/DESACTIVA), o None
        """
        if not self.svg_file:
            return None

        try:
            folder = self.category.lower() if self.category else ""
            full_path = Path(self.svg_path) / folder / self.svg_file

            if not full_path.exists():
                return None

            # Leer el SVG como texto
            with open(full_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()

            # Detectar tipo según las capas presentes
            # Prioridad: Motor > Manual > Automático

            # 1. Motor (ACTIVA-L, ACTIVA-R, DESACTIVA)
            if 'inkscape:label="ACTIVA-R"' in svg_content or 'id="layer_activa-r"' in svg_content.lower():
                return "motor"

            # 2. Manual (ON, OFF o ON-N para selectores multiposición)
            has_on = ('inkscape:label="ON"' in svg_content or 'id="layer_on"' in svg_content.lower() or
                      re.search(r'inkscape:label="ON-\d+"', svg_content))
            has_off = 'inkscape:label="OFF"' in svg_content or 'id="layer_off"' in svg_content.lower()
            if has_on and has_off:
                return "manual"

            # 3. Automático (ACTIVA, DESACTIVA) - pero no motor
            if 'inkscape:label="ACTIVA"' in svg_content or 'id="layer_activa"' in svg_content.lower():
                # Verificar que no sea motor (no tiene ACTIVA-R/ACTIVA-L)
                if 'ACTIVA-R' not in svg_content and 'ACTIVA-L' not in svg_content:
                    return "automatic"

            return None

        except Exception as e:
            print(f"⚠️ Error detectando modo de activación para {self.name}: {e}")
            return None

    def _render_state_key(self, full_path, mtime_ns):
        """
        Clave hashable con TODO lo que determina el render del SVG:
        archivo (+mtime), fondo del canvas, tamaño, estado del componente y
        transformaciones. Si cambia cualquiera de estos valores, la caché falla
        y se vuelve a renderizar.
        """
        try:
            canvas_bg = self.canvas.cget("bg")
        except Exception:
            canvas_bg = ''
        return (
            str(full_path), mtime_ns, canvas_bg,
            int(self.original_size[0]), int(self.original_size[1]),
            _freeze_state(getattr(self, 'label_data', None)),
            getattr(self, 'is_active', None),
            getattr(self, 'component_activation_mode', None),
            getattr(self, 'motor_direction', 0),
            getattr(self, 'current_position', 0),
            getattr(self, 'layer_running', False),
            _freeze_state(getattr(self, 'burner_layer_states', None)),
            getattr(self, 'component_type', None),
            self.rotation,
            bool(getattr(self, 'flipped_h', False)),
            bool(getattr(self, 'flipped_v', False)),
        )

    def _compose_svg_content(self, svg_content, canvas_bg):
        """Aplica fondo oscuro, colores de fase, capas ON/OFF y etiquetas al SVG."""
        if _is_dark_bg(canvas_bg):  # Modo oscuro
            # Reemplazar colores oscuros por claros
            svg_content = svg_content.replace('black', 'white')
            svg_content = svg_content.replace('#000000', '#ffffff')
            svg_content = svg_content.replace('#000', '#fff')
            svg_content = svg_content.replace('fill="rgb(0,0,0)"', 'fill="rgb(255,255,255)"')
            svg_content = svg_content.replace('stroke="black"', 'stroke="white"')
            svg_content = svg_content.replace('stroke="#000000"', 'stroke="#ffffff"')
            svg_content = svg_content.replace('stroke="#000"', 'stroke="#fff"')
            svg_content = svg_content.replace('fill="black"', 'fill="white"')
            svg_content = svg_content.replace('fill="#000000"', 'fill="#ffffff"')
            svg_content = svg_content.replace('fill="#000"', 'fill="#fff"')
            svg_content = svg_content.replace('color="black"', 'color="white"')
            svg_content = svg_content.replace('color="#000000"', 'color="#ffffff"')
            svg_content = svg_content.replace('color="#000"', 'color="#fff"')
            svg_content = re.sub(r'#550022(?:ff)?', '#ffffff', svg_content, flags=re.IGNORECASE)

        # Aplicar colores específicos para fases si es necesario
        svg_content = self._apply_fase_specific_colors(svg_content)

        # SIMULACIÓN: Aplicar visibilidad de capas (ON/OFF)
        svg_content = self._apply_layer_visibility(svg_content)

        # ETIQUETAS TERMINALES: Reemplazar textos en el SVG
        svg_content = self._apply_terminal_labels_to_svg(svg_content)

        # VALORES FUENTE DC: Reemplazar Voltaje, Amperios y Watts
        svg_content = self._apply_power_supply_values_to_svg(svg_content)
        return svg_content

    def load_image(self, svg_path):
        self.photo = None
        if not SVG_SUPPORT:
            return

        # SEGURIDAD: No intentar cargar si no hay archivo SVG (ej: JunctionComponent)
        if not self.svg_file:
            return

        try:
            folder = self.category.lower() if self.category else ""
            full_path = Path(svg_path) / folder / self.svg_file

            if not full_path.exists():
                print(f"SVG no encontrado: {full_path}")
                return

            # Estado completo del render: si ya se renderizó igual, no se hace
            # NADA de trabajo (ni leer el archivo, ni cairosvg, ni PIL).
            try:
                mtime_ns = full_path.stat().st_mtime_ns
            except OSError:
                mtime_ns = 0
            state_key = self._render_state_key(full_path, mtime_ns)
            cached = _RASTER_CACHE.get(state_key)
            if cached is not None:
                self.image_data, self.photo = cached[0], cached[1]
                self.size = [cached[2][0], cached[2][1]]
                return

            # 1. Texto crudo del SVG (compartido por todos los componentes del
            #    mismo archivo, así que se lee una sola vez por sesión).
            text_key = (str(full_path), mtime_ns)
            svg_text = _SVG_TEXT_CACHE.get(text_key)
            if svg_text is None:
                with open(full_path, 'r', encoding='utf-8') as f:
                    svg_text = f.read()
                _cache_put(_SVG_TEXT_CACHE, text_key, svg_text, _CACHE_LIMITS['text'])

            # 2. SVG con el estado aplicado (capas ON/OFF, etiquetas, colores)
            svg_content = self._compose_svg_content(svg_text, self.canvas.cget("bg"))

            # 3. PNG rasterizado: identidad del contenido + tamaño de salida.
            #    Dos componentes distintos con el mismo dibujo comparten el PNG.
            png_key = (zlib.crc32(svg_content.encode('utf-8')),
                       int(self.original_size[0]), int(self.original_size[1]))
            png_data = _PNG_CACHE.get(png_key)
            if png_data is None:
                png_data = cairosvg.svg2png(
                    bytestring=svg_content.encode('utf-8'),
                    output_width=self.original_size[0],
                    output_height=self.original_size[1]
                )
                _cache_put(_PNG_CACHE, png_key, png_data, _CACHE_LIMITS['png'])

            # 4. Imagen final (PIL + PhotoImage) con rotación/reflejo aplicados
            # SOLUCIÓN ANTI-DOBLE-ROTACIÓN: Separar imagen de análisis de imagen visual
            original_image = Image.open(io.BytesIO(png_data))

            # Imagen para análisis: SIEMPRE original (0°)
            self.image_data = original_image

            # Imagen para mostrar: Aplicar transformaciones (rotación + reflejo)
            display_image = original_image

            # 1. Aplicar rotación si es necesario
            if self.rotation != 0:
                display_image = display_image.rotate(-self.rotation, expand=True)
                self.size = [display_image.size[0], display_image.size[1]]
            else:
                # Rotación 0: mantener tamaño original
                self.size = [self.original_size[0], self.original_size[1]]

            # 2. Aplicar reflejo horizontal si está activado
            if getattr(self, 'flipped_h', False):
                display_image = display_image.transpose(Image.FLIP_LEFT_RIGHT)

            self.photo = ImageTk.PhotoImage(display_image)

            _cache_put(_RASTER_CACHE, state_key,
                       (original_image, self.photo, tuple(self.size)),
                       _CACHE_LIMITS['raster'])

        except Exception as e:
            print(f"Error cargando SVG {self.svg_file}: {e}")
            import traceback
            traceback.print_exc()
            self.photo = None


    def detect_connection_points(self):
        if (hasattr(self, 'component_type') and self.component_type == "empalme"):

            return

        # TÉCNICA ANTI-TRAZAS: Limpiar SIEMPRE la lista de puntos antes de detectar nuevos
        self.conn_points = []

        if not SVG_SUPPORT or not hasattr(self, 'image_data'):
            return
        try:
            # CLAVE: self.image_data es SIEMPRE la imagen original (0°)
            # La rotación se aplica matemáticamente en get_connection_points_global()
            pixels = self.image_data.load()
            width, height = self.image_data.size
            target_color = (128, 128, 128)
            tolerance = 20
            points = []

            for y in range(height):
                for x in range(width):
                    rgba = pixels[x, y]
                    r, g, b = rgba[:3] if len(rgba) == 4 else rgba[:3]
                    if (abs(r - target_color[0]) <= tolerance and
                        abs(g - target_color[1]) <= tolerance and
                        abs(b - target_color[2]) <= tolerance):
                        points.append((x, y))

            clusters = []
            while points:
                cluster = [points.pop(0)]
                i = 0
                while i < len(points):
                    if (abs(points[i][0] - cluster[0][0]) <= 2 and
                        abs(points[i][1] - cluster[0][1]) <= 2):
                        cluster.append(points.pop(i))
                    else:
                        pass
                        i += 1
                if cluster:
                    avg_x = sum(p[0] for p in cluster) / len(cluster)
                    avg_y = sum(p[1] for p in cluster) / len(cluster)

                    # Detectar orientación basándose en la posición en el componente
                    orientation = self._detect_point_orientation(avg_x, avg_y)
                    self.conn_points.append(ConnectionPoint(avg_x, avg_y, 0.5, orientation))

        except Exception as e:

            pass
            self.conn_points = []

    def _detect_point_orientation(self, x, y):
        """
        Detecta la orientación de un punto de conexión basándose en su posición relativa en el componente.

        Args:
            x, y: Coordenadas del punto en el componente (imagen original)

        Returns:
            str: Orientación ('N', 'S', 'E', 'O')
        """
        # Usar dimensiones originales del componente
        width, height = self.original_size

        # Calcular posición relativa (0.0 a 1.0)
        rel_x = x / width if width > 0 else 0.5
        rel_y = y / height if height > 0 else 0.5

        # Tolerancia para detectar bordes
        edge_tolerance = 0.3

        # Sistema de detección de bordes con diccionarios O(1)
        edge_conditions = [
            ('N', rel_y <= edge_tolerance, rel_y),  # Borde superior
            ('S', rel_y >= (1.0 - edge_tolerance), 1.0 - rel_y),  # Borde inferior
            ('O', rel_x <= edge_tolerance, rel_x),  # Borde izquierdo
            ('E', rel_x >= (1.0 - edge_tolerance), 1.0 - rel_x)  # Borde derecho
        ]

        # Detectar primer borde que cumple la condición (prioridad por orden)
        for orientation, condition, distance in edge_conditions:
            if condition:
                return orientation

        # Si no está en ningún borde extremo, usar posición más cercana
        distances = {
            'N': rel_y,
            'S': 1.0 - rel_y,
            'O': rel_x,
            'E': 1.0 - rel_x
        }
        return min(distances, key=distances.get)

    def _rotate_orientation(self, orientation, rotation_angle):
        """
        Rota la orientación de un punto según el ángulo de rotación del componente.

        Args:
            orientation: Orientación original ('N', 'S', 'E', 'O')
            rotation_angle: Ángulo de rotación (0, 90, 180, 270)

        Returns:
            str: Nueva orientación después de la rotación
        """
        # Mapeo de orientaciones
        orientations = ['N', 'E', 'S', 'O']  # En sentido horario

        try:
            current_index = orientations.index(orientation)
            # Cada 90° de rotación horaria = +1 en el índice
            steps = (rotation_angle // 90) % 4
            new_index = (current_index + steps) % 4
            return orientations[new_index]
        except ValueError:
            # Si la orientación no es válida, devolver Norte por defecto
            return 'N'

    def get_scaled_image(self):
        """
        Genera una imagen escalada según el scale_factor del canvas.

        Usa caché acotada (máx. 4 claves): si rotación, reflejos, imagen base y zoom
        ya fueron escalados antes, se reutiliza el PhotoImage sin volver a escalar ni
        rotar (evita el resize LANCZOS en cada frame de arrastre/redibujado).
        """
        if not SVG_SUPPORT or not hasattr(self, 'image_data'):
            return None

        try:
            zoom_level = self.canvas.zoom_level
            img_key = (id(self.image_data), self.rotation,
                       getattr(self, 'flipped_h', False),
                       getattr(self, 'flipped_v', False),
                       zoom_level)

            cache = self._scaled_image_cache
            if cache is None:
                cache = {}
                self._scaled_image_cache = cache

            cached_photo = cache.get(img_key)
            if cached_photo is not None:
                return cached_photo

            # Calcular el nuevo tamaño basado en el scale_factor
            original_image = self.image_data

            transformed_image = original_image

            # 1. Rotar la imagen si es necesario
            if self.rotation != 0:
                transformed_image = transformed_image.rotate(-self.rotation, expand=True)

            # 2. Aplicar reflejo horizontal si está activado
            if getattr(self, 'flipped_h', False):
                transformed_image = transformed_image.transpose(Image.FLIP_LEFT_RIGHT)

            # 3. Aplicar reflejo vertical si está activado
            if getattr(self, 'flipped_v', False):
                transformed_image = transformed_image.transpose(Image.FLIP_TOP_BOTTOM)

            image_scale = zoom_level
            new_width = int(transformed_image.size[0] * image_scale)
            new_height = int(transformed_image.size[1] * image_scale)

            if new_width > 0 and new_height > 0:
                scaled_image = transformed_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(scaled_image)
                if len(cache) >= 4:
                    cache.pop(next(iter(cache)))
                cache[img_key] = photo
                return photo

        except Exception as e:

            pass
        return None

    def draw(self):
        """
        Dibuja el componente en el canvas.
        Implementación anti-trazas: limpieza completa antes de redibujar.
        """
        # TÉCNICA ANTI-TRAZAS: Limpiar COMPLETAMENTE antes de dibujar
        self._clear_component_elements()

        if SVG_SUPPORT and hasattr(self, 'image_data'):
            scaled_photo = self.get_scaled_image()
            if scaled_photo:
                # CORRECCIÓN DESFASE: Usar misma fórmula que puntos de conexión (sin pan offset)
                self.canvas_id = self.canvas.create_image(
                    self.x * self.canvas.zoom_level,
                    self.y * self.canvas.zoom_level,
                    image=scaled_photo, anchor="nw", tags="component"
                )
                # Mantener referencia para evitar garbage collection
                self.scaled_photo = scaled_photo
            else:
                # Fallback a rectángulo si falla la escalado
                # CORRECCIÓN DESFASE: Usar misma fórmula que puntos de conexión (sin pan offset)
                fill_color = adapt_color_for_display("#cccccc", self.canvas.cget("bg"))
                outline_color = adapt_color_for_display("black", self.canvas.cget("bg"))
                self.canvas_id = self.canvas.create_rectangle(
                    self.x * self.canvas.zoom_level,
                    self.y * self.canvas.zoom_level,
                    (self.x + self.size[0]) * self.canvas.zoom_level,
                    (self.y + self.size[1]) * self.canvas.zoom_level,
                    fill=fill_color, outline=outline_color, width=2, tags="component"
                )
        else:
            pass
            # Fallback para cuando no hay soporte SVG
            # Adaptar colores para modo oscuro
            fill_color = adapt_color_for_display("#cccccc", self.canvas.cget("bg"))
            outline_color = adapt_color_for_display("black", self.canvas.cget("bg"))
            self.canvas_id = self.canvas.create_rectangle(
                self.x,
                self.y,
                self.x + self.size[0],
                self.y + self.size[1],
                fill=fill_color, outline=outline_color, width=2, tags="component"
            )

        self.draw_connection_points()

        self.draw_label()

        self.update_selection_visual()

    def draw_vdf_display(self):
        """Dibuja la pantalla del VDF delegando al renderizador especializado."""
        LabelRenderer.draw_vdf_display(self)

    def draw_ssf_display(self):
        """Dibuja el porcentaje de rampa en el centro del SST-C"""
        self.canvas.delete(f"ssf_metrics_{id(self)}")
        # El usuario solicitó quitar las letras verdes.
        return

    def draw_connection_points(self):
        """
        Dibuja los puntos de conexión del componente.
        SOLUCIÓN SIMPLE: Un tag único por componente para eliminación rápida.
        """
        draw_component_points(self.canvas, self)

    def get_connection_points_global(self):
        """
        Convierte puntos de conexión desde coordenadas locales a globales aplicando transformaciones.
        ORDEN: 1) Reflejo horizontal (si aplica), 2) Rotación matemática
        También actualiza las orientaciones según las transformaciones del componente.

        Cachea el resultado: solo se recalcula si cambian posición, rotación, reflejos,
        tamaño y los puntos de conexión (x, y, radio, orientación, estado conectado).
        """
        # Firma rápida de estado: cuando no cambia, se devuelve la caché (evita
        # reconstruir la lista y crear objetos temporales en cada frame/llamada).
        cache_key = (self.x, self.y, self.rotation,
                     getattr(self, 'flipped_h', False),
                     getattr(self, 'flipped_v', False),
                     tuple(self.original_size),
                     getattr(self, 'component_type', ''),
                     tuple((p.x, p.y, p.radius, p.orientation, p.connected)
                           for p in self.conn_points))
        if cache_key == self._points_cache_key:
            return self._points_cache

        points = []

        # Mapear ángulos de rotación a funciones de transformación
        rotation_transforms = {
            0:   lambda p: (p.x, p.y),
            90:  lambda p: (self.original_size[1] - p.y, p.x),
            180: lambda p: (self.original_size[0] - p.x, self.original_size[1] - p.y),
            270: lambda p: (p.y, self.original_size[0] - p.x)
        }

        transform_func = rotation_transforms.get(self.rotation, rotation_transforms[0])

        for point in self.conn_points:
            # 1. Aplicar reflejos si están activados (ANTES de rotar)
            temp_x = point.x
            temp_y = point.y

            # Reflejo horizontal
            if getattr(self, 'flipped_h', False):
                center_x = self.original_size[0] / 2
                temp_x = 2 * center_x - temp_x

            # Reflejo vertical
            if getattr(self, 'flipped_v', False):
                center_y = self.original_size[1] / 2
                temp_y = 2 * center_y - temp_y

            # Crear punto temporal con coordenadas reflejadas
            temp_point = type('Point', (), {'x': temp_x, 'y': temp_y})()

            # 2. ROTACIÓN MATEMÁTICA
            rel_x, rel_y = transform_func(temp_point)
            global_x = self.x + rel_x
            global_y = self.y + rel_y

            rotated_orientation = self._rotate_orientation(point.orientation, self.rotation)
            if getattr(self, 'component_type', '') == 'fase':
                rotated_orientation = 'N'

            rotated_point = type('ConnectionPoint', (), {
                'x': point.x,
                'y': point.y,
                'radius': getattr(point, 'radius', 0.5),
                'connected': point.connected,
                'orientation': rotated_orientation
            })()

            points.append((global_x, global_y, rotated_point))

        self._points_cache = points
        self._points_cache_key = cache_key
        return points

    def contains_point(self, x, y):
        """
        Verifica si el punto (x, y) está dentro de los límites del componente.
        
        CORRECCIÓN DESFASE: Comparar con coordenadas visuales escaladas
        para que coincida con donde el usuario ve el componente.
        
        Args:
            x, y: Coordenadas en canvas escalado (coordenadas visuales)
            
        Returns:
            bool: True si el punto está dentro del componente, False en caso contrario.
        """
        # Comparar directamente en coordenadas del mundo (lógicas)
        # x, y deben ser coordenadas del mundo (ya convertidas desde el evento)
        return (self.x <= x <= self.x + self.size[0] and
                self.y <= y <= self.y + self.size[1])
    def move(self, dx, dy):
        """Mueve el componente con snap suave al grid."""
        # Ocultar círculo de selección durante el movimiento para evitar lag
        if not hasattr(self, '_is_moving') or not self._is_moving:
            # Primera vez que se mueve - borrar círculo existente
            if self.selection_id:
                try:
                    self.canvas.delete(self.selection_id)
                except Exception:
                    pass
                self.selection_id = None
            # Marcar que estamos en movimiento
            self._is_moving = True

        old_x = self.x
        old_y = self.y
        self.x += dx
        self.y += dy

        # SNAP SUAVIZADO durante movimiento
        # Aplicar snap solo si el snap está habilitado y el componente está cerca del grid
        if hasattr(self.canvas, 'master') and hasattr(self.canvas.master, 'snap_to_grid'):
            snap_enabled = self.canvas.master.snap_to_grid_enabled.get() if hasattr(self.canvas.master, 'snap_to_grid_enabled') else False
            if snap_enabled:
                snapped_x, snapped_y = self.canvas.master.snap_to_grid(self.x, self.y, tolerance=25)
                # Solo aplicar snap si está razonablemente cerca del grid
                distance = ((self.x - snapped_x) ** 2 + (self.y - snapped_y) ** 2) ** 0.5
                if distance <= 20:  # Si está cerca, aplicar snap suave
                    self.x = snapped_x
                    self.y = snapped_y

        # En lugar de redibujar completo (que borra y recrea
        # imagen, puntos y etiquetas en cada frame), trasladar los items ya
        # existentes con el desplazamiento efectivo. Misma técnica que
        # TextComponent.move.
        if self.canvas_id:
            zoom = self.canvas.zoom_level
            delta_x = (self.x - old_x) * zoom
            delta_y = (self.y - old_y) * zoom
            self.canvas.move(self.canvas_id, delta_x, delta_y)
            self.canvas.move(f"points_{id(self)}", delta_x, delta_y)
            self.canvas.move(f"label_{id(self)}", delta_x, delta_y)
        else:
            self.draw()
            self.clear_label()
            self.draw_label()

    def _reload_and_redraw(self):
        """Recarga la imagen y redibuja componente + etiqueta tras una transformación."""
        self.load_image(self.svg_path)
        self.draw()
        self.clear_label()
        self.draw_label()

    def rotate(self, angle):
        """
        Rota el componente en el ángulo especificado.
        NUEVO ENFOQUE: Solo rotación visual + matemática, sin doble procesamiento.

        Args:
            angle (int): Ángulo de rotación en grados (90, -90, 180, etc.)
        """
        self.rotation = (self.rotation + angle) % 360

        # Ya no limpiar todo ni recalcular puntos
        # Los puntos se detectan UNA SOLA VEZ en imagen original

        # Solo detectar puntos si es la primera vez
        if not hasattr(self, 'conn_points') or not self.conn_points:
            self.detect_connection_points()

        # Regenerar highlight si existe (para aplicar nueva rotación en el futuro)
        # Nota: _generate_highlight_image usa image_data que es la original sin rotar,
        # así que no necesitamos regenerar _highlight_image_data, solo redibujar.
        # Pero update_selection_visual se encargará de obtener la versión rotada.

        self._reload_and_redraw()

    def flip_horizontal(self):
        """
        Refleja el componente horizontalmente (espejo).
        Invierte la imagen, los puntos de conexión y la posición de las etiquetas.
        """
        # Alternar estado de reflejo (inicializar si no existe)
        self.flipped_h = not getattr(self, 'flipped_h', False)

        self._reload_and_redraw()

    def flip_vertical(self):
        """
        Refleja el componente verticalmente (espejo).
        Invierte la imagen, los puntos de conexión y la posición de las etiquetas.
        """
        # Alternar estado de reflejo vertical (inicializar si no existe)
        self.flipped_v = not getattr(self, 'flipped_v', False)

        self._reload_and_redraw()

    def _clear_component_elements(self):
        """
        Limpia todos los elementos visuales del componente del canvas.
        SOLUCIÓN SIMPLE: Tags únicos para eliminación eficiente.
        """
        # Limpiar imagen principal
        if self.canvas_id:
            self.canvas.delete(self.canvas_id)
            self.canvas_id = None

        # Limpiar todos los puntos de conexión por tag único (MUY EFICIENTE)
        component_tag = f"points_{id(self)}"
        self.canvas.delete(component_tag)
        self.point_ids = []

        # Limpiar rectángulo de selección
        if self.selection_id:
            self.canvas.delete(self.selection_id)
            self.selection_id = None

        # Limpiar etiquetas
        self.clear_label()

    def delete(self):
        """
        Elimina completamente el componente del canvas.
        SOLUCIÓN SIMPLE: Tag único para eliminación eficiente.
        """
        if self.canvas_id:
            self.canvas.delete(self.canvas_id)

        component_tag = f"points_{id(self)}"
        self.canvas.delete(component_tag)

        self.clear_label()

    def to_dict(self):
        """Convierte el componente a diccionario para guardar en .ecad"""
        return {
            "svg_file": self.svg_file,
            "name": self.name,
            "size": self.size,
            "original_size": self.original_size,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "category": self.category,
            "label_data": self.label_data, # Incluir datos de etiqueta
            # Serializar puntos de conexión detectados (coordenadas locales en imagen original)
            "conn_points": serialize_connection_points(self.conn_points)
        }

    @classmethod
    def from_dict(cls, canvas, data, svg_path, config):
        """Crea un componente desde diccionario (para cargar .ecad)"""
        comp = cls(
            canvas=canvas,
            svg_file=data["svg_file"],
            name=data["name"],
            size=data["size"],
            x=data["x"],
            y=data["y"],
            svg_path=svg_path,
            category=data["category"],
            config=config
        )

        # Restaurar propiedades adicionales
        comp.original_size = data.get("original_size", data["size"])
        rotation = data.get("rotation", 0)

        # Restaurar datos de etiqueta si existen
        if "label_data" in data:
            comp.label_data = data["label_data"]
        # Restaurar puntos de conexión si están en el archivo, sino detectar automáticamente
        if "conn_points" in data and isinstance(data["conn_points"], list):
            comp.conn_points = parse_connection_points(data["conn_points"])
        else:
            comp.detect_connection_points()

        comp.rotation = rotation
        comp.load_image(svg_path)

        # Forzar actualización visual
        comp.draw()

        return comp

    def draw_label(self):
        """Dibuja la etiqueta del componente delegando al renderizador especializado."""
        LabelRenderer.draw(self)

    def is_master(self):
        """Determina si es un componente maestro (bobina) que debe mostrar referencias."""
        svg = self.svg_file.lower()
        return "coil" in svg or "bobina" in svg

    def extract_terminal_labels_from_svg(self):
        """
        Extrae los textos numéricos del SVG para pre-llenar el campo de edición.
        Busca elementos <text> cortos (lenght <= 4) y devuelve una cadena separada por comas
        ordenada espacialmente (Columna por columna).
        """
        if not self.svg_file or not SVG_SUPPORT:
            return ""

        try:
            folder = self.category.lower() if self.category else ""
            full_path = Path(self.svg_path) / folder / self.svg_file

            if not full_path.exists():
                return ""

            with open(full_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()

            try:
                # Intentar parsear directamente
                # Registrar namespaces puede ayudar a la serialización después, pero para lectura no es crítico
                root = ET.fromstring(svg_content)
            except ET.ParseError:
                # Si falla, intentar limpiar solo encoding
                clean_content = re.sub(r'<\?xml.*?\?>', '', svg_content)
                try:
                    root = ET.fromstring(clean_content)
                except ET.ParseError:
                    texts = re.findall(r'>\s*([0-9A-Z]{1,4})\s*<', svg_content)
                    return ",".join(texts)

            # Detectar namespace
            ns = {}
            if root.tag.startswith('{'):
                uri = root.tag.split('}')[0].strip('{')
                ns = {'ns': uri}

            text_elements_data = []

            # Buscar texto con o sin namespace
            query = './/ns:text' if ns else './/text'
            all_texts = root.findall(query, ns)

            for text_elem in all_texts:
                try:
                    x = float(text_elem.get('x', 0))
                    y = float(text_elem.get('y', 0))

                    current_text = ""
                    # Buscar tspan con o sin namespace
                    tspan_query = './/ns:tspan' if ns else './/tspan'
                    tspan = text_elem.find(tspan_query, ns)

                    if tspan is not None:
                        current_text = tspan.text or ""
                    else:
                        current_text = text_elem.text or ""

                    if clean_text := current_text.strip():
                        if len(clean_text) <= 4: # Asumir que terminales son cortos
                            text_elements_data.append({
                                'x': x,
                                'y': y,
                                'text': clean_text
                            })
                except ValueError:
                    continue

            if not text_elements_data:
                return ""

            # ORDENAMIENTO ESPACIAL: Columna por columna (X), luego Fila por fila (Y)
            def sort_key(item):
                x = item['x']
                y = item['y']
                col_x = round(x / 5) * 5 # Tolerancia 5px
                return (col_x, y)

            sorted_texts = sorted(text_elements_data, key=sort_key)

            sorted_texts = sorted(text_elements_data, key=sort_key)

            result = ",".join([item['text'] for item in sorted_texts])
            return result

        except Exception as e:
            print(f"Error extrayendo terminales de SVG: {e}")
            return ""
    def _apply_terminal_labels_to_svg(self, svg_content):
        """
        Reemplaza los textos de terminales en el SVG con los valores personalizados del usuario,
        preservando el SVG original intacto (namespaces, atributos Inkscape, estructura).

        Estrategia:
          - ET se usa SOLO PARA LECTURA: obtener coordenadas (x,y) y texto actual de cada <text>.
          - Los reemplazos se hacen como operaciones de string sobre svg_content original,
            encontrando la posición exacta de cada ocurrencia y reemplazando de atrás hacia adelante
            (para que los offsets anteriores no se invaliden).
          - Esto evita ET.tostring(), que altera namespaces y estructura del SVG y rompe cairosvg.
        """
        if not hasattr(self, 'label_data') or not self.label_data.get('terminals'):
            return svg_content

        try:
            terminals_raw = self.label_data['terminals']
            # Algunos proyectos guardan los terminales como lista; el SVG necesita texto
            if isinstance(terminals_raw, (list, tuple)):
                terminals_str = ','.join(str(t) for t in terminals_raw)
            else:
                terminals_str = str(terminals_raw)
            terminals_str = terminals_str.replace('-', ',').replace(' ', ',').replace(';', ',')
            user_terminals = [t.strip() for t in terminals_str.split(',') if t.strip()]
            if not user_terminals:
                return svg_content

            # Parsear con ET solo para leer coordenadas — nunca para escribir
            try:
                clean = re.sub(r'<\?xml[^>]*\?>', '', svg_content)
                root = ET.fromstring(clean)
            except ET.ParseError:
                return svg_content

            ns = {}
            if root.tag.startswith('{'):
                uri = root.tag.split('}')[0].strip('{')
                ns = {'ns': uri}

            text_elements_data = []
            query = './/ns:text' if ns else './/text'
            for text_elem in root.findall(query, ns):
                try:
                    x = float(text_elem.get('x', '0').split()[0])
                    y = float(text_elem.get('y', '0').split()[0])
                    tspan_query = './/ns:tspan' if ns else './/tspan'
                    tspan = text_elem.find(tspan_query, ns)
                    current_text = (tspan.text if tspan is not None else text_elem.text) or ''
                    clean_text = current_text.strip()
                    if clean_text and len(clean_text) <= 4:
                        text_elements_data.append({
                            'x': x, 'y': y,
                            'original': clean_text,
                            'has_tspan': tspan is not None
                        })
                except (ValueError, AttributeError):
                    continue

            if not text_elements_data:
                return svg_content

            # Mismo orden que extract_terminal_labels_from_svg (tolerancia 5px)
            sorted_texts = sorted(text_elements_data,
                                  key=lambda item: (round(item['x'] / 5) * 5, item['y']))

            # Encontrar la posición exacta (start, end) de cada ocurrencia en el string original
            # y registrar el nuevo texto. orig_count lleva cuenta de cuántas veces ya usamos
            # cada texto original, para distinguir duplicados (e.g. dos terminales "1").
            replacements_positions = []  # [(start, end, nuevo_texto), ...]
            orig_count = {}

            for i, item in enumerate(sorted_texts):
                if i >= len(user_terminals):
                    break
                original = item['original']
                nuevo = user_terminals[i]
                has_tspan = item['has_tspan']
                n = orig_count.get(original, 0)  # n-ésima ocurrencia a sustituir

                if has_tspan:
                    pattern = r'(<tspan\b[^>]*>)(' + re.escape(original) + r')(</tspan>)'
                else:
                    pattern = r'(<text\b[^>]*>)(' + re.escape(original) + r')(</text>)'

                count = 0
                for m in re.finditer(pattern, svg_content):
                    if count == n:
                        replacements_positions.append((m.start(2), m.end(2), nuevo))
                        break
                    count += 1

                orig_count[original] = n + 1

            # Reemplazar de atrás hacia adelante para no invalidar offsets anteriores
            replacements_positions.sort(key=lambda r: r[0], reverse=True)
            result = svg_content
            for start, end, nuevo in replacements_positions:
                result = result[:start] + nuevo + result[end:]

            return result

        except Exception as e:
            print(f"Error reemplazando textos en SVG: {e}")
            return svg_content

    def _apply_power_supply_values_to_svg(self, svg_content):
        """Reemplaza los valores de voltaje, amperios y potencia en el SVG de la fuente."""
        if not self.svg_file or "power_supply_dc" not in self.svg_file.lower():
            return svg_content

        v = self.label_data.get('voltaje', '24')
        a = self.label_data.get('amperios', '10')
        w = self.label_data.get('potencia', '240')

        # Patrones específicos detectados en POWER_SUPPLY_DC.svg
        # Buscamos reemplazos que mantengan la estructura del tspan
        # Usamos regex para atrapar el contenido del tspan sea cual sea el id

        # Voltaje: 24DC
        svg_content = re.sub(r'>(24DC|[\d.]+DC)<', f'>{v}DC<', svg_content)
        # Amperios: 10A
        svg_content = re.sub(r'>(10A|[\d.]+A)<', f'>{a}A<', svg_content)
        # Watts: 240W
        svg_content = re.sub(r'>(240W|[\d.]+W)<', f'>{w}W<', svg_content)

        return svg_content

    def clear_label(self):
        """Limpia las etiquetas del canvas"""
        # MÉTODO 1: Limpiar por tag único (MÁS CONFIABLE)
        label_tag = f"label_{id(self)}"
        self.canvas.delete(label_tag)

        # MÉTODO 2: Limpiar por IDs individuales como respaldo
        if hasattr(self, 'label_ids') and self.label_ids:
            for label_id in self.label_ids:
                try:
                    self.canvas.delete(label_id)
                except:
                    pass  # Ignorar si ya fue eliminado

        # Solo limpiar elementos MUY ESPECÍFICOS de este componente
        # (Eliminar el área de búsqueda agresiva que causaba conflictos)
        try:
            # Diccionario de posicionamiento O(1) en lugar de elif chain O(3)
            # Mapeo directo de tipos de componentes a funciones de posicionamiento
            label_positioners = {
                "fase": lambda: self._get_fase_label_position(),  # Posición especial por punto de conexión
                "conxn": lambda: ((self.x + self.size[0] + 5) * self.canvas.zoom_level,
                                 (self.y + 5) * self.canvas.zoom_level),  # Arriba-derecha
                "conxn2": lambda: ((self.x + self.size[0] + 5) * self.canvas.zoom_level,
                                  (self.y + 5) * self.canvas.zoom_level)  # Arriba-derecha
            }

            # Lookup O(1) para posición de etiqueta, fallback a posición normal
            positioner_func = label_positioners.get(self.component_type)
            if positioner_func:
                label_x, label_y = positioner_func()
            else:
                # Posición normal: a la derecha del componente
                label_x = (self.x + self.size[0] + 5) * self.canvas.zoom_level
                label_y = self.y * self.canvas.zoom_level

            # Buscar en área MUY PEQUEÑA y específica (solo 30x30 px)
            area_items = self.canvas.find_overlapping(
                label_x - 5, label_y - 5,
                label_x + 150, label_y + 60  # Área más pequeña y específica
            )

            for item in area_items:
                if self.canvas.type(item) == 'text':
                    # VERIFICACIÓN TRIPLE: Solo eliminar si el elemento tiene nuestro tag específico
                    try:
                        item_tags = self.canvas.gettags(item)
                        if f"label_{id(self)}" in item_tags:
                            self.canvas.delete(item)
                    except:
                        pass  # Ignorar errores de verificación

        except Exception as e:
            # Si falla la limpieza específica, solo usar métodos 1 y 2
            pass

        # Resetear lista de IDs
        self.label_ids = []

    def refresh_display(self):
        """Actualiza la visualización del componente para modo oscuro"""
        try:
            # CLAVE: Recargar la imagen con los colores actualizados
            self.load_image(self.svg_path)
            self.draw()
            self.draw_connection_points()
        except Exception as e:

            pass

    def _get_available_positions(self):
        """Detecta las posiciones disponibles en el SVG (OFF, ON-2, ON-3, etc.)."""
        positions = ['OFF']  # Por defecto siempre hay OFF

        # Construir path completo al SVG
        folder = self.category.lower() if self.category else ""
        full_path = Path(self.svg_path) / folder / self.svg_file if self.svg_file else None

        if not full_path or not full_path.exists():
            return positions

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()

            # Buscar capas ON-N (ON-2, ON-3, ON-4...)
            matches = re.findall(r'inkscape:label="(ON-\d+)"', svg_content)
            for match in sorted(matches, key=lambda x: int(x.split('-')[1])):
                if match not in positions:
                    positions.append(match)

            # Si no hay ON-N pero hay ON, usar formato simple
            if len(positions) == 1 and 'inkscape:label="ON"' in svg_content:
                positions.append('ON')
        except Exception:
            pass

        return positions

class TextComponent:
    """Clase para manejar componentes de texto que se pueden mover como cualquier componente."""

    def __init__(self, canvas, text, font_size, x, y, color=None, anchor="center", bold=False, rotation=0):
        self.canvas = canvas
        self.text = text
        self.font_size = font_size
        self.x = x
        self.y = y
        self.anchor = anchor
        self.bold = bold
        self.rotation = rotation % 360

        # Color por defecto inteligente para modo oscuro
        if color is None:
            color = self._get_default_text_color()
        self.color = color
        self.current_font = "Arial"  # Fuente por defecto
        self.selected = False
        self.canvas_id = None

        self.draw()

                    # TextComponent creado '{text}' en ({x}, {y}) tamaño {font_size}")

    def _get_default_text_color(self):
        """Detecta automáticamente el color de texto apropiado para el tema actual"""
        try:
            # Detectar si estamos en modo oscuro
            canvas_bg = self.canvas.cget("bg")
            is_dark_theme = _is_dark_bg(canvas_bg)

            # En modo oscuro, usar blanco por defecto; en modo claro, negro
            return "#ffffff" if is_dark_theme else "#000000"
        except Exception:
            return "#000000"  # Fallback seguro

    def draw(self):
        """Dibuja el texto en el canvas con adaptación para tema oscuro."""
        if self.canvas_id:
            self.canvas.delete(self.canvas_id)

        # Adaptar color para el tema (oscuro/claro) - Usar fondo real del canvas
        try:
            bg_color = self.canvas.cget("bg")
            adapted_color = adapt_color_for_display(self.color, canvas_bg=bg_color)
        except Exception:
            adapted_color = adapt_color_for_display(self.color)
        except Exception:
            adapted_color = self.color  # Fallback al color original

        scaled_font_size = int(self.font_size * self.canvas.zoom_level)

        font_style = ("Arial", scaled_font_size)
        if getattr(self, 'bold', False):
            font_style = ("Arial", scaled_font_size, "bold")

        self.canvas_id = self.canvas.create_text(
            self.x * self.canvas.zoom_level, self.y * self.canvas.zoom_level,
            text=self.text,
            font=font_style,
            fill=adapted_color,
            anchor=self.anchor,
            angle=self.rotation
        )

        # Marcar como componente seleccionable
        self.canvas.addtag_withtag(f"text_component_{id(self)}", self.canvas_id)

    def adapt_color_for_display(self, original_color):
        """Adapta un color para la visualización según el modo activo - delegando a utility_functions"""
        return adapt_color_for_display(original_color, self.canvas.cget("bg"))

    def select(self):
        """Selecciona el componente de texto."""
        # BLOQUEO HOJA REPORTES: No permitir selección ni recuadro en reportes
        try:
            if hasattr(self.canvas, 'app') and hasattr(self.canvas.app, 'project'):
                sheet = self.canvas.app.project.get_active_sheet()
                if sheet and (not getattr(sheet, 'editable', True) or sheet.name in AppConstants.NON_EDITABLE_SHEETS):
                    self.selected = False
                    return
        except Exception:
            pass

        self.selected = True

        bbox = self.canvas.bbox(self.canvas_id)
        if bbox:
            self.selection_rect = self.canvas.create_rectangle(
                bbox[0]-5, bbox[1]-5, bbox[2]+5, bbox[3]+5,
                outline="", width=1, fill="", tags="selection"
            )

    def move(self, dx, dy):
        """Mueve el componente de texto con manejo correcto de zoom_level."""
        # AJUSTAR MOVIMIENTO POR ZOOM - Igual que en evaPr_OK.py-MALO
        # Los dx, dy vienen en coordenadas del mundo, necesitamos convertirlos a canvas escalado
        adjusted_dx = dx * self.canvas.zoom_level
        adjusted_dy = dy * self.canvas.zoom_level

        self.x += dx  # Mantener coordenadas del mundo
        self.y += dy
        self.canvas.move(self.canvas_id, adjusted_dx, adjusted_dy)

        if self.selected and hasattr(self, 'selection_rect'):
            self.canvas.move(self.selection_rect, adjusted_dx, adjusted_dy)

    def set_position(self, x, y):
        """Establece la posición del texto."""
        self.x = x
        self.y = y
        self.canvas.coords(self.canvas_id, x, y)

    def delete(self):
        """Elimina el componente de texto del canvas."""
        if self.canvas_id:
            self.canvas.delete(self.canvas_id)
        if hasattr(self, 'selection_rect'):
            self.canvas.delete(self.selection_rect)

    def get_bounds(self):
        """Retorna los límites del texto para selección."""
        return self.canvas.bbox(self.canvas_id)

    def contains_point(self, x, y):
        """Verifica si el punto está dentro del texto."""
        bbox = self.get_bounds()
        if bbox:
            # Convertir coordenadas del mundo a coordenadas del canvas (escaladas)
            canvas_x = x * self.canvas.zoom_level
            canvas_y = y * self.canvas.zoom_level
            return bbox[0] <= canvas_x <= bbox[2] and bbox[1] <= canvas_y <= bbox[3]
        return False

    def update_text(self, new_text):
        """Actualiza el contenido del texto."""
        self.text = new_text
        self.canvas.itemconfig(self.canvas_id, text=new_text, angle=self.rotation)

        if self.selected and hasattr(self, 'selection_rect'):
            self.canvas.delete(self.selection_rect)

            bbox = self.canvas.bbox(self.canvas_id)
            if bbox:
                self.selection_rect = self.canvas.create_rectangle(
                    bbox[0]-5, bbox[1]-5, bbox[2]+5, bbox[3]+5,
                    outline="", width=1, fill="", tags="selection"
                )

    def rotate(self, angle):
        """Rota el texto en el ángulo indicado en grados."""
        self.rotation = (self.rotation + angle) % 360
        if self.canvas_id:
            self.canvas.itemconfig(self.canvas_id, angle=self.rotation)
        if self.selected and hasattr(self, 'selection_rect'):
            self.canvas.delete(self.selection_rect)
            bbox = self.canvas.bbox(self.canvas_id)
            if bbox:
                self.selection_rect = self.canvas.create_rectangle(
                    bbox[0]-5, bbox[1]-5, bbox[2]+5, bbox[3]+5,
                    outline="", width=1, fill="", tags="selection"
                )

    def update_font_size(self, new_size):
        """Actualiza el tamaño de fuente del texto."""
        self.font_size = new_size
        # Usar la fuente actual si está disponible, sino usar Arial por defecto
        current_font = getattr(self, 'current_font', 'Arial')

        # Calcular tamaño escalado
        scaled_font_size = int(new_size * self.canvas.zoom_level)

        font_style = (current_font, scaled_font_size)
        if getattr(self, 'bold', False):
            font_style = (current_font, scaled_font_size, "bold")

        self.canvas.itemconfig(self.canvas_id, font=font_style, angle=self.rotation)

        # NO CAMBIAR EL COLOR - mantener la adaptación existente

    def update_color(self, new_color):
        """Actualiza el color del texto con adaptación para tema oscuro."""
        self.color = new_color
        # Adaptar color para el tema (oscuro/claro) - COMO EL CROSSHAIR
        try:
            adapted_color = self.adapt_color_for_display(new_color)
            self.canvas.itemconfig(self.canvas_id, fill=adapted_color)
        except Exception:
            # Fallback al color original si falla la adaptación
            self.canvas.itemconfig(self.canvas_id, fill=new_color)

    def update_font(self, new_font):
        """Actualiza la fuente del texto."""
        self.current_font = new_font  # Guardar la fuente actual

        # Calcular tamaño escalado
        scaled_font_size = int(self.font_size * self.canvas.zoom_level)

        font_style = (new_font, scaled_font_size)
        if getattr(self, 'bold', False):
            font_style = (new_font, scaled_font_size, "bold")

        self.canvas.itemconfig(self.canvas_id, font=font_style, angle=self.rotation)

    def to_dict(self):
        """Serializa el componente de texto a un diccionario."""
        return {
            "type": "text",
            "text": self.text,
            "font_size": self.font_size,
            "x": self.x,
            "y": self.y,
            "color": self.color,
            "bold": getattr(self, 'bold', False),
            "rotation": self.rotation
        }

    @classmethod
    def from_dict(cls, canvas, data):
        """Crea un componente de texto desde un diccionario."""
        return cls(
            canvas=canvas,
            text=data["text"],
            font_size=data["font_size"],
            x=data["x"],
            y=data["y"],
            color=data.get("color"),
            bold=data.get("bold", False),
            rotation=data.get("rotation", 0)
        )
class ImageComponent:
    """Clase para manejar imágenes (logo) que se pueden mover y escalar con zoom."""
    def __init__(self, canvas, image_path, x, y, size=None):
        self.canvas = canvas
        self.image_path = image_path
        self.x = x
        self.y = y
        self.size = size # [w, h]
        self.canvas_id = None
        self.photo = None
        self.original_image = None
        self.load_image()

    def load_image(self):
        try:
            from PIL import Image
            self.original_image = Image.open(self.image_path)
            if self.size:
                self.original_image = self.original_image.resize(self.size, Image.Resampling.LANCZOS)
            else:
                self.size = [self.original_image.width, self.original_image.height]
        except Exception as e:
            print(f"Error cargando imagen {self.image_path}: {e}")

    def draw(self):
        if not self.original_image:
            return

        from PIL import ImageTk, Image
        zoom = getattr(self.canvas, 'zoom_level', 1.0)

        new_w = int(self.size[0] * zoom)
        new_h = int(self.size[1] * zoom)

        if new_w > 0 and new_h > 0:
            display_img = self.original_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(display_img)

            if self.canvas_id:
                self.canvas.delete(self.canvas_id)

            self.canvas_id = self.canvas.create_image(
                self.x * zoom,
                self.y * zoom,
                image=self.photo,
                anchor="center",
                tags="image_comp"
            )

    def move(self, dx, dy):
        self.x += dx
        self.y += dy
        self.draw()

    def contains_point(self, x, y):
        w, h = self.size[0], self.size[1]
        return (self.x - w/2 <= x <= self.x + w/2 and
                self.y - h/2 <= y <= self.y + h/2)

    def to_dict(self):
        data = {
            "type": "image",
            "image_path": str(self.image_path),
            "x": self.x,
            "y": self.y,
            "size": self.size
        }
        # Algunas imágenes se regeneran desde un SVG al exportar a DXF.
        # El PNG de pantalla puede ser temporal, por lo que se debe conservar
        # también su origen vectorial al guardar y volver a abrir el proyecto.
        if getattr(self, "source_svg", None):
            data["source_svg"] = self.source_svg
        return data

    @classmethod
    def from_dict(cls, canvas, data):
        component = cls(
            canvas=canvas,
            image_path=data["image_path"],
            x=data["x"],
            y=data["y"],
            size=data.get("size")
        )
        if data.get("source_svg"):
            component.source_svg = data["source_svg"]
        return component

    def delete(self):
        if self.canvas_id:
            self.canvas.delete(self.canvas_id)

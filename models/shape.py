import math
import tkinter as tk
# Para adaptar colores al modo oscuro/claro
from utils.utility_functions import adapt_color_for_display
from typing import Optional, List, Tuple
from utils.utils import load_medidas_config

# Secciones comerciales por defecto de canaleta ranurada (ancho x alto en mm)
SECCIONES_CANALETA_POR_DEFECTO = [
    "20x20", "25x25", "40x40", "40x60", "40x80",
    "60x40", "60x60", "60x80", "80x60", "100x60", "100x80",
]

def parse_seccion_canaleta(texto) -> Optional[Tuple[float, float]]:
    """Interpreta una sección comercial tipo '40x60' -> (40.0, 60.0). Devuelve None si es inválida."""
    if texto is None:
        return None
    if isinstance(texto, (tuple, list)) and len(texto) >= 2:
        try:
            return (float(texto[0]), float(texto[1]))
        except (TypeError, ValueError):
            return None
    limpio = str(texto).strip().lower().replace("×", "x").replace("*", "x").replace(" ", "")
    if "x" not in limpio:
        return None
    partes = limpio.split("x")
    try:
        return (float(partes[0]), float(partes[1]))
    except (ValueError, IndexError):
        return None

def formatear_seccion_canaleta(ancho: float, alto: float) -> str:
    """Devuelve el identificador de sección en mayúsculas, p.ej. '40X60'."""
    def _fmt(v):
        return str(int(round(v)))
    return f"{_fmt(ancho)}X{_fmt(alto)}"

def get_secciones_canaleta() -> List[str]:
    """Catálogo de secciones comerciales configurado en medidas.json."""
    config_can = load_medidas_config().get("configuracion_formas", {}).get("canaleta", {})
    secciones = config_can.get("secciones_comerciales") or SECCIONES_CANALETA_POR_DEFECTO
    validas = []
    for s in secciones:
        if parse_seccion_canaleta(s):
            validas.append(str(s).strip())
    return validas

def _seccion_canaleta_config(config_can: dict) -> Tuple[float, float]:
    """Sección estándar configurada; si no existe, deriva de 'ancho_estandar'."""
    dims = parse_seccion_canaleta(config_can.get("seccion_estandar"))
    if dims:
        return dims
    ancho = config_can.get("ancho_estandar", 40) or 40
    return (float(ancho), float(ancho))

def _transform_bbox_for_canvas(canvas: tk.Canvas, bbox: Tuple[float, float, float, float]) -> Tuple[int, int, int, int]:
    """
    Transforma un bbox en coordenadas mundo a coordenadas del canvas (incluye zoom).
    NO resta el offset de pan (scroll), ya que Tkinter lo maneja nativamente.
    """
    try:
        from utils.coordinates import world_to_canvas_coords
        x1, y1 = world_to_canvas_coords(bbox[0], bbox[1], canvas)
        x2, y2 = world_to_canvas_coords(bbox[2], bbox[3], canvas)
        return int(x1), int(y1), int(x2), int(y2)
    except Exception:
        zoom = getattr(canvas, 'zoom_level', 1.0)
        return int(bbox[0] * zoom), int(bbox[1] * zoom), int(bbox[2] * zoom), int(bbox[3] * zoom)

class Circle:
    """Representa un círculo en el canvas - IDÉNTICO AL ORIGINAL"""
    def __init__(self, x: float, y: float, radius: float, canvas_id: Optional[int] = None):
        self.x = x
        self.y = y
        self.radius = radius
        self.canvas_id = canvas_id
        self.selected = False
        self.shape_type = "circle"
        self.metadata = {}
        self.label = "" # Etiqueta de texto opcional

    def get_bbox(self) -> Tuple[float, float, float, float]:
        """Retorna las coordenadas del bounding box - IDÉNTICO AL ORIGINAL"""
        return (
            self.x - self.radius,
            self.y - self.radius,
            self.x + self.radius,
            self.y + self.radius
        )

    def contains_point(self, x: float, y: float) -> bool:
        """Verifica si un punto está dentro del círculo - IDÉNTICO AL ORIGINAL"""
        distance = math.sqrt((x - self.x)**2 + (y - self.y)**2)
        return distance <= self.radius

    def move(self, dx: float, dy: float):
        """Mueve el círculo por dx, dy"""
        self.x += dx
        self.y += dy

    def resize(self, new_radius: float):
        """Cambia el radio del círculo"""
        medidas = load_medidas_config()
        min_r = medidas.get("configuracion_formas", {}).get("circulo", {}).get("radio_minimo", 5.0)
        self.radius = max(min_r, new_radius)

    def to_dict(self) -> dict:
        """Serializa el círculo a un diccionario"""
        return {
            "type": self.shape_type,
            "x": self.x,
            "y": self.y,
            "radius": self.radius,
            "outline": getattr(self, 'outline', "#000000"),
            "outline_width": getattr(self, 'outline_width', 2),
            "fill": getattr(self, 'fill', ""),
            "metadata": getattr(self, 'metadata', {}),
            "label": getattr(self, 'label', "")
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Circle':
        """Crea un círculo desde un diccionario"""
        circle = cls(data["x"], data["y"], data["radius"])
        circle.outline = data.get("outline", "#000000")
        circle.outline_width = data.get("outline_width", 2)
        circle.fill = data.get("fill", "")
        circle.metadata = data.get("metadata", {})
        circle.label = data.get("label", "")
        return circle

    def draw(self, canvas: tk.Canvas):
        """Dibuja el círculo en el canvas y guarda el canvas_id."""
        bbox = self.get_bbox()
        # Transformar bbox a coordenadas de pantalla según zoom/world_to_screen
        screen_bbox = _transform_bbox_for_canvas(canvas, bbox)

        outline = getattr(self, 'outline', None)
        if outline is None: # Si es None, usamos color adaptado
            base = getattr(self, 'COLOR_CIRCLE', '#000000') if hasattr(self, 'COLOR_CIRCLE') else '#000000'
            outline = adapt_color_for_display(base, canvas.cget('bg'))
        # Si outline == "", tkinter lo interpreta como sin borde (correcto)
        width = getattr(self, 'outline_width', 2)
        fill = getattr(self, 'fill', '')
        try:
            self.canvas_id = canvas.create_oval(*screen_bbox, outline=outline, width=width, fill=fill)
            if self.label:
                tx, ty = _transform_bbox_for_canvas(canvas, (self.x, self.y, self.x, self.y))[:2]
                canvas.create_text(tx, ty, text=self.label, fill="white" if fill else "black", font=("Arial", int(8 * getattr(canvas, 'zoom_level', 1.0))))
        except Exception:
            # Intentar sin fill si falla
            self.canvas_id = canvas.create_oval(*screen_bbox, outline=outline, width=width, fill="")

class Rect:
    """Representa un rectángulo en el canvas - IDÉNTICO AL ORIGINAL"""
    def __init__(self, x: float, y: float, width: float, height: float, canvas_id: Optional[int] = None):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.canvas_id = canvas_id
        self.selected = False
        self.shape_type = "rect"
        self.metadata = {}
        self.label = "" # Etiqueta de texto opcional

    def get_bbox(self) -> Tuple[float, float, float, float]:
        """Retorna las coordenadas del bounding box - IDÉNTICO AL ORIGINAL"""
        return (
            self.x - self.width/2,
            self.y - self.height/2,
            self.x + self.width/2,
            self.y + self.height/2
        )

    def contains_point(self, x: float, y: float) -> bool:
        """Verifica si un punto está dentro del rectángulo - IDÉNTICO AL ORIGINAL"""
        return (
            self.x - self.width/2 <= x <= self.x + self.width/2 and
            self.y - self.height/2 <= y <= self.y + self.height/2
        )

    def move(self, dx: float, dy: float):
        """Mueve el rectángulo por dx, dy"""
        self.x += dx
        self.y += dy

    def resize(self, new_width: float):
        """Cambia el tamaño del rectángulo manteniendo proporción"""
        medidas = load_medidas_config()
        config_rect = medidas.get("configuracion_formas", {}).get("rectangulo", {})
        ratio = config_rect.get("relacion_aspecto", 1.5)
        min_size = config_rect.get("tamano_minimo", 10.0)

        # Mantener relación de aspecto (por defecto 3:2 -> 1.5)
        self.width = max(min_size, new_width * ratio)
        self.height = max(min_size, new_width)

    def to_dict(self) -> dict:
        """Serializa el rectángulo a un diccionario"""
        return {
            "type": self.shape_type,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "outline": getattr(self, 'outline', "#000000"),
            "outline_width": getattr(self, 'outline_width', 2),
            "fill": getattr(self, 'fill', ""),
            "metadata": getattr(self, 'metadata', {}),
            "label": getattr(self, 'label', "")
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Rect':
        """Crea un rectángulo desde un diccionario"""
        rect = cls(data["x"], data["y"], data["width"], data["height"])
        rect.outline = data.get("outline", "#000000")
        rect.outline_width = data.get("outline_width", 2)
        rect.fill = data.get("fill", "")
        rect.metadata = data.get("metadata", {})
        rect.label = data.get("label", "")
        return rect

    def draw(self, canvas: tk.Canvas):
        """Dibuja el rectángulo en el canvas y guarda el canvas_id."""
        bbox = self.get_bbox()
        screen_bbox = _transform_bbox_for_canvas(canvas, bbox)
        outline = getattr(self, 'outline', None)
        if outline is None:
            outline = adapt_color_for_display('#000000', canvas.cget('bg'))
        width = getattr(self, 'outline_width', 2)
        fill = getattr(self, 'fill', '')
        try:
            self.canvas_id = canvas.create_rectangle(*screen_bbox, outline=outline, width=width, fill=fill)
            if self.label:
                tx, ty = _transform_bbox_for_canvas(canvas, (self.x, self.y, self.x, self.y))[:2]
                canvas.create_text(tx, ty, text=self.label, fill="white" if fill else "black", font=("Arial", int(8 * getattr(canvas, 'zoom_level', 1.0))))
        except Exception:
            self.canvas_id = canvas.create_rectangle(*screen_bbox, outline=outline, width=width, fill="")

class RoundedRect(Rect):
    """Rectángulo con esquinas redondeadas, compatible con Rect."""
    def __init__(self, x: float, y: float, width: float, height: float, radius: float, canvas_id: Optional[int] = None):
        super().__init__(x, y, width, height, canvas_id)
        self.radius = max(0, min(radius, width / 2, height / 2))
        self.shape_type = "rounded_rect"

    def draw(self, canvas: tk.Canvas):
        screen_points = self._screen_points(canvas)
        outline = getattr(self, 'outline', '#000000')
        width = getattr(self, 'outline_width', 2)
        fill = getattr(self, 'fill', '')
        self.canvas_id = canvas.create_polygon(
            *screen_points, outline=outline, width=width, fill=fill
        )

    def _screen_points(self, canvas: tk.Canvas):
        x1, y1, x2, y2 = self.get_bbox()
        radius = self.radius
        points = []
        corner_centers = (
            (x1, y1, math.pi / 2, 0),
            (x2, y1, math.pi, math.pi / 2),
            (x2, y2, -math.pi / 2, -math.pi),
            (x1, y2, 0, -math.pi / 2),
        )
        for center_x, center_y, start_angle, end_angle in corner_centers:
            for step in range(9):
                angle = start_angle + (end_angle - start_angle) * step / 8
                points.extend((
                    center_x + radius * math.cos(angle),
                    center_y + radius * math.sin(angle),
                ))
        screen_points = []
        for index in range(0, len(points), 2):
            sx, sy = _transform_bbox_for_canvas(
                canvas, (points[index], points[index + 1], points[index], points[index + 1])
            )[:2]
            screen_points.extend((sx, sy))
        return screen_points

    def to_dict(self) -> dict:
        data = super().to_dict()
        data['type'] = self.shape_type
        data['radius'] = self.radius
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'RoundedRect':
        rounded = cls(
            data['x'], data['y'], data['width'], data['height'],
            data.get('radius', 0)
        )
        rounded.outline = data.get('outline', '#000000')
        rounded.outline_width = data.get('outline_width', 2)
        rounded.fill = data.get('fill', '')
        rounded.metadata = data.get('metadata', {})
        rounded.label = data.get('label', '')
        return rounded

class MultipoleBorner(Rect):
    """Representa una borna multipolo (2P, 3P, 4P) con divisiones internas."""
    def __init__(self, x: float, y: float, width: float, height: float, poles: int, canvas_id: Optional[int] = None):
        super().__init__(x, y, width, height, canvas_id)
        self.shape_type = "multipole_borner"
        self.poles = poles
        self.inner_ids = []

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["type"] = "multipole_borner"
        d["poles"] = self.poles
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'MultipoleBorner':
        poles = data.get("poles", 1)
        borner = cls(data["x"], data["y"], data["width"], data["height"], poles)
        borner.outline = data.get("outline", "black")
        borner.outline_width = data.get("outline_width", 1.5)
        borner.fill = data.get("fill", "#afc6e9")
        borner.metadata = data.get("metadata", {})
        borner.label = data.get("label", "")
        return borner

    def draw(self, canvas: tk.Canvas):
        # 1. Dibujar rectángulo exterior
        super().draw(canvas)
        # 2. Dibujar divisiones y tornillos internos
        self.update_inner_graphics(canvas)

    def update_inner_graphics(self, canvas: tk.Canvas):
        """Redibuja las partes internas cuando el bloque de borna se mueve/redimensiona, sin recrear el rectángulo base"""
        # Limpiar líneas previas
        if hasattr(self, 'inner_ids'):
            for i_id in self.inner_ids:
                try: canvas.delete(i_id)
                except: pass
        self.inner_ids = []

        try:
            zoom = getattr(canvas, 'zoom_level', 1.0)
            bbox = self.get_bbox()
            x1, y1, x2, y2 = _transform_bbox_for_canvas(canvas, bbox)
            sw, sh = x2 - x1, y2 - y1

            # Dividir horizontalmente en 'poles' partes
            pole_w = sw / self.poles

            for i in range(1, self.poles):
                lx = x1 + i * pole_w
                line_id = canvas.create_line(
                    lx, y1, lx, y2,
                    fill=getattr(self, 'outline', 'black'),
                    width=getattr(self, 'outline_width', 1) * zoom
                )
                self.inner_ids.append(line_id)

            screw_r = min(pole_w, sh) * 0.15  # Radio del círculo
            for i in range(self.poles):
                px = x1 + (i + 0.5) * pole_w
                py = y1 + sh / 2

                # Círculo para el tornillo (oval)
                oval_id = canvas.create_oval(
                    px - screw_r, py - screw_r,
                    px + screw_r, py + screw_r,
                    fill="#cccccc", outline=getattr(self, 'outline', 'black'), width=max(1, int(1 * zoom))
                )
                self.inner_ids.append(oval_id)

        except Exception as e:
            print(f"Error actualizando divisiones de borna multipolo: {e}")

class DinRail(Rect):
    """Representa un Riel DIN con agujeros y perfil - Hereda de Rect para arrastre/selección"""
    def __init__(self, x: float, y: float, width: float, height: float, canvas_id: Optional[int] = None):
        super().__init__(x, y, width, height, canvas_id)
        medidas = load_medidas_config()
        config_din = medidas.get("configuracion_formas", {}).get("riel_din", {})

        self.shape_type = "din_rail"
        self.fill = config_din.get("color_relleno", "#D3D3D3")
        self.outline = "black"
        self.outline_width = config_din.get("ancho_borde", 1.5)
        self.inner_ids = []

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["type"] = "din_rail"
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'DinRail':
        rail = cls(data["x"], data["y"], data["width"], data["height"])
        rail.outline = data.get("outline", "black")
        rail.outline_width = data.get("outline_width", 1.5)
        rail.fill = data.get("fill", "#D3D3D3")
        rail.metadata = data.get("metadata", {})
        rail.label = data.get("label", "")
        return rail

    def _clear_inner_ids(self, canvas: tk.Canvas):
        if hasattr(self, 'inner_ids'):
            for i_id in self.inner_ids:
                try: canvas.delete(i_id)
                except: pass
        self.inner_ids = []

    def _render_din_inner(self, canvas: tk.Canvas):
        """Detalles del Riel DIN (Escalados): perfil OMEGA y ranuras"""
        try:
            zoom = getattr(canvas, 'zoom_level', 1.0)
            bbox = self.get_bbox()
            x1, y1, x2, y2 = _transform_bbox_for_canvas(canvas, bbox)
            sw, sh = x2 - x1, y2 - y1

            # Dibujar siempre y cuando el alto sea visible (> 5px en pantalla)
            if sh > 5 * zoom:
                # Líneas del perfil OMEGA
                l1 = canvas.create_line(x1, y1 + sh*0.15, x2, y1 + sh*0.15, fill="#404040", width=1*zoom)
                l2 = canvas.create_line(x1, y1 + sh*0.30, x2, y1 + sh*0.30, fill="#808080", width=0.5*zoom)
                l3 = canvas.create_line(x1, y2 - sh*0.30, x2, y2 - sh*0.30, fill="#808080", width=0.5*zoom)
                l4 = canvas.create_line(x1, y2 - sh*0.15, x2, y2 - sh*0.15, fill="#101010", width=1*zoom) # Más oscuro simulando sombra
                self.inner_ids.extend([l1, l2, l3, l4])

                # Agujeros (Ranuras ovaladas) - Desde medidas.json
                medidas = load_medidas_config()
                config_din = medidas.get("configuracion_formas", {}).get("riel_din", {})

                slot_w_mundo = config_din.get("ancho_ranura", 15)
                slot_h_mundo = config_din.get("alto_ranura", 6)
                spacing_mundo = config_din.get("espaciado", 25)

                slot_w = slot_w_mundo * zoom
                slot_h = slot_h_mundo * zoom
                spacing = spacing_mundo * zoom

                if sw > spacing:
                    num_slots = int(sw / spacing)
                    # Centrar todos los agujeros
                    start_cx = x1 + (sw - (num_slots - 1) * spacing) / 2
                    for i in range(num_slots):
                        cx = start_cx + i * spacing
                        cy = y1 + sh/2
                        # Usar un óvalo/cápsula
                        slot_id = canvas.create_oval(cx - slot_w/2, cy - slot_h/2, cx + slot_w/2, cy + slot_h/2, outline="#404040", width=1*zoom, fill=canvas.cget('bg'))
                        self.inner_ids.append(slot_id)
        except Exception:
            pass

    def draw(self, canvas: tk.Canvas):
        # Limpiar partes internas anteriores si existían (útil al hacer zoom/pan)
        self._clear_inner_ids(canvas)
        # Dibuja el marco base gris
        super().draw(canvas)
        # Detalles del Riel DIN (Escalados)
        self._render_din_inner(canvas)

    def update_inner_graphics(self, canvas: tk.Canvas):
        """Redibuja las partes internas cuando el perfil base se mueve/redimensiona, sin crear estelas del rectángulo base"""
        self._clear_inner_ids(canvas)
        self._render_din_inner(canvas)

class Canaleta:
    """Canaleta ranurada (bandeja para cables).

    El ancho no es un valor único: la pieza tiene una *sección comercial*
    del tipo 'AxH' (p. ej. '40X60'), donde el primer número es el ancho
    (base, siempre horizontal en el plano 2D) y el segundo el alto.
    """
    def __init__(self, x: float, y: float, largo: float, horizontal: bool = True,
                 canvas_id: Optional[int] = None, seccion=None):
        medidas = load_medidas_config()
        config_can = medidas.get("configuracion_formas", {}).get("canaleta", {})
        largo_minimo = config_can.get("largo_minimo", 40)

        self.x = x
        self.y = y
        self.largo = max(largo_minimo, largo)
        self.horizontal = horizontal
        self.canvas_id = canvas_id
        self.selected = False
        self.shape_type = "canaleta"
        self.metadata = {}
        self.inner_ids = []
        self.fill = config_can.get("color_relleno", "#C0C0C0")
        self.outline = config_can.get("color_borde", "#808080")
        self.outline_width = config_can.get("ancho_borde", 1.5)
        self.label = ""

        # Sección comercial (ancho x alto)
        dims = parse_seccion_canaleta(seccion) or _seccion_canaleta_config(config_can)
        self.ancho_fijo = dims[0]  # ancho de la base (eje X)
        self.alto_fijo = dims[1]   # altura de la canaleta (eje Y)
        self.seccion = formatear_seccion_canaleta(self.ancho_fijo, self.alto_fijo)

    def set_seccion(self, seccion) -> bool:
        """Cambia la sección comercial. Devuelve True si aplicó un cambio real."""
        dims = parse_seccion_canaleta(seccion)
        if not dims:
            return False
        nueva = formatear_seccion_canaleta(*dims)
        if nueva == self.seccion:
            return False
        self.ancho_fijo = dims[0]
        self.alto_fijo = dims[1]
        self.seccion = nueva
        return True

    def get_bbox(self):
        """Retorna bounding box según orientación (el ancho es siempre el eje X)."""
        semi_ancho = getattr(self, 'ancho_fijo', 40) / 2
        semi_alto = getattr(self, 'alto_fijo', getattr(self, 'ancho_fijo', 40)) / 2
        if self.horizontal:
            return (self.x - self.largo/2, self.y - semi_alto, self.x + self.largo/2, self.y + semi_alto)
        else:
            return (self.x - semi_ancho, self.y - self.largo/2, self.x + semi_ancho, self.y + self.largo/2)

    def contains_point(self, x: float, y: float) -> bool:
        """Verifica si punto está dentro"""
        x1, y1, x2, y2 = self.get_bbox()
        return x1 <= x <= x2 and y1 <= y <= y2

    def move(self, dx: float, dy: float):
        """Mueve la canaleta"""
        self.x += dx
        self.y += dy

    def to_dict(self) -> dict:
        return {
            "type": "canaleta",
            "x": self.x,
            "y": self.y,
            "largo": self.largo,
            "horizontal": self.horizontal,
            "seccion": self.seccion,
            "outline": self.outline,
            "outline_width": self.outline_width,
            "fill": self.fill,
            "metadata": self.metadata,
            "label": self.label
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Canaleta':
        canaleta = cls(data["x"], data["y"], data.get("largo", 100),
                       data.get("horizontal", True), seccion=data.get("seccion"))
        canaleta.outline = data.get("outline", "#808080")
        canaleta.outline_width = data.get("outline_width", 1.5)
        canaleta.fill = data.get("fill", "#C0C0C0")
        canaleta.metadata = data.get("metadata", {})
        canaleta.label = data.get("label", "")
        return canaleta

    def _clear_canaleta_inner(self, canvas: tk.Canvas):
        if hasattr(self, 'inner_ids'):
            for i_id in self.inner_ids:
                try: canvas.delete(i_id)
                except: pass
        self.inner_ids = []

    def _render_canaleta_inner(self, canvas: tk.Canvas):
        """Dibuja las líneas internas de la canaleta según orientación"""
        try:
            zoom = getattr(canvas, 'zoom_level', 1.0)
            bbox = self.get_bbox()
            x1, y1, x2, y2 = _transform_bbox_for_canvas(canvas, bbox)

            medidas = load_medidas_config()
            offsets = medidas.get("configuracion_formas", {}).get("canaleta", {}).get("offsets_linea_interna", [0.33, 0.67])

            if self.horizontal:
                line1_y = y1 + (y2 - y1) * offsets[0]
                line2_y = y1 + (y2 - y1) * offsets[1]
                l1 = canvas.create_line(x1, line1_y, x2, line1_y, fill="#A0A0A0", width=1*zoom)
                l2 = canvas.create_line(x1, line2_y, x2, line2_y, fill="#E0E0E0", width=1*zoom)
                self.inner_ids.extend([l1, l2])
            else:
                line1_x = x1 + (x2 - x1) * offsets[0]
                line2_x = x1 + (x2 - x1) * offsets[1]
                l1 = canvas.create_line(line1_x, y1, line1_x, y2, fill="#A0A0A0", width=1*zoom)
                l2 = canvas.create_line(line2_x, y1, line2_x, y2, fill="#E0E0E0", width=1*zoom)
                self.inner_ids.extend([l1, l2])
        except:
            pass

    def draw(self, canvas: tk.Canvas):
        """Dibuja canaleta con líneas internas"""
        self._clear_canaleta_inner(canvas)

        bbox = self.get_bbox()
        screen_bbox = _transform_bbox_for_canvas(canvas, bbox)
        x1, y1, x2, y2 = screen_bbox

        try:
            self.canvas_id = canvas.create_rectangle(x1, y1, x2, y2, outline=self.outline, width=self.outline_width, fill=self.fill)
        except:
            pass

        self._render_canaleta_inner(canvas)

    def update_inner_graphics(self, canvas: tk.Canvas):
        """Actualiza gráficos internos"""
        self._clear_canaleta_inner(canvas)
        self._render_canaleta_inner(canvas)

class Ellipse:
    """Representa una elipse en el canvas - IDÉNTICO AL ORIGINAL"""
    def __init__(self, x: float, y: float, radius_x: float, radius_y: float, canvas_id: Optional[int] = None):
        self.x = x
        self.y = y
        self.radius_x = radius_x  # Radio horizontal
        self.radius_y = radius_y  # Radio vertical
        self.canvas_id = canvas_id
        self.selected = False
        self.shape_type = "ellipse"

    def get_bbox(self) -> Tuple[float, float, float, float]:
        """Retorna las coordenadas del bounding box - IDÉNTICO AL ORIGINAL"""
        return (
            self.x - self.radius_x,
            self.y - self.radius_y,
            self.x + self.radius_x,
            self.y + self.radius_y
        )

    def contains_point(self, x: float, y: float) -> bool:
        """Verifica si un punto está dentro de la elipse - IDÉNTICO AL ORIGINAL"""
        # Ecuación de elipse: (x-h)²/rx² + (y-k)²/ry² <= 1
        dx = (x - self.x) / self.radius_x
        dy = (y - self.y) / self.radius_y
        return (dx * dx + dy * dy) <= 1

    def move(self, dx: float, dy: float):
        """Mueve la elipse por dx, dy"""
        self.x += dx
        self.y += dy

    def resize(self, new_size: float):
        """Cambia el tamaño de la elipse"""
        medidas = load_medidas_config()
        config_el = medidas.get("configuracion_formas", {}).get("elipse", {})
        ratio = config_el.get("relacion_aspecto", 1.5)
        min_size = config_el.get("tamano_minimo", 10.0)

        # Mantener relación de aspecto de elipse (por defecto 1.5)
        self.radius_x = max(min_size, new_size * ratio)
        self.radius_y = max(min_size, new_size)

    def to_dict(self) -> dict:
        """Serializa la elipse a un diccionario"""
        return {
            "type": self.shape_type,
            "x": self.x,
            "y": self.y,
            "radius_x": self.radius_x,
            "radius_y": self.radius_y,
            "outline": getattr(self, 'outline', "#000000"),
            "outline_width": getattr(self, 'outline_width', 2),
            "fill": getattr(self, 'fill', "")
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Ellipse':
        """Crea una elipse desde un diccionario"""
        ellipse = cls(data["x"], data["y"], data["radius_x"], data["radius_y"])
        ellipse.outline = data.get("outline", "#000000")
        ellipse.outline_width = data.get("outline_width", 2)
        ellipse.fill = data.get("fill", "")
        return ellipse

    def draw(self, canvas: tk.Canvas):
        """Dibuja la elipse en el canvas y guarda el canvas_id."""
        bbox = self.get_bbox()
        screen_bbox = _transform_bbox_for_canvas(canvas, bbox)
        outline = getattr(self, 'outline', None)
        if outline is None:
            outline = adapt_color_for_display('#000000', canvas.cget('bg'))
        width = getattr(self, 'outline_width', 2)
        fill = getattr(self, 'fill', '')
        try:
            self.canvas_id = canvas.create_oval(*screen_bbox, outline=outline, width=width, fill=fill)
        except Exception:
            self.canvas_id = canvas.create_oval(*screen_bbox, outline=outline, width=width, fill="")

class Square:
    """Representa un cuadrado en el canvas - IDÉNTICO AL ORIGINAL"""
    def __init__(self, x: float, y: float, side_length: float, canvas_id: Optional[int] = None):
        self.x = x
        self.y = y
        self.side_length = side_length
        self.canvas_id = canvas_id
        self.selected = False
        self.shape_type = "square"

    def get_bbox(self) -> Tuple[float, float, float, float]:
        """Retorna las coordenadas del bounding box - IDÉNTICO AL ORIGINAL"""
        half_side = self.side_length / 2
        return (
            self.x - half_side,
            self.y - half_side,
            self.x + half_side,
            self.y + half_side
        )

    def contains_point(self, x: float, y: float) -> bool:
        """Verifica si un punto está dentro del cuadrado - IDÉNTICO AL ORIGINAL"""
        half_side = self.side_length / 2
        return (
            self.x - half_side <= x <= self.x + half_side and
            self.y - half_side <= y <= self.y + half_side
        )

    def move(self, dx: float, dy: float):
        """Mueve el cuadrado por dx, dy"""
        self.x += dx
        self.y += dy

    def resize(self, new_side: float):
        """Cambia el lado del cuadrado"""
        medidas = load_medidas_config()
        min_s = medidas.get("configuracion_formas", {}).get("cuadrado", {}).get("lado_minimo", 10.0)
        self.side_length = max(min_s, new_side)

    def to_dict(self) -> dict:
        """Serializa el cuadrado a un diccionario"""
        return {
            "type": self.shape_type,
            "x": self.x,
            "y": self.y,
            "side_length": self.side_length,
            "outline": getattr(self, 'outline', "#000000"),
            "outline_width": getattr(self, 'outline_width', 2),
            "fill": getattr(self, 'fill', "")
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Square':
        """Crea un cuadrado desde un diccionario"""
        square = cls(data["x"], data["y"], data["side_length"])
        square.outline = data.get("outline", "#000000")
        square.outline_width = data.get("outline_width", 2)
        square.fill = data.get("fill", "")
        return square

    def draw(self, canvas: tk.Canvas):
        """Dibuja el cuadrado en el canvas y guarda el canvas_id."""
        bbox = self.get_bbox()
        screen_bbox = _transform_bbox_for_canvas(canvas, bbox)
        outline = getattr(self, 'outline', None)
        if outline is None:
            outline = adapt_color_for_display('#000000', canvas.cget('bg'))
        width = getattr(self, 'outline_width', 2)
        fill = getattr(self, 'fill', '')
        try:
            self.canvas_id = canvas.create_rectangle(*screen_bbox, outline=outline, width=width, fill=fill)
        except Exception:
            self.canvas_id = canvas.create_rectangle(*screen_bbox, outline=outline, width=width, fill="")

class Line:
    """Representa una línea en el canvas"""
    def __init__(self, x1: float, y1: float, x2: float, y2: float, canvas_id: Optional[int] = None):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.canvas_id = canvas_id
        self.selected = False
        self.shape_type = "geom_line"
        self.color = "black"
        self.width = 1

    def get_bbox(self) -> Tuple[float, float, float, float]:
        """Retorna las coordenadas del bounding box"""
        return (
            min(self.x1, self.x2),
            min(self.y1, self.y2),
            max(self.x1, self.x2),
            max(self.y1, self.y2)
        )

    def contains_point(self, x: float, y: float) -> bool:
        """Verifica si un punto está cerca de la línea (muy simplificado)"""
        # Por ahora no es crítico para reportes estáticos
        bbox = self.get_bbox()
        return bbox[0] - 5 <= x <= bbox[2] + 5 and bbox[1] - 5 <= y <= bbox[3] + 5

    def move(self, dx: float, dy: float):
        """Mueve la línea por dx, dy"""
        self.x1 += dx
        self.y1 += dy
        self.x2 += dx
        self.y2 += dy

    def to_dict(self) -> dict:
        """Serializa la línea a un diccionario"""
        return {
            "type": self.shape_type,
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "color": self.color,
            "width": self.width
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Line':
        """Crea una línea desde un diccionario"""
        line = cls(data["x1"], data["y1"], data["x2"], data["y2"])
        line.color = data.get("color", "black")
        line.width = data.get("width", 1)
        return line

    def draw(self, canvas: tk.Canvas):
        """Dibuja la línea en el canvas."""
        try:
            zoom = getattr(canvas, 'zoom_level', 1.0)
            coords = [self.x1 * zoom, self.y1 * zoom, self.x2 * zoom, self.y2 * zoom]
        except Exception:
            coords = [self.x1, self.y1, self.x2, self.y2]

        color = adapt_color_for_display(self.color, canvas.cget('bg'))
        arrow = getattr(self, 'arrow', None)
        self.canvas_id = canvas.create_line(*coords, fill=color, width=self.width, arrow=arrow)

class ShapeEditor:
    """
    Maneja la creación y edición de círculos, rectángulos, elipses y cuadrados
    IDÉNTICO AL SHAPE_EDITOR.PY ORIGINAL
    """

    # Constantes de configuración - IDÉNTICAS AL ORIGINAL
    MIN_SIZE = 1
    MAX_SIZE = 100000
    SIZE_CHANGE_RATE = 0.5
    LINE_WIDTH = 2

    COLOR_CIRCLE = "#000000"
    COLOR_RECT = "#000000"
    COLOR_ELLIPSE = "#000000"
    COLOR_SQUARE = "#000000"
    COLOR_SELECTED = "#f1c40f"
    COLOR_PREVIEW = "#95a5a6"

    def __init__(self, canvas: tk.Canvas, shape_manager=None):
        """
        Inicializa el editor de formas

        Args:
            canvas: Canvas de tkinter donde dibujar las formas
            shape_manager: Referencia al ShapeManager para registrar shapes
        """
        self.canvas = canvas
        self.shape_manager = shape_manager

        self.current_mode = None  # 'circle', 'rect', 'ellipse', 'square', or None
        self.shapes: List = []
        self.selected_shape = None

        # Estado de creación
        self.preview_shape = None
        self.creating = False
        self.start_x = 0
        self.start_y = 0
        self.initial_size = 40
        self.current_size = 40  # Tamaño actual durante el arrastre

        # Flag para evitar recursión infinita en eventos de mouse
        self._dragging_in_progress = False

        # Dimensiones específicas por tipo de forma
        self.current_width = 40    # Para rectángulos
        self.current_height = 40   # Para rectángulos
        self.current_radius_x = 40 # Para elipses (radio horizontal)
        self.current_radius_y = 40 # Para elipses (radio vertical)
        self.current_sides = 40     # Para cuadrados (longitud del lado)

        medidas = load_medidas_config()
        config_editor = medidas.get("configuracion_formas", {}).get("editor_formas", {})

        self.MIN_SIZE = config_editor.get("tamano_minimo", 1)
        self.MAX_SIZE = config_editor.get("tamano_maximo", 100000)
        self.SIZE_CHANGE_RATE = config_editor.get("tasa_cambio_tamano", 0.5)
        self.LINE_WIDTH = config_editor.get("ancho_linea", 2)

        # Estado de edición (redimensionamiento)
        self.editing = False
        self.edit_start_y = 0
        self.edit_initial_size = 0

        # Estado de movimiento
        self.moving = False
        self.move_start_x = 0
        self.move_start_y = 0

    def _is_cabinet_2d_sheet(self):
        """Verifica si la hoja activa es la Hoja de Gabinete 2D."""
        try:
            app = getattr(self.canvas, 'app', None)
            if app:
                sheet = app.project.get_active_sheet()
                return sheet and sheet.name == "Hoja de Gabinete 2D"
        except Exception:
            pass
        return False

    def on_right_press(self, event):
        """Maneja el click derecho: en Hoja 2D selecciona y mueve, en otras hojas redimensiona."""
        # Si no hay selección, intentar seleccionar lo que está bajo el cursor
        if not self.selected_shape:
            self._select_shape_at(event.x, event.y)

        if not self.selected_shape or self.current_mode or self.creating:
            return

        # En la Hoja de Gabinete 2D: click derecho = MOVER (sin redimensionar)
        if self._is_cabinet_2d_sheet():
            self.moving = True
            self.move_start_x = event.x
            self.move_start_y = event.y
            self.canvas.focus_set()
            self.canvas.config(cursor="fleur")
            return

        # Comportamiento normal en otras hojas: redimensionar
        self.editing = True
        self.press_x = event.x
        self.press_y = event.y
        center_x = self.selected_shape.x
        center_y = self.selected_shape.y
        try:
            wx, wy = self.canvas.screen_to_world(event.x, event.y)
        except Exception:
            zoom = getattr(self.canvas, 'zoom_level', 1.0)
            wx, wy = event.x / zoom, event.y / zoom
        self.initial_mouse_pos_world = (wx, wy)
        self.initial_mouse_dist = math.sqrt((wx - center_x)**2 + (wy - center_y)**2)
        if self.initial_mouse_dist < 1: self.initial_mouse_dist = 1
        self.initial_dims = {}
        shape_type = self.selected_shape.shape_type
        if shape_type == "circle":
            self.initial_dims['radius'] = self.selected_shape.radius
        elif shape_type == "rect":
            self.initial_dims['width'] = self.selected_shape.width
            self.initial_dims['height'] = self.selected_shape.height
        elif shape_type == "ellipse":
            self.initial_dims['radius_x'] = self.selected_shape.radius_x
            self.initial_dims['radius_y'] = self.selected_shape.radius_y
        elif shape_type == "square":
            self.initial_dims['side_length'] = self.selected_shape.side_length
        self.canvas.config(cursor="sizing")

    def on_right_drag(self, event):
        """Maneja el arrastre con click derecho: en Hoja 2D mueve, en otras hojas redimensiona."""
        # En Hoja de Gabinete 2D: mover el bloque seleccionado
        if self._is_cabinet_2d_sheet():
            if self.moving and self.selected_shape:
                delta_x = event.x - self.move_start_x
                delta_y = event.y - self.move_start_y
                zoom = getattr(self.canvas, 'zoom_level', 1.0)
                self.selected_shape.x += delta_x / zoom
                self.selected_shape.y += delta_y / zoom
                self.move_start_x = event.x
                self.move_start_y = event.y
                self._redraw_shape(self.selected_shape)
            return

        # Comportamiento normal: redimensionar
        if self.editing and self.selected_shape:
            # Calcular centro de la forma
            center_x = self.selected_shape.x
            center_y = self.selected_shape.y

            # Convertir evento a coordenadas mundo
            try:
                wx, wy = self.canvas.screen_to_world(event.x, event.y)
            except Exception:
                zoom = getattr(self.canvas, 'zoom_level', 1.0)
                wx, wy = event.x / zoom, event.y / zoom

            shape_type = self.selected_shape.shape_type

            # Lógica para Rectángulos y Elipses (Independiente)
            if shape_type in ["rect", "ellipse"]:
                # Determinar dirección predominante del arrastre en pantalla
                delta_screen_x = event.x - self.press_x
                delta_screen_y = event.y - self.press_y

                is_vertical = abs(delta_screen_y) > abs(delta_screen_x)

                if is_vertical:
                    # Escalado Vertical
                    initial_dist_y = abs(self.initial_mouse_pos_world[1] - center_y)
                    if initial_dist_y < 0.1: initial_dist_y = 0.1

                    current_dist_y = abs(wy - center_y)
                    scale_y = current_dist_y / initial_dist_y

                    if shape_type == "rect":
                        new_height = max(1.0, self.initial_dims['height'] * scale_y)
                        self.selected_shape.height = new_height
                        # Restaurar ancho original para evitar cambios accidentales
                        self.selected_shape.width = self.initial_dims['width']
                    else: # ellipse
                        new_ry = max(1.0, self.initial_dims['radius_y'] * scale_y)
                        self.selected_shape.radius_y = new_ry
                        self.selected_shape.radius_x = self.initial_dims['radius_x']

                else:
                    # Escalado Horizontal
                    initial_dist_x = abs(self.initial_mouse_pos_world[0] - center_x)
                    if initial_dist_x < 0.1: initial_dist_x = 0.1

                    current_dist_x = abs(wx - center_x)
                    scale_x = current_dist_x / initial_dist_x

                    if shape_type == "rect":
                        new_width = max(1.0, self.initial_dims['width'] * scale_x)
                        self.selected_shape.width = new_width
                        self.selected_shape.height = self.initial_dims['height']
                    else: # ellipse
                        new_rx = max(1.0, self.initial_dims['radius_x'] * scale_x)
                        self.selected_shape.radius_x = new_rx
                        self.selected_shape.radius_y = self.initial_dims['radius_y']

            # Lógica para Círculos y Cuadrados (Uniforme)
            else:
                current_dist = math.sqrt((wx - center_x)**2 + (wy - center_y)**2)
                scale = current_dist / self.initial_mouse_dist

                if shape_type == "circle":
                    new_radius = max(1.0, self.initial_dims['radius'] * scale)
                    self.selected_shape.radius = new_radius
                elif shape_type == "square":
                    new_side = max(1.0, self.initial_dims['side_length'] * scale)
                    self.selected_shape.side_length = new_side

            self._redraw_shape(self.selected_shape)

    def _create_shape(self):
        """Crea una forma permanente en el canvas - IDÉNTICO AL ORIGINAL"""
        if self.preview_shape:
            self.canvas.delete(self.preview_shape)
            self.preview_shape = None

        if self.current_mode == 'circle':
            final_radius = max(
                self.MIN_SIZE,
                min(self.MAX_SIZE, self.current_size)
            )
            # Crear shape en coordenadas mundo (convertir desde pantalla)
            try:
                wx, wy = self.canvas.screen_to_world(self.start_x, self.start_y)
            except Exception:
                zoom = getattr(self.canvas, 'zoom_level', 1.0)
                wx, wy = self.start_x / zoom, self.start_y / zoom
            shape = Circle(wx, wy, final_radius)
            # Persist visual properties on the shape so updates (move/redo) keep them
            shape.outline = self.COLOR_CIRCLE
            shape.outline_width = self.LINE_WIDTH
            shape.fill = ""
            screen_bbox = _transform_bbox_for_canvas(self.canvas, shape.get_bbox())
            canvas_id = self.canvas.create_oval(
                *screen_bbox,
                outline=adapt_color_for_display(self.COLOR_CIRCLE, self.canvas.cget('bg')),
                width=self.LINE_WIDTH,
                fill=""
            )
        elif self.current_mode == 'rect':
            width = max(self.MIN_SIZE, min(self.MAX_SIZE * 2, self.current_width))
            height = max(self.MIN_SIZE, min(self.MAX_SIZE * 2, self.current_height))
            try:
                wx, wy = self.canvas.screen_to_world(self.start_x, self.start_y)
            except Exception:
                zoom = getattr(self.canvas, 'zoom_level', 1.0)
                wx, wy = self.start_x / zoom, self.start_y / zoom
            shape = Rect(wx, wy, width, height)
            shape.outline = self.COLOR_RECT
            shape.outline_width = self.LINE_WIDTH
            shape.fill = ""
            screen_bbox = _transform_bbox_for_canvas(self.canvas, shape.get_bbox())
            canvas_id = self.canvas.create_rectangle(
                *screen_bbox,
                outline=adapt_color_for_display(self.COLOR_RECT, self.canvas.cget('bg')),
                width=self.LINE_WIDTH,
                fill=""
            )
        elif self.current_mode == 'ellipse':
            radius_x = max(self.MIN_SIZE, min(self.MAX_SIZE * 2, self.current_radius_x))
            radius_y = max(self.MIN_SIZE, min(self.MAX_SIZE * 2, self.current_radius_y))
            try:
                wx, wy = self.canvas.screen_to_world(self.start_x, self.start_y)
            except Exception:
                zoom = getattr(self.canvas, 'zoom_level', 1.0)
                wx, wy = self.start_x / zoom, self.start_y / zoom
            shape = Ellipse(wx, wy, radius_x, radius_y)
            shape.outline = self.COLOR_ELLIPSE
            shape.outline_width = self.LINE_WIDTH
            shape.fill = ""
            screen_bbox = _transform_bbox_for_canvas(self.canvas, shape.get_bbox())
            canvas_id = self.canvas.create_oval(
                *screen_bbox,
                outline=adapt_color_for_display(self.COLOR_ELLIPSE, self.canvas.cget('bg')),
                width=self.LINE_WIDTH,
                fill=""
            )
        elif self.current_mode == 'square':
            side_length = max(self.MIN_SIZE, min(self.MAX_SIZE * 2, self.current_side))
            try:
                wx, wy = self.canvas.screen_to_world(self.start_x, self.start_y)
            except Exception:
                zoom = getattr(self.canvas, 'zoom_level', 1.0)
                wx, wy = self.start_x / zoom, self.start_y / zoom
            shape = Square(wx, wy, side_length)
            shape.outline = self.COLOR_SQUARE
            shape.outline_width = self.LINE_WIDTH
            shape.fill = ""
            screen_bbox = _transform_bbox_for_canvas(self.canvas, shape.get_bbox())
            canvas_id = self.canvas.create_rectangle(
                *screen_bbox,
                outline=adapt_color_for_display(self.COLOR_SQUARE, self.canvas.cget('bg')),
                width=self.LINE_WIDTH,
                fill=""
            )

        shape.canvas_id = canvas_id
        self.shapes.append(shape)
        self.selected_shape = shape # CRÍTICO: Asignar shape creado para que sea detectable

        # Agregar shape al ShapeManager para selección
        if hasattr(self, 'shape_manager') and self.shape_manager:
            self.shape_manager.add_shape(shape)

    def _select_shape_at(self, x: float, y: float):
        """Selecciona una forma en las coordenadas dadas - IDÉNTICO AL ORIGINAL"""
        if self.selected_shape:
            self._update_shape_color(self.selected_shape, False)
            self.selected_shape = None
        # Convertir coordenadas de pantalla a mundo antes de buscar
        try:
            wx, wy = self.canvas.screen_to_world(x, y)
        except Exception:
            zoom = getattr(self.canvas, 'zoom_level', 1.0)
            wx, wy = x / zoom, y / zoom

        # Buscar forma en las coordenadas (en orden inverso para seleccionar la más reciente)
        for shape in reversed(self.shapes):
            if shape.contains_point(wx, wy):
                self.selected_shape = shape
                self._update_shape_color(shape, True)
                # Cursor normal cuando se selecciona
                self.canvas.config(cursor="arrow")
                break
        else:
            # Si no se encontró ninguna forma, cursor normal
            self.canvas.config(cursor="arrow")

    def _update_shape_color(self, shape, selected: bool):
        """Actualiza el color de una forma según su estado - IDÉNTICO AL ORIGINAL"""
        shape.selected = selected
        canvas_bg = self.canvas.cget('bg') if hasattr(self.canvas, 'cget') else '#ffffff'

        # Preferir outline específico del shape si existe
        if hasattr(shape, 'outline') and shape.outline:
            base_color = shape.outline
        else:
            if shape.shape_type == "circle":
                base_color = self.COLOR_CIRCLE
            elif shape.shape_type == "rect":
                base_color = self.COLOR_RECT
            elif shape.shape_type == "ellipse":
                base_color = self.COLOR_ELLIPSE
            elif shape.shape_type == "square":
                base_color = self.COLOR_SQUARE
            else:
                base_color = self.COLOR_CIRCLE

        if selected:
            color = adapt_color_for_display(self.COLOR_SELECTED, canvas_bg)
        else:
            color = adapt_color_for_display(base_color, canvas_bg)

        try:
            self.canvas.itemconfig(
                shape.canvas_id,
                outline=color,
                width=self.LINE_WIDTH
            )
        except Exception:
            pass

    def _redraw_shape(self, shape):
        """
        Redibuja una forma con sus nuevas dimensiones - IDÉNTICO AL ORIGINAL
        CLAVE: Este método NO borra, solo actualiza coordenadas para evitar estelas
        """
        self._update_shape_color(shape, shape.selected)
        if getattr(shape, 'shape_type', None) == 'rounded_rect':
            try:
                self.canvas.delete(shape.canvas_id)
            except Exception:
                pass
            shape.draw(self.canvas)
            self._update_shape_color(shape, shape.selected)
            return

        # Actualizar coordenadas del canvas usando conversión a pantalla
        screen_bbox = _transform_bbox_for_canvas(self.canvas, shape.get_bbox())
        try:
            self.canvas.coords(shape.canvas_id, *screen_bbox)
        except Exception:
            # Fallback a coords sin transformar
            self.canvas.coords(shape.canvas_id, *shape.get_bbox())

        # SOLUCIÓN: Si es un Riel DIN u otra forma compuesta, actualizar sus partes internas
        if hasattr(shape, 'update_inner_graphics'):
            shape.update_inner_graphics(self.canvas)

        tag = getattr(shape, 'metadata', {}).get('component_tag')
        if tag:
            try:
                app = getattr(self.canvas, 'app', None)
                if app and hasattr(app, 'text_components'):
                    h = getattr(shape, 'height', getattr(shape, 'radius', 0) * 2)
                    label_y = shape.y - h / 2 - 10
                    for tc in app.text_components:
                        if getattr(tc, 'text', '') == tag:
                            tc.x = shape.x
                            tc.y = label_y
                            if hasattr(tc, 'canvas_id') and tc.canvas_id:
                                try:
                                    sx, sy = _transform_bbox_for_canvas(self.canvas, (shape.x, label_y, shape.x, label_y))[:2]
                                    self.canvas.coords(tc.canvas_id, sx, sy)
                                except Exception:
                                    pass
                            break
            except Exception:
                pass

    # Métodos de interfaz pública compatibles con el código existente

    def find_shape_at_position(self, x: float, y: float) -> Optional[object]:
        """Encuentra una forma en la posición especificada"""
        # Convertir pantalla -> mundo si es necesario
        try:
            wx, wy = self.canvas.screen_to_world(x, y)
        except Exception:
            zoom = getattr(self.canvas, 'zoom_level', 1.0)
            wx, wy = x / zoom, y / zoom

        # Buscar en orden normal (no reverso) para respetar Z-order
        # Las formas seleccionables están DESPUÉS del fondo del gabinete
        # CAMBIO: Ahora permitimos que cabinet_background sea seleccionable
        # La protección contra movimiento/eliminación está implementada en handlers/event_handlers.py
        for shape in self.shapes:
            if shape.contains_point(wx, wy):
                return shape
        return None

    def add_shape(self, shape):
        """Agrega una forma al gestor"""
        self.shapes.append(shape)

    def remove_shape(self, shape):
        """Elimina una forma del gestor"""
        if shape in self.shapes:
            self.shapes.remove(shape)

    def clear_selection(self):
        """Limpia la selección actual"""
        if self.selected_shape:
            self._update_shape_color(self.selected_shape, False)
            self.selected_shape = None

    def select_shape(self, shape):
        """Selecciona una forma específica"""
        if self.selected_shape:
            self._update_shape_color(self.selected_shape, False)

        self.selected_shape = shape
        if shape:
            self._update_shape_color(shape, True)

    def get_selected_shape(self):
        """Retorna la forma actualmente seleccionada"""
        return self.selected_shape

# Factory para compatibilidad con código existente
class ShapeFactory:
    """Factory para crear diferentes tipos de formas"""

    @staticmethod
    def create_shape(shape_type: str, x: float, y: float, **kwargs):
        """Crea una nueva forma del tipo especificado"""
        if shape_type == "circle":
            radius = kwargs.get("radius", 40)
            return Circle(x, y, radius)
        elif shape_type == "rectangle":
            width = kwargs.get("width", 60)
            height = kwargs.get("height", 40)
            return Rect(x, y, width, height)
        elif shape_type == "ellipse":
            radius_x = kwargs.get("width", 80)
            radius_y = kwargs.get("height", 50)
            return Ellipse(x, y, radius_x, radius_y)
        elif shape_type == "square":
            side_length = kwargs.get("size", 50)
            return Square(x, y, side_length)
        elif shape_type in ["line", "geom_line"]:
            x2 = kwargs.get("x2", x + 100)
            y2 = kwargs.get("y2", y + 100)
            return Line(x, y, x2, y2)
        else:
            raise ValueError(f"Tipo de forma no soportado: {shape_type}")

# ShapeManager para compatibilidad
class ShapeManager:
    """Gestor para manejar múltiples formas en el canvas"""

    def __init__(self, canvas: Optional[tk.Canvas] = None):
        """Inicializa el gestor de formas"""
        self.shapes: List = []
        self.selected_shape = None
        self.canvas = canvas
        if canvas:
            self.editor = ShapeEditor(canvas, self)
        else:
            self.editor = None

    def add_shape(self, shape):
        """Agrega una nueva forma al gestor"""
        self.shapes.append(shape)

    def remove_shape(self, shape):
        """Elimina una forma del gestor"""
        if shape in self.shapes:
            self.shapes.remove(shape)
        if self.selected_shape == shape:
            self.selected_shape = None

    def find_shape_at_position(self, x: float, y: float):
        """Encuentra la forma que contiene el punto especificado.
        Prioridad: shapes específicos (DinRail, Canaleta, Rect, etc.)
        sobre cabinet_background para que un clic en la canaleta no sea
        absorbido por el fondo del gabinete."""
        background_candidate = None
        for shape in reversed(self.shapes):
            if not shape.contains_point(x, y):
                continue
            meta_type = getattr(shape, 'metadata', {}).get('type', '')
            if meta_type == 'cabinet_background':
                background_candidate = shape  # guardar como fallback
                continue
            return shape # shape específico -> prioridad máxima
        return background_candidate  # solo fondo si no había otro

    def clear_selection(self):
        """Limpia la selección actual"""
        if self.selected_shape:
            if self.editor:
                self.editor._update_shape_color(self.selected_shape, False)
            self.selected_shape.selected = False
            self.selected_shape = None

    def select_shape(self, shape, start_x=None, start_y=None):
        """Selecciona una forma específica y activa el modo de movimiento

        Args:
            shape: Forma a seleccionar
            start_x: Coordenada X inicial del arrastre
            start_y: Coordenada Y inicial del arrastre
        """
        if getattr(shape, 'metadata', {}).get('type') == 'cabinet_background':
            return None

        if self.selected_shape:
            self.selected_shape.selected = False
            if self.editor:
                self.editor._update_shape_color(self.selected_shape, False)

        self.selected_shape = shape
        if shape:
            shape.selected = True
            if self.editor:
                self.editor._update_shape_color(shape, True)
                # Activar modo de movimiento al seleccionar
                self.editor.moving = True
                # Usar coordenadas del mouse si están disponibles, sino convertir la posición de la forma a pantalla
                if start_x is not None and start_y is not None:
                    self.editor.move_start_x = start_x
                    self.editor.move_start_y = start_y
                else:
                    try:
                        # Para formas con x,y (Rect, Circle, etc.)
                        cx = getattr(shape, 'x', getattr(shape, 'x1', 0))
                        cy = getattr(shape, 'y', getattr(shape, 'y1', 0))

                        sx, sy = self.canvas.world_to_screen(cx, cy)
                        self.editor.move_start_x = sx
                        self.editor.move_start_y = sy
                    except Exception:
                        zoom = getattr(self.canvas, 'zoom_level', 1.0)
                        cx = getattr(shape, 'x', getattr(shape, 'x1', 0))
                        cy = getattr(shape, 'y', getattr(shape, 'y1', 0))
                        self.editor.move_start_x = int(cx * zoom)
                        self.editor.move_start_y = int(cy * zoom)

    def create_shape_from_data(self, shape_data):
        """Crea shape desde diccionario de datos"""
        shape_type = shape_data['type']
        x = shape_data['x']
        y = shape_data['y']
        width = shape_data['width']
        height = shape_data['height']

        if shape_type == "circle":
            radius = min(width, height) / 2
            shape = Circle(x, y, radius)
        elif shape_type == "rectangle":
            shape = Rect(x, y, width, height)
        elif shape_type == "ellipse":
            # width/height are full extents from the preview; Ellipse expects radii
            radius_x = width / 2
            radius_y = height / 2
            shape = Ellipse(x, y, radius_x, radius_y)
        elif shape_type == "square":
            # Para cuadrado, usar el lado más pequeño
            size = min(width, height)
            shape = Square(x, y, size)
        elif shape_type == "din_rail":
            shape = DinRail(x, y, width, max(30, height)) # Permitir algo de elasticidad o fijarlo
        elif shape_type == "canaleta":
            # Usar parámetro 'horizontal' si está disponible en shape_data
            is_horizontal = shape_data.get('horizontal', True)
            # 'seccion' permite crear la canaleta con un ancho comercial concreto
            shape = Canaleta(x, y, width, horizontal=is_horizontal,
                             seccion=shape_data.get('seccion'))  # ancho fijo de sección, largo variable
        elif shape_type == "line":
            x1 = shape_data.get('x1', 0)
            y1 = shape_data.get('y1', 0)
            x2 = shape_data.get('x2', 100)
            y2 = shape_data.get('y2', 100)
            shape = Line(x1, y1, x2, y2)
            shape.color = shape_data.get('color', 'black')
            shape.width = shape_data.get('width', 1)
            self.shapes.append(shape)
            if self.canvas:
                shape.draw(self.canvas)
            return shape
        else:
            return None

        # Para canaleta: si fill viene vacío, respetar el color por defecto de la clase (#C0C0C0)
        incoming_fill = shape_data.get('fill', '')
        if shape_type == 'canaleta' and not incoming_fill:
            pass  # Mantener self.fill = "#C0C0C0" definido en Canaleta.__init__
        else:
            shape.fill = incoming_fill if incoming_fill else shape_data.get('fill', 'lightgray')
        shape.outline = shape_data.get('outline', 'black')
        shape.outline_width = shape_data.get('outline_width', 2)

        # FIX Z-ORDER: Riel DIN y Canaleta siempre al inicio (detrás de componentes)
        if shape_type in ["din_rail", "canaleta"]:
            self.shapes.insert(0, shape)  # Insertar al inicio
        else:
            self.shapes.append(shape)  # Componentes al final

        if self.canvas:
            shape.draw(self.canvas)

        self.selected_shape = shape
        if self.editor:
            try:
                # No activar modo 'moving' automáticamente - solo marcar selección
                self.editor.selected_shape = shape
                self.editor._update_shape_color(shape, True)
            except Exception:
                pass

        return shape

    def draw_all(self, canvas: tk.Canvas):
        """Redibuja todas las formas en el canvas"""
        for shape in self.shapes:
            if shape.canvas_id and canvas:
                if getattr(shape, 'metadata', {}).get('type') == 'cabinet_background':
                    try:
                        if getattr(shape, 'shape_type', None) == 'rounded_rect':
                            canvas.coords(shape.canvas_id, *shape._screen_points(canvas))
                        elif getattr(shape, 'shape_type', None) == 'geom_line' or getattr(shape, 'shape_type', None) == 'line':
                            zoom = getattr(canvas, 'zoom_level', 1.0)
                            canvas.coords(shape.canvas_id,
                                          shape.x1 * zoom, shape.y1 * zoom,
                                          shape.x2 * zoom, shape.y2 * zoom)
                        else:
                            screen_bbox = _transform_bbox_for_canvas(canvas, shape.get_bbox())
                            canvas.coords(shape.canvas_id, *screen_bbox)
                    except Exception:
                        pass
                    continue
                if getattr(shape, 'shape_type', None) == 'rounded_rect':
                    try:
                        canvas.delete(shape.canvas_id)
                    except Exception:
                        pass
                    shape.draw(canvas)
                    if hasattr(shape, 'selected') and self.editor:
                        self.editor._update_shape_color(shape, shape.selected)
                    continue

                screen_bbox = _transform_bbox_for_canvas(canvas, shape.get_bbox())
                try:
                    canvas.coords(shape.canvas_id, *screen_bbox)
                except Exception:
                    try:
                        canvas.coords(shape.canvas_id, *shape.get_bbox())
                    except Exception:
                        pass
                if hasattr(shape, 'selected') and self.editor:
                    self.editor._update_shape_color(shape, shape.selected)

                if hasattr(shape, 'update_inner_graphics'):
                    shape.update_inner_graphics(canvas)

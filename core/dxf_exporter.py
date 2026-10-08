"""
Exportador DXF vectorial.
"""

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# ezdxf y svgpathtools se importan bajo demanda: entre ambos arrastran numpy y
# scipy y suman ~1 s, que se pagaba en cada arranque aunque el usuario nunca
# exporte a DXF.  Ver _load_ezdxf().
from config.settings import AppConstants
from ui.export_dialog import confirm_overwrite, show_export_success

_ezdxf = None
_svgpathtools = None
_text_align = None


def _load_ezdxf():
    """Importa ezdxf/svgpathtools la primera vez que se hace falta."""
    global _ezdxf, _svgpathtools, _text_align
    if _ezdxf is None:
        import ezdxf
        import svgpathtools
        from ezdxf.enums import TextEntityAlignment

        _ezdxf = ezdxf
        _svgpathtools = svgpathtools
        _text_align = TextEntityAlignment
    return _ezdxf


def _enum():
    """Alineaciones de texto de ezdxf (carga perezosa)."""
    if _text_align is None:
        _load_ezdxf()
    return _text_align

SVG_NS = "http://www.w3.org/2000/svg"

LAYERS = [
    ("CONDUCTORES", 1),
    ("SIMBOLOS", 3),
    ("GEOMETRIA", 5),
    ("TEXTOS", 7),
    ("PUNTOS", 6),
]

JUNCTION_RADIUS_PX = 2.5

# Separación entre hojas y ancho mínimo reservado, en píxeles del mundo.
SHEET_GAP_PX = 200.0
SHEET_MIN_WIDTH_PX = 800.0
# Escala del símbolo del plano de borner respecto a su caja en pantalla.
BORNER_DXF_SIZE_SCALE = 2.0 / 3.0

# Cápsula del apantallamiento en el DXF (píxeles del mundo).
SHIELDING_CAPSULE_PAD_X = 10.0
SHIELDING_CAPSULE_HEIGHT = 9.0
SHIELDING_CAPSULE_TOP_OFFSET = 2.0
# Factor sobre el eje mayor de la cápsula. Bajarlo de 1.0 la acorta respecto al
# cable: el DXF la deja más proporcionada y deja de sobresalir por los extremos.
SHIELDING_CAPSULE_WIDTH_SCALE = 0.7

# Resolución al aproximar curvas SVG con polilíneas.
BEZIER_SAMPLES = 12
ARC_SAMPLES = 16
# DXF ARC solo admite arcos circulares.
CIRCULAR_TOL = 1e-6

# Alturas de etiquetas en píxeles del mundo.
_LABEL_FONT_PX = 8.0
_DESCRIPTION_FONT_PX = 7.0

_NUM = r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_TRANSFORM_RE = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")
_NUMBER_RE = re.compile(_NUM)
_UNSAFE_NAME_RE = re.compile(r"[^0-9A-Za-z_]+")

def _tag(el):
    """Nombre del elemento sin el namespace SVG."""
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag

def _fnum(value, default=0.0):
    """Convierte a float tolerando sufijos SVG como '10px'."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_RE.search(str(value))
    cleaned = match.group(0) if match else ""
    if cleaned in ("", "-", ".", "e", "E"):
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default

def _matrix(transform_str):
    """Convierte un atributo transform SVG en una matriz afín 2D."""
    if not transform_str:
        return None
    result = _Transform()
    for name, args in _TRANSFORM_RE.findall(transform_str):
        nums = [float(v) for v in _NUMBER_RE.findall(args)]
        if name == "translate" and nums:
            tx = nums[0]
            ty = nums[1] if len(nums) > 1 else 0.0
            step = _Transform(1, 0, 0, 1, tx, ty)
        elif name == "scale" and nums:
            sx = nums[0]
            sy = nums[1] if len(nums) > 1 else sx
            step = _Transform(sx, 0, 0, sy, 0, 0)
        elif name == "rotate" and nums:
            rad = math.radians(nums[0])
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            step = _Transform(cos_a, sin_a, -sin_a, cos_a, 0, 0)
            if len(nums) >= 3:
                cx, cy = nums[1], nums[2]
                step = _Transform(1, 0, 0, 1, cx, cy) * step * _Transform(1, 0, 0, 1, -cx, -cy)
        elif name == "matrix" and len(nums) >= 6:
            step = _Transform(*nums[:6])
        elif name == "skewX" and nums:
            step = _Transform(1, 0, math.tan(math.radians(nums[0])), 1, 0, 0)
        elif name == "skewY" and nums:
            step = _Transform(1, math.tan(math.radians(nums[0])), 0, 1, 0, 0)
        else:
            continue
        result = result * step
    if result.is_identity:
        return None
    return result

class _Transform:
    """Matriz afín 2D acumulada para transformaciones de SVG."""

    __slots__ = ("a", "b", "c", "d", "e", "f")

    def __init__(self, a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0):
        self.a, self.b, self.c, self.d, self.e, self.f = a, b, c, d, e, f

    def __mul__(self, other):
        """self * other: other se aplica primero, como en el orden SVG."""
        a1, b1, c1, d1, e1, f1 = self.a, self.b, self.c, self.d, self.e, self.f
        a2, b2, c2, d2, e2, f2 = other.a, other.b, other.c, other.d, other.e, other.f
        return _Transform(
            a1 * a2 + c1 * b2,
            b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2,
            b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1,
            b1 * e2 + d1 * f2 + f1,
        )

    def apply(self, x, y):
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    @property
    def is_identity(self):
        return (self.a, self.b, self.c, self.d, self.e, self.f) == (
            1.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
        )

class _Canvas:
    """Escribe entidades DXF convirtiendo coordenadas del mundo a milímetros."""

    def __init__(self, doc, scale, height_px, offset_x=0.0, y_up=True):
        self.doc = doc
        self.msp = doc.modelspace()
        # Puede apuntar a modelspace o al layout de un bloque.
        self.dst = self.msp
        self.scale = scale
        self.height_px = height_px
        self.offset_x = offset_x
        # Los bloques usan coordenadas locales con Y hacia abajo.
        self.y_up = y_up
        # Extensión escrita en coordenadas del mundo.
        self._min_x = None
        self._max_x = None
        self._min_y = None
        self._max_y = None

    def _pt(self, x, y):
        """Píxeles del mundo -> milímetros DXF con Y hacia arriba."""
        self._track(x, y)
        x = float(x)
        y = float(y)
        if not self.y_up:
            return (x * self.scale, -y * self.scale)
        return ((x + self.offset_x) * self.scale, (self.height_px - y) * self.scale)

    def point(self, x, y):
        """Punto de inserción en DXF (mm) para una coordenada del mundo."""
        return self._pt(x, y)

    def _track(self, x, y, radius=0.0):
        x = float(x)
        y = float(y)
        lo, hi = x - radius, x + radius
        vlo, vhi = y - radius, y + radius
        self._min_x = lo if self._min_x is None else min(self._min_x, lo)
        self._max_x = hi if self._max_x is None else max(self._max_x, hi)
        self._min_y = vlo if self._min_y is None else min(self._min_y, vlo)
        self._max_y = vhi if self._max_y is None else max(self._max_y, vhi)

    def track_point(self, x, y, radius=0.0):
        """Registra un punto del mundo sin escribir ninguna entidad."""
        self._track(x, y, radius=radius)

    @property
    def local_bbox(self):
        """Extensión escrita, en píxeles del mundo, o None si no se escribió nada."""
        if self._min_x is None or self._max_x is None:
            return None
        return (self._min_x, self._min_y, self._max_x, self._max_y)

    def _len(self, value):
        return float(value) * self.scale

    def _polyline(self, pts, layer, closed=False, bulges=None):
        pts = [self._pt(x, y) for x, y in pts]
        if len(pts) < 2:
            return
        if closed and pts[0] != pts[-1]:
            pts.append(pts[0])
        if bulges:
            seq = []
            n = len(pts) - (1 if not closed else 0)
            for i, pt in enumerate(pts):
                b = bulges[i] if i < len(bulges) and bulges[i] is not None else 0.0
                seq.append((pt[0], pt[1], 0.0, 0.0, b))
            self.dst.add_lwpolyline(seq, format="xyseb", dxfattribs={"layer": layer})
        else:
            self.dst.add_lwpolyline(pts, format="xy", dxfattribs={"layer": layer})

    def line(self, x1, y1, x2, y2, layer):
        self.dst.add_line(self._pt(x1, y1), self._pt(x2, y2), dxfattribs={"layer": layer})

    def circle(self, cx, cy, r, layer):
        r = self._len(r)
        if r > 1e-9:
            self._track(cx, cy, radius=float(r) / self.scale)
            self.dst.add_circle(self._pt(cx, cy), r, dxfattribs={"layer": layer})

    def filled_circle(self, cx, cy, r, layer):
        """Dibuja un círculo relleno mediante un HATCH sólido y su contorno."""
        r = self._len(r)
        if r <= 1e-9:
            return
        center = self._pt(cx, cy)
        self._track(cx, cy, radius=float(r) / self.scale)
        hatch = self.dst.add_hatch(color=6, dxfattribs={"layer": layer})
        hatch.set_solid_fill(color=6)
        hatch.paths.add_edge_path().add_arc(
            center=center,
            radius=r,
            start_angle=0,
            end_angle=360,
            ccw=1,
        )
        self.dst.add_circle(center, r, dxfattribs={"layer": layer, "color": 6})

    def ellipse(self, cx, cy, major, ratio, rotation_deg, layer):
        """DXF exige ratio <= 1 y major_axis como vector, no como largo."""
        major = self._len(major)
        if major <= 1e-9:
            return
        ratio = max(min(ratio, 1.0), 1e-9)
        rad = math.radians(-rotation_deg)
        axis = (major * math.cos(rad), major * math.sin(rad))
        try:
            self.dst.add_ellipse(self._pt(cx, cy), axis, ratio, dxfattribs={"layer": layer})
        except Exception:
            self.circle(cx, cy, major * ratio, layer)

    def text(self, value, x, y, height, layer, rotation=0.0, align="left"):
        if not value:
            return
        ent = self.dst.add_text(
            value,
            height=max(self._len(height), 0.01),
            # El ángulo se pasa tal cual, sin negarlo. La línea base de un texto
            # con ángulo θ en el canvas es (cos θ, -sin θ) porque Tk mide el ángulo
            # antihorario en pantalla; el volteo de Y de _pt la convierte en
            # (cos θ, sin θ), que es justo la dirección que produce una rotación φ
            # en DXF cuando φ = θ. Negarlo intercambiaba 90° y 270°, dejando el
            # texto rotado al revés respecto del canvas.
            rotation=(rotation % 360.0) if rotation else 0.0,
            # Usar una fuente TrueType consistente evita que los visores DXF
            # sustituyan el texto por una fuente SHX desproporcionadamente ancha.
            dxfattribs={"layer": layer, "style": "evaPr"},
        )
        place = {
            "left": _enum().LEFT,
            "center": _enum().CENTER,
            "right": _enum().RIGHT,
        }.get(align, _enum().LEFT)
        ent.set_placement(self._pt(x, y), align=place)

    def arc(self, cx, cy, radius, start_deg, end_deg, layer):
        radius = float(radius)
        if radius > 0:
            self._track(cx, cy, radius=radius)
        self.dst.add_arc(
            self._pt(cx, cy),
            self._len(radius),
            start_deg,
            end_deg,
            dxfattribs={"layer": layer},
        )

class _SvgImageProxy:
    """Adapta una imagen del plano de borner para exportarla desde su SVG."""

    def __init__(self, svg_file, size, phase=None):
        self.svg_file = svg_file
        self.category = ""
        self.size = (float(size[0]), float(size[1]))
        self.original_size = [float(size[0]), float(size[1])]
        self.label_data = {}
        self.component_type = "borner"
        phase = str(phase or "").upper()
        self.burner_layer_states = {"PE": phase == "PE", "N": phase == "N"}

    def _apply_layer_visibility(self, svg_content):
        pe = "inline" if self.burner_layer_states["PE"] else "none"
        n = "inline" if self.burner_layer_states["N"] else "none"
        svg_content = re.sub(
            r'(<g[^>]*?(?:id="PE"|inkscape:label="PE")[^>]*?)style="display:[^"]*"',
            rf'\1style="display:{pe}"',
            svg_content,
            flags=re.IGNORECASE,
        )
        svg_content = re.sub(
            r'(<g[^>]*?(?:id="N"|inkscape:label="N")[^>]*?)style="display:[^"]*"',
            rf'\1style="display:{n}"',
            svg_content,
            flags=re.IGNORECASE,
        )
        return svg_content

class DxfExporter:
    """Genera un DXF R2010 a partir del estado actual de la aplicacion."""

    LAYER_CONDUCTORES = "CONDUCTORES"
    LAYER_SIMBOLOS = "SIMBOLOS"
    LAYER_GEOMETRIA = "GEOMETRIA"
    LAYER_TEXTOS = "TEXTOS"
    LAYER_PUNTOS = "PUNTOS"

    JUNCTION_BLOCK = "EVAPR_EMPALME"
    APPID = "EVAPR"

    def __init__(self, app):
        self.app = app
        self.warnings = []
        self._blocks = {}
        self._block_names = set()
        self._doc = None
        # Cachés por archivo SVG: el mismo símbolo se repite muchas veces en un
        # plano y antes se releía y se reparseaba en cada instancia.
        self._svg_text = {}
        self._svg_root = {}

    def export_dxf(self):
        """Pide destino por dialogo y escribe el DXF. Devuelve la ruta o None."""
        from tkinter import filedialog

        initial = self._initial_filename()
        filename = filedialog.asksaveasfilename(
            title="Exportar DXF vectorial",
            initialfile=initial,
            defaultextension=".dxf",
            filetypes=[("Archivo DXF", "*.dxf"), ("Todos los archivos", "*.*")],
            parent=getattr(self.app, "root", None),
            confirmoverwrite=False,
        )
        if not filename or not confirm_overwrite(getattr(self.app, "root", None), filename):
            return None
        written = self._write_dxf(filename)
        if written:
            self._notify_exported(written)
        return written

    def _write_dxf(self, filename):
        self.warnings = []
        status = getattr(self.app, "set_status", None)
        try:
            # Igual que el PDF: durante la exportación no hay que regenerar las
            # hojas de informe ni repintar la UI al cambiar de hoja.  Sin esto, DXF
            # recalculaba BOM, resumen de gabinete, borner, seguridad y gabinete 2D
            # en cada salto de hoja, y además mutaba el proyecto mientras exportaba.
            self.app._is_exporting_dxf = True
            if callable(status):
                try:
                    status("📐 Exportando DXF... Por favor espere", "red", duration=None)
                    getattr(self.app.root, "update_idletasks", lambda: None)()
                except Exception:
                    pass
            doc = self._build_document()
            doc.saveas(filename)
        finally:
            self.app._is_exporting_dxf = False
        return filename

    def _notify_exported(self, filename):
        """Muestra la confirmación de exportación compartida con PDF."""
        parent = getattr(self.app, "root", None)
        show_export_success(parent, "DXF", filename, self.warnings)
        status = getattr(self.app, "set_status", None)
        if callable(status):
            try:
                status("✅ DXF exportado con éxito", "green")
            except Exception:
                pass

    def _build_document(self):
        ezdxf = _load_ezdxf()
        doc = ezdxf.new("R2010", setup=True)
        doc.header["$INSUNITS"] = 4  # milimetros
        doc.header["$MEASUREMENT"] = 1  # metrico
        doc.header["$LUNITS"] = 2
        for name, color in LAYERS:
            doc.layers.add(name, color=color)
        try:
            doc.appids.add(self.APPID)
        except Exception:
            pass
        try:
            doc.styles.add("evaPr", font="Arial.ttf")
        except Exception:
            pass
        self._doc = doc
        self._blocks = {}
        self._block_names = set()
        self._svg_text = {}
        self._svg_root = {}

        project = getattr(self.app, "project", None)
        sheets = getattr(project, "sheets", None) or []
        excluded = ("Hoja de Gabinete 2D", "Lista de Materiales", "Tabla de Cableado")
        # Mapear índices de hojas a exportar
        export_indices = []
        for i, s in enumerate(sheets):
            name = getattr(s, 'name', '') or ''
            if name not in excluded:
                export_indices.append(i)
        count = len(export_indices)
        if count == 0:
            export_indices = list(range(len(sheets)))
            count = len(export_indices)
        original_index = self._active_sheet_index()
        try:
            # Apila las hojas en X usando la extensión realmente exportada.
            offset_x = 0.0
            for k, index in enumerate(export_indices):
                self._select_sheet(index)
                canvas = _Canvas(
                    doc,
                    1.0 / AppConstants.MM_TO_PX,
                    self._world_height(),
                    offset_x=offset_x,
                )
                self._emit_sheet(canvas, index)
                end_x = offset_x + (canvas._max_x if canvas._max_x is not None else 0.0)
                offset_x = max(end_x + SHEET_GAP_PX, offset_x + SHEET_MIN_WIDTH_PX)
        finally:
            if original_index is not None:
                self._select_sheet(original_index)
        return doc

    def _world_height(self):
        """Alto del mundo en píxeles, usado para invertir el eje Y."""
        height = float(AppConstants.CANVAS_HEIGHT)
        for comp in self._active_components():
            x, y = getattr(comp, "x", 0), getattr(comp, "y", 0)
            w, h = getattr(comp, "size", (0, 0))
            height = max(height, y + h + 200.0)
        manager = getattr(self.app, "shape_manager", None)
        for shape in getattr(manager, "shapes", None) or []:
            try:
                bbox = shape.get_bbox()
            except Exception:
                continue
            if bbox:
                height = max(height, bbox[3] + 200.0)
        for conn in getattr(self.app, "connections", []) or []:
            for seg in getattr(conn, "segments", None) or []:
                try:
                    height = max(height, seg[0][1], seg[1][1])
                except (TypeError, IndexError):
                    continue
        return height

    def _active_sheet_index(self):
        project = getattr(self.app, "project", None)
        index = getattr(project, "active_sheet_index", None)
        return index if isinstance(index, int) else None

    def _select_sheet(self, index):
        """Activa una hoja para que los modelos en vivo correspondan a ella."""
        switch = getattr(self.app, "switch_to_sheet", None)
        if not callable(switch):
            return
        try:
            switch(index)
        except Exception as exc:
            self.warnings.append(f"No se pudo activar la hoja {index + 1}: {exc}")

    def _active_components(self):
        return list(getattr(self.app, "components", []) or [])

    def _initial_filename(self):
        project = getattr(self.app, "project", None)
        name = getattr(project, "name", "") or "evaPr"
        return f"{name}.dxf"

    def _emit_sheet(self, canvas, index):
        """Exporta los elementos de una hoja activa."""
        self._emit_connections(canvas)
        self._emit_components(canvas)
        self._emit_junctions(canvas)
        self._emit_shieldings(canvas)
        self._emit_shapes(canvas)
        self._emit_text_components(canvas)
        self._emit_image_components(canvas)

    def _emit_junctions(self, canvas):
        """Exporta los empalmes como círculos reutilizando un bloque DXF."""
        emitted = set()
        block = self._junction_block(canvas)
        r = JUNCTION_RADIUS_PX
        box = (-r, -r, r, r)

        # Los empalmes se representan como círculos en su borne común.
        for comp in self._active_components():
            if getattr(comp, "component_type", "") != "junction":
                continue
            ex = getattr(comp, "x", 0)
            ey = getattr(comp, "y", 0)
            if block:
                self._insert_block(canvas, block, ex - r, ey - r, 2 * r, 2 * r, 0.0, bbox=box)
            else:
                canvas.filled_circle(ex, ey, r, self.LAYER_PUNTOS)
            emitted.add((round(ex, 3), round(ey, 3)))

        for conn in getattr(self.app, "connections", []) or []:
            segments = getattr(conn, "segments", None) or []
            for empalme in getattr(conn, "puntos_empalme", None) or []:
                seg_idx = getattr(empalme, "segmento_idx", 0)
                ratio = getattr(empalme, "posicion_ratio", 0.5)
                if seg_idx >= len(segments):
                    continue
                try:
                    start, end = segments[seg_idx]
                    ex = start[0] + (end[0] - start[0]) * ratio
                    ey = start[1] + (end[1] - start[1]) * ratio
                except (TypeError, IndexError, ValueError):
                    continue
                key = (round(ex, 3), round(ey, 3))
                if key not in emitted:
                    if block:
                        self._insert_block(canvas, block, ex - r, ey - r, 2 * r, 2 * r, 0.0, bbox=box)
                    else:
                        canvas.filled_circle(ex, ey, r, self.LAYER_PUNTOS)
                    emitted.add(key)

    def _emit_shieldings(self, canvas):
        """Exporta los apantallamientos: cápsula, línea de referencia, cortes y textos.

        replica la geometría de Shielding.draw() para que el DXF muestre lo mismo
        que el canvas. El apantallamiento se guarda en la hoja como un elemento
        de tipo "shielding" que switch_to_sheet carga en shielding_manager, así que
        aquí se lee el manager de la hoja activa.
        """
        manager = getattr(self.app, "shielding_manager", None)
        shieldings = getattr(manager, "shieldings", None) or []
        for sh in shieldings:
            try:
                x1 = float(getattr(sh, "x1", 0.0))
                x2 = float(getattr(sh, "x2", 0.0))
                y = float(getattr(sh, "y", 0.0))
            except Exception:
                continue
            left, right = min(x1, x2), max(x1, x2)

            # 1. Cápsula del apantallamiento. Es más baja y corta que en el
            # canvas porque en DXF el trazo seve mucho más grueso: con la
            # proporción original (16 px de alto) se leía como una banda
            # dominante. El borde superior se mantiene en y+2 para que no se
            # desprenda de los cortes diagonales.
            top = y + SHIELDING_CAPSULE_TOP_OFFSET
            major = ((right - left) + 2.0 * SHIELDING_CAPSULE_PAD_X) * SHIELDING_CAPSULE_WIDTH_SCALE
            if major > 0:
                canvas.ellipse(
                    (left + right) / 2.0,
                    top + SHIELDING_CAPSULE_HEIGHT / 2.0,
                    major,
                    SHIELDING_CAPSULE_HEIGHT / major,
                    0.0,
                    self.LAYER_CONDUCTORES,
                )

            # 2. Línea horizontal de referencia sobre la que van los cortes.
            canvas.line(left - 20.0, y - 12.0, right + 20.0, y - 12.0,
                        self.LAYER_CONDUCTORES)

            # 3. Cortes diagonales con su etiqueta (BK, BN, PE...).
            for label in getattr(sh, "labels", None) or []:
                if not isinstance(label, dict) or label.get("x") is None:
                    continue
                lx = float(label["x"])
                canvas.line(lx - 3.0, y + 3.0, lx + 3.0, y - 3.0,
                            self.LAYER_CONDUCTORES)
                text = label.get("text")
                if text:
                    canvas.text(str(text), lx, y - 14.0, _LABEL_FONT_PX,
                                self.LAYER_TEXTOS, align="center")

            # 4. Cabecera de especificaciones, a la izquierda del extremo inicial.
            header = getattr(sh, "header_text", None)
            if header:
                canvas.text(str(header), left - 22.0, y - 12.0, 9.0,
                            self.LAYER_TEXTOS, align="right")

    def _junction_block(self, canvas):
        """Bloque con el círculo de empalme, o None si no se pudo crear."""
        name = self._blocks.get("__empalme__")
        if name:
            return name
        block = canvas.doc.blocks.new(name=self.JUNCTION_BLOCK, base_point=(0, 0))
        inner = _Canvas(canvas.doc, canvas.scale, 0.0, y_up=False)
        inner.dst = block
        inner.filled_circle(0.0, 0.0, JUNCTION_RADIUS_PX, self.LAYER_PUNTOS)
        if not len(block):
            canvas.doc.blocks.delete_block(self.JUNCTION_BLOCK, safe=False)
            return None
        self._block_names.add(self.JUNCTION_BLOCK)
        self._blocks["__empalme__"] = self.JUNCTION_BLOCK
        return self.JUNCTION_BLOCK

    def _emit_connections(self, canvas):
        for conn in getattr(self.app, "connections", []) or []:
            segments = getattr(conn, "segments", None) or []
            dash = getattr(conn, "line_dash", "") or ""
            for seg in segments:
                try:
                    (x1, y1), (x2, y2) = seg
                except (TypeError, ValueError):
                    continue
                canvas.line(x1, y1, x2, y2, self.LAYER_CONDUCTORES)

    def _emit_components(self, canvas):
        for comp in self._active_components():
            # Los empalmes se exportan aparte como círculos.
            if getattr(comp, "component_type", "") == "junction":
                continue
            x, y = getattr(comp, "x", 0), getattr(comp, "y", 0)
            w, h = getattr(comp, "size", (0, 0))
            rot = getattr(comp, "rotation", 0) or 0
            svg_path = getattr(comp, "svg_path", None)
            svg_file = getattr(comp, "svg_file", None)
            if svg_path and svg_file:
                category = (getattr(comp, "category", "") or "").lower()
                full = Path(svg_path) / category / svg_file
                if full.is_file():
                    self._emit_svg_symbol(
                        canvas, full, comp, x, y, w, h, rot, 1.0
                    )
                    self._emit_component_labels(canvas, comp, x, y, w, h)
                    continue
                self.warnings.append(f"Símbolo no encontrado: {full}")
            self._emit_symbol_fallback(canvas, comp, x, y, w, h)
            self._emit_component_labels(canvas, comp, x, y, w, h)

    def _emit_component_labels(self, canvas, comp, x, y, w, h):
        """Dibuja el designador y los detalles del componente."""
        if not getattr(getattr(self.app, "canvas", None), "show_labels", True):
            return
        label_data = getattr(comp, "label_data", None) or {}
        name = label_data.get("name")
        if not name:
            return

        is_right = label_data.get("derecha", True)
        align = "left" if is_right else "right"
        lx = x + w + 5 if is_right else x - 5
        ly = y + 10

        if getattr(comp, "component_type", "") == "fase":
            # Las etiquetas de fase van al lado opuesto de la conexión.
            try:
                from ui.label_renderer import LabelRenderer

                canvas_lx, canvas_ly, tk_anchor = LabelRenderer._get_fase_label_position(comp)
                zoom = self._zoom()
                lx, ly = canvas_lx / zoom, canvas_ly / zoom
                anchor_map = {
                    "n": ("center", 8), "s": ("center", 0),
                    "w": ("left", 3), "e": ("right", 3),
                    "nw": ("left", 8), "ne": ("right", 8),
                }
                align, baseline = anchor_map.get(tk_anchor, ("left", 8))
                ly += baseline
            except Exception:
                pass

        canvas.text(name, lx, ly, _LABEL_FONT_PX, self.LAYER_TEXTOS, align=align)
        y_offset = 12
        if label_data.get("show_details") and label_data.get("description"):
            canvas.text(
                str(label_data["description"]),
                lx,
                ly + y_offset,
                _DESCRIPTION_FONT_PX,
                self.LAYER_TEXTOS,
                align=align,
            )
            y_offset += 12
        if label_data.get("show_details") and getattr(comp, "component_type", "") == "normal":
            for field in ("marca", "voltaje", "amperios", "potencia"):
                if field == "potencia" and getattr(comp, "category", "") != "Motors":
                    continue
                value = label_data.get(field)
                if value:
                    canvas.text(
                        str(value), lx, ly + y_offset, _LABEL_FONT_PX,
                        self.LAYER_TEXTOS, align=align,
                    )
                    y_offset += 10

    def _emit_symbol_fallback(self, canvas, comp, x, y, w, h):
        """Dibuja un rectángulo cuando el símbolo no tiene SVG disponible."""
        canvas._polyline(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
            self.LAYER_SIMBOLOS,
            closed=True,
        )

    def _prepare_symbol_svg(self, comp, raw):
        """Aplica visibilidad de capas y sustituciones de texto del componente."""
        for name in (
            "_apply_terminal_labels_to_svg",
            "_apply_power_supply_values_to_svg",
            "_apply_layer_visibility",
        ):
            hook = getattr(comp, name, None)
            if callable(hook):
                try:
                    raw = hook(raw)
                except Exception as exc:
                    self.warnings.append(
                        f"{name} falló en {getattr(comp, 'svg_file', '?')}: {exc}"
                    )
        return raw

    def _svg_source(self, full):
        """Devuelve (texto, raiz) de un SVG, cacheados por archivo.

        El mismo símbolo aparece muchas veces en un plano; sin este caché se
        releía el archivo y se reparseaba el XML en cada instancia.
        """
        key = str(full)
        raw = self._svg_text.get(key)
        if raw is None:
            try:
                raw = full.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                self.warnings.append(f"No se pudo leer {full.name}: {exc}")
                return None, None
            self._svg_text[key] = raw
        if key in self._svg_root:
            return raw, self._svg_root[key]
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            self.warnings.append(f"SVG inválido {full.name}: {exc}")
            self._svg_root[key] = None
            return raw, None
        self._svg_root[key] = root
        return raw, root

    def _emit_svg_symbol(self, canvas, full, comp, x, y, w, h, rot, zoom):
        """Escribe la geometría como bloque y los textos como entidades individuales."""
        raw, root = self._svg_source(full)
        if raw is None or root is None:
            return

        vb_x, vb_y, vb_w, vb_h = self._viewbox_size(root, w, h)
        # Centra el símbolo en su caja visual sin deformarlo al rotar.
        orig_w, orig_h = [float(v) for v in (getattr(comp, "original_size", None) or (w, h))]
        # Corrige viewBox con orientación opuesta a original_size.
        if orig_h and vb_h:
            if (orig_w / orig_h > 1 and vb_w / vb_h < 1) or (
                orig_w / orig_h < 1 and vb_w / vb_h > 1
            ):
                orig_w, orig_h = orig_h, orig_w

        vb_w = vb_w or 1.0
        vb_h = vb_h or 1.0
        dx = (float(w) - orig_w) / 2.0
        dy = (float(h) - orig_h) / 2.0

        # El origen del viewBox también forma parte de su viewport.  Ignorarlo
        # desplaza cualquier SVG que use coordenadas negativas (por ejemplo,
        # selector-3 y los roller-switches) respecto a sus puntos de conexión.
        local = _Transform(orig_w / vb_w, 0.0, 0.0, orig_h / vb_h, dx, dy)
        local = local * _Transform(1.0, 0.0, 0.0, 1.0, -vb_x, -vb_y)
        local = local * _Transform(zoom, 0, 0, zoom, 0, 0)

        block = self._symbol_block(canvas, full, comp, raw, local, w, h, zoom)
        if block:
            self._insert_block(canvas, block[0], x, y, w, h, rot, comp, bbox=block[1])
        else:
            # Si el SVG no permite crear un bloque, dibuja su geometría directamente.
            geo_root = self._parse_root(self._prepare_geometry_svg(comp, raw), full)
            if geo_root is not None:
                self._emit_svg_document(
                    canvas,
                    geo_root,
                    self._symbol_world_xform(x, y, w, h, rot, local),
                    self.LAYER_SIMBOLOS,
                    comp,
                    mode="geometry",
                )

        text_root = self._parse_root(self._prepare_symbol_svg(comp, raw), full)
        if text_root is not None:
            self._emit_svg_document(
                canvas,
                text_root,
                self._symbol_world_xform(x, y, w, h, rot, local),
                self.LAYER_TEXTOS,
                comp,
                mode="text",
            )

    def _symbol_world_xform(self, x, y, w, h, rot, local):
        """Transforma el símbolo al mundo y aplica el giro sobre el centro de la caja."""
        base = _Transform(1, 0, 0, 1, x, y)
        if rot:
            rad = math.radians(rot)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            base = (
                base
                * _Transform(1, 0, 0, 1, w / 2.0, h / 2.0)
                * _Transform(cos_a, sin_a, -sin_a, cos_a, 0, 0)
                * _Transform(1, 0, 0, 1, -w / 2.0, -h / 2.0)
            )
        return base * local

    @staticmethod
    def _viewbox_size(root, w, h):
        """Devuelve (vb_x, vb_y, vb_w, vb_h) del viewBox del SVG, con la caja visual como respaldo."""
        vb = (root.get("viewBox") or "").split()
        if len(vb) == 4:
            try:
                vb_x, vb_y, vb_w, vb_h = float(vb[0]), float(vb[1]), float(vb[2]), float(vb[3])
                return vb_x, vb_y, vb_w, vb_h
            except ValueError:
                pass
        return 0.0, 0.0, float(w or 1.0), float(h or 1.0)

    def _parse_root(self, raw, full):
        try:
            return ET.fromstring(raw)
        except ET.ParseError as exc:
            self.warnings.append(f"SVG inválido {full.name}: {exc}")
            return None

    def _symbol_block(self, canvas, full, comp, raw, local, w, h, zoom):
        """Devuelve el bloque de geometría y su extensión, o None si está vacío."""
        vis = self._visibility_key(comp)
        cache_key = (
            full.stem,
            vis,
            round(float(w), 2),
            round(float(h), 2),
            round(zoom, 4),
        )
        cached = self._blocks.get(cache_key)
        if cached:
            return cached

        geo_svg = self._prepare_geometry_svg(comp, raw)
        geo_root = self._parse_root(geo_svg, full)
        if geo_root is None:
            return None
        sig = self._geometry_signature(geo_svg, w, h)
        reused = self._blocks.get(("sig",) + sig)
        if reused:
            self._blocks[cache_key] = reused
            return reused

        name = self._unique_block_name(full.stem)
        block = canvas.doc.blocks.new(name=name, base_point=(0, 0))
        inner = _Canvas(canvas.doc, canvas.scale, 0.0, y_up=False)
        inner.dst = block
        # El punto de inserción es el centro del símbolo.
        local_block = _Transform(1, 0, 0, 1, -float(w) / 2.0, -float(h) / 2.0) * local
        try:
            self._emit_svg_document(
                inner, geo_root, local_block, self.LAYER_SIMBOLOS, comp, mode="geometry"
            )
        except Exception as exc:
            self.warnings.append(f"Bloque {name} incompleto ({full.name}): {exc}")
        if not len(block):
            canvas.doc.blocks.delete_block(name, safe=False)
            return None
        self._blocks[("sig",) + sig] = (name, inner.local_bbox)
        self._blocks[cache_key] = (name, inner.local_bbox)
        return self._blocks[cache_key]

    def _geometry_signature(self, geo_svg, w, h):
        """Firma del SVG preparado y las dimensiones del bloque."""
        try:
            digest = hashlib.sha1(geo_svg.encode("utf-8", "ignore")).hexdigest()
        except Exception:
            digest = ""
        return digest, (round(float(w), 2), round(float(h), 2))

    def _prepare_geometry_svg(self, comp, raw):
        """Aplica la visibilidad de capas antes de crear el bloque."""
        hook = getattr(comp, "_apply_layer_visibility", None)
        if callable(hook):
            try:
                return hook(raw)
            except Exception as exc:
                self.warnings.append(
                    f"_apply_layer_visibility falló en {getattr(comp, 'svg_file', '?')}: {exc}"
                )
        return raw

    def _visibility_key(self, comp):
        """Firma del estado del componente que decide qué capas del SVG se ven."""
        label = getattr(comp, "label_data", None) or {}
        burner = getattr(comp, "burner_layer_states", None) or {}
        parts = (
            getattr(comp, "component_activation_mode", None),
            getattr(comp, "is_active", None),
            getattr(comp, "motor_direction", None),
            getattr(comp, "current_position", None),
            getattr(comp, "layer_running", None),
            label.get("vdf_analog_enabled"),
            label.get("lotto"),
            burner.get("PE"),
            burner.get("N"),
        )
        if not any(p not in (None, False, 0, "") for p in parts):
            return ""
        return _UNSAFE_NAME_RE.sub("_", "_".join(str(p) for p in parts))

    def _unique_block_name(self, stem):
        base = _UNSAFE_NAME_RE.sub("_", stem)[:40].strip("_") or "SIMBOLO"
        name = base
        index = 2
        while name in self._block_names:
            name = f"{base}_{index}"
            index += 1
        self._block_names.add(name)
        return name

    def _insert_block(self, canvas, name, x, y, w=0.0, h=0.0, rot=0.0, comp=None, bbox=None):
        """Inserta un bloque en el centro del símbolo y añade su etiqueta a XDATA."""
        cx = x + float(w) / 2.0
        cy = y + float(h) / 2.0
        if bbox:
            rad = math.radians(float(rot or 0.0))
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            for bx, by in (
                (bbox[0], bbox[1]),
                (bbox[2], bbox[1]),
                (bbox[2], bbox[3]),
                (bbox[0], bbox[3]),
            ):
                canvas.track_point(cx + bx * cos_a - by * sin_a, cy + bx * sin_a + by * cos_a)
        attribs = {
            "layer": self.LAYER_SIMBOLOS if comp is not None else self.LAYER_PUNTOS,
            "rotation": (-float(rot or 0.0)) % 360.0,
            "xscale": 1.0,
            "yscale": 1.0,
            "zscale": 1.0,
        }
        try:
            ref = canvas.msp.add_blockref(name, canvas.point(cx, cy), dxfattribs=attribs)
        except Exception as exc:
            self.warnings.append(f"No se pudo insertar el bloque {name}: {exc}")
            return None
        if comp is not None:
            label = str((getattr(comp, "label_data", None) or {}).get("name") or "").strip()
            if label:
                try:
                    ref.set_xdata(self.APPID, [(1000, label)])
                except Exception:
                    pass
        return ref

    def _emit_shapes(self, canvas):
        manager = getattr(self.app, "shape_manager", None)
        shapes = getattr(manager, "shapes", None) or []
        for shape in shapes:
            try:
                bbox = shape.get_bbox()
            except Exception:
                bbox = None
            layer = self.LAYER_GEOMETRIA
            if getattr(shape, "shape_type", "") == "canaleta":
                layer = self.LAYER_GEOMETRIA
            if bbox:
                x0, y0, x1, y1 = bbox
                canvas._polyline(
                    [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, closed=True
                )
            stype = getattr(shape, "shape_type", "")
            if stype == "circle":
                r = _fnum(getattr(shape, "radius", 0))
                canvas.circle(shape.x, shape.y, r, layer)
            elif stype == "din_rail":
                self._emit_din_profile(canvas, shape)

    def _emit_din_profile(self, canvas, shape):
        """Dibuja las líneas interiores del perfil DIN."""
        try:
            x, y, w, h = shape.get_bbox()
        except Exception:
            return
        x0, y0, x1, y1 = x, y, x + w, y + h
        for frac in (0.15, 0.85):
            ly = y0 + (y1 - y0) * frac
            canvas.line(x0, ly, x1, ly, self.LAYER_GEOMETRIA)

    def _emit_text_components(self, canvas):
        for tc in getattr(self.app, "text_components", []) or []:
            value = (getattr(tc, "text", "") or "").strip()
            if not value:
                continue
            size = _fnum(getattr(tc, "font_size", 0), 0) or 10.0
            rotation = _fnum(getattr(tc, "rotation", 0), 0)
            anchor = getattr(tc, "anchor", "center")
            align = {"center": "center", "w": "left", "e": "right"}.get(anchor, "left")
            size = self._fit_safety_text_size(tc, value, size, align)
            canvas.text(
                value,
                getattr(tc, "x", 0),
                getattr(tc, "y", 0),
                size,
                self.LAYER_TEXTOS,
                rotation,
                align=align,
            )

    def _fit_safety_text_size(self, text_component, value, size, align):
        """Evita que el texto de la hoja de seguridad rebase su marco en DXF.

        El lienzo de Tk mide el texto con Arial, mientras que algunos lectores
        DXF sustituyen la fuente por una de mayor ancho. Se conserva el diseño
        original y solo se reduce, cuando hace falta, el tamaño de cada renglón
        de esa hoja al exportar.
        """
        project = getattr(self.app, "project", None)
        sheets = getattr(project, "sheets", None) or []
        index = getattr(project, "active_sheet_index", -1)
        if not isinstance(index, int) or not 0 <= index < len(sheets):
            return size
        if getattr(sheets[index], "name", "") != "Prescripciones de Seguridad":
            return size

        x = float(getattr(text_component, "x", 0.0))
        # El recuadro principal ocupa x=40..1220; dejamos 20 px interiores.
        if align == "right":
            available = x - 60.0
        elif align == "center":
            available = 2.0 * min(x - 60.0, 1200.0 - x)
        else:
            available = 1200.0 - x
        if available <= 0:
            return size

        # Cota conservadora para Arial: ancho medio de 0.62 veces la altura.
        estimated_width = len(value) * float(size) * 0.62
        if estimated_width <= available:
            return size
        return max(1.0, float(size) * available / estimated_width)

    def _emit_image_components(self, canvas):
        """Exporta las imágenes del plano de borner desde sus SVG de origen."""
        images = getattr(self.app, "image_components", None) or []
        if not images:
            return
        base = self._svg_base_dir()
        for img in images:
            source = getattr(img, "source_svg", None)
            if not source:
                continue
            full = base / source
            if not full.is_file():
                self.warnings.append(f"SVG de imagen no encontrado: {full}")
                continue
            size = getattr(img, "size", None) or (0, 0)
            w, h = float(size[0]), float(size[1])
            if w <= 0 or h <= 0:
                continue
            if Path(source).name.lower() == "borner-pdf.svg":
                w *= BORNER_DXF_SIZE_SCALE
                h *= BORNER_DXF_SIZE_SCALE
            proxy = _SvgImageProxy(source, (w, h), getattr(img, "borner_phase", None))
            x = float(getattr(img, "x", 0.0)) - w / 2.0
            y = float(getattr(img, "y", 0.0)) - h / 2.0
            self._emit_svg_symbol(canvas, full, proxy, x, y, w, h, 0.0, 1.0)

    @staticmethod
    def _svg_base_dir():
        """Carpeta de símbolos SVG, resolviendo la raíz de la aplicación."""
        try:
            from utils.utils import get_app_dir

            base = Path(get_app_dir()) / "svgs"
            if base.is_dir():
                return base
        except Exception:
            pass
        return Path(__file__).resolve().parent.parent / "svgs"

    _TEXT_TAGS = ("text", "tspan", "textPath", "title", "desc")

    def _emit_svg_document(self, canvas, root, xform, layer, comp=None, mode="geometry"):
        """Recorre un SVG raíz sin volver a aplicar su viewport."""
        if self._is_element_hidden(root):
            return
        root_transform = _matrix(root.get("transform"))
        if root_transform is not None:
            xform = xform * root_transform
        for child in root:
            self._emit_element(canvas, child, xform, layer, comp, mode)

    def _emit_element(self, canvas, el, xform, layer, comp=None, mode="geometry"):
        """Recorre el árbol SVG aplicando transformaciones acumuladas."""
        tag = _tag(el)
        if tag == "defs":
            return

        if self._is_element_hidden(el):
            return

        if mode == "geometry" and tag in self._TEXT_TAGS:
            return

        local = _matrix(el.get("transform"))
        if local is not None:
            xform = xform * local
        if tag == "g":
            for child in el:
                self._emit_element(canvas, child, xform, layer, comp, mode)
            return
        if tag == "svg":
            if el.get("width") is None and el.get("height") is None:
                for child in el:
                    self._emit_element(canvas, child, xform, layer, comp, mode)
                return
            nx = _fnum(el.get("x"))
            ny = _fnum(el.get("y"))
            nw = _fnum(el.get("width"), 1.0) or 1.0
            nh = _fnum(el.get("height"), 1.0) or 1.0
            vb = (el.get("viewBox") or "").split()
            if len(vb) == 4:
                try:
                    vbx, vby, vbw, vbh = float(vb[0]), float(vb[1]), float(vb[2]), float(vb[3])
                    sx, sy = nw / vbw if vbw else 1.0, nh / vbh if vbh else 1.0
                except (ValueError, ZeroDivisionError):
                    sx = sy = 1.0
                    vbx = vby = 0.0
                # La transformación de un viewport SVG es
                # translate(x, y) * scale * translate(-viewBox.x, -viewBox.y).
                xform = xform * _Transform(sx, 0, 0, sy, nx, ny)
                xform = xform * _Transform(1, 0, 0, 1, -vbx, -vby)
            else:
                xform = xform * _Transform(1, 0, 0, 1, nx, ny)
            for child in el:
                self._emit_element(canvas, child, xform, layer, comp, mode)
            return

        is_text = tag == "text"
        if mode == "text" and not is_text:
            handler = None
        else:
            handler = {
                "path": self._emit_path,
                "line": self._emit_line,
                "rect": self._emit_rect,
                "circle": self._emit_circle,
                "ellipse": self._emit_ellipse,
                "polyline": self._emit_polygon,
                "polygon": self._emit_polygon,
                "text": self._emit_text,
            }.get(tag)
        if handler is not None:
            handler(canvas, el, xform, layer)
        for child in el:
            self._emit_element(canvas, child, xform, layer, comp, mode)

    def _emit_line(self, canvas, el, xform, layer):
        x1, y1 = xform.apply(_fnum(el.get("x1")), _fnum(el.get("y1")))
        x2, y2 = xform.apply(_fnum(el.get("x2")), _fnum(el.get("y2")))
        canvas.line(x1, y1, x2, y2, layer)

    def _emit_rect(self, canvas, el, xform, layer):
        x, y = _fnum(el.get("x")), _fnum(el.get("y"))
        w, h = _fnum(el.get("width")), _fnum(el.get("height"))
        if w <= 0 or h <= 0:
            return
        pts = [xform.apply(px, py) for px, py in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))]
        canvas._polyline(pts, layer, closed=True)

    def _emit_circle(self, canvas, el, xform, layer):
        cx, cy = _fnum(el.get("cx")), _fnum(el.get("cy"))
        r = _fnum(el.get("r"))
        px, py = xform.apply(cx, cy)
        scale = math.sqrt(abs(xform.a * xform.d - xform.b * xform.c))
        canvas.circle(px, py, r * scale, layer)

    def _emit_ellipse(self, canvas, el, xform, layer):
        cx, cy = _fnum(el.get("cx")), _fnum(el.get("cy"))
        rx, ry = _fnum(el.get("rx")), _fnum(el.get("ry"))
        if rx <= 0 or ry <= 0:
            return
        px, py = xform.apply(cx, cy)
        ux = (xform.a * rx, xform.b * rx)
        vy = (xform.c * ry, xform.d * ry)
        len_x, len_y = math.hypot(*ux), math.hypot(*vy)
        if min(len_x, len_y) <= 1e-9:
            return
        angle = math.degrees(math.atan2(ux[1], ux[0]))
        if len_x >= len_y:
            canvas.ellipse(px, py, len_x, len_y / len_x, angle, layer)
        else:
            canvas.ellipse(px, py, len_y, len_x / len_y, angle + 90.0, layer)

    def _emit_polygon(self, canvas, el, xform, layer):
        raw = el.get("points") or ""
        nums = [float(v) for v in re.findall(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", raw)]
        if len(nums) < 4:
            return
        pts = [xform.apply(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
        canvas._polyline(pts, layer, closed=_tag(el) == "polygon")

    def _emit_text(self, canvas, el, xform, layer):
        value = "".join(el.itertext()).strip()
        if not value:
            return
        size = _fnum(el.get("font-size"), 10.0) or 10.0
        px, py = xform.apply(_fnum(el.get("x")), _fnum(el.get("y")))
        scale = math.sqrt(abs(xform.a * xform.d - xform.b * xform.c)) or 1.0
        rotation = _fnum(el.get("rotate"))
        canvas.text(value, px, py, size * scale, self.LAYER_TEXTOS, rotation)

    def _emit_path(self, canvas, el, xform, layer):
        d = el.get("d")
        if not d:
            return
        _load_ezdxf()
        spt = _svgpathtools
        try:
            parsed = spt.parse_path(d)
        except Exception as exc:
            self.warnings.append(f"Path ilegible: {exc}")
            return
        for seg in parsed:
            if isinstance(seg, spt.Arc):
                self._emit_arc(canvas, seg, xform, layer)
            elif isinstance(seg, (spt.CubicBezier, spt.QuadraticBezier)):
                pts = [seg.point(i / BEZIER_SAMPLES) for i in range(BEZIER_SAMPLES + 1)]
                canvas._polyline([xform.apply(p.real, p.imag) for p in pts], layer)
            else:
                a = xform.apply(seg.start.real, seg.start.imag)
                b = xform.apply(seg.end.real, seg.end.imag)
                canvas.line(a[0], a[1], b[0], b[1], layer)

    def _emit_arc(self, canvas, seg, xform, layer):
        """Un arco SVG se vuelve ARC si es circular; si no, polilínea con bulge."""
        rx, ry = seg.radius.real, seg.radius.imag
        pts = [seg.point(i / ARC_SAMPLES) for i in range(ARC_SAMPLES + 1)]
        xs = [p.real for p in pts]
        ys = [p.imag for p in pts]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        if width <= 1e-9 or height <= 1e-9:
            return

        circular = abs(rx - ry) < CIRCULAR_TOL * max(rx, ry, 1.0)
        if circular and abs(xform.b) < 1e-12 and abs(xform.c) < 1e-12:
            center = seg.center
            cx, cy = float(center.real), float(center.imag)
            px, py = xform.apply(cx, cy)
            scale = math.sqrt(abs(xform.a * xform.d - xform.b * xform.c))
            start_deg = math.degrees(
                math.atan2(seg.start.imag - cy, seg.start.real - cx)
            )
            sweep_deg = math.degrees(float(seg.delta))
            end_deg = start_deg + sweep_deg
            while end_deg <= start_deg:
                end_deg += 360.0
            while end_deg - start_deg >= 360.0:
                end_deg -= 360.0
            if end_deg <= start_deg:
                end_deg = start_deg + 360.0
            try:
                canvas.arc(px, py, rx * scale, start_deg, end_deg, layer)
                return
            except Exception:
                pass

        mapped = [xform.apply(p.real, p.imag) for p in pts]
        bulges = self._bulges_from_points(pts)
        canvas._polyline(mapped, layer, bulges=bulges)

    @staticmethod
    def _bulges_from_points(points):
        """Calcula el bulge DXF de cada tramo a partir de sus tres puntos."""
        bulges = []
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            nxt = points[i + 2] if i + 2 < len(points) else p1
            a = abs(_cross(p1, p2, nxt))
            c = abs(p2 - p1)
            if a < 1e-12 or c < 1e-12:
                bulges.append(0.0)
                continue
            d = abs(p2 - nxt)
            b = abs(nxt - p1)
            if b < 1e-12 or d < 1e-12:
                bulges.append(0.0)
                continue
            s = 4.0 * a / (b * c + c * d)
            if s > 2.0:
                bulges.append(0.0)
                continue
            angle = 2.0 * math.atan2(s, math.sqrt(max(4.0 - s * s, 0.0)))
            bulges.append(math.tan(angle / 4.0))
        return bulges

    def _is_element_hidden(self, el):
        """Determina si el elemento SVG debe omitirse por display:none."""
        style = el.get("style") or ""
        if "display:none" in style or "display: none" in style:
            return True
        try:
            if el.attrib and any(k.endswith("display") for k in el.attrib):
                for k, v in el.attrib.items():
                    if k.endswith("display") and v.strip() == "none":
                        return True
        except Exception:
            pass
        return False

    def _zoom(self):
        canvas = getattr(self.app, "canvas", None)
        zoom = getattr(canvas, "zoom_level", 1.0)
        return zoom if zoom else 1.0

def _cross(p1, p2, p3):
    """Producto cruzado 2D entre p1->p2 y p1->p3."""
    return (p2.real - p1.real) * (p3.imag - p1.imag) - (p2.imag - p1.imag) * (
        p3.real - p1.real
    )

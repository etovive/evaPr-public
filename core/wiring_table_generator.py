import re
import logging
from models.component import TextComponent
from models.shape import Rect

_log = logging.getLogger("evaPr.wiring_table")

SHEET_NAME = "Tabla de Cableado"
EXCLUDED_SHEETS = {"Lista de Materiales", "Resumen de Gabinete", "Plano de Borner", SHEET_NAME}

COLUMNS = [
    ("N° HILO",         95),
    ("HOJA",           110),
    ("ORIGEN / COMP.", 140),
    ("ORIG. TERM.",     80),
    ("DESTINO / COMP.",140),
    ("DEST. TERM.",     80),
    ("SECCIÓN",         85),
    ("BORNER / PASO",  100),
    ("NOTAS TÉCNICAS", 220),
]

START_X, START_Y = 60, 40
ROW_H,   HEAD_H  = 35, 55
TOTAL_WIDTH = sum(w for _, w in COLUMNS)

EXTERNAL_COMPONENT_TYPES = {
    'motor', 'dosificadora', 'boya', 'presostato',
    'sensor', 'actuator', 'lamp_ext', 'solenoid',
}

_EXTERNAL_NAME_RE = re.compile(
    r'^M\d+$|DOSIFICADORA|BOYA|PRESOSTATO|SENSOR', re.IGNORECASE
)

def _is_external(comp):
    if not comp:
        return False
    if str(comp.get('component_type', '') or '').lower() in EXTERNAL_COMPONENT_TYPES:
        return True
    tag = str((comp.get('label_data') or {}).get('name', '') or '').strip()
    if tag and _EXTERNAL_NAME_RE.search(tag):
        return True
    return comp.get('external', False)

def _is_terminal_block(comp):
    """Bornera de paso o de salida a campo: X1…Xn, TB1…"""
    if not comp:
        return False
    if str(comp.get('component_type', '') or '').lower() in (
            'terminal', 'terminal_block', 'borner', 'bornera'):
        return True
    tag = str((comp.get('label_data') or {}).get('name', '') or '').strip().upper()
    return bool(re.match(r'^X\d+$', tag) or re.match(r'^TB\d+$', tag))

def _terminal_tag(comp):
    """Si el componente es bornera devuelve su tag (ej. 'X1'), si no None."""
    if not _is_terminal_block(comp):
        return None
    return str((comp.get('label_data') or {}).get('name', '') or '').strip().upper()

import math

def _get_phys_term(elem, p_idx):
    """Traduce índice de punto de conexión al label físico del terminal usando posición absoluta."""
    if not elem:
        return str(p_idx)

    tag = _get_tag(elem)
    if _is_bus(tag) or _is_signal_label(tag):
        return "-"

    t_data = (elem.get('label_data') or {}).get('terminals', '')
    if not t_data:
        return str(p_idx)

    labels = [l.strip() for l in re.split(r'[;,\-]', t_data) if l.strip()]
    pts = elem.get('conn_points', [])
    if not pts or p_idx >= len(pts):
        return str(p_idx)

    # Sorteo por posición absoluta en el plano (considerando rotación)
    rot = elem.get('rotation', 0)
    angle = math.radians(rot)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)

    abs_pts = []
    for i, p in enumerate(pts):
        rx, ry = p.get('x', 0), p.get('y', 0)
        # Rotación de puntos relativa al componente
        ax = rx * cos_a - ry * sin_a
        ay = rx * sin_a + ry * cos_a
        abs_pts.append({'i': i, 'x': ax, 'y': ay})

    # Ordenar: primero por columnas (X), luego por filas (Y)
    indexed = sorted(
        abs_pts,
        key=lambda p: (round(p['x'] / 5) * 5, round(p['y'] / 5) * 5)
    )

    for order, pt in enumerate(indexed):
        if pt['i'] == p_idx and order < len(labels):
            return labels[order]
    return str(p_idx)

def _is_jumper(name):
    """J1, J2… — nodos ficticios de unión."""
    return bool(name and re.match(r'^J\d+$', str(name).strip().upper()))

def _is_signal_label(name):
    """Saltos de señal. Excluye buses para evitar confusión con Neutro (N)."""
    if not name or _is_bus(name):
        return False
    return bool(re.match(r'^[A-Z]$|^/\d|^\d+$', str(name).strip().upper()))

def _is_bus(name):
    """Nodos de bus de alimentación."""
    return str(name).strip().upper() in {"L1", "N", "PE", "L2", "L3", "L1-1", "L1-2"}

def _get_tag(elem):
    """Obtiene el nombre (tag) de un elemento."""
    if not elem: return ""
    return str((elem.get('label_data') or {}).get('name', '') or '').strip().upper()

def _sec_from_color(color):
    if not color:
        return "1,5mm²"
    c = str(color).strip().lower()
    if c in ('#000000', 'black', '#ff0000', 'red', '#ffff00', 'yellow'):
        return "6mm²"
    if c in ('#0000ff', 'blue', '#00ffff', 'cyan'):
        return "2,5mm²"
    return "1,5mm²"

def _natural_key(text):
    """Clave para ordenamiento alfanumérico natural (Q1, Q2, Q10...)."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(text))]

class WiringTableGenerator:
    def __init__(self, project):
        self.project = project

    def get_wiring_data(self):
        global_signal_map = self._build_global_signal_map()
        physical_wires = []
        terminal_usage = {}
        seen           = set()

        for sh_idx, sheet in enumerate(self.project.sheets):
            if sheet.name in EXCLUDED_SHEETS:
                continue
            elems = getattr(sheet, 'elements', [])
            conns = getattr(sheet, 'connections', [])

            for c in conns:
                s_i = c.get('start_component_idx')
                e_i = c.get('end_component_idx')
                if s_i is None or e_i is None:
                    continue

                res_o = self._resolve(s_i, c.get('start_point_idx', 0), sh_idx, global_signal_map)
                res_d = self._resolve(e_i, c.get('end_point_idx',   0), sh_idx, global_signal_map)

                if not res_o or not res_d:
                    continue

                s_i, sp_i, sh_o = res_o
                e_i, ep_i, sh_d = res_d

                elems_o = getattr(self.project.sheets[sh_o], 'elements', [])
                elems_d = getattr(self.project.sheets[sh_d], 'elements', [])
                comp_o  = elems_o[s_i]
                comp_d  = elems_d[e_i]

                tag_o = _get_tag(comp_o)
                tag_d = _get_tag(comp_d)

                if _is_signal_label(tag_o) or _is_signal_label(tag_d): continue
                if _is_external(comp_o) or _is_external(comp_d): continue
                if _is_bus(tag_o) and _is_bus(tag_d): continue
                if tag_o == tag_d: continue

                term_o = _get_phys_term(comp_o, sp_i)
                term_d = _get_phys_term(comp_d, ep_i)

                # DEDUPLICACIÓN Y NORMALIZACIÓN DE DIRECCIÓN
                # Siempre ponemos los buses en el destino y ordenamos componentes alfabéticamente
                # para que el cableado quede agrupado de forma lógica por componente.
                should_swap = False
                if _is_bus(tag_o) and not _is_bus(tag_d):
                    should_swap = True
                elif not _is_bus(tag_o) and not _is_bus(tag_d):
                    if _natural_key(tag_d) < _natural_key(tag_o):
                        should_swap = True

                if should_swap:
                    tag_o, tag_d = tag_d, tag_o
                    term_o, term_d = term_d, term_o
                    comp_o, comp_d = comp_d, comp_o

                conn_key = frozenset([(tag_o, term_o), (tag_d, term_d)])
                if conn_key in seen: continue
                seen.add(conn_key)

                o_key = (tag_o, term_o)
                d_key = (tag_d, term_d)
                terminal_usage[o_key] = terminal_usage.get(o_key, 0) + 1
                terminal_usage[d_key] = terminal_usage.get(d_key, 0) + 1

                line_color = c.get('line_color', '')
                sec = _sec_from_color(line_color)
                borner = _terminal_tag(comp_d) or _terminal_tag(comp_o) or '-'

                physical_wires.append({
                    'hoja':       sheet.name,
                    'o_n':        tag_o,
                    'o_t':        term_o,
                    'd_n':        tag_d,
                    'd_t':        term_d,
                    'sec':        sec,
                    'borner':     borner,
                    'o_key':      o_key,
                    'd_key':      d_key,
                })

        # ORDENAMIENTO ESTILO "MUNDO REAL": por componente y luego por terminal
        physical_wires.sort(key=lambda w: (
            _natural_key(w['o_n']),
            _natural_key(w['o_t']),
            _natural_key(w['d_n'])
        ))

        for i, wire in enumerate(physical_wires):
            wire['hilo'] = f"W{str(i + 1).zfill(3)}"
            is_derivation = (terminal_usage.get(wire['o_key'], 0) > 1 or
                             terminal_usage.get(wire['d_key'], 0) > 1)
            wire['nota'] = "COLOCAR PIN DOBLE (Derivación)" if is_derivation else "PIN SIMPLE (Directo)"

        return physical_wires

    def _build_global_signal_map(self):
        gmap = {}
        for sh_idx, sheet in enumerate(self.project.sheets):
            if sheet.name in EXCLUDED_SHEETS: continue
            for e_idx, elem in enumerate(getattr(sheet, 'elements', [])):
                if elem.get('type') == 'text': continue
                tag = _get_tag(elem)
                if _is_signal_label(tag):
                    gmap.setdefault(tag, []).append((sh_idx, e_idx))
        return gmap

    def _resolve(self, comp_idx, point_idx, sh_idx, global_signal_map, visited=None):
        if visited is None: visited = set()
        state = (sh_idx, comp_idx)
        if state in visited: return None
        visited.add(state)

        sheet = self.project.sheets[sh_idx]
        elems = getattr(sheet, 'elements', [])
        elem  = elems[comp_idx]
        tag   = _get_tag(elem)
        etype = elem.get('type', '')

        if etype == 'junction' or _is_jumper(tag):
            conns = getattr(sheet, 'connections', [])
            for c in conns:
                s2, e2 = c.get('start_component_idx'), c.get('end_component_idx')
                if s2 == comp_idx:
                    res = self._resolve(e2, c.get('end_point_idx', 0), sh_idx, global_signal_map, visited)
                    if res: return res
                elif e2 == comp_idx:
                    res = self._resolve(s2, c.get('start_point_idx', 0), sh_idx, global_signal_map, visited)
                    if res: return res
            return None

        if _is_signal_label(tag):
            partners = [
                (si, ei) for si, ei in global_signal_map.get(tag, [])
                if not (si == sh_idx and ei == comp_idx)
            ]
            for p_sh_idx, p_e_idx in partners:
                p_sheet = self.project.sheets[p_sh_idx]
                p_conns = getattr(p_sheet, 'connections', [])
                for c2 in p_conns:
                    s2, e2 = c2.get('start_component_idx'), c2.get('end_component_idx')
                    if s2 == p_e_idx:
                        res = self._resolve(e2, c2.get('end_point_idx', 0), p_sh_idx, global_signal_map, visited)
                        if res: return res
                    elif e2 == p_e_idx:
                        res = self._resolve(s2, c2.get('start_point_idx', 0), p_sh_idx, global_signal_map, visited)
                        if res: return res
            return None

        return comp_idx, point_idx, sh_idx

    def generate_wiring_table_sheet(self, app):
        s_idx = next((i for i, s in enumerate(app.project.sheets) if s.name == SHEET_NAME), -1)
        if s_idx == -1:
            app.project.add_sheet(SHEET_NAME)
            s_idx = len(app.project.sheets) - 1
        app.switch_to_sheet(s_idx)
        app.canvas.delete("all")
        app.components.clear()
        app.connections.clear()
        app.text_components.clear()
        if hasattr(app, 'shape_manager'): app.shape_manager.shapes.clear()
        physical_wires = self.get_wiring_data()
        self._draw(app, physical_wires)
        app.set_status(f"✅ Tabla de Cableado: {len(physical_wires)} conexiones internas generadas.", "green")

    def _draw(self, app, rows):
        y = START_Y
        h_bg = Rect(START_X + TOTAL_WIDTH / 2, y, TOTAL_WIDTH + 10, 50)
        h_bg.fill = "#1a252f"
        app.shape_manager.shapes.append(h_bg)
        h_bg.draw(app.canvas)
        TextComponent(app.canvas, "LISTADO DE CABLEADO PUNTO A PUNTO", 12, START_X + TOTAL_WIDTH / 2, y, color="#fff", bold=True)
        y += 55
        c_bg = Rect(START_X + TOTAL_WIDTH / 2, y, TOTAL_WIDTH, HEAD_H)
        c_bg.fill = "#2c3e50"
        app.shape_manager.shapes.append(c_bg)
        c_bg.draw(app.canvas)
        cx = START_X
        for lbl, w in COLUMNS:
            TextComponent(app.canvas, lbl, 9, cx + w / 2, y, color="#fff", bold=True)
            cx += w
        y += (HEAD_H / 2) + (ROW_H / 2)
        for i, r in enumerate(rows):
            r_bg = Rect(START_X + TOTAL_WIDTH / 2, y, TOTAL_WIDTH, ROW_H)
            r_bg.fill    = "#f2f3f4" if i % 2 == 0 else "#ffffff"
            r_bg.outline = "#d5dbdb"
            app.shape_manager.shapes.append(r_bg)
            r_bg.draw(app.canvas)
            txt_vals = [r['hilo'], r['hoja'], r['o_n'], r['o_t'], r['d_n'], r['d_t'], r['sec'], r.get('borner', '-'), r.get('nota', '')]
            cx = START_X
            for val, (_, cw) in zip(txt_vals, COLUMNS):
                color = "#d35400" if "DOBLE" in str(val) else "#2c3e50"
                TextComponent(app.canvas, str(val), 8, cx + cw / 2, y, color=color)
                cx += cw
            y += ROW_H
            if y > 900: app.canvas.config(scrollregion=(0, 0, TOTAL_WIDTH + 200, y + 500))

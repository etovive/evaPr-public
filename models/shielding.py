import tkinter as tk
from typing import List, Optional, Dict
from utils.coordinates import draw_world_line, draw_world_oval, world_to_canvas_coords
from utils.utility_functions import adapt_color_for_display

class Shielding:
    """
    Representa un conjunto de apantallamiento que cruza múltiples conductores.
    """

    def __init__(self, x1: float, x2: float, y: float, labels: List[Dict] = None, header_text: str = None,
                 num_wires: int = 0, gauge: float = 1.5, cable_name: str = "X1"):
        self.x1 = x1
        self.x2 = x2
        self.y = y
        self.labels = labels or []

        # Atributos estructurados (prioridad a parámetros directos)
        self.num_wires = num_wires if num_wires > 0 else len(self.labels)
        self.gauge = gauge
        self.cable_name = cable_name
        self.voltage = "300/500V"

        # Si se pasa un header_text, intentar parsearlo para recuperar datos si están en 0
        if header_text:
            self.header_text = header_text
            # Solo parsear si los valores actuales son los por defecto de clase
            if self.num_wires == 0 or self.gauge == 1.5:
                self._parse_header_text(header_text)
        else:
            self.update_header_from_fields()

        self.canvas_ids = []
        self.selected = False
        self.unique_tag = f"shielding_{id(self)}"

    def to_dict(self) -> Dict:
        return {
            'x1': self.x1,
            'x2': self.x2,
            'y': self.y,
            'labels': self.labels,
            'header_text': self.header_text,
            'num_wires': self.num_wires,
            'gauge': self.gauge,
            'cable_name': self.cable_name,
            'voltage': self.voltage
        }

    @classmethod
    def from_dict(cls, data: Dict):
        sh = cls(
            x1=data['x1'],
            x2=data['x2'],
            y=data['y'],
            labels=data.get('labels', []),
            header_text=data.get('header_text')
        )
        sh.num_wires = data.get('num_wires', sh.num_wires)
        sh.gauge = data.get('gauge', sh.gauge)
        sh.cable_name = data.get('cable_name', sh.cable_name)
        sh.voltage = data.get('voltage', "300/500V")
        return sh

    def _parse_header_text(self, text: str):
        """Intenta extraer hilos, calibre y nombre de un string de cabecera."""
        try:
            # Ejemplos válidos:
            # "4x1,5=+-X1\n300/500V"
            # "4x10 AWG=+-X1\n300/500V"
            import re
            match = re.search(r"(\d+)x\s*([\d,.]+)\s*(?:AWG)?\s*=+-(.*)", text, re.IGNORECASE)
            if match:
                self.num_wires = int(match.group(1))
                gauge_str = match.group(2).replace(',', '.')
                gauge_num = float(gauge_str)
                if 'awg' in text.lower():
                    gauge_num = self.awg_to_mm2(gauge_num)
                self.gauge = gauge_num
                self.cable_name = match.group(3).split('\n')[0].strip()

                if '\n' in match.group(3):
                    self.voltage = match.group(3).split('\n')[1].strip()
        except:
            pass

    def update_header_from_fields(self):
        """Sincroniza header_text basado en los campos individuales."""
        awg = self.get_awg_equivalent()
        self.header_text = f"{self.num_wires}x{awg} AWG=+-{self.cable_name}\n{self.voltage}"

    def get_awg_equivalent(self) -> str:
        """Devuelve el equivalente aproximado en AWG"""
        # Tabla estándar mm2 -> AWG
        mm2_to_awg = {
            0.5: "20", 0.75: "18", 1.0: "17", 1.5: "16", 2.5: "14",
            4.0: "12", 6.0: "10", 10.0: "8", 16.0: "6", 25.0: "4",
            35.0: "2", 50.0: "1/0", 70.0: "2/0", 95.0: "3/0", 120.0: "4/0"
        }
        # Buscar el valor más cercano si no es exacto
        if self.gauge in mm2_to_awg:
            return mm2_to_awg[self.gauge]

        # Fallback: encontrar el más cercano
        closest = min(mm2_to_awg.keys(), key=lambda x: abs(x - self.gauge))
        return mm2_to_awg[closest]

    @staticmethod
    def awg_to_mm2(awg_value: float) -> float:
        """Convierte un valor AWG aproximado a mm² para mantener compatibilidad interna."""
        awg_map = {
            20: 0.5, 18: 0.75, 17: 1.0, 16: 1.5, 14: 2.5,
            12: 4.0, 10: 6.0, 8: 10.0, 6: 16.0, 4: 25.0,
            2: 35.0, 1: 50.0, 0: 50.0, -1: 70.0, -2: 95.0, -3: 120.0,
            -4: 150.0
        }
        awg_key = round(float(awg_value))
        return awg_map.get(awg_key, 1.5)

    def draw(self, canvas: tk.Canvas):
        """Dibuja el apantallamiento en el canvas con paridad visual al EJEMPLO.png"""
        self.clear(canvas)

        # Tag único para este objeto para permitir movimientos eficientes
        tag = self.unique_tag

        zoom = getattr(canvas, 'zoom_level', 1.0)
        canvas_bg = canvas.cget("bg")
        color_azul = adapt_color_for_display("#0000FF", canvas_bg)
        color_rojo = adapt_color_for_display("#CC0000", canvas_bg) # Rojo profesional
        color_verde = adapt_color_for_display("#00AA00", canvas_bg) # Verde profesional

        # 1. Cápsula de apantallamiento (Dashed blue capsule) - FONDO
        h_capsule = 16
        y_capsule = self.y + 10
        y_top = y_capsule - h_capsule/2
        y_bottom = y_capsule + h_capsule/2

        outline_color = color_azul
        outline_width = 1.5
        if self.selected:
            outline_color = "#FFD700" # Dorado para selección
            outline_width = 3.0

        self.canvas_ids.append(draw_world_oval(
            canvas, self.x1 - 15, y_top, self.x2 + 15, y_bottom,
            outline=outline_color, width=outline_width, dash=(6, 4), fill="", tags=("shielding", tag)
        ))

        # 2. Línea horizontal de referencia (solid blue line) - ARRIBA
        y_line = self.y - 12
        self.canvas_ids.append(draw_world_line(
            canvas, self.x1 - 20, y_line, self.x2 + 20, y_line,
            fill=outline_color, width=outline_width, tags=("shielding", tag)
        ))

        # 3. Slashes (/) y Etiquetas (BK, BN...)
        for label in self.labels:
            lx = label['x']
            l_text = label['text']
            is_pe = "GNYE" in l_text.upper()
            l_color = color_verde if is_pe else color_rojo

            # A. Slash diagonal (/) - EN EL CABLE
            self.canvas_ids.append(draw_world_line(
                canvas, lx - 3, self.y + 3,
                lx + 3, self.y - 3,
                fill=l_color, width=2.0, tags=("shielding", tag)
            ))

            # B. Etiqueta (BK, BN, etc.) - ENCIMA DE LA LÍNEA AZUL
            sx, sy = world_to_canvas_coords(lx, y_line - 1, canvas)
            self.canvas_ids.append(canvas.create_text(
                sx, sy, text=l_text, fill=l_color,
                font=("Arial", int(8 * zoom)), anchor=tk.S, tags=("shielding", tag)
            ))

        # 4. Cabecera (Cable specs) - IZQUIERDA SUPERIOR
        hx, hy = world_to_canvas_coords(self.x1 - 22, y_line, canvas)

        text_id = canvas.create_text(
            hx, hy, text=self.header_text, fill=color_azul,
            font=("Arial", int(9 * zoom)), justify=tk.RIGHT, anchor=tk.E,
            tags=("shielding", "shielding_label", tag)
        )
        self.canvas_ids.append(text_id)

        # Asegurar que esté por encima de todo
        canvas.tag_raise(tag)

    def clear(self, canvas: tk.Canvas):
        """Elimina los elementos visuales del canvas"""
        for cid in self.canvas_ids:
            try:
                canvas.delete(cid)
            except:
                pass
        self.canvas_ids = []

    def contains_point(self, x: float, y: float, tolerance: float = 10.0) -> bool:
        """Verifica si el punto está cerca de la línea principal"""
        if abs(y - self.y) > tolerance:
            return False
        return min(self.x1, self.x2) - tolerance <= x <= max(self.x1, self.x2) + tolerance

    def move(self, dx: float, dy: float, canvas: Optional[tk.Canvas] = None):
        """Mueve el apantallamiento en el mundo (Restringido a vertical)"""
        self.y += dy

        # En lugar de borrar y redibuja, movemos todos los elementos con el tag único
        if canvas:
            # dy en canvas depende del zoom
            zoom = getattr(canvas, 'zoom_level', 1.0)
            dy_canvas = dy * zoom

            canvas.move(self.unique_tag, 0, dy_canvas)

            # Nota: Si el zoom cambia, el move de canvas no es suficiente,
            # pero en un drag el zoom suele ser constante.
            # En caso de duda, forzamos un redraw final en on_release (se maneja en Application)

class ShieldingManager:
    """Gestiona las instancias de Shielding en el proyecto"""

    def __init__(self, app):
        self.app = app
        self.shieldings: List[Shielding] = []
        self.active_preview: Optional[Shielding] = None
        self.selected_shielding: Optional[Shielding] = None

    def add_shielding(self, shielding: Shielding):
        self.shieldings.append(shielding)
        shielding.draw(self.app.canvas)

    def select_shielding(self, shielding: Optional[Shielding]):
        """Maneja la selección de un apantallamiento"""
        if self.selected_shielding and self.selected_shielding != shielding:
            self.selected_shielding.selected = False
            self.selected_shielding.draw(self.app.canvas)

        self.selected_shielding = shielding

        if self.selected_shielding:
            self.selected_shielding.selected = True
            self.selected_shielding.draw(self.app.canvas)
            if hasattr(self.app, 'set_status'):
                self.app.set_status("🛡️ Apantallamiento seleccionado", "blue")

    def move_selected_shielding(self, dx: float, dy: float):
        """Mueve el apantallamiento seleccionado"""
        if self.selected_shielding:
            self.selected_shielding.move(dx, dy, self.app.canvas)

    def find_shielding_at(self, x: float, y: float, tolerance: float = 20.0) -> Optional[Shielding]:
        """Busca si hay un apantallamiento en la posición dada"""
        # Prioridad a los más recientes (encima)
        for sh in reversed(self.shieldings):
            if sh.contains_point(x, y, tolerance):
                return sh
        return None

    def remove_shielding(self, shielding: Shielding):
        if shielding in self.shieldings:
            shielding.clear(self.app.canvas)
            self.shieldings.remove(shielding)
            if self.selected_shielding == shielding:
                self.selected_shielding = None

    def detect_intersections(self, y: float, x_start: float, x_end: float) -> List[Dict]:
        """Detecta cables que cruzan la línea horizontal y devuelve etiquetas con info de potencia"""
        intersections = []
        x_min, x_max = min(x_start, x_end), max(x_start, x_end)

        # Recorrer todas las conexiones para encontrar segmentos verticales que crucen y
        for conn in getattr(self.app, 'connections', []):
            if not hasattr(conn, 'segments') or not conn.segments:
                continue

            for segment in conn.segments:
                try:
                    if len(segment) < 2: continue
                    p1, p2 = segment[0], segment[1]
                    sx1, sy1 = p1[0], p1[1]
                    sx2, sy2 = p2[0], p2[1]

                    if abs(sx1 - sx2) < 5:
                        if min(sy1, sy2) - 5 <= y <= max(sy1, sy2) + 5:
                            if x_min - 2 <= sx1 <= x_max + 2:
                                is_pe = False
                                phase = None

                                # Intentar detectar la fase del componente conectado
                                for comp in [conn.start_component, conn.end_component]:
                                    if hasattr(comp, 'label_data') and comp.label_data.get('name'):
                                        name = str(comp.label_data['name']).upper().strip()
                                        if name in ['L1', 'L2', 'L3', 'N', 'PE']:
                                            phase = name
                                            break

                                if phase == 'PE': is_pe = True

                                line_dash = getattr(conn, 'line_dash', None)
                                if line_dash: is_pe = True

                                line_color = str(getattr(conn, 'line_color', "")).lower()
                                if any(c in line_color for c in ["green", "lime", "gnye"]):
                                    is_pe = True

                                # Intentar obtener información de potencia y amperios del componente de inicio o fin
                                power_val = 0.0
                                amps_val = 0.0
                                for comp in [conn.start_component, conn.end_component]:
                                    if hasattr(comp, 'label_data'):
                                        if comp.label_data.get('potencia') and power_val == 0.0:
                                            try:
                                                # Extraer número del string potencia (ej: "2.2kW" -> 2.2)
                                                p_str = str(comp.label_data['potencia']).lower().replace('kw', '').replace(',', '.')
                                                power_val = float(p_str)
                                            except: pass
                                        if comp.label_data.get('amperios') and amps_val == 0.0:
                                            try:
                                                # Extraer número del string amperios (ej: "12A" -> 12.0)
                                                import re as _re
                                                m = _re.search(r'[\d.]+', str(comp.label_data['amperios']))
                                                if m:
                                                    amps_val = float(m.group())
                                            except: pass

                                intersections.append({
                                    'x': sx1,
                                    'is_pe': is_pe,
                                    'power': power_val,
                                    'amps': amps_val,
                                    'phase': phase
                                })
                except: continue

        unique_intersections = []
        seen_x = set()
        for inter in sorted(intersections, key=lambda i: i['x']):
            is_new = True
            for ux in seen_x:
                if abs(ux - inter['x']) < 4:
                    is_new = False
                    break
            if is_new:
                unique_intersections.append(inter)
                seen_x.add(inter['x'])

        # Mapeo de fase configurable por el usuario (colores de conductores)
        DEFAULT_COLOR_MAP = {
            "L1": "BK", "L2": "RD", "L3": "BU",
            "N": "GY", "PE": "GNYE"
        }
        app_config = getattr(self.app, 'config', {}) or {}
        phase_map = app_config.get("cable_color_map") or DEFAULT_COLOR_MAP
        # Unir con defaults para asegurar que siempre existan las 5 fases
        phase_map = dict(DEFAULT_COLOR_MAP, **phase_map)

        # Heurística inteligente: Determinar esquema de colores basado en el número de conductores activos
        non_pe_intersections = [inter for inter in unique_intersections if not inter.get('is_pe')]
        num_non_pe = len(non_pe_intersections)

        # Heurística inteligente: Determinar esquema de colores basado en el número de conductores activos.
        # Usa el mapa configurado de colores para que las fases/neutro respeten la configuración.
        if num_non_pe == 2:
            non_pe_labels = [phase_map.get("L1", "BK"), phase_map.get("N", "GY")]  # Fase + Neutro
        elif num_non_pe == 3:
            non_pe_labels = [phase_map.get("L1", "BK"), phase_map.get("L2", "RD"), phase_map.get("L3", "BU")]  # 3-Fase
        elif num_non_pe >= 4:
            non_pe_labels = [phase_map.get("L1", "BK"), phase_map.get("L2", "RD"), phase_map.get("L3", "BU"), phase_map.get("N", "GY")]  # 3-Fase + Neutro
        else:
            non_pe_labels = [phase_map.get("L1", "BK"), phase_map.get("L2", "RD"), phase_map.get("L3", "BU"), phase_map.get("N", "GY")]  # Por defecto

        results = []
        non_pe_idx = 0
        max_power = 0.0
        max_amps = 0.0

        for inter in unique_intersections:
            if inter['power'] > max_power: max_power = inter['power']
            if inter.get('amps', 0.0) > max_amps: max_amps = inter['amps']

            # Determinar texto de la etiqueta
            label_text = ""
            if inter['is_pe']:
                label_text = "GNYE"
            else:
                if inter.get('phase') in phase_map:
                    label_text = phase_map[inter['phase']]
                else:
                    # Usar la lista de fallback según la cantidad de hilos detectada
                    if non_pe_idx < len(non_pe_labels):
                        label_text = non_pe_labels[non_pe_idx]
                    else:
                        label_text = "BK" # Fallback ultra-seguro

                non_pe_idx += 1 # Incrementar para conductores activos (fase/neutro)

            results.append({
                'x': inter['x'],
                'text': label_text,
                'color': adapt_color_for_display("#CC0000", self.app.canvas.cget("bg")) if label_text != "GNYE" else adapt_color_for_display("#00AA00", self.app.canvas.cget("bg")),
                'power': inter['power'],
                'amps': inter.get('amps', 0.0),
            })

        return results

    def calculate_header_text(self, intersections: List[Dict]) -> str:
        """Calcula el texto de cabecera basado en cables y amperios (IEC 60364)."""
        from core.protection_suggestions import _cable_section
        import re as _re

        num_wires = len(intersections)
        max_amps = max([i.get('amps', 0.0) for i in intersections]) if intersections else 0.0

        # Usar _cable_section: misma lógica que el botón Sugerir (18 escalones IEC)
        # Devuelve string como "2,5 mm² (AWG 12)"; extraemos el número mm² y lo convertimos a AWG para la cabecera.
        if max_amps > 0:
            label_str = _cable_section(max_amps)
            m = _re.search(r'[\d,]+', label_str)
            gauge = float(m.group().replace(',', '.')) if m else 1.5
        else:
            gauge = 1.5   # fallback: sin amperios disponibles

        awg_value = Shielding(x1=0, x2=0, y=0, gauge=gauge).get_awg_equivalent()
        return f"{num_wires}x{awg_value} AWG=+-X1\n300/500V", num_wires, gauge

    def clear_preview(self):
        if self.active_preview:
            self.active_preview.clear(self.app.canvas)
            self.active_preview = None

    def update_preview(self, x1, y1, x2, y2):
        self.clear_preview()
        labels = self.detect_intersections(y1, x1, x2)
        header, n_wires, n_gauge = self.calculate_header_text(labels)
        self.active_preview = Shielding(
            x1, x2, y1, labels=labels, header_text=header,
            num_wires=n_wires, gauge=n_gauge
        )
        self.active_preview.draw(self.app.canvas)

    def refresh_all_labels(self):
        """Recalcula las etiquetas (códigos de color) de todos los apantallamientos
        usando la configuración actual y los redibuja."""
        for sh in self.shieldings:
            labels = self.detect_intersections(sh.y, sh.x1, sh.x2)
            sh.labels = labels
            sh.num_wires = len(labels)
            sh.draw(self.app.canvas)

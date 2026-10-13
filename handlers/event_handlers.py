import time
import math
from utils.simple_zoom_manager import create_simple_zoom_manager
from utils.alignment_utils import create_alignment_manager
from utils.utility_functions import is_near_segment
from utils.coordinates import event_to_canvas_coords, get_pan_offset, draw_world_oval, draw_world_rectangle
from config.settings import AppConstants

class ShapeDrawingState:
    """Maneja el estado de dibujo de shapes en dos fases"""

    def __init__(self, app):
        self.app = app
        self.is_drawing = False
        self.shape_type = None
        self.start_x = None
        self.start_y = None
        self.preview_id = None

    def activate(self, shape_type):
        """Activa modo de dibujo"""
        self.shape_type = shape_type
        self.is_drawing = False
        self._set_canvas_cursor("crosshair")
        if hasattr(self.app, 'set_status'):
            self.app.set_status(f"🎨 Modo dibujo: {shape_type} - Haga clic para iniciar", "blue", duration=5000)

    def _seccion_canaleta_default(self):
        """Sección comercial (ancho, alto) con la que se dibujan las canaletas nuevas."""
        try:
            from models.shape import _seccion_canaleta_config
            from utils.utils import load_medidas_config
            config_can = load_medidas_config().get("configuracion_formas", {}).get("canaleta", {})
            return _seccion_canaleta_config(config_can)
        except Exception:
            return (40, 40)

    def start_drawing(self, x, y):
        """Primer click: Inicia dibujo"""
        if not self.shape_type:
            return False

        # USAR FUNCIÓN CENTRALIZADA: Calcular coordenadas compensando pan
        self.start_x, self.start_y = event_to_canvas_coords(
            type('Event', (), {'x': x, 'y': y})(),
            self.app.canvas
        )
        self.is_drawing = True

        if hasattr(self.app, 'set_status'):
            self.app.set_status(f"🎨 Dibujando {self.shape_type}: Arrastre y haga clic para finalizar", "green", duration=5000)
        return True

    def update_preview(self, x, y):
        """Actualiza preview mientras arrastra"""
        if not self.is_drawing:
            return

        # USAR FUNCIÓN CENTRALIZADA: Calcular coordenadas compensando pan
        current_x, current_y = event_to_canvas_coords(
            type('Event', (), {'x': x, 'y': y})(),
            self.app.canvas
        )

        if self.preview_id:
            self.app.canvas.delete(self.preview_id)

        # Calcular bbox teniendo en cuenta tipos que deben ser cuadrados (circle, square)
        dx = current_x - self.start_x
        dy = current_y - self.start_y

        if self.shape_type in ["circle", "square"]:
            # Mantener proporción cuadrada: usar la máxima distancia en ambas direcciones
            size = max(abs(dx), abs(dy))
            # Construir bbox centrado en start_x/start_y
            x1 = self.start_x - size
            y1 = self.start_y - size
            x2 = self.start_x + size
            y2 = self.start_y + size
        else:
            x1 = min(self.start_x, current_x)
            y1 = min(self.start_y, current_y)
            x2 = max(self.start_x, current_x)
            y2 = max(self.start_y, current_y)

        if self.preview_id:
            try:
                self.app.canvas.delete(self.preview_id)
            except Exception:
                pass

        if self.shape_type in ["circle", "ellipse"]:
            self.preview_id = draw_world_oval(
                self.app.canvas,
                x1, y1, x2, y2, outline="blue", width=2, dash=(5, 5), fill=""
            )
        elif self.shape_type == "din_rail":
            # Riel DIN: altura fija 35, empieza desde la punta del puntero (start_x, start_y)
            # start_y es la esquina superior -> se extiende 35 hacia abajo
            y1 = self.start_y
            y2 = self.start_y + 35
            self.preview_id = draw_world_rectangle(
                self.app.canvas,
                x1, y1, x2, y2, outline="blue", width=2, dash=(5, 5), fill=""
            )
        elif self.shape_type == "canaleta":
            # Detectar orientación según el movimiento del mouse
            dx = abs(current_x - self.start_x)
            dy = abs(current_y - self.start_y)
            is_vertical = dy > dx
            ancho, alto = self._seccion_canaleta_default()

            if is_vertical:
                # Canaleta vertical: ancho fijo de la sección, empieza desde start_x (borde izquierdo)
                x1 = self.start_x
                x2 = self.start_x + ancho
                y1 = self.start_y
                y2 = current_y
            else:
                # Canaleta horizontal: alto fijo de la sección, empieza desde start_y (borde superior)
                x1 = self.start_x
                x2 = current_x
                y1 = self.start_y
                y2 = self.start_y + alto

            self.preview_id = draw_world_rectangle(
                self.app.canvas,
                x1, y1, x2, y2, outline="blue", width=2, dash=(5, 5), fill=""
            )
            self._canaleta_vertical = is_vertical
        else:  # rectangle, square
            self.preview_id = draw_world_rectangle(
                self.app.canvas,
                x1, y1, x2, y2, outline="blue", width=2, dash=(5, 5), fill=""
            )

    def finish_drawing(self, x, y):
        """Segundo click: Finaliza y crea shape"""
        if not self.is_drawing:
            return None

        # USAR FUNCIÓN CENTRALIZADA: Calcular coordenadas compensando pan
        end_x, end_y = event_to_canvas_coords(
            type('Event', (), {'x': x, 'y': y})(),
            self.app.canvas
        )

        # Calcula dimensiones consistentes con el preview:
        # Para circle/square el preview usa start_x/start_y como centro y 'size' como radio
        # Para rect/ellipse el preview usa start_x/start_y como esquina (corner)
        if self.shape_type in ["circle", "square"]:
            dx = abs(end_x - self.start_x)
            dy = abs(end_y - self.start_y)
            size = max(dx, dy)
            # El preview dibuja un bbox de lado = 2*size (start es centro)
            width = size * 2
            height = size * 2
            center_x = self.start_x
            center_y = self.start_y
        else:
            x1 = min(self.start_x, end_x)
            y1 = min(self.start_y, end_y)
            x2 = max(self.start_x, end_x)
            y2 = max(self.start_y, end_y)
            width = x2 - x1
            height = y2 - y1
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2

        if self.shape_type == "din_rail":
            height = 35
            # center_x = mitad entre start y end, center_y = start_y + 35/2 (punta arriba)
            center_x = (x1 + x2) / 2
            center_y = self.start_y + 17.5
            if width < 10:
                self.cancel()
                return None
        elif self.shape_type == "canaleta":
            is_vertical = getattr(self, '_canaleta_vertical', False)
            ancho, alto = self._seccion_canaleta_default()

            if is_vertical:
                # Canaleta vertical: ancho fijo de la sección, largo = arrastre vertical
                # Empieza desde start_x (borde izquierdo), center_x = start_x + ancho/2
                width = abs(end_y - self.start_y)
                height = alto
                center_x = self.start_x + ancho / 2
                center_y = (self.start_y + end_y) / 2
            else:
                # Canaleta horizontal: alto fijo de la sección, largo = arrastre horizontal
                # Empieza desde start_y (borde superior), center_y = start_y + alto/2
                width = abs(end_x - self.start_x)
                height = alto
                center_x = (self.start_x + end_x) / 2
                center_y = self.start_y + alto / 2

            if width < 10:
                self.cancel()
                return None
        elif width < 10 or height < 10:
            self.cancel()
            return None

        if self.preview_id:
            self.app.canvas.delete(self.preview_id)
            self.preview_id = None

        shape = self._create_shape(center_x, center_y, width, height)

        self.is_drawing = False
        # Desactivar visualmente el botón de la herramienta de shapes si existe el panel
        try:
            if hasattr(self.app, 'drawing_panel') and self.shape_type:
                try:
                    # Llamada segura al método de la UI (puede ser privado)
                    self.app.drawing_panel._deactivate_shape_button(self.shape_type)
                except Exception:
                    pass
        except Exception:
            pass

        # Notificar a la app para que desactive el botón de la barra 2D
        finished_type = self.shape_type  # guardarlo antes de limpiar
        self.shape_type = None
        self.start_x = None
        self.start_y = None
        self.app.canvas.config(cursor="")

        if hasattr(self.app, 'notify_shape_draw_finished'):
            try:
                self.app.notify_shape_draw_finished(finished_type)
            except Exception:
                pass

        if hasattr(self.app, 'set_status'):
            self.app.set_status("✅ Forma creada con éxito", "green")

        return shape

    def _create_shape(self, center_x, center_y, width, height):
        """Crea la shape real"""
        try:
            shape_data = {
                'type': self.shape_type,
                'x': center_x,
                'y': center_y,
                'width': width,
                'height': height,
                # Canaleta: relleno gris suave; resto: sin fondo
                'fill': '#D0D0D0' if self.shape_type == 'canaleta' else '',
                # Usar color y grosor seleccionados en el panel si están disponibles
                'outline': (self.app.current_line_color.get() if hasattr(self.app, 'current_line_color') else 'black'),
                'outline_width': (self.app.current_line_width.get() if hasattr(self.app, 'current_line_width') else 2)
            }

            # Para canaleta, agregar información de orientación
            if self.shape_type == "canaleta":
                is_vertical = getattr(self, '_canaleta_vertical', False)
                shape_data['horizontal'] = not is_vertical
                # Sección comercial por defecto (modificable luego con Ctrl+clic derecho)
                ancho, alto = self._seccion_canaleta_default()
                shape_data['seccion'] = f"{ancho:g}x{alto:g}"

            if hasattr(self.app, 'shape_manager'):
                if hasattr(self.app.shape_manager, 'create_shape_from_data'):
                    created = self.app.shape_manager.create_shape_from_data(shape_data)
                    # Asegurar que la forma final utilice outline color/grosor en el canvas
                    if created and hasattr(created, 'canvas_id') and created.canvas_id and hasattr(self.app, 'canvas'):
                        try:
                            fill_final = '#D0D0D0' if shape_data['type'] == 'canaleta' else ''
                            self.app.canvas.itemconfig(created.canvas_id, outline=shape_data['outline'], width=shape_data['outline_width'], fill=fill_final)
                        except Exception:
                            pass
                    return created

            return None
        except Exception as e:
            return None

    def cancel(self):
        """Cancela el dibujo"""
        if self.preview_id:
            self.app.canvas.delete(self.preview_id)
            self.preview_id = None

        cancelled_type = self.shape_type  # guardar antes de limpiar
        self.is_drawing = False
        self.shape_type = None
        self.start_x = None
        self.start_y = None
        self.app.canvas.config(cursor="")

        # Notificar a la app para desactivar el botón de la barra 2D
        if cancelled_type and hasattr(self.app, 'notify_shape_draw_finished'):
            try:
                self.app.notify_shape_draw_finished(cancelled_type)
            except Exception:
                pass

        if hasattr(self.app, 'set_status'):
            self.app.set_status("🛑 Dibujo cancelado", "orange")

# CONSTANTES DEL CANVAS A3 (deben coincidir con evaPr_OK.py)

class EventHandler:
    """
    Clase centralizada para gestionar todos los eventos del mouse y teclado.

    Esta clase actúa como un intermediario entre los eventos de la interfaz
    y las operaciones principales de la aplicación.
    """

    def __init__(self, app):
        """
        Inicializa el gestor de eventos.

        Args:
            app: Instancia de PlanoElectrico que contiene toda la lógica de la aplicación
        """
        self.app = app

        self.simple_zoom_manager = create_simple_zoom_manager(app)

        self.alignment_manager = create_alignment_manager(app)

        self.shape_drawing = ShapeDrawingState(app)

        # OPTIMIZACIÓN MOTION: Throttling para 60 FPS
        self.last_motion_time = 0
        self.motion_throttle_ms = 16  # ~60 FPS (1000ms / 60 = 16.67ms)
        self.last_mouse_x = 0
        self.last_mouse_y = 0

    def on_mouse_wheel_zoom(self, event):
        """
        Maneja el zoom con la rueda del mouse (Ctrl + Wheel).
        
        Soporta:
        - Windows/MacOS: event.delta
        - Linux: Button-4 (Zoom In) y Button-5 (Zoom Out)
        """
        if hasattr(self, 'simple_zoom_manager'):
            # Detectar dirección
            if event.num == 5 or event.delta < 0:
                self.simple_zoom_manager.zoom_out()
            elif event.num == 4 or event.delta > 0:
                self.simple_zoom_manager.zoom_in()

            # Redibujar apantallamientos y formas geométricas después del zoom para actualizar coordenadas y escala
            if hasattr(self.app, 'shielding_manager'):
                for sh in self.app.shielding_manager.shieldings:
                    sh.draw(self.app.canvas)

            if hasattr(self.app, 'redraw_all_shapes'):
                self.app.redraw_all_shapes()

            # FIX ZOOM: Redibujar Block Terminals (create_image no escala con canvas.scale)
            self._redraw_block_terminals_after_zoom()

            if hasattr(self.app, 'draw_grid'):
                self.app.draw_grid(force=True) # El grid también se refresca

    def _try_start_wire_label_drag(self, event):
        """Detecta si el clic apunta a una etiqueta de numeración de cables y prepara su arrastre."""
        app = self.app
        canvas = app.canvas
        # Solo si la numeración está habilitada
        if not getattr(app, 'wire_numbering_enabled', None) or not app.wire_numbering_enabled.get():
            return False
        try:
            items = canvas.find_withtag("current")
        except Exception:
            return False
        for item in items:
            tags = canvas.gettags(item)
            if "wire_label" in tags:
                # Extraer id de conexión desde la tag conn_<id>
                conn = None
                try:
                    conn_id = int(next(t for t in tags if t.startswith("conn_")).split("_", 1)[1])
                    for c in app.connections:
                        if id(c) == conn_id:
                            conn = c
                            break
                except Exception:
                    conn = None
                if conn is None:
                    continue
                app._dragging_wire_label = True
                app._dragging_wire_label_conn = conn
                app._selected_wire_label_conn = conn
                # Si aún no tiene ancla propia, calcularla a partir del item clicado.
                # El ancla es el punto de la barra "/" sobre el cable; el texto va desplazado de él.
                if not getattr(conn, 'wire_label_pos', None):
                    coords = canvas.coords(item)
                    zoom = getattr(canvas, 'zoom_level', 1.0)
                    if len(coords) >= 4:
                        cx_item = (coords[0] + coords[2]) / 2.0
                        cy_item = (coords[1] + coords[3]) / 2.0
                    elif len(coords) >= 2:
                        cx_item = coords[0]
                        cy_item = coords[1]
                    else:
                        cx_item = 0
                        cy_item = 0
                    cx_world, cy_world = cx_item / zoom, cy_item / zoom

                    # Determinar orientación del segmento más largo y su offset de texto
                    best_seg = None
                    max_len = -1
                    for seg in conn.segments:
                        (x1s, y1s), (x2s, y2s) = seg
                        length = ((x2s - x1s) ** 2 + (y2s - y1s) ** 2) ** 0.5
                        if length > max_len:
                            max_len = length
                            best_seg = seg
                    off_x = 0
                    off_y = 0
                    if best_seg:
                        (sx1s, sy1s), (sx2s, sy2s) = best_seg
                        if abs(sx1s - sx2s) > abs(sy1s - sy2s):  # Horizontal
                            off_y = -12
                        else:  # Vertical
                            off_x = 12
                    # El ancla de la barra es el punto clicado menos el offset del texto
                    conn.wire_label_pos = (cx_world - off_x, cy_world - off_y)
                try:
                    canvas.config(cursor="fleur")
                except Exception:
                    pass
                return True
        return False

    def _drag_wire_label(self, event):
        """Arrastra la etiqueta de numeración a lo largo del cable que numera."""
        app = self.app
        conn = getattr(app, '_dragging_wire_label_conn', None)
        if conn is None:
            return
        try:
            mx, my = event_to_canvas_coords(event, app.canvas)
        except Exception:
            return

        best_seg = None
        max_len = -1
        for seg in conn.segments:
            (x1, y1), (x2, y2) = seg
            length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            if length > max_len:
                max_len = length
                best_seg = seg
        if best_seg is None:
            return

        (sx1, sy1), (sx2, sy2) = best_seg
        horizontal = abs(sx1 - sx2) > abs(sy1 - sy2)

        saved = conn.wire_label_pos or (0, 0)
        margin = 3
        if horizontal:
            # Sólo se mueve a lo largo del eje X, Y se mantiene fijo
            cx = min(max(mx, min(sx1, sx2) + margin), max(sx1, sx2) - margin)
            cy = saved[1]
        else:
            # Sólo se mueve a lo largo del eje Y, X se mantiene fijo
            cy = min(max(my, min(sy1, sy2) + margin), max(sy1, sy2) - margin)
            cx = saved[0]

        conn.wire_label_pos = (cx, cy)
        if hasattr(app, 'update_wire_numbers'):
            app.update_wire_numbers()

    def _find_wire_label_conn_at(self, event):
        """Devuelve la conexión cuya etiqueta de numeración está bajo el cursor, o None."""
        app = self.app
        canvas = app.canvas
        if not getattr(app, 'wire_numbering_enabled', None) or not app.wire_numbering_enabled.get():
            return None
        try:
            items = canvas.find_withtag("current")
        except Exception:
            return None
        for item in items:
            tags = canvas.gettags(item)
            if "wire_label" in tags:
                try:
                    conn_id = int(next(t for t in tags if t.startswith("conn_")).split("_", 1)[1])
                    for c in app.connections:
                        if id(c) == conn_id:
                            return c
                except Exception:
                    pass
        return None

    def _try_edit_wire_label(self, event):
        """Clic derecho sobre una etiqueta de numeración: abre diálogo para editarla."""
        conn = self._find_wire_label_conn_at(event)
        if conn is None:
            return False
        self._edit_wire_label_dialog(conn)
        try:
            self.app.canvas.config(cursor="")
        except Exception:
            pass
        return True

    def _edit_wire_label_dialog(self, conn):
        """Muestra un diálogo para editar el texto de la etiqueta de numeración de un cable."""
        try:
            from tkinter import simpledialog
        except Exception:
            return

        current = conn.wire_label_manual or self.app.wire_numbering_manager.get_label_for_connection(conn) or ""
        new_text = simpledialog.askstring(
            "Editar Numeración",
            "Texto de la etiqueta de numeración (vacío = restaurar automática):",
            initialvalue=current,
            parent=self.app.root
        )
        if new_text is None:
            return  # Cancelado
        new_text = new_text.strip()
        if new_text:
            conn.wire_label_manual = new_text
        else:
            conn.wire_label_manual = None  # Restaurar numeración automática
        if hasattr(self.app, 'is_dirty'):
            self.app.is_dirty = True
        if hasattr(self.app, 'update_wire_numbers'):
            self.app.update_wire_numbers()

    def _delete_selected_wire_label(self):
        """Borra (oculta) la etiqueta de numeración seleccionada con Delete."""
        app = self.app
        conn = getattr(app, '_selected_wire_label_conn', None)
        if conn is None:
            return False
        conn.wire_label_hidden = True
        conn.wire_label_manual = None
        app._selected_wire_label_conn = None
        if hasattr(app, 'is_dirty'):
            app.is_dirty = True
        if hasattr(app, 'update_wire_numbers'):
            app.update_wire_numbers()
        if hasattr(app, 'set_status'):
            try:
                app.set_status("🗑️ Numeración de cable oculta (Ctrl+Z para restaurar)", "orange")
            except Exception:
                pass
        return True

    def on_canvas_click(self, event):
        """
        Maneja los clicks del mouse en el canvas.

        Funcionalidades:
        - Gestión de preview de componentes
        - Selección de puntos de conexión
        - Creación de conexiones entre componentes
        - Selección de componentes para arrastre
        - Selección de segmentos de línea
        - Creación de componentes de texto
        """
        # DETECTAR CLIC SOBRE ETIQUETA DE NUMERACIÓN DE CABLE (arrastre)
        if self._try_start_wire_label_drag(event):
            return "break"
        # Si el clic no fue sobre una etiqueta de numeración, limpiar su selección
        if getattr(self.app, '_selected_wire_label_conn', None) is not None:
            self.app._selected_wire_label_conn = None

        # BLOQUEO HOJA REPORTES: Si la hoja no es editable, bloquear interacciones de edición
        if hasattr(self.app, 'project'):
            sheet = self.app.project.get_active_sheet()

            # INTERACTIVIDAD EN REPORTES: Detectar clicks en elementos con metadatos especiales
            # Incluso en hojas no editables, permitimos la interacción con selectores
            x_click, y_click = event_to_canvas_coords(event, self.app.canvas)

            for t_comp in getattr(self.app, 'text_components', []):
                if hasattr(t_comp, 'contains_point') and t_comp.contains_point(x_click, y_click):
                    meta = getattr(t_comp, 'metadata', {})
                    if meta.get('type') == 'cabinet_dimension_selector':
                        if hasattr(self.app, 'show_cabinet_selection_menu'):
                            self.app.show_cabinet_selection_menu(event)
                            return "break"

            if sheet and (not getattr(sheet, 'editable', True) or sheet.name in AppConstants.NON_EDITABLE_SHEETS):
                # EXCEPCIÓN: Permitir clics si el usuario está actualmente en modo dibujo (ej: insertando Riel DIN)
                if not (hasattr(self, 'shape_drawing') and self.shape_drawing and self.shape_drawing.shape_type):
                    # Ignorar clicks en la hoja no editable para evitar mover elementos accidentalmente
                    return "break"

        # SIMULACIÓN: Si está en modo simulación, bloquear edición pero permitir interacción
        if hasattr(self.app, 'simulation_mode') and self.app.simulation_mode:
            # USAR FUNCIÓN CENTRALIZADA: Calcular coordenadas compensando pan y zoom
            cx, cy = event_to_canvas_coords(event, self.app.canvas)

            component = self.app.find_component_at_position(cx, cy)

            if component:
                # Soporte para pulsadores momentáneos en simulación
                svg_name = (getattr(component, 'svg_file', '') or '').lower()
                is_momentary = False
                # Detectar por flag explícito
                if getattr(component, 'momentary', False):
                    is_momentary = True
                # Detectar switches monopolares NC/NO y botones por nombre
                if 'switch' in svg_name and ('-nc' in svg_name or '-no' in svg_name):
                    is_momentary = True
                if 'boton' in svg_name or 'push' in svg_name:
                    is_momentary = True

                if is_momentary:
                    # Activar mientras el mouse está presionado
                    component.is_active = True
                    # Registrar componente presionado en la app para soltar luego
                    if not hasattr(self.app, 'sim_pressed_components'):
                        self.app.sim_pressed_components = set()
                    self.app.sim_pressed_components.add(component)
                    # Refrescar visual
                    try:
                        component.load_image(component.svg_path)
                        component.draw()
                    except Exception:
                        pass
                elif hasattr(component, 'toggle_state'):
                    component.toggle_state()

            return "break"

        # PRIORIDAD MÁXIMA: DIBUJO DE SHAPES
        # PRIORIDAD MÁXIMA: DIBUJO DE SHAPES
        if self.shape_drawing.shape_type:
            if not self.shape_drawing.is_drawing:
                # Primer click: iniciar dibujo
                self.shape_drawing.start_drawing(event.x, event.y)
                return # CRÍTICO: detener procesamiento
            else:
                # Segundo click: finalizar dibujo
                shape = self.shape_drawing.finish_drawing(event.x, event.y)
                return # CRÍTICO: detener procesamiento

        # PRIORIDAD: DIBUJO DE APANTALLAMIENTO
        if getattr(self.app, 'shielding_mode_enabled', None) and self.app.shielding_mode_enabled.get():
            x_world, y_world = event_to_canvas_coords(event, self.app.canvas)
            self.app.shielding_drag_start = (x_world, y_world)
            return

        # ... RESTO DEL CÓDIGO ORIGINAL SIN CAMBIOS ...

        # MODO TEXTO: Crear componente de texto
        if hasattr(self.app, 'text_mode') and self.app.text_mode and hasattr(self.app, 'current_text_info'):
            # USAR FUNCIÓN CENTRALIZADA: Calcular coordenadas compensando pan
            x, y = event_to_canvas_coords(event, self.app.canvas)
            self.app.place_text_component(x, y)
            return
        # USAR FUNCIÓN CENTRALIZADA: Calcular coordenadas compensando pan
        x_comp, y_comp = event_to_canvas_coords(event, self.app.canvas)
        # BUSCAR APANTALLAMIENTO BAJO EL CLICK (si no hay componente)
        if hasattr(self.app, 'shielding_manager'):
            shielding = self.app.shielding_manager.find_shielding_at(x_comp, y_comp)
            if shielding:
                # Deseleccionar otros elementos antes de seleccionar el nuevo
                self._clear_selection_unless_click_inside_selected(x_comp, y_comp)
                self.app.shielding_manager.select_shielding(shielding)

                # FIX CRÍTICO: Inicializar drag_data para evitar saltos en el primer movimiento
                self.app.drag_data["x"] = event.x
                self.app.drag_data["y"] = event.y

                return

        # DETECTAR COMPONENTE CLICKEADO (COMÚN A TODOS LOS MODOS)
        # USAR FUNCIÓN CENTRALIZADA: Calcular coordenadas compensando pan
        componente_clickeado = None

        for component in self.app.components:
            if component.contains_point(x_comp, y_comp):
                componente_clickeado = component
                break

        # Gestión inteligente del preview de componente
        if self.app.component_preview_mode:

            # USAR FUNCIÓN CENTRALIZADA: Calcular coordenadas compensando pan
            x_world, y_world = event_to_canvas_coords(event, self.app.canvas)

            if componente_clickeado:
                # Click sobre componente existente: insertar empalme si es aplicable
                if (hasattr(self.app, 'preview_category') and
                    self.app.preview_category == "Connection" and
                    self.app.preview_component_data and
                    "empalme" in self.app.preview_component_data.get("name", "").lower()):

                    # Buscar línea intersectada para insertar empalme
                    linea_info = self.app.buscar_linea_intersectada(x_world, y_world)
                    if linea_info:
                        temp_component = self.app.finalizar_preview_componente(x_world, y_world, ejecutar_autoconexion=False)
                        if temp_component:
                            # ABRIR AUTOMÁTICAMENTE LA VENTANA DE EDICIÓN DE ETIQUETA PARA EMPALME
                            try:
                                self.app.edit_component_label(temp_component)
                            except Exception as e:
                                pass
                            self.app.insertar_empalme_en_linea(temp_component, linea_info, x_world, y_world)
                        return

            # Click en área vacía: colocar componente normalmente
            component_placed = self.app.finalizar_preview_componente(x_world, y_world)
            if component_placed:
                pass

                # ABRIR AUTOMÁTICAMENTE LA VENTANA DE EDICIÓN DE ETIQUETA
                try:
                    self.app.edit_component_label(component_placed)
                except Exception as e:
                    pass

                # LÍNEA AUTOMÁTICA MANHATTAN PARA COMPONENTES FASE
                if hasattr(component_placed, 'svg_file') and component_placed.svg_file == "fase.svg":
                    self._crear_linea_fase_manhattan(component_placed)

                # Asegurar que el modo preview se desactive completamente
                self.app.component_preview_mode = False
                self.app.preview_component = None
                self.app.preview_component_data = None
                self.app.preview_category = None

            return

        # Manejo de clicks para formas
        # Si estamos en modo preview de formas y no hay componente en el click
        if (hasattr(self.app, 'shape_preview_mode') and self.app.shape_preview_mode and
            not componente_clickeado):

            # USAR FUNCIÓN CENTRALIZADA: Calcular coordenadas compensando pan
            x_world, y_world = event_to_canvas_coords(event, self.app.canvas)

            shape = self.app.handle_shape_click(x_world, y_world)
            return

        # Seleccionar shapes existentes
        # Solo si NO estamos en modo preview de formas
        if not (hasattr(self.app, 'shape_preview_mode') and self.app.shape_preview_mode):
            # USAR FUNCIÓN CENTRALIZADA: Calcular coordenadas compensando pan
            x_world, y_world = event_to_canvas_coords(event, self.app.canvas)

            # Buscar shape clickeado
            clicked_shape = self.app.find_shape_at_position(x_world, y_world)
                # GABINETE 2D: si el shape es Puerta/Tablero (cabinet image),
                # NO interceptar el click — dejar que llegue a start_selection_box
            if clicked_shape:
                # PRIORIDAD: Block Terminal sobre cualquier shape
                # Si hay un BT en esta posición, seleccionarlo directamente
                bt_priority = self._find_bt_at(x_world, y_world)
                if bt_priority:
                    self._on_bt_click(event, bt_priority)
                    return

                _shape_meta_type = str(getattr(clicked_shape, 'metadata', {}).get('type', ''))
                _is_cabinet_image = (
                    self._is_cabinet_sheet() and
                    getattr(clicked_shape, 'shape_type', None) == 'image' and
                    'cabinet' in _shape_meta_type
                )
                _is_cabinet_background = (_shape_meta_type == 'cabinet_background')
                # Si es fondo de gabinete (tablero/tapa): verificar BT. Si no hay BT
                # ni Ctrl presionado, iniciar selección por área sobre el fondo sin
                if _is_cabinet_background or _is_cabinet_image:
                    bt_on_cabinet = self._find_bt_at(x_world, y_world)
                    if bt_on_cabinet:
                        self._on_bt_click(event, bt_on_cabinet)
                        return
                    return  # La estructura del gabinete es completamente inerte.
                if not _is_cabinet_image and not _is_cabinet_background:
                    # GABINETE/TAPA 2D: los dispositivos de estas hojas son shapes
                    # (metadata 'component' / 'door_component' / 'relay_socket'), no
                    # componentes eléctricos. Por eso la selección múltiple por Ctrl
                    # debe resolverse aquí: ShapeManager.select_shape() solo admite
                    # una forma a la vez y abortaba el flujo antes de llegar al
                    # manejador de selected_elements.
                    ctrl_pressed = hasattr(event, 'state') and (event.state & 0x4)
                    if ctrl_pressed:
                        self._toggle_shape_in_multi_selection(clicked_shape)
                        try:
                            self.app.drag_data["x"] = event.x
                            self.app.drag_data["y"] = event.y
                        except Exception:
                            pass
                        return

                    self._clear_selection_unless_click_inside_selected(x_world, y_world)

                    self.app.select_shape(clicked_shape)
                    # Inicializar datos de arrastre para evitar desfase en el primer movimiento
                    try:
                        self.app.drag_data["x"] = event.x
                        self.app.drag_data["y"] = event.y
                    except Exception:
                        pass
                    return

        # FUNCIONALIDAD ORIGINAL: Gestión de conexiones y selección
        # Convertir coordenadas de pantalla a mundo para comparar con puntos
        x, y = event_to_canvas_coords(event, self.app.canvas)
        x_comp = x
        y_comp = y

        # BUSCAR PUNTOS DE CONEXIÓN PRIMERO EN TODOS LOS COMPONENTES
        # Esto permite detectar clics en halos verdes incluso si están fuera del área del componente
        best_component = None
        best_point_idx = None
        best_orphan = False
        min_distance = float('inf')
        snap_radius = 8  # Radio del halo verde - ÁREA DE DETECCIÓN AMPLIADA

        # Buscar el punto de conexión más cercano en TODOS los componentes
        for component in self.app.components:
            global_points = component.get_connection_points_global()
            for i, (point_x, point_y, point_info) in enumerate(global_points):
                # Ahora x,y y point_x,point_y están ambos en coordenadas del mundo
                distance = ((x - point_x) ** 2 + (y - point_y) ** 2) ** 0.5

                # Preferir puntos huérfanos (borrables con <delete>) a la misma distancia.
                # Los empalmes tienen 2 puntos superpuestos: si el índice 0 está conectado,
                # el usuario debe poder seleccionar el índice 1 (huérfano) al hacer clic.
                is_orph = False
                if hasattr(self.app, '_point_is_orphaned'):
                    try:
                        is_orph = self.app._point_is_orphaned(component, i)
                    except Exception:
                        is_orph = False

                if distance < min_distance and distance <= snap_radius:
                    min_distance = distance
                    best_point_idx = i
                    best_component = component
                    best_orphan = is_orph
                elif distance == min_distance and is_orph and not best_orphan:
                    # Empate de distancia: priorizar el punto que puede borrarse
                    min_distance = distance
                    best_point_idx = i
                    best_component = component
                    best_orphan = True

        # SI SE ENCONTRÓ UN PUNTO DE CONEXIÓN CERCANO, PROCESARLO
        if best_component is not None and best_point_idx is not None:
            # Ctrl+Click para modo manual routing
            ctrl_pressed = hasattr(event, 'state') and (event.state & 0x4)

            # PRIORIDAD 1: Si manual routing está activo, CUALQUIER click termina la conexión
            try:
                from core.unified_line_system import get_manhattan_router
                manual_router = get_manhattan_router(self.app)

                if manual_router.manual_active:
                    # Manual routing activo: terminar conexión (con o sin Ctrl)

                    success = manual_router.finish_manual_connection(best_component, best_point_idx)

                    if not success:
                        manual_router.cancel()

                    return  # Terminar procesamiento aquí

            except Exception as e:
                # En caso de error, cancelar y continuar con lógica normal
                try:
                    manual_router.cancel()
                except:
                    pass

            # PRIORIDAD 2: Si manual routing NO está activo, Ctrl+Click o botón 8 activo lo activan
            button8_active = hasattr(self.app, 'button_active_states') and self.app.button_active_states.get("button8", False)
            if ctrl_pressed or button8_active:
                try:
                    from core.unified_line_system import get_manhattan_router
                    manual_router = get_manhattan_router(self.app)

                    if manual_router.activate_manual_routing(best_component, best_point_idx):
                        return  # Terminar procesamiento aquí
                    else:
                        pass  # Continuar con modo normal si hay error
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    pass  # Continuar con modo normal si hay error

            # PRIORIDAD 2: Si no está activo, Ctrl+Click activa manual routing (solo si no hay conexión en progreso)

            # EVITAR CONFLICTOS: No activar modo conexión normal si el botón 8 está activo
            button8_active = hasattr(self.app, 'button_active_states') and self.app.button_active_states.get("button8", False)
            if button8_active:
                return  # No hacer nada más si el botón 8 está activo

            # Continuar con modo conexión normal
            if not hasattr(self.app, 'connection_mode'):
                self.app.connection_mode = False
            if not hasattr(self.app, 'connection_start'):
                self.app.connection_start = None

            if hasattr(self.app, 'select_connection_point'):
                self.app.select_connection_point(best_component, best_point_idx)

            if not self.app.connection_start:
                # Primer click: establecer punto de inicio y activar modo conexión
                self.app.connection_mode = True
                self.app.connection_start = (best_component, best_point_idx)
                if hasattr(self.app, 'set_status'):
                    self.app.set_status("🔗 Punto de inicio seleccionado - Haga clic en punto final", "blue", duration=5000)

                # SNAP VISUAL: Resaltar el punto seleccionado
                if hasattr(self.app, 'highlight_connection_point'):
                    self.app.highlight_connection_point(best_component, best_point_idx)

            else:
                # Segundo click: crear conexión
                if hasattr(self.app, 'clear_connection_point_highlights'):
                    self.app.clear_connection_point_highlights()
                result = self.app.finish_connection(best_component, best_point_idx)
                # Si la conexión se creó, el punto ya no es huérfano: limpiar selección
                if result is not None and hasattr(self.app, 'clear_selected_connection_point'):
                    self.app.clear_selected_connection_point()
            return

        # SI NO SE ENCONTRÓ PUNTO DE CONEXIÓN, BUSCAR COMPONENTE BAJO EL CLICK
        clicked_component = self.app.find_component_at_position(x_comp, y_comp)

        # VERIFICAR BLOCK TERMINAL POR BOUNDING BOX MATEMÁTICO
        # Igual que contains_point() en componentes normales: no depende de píxeles ni transparencias
        if not clicked_component:
            bt_hit = self._find_bt_at(x_comp, y_comp)
            if bt_hit:
                self._on_bt_click(event, bt_hit)
                return

        if clicked_component:
            # SELECCIÓN DE COMPONENTES
            # Verificar si Ctrl está presionado para selección múltiple
            ctrl_pressed = hasattr(event, 'state') and (event.state & 0x4)

            if ctrl_pressed and hasattr(self.app, 'selected_elements'):
                # SELECCIÓN MÚLTIPLE CON CTRL
                if clicked_component in self.app.selected_elements:
                    self.app.selected_elements.remove(clicked_component)
                    clicked_component.selected = False
                else:
                    self.app.selected_elements.append(clicked_component)
                    clicked_component.selected = True
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status(f"📥 Elemento añadido a la selección ({len(self.app.selected_elements)} totales)", "blue")

                if hasattr(self.app, 'update_selection_indicators'):
                    self.app.update_selection_indicators()

                # drag_data debe usar coordenadas de pantalla, no del mundo
                self.app.drag_data["x"] = event.x
                self.app.drag_data["y"] = event.y
            else:
                if (hasattr(self.app, 'selected_elements') and
                    clicked_component in self.app.selected_elements):
                    # Click sobre un elemento que ya forma parte de la selección múltiple.
                    # Forzar modo de arrastre de grupo: asegurarnos de que
                    # `selected_component` esté vacío para que el código de drag
                    # mueva todo el `selected_elements` en lugar de un único componente.
                    self.app.selected_component = None
                    # Re-marcar como seleccionados (por si acaso alguno perdió el flag)
                    for el in self.app.selected_elements:
                        try:
                            if hasattr(el, 'selected'):
                                el.selected = True
                        except Exception:
                            pass
                    # Lock current group as drag targets to avoid selection mutation during drag
                    try:
                        self.app._group_drag_targets = list(self.app.selected_elements)
                    except Exception:
                        self.app._group_drag_targets = None
                    # No limpiar la selección ni seleccionar individualmente
                    # — permitir que on_canvas_drag procese el movimiento en grupo.
                    pass
                else:
                    # Usar helper centralizado para limpiar selecciones previas
                    self._clear_selection()

                    self.app.selected_component = clicked_component
                    clicked_component.selected = True

                    # Asegurar que se actualizan los indicadores visuales de selección
                    if hasattr(self.app, 'update_selection_indicators'):
                        self.app.update_selection_indicators()

                    if hasattr(self.app, 'set_status'):
                        # Intentar obtener el nombre del componente o tipo
                        comp_name = getattr(clicked_component, 'symbol_type', 'Componente')
                        self.app.set_status(f"🖱️ Seleccionado: {comp_name}", "blue")

                    if hasattr(self.app, 'force_canvas_refresh'):
                        self.app.force_canvas_refresh()

                # Asegurar que shielding_manager sepa que seleccionamos un componente
                if hasattr(self.app, 'shielding_manager'):
                    self.app.shielding_manager.selected_shielding = None

            # drag_data debe usar coordenadas de pantalla, no del mundo
            self.app.drag_data["x"] = event.x
            self.app.drag_data["y"] = event.y

        else:
            # PRIMERA PRIORIDAD: VERIFICAR SELECCIÓN DE LÍNEAS

            # Click normal en espacio vacío para añadir puntos de ángulo
            # EXCEPCIÓN: No interceptar si estamos colocando un componente (SHAPE/FASE)
            # PRIORIDAD CRÍTICA: Verificar esto ANTES de seleccionar líneas para permitir puntos cerca de líneas
            ctrl_pressed = hasattr(event, 'state') and (event.state & 0x4)
            if not ctrl_pressed and (not hasattr(self.app, 'component_preview_mode') or not self.app.component_preview_mode):
                try:
                    from core.unified_line_system import get_manhattan_router
                    manual_router = get_manhattan_router(self.app)

                    if manual_router.manual_active:
                        # Intentar finalizar sobre línea existente primero
                        if manual_router.finish_manual_on_line(x, y):
                            return  # Conexión finalizada sobre línea
                        # Si no hay línea, agregar punto de ángulo
                        manual_router.add_angle_point(event.x, event.y)
                        return  # No procesar más - PRIORIDAD SOBRE SELECCIÓN DE LÍNEA
                except Exception as e:
                    pass

            # Buscar si el click está cerca de una línea ANTES de procesar click en vacío
            line_selected = False
            for connection in self.app.connections:
                for i, segment in enumerate(connection.segments):
                    (x1, y1), (x2, y2) = segment
                    # MODIFICADO: Compensar pan offset para segmentos de conexión
                    canvas_x1 = x1
                    canvas_y1 = y1
                    canvas_x2 = x2
                    canvas_y2 = y2

                    if is_near_segment(x, y, canvas_x1, canvas_y1, canvas_x2, canvas_y2, 15):
                        if (hasattr(self.app, 'selected_elements') and
                            connection in self.app.selected_elements):
                            pass
                        else:
                            if self.app.selected_component:
                                self.app.selected_component.selected = False
                                self.app.selected_component = None

                            if hasattr(self.app, 'selected_elements'):
                                for elem in self.app.selected_elements:
                                    if hasattr(elem, 'selected'):
                                        elem.selected = False
                                self.app.selected_elements.clear()

                        # Limpiar selección de línea anterior
                        if hasattr(self.app, 'clear_connection_highlights'):
                            self.app.clear_connection_highlights()

                        # Limpiar punto de conexión seleccionado al elegir una línea
                        if hasattr(self.app, 'clear_selected_connection_point'):
                            self.app.clear_selected_connection_point()

                        self.app.selected_connection = connection
                        self.app.selected_segment = (connection, i)
                        # Bloquear arrastre inmediato al seleccionar con clic
                        self.app.locked_segment = True

                        if hasattr(self.app, 'set_status'):
                            self.app.set_status("🔗 Conexión seleccionada", "blue")

                        if self.app.config.get("enable_move_connections", True):
                            self.app.canvas.config(cursor="fleur")

                        # drag_data debe usar coordenadas de pantalla
                        self.app.drag_data["x"] = event.x
                        self.app.drag_data["y"] = event.y

                        # Resaltar visualmente la línea seleccionada
                        self.app.highlight_selected_connection(connection, i)

                        line_selected = True
                        break

                if line_selected:
                    break

            # Solo procesar "click en vacío" si NO se seleccionó una línea
            if not line_selected:
                # Ctrl+Click en espacio vacío para cancelar manual routing
                ctrl_pressed = hasattr(event, 'state') and (event.state & 0x4)
                if ctrl_pressed:
                    try:
                        from core.unified_line_system import get_manhattan_router
                        manual_router = get_manhattan_router(self.app)

                        if manual_router.manual_active:
                            manual_router.cancel()
                            return  # No procesar más
                    except Exception as e:
                        pass
                # CLICK EN ESPACIO VACÍO
                # Verificar si Ctrl está presionado
                ctrl_pressed = hasattr(event, 'state') and (event.state & 0x4)

                if not ctrl_pressed:
                    # Click en espacio vacío sin Ctrl: ejecutar Escape completo
                    self.on_escape_key()
                    # También iniciar selección por área para permitir drag
                    if not self.app.component_preview_mode:
                        if hasattr(self.app, 'start_selection_box'):
                            self.app.start_selection_box(event.x, event.y)
                    return

                # Cancelar modo conexión si está activo
                if hasattr(self.app, 'connection_mode') and self.app.connection_mode:
                    self.app.connection_mode = False
                    self.app.connection_start = None
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status("Modo conexión cancelado", "red")

                # Iniciar selección por área
                # Solo si no estamos en modo preview y no hay Ctrl presionado
                if not self.app.component_preview_mode and not ctrl_pressed:
                    # Iniciar selección por área con coordenadas de PANTALLA
                    if hasattr(self.app, 'start_selection_box'):
                        self.app.start_selection_box(event.x, event.y)
                        if hasattr(self.app, 'set_status'):
                            self.app.set_status("🔍 Seleccionando área...", duration=2000)

    def on_right_click(self, event):
        """
        Maneja el click derecho del mouse para insertar puntos, selección de segmentos o menú contextual.

        Insertar punto en línea con Ctrl+I activo
        Selección de segmentos con clic derecho
        """
        # CLIC DERECHO SOBRE ETIQUETA DE NUMERACIÓN: editar su texto
        if self._try_edit_wire_label(event):
            return "break"

        # Ignorar click derecho si Alt está presionado (para arrastre restringido)
        import sys
        alt_pressed = bool(event.state & 0x20000) if sys.platform.startswith('win') else bool(event.state & 0x8)
        if alt_pressed:
            x_comp, y_comp = event_to_canvas_coords(event, self.app.canvas)
            clicked_component = self.app.find_component_at_position(x_comp, y_comp)
            if clicked_component and clicked_component != self.app.selected_component:
                if self.app.selected_component:
                    self.app.selected_component.selected = False
                self.app.selected_component = clicked_component
                clicked_component.selected = True
                if hasattr(self.app, 'update_selection_indicators'):
                    self.app.update_selection_indicators()

            self.app.drag_data["x"] = event.x
            self.app.drag_data["y"] = event.y
            return  # No procesar para evitar conflicto con Alt + click derecho

        # Ctrl + clic derecho sobre una CANALETA en la Hoja 2D: elegir ancho comercial
        ctrl_pressed = bool(event.state & 0x4)
        if ctrl_pressed and self._abrir_menu_seccion_canaleta(event):
            return "break"

        if hasattr(self.app, 'project'):
            sheet = self.app.project.get_active_sheet()
            if sheet and (not getattr(sheet, 'editable', True) or sheet.name in AppConstants.NON_EDITABLE_SHEETS):
                return "break"

        # MODO SIMULACIÓN: Bloquear menú contextual y edición
        if hasattr(self.app, 'simulation_mode') and self.app.simulation_mode:
            # VDF Slider Check: Permitir slider si es VDF con control analógico
            # Usar coordenadas de canvas para encontrar componente
            self.app.canvas.focus_set()
            self.app.canvas.update_idletasks()
            x_click, y_click = event_to_canvas_coords(event, self.app.canvas)
            comp = self.app.find_component_at_position(x_click, y_click)

            if comp:
                fname = (getattr(comp, 'svg_file', '') or '').lower()
                # Verificar si es VDF-C y tiene control analógico habilitado
                if "vdf-c" in fname and getattr(comp, 'label_data', {}).get('vdf_analog_enabled', False):
                    self.app.show_vdf_analog_slider(comp, event.x_root, event.y_root)

            return

        # Click derecho durante preview ejecuta Ctrl+X (invertir detección)
        if hasattr(self.app, 'component_preview_mode') and self.app.component_preview_mode:
            if hasattr(self.app, '_simulate_ctrl_x'):
                self.app._simulate_ctrl_x()
                return # Detener aquí para no abrir menús ni insertar puntos

        # MODIFICADO: Convertir coordenadas compensando pan offset y zoom
        self.app.canvas.focus_set()
        self.app.canvas.update_idletasks()
        x_comp, y_comp = event_to_canvas_coords(event, self.app.canvas)
        x, y = event.x, event.y

        # PRIORIDAD #1: Insertar punto en línea si está activo el modo
        if self.app.is_insert_point_mode:
            if self.handle_insert_point_on_line(event):
                return  # Si se insertó punto, terminar aquí

        # Buscar APANTALLAMIENTO bajo el click derecho
        if hasattr(self.app, 'shielding_manager'):
            shielding = self.app.shielding_manager.find_shielding_at(x_comp, y_comp)
            if shielding:
                # 1. Limpiar otras selecciones
                self._clear_selection()
                # 2. Seleccionar el apantallamiento
                self.app.shielding_manager.select_shielding(shielding)
                # 3. Abrir editor específico
                if hasattr(self.app, '_edit_shielding_label'):
                    self.app._edit_shielding_label(shielding)
                return

        # PRIORIDAD #2: Buscar SEGMENTO bajo el click derecho
        segment_selected = False
        # connection.segments guarda coordenadas del MUNDO y se dibujan escaladas
        # por zoom, así que el cursor hay que compararlo en el mismo espacio: usar
        # event.x/event.y (pantalla) hacia que el acierto dependiera del pan. Con la
        # vista desplazada un click sobre un componente con conexiones se detectaba
        # como segmento, la rama del componente no se ejecutaba y el diálogo de
        # etiqueta no se abria nunca.
        _zoom = getattr(self.app.canvas, 'zoom_level', 1.0) or 1.0
        tolerancia_segmento = 15 / _zoom
        for connection in self.app.connections:
            for i, segment in enumerate(connection.segments):
                (x1, y1), (x2, y2) = segment

                if is_near_segment(x_comp, y_comp, x1, y1, x2, y2, tolerancia_segmento):
                    pass

                    # Limpiar selecciones anteriores
                    if self.app.selected_component:
                        self.app.selected_component.selected = False
                        self.app.selected_component = None

                    if hasattr(self.app, 'selected_elements'):
                        for elem in self.app.selected_elements:
                            if hasattr(elem, 'selected'):
                                elem.selected = False
                        self.app.selected_elements.clear()

                    if hasattr(self.app, 'clear_connection_highlights'):
                        self.app.clear_connection_highlights()

                    self.app.selected_connection = connection
                    self.app.selected_segment = (connection, i)

                    self.app.canvas.config(cursor="sizing")

                    # RESALTAR SEGMENTO EN ROJO
                    if i < len(connection.line_ids):
                        try:
                            line_id = connection.line_ids[i]
                            self.app.canvas.itemconfig(line_id, fill="red", width=3)
                        except Exception as e:
                            pass

                    # drag_data debe usar coordenadas de pantalla
                    self.app.drag_data["x"] = event.x
                    self.app.drag_data["y"] = event.y

                    if self._is_fase_connection(connection):
                        self.app.fase_cloning_initial_y = event.y
                        self.app.fase_cloning_initial_x = event.x
                        self.app.fase_cloning_axis = self._get_fase_cloning_axis(connection)
                        self.app.fase_cloning_orig_pos = {
                            'start': (connection.start_component.x, connection.start_component.y),
                            'end': (connection.end_component.x, connection.end_component.y)
                        }

                    segment_selected = True
                    break

            if segment_selected:
                break

        # Si NO se seleccionó segmento, buscar SHAPE para redimensionamiento
        if not segment_selected:
            # Redimensionar shapes con click derecho
            selected_shape = self.app.get_selected_shape()
            if selected_shape:
                # Delegar al ShapeEditor
                if hasattr(self.app.shape_manager, 'editor') and self.app.shape_manager.editor:
                    self.app.shape_manager.editor.selected_shape = selected_shape
                    self.app.shape_manager.editor.on_right_press(event)
                    return  # Terminar aquí si se está redimensionando una shape

            # Si NO hay shape seleccionada, buscar COMPONENTE
            clicked_component = self.app.find_component_at_position(x_comp, y_comp)

            if clicked_component:
                if self.app.selected_component:
                    self.app.selected_component.selected = False

                self.app.selected_component = clicked_component
                clicked_component.selected = True

                # Abrir editor de etiquetas directamente
                self.app.edit_component_label(clicked_component)
            else:
                if hasattr(self.app, 'show_canvas_context_menu'):
                    self.app.show_canvas_context_menu(event)

    # ANCHO COMERCIAL DE CANALETA RANURADA (Ctrl + clic derecho en Hoja 2D)

    def _es_hoja_cabinet_2d(self) -> bool:
        """True si la hoja activa es la 'Hoja de Gabinete 2D'."""
        try:
            sheet = self.app.project.get_active_sheet()
            return bool(sheet) and sheet.name == "Hoja de Gabinete 2D"
        except Exception:
            return False

    def _canaleta_en_posicion(self, x_comp: float, y_comp: float):
        """Devuelve la Canaleta bajo el punto dado (coordenadas de mundo), o None."""
        from models.shape import Canaleta

        # La lista de la hoja activa tiene prioridad (z-order: lo último dibujado va encima)
        for shape in reversed(self.app.shape_manager.shapes):
            if isinstance(shape, Canaleta) and shape.contains_point(x_comp, y_comp):
                return shape

        # Respaldo: buscar en las canaletas preservadas de la hoja
        sheet = self.app.project.get_active_sheet()
        for shape in reversed(getattr(sheet, 'live_shape_objects', []) or []):
            if isinstance(shape, Canaleta) and shape.contains_point(x_comp, y_comp):
                return shape
        return None

    def _abrir_menu_seccion_canaleta(self, event) -> bool:
        """Abre el menú de anchos comerciales si hay una canaleta bajo el cursor en la Hoja 2D."""
        if not self._es_hoja_cabinet_2d():
            return False

        x_comp, y_comp = event_to_canvas_coords(event, self.app.canvas)
        canaleta = self._canaleta_en_posicion(x_comp, y_comp)
        if canaleta is None:
            return False

        # Seleccionar la canaleta para que el cambio se vea resaltado
        editor = getattr(self.app.shape_manager, 'editor', None)
        if editor:
            editor.selected_shape = canaleta
        if self.app.shape_manager:
            self.app.shape_manager.selected_shape = canaleta
        canaleta.selected = True

        self.show_canaleta_section_menu(event, canaleta)
        return True

    def show_canaleta_section_menu(self, event, canaleta):
        """Menú contextual con el catálogo de anchos comerciales de canaleta ranurada."""
        import tkinter as tk
        from models.shape import get_secciones_canaleta, formatear_seccion_canaleta, parse_seccion_canaleta

        secciones = get_secciones_canaleta()
        if not secciones:
            return

        actual = formatear_seccion_canaleta(canaleta.ancho_fijo, canaleta.alto_fijo)

        menu = tk.Menu(self.app.root, tearoff=0)
        menu.add_command(label="📏 Ancho comercial de canaleta", state="disabled")
        menu.add_separator()

        for s in secciones:
            dims = parse_seccion_canaleta(s)
            if not dims:
                continue
            etiqueta = f"{int(round(dims[0]))} x {int(round(dims[1]))} mm"
            if formatear_seccion_canaleta(*dims) == actual:
                etiqueta = f"●  {etiqueta}"
            menu.add_command(
                label=etiqueta,
                command=lambda d=dims: self._aplicar_seccion_canaleta(canaleta, d)
            )

        menu.add_separator()
        menu.add_command(
            label=f"Largo actual: {canaleta.largo:.0f} mm",
            state="disabled"
        )
        try:
            menu.post(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _aplicar_seccion_canaleta(self, canaleta, dims):
        """Cambia la sección comercial de la canaleta y refresca 2D + informes."""
        if not canaleta.set_seccion(dims):
            return

        # Reflejar el nuevo ancho en el 2D
        editor = getattr(self.app.shape_manager, 'editor', None)
        if editor:
            try:
                editor._redraw_shape(canaleta)
            except Exception:
                canaleta.draw(self.app.canvas)
        else:
            canaleta.draw(self.app.canvas)

        if hasattr(self.app, 'set_status'):
            self.app.set_status(
                f"📏 Canaleta {canaleta.seccion} mm "
                f"(ancho {canaleta.ancho_fijo:.0f} x alto {canaleta.alto_fijo:.0f})",
                "blue"
            )

        # Reflejar el nuevo ancho en la BOM y en el resumen de gabinete
        try:
            sheet = self.app.project.get_active_sheet()
            if sheet is not None and hasattr(sheet, 'live_shape_objects'):
                sheet.live_shape_objects = self.app.shape_manager.shapes[:]
        except Exception:
            pass

        # Regenerar los reportes que ya existen y luego volver a la Hoja 2D
        nombres = {s.name for s in self.app.project.sheets}
        index_actual = self.app.project.active_sheet_index
        if "Lista de Materiales" in nombres and hasattr(self.app, 'insert_bom_sheet'):
            try:
                self.app.insert_bom_sheet()
            except Exception:
                pass
        if "Resumen de Gabinete" in nombres and hasattr(self.app, 'insert_cabinet_summary_sheet'):
            try:
                self.app.insert_cabinet_summary_sheet()
            except Exception:
                pass
        try:
            if self.app.project.active_sheet_index != index_actual:
                self.app.switch_to_sheet(index_actual)
        except Exception:
            pass

        try:
            self.app.save_undo_checkpoint()
        except Exception:
            pass

    def handle_insert_point_on_line(self, event):
        """Inserta un punto de conexión en la línea más cercana al cursor"""
        # Convertir coordenadas de pantalla a mundo correctamente
        x_world, y_world = event_to_canvas_coords(event, self.app.canvas)

        # Buscar la línea más cercana
        closest_connection = None
        closest_segment_idx = None
        closest_point = None
        min_distance = float('inf')

        for connection in self.app.connections:
            for i, segment in enumerate(connection.segments):
                (x1, y1), (x2, y2) = segment
                # Los segmentos ya están en coordenadas de mundo

                # Calcular distancia y punto más cercano usando la función existente
                from utils.utility_functions import project_point_on_segment
                dist, point_on_line = project_point_on_segment(x_world, y_world, x1, y1, x2, y2)

                if dist <= 25:
                    # Si es más cercano que el anterior, actualizar
                    if dist < min_distance:
                        min_distance = dist
                        closest_connection = connection
                        closest_segment_idx = i
                        closest_point = point_on_line

        if closest_connection and closest_point:
            # Insertar punto de empalme CON ÍNDICE DE SEGMENTO
            self.app.insert_junction_point(closest_connection, closest_point, closest_segment_idx)

            return True
        else:

            return False

    def _set_canvas_cursor(self, cursor):
        """Establece el cursor del canvas solo si realmente cambió
        (evita comandos de configuración redundantes en cada frame)."""
        try:
            if self.app.canvas.cget('cursor') != cursor:
                self.app.canvas.config(cursor=cursor)
        except Exception:
            pass

    def on_canvas_drag(self, event):
        """Maneja el arrastre de elementos en el canvas"""
        # ARRASTRE DE ETIQUETA DE NUMERACIÓN DE CABLE (con restricción sobre la línea)
        if getattr(self.app, '_dragging_wire_label', False):
            self._drag_wire_label(event)
            return

        # PRIORIDAD: PREVIEW DE APANTALLAMIENTO
        if getattr(self.app, 'shielding_mode_enabled', None) and self.app.shielding_mode_enabled.get():
            if hasattr(self.app, 'shielding_drag_start') and self.app.shielding_drag_start:
                x1, y1 = self.app.shielding_drag_start
                x2, y2 = event_to_canvas_coords(event, self.app.canvas)
                # Solo actualizar si el movimiento es horizontal significativo
                if abs(x2 - x1) > 2:
                    self.app.shielding_manager.update_preview(x1, y1, x2, y1)
                return
        if hasattr(self.app, 'project'):
            sheet = self.app.project.get_active_sheet()
            if sheet and (not getattr(sheet, 'editable', True) or sheet.name in AppConstants.NON_EDITABLE_SHEETS):
                return "break"

        """
        Maneja el arrastre de componentes en el canvas y selección por área.
        """
        # Capturar estado antes de iniciar el arrastre si no se ha capturado aún
        if not getattr(self.app, '_undo_move_checkpoint_saved', False):
            self.app.save_undo_checkpoint()
            self.app._undo_move_checkpoint_saved = True

        # MODO SIMULACIÓN: Bloquear arrastre
        if hasattr(self.app, 'simulation_mode') and self.app.simulation_mode:
            return

        # DEBUG SIMPLE: Componente movido exitosamente
        try:
            zoom_level = self.app.canvas.zoom_level
            pan_offset_x, pan_offset_y = get_pan_offset(self.app.canvas)
            x_comp, y_comp = event_to_canvas_coords(event, self.app.canvas)

        except Exception as e:
            pass

        # Mantener fija la posición del mouse y crosshair con Alt
        # (Sincronizado con la restricción de movimiento de componentes/selecciones)
        import sys
        alt_pressed = bool(event.state & 0x20000) if sys.platform.startswith('win') else bool(event.state & 0x0008)
        l_btn = event.state & 0x0100
        r_btn = event.state & 0x0400

        # Determinar si estamos desplazando elementos (condiciones de línea 1139)
        has_shielding = hasattr(self.app, 'shielding_manager') and self.app.shielding_manager.selected_shielding
        is_moving_elements = (self.app.selected_component or
                             (hasattr(self.app, 'selected_elements') and len(self.app.selected_elements) > 0) or
                             has_shielding or self.app.get_selected_shape())

        if alt_pressed and is_moving_elements:
            if r_btn:  # Alt + Click Derecho: Movimiento Horizontal (Fijar Vertical)
                # Mantener el eje Y fijo según el punto inicial del arrastre
                y_fixed = self.app.drag_data.get("y", event.y)
                if abs(event.y - y_fixed) > 0:
                    try:
                        self.app.canvas.event_generate('<Motion>', warp=True, x=event.x, y=y_fixed)
                    except: pass
                event.y = y_fixed
            elif l_btn: # Alt + Click Izquierdo: Movimiento Vertical (Fijar Horizontal)
                # Mantener el eje X fijo según el punto inicial del arrastre
                x_fixed = self.app.drag_data.get("x", event.x)
                if abs(event.x - x_fixed) > 0:
                    try:
                        self.app.canvas.event_generate('<Motion>', warp=True, x=x_fixed, y=event.y)
                    except: pass
                event.x = x_fixed

        if hasattr(self.app, '_draw_crosshair'):
            self.app._draw_crosshair(event)

        # BT DRAG: Si hay Block Terminal seleccionado, manejar su arrastre y salir
        if getattr(self.app, '_selected_block_terminal', None):
            self._on_bt_drag(event, self.app._selected_block_terminal)
            return

        if self.app.component_preview_mode:
            # Durante el preview, el movimiento se maneja en on_mouse_motion
            return

        # Actualizar selección por área
        if hasattr(self.app, 'selection_box_active') and self.app.selection_box_active:
            if hasattr(self.app, 'update_selection_box'):
                self.app.update_selection_box(event.x, event.y)
                if hasattr(self.app, 'set_status'):
                    self.app.set_status("🔍 Seleccionando área...", duration=1000)
            return

        # Redimensionar shapes con click derecho
        if (hasattr(self.app.shape_manager, 'editor') and self.app.shape_manager.editor and
            self.app.shape_manager.editor.editing):
            self.app.shape_manager.editor.on_right_drag(event)
            return  # No procesar otros tipos de arrastre

        # FUNCIONALIDAD MEJORADA: Arrastre CONECTADO de líneas seleccionadas
        if (hasattr(self.app, 'selected_connection') and self.app.selected_connection and
            hasattr(self.app, 'selected_segment') and self.app.selected_segment):

            # Si locked_segment está activo, la línea fue recién seleccionada con este
            # mismo clic — liberar en el primer movimiento real e intencional del usuario.
            if getattr(self.app, 'locked_segment', False):
                self.app.locked_segment = False
                # NO hacer return — continuar para permitir clonación y arrastre normal

            connection, segment_idx = self.app.selected_segment
            print(f"[DEBUG DRAG] Selected segment: connection {connection}, idx {segment_idx}")

            # AUTOMÁTICO: Detectar líneas de fase y manejar clonado
            # La clonación de fase siempre se procesa ANTES del bloqueo de movimiento,
            # para que funcione aunque "Habilitar mover líneas de conexión" esté desactivado.
            if self._is_fase_connection(connection):
                # Delegar toda la lógica de clonado a la función especializada
                # Esta función maneja activación automática y procesamiento
                if self._handle_fase_cloning_drag(event, connection):
                    return  # Si está en modo clonado o se activó, no procesar arrastre normal

            # Bloquear movimiento de líneas si está deshabilitado en configuración
            # (se evalúa DESPUÉS de la clonación de fases para no interferir con ella)
            if not self.app.config.get("enable_move_connections", True):
                return

            # REDIRECCIÓN: Si hay grupo, pasar al código de componentes que ya funciona
            if hasattr(self.app, 'selected_elements') and len(self.app.selected_elements) > 0:
                # NO manejar aquí - dejar que el código de componentes lo maneje
                pass
            else:
                # Solo manejar líneas individuales con el código original
                # MANTENER CURSOR SIZING DURANTE EL ARRASTRE
                self._set_canvas_cursor("sizing")

                # CORRECCIÓN DESFASE: Calcular dx/dy en coordenadas de pantalla
                dx_screen = event.x - self.app.drag_data["x"]
                dy_screen = event.y - self.app.drag_data["y"]

                # CRÍTICO: Actualizar drag_data INMEDIATAMENTE para asegurar que dx sea relativo al frame anterior
                # Esto evita el crecimiento exponencial de dx que causaba el desfase masivo
                self.app.drag_data["x"] = event.x
                self.app.drag_data["y"] = event.y

                # Convertir de coordenadas de pantalla a coordenadas del mundo
                dx_world = dx_screen / self.app.canvas.zoom_level
                dy_world = dy_screen / self.app.canvas.zoom_level

                dx = dx_world
                dy = dy_world

                # Detectar y mover segmentos de bus paralelos (DESACTIVADO temporalmente por reporte de error)
                moved_components = set()

                # Activar modo de movimiento rápido para reducir lag
                if hasattr(self.app, 'unified_line_system'):
                    self.app.unified_line_system.start_fast_move_mode()

                if hasattr(self.app, 'move_segment_with_connections'):
                    try:
                        self.app.move_segment_with_connections(connection, segment_idx, dx, dy, moved_components=moved_components)
                    except Exception as e:
                        print(f"[DEBUG DRAG] Error moving ref segment: {e}")

                    # DESACTIVADO: Movimiento de segmentos paralelos causa recursión infinita en algunos casos
                else:
                    # Fallback al método anterior si la nueva función no está disponible
                    if segment_idx < len(connection.line_ids):
                        try:
                            line_id = connection.line_ids[segment_idx]
                            coords = self.app.canvas.coords(line_id)

                            if len(coords) >= 4:
                                x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
                                is_horizontal = abs(x2 - x1) > abs(y2 - y1)

                                # CORRECCIÓN ZOOM: Multiplicar delta mundo por zoom para desplazamientos en canvas
                                zoom = self.app.canvas.zoom_level
                                if is_horizontal:
                                    new_coords = [x1, y1 + (dy * zoom), x2, y2 + (dy * zoom)]
                                else:
                                    new_coords = [x1 + (dx * zoom), y1, x2 + (dx * zoom), y2]

                                self.app.canvas.coords(line_id, *new_coords)

                        except Exception as e:

                            pass

                if hasattr(self.app, 'set_status'):
                    self.app.set_status("↕️ Moviendo segmento de línea...", duration=1000)
                return  # Solo retornar para líneas individuales

        left_button_pressed = event.state & 0x100
        right_button_pressed = event.state & 0x400
        import sys
        alt_pressed = bool(event.state & 0x20000) if sys.platform.startswith('win') else bool(event.state & 0x8)

        # Determinar si hay algo que arrastrar (Componente o Apantallamiento)
        has_shielding_selected = hasattr(self.app, 'shielding_manager') and self.app.shielding_manager.selected_shielding

        if ((self.app.selected_component or (hasattr(self.app, 'selected_elements') and len(self.app.selected_elements) > 0) or self.app.get_selected_shape()) or has_shielding_selected) and (left_button_pressed or (alt_pressed and right_button_pressed)) and (not hasattr(self.app, 'locked_segment') or not self.app.locked_segment):
            if hasattr(self.app, 'set_status'):
                self.app.set_status("🚀 Moviendo elementos...", duration=1000)
            # CORRECCIÓN DESFASE: Convertir dx/dy de coordenadas de pantalla a coordenadas del mundo
            dx_screen = event.x - self.app.drag_data["x"]
            dy_screen = event.y - self.app.drag_data["y"]

            # CRÍTICO: Actualizar drag_data para el siguiente frame
            self.app.drag_data["x"] = event.x
            self.app.drag_data["y"] = event.y

            # Convertir de coordenadas de pantalla a coordenadas del mundo
            dx_world = dx_screen / self.app.canvas.zoom_level
            dy_world = dy_screen / self.app.canvas.zoom_level

            # Restringir movimiento con Alt
            if alt_pressed:
                if right_button_pressed:  # Alt + click derecho: movimiento horizontal (fija vertical)
                    dy_world = 0
                elif left_button_pressed:  # Alt + click izquierdo: movimiento vertical (fija horizontal)
                    dx_world = 0

            # Movimiento horizontal si shape está pegado al riel DIN
            selected_shape = self.app.get_selected_shape()
            if selected_shape and hasattr(selected_shape, 'metadata') and selected_shape.metadata.get('snapped_to_rail'):
                # Solo permitir movimiento horizontal mientras está pegado al riel
                dy_world = 0

            dx = dx_world
            dy = dy_world

            # Arrastre de Apantallamiento
            if has_shielding_selected:
                self.app.shielding_manager.move_selected_shielding(dx, dy)

            # Activar modo de movimiento rápido para reducir lag
            if hasattr(self.app, 'unified_line_system'):
                self.app.unified_line_system.start_fast_move_mode()

            if hasattr(self.app, 'selected_elements') and len(self.app.selected_elements) > 0:
                # OPTIMIZACIÓN DE RENDIMIENTO: Identificar elementos y conexiones afectados de una sola vez
                # Incluir cualquier elemento seleccionable que implemente `move()`
                # (esto cubre componentes 2D que pueden no exponer
                # `get_connection_points_global`). Evita excluir elementos
                # útiles para el arrastre en hojas 2D.
                # Prefer locked drag targets if present (set on click inside a group)
                targets = getattr(self.app, '_group_drag_targets', None)
                if targets:
                    selected_components = {e for e in targets if hasattr(e, 'move')}
                else:
                    selected_components = {e for e in self.app.selected_elements if hasattr(e, 'move')}

                # Verificar si es el primer movimiento para limpiar indicadores
                first_move = True
                for comp in selected_components:
                    if getattr(comp, '_is_moving', False):
                        first_move = False
                        break

                if first_move:
                    self.app.canvas.delete("selection_indicator")

                # IDENTIFICAR LÍNEAS AFECTADAS Y LÍNEAS MANUALES INTERNAS
                internal_manual_connections = []
                affected_connections = set()

                for connection in self.app.connections:
                    is_start_selected = connection.start_component in selected_components
                    is_end_selected = connection.end_component in selected_components

                    if is_start_selected or is_end_selected:
                        affected_connections.add(connection)

                        # Si es manual e interna al grupo, se moverá con el grupo más adelante
                        if (getattr(connection, 'manually_modified', False) and
                            is_start_selected and is_end_selected):
                            internal_manual_connections.append(connection)

                # 1. Mover componentes y shapes
                # Move using the locked targets if present, otherwise current selection
                move_list = getattr(self.app, '_group_drag_targets', None) or list(self.app.selected_elements)
                for element in move_list:
                    if hasattr(element, 'move'):
                        element.move(dx, dy)

                # 2. ACTUALIZAR CONEXIONES EN BLOQUE (Mucho más eficiente)
                if hasattr(self.app, 'unified_line_system'):
                    for connection in affected_connections:
                        # CLON DE FASE VERTICAL: reconstruir escalera-L desde los pines
                        # actuales para conservar forma y ortogonalidad al mover el clon.
                        if getattr(connection, 'fase_clone_axis', None) == 'x':
                            fcs = self.app.unified_line_system
                            if fcs._rebuild_fase_clone_segments(connection):
                                fcs._redraw_connection_fast(connection)
                                continue

                        # Si es manual e interna, el movimiento se manejará por traslado de segmentos (abajo)
                        if connection in internal_manual_connections:
                            continue

                        # Si es manual externa, ajustar solo pins (rubber-banding)
                        if getattr(connection, 'manually_modified', False):
                            if hasattr(self.app, 'adjust_connection_endpoints'):
                                self.app.adjust_connection_endpoints(connection)
                        else:
                            # Si es automática (Manhattan), recalcular ruta
                            self.app.unified_line_system._recalculate_connection_segments_fast(connection)
                            self.app.unified_line_system._redraw_connection_fast(connection)

                # Trasladar líneas manuales internas
                for connection in internal_manual_connections:
                    # Trasladar segmentos en la estructura de datos
                    if hasattr(connection, 'segments') and connection.segments:
                        for i, segment in enumerate(connection.segments):
                            (x1, y1), (x2, y2) = segment
                            connection.segments[i] = ((x1 + dx, y1 + dy), (x2 + dx, y2 + dy))

                    # Trasladar puntos de ángulo manual si existen
                    if hasattr(connection, 'manual_angle_points') and connection.manual_angle_points:
                        for i, point in enumerate(connection.manual_angle_points):
                            px, py = point
                            connection.manual_angle_points[i] = (px + dx, py + dy)

                    if hasattr(connection, 'line_ids') and connection.line_ids:
                        for line_id in connection.line_ids:
                            try:
                                coords = self.app.canvas.coords(line_id)
                                if coords:
                                    # Trasladar todas las coordenadas
                                    # CORRECCIÓN ZOOM: Aplicar zoom al desplazamiento
                                    zoom = self.app.canvas.zoom_level
                                    new_coords = []
                                    for i in range(0, len(coords), 2):
                                        new_coords.append(coords[i] + (dx * zoom))      # x
                                        new_coords.append(coords[i+1] + (dy * zoom))    # y
                                    self.app.canvas.coords(line_id, *new_coords)
                            except Exception as e:
                                pass  # Ignorar errores en líneas individuales

                # GABINETE 2D: Redibujar shapes si el grupo contiene alguno
                _has_shapes = any(hasattr(e, 'shape_type') for e in self.app.selected_elements)
                if _has_shapes and hasattr(self.app, 'redraw_all_shapes'):
                    self.app.redraw_all_shapes()
            else:
                if self.app.selected_component is not None:
                    self.app.selected_component.move(dx, dy)

                    # Usar sistema unificado optimizado
                    if hasattr(self.app, 'unified_line_system'):
                        self.app.unified_line_system.update_all_connections_for_component(self.app.selected_component)
                    else:
                        # Fallback al método anterior
                        for connection in self.app.connections:
                            if (connection.start_component == self.app.selected_component or
                                connection.end_component == self.app.selected_component):
                                self.app.manhattan_router.update_manhattan_line(connection)
                else:
                    # Mover shapes seleccionadas
                    selected_shape = self.app.get_selected_shape()
                    if selected_shape:
                        # BLOQUEAR MOVIMIENTO DE SHAPES FIJOS (Tablero, Puerta, Líneas de medida)
                        meta = getattr(selected_shape, 'metadata', {})
                        is_locked = meta.get('locked') or meta.get('type') == 'cabinet_background'
                        if is_locked:
                            if hasattr(self.app, 'set_status'):
                                self.app.set_status("🔒 Elemento fijo — no se puede mover", "orange")
                        else:
                            selected_shape.move(dx, dy)

                            if hasattr(selected_shape, 'metadata') and 'component_tag' in selected_shape.metadata:
                                tag = selected_shape.metadata['component_tag']
                                if hasattr(self.app, 'text_components'):
                                    for t in self.app.text_components:
                                        if getattr(t, 'text', '') == tag:
                                            # Solo mover si está cerca (para evitar mover otros textos idénticos)
                                            dist = math.sqrt((t.x - selected_shape.x)**2 + (t.y - selected_shape.y)**2)
                                            if dist < 200: # Umbral razonable para etiquetas de gabinete
                                                t.move(dx, dy)
                                                break

                            # Si es un riel DIN, mover shapes pegados
                            if hasattr(selected_shape, 'shape_type') and selected_shape.shape_type == 'din_rail':
                                if hasattr(self.app, 'shape_manager') and hasattr(self.app.shape_manager, 'shapes'):
                                    # Buscar y mover shapes pegados a este riel
                                    for shape in self.app.shape_manager.shapes:
                                        if (hasattr(shape, 'metadata') and
                                            shape.metadata.get('snapped_to_rail') and
                                            shape.metadata.get('snapped_rail_id') == id(selected_shape)):
                                            shape.move(dx, dy)

                            # Detectar si un shape se desliza fuera del riel
                            if (hasattr(selected_shape, 'metadata') and
                                selected_shape.metadata.get('snapped_to_rail') and dx != 0):
                                # Buscar el riel al que está pegado
                                if hasattr(self.app, 'shape_manager') and hasattr(self.app.shape_manager, 'shapes'):
                                    for shape in self.app.shape_manager.shapes:
                                        if id(shape) == selected_shape.metadata.get('snapped_rail_id'):
                                            # Verificar si el shape se deslizó fuera del riel (límites X)
                                            rail_x_min = shape.x - shape.width / 2
                                            rail_x_max = shape.x + shape.width / 2
                                            shape_x_min = selected_shape.x - selected_shape.width / 2 if hasattr(selected_shape, 'width') else selected_shape.x
                                            shape_x_max = selected_shape.x + selected_shape.width / 2 if hasattr(selected_shape, 'width') else selected_shape.x

                                            # Si el shape se salió del riel en X, despegarlo automáticamente
                                            if shape_x_min < rail_x_min or shape_x_max > rail_x_max:
                                                selected_shape.metadata['snapped_to_rail'] = False
                                                if 'snapped_rail_id' in selected_shape.metadata:
                                                    del selected_shape.metadata['snapped_rail_id']
                                            break

                            self.app.redraw_all_shapes()

            self.app.drag_data["x"] = event.x
            self.app.drag_data["y"] = event.y

    def on_canvas_release(self, event):
        """
        Maneja la liberación del mouse después del arrastre

        """
        # FINALIZAR ARRASTRE DE ETIQUETA DE NUMERACIÓN DE CABLE
        if getattr(self.app, '_dragging_wire_label', False):
            self.app._dragging_wire_label = False
            self.app._dragging_wire_label_conn = None
            try:
                self.app.canvas.config(cursor="")
            except Exception:
                pass
            # Marcar el lienzo como modificado para indicar cambios sin guardar
            if hasattr(self.app, 'is_dirty'):
                self.app.is_dirty = True
            return "break"

        # PRIORIDAD: FINALIZAR APANTALLAMIENTO
        if getattr(self.app, 'shielding_mode_enabled', None) and self.app.shielding_mode_enabled.get():
            if hasattr(self.app, 'shielding_drag_start') and self.app.shielding_drag_start:
                x1, y1 = self.app.shielding_drag_start
                x2, y2 = event_to_canvas_coords(event, self.app.canvas)

                if self.app.shielding_manager.active_preview:
                    preview = self.app.shielding_manager.active_preview
                    if abs(preview.x2 - preview.x1) > 10:
                        from models.shielding import Shielding
                        final_shielding = Shielding(
                            preview.x1, preview.x2, preview.y,
                            labels=preview.labels,
                            header_text=preview.header_text,
                            num_wires=preview.num_wires,
                            gauge=preview.gauge,
                            cable_name=preview.cable_name
                        )
                        self.app.shielding_manager.add_shielding(final_shielding)

                        if hasattr(self.app, 'undo_manager'):
                            self.app.undo_manager.save_state("Crear Apantallamiento")

                    self.app.shielding_manager.clear_preview()

                self.app.shielding_drag_start = None

                # Desactivar modo automáticamente tras soltar el click
                if hasattr(self.app, '_toggle_shielding_mode'):
                    self.app._toggle_shielding_mode()

                return

        # Finalizar movimiento de Apantallamiento
        if hasattr(self.app, 'shielding_manager') and self.app.shielding_manager.selected_shielding:
            # Forzar un redibujado final para asegurar alineación perfecta tras el drag con canvas.move
            self.app.shielding_manager.selected_shielding.draw(self.app.canvas)
            if hasattr(self.app, 'undo_manager'):
                self.app.undo_manager.save_state("Mover Apantallamiento")

        # Finalizar modo de movimiento rápido
        if hasattr(self.app, 'unified_line_system'):
            self.app.unified_line_system.end_fast_move_mode()

        # Finalizar redimensionamiento de shapes
        if (hasattr(self.app.shape_manager, 'editor') and self.app.shape_manager.editor and
            self.app.shape_manager.editor.editing):
            self.app.shape_manager.editor.editing = False
            self.app.shape_manager.editor.edit_initial_size = 0
            self.app.canvas.config(cursor="arrow")
            return  # No procesar otros tipos de liberación

        # Finalizar clonado de fase
        if (hasattr(self.app, 'fase_cloning_active') and self.app.fase_cloning_active):
            self._finalize_fase_cloning()
            return

        # Finalizar selección por área
        if hasattr(self.app, 'selection_box_active') and self.app.selection_box_active:
            if hasattr(self.app, 'finish_selection_box'):
                self.app.finish_selection_box(event.x, event.y)

            return

        # Finalizar arrastre de línea
        if (hasattr(self.app, 'selected_connection') and self.app.selected_connection and
            hasattr(self.app, 'selected_segment') and self.app.selected_segment):

            connection, segment_idx = self.app.selected_segment

            # AL SOLTAR: Restaurar color normal pero mantener selección activa
            if segment_idx < len(connection.line_ids):
                try:
                    line_id = connection.line_ids[segment_idx]
                    # Restaurar color y grosor normal
                    current_color = self.app.current_line_color.get()
                    current_width = self.app.current_line_width.get()
                    current_dash = self.app.parse_dash_pattern(self.app.current_line_dash.get())
                    self.app.canvas.itemconfig(line_id, fill=current_color, width=current_width, dash=current_dash)

                except Exception as e:
                    pass

            # MANTENER CURSOR SIZING Y SELECCIÓN ACTIVA
            self.app.canvas.config(cursor="sizing")

            # Limpiar caché de segmentos de bus para el próximo arrastre
            if hasattr(self.app, 'bus_segments_cache'):
                delattr(self.app, 'bus_segments_cache')

            # Liberar bloqueo al soltar el mouse — el siguiente drag ya es intencional
            self.app.locked_segment = False

            # Finalizar modo de movimiento rápido
            if hasattr(self.app, 'unified_line_system'):
                self.app.unified_line_system.end_fast_move_mode()

            # Mantener la selección activa para permitir más movimientos o borrado
            # El cursor se mantiene como "sizing" hasta que se presione Escape

            return

        # FUNCIONALIDAD ORIGINAL: Reset de arrastre
        if self.app.selected_component:
            # Restaurar círculo de selección al soltar componente
            # Marcar que ya no está en movimiento
            if hasattr(self.app.selected_component, '_is_moving'):
                self.app.selected_component._is_moving = False
            # Redibujar el círculo de selección (solo si el componente tiene este método)
            if hasattr(self.app.selected_component, 'update_selection_visual'):
                self.app.selected_component.update_selection_visual()

            # Realinear texto insertado con la etiqueta fija más cercana al soltar
            _sel = self.app.selected_component
            if (hasattr(_sel, 'canvas_id') and hasattr(_sel, 'text')
                    and hasattr(self.app, '_align_text_to_nearest_label')):
                self.app._align_text_to_nearest_label(_sel)
                if hasattr(_sel, 'update_selection_visual'):
                    _sel.update_selection_visual()

        # También restaurar círculo para selección múltiple
        if hasattr(self.app, 'selected_elements') and self.app.selected_elements:
            for element in self.app.selected_elements:
                if hasattr(element, '_is_moving'):
                    element._is_moving = False
                if hasattr(element, 'update_selection_visual'):
                    element.update_selection_visual()

            # CRÍTICO: Redibujar indicadores de selección múltiple en las nuevas posiciones
            if hasattr(self.app, 'update_selection_indicators'):
                self.app.update_selection_indicators()

        # Limpiar targets de arrastre grupal si existen
        if hasattr(self.app, '_group_drag_targets'):
            try:
                delattr(self.app, '_group_drag_targets')
            except Exception:
                try:
                    del self.app._group_drag_targets
                except Exception:
                    pass

        # Resetear flag de undo move
        self.app._undo_move_checkpoint_saved = False

        # AUTO-ALINEACIÓN: Alinear componentes movidos si el quiebre es < 10px
        if self.app.selected_component:
            if hasattr(self.app, 'auto_align_component_to_connections'):
                self.app.auto_align_component_to_connections(self.app.selected_component)
        elif hasattr(self.app, 'selected_elements') and self.app.selected_elements:
            if hasattr(self.app, 'auto_align_component_to_connections'):
                for element in self.app.selected_elements:
                    if hasattr(element, 'get_connection_points_global'):
                        self.app.auto_align_component_to_connections(element)

        # SNAP TO RAIL DIN AL SOLTAR — solo si el shape toca físicamente el riel
        selected_shape = self.app.get_selected_shape()
        if selected_shape and hasattr(selected_shape, 'x') and hasattr(selected_shape, 'y'):
            # Nunca hacer snap a shapes fijos (tablero, tapa, medidas)
            _meta = getattr(selected_shape, 'metadata', {})
            if _meta.get('locked') or _meta.get('type') == 'cabinet_background':
                pass
            elif hasattr(self.app, 'shape_manager') and hasattr(self.app.shape_manager, 'shapes'):
                for rail in self.app.shape_manager.shapes:
                    if not (hasattr(rail, 'shape_type') and rail.shape_type == 'din_rail'):
                        continue

                    # Bounding box del riel
                    rail_x_min = rail.x - rail.width / 2
                    rail_x_max = rail.x + rail.width / 2
                    rail_y_min = rail.y - rail.height / 2
                    rail_y_max = rail.y + rail.height / 2

                    shape_half_w = getattr(selected_shape, 'radius', getattr(selected_shape, 'width', 0) / 2)
                    shape_half_h = getattr(selected_shape, 'radius', getattr(selected_shape, 'height', 0) / 2)
                    shape_x_min = selected_shape.x - shape_half_w
                    shape_x_max = selected_shape.x + shape_half_w
                    shape_y_min = selected_shape.y - shape_half_h
                    shape_y_max = selected_shape.y + shape_half_h

                    # Solo snap si los bboxes se solapan (contacto físico real)
                    touching_x = shape_x_max > rail_x_min and shape_x_min < rail_x_max
                    touching_y = shape_y_max > rail_y_min and shape_y_min < rail_y_max

                    if touching_x and touching_y:
                        # Centrar el shape en el eje Y del riel
                        selected_shape.y = rail.y

                        if not hasattr(selected_shape, 'metadata'):
                            selected_shape.metadata = {}
                        selected_shape.metadata['snapped_to_rail'] = True
                        selected_shape.metadata['snapped_rail_id'] = id(rail)

                        if hasattr(self.app, 'redraw_all_shapes'):
                            self.app.redraw_all_shapes()
                        break

        # SNAP TO RAIL DIN — BLOCK TERMINAL (mismo criterio que shapes)
        bt = getattr(self.app, '_selected_block_terminal', None)
        if bt and hasattr(self.app, 'shape_manager'):
            from models.shape import DinRail
            for rail in self.app.shape_manager.shapes:
                if not isinstance(rail, DinRail):
                    continue

                # Bounding box del riel
                rail_x_min = rail.x - rail.width / 2
                rail_x_max = rail.x + rail.width / 2
                rail_y_min = rail.y - rail.height / 2
                rail_y_max = rail.y + rail.height / 2

                # Bounding box del BT
                bt_x_min = bt['x0']
                bt_x_max = bt['x0'] + bt['total_w']
                bt_y_min = bt['y0']
                bt_y_max = bt['y0'] + bt['total_h']

                # Solo snap si los bboxes se solapan (mismo criterio que shapes)
                touching_x = bt_x_max > rail_x_min and bt_x_min < rail_x_max
                touching_y = bt_y_max > rail_y_min and bt_y_min < rail_y_max

                if touching_x and touching_y:
                    # Calcular desplazamiento Y necesario para centrar en el riel
                    new_y  = rail.y
                    dy     = new_y - bt['y']

                    # Mover todos los items del canvas
                    self.app.canvas.move(bt['bt_tag'], 0, dy)

                    # Actualizar coordenadas en el dict
                    bt['y']  += dy
                    bt['y0'] += dy
                    bt['snapped_to_rail'] = True
                    bt['snapped_rail_id'] = id(rail)
                    break

        if hasattr(self.app, 'update_cross_references'):
            self.app.update_cross_references()

        if hasattr(self.app, 'update_wire_numbers'):
            self.app.update_wire_numbers()

        # SIMULACIÓN: Si hay componentes presionados (momentary), liberarlos
        if hasattr(self.app, 'sim_pressed_components') and self.app.sim_pressed_components:
            try:
                for comp in list(self.app.sim_pressed_components):
                    try:
                        comp.is_active = False
                        # Refrescar visual
                        comp.load_image(comp.svg_path)
                        comp.draw()
                    except Exception:
                        pass
                # Limpiar registro
                self.app.sim_pressed_components.clear()
            except Exception:
                pass

    def on_mouse_motion(self, event):
        """Maneja el movimiento del mouse sobre el canvas"""
        if hasattr(self.app, 'project'):
            sheet = self.app.project.get_active_sheet()
            if sheet and (not getattr(sheet, 'editable', True) or sheet.name in AppConstants.NON_EDITABLE_SHEETS):
                # EXCEPCIÓN: Permitir movimiento si estamos dibujando un Riel DIN u otra forma
                if not (hasattr(self, 'shape_drawing') and self.shape_drawing and self.shape_drawing.shape_type):
                    self.app.canvas.config(cursor="")
                    return

        # Movimiento del mouse: preview, snapping y crosshair consolidados.
        # Throttling a 60 FPS y cálculos por distancia al cuadrado para evitar
        # sobrecarga. Solo un sistema de preview puede estar activo a la vez.
        # Durante el arrastre de etiqueta de numeración, no alterar cursor ni previews
        if getattr(self.app, '_dragging_wire_label', False):
            try:
                self.app.canvas.config(cursor="fleur")
            except Exception:
                pass
            return

        # THROTTLING: Limitar a 60 FPS (16ms entre eventos)
        current_time = int(time.time() * 1000)
        if current_time - self.last_motion_time < self.motion_throttle_ms:
            return  # Saltar este evento si no ha pasado suficiente tiempo
        self.last_motion_time = current_time

        if self.app.locked_segment:
            return

        x, y = event.x, event.y
        x_comp, y_comp = event_to_canvas_coords(event, self.app.canvas)

        # Solo actualizar mouse pos si cambió significativamente
        mouse_changed = (abs(x - self.last_mouse_x) > 2 or abs(y - self.last_mouse_y) > 2)
        if mouse_changed:
            self.app.mouse_x = x
            self.app.mouse_y = y
            self.last_mouse_x = x
            self.last_mouse_y = y

        # ACTUALIZAR CROSSHAIR: Solo si es necesario
        if hasattr(self.app, '_draw_crosshair') and mouse_changed:
            self.app._draw_crosshair(event)

        # COORDINACIÓN DE PREVIEW: PRIORIDAD DEFINIDA
        # PRIORIDAD 1: PREVIEW DE SHAPES
        if self.shape_drawing.is_drawing and mouse_changed:
            self.shape_drawing.update_preview(x, y)
            return  # No procesar otros previews

        # COORDINACIÓN DE PREVIEW: PRIORIDAD DEFINIDA

        # PRIORIDAD 2: Preview de componente (reemplaza a EventHandler)
        if self.app.component_preview_mode and mouse_changed:
            self.app.mover_preview_componente(x_comp, y_comp)
            return # NO ejecutar más sistemas de preview

        # PRIORIDAD 3: Preview de formas (reemplaza a EventHandler)
        if hasattr(self.app, 'shape_preview_mode') and self.app.shape_preview_mode and mouse_changed:
            self._move_shape_preview(x, y)
            return # NO ejecutar más sistemas de preview

        # PRIORIDAD 4: Preview de EventHandler (solo cuando no hay otros activos)
        # Solo ejecutar si NO hay otros modos de preview activos Y no hay shapes siendo editadas

        # NO ejecutar EventHandler si hay shapes activas siendo editadas
        if (hasattr(self.app, 'get_selected_shape') and
            hasattr(self.app.shape_manager, 'editor') and
            self.app.shape_manager.editor and
            self.app.shape_manager.editor.editing):
            return  # No interferir con edición de shapes

        # Solo ejecutar EventHandler cuando está libre y el mouse realmente se movió
        if mouse_changed:
            self._run_coordinated_eventhandler_preview(x, y)

        # PRIORIDAD MÁXIMA: PREVIEW MANUAL ROUTING (antes que cualquier otra detección)
        # Solo ejecutar si NO hay otros modos de preview activos
        if not self.shape_drawing.is_drawing and not self.app.component_preview_mode and mouse_changed:
            self._handle_manual_routing_preview(x, y)

        # Detección de puntos de conexión y highlight en un único loop
        near_connection_point = False
        closest_point = None
        closest_distance_sq = float('inf')
        visual_threshold_sq = 15 * 15
        click_threshold_sq = 8 * 8

        if self.app.highlighted_component:
            self.app.highlighted_component.highlighted = False
            self.app.highlighted_component = None

        for comp in self.app.components:
            # Highlight: componente bajo el cursor
            is_inside = comp.contains_point(x_comp, y_comp)
            if is_inside and not self.app.highlighted_component:
                comp.highlighted = True
                self.app.highlighted_component = comp

            # Solo calcular puntos si el cursor está cerca del componente
            # (con un margen de seguridad de 20px)
            margin = 20
            if not is_inside and not (comp.x - margin <= x_comp <= comp.x + comp.size[0] + margin and
                                     comp.y - margin <= y_comp <= comp.y + comp.size[1] + margin):
                continue

            # Snap: puntos de conexión cercanos
            for i, (global_x, global_y, point) in enumerate(comp.get_connection_points_global()):
                distance_sq = (x_comp - global_x) ** 2 + (y_comp - global_y) ** 2
                if distance_sq <= visual_threshold_sq:
                    near_connection_point = True
                    if distance_sq < closest_distance_sq:
                        closest_distance_sq = distance_sq
                        distance = distance_sq ** 0.5 if distance_sq <= click_threshold_sq else 15
                        closest_point = {
                            'component': comp,
                            'point_idx': i,
                            'canvas_x': global_x,
                            'canvas_y': global_y,
                            'distance': distance,
                            'within_click_area': distance_sq <= click_threshold_sq
                        }

        # SNAP AUTOMÁTICO CON FEEDBACK PRECISO
        if near_connection_point and closest_point:
            self._set_canvas_cursor("crosshair")

            # SNAP AUTOMÁTICO: Activar modo de conexión si no está activo
            if not hasattr(self.app, 'connection_mode'):
                self.app.connection_mode = False
            if not hasattr(self.app, 'connection_start'):
                self.app.connection_start = None

            if hasattr(self.app, 'status_label'):
                comp_name = closest_point['component'].name

                if hasattr(self.app, 'set_status'):
                    self.app.set_status(f"🎯 ÁREA DE CLICK: {comp_name} - Click aquí para conectar", "lime")

                    # SNAP VISUAL: Resaltar SOLO cuando está en área de click
                    if hasattr(self.app, 'highlight_connection_point'):
                        self.app.highlight_connection_point(
                            closest_point['component'],
                            closest_point['point_idx']
                        )
                else:  # Cerca pero fuera del área de click
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status(f"📍 Punto cercano: {comp_name} - Acérquese más para conectar", "orange")

                    # NO mostrar círculo amarillo cuando está fuera del área de click
                    if hasattr(self.app, 'clear_connection_point_highlights'):
                        self.app.clear_connection_point_highlights()

        else:
            # Restaurar cursor normal cuando no está cerca de puntos de conexión
            if not (hasattr(self.app, 'selected_connection') and self.app.selected_connection):
                self._set_canvas_cursor("")

            # Limpiar información de status
            if hasattr(self.app, 'set_status'):
                if not hasattr(self.app, 'connection_mode') or not self.app.connection_mode:
                    # El temporizador de set_status lo reseteará a "Listo"
                    pass

            # Limpiar resaltado de puntos
            if hasattr(self.app, 'clear_connection_point_highlights'):
                self.app.clear_connection_point_highlights()

    def on_canvas_resize(self, event):
        """
        Maneja el redimensionamiento del canvas.
        """
        # No redibujar el grid al redimensionar: el grid es fijo hasta que el usuario lo solicite
        return

    def on_key_press(self, event):
        """
        Maneja las pulsaciones de teclas según especificación EXACTA.

        ATAJOS DEFINIDOS:
        - Ctrl+R: giro derecha
        - Ctrl+Shift+R: giro izquierda
        - Ctrl+O: abrir archivo .ecad
        - Ctrl+N: nuevo lienzo
        - Ctrl+S: guardar archivo .ecad
        - Ctrl+E: exportar PDF
        - Ctrl+T: exportar DXF
        - Ctrl+Q: salir
        - Ctrl+J: distribución vertical
        - Ctrl+K: distribución horizontal
        - Ctrl+X: toggle invertir detección
        - Ctrl+A: toggle auto conexión
        - Ctrl+U: seleccionar todo
        - Ctrl+G: toggle grid (snap to grid)
        - Ctrl++/Ctrl+=: zoom in (aumentar zoom 10%)
        - Ctrl+-: zoom out (disminuir zoom 10%)
        - Ctrl+0: reset zoom (restaurar 100%)
        - Ctrl+H: alineamiento vertical de componente seleccionado
        - Ctrl+Shift+H: reflejo horizontal de componente seleccionado (NUEVO)
        - Ctrl+Shift+V: reflejo vertical de componente seleccionado (NUEVO)
        - Delete: borrar selección o componente, línea, punto de conexión
        - Escape: deseleccionar
        """
        key = event.keysym.lower()
        ctrl_pressed = event.state & 0x4  # Ctrl está presionado
        shift_pressed = event.state & 0x1  # Shift está presionado

        # RESILIENCIA: Sincronizar selected_component si hay solo uno en selected_elements
        # Esto es un fallback por si finish_selection_box no lo hizo o se perdió el estado
        if not self.app.selected_component and hasattr(self.app, 'selected_elements') and len(self.app.selected_elements) == 1:
            from models.component import Component
            if isinstance(self.app.selected_elements[0], Component):
                self.app.selected_component = self.app.selected_elements[0]

        # MODO SIMULACIÓN: Restringir teclas de edición
        if hasattr(self.app, 'simulation_mode') and self.app.simulation_mode:
            # Solo permitir teclas de navegación (Zoom, Pan) y Salir
            allowed_keys = ['plus', 'equal', 'kp_add', 'minus', 'kp_subtract', '0', 'kp_0', 'q']

            # Permitir flechas para pan (manejado en otro lugar, pero por si acaso)
            if key in ['up', 'down', 'left', 'right']:
                pass # Dejar pasar
            elif key not in allowed_keys:
                return # BLOQUEAR OTRAS TECLAS (Delete, Ctrl+R, etc.)

        if key == 'delete':
            # Delete: borrar selección o componente, línea
            self.on_delete_key()

        elif key == 'escape':
            self.on_escape_key()

        elif self.app.component_preview_mode and key in ['plus', 'equal', 'kp_add']:
            # + en preview: rotar derecha
            self.app.rotate_preview_component(90)
            return

        elif self.app.component_preview_mode and key in ['minus', 'kp_subtract']:
            # en preview: rotar izquierda
            self.app.rotate_preview_component(-90)
            return

        elif ctrl_pressed:
            if key == 'r':
                if shift_pressed:
                    # Ctrl+Shift+R: giro izquierda
                    if self.app.component_preview_mode:
                        self.app.rotate_preview_component(-90)
                    elif self.app.selected_component:
                        self.app.rotate_selected_component(-90)  # Giro izquierda

                else:
                    # Ctrl+R: giro derecha
                    if self.app.component_preview_mode:
                        self.app.rotate_preview_component(90)
                    elif self.app.selected_component:
                        self.app.rotate_selected_component(90)   # Giro derecha

            elif key == 'z':
                # Ctrl+Z: Deshacer
                self.app.undo()
                return

            elif key == 'y':
                # Ctrl+Y: Rehacer
                self.app.redo()
                return

            elif key == 'c':
                # Ctrl+C: Copiar selección
                self.app.copy_selection()
                return

            elif key == 'v':
                # Ctrl+V: Pegar selección
                self.app.paste_selection()
                return

            elif key == 'u':
                # Ctrl+U: Seleccionar todo
                if hasattr(self.app, 'select_all'):
                    self.app.select_all()

            elif key == 'o':
                # Ctrl+O: abrir archivo .ecad
                if hasattr(self.app, 'load_canvas'):
                    self.app.load_canvas()
                else:
                    pass

            elif key == 'n':
                # Ctrl+N: nuevo lienzo
                if hasattr(self.app, 'new_canvas'):
                    self.app.new_canvas()
                else:
                    pass

            elif key == 's':
                # Ctrl+S: guardar archivo .ecad
                if hasattr(self.app, 'save_canvas'):
                    self.app.save_canvas()
                else:
                    pass

            elif key == 'e':
                if hasattr(self.app, 'export_pdf'):
                    self.app.export_pdf()

            elif key == 't':
                if hasattr(self.app, 'export_dxf'):
                    self.app.export_dxf()

            elif key == 'q':
                # Ctrl+Q: salir
                self.app.root.quit()

            elif key == 'i':
                # Ctrl+I: activar/desactivar modo insertar punto
                self.app.toggle_insert_point_mode()

            # NUEVOS ATAJOS
            elif key == 'x':
                # Ctrl+X: toggle invertir detección
                if hasattr(self.app, 'invertir_deteccion'):
                    current_value = self.app.invertir_deteccion.get()
                    new_value = not current_value
                    self.app.invertir_deteccion.set(new_value)

                    # Mensaje en consola

                    if hasattr(self.app, 'set_status'):
                        status_text = f"Invertir detección: {'ACTIVADO' if new_value else 'DESACTIVADO'}"
                        self.app.set_status(status_text, "blue")
                else:
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status("Invertir no disponible", "red")

            elif key == 'a':
                # Ctrl+A: toggle auto conexión
                if hasattr(self.app, 'auto_conexion_enabled'):
                    current_value = self.app.auto_conexion_enabled.get()
                    new_value = not current_value
                    self.app.auto_conexion_enabled.set(new_value)

                    # Mensaje en consola

                    if hasattr(self.app, 'set_status'):
                        status_text = f"Auto conexión: {'ACTIVADO' if new_value else 'DESACTIVADO'}"
                        self.app.set_status(status_text, "blue")
                else:
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status("Auto conexión no disponible", "red")

            elif key == 'g':
                # Ctrl+G: toggle grid (visibilidad + snap to grid)
                if hasattr(self.app, 'snap_to_grid_enabled') and hasattr(self.app, 'config'):
                    current_snap = self.app.snap_to_grid_enabled.get()

                    # Verificar si se está intentando activar el grid
                    new_snap = not current_snap
                    if new_snap:
                        # Mostrar advertencia antes de activar el grid
                        if not self.app.show_grid_warning():
                            # Usuario canceló, no activar
                            if hasattr(self.app, 'set_status'):
                                self.app.set_status("Activación de Grid cancelada por el usuario", "orange")
                            return

                    self.app.snap_to_grid_enabled.set(new_snap)
                    self.app.config["snap_to_grid_enabled"] = new_snap

                    # Asegurar que el grid sea visible cuando se activa snap
                    if new_snap and hasattr(self.app, 'grid_visible'):
                        self.app.config["grid_visible"] = True

                    self.app.draw_grid(force=True)

                    # Mensaje en consola
                    status = f"Grid visible + Snap: {'ACTIVADO' if new_snap else 'DESACTIVADO'}"

                    if hasattr(self.app, 'set_status'):
                        self.app.set_status(status, "blue")
                else:
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status("Grid no disponible", "red")

            elif key in ['plus', 'equal', 'kp_add']:
                # Zoom in: Ctrl++/Ctrl+=/Numpad+
                self.simple_zoom_manager.zoom_in()
                self._redraw_block_terminals_after_zoom()
                if self.app:
                    self.app.set_status(f"🔍 Zoom: {int(self.simple_zoom_manager.zoom_level * 100)}%", "blue")
                    self.app.update_info_bar()
                return "break"
            elif (ctrl_pressed and key == "minus") or key == "kp_subtract":
                # Zoom out: Ctrl+-+/Numpad-
                self.simple_zoom_manager.zoom_out()
                self._redraw_block_terminals_after_zoom()
                if self.app:
                    self.app.set_status(f"🔍 Zoom: {int(self.simple_zoom_manager.zoom_level * 100)}%", "blue")
                    self.app.update_info_bar()
                return "break"
            elif (ctrl_pressed and key == "0") or key == "kp_0":
                # Reset zoom: Ctrl+0/Numpad0
                self.simple_zoom_manager.reset_zoom()
                self._redraw_block_terminals_after_zoom()
                if self.app:
                    self.app.set_status("🔍 Zoom restablecido (100%)", "blue")
                    self.app.update_info_bar()
                return "break"

            elif key == 'h':
                # GABINETE 2D: alinear shapes (circle/rect/square) seleccionados
                if self._is_cabinet_sheet():
                    _ALIGNABLE = {'circle', 'rect', 'square'}
                    selected_shapes = [
                        e for e in getattr(self.app, 'selected_elements', [])
                        if getattr(e, 'shape_type', None) in _ALIGNABLE
                    ]
                    if len(selected_shapes) > 1:
                        ref_x = selected_shapes[0].x
                        for s in selected_shapes[1:]:
                            s.x = ref_x
                        if hasattr(self.app, 'redraw_all_shapes'):
                            self.app.redraw_all_shapes()
                        self.app.canvas.update()
                        for e in self.app.selected_elements:
                            if hasattr(e, 'selected'):
                                e.selected = False
                        self.app.selected_elements.clear()
                        if hasattr(self.app, 'selected_component'):
                            self.app.selected_component = None
                        if hasattr(self.app, 'update_selection_indicators'):
                            self.app.update_selection_indicators()
                        if hasattr(self.app, 'set_status'):
                            self.app.set_status("📏 Shapes alineados verticalmente", "blue")
                    else:
                        if hasattr(self.app, 'set_status'):
                            self.app.set_status("⚠️ Selecciona 2 o más shapes arrastrando el cuadrado azul", "orange")
                    return "break"

                # OTRAS HOJAS: comportamiento original intacto
                # Verificar selección múltiple primero
                if (hasattr(self.app, 'selected_elements') and
                    len(self.app.selected_elements) > 1):
                    self.alignment_manager.align_multiple_vertically()

                    # DESELECCIÓN COMPLETA: Igual que en otros lugares
                    # Marcar cada elemento como no seleccionado
                    for elem in self.app.selected_elements:
                        if hasattr(elem, 'selected'):
                            elem.selected = False
                    # Limpiar la lista
                    self.app.selected_elements.clear()

                    if hasattr(self.app, 'selected_component'):
                        self.app.selected_component = None

                    if hasattr(self.app, 'update_selection_indicators'):
                        self.app.update_selection_indicators()

                    if hasattr(self.app, 'set_status'):
                        self.app.set_status("📏 Alineación múltiple completada", "blue")

                # Fallback a selección individual (comportamiento original)
                elif self.app.selected_component:
                    self.alignment_manager.align_selected_vertically()

                    # DESELECCIÓN DEL COMPONENTE INDIVIDUAL
                    if self.app.selected_component and hasattr(self.app.selected_component, 'selected'):
                        self.app.selected_component.selected = False
                    self.app.selected_component = None

                    if hasattr(self.app, 'update_selection_indicators'):
                        self.app.update_selection_indicators()

                    if hasattr(self.app, 'set_status'):
                        self.app.set_status("📏 Alineación vertical completada", "blue")

            elif key == 'h' and shift_pressed:
                # Ctrl+Shift+H: Reflejo Horizontal
                if self.app.selected_component:
                    self.app.flip_selected_horizontal()
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status("↔️ Reflejo horizontal aplicado", "blue")

            elif key == 'v' and shift_pressed:
                # Ctrl+Shift+V: Reflejo Vertical
                if self.app.selected_component:
                    self.app.flip_selected_vertical()
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status("↕️ Reflejo vertical aplicado", "blue")

            elif key == 'j':
                # Ctrl+J: Distribución vertical
                if hasattr(self.app, '_distribute_components_vertically'):
                    # CRÍTICO: Sincronizar selected_elements con selected_components
                    if hasattr(self.app, 'selected_elements') and self.app.selected_elements:
                        self.app.selected_components = self.app.selected_elements.copy()
                    self.app._distribute_components_vertically()
                    self.app.set_status("↕️ Distribución vertical completada", "blue")

            elif key == 'k':
                # GABINETE 2D: alinear shapes (circle/rect/square) seleccionados
                if self._is_cabinet_sheet():
                    _ALIGNABLE = {'circle', 'rect', 'square'}
                    selected_shapes = [
                        e for e in getattr(self.app, 'selected_elements', [])
                        if getattr(e, 'shape_type', None) in _ALIGNABLE
                    ]
                    if len(selected_shapes) > 1:
                        ref_y = selected_shapes[0].y
                        for s in selected_shapes[1:]:
                            s.y = ref_y
                        if hasattr(self.app, 'redraw_all_shapes'):
                            self.app.redraw_all_shapes()
                        self.app.canvas.update()
                        for e in self.app.selected_elements:
                            if hasattr(e, 'selected'):
                                e.selected = False
                        self.app.selected_elements.clear()
                        if hasattr(self.app, 'selected_component'):
                            self.app.selected_component = None
                        if hasattr(self.app, 'update_selection_indicators'):
                            self.app.update_selection_indicators()
                        if hasattr(self.app, 'set_status'):
                            self.app.set_status("📏 Shapes alineados horizontalmente", "blue")
                    else:
                        if hasattr(self.app, 'set_status'):
                            self.app.set_status("⚠️ Selecciona 2 o más shapes arrastrando el cuadrado azul", "orange")
                    return "break"

                # OTRAS HOJAS: comportamiento original intacto
                # Ctrl+K: Distribución horizontal
                if hasattr(self.app, '_distribute_components_horizontally'):
                    # CRÍTICO: Sincronizar selected_elements con selected_components
                    if hasattr(self.app, 'selected_elements') and self.app.selected_elements:
                        self.app.selected_components = self.app.selected_elements.copy()
                    self.app._distribute_components_horizontally()
                    self.app.set_status("↔️ Distribución horizontal completada", "blue")

            elif key == 'm':
                # Ctrl+M: Distribución horizontal
                if hasattr(self.app, '_distribute_components_equidistant_horizontally'):
                    # CRÍTICO: Sincronizar selected_elements con selected_components
                    if hasattr(self.app, 'selected_elements') and self.app.selected_elements:
                        self.app.selected_components = self.app.selected_elements.copy()
                    self.app._distribute_components_equidistant_horizontally()

            elif key == 'b':
                # Ctrl+B: Insertar Block Terminal en Hoja de Gabinete 2D
                self._insert_block_terminal(event)

        # TECLAS SIN Ctrl - PAN CON FLECHAS

    # BLOCK TERMINAL (Ctrl+B)

    # SVG fuentes embebidas — una borna por módulo, se repite N veces en ancho
    BLOCK_SVG = {
        '2F': '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="10.4" height="45" version="1.1" viewBox="0 0 2.7516 11.906" xml:space="preserve" xmlns="http://www.w3.org/2000/svg">
<title>Block_Terminal 2level</title>
<g transform="matrix(.99991 0 0 1.0024 -.23629 -.053378)" stroke="#000" stroke-linecap="square" stroke-linejoin="round"><rect x=".36058" y=".17721" width="2.0022" height="11.601" fill="#afc6e9" stroke-width=".24827"/><ellipse cx="1.3611" cy="3.3085" rx=".67017" ry=".70537" fill="#59f" stroke-width=".15118"/><rect x="2.3238" y="1.9352" width=".5884" height="8.0933" fill="#afc6e9" stroke-width=".11196"/><ellipse cx="2.6204" cy="3.3124" rx=".18441" ry=".1941" fill="#59f" stroke-width=".073846"/><ellipse cx="2.6237" cy="8.1814" rx=".18445" ry=".19414" fill="#eaf" stroke-width=".073764"/><ellipse cx="1.3578" cy="8.1535" rx=".67017" ry=".70537" fill="#eaf" stroke-width=".15118"/><path transform="rotate(76.353 1.1474 3.2768)" d="m1.3838 3.2795-0.18073-0.075472-0.19289 0.033959 0.075472-0.18073-0.033959-0.19289 0.18073 0.075472 0.19289-0.033959-0.075472 0.18073z" fill="#784421" stroke-width=".26458"/><path transform="rotate(41.101 -5.524 5.8334)" d="m1.3838 3.2795-0.18073-0.075472-0.19289 0.033959 0.075472-0.18073-0.033959-0.19289 0.18073 0.075472 0.19289-0.033959-0.075472 0.18073z" fill="#784421" stroke-width=".26458"/></g></svg>''',
        '3F': '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="10.4" height="60" version="1.1" viewBox="0 0 2.7516 15.875" xml:space="preserve" xmlns="http://www.w3.org/2000/svg">
<title>Block_Terminal 3Level</title>
<g transform="matrix(1.0269 0 0 .99982 -.22571 .0014503)" stroke="#000" stroke-linecap="square" stroke-linejoin="round"><rect x=".35069" y=".13219" width="1.9133" height="15.621" fill="#afc6e9" stroke-width=".26458"/><ellipse cx="1.3272" cy="7.9042" rx=".67017" ry=".70537" fill="#59f" stroke-width=".15118"/><rect x="2.3088" y="1.6361" width=".55064" height="12.629" fill="#afc6e9" stroke-width=".070361"/><ellipse cx="2.5865" cy="7.9082" rx=".18441" ry=".1941" fill="#59f" stroke-width=".073846"/><ellipse cx="2.5898" cy="12.777" rx=".18445" ry=".19414" fill="#eaf" stroke-width=".073764"/><ellipse cx="1.324" cy="12.749" rx=".67017" ry=".70537" fill="#eaf" stroke-width=".15118"/><ellipse cx="2.5978" cy="3.0795" rx=".18445" ry=".19414" fill="#eaf" stroke-width=".073764"/><ellipse cx="1.332" cy="3.0506" rx=".67017" ry=".70537" fill="#eaf" stroke-width=".15118"/><path transform="rotate(76.353 1.2974 3.1315)" d="m1.3838 3.2795-0.18073-0.075472-0.19289 0.033959 0.075472-0.18073-0.033959-0.19289 0.18073 0.075472 0.19289-0.033959-0.075472 0.18073z" fill="#784421" stroke-width=".26458"/><path transform="rotate(41.101 -5.1948 5.6696)" d="m1.3838 3.2795-0.18073-0.075472-0.19289 0.033959 0.075472-0.18073-0.033959-0.19289 0.18073 0.075472 0.19289-0.033959-0.075472 0.18073z" fill="#784421" stroke-width=".26458"/><path transform="rotate(41.101 -11.6 8.0615)" d="m1.3838 3.2795-0.18073-0.075472-0.19289 0.033959 0.075472-0.18073-0.033959-0.19289 0.18073 0.075472 0.19289-0.033959-0.075472 0.18073z" fill="#784421" stroke-width=".26458"/></g></svg>''',
        '4F': '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="10.4" height="90" version="1.1" viewBox="0 0 2.7516 23.812" xml:space="preserve" xmlns="http://www.w3.org/2000/svg">
<title>Block_Terminal 4Level</title>
<g transform="matrix(1.0346 0 0 .99984 -.11607 .0018568)" stroke="#000" stroke-linecap="square" stroke-linejoin="round"><rect x=".24265" y=".13219" width="1.9059" height="23.468" fill="#afc6e9" stroke-width=".26458"/><ellipse cx="1.195" cy="15.209" rx=".67017" ry=".70537" fill="#59f" stroke-width=".15118"/><rect x="2.1844" y="2.7484" width=".53501" height="19.414" fill="#afc6e9" stroke-width=".085988"/><ellipse cx="2.4543" cy="15.213" rx=".18441" ry=".1941" fill="#59f" stroke-width=".073846"/><ellipse cx="2.4577" cy="20.082" rx=".18445" ry=".19414" fill="#eaf" stroke-width=".073764"/><ellipse cx="1.1918" cy="20.054" rx=".67017" ry=".70537" fill="#eaf" stroke-width=".15118"/><ellipse cx="1.203" cy="4.7696" rx=".67017" ry=".70537" fill="#59f" stroke-width=".15118"/><ellipse cx="2.4623" cy="4.7488" rx=".18441" ry=".1941" fill="#59f" stroke-width=".073846"/><ellipse cx="2.4656" cy="9.6435" rx=".18445" ry=".19414" fill="#eaf" stroke-width=".073764"/><ellipse cx="1.1998" cy="9.6146" rx=".67017" ry=".70537" fill="#eaf" stroke-width=".15118"/></g></svg>'''
    }

    BLOCK_HEIGHT    = {'2F': 45, '3F': 60, '4F': 90}   # px (1:1 mm=px)
    BLOCK_MODULE_W  = 10.4                               # px por módulo
    BLOCK_DEFAULT_BORNAS = 5
    BLOCK_DEFAULT_FILAS  = 2

    def _is_cabinet_sheet(self):
        """Retorna True si la hoja activa es la Hoja de Gabinete 2D."""
        if not hasattr(self.app, 'project'):
            return False
        sheet = self.app.project.get_active_sheet()
        if sheet is None:
            return False
        name = sheet.name.lower()
        return 'gabinete' in name or 'cabinet' in name or '2d' in name

    def _insert_block_terminal(self, event=None):
        """Ctrl+B — inserta un BT centrado en el riel DIN más cercano (o en el centro del canvas)."""
        if not self._is_cabinet_sheet():
            if hasattr(self.app, 'set_status'):
                self.app.set_status("⚠️ Ctrl+B solo disponible en la Hoja de Gabinete 2D", "orange")
            return

        # Posición base: centro visible del canvas
        try:
            cx = self.app.canvas.winfo_width()  / 2
            cy = self.app.canvas.winfo_height() / 2
            from utils.coordinates import event_to_canvas_coords
            wx, wy = event_to_canvas_coords(
                type('Event', (), {'x': cx, 'y': cy})(),
                self.app.canvas
            )
        except Exception:
            wx, wy = 200, 200

        # Snap al riel DIN más cercano: ajustar wy para que el BT quede montado en el riel
        try:
            from models.shape import DinRail
            rails = [s for s in self.app.shape_manager.shapes if isinstance(s, DinRail)]
            if rails:
                nearest = min(rails, key=lambda r: abs(r.y - wy))
                svg_key_snap = '2F' if self.BLOCK_DEFAULT_FILAS <= 2 else ('3F' if self.BLOCK_DEFAULT_FILAS == 3 else '4F')
                bt_half_h = self.BLOCK_HEIGHT[svg_key_snap] / 2
                rail_top = nearest.y - nearest.height / 2
                # El borde superior del BT se alinea con el borde superior del riel
                wy = rail_top + bt_half_h
        except Exception:
            pass

        self._place_block_terminal(wx, wy, self.BLOCK_DEFAULT_FILAS, self.BLOCK_DEFAULT_BORNAS, auto_open=True)

    def _place_block_terminal(self, wx, wy, filas, bornas, label_data=None, auto_open=False):
        """
        Dibuja el bloque y lo registra en app.block_terminals.
        auto_open=True solo al insertar por primera vez (Ctrl+B).
        label_data opcional para restaurar datos tras un redibujado.
        """
        import io

        svg_key  = '2F' if filas <= 2 else ('3F' if filas == 3 else '4F')
        module_w = self.BLOCK_MODULE_W
        module_h = self.BLOCK_HEIGHT[svg_key]
        total_w  = module_w * bornas
        total_h  = module_h
        x0 = wx - total_w / 2
        y0 = wy - total_h / 2

        if not hasattr(self.app, 'block_terminals'):
            self.app.block_terminals = []

        canvas     = self.app.canvas
        canvas_ids = []

        # Rectángulo invisible de hit-testing (debe ser el PRIMERO, debajo de todo)
        # fill='white' + stipple='gray12': visualmente casi invisible pero Tkinter
        # lo considera opaco para hit-testing -> cualquier clic en el área del bloque
        # dispara el tag_bind, sin importar transparencias del SVG ni gaps entre módulos.
        hit_id = canvas.create_rectangle(
            x0, y0, x0 + total_w, y0 + total_h,
            outline='', fill='white', stipple='gray12')
        canvas_ids.append(hit_id)

        # Intentar renderizar el SVG real
        rendered = False
        try:
            import cairosvg
            from PIL import Image, ImageTk
            svg_bytes = self.BLOCK_SVG[svg_key].encode('utf-8')
            png_data  = cairosvg.svg2png(bytestring=svg_bytes,
                                         output_width=round(module_w),
                                         output_height=round(module_h))
            img   = Image.open(io.BytesIO(png_data))
            photo = ImageTk.PhotoImage(img)
            if not hasattr(self.app, '_bt_photo_refs'):
                self.app._bt_photo_refs = []
            for i in range(bornas):
                xi  = x0 + i * module_w
                cid = canvas.create_image(round(xi), round(y0), anchor='nw', image=photo)
                canvas_ids.append(cid)
                self.app._bt_photo_refs.append(photo)
            rendered = True
        except Exception:
            pass

        # Fallback: rectángulos de respaldo
        if not rendered:
            screw_r = module_w * 0.28
            for i in range(bornas):
                xi = x0 + i * module_w
                canvas_ids.append(canvas.create_rectangle(
                    xi, y0, xi + module_w, y0 + total_h,
                    fill='#afc6e9', outline='black', width=1))
                scx = xi + module_w / 2
                for frac, color in [(0.28, '#5599ff'), (0.72, '#eaaff5')]:
                    sy = y0 + total_h * frac
                    canvas_ids.append(canvas.create_oval(
                        scx - screw_r, sy - screw_r,
                        scx + screw_r, sy + screw_r,
                        fill=color, outline='black', width=0.8))

        # Asegurar que division existe en label_data
        ld = label_data.copy() if label_data else {
            'name': '', 'description': '', 'marca': '', 'amperios': '',
            'bt_filas': str(filas), 'bt_bornas': str(bornas),
            'division': 'Sin división'
        }
        if 'division' not in ld:
            ld['division'] = 'Sin división'

        # Dibujar divisiones / separadores
        division_str = ld.get('division', 'Sin división')
        N = 0
        if "2P" in division_str:
            N = 2
        elif "3P" in division_str:
            N = 3
        elif "4P" in division_str:
            N = 4

        if N > 0:
            sep_w = 2.0
            for i in range(bornas):
                if (i + 1) % N == 0 and (i + 1) < bornas:
                    x_div = x0 + (i + 1) * module_w
                    div_id = canvas.create_rectangle(
                        x_div - sep_w/2, y0, x_div + sep_w/2, y0 + total_h,
                        fill='#555555', outline='black', width=0.5
                    )
                    canvas_ids.append(div_id)

        # Asignar tag de grupo único a todos los elementos del bloque
        # Usar tag en lugar de tag_bind individual: así el canvas routing
        # entrega el evento correctamente sin que los bindings globales lo capturen
        bt_tag = f'block_terminal_{id(canvas_ids)}'

        # Borde exterior (usado para resaltar selección)
        # outline='' por defecto: invisible hasta que el usuario seleccione el BT
        border_id = canvas.create_rectangle(
            x0, y0, x0 + total_w, y0 + total_h,
            outline='', width=1.5, fill='', tags=(bt_tag,))
        canvas_ids.append(border_id)

        # Etiqueta superior
        # Color adaptativo para la etiqueta
        IS_DARK = self.app.is_dark_mode() if hasattr(self.app, 'is_dark_mode') else False
        TEXT_COLOR = 'white' if IS_DARK else 'black'

        label_id = canvas.create_text(
            wx, y0 - 10,
            text='BT?', font=('Arial', 8, 'bold'), fill=TEXT_COLOR, anchor='center',
            tags=(bt_tag,))
        canvas_ids.append(label_id)

        # Aplicar el mismo tag a todos los items ya creados
        for cid in canvas_ids:
            try:
                canvas.addtag_withtag(bt_tag, cid)
            except Exception:
                pass

        # Registro del bloque
        bt = {
            'x': wx,       'y': wy,
            'filas': filas, 'bornas': bornas,
            'canvas_ids': canvas_ids,
            'label_id':   label_id,
            'border_id':  border_id,
            'bt_tag':     bt_tag,
            'label_data': ld,
            'svg_key': svg_key,
            'total_w': total_w, 'total_h': total_h,
            'x0': x0, 'y0': y0
        }
        self.app.block_terminals.append(bt)
        self.app._selected_block_terminal = bt

        nombre = bt['label_data'].get('name', '')
        if nombre:
            try:
                canvas.itemconfig(label_id, text=nombre)
            except Exception:
                pass

        # Bindings sobre el TAG del grupo (captura todos los items)
        canvas.tag_bind(bt_tag, '<Button-1>',  lambda e, b=bt: self._on_bt_click(e, b))
        canvas.tag_bind(bt_tag, '<Button-3>',  lambda e, b=bt: self._on_bt_right_click(e, b))
        canvas.tag_bind(bt_tag, '<B1-Motion>', lambda e, b=bt: self._on_bt_drag(e, b))

        if hasattr(self.app, 'set_status') and auto_open:
            self.app.set_status(
                f"✅ Block Terminal: {filas}F × {bornas} bornas  |  "
                "Clic derecho → editar  |  Delete → borrar", "green")
        if auto_open and hasattr(self.app, 'save_undo_checkpoint'):
            self.app.save_undo_checkpoint()

        # Auto-abrir diálogo SOLO en la inserción inicial (no en redibujados)
        if auto_open:
            self.app.canvas.after(50, lambda b=bt: self._open_bt_label_dialog(b))

    # Helpers de selección y arrastre

    def _find_bt_at(self, x, y):
        """Retorna el block terminal que contiene el punto (x, y), o None. (Fix Zoom)"""
        if not hasattr(self.app, 'block_terminals'):
            return None
        for bt in self.app.block_terminals:
            # FIX ZOOM: Usar dimensiones base (mundo) para la detección
            module_w = self.BLOCK_MODULE_W
            svg_key = bt.get('svg_key', '2F' if bt['filas'] <= 2 else ('3F' if bt['filas'] == 3 else '4F'))
            module_h = self.BLOCK_HEIGHT[svg_key]

            tw = module_w * bt['bornas']
            th = module_h

            # Calcular bounds en coordenadas mundo (invariante ante el zoom)
            bx0 = bt['x'] - tw / 2
            by0 = bt['y'] - th / 2

            if bx0 <= x <= bx0 + tw and \
               by0 <= y <= by0 + th:
                return bt
        return None

    def _on_bt_click(self, event, bt):
        """Selecciona el BT al hacer clic izquierdo."""
        self._clear_selection()

        self.app._selected_block_terminal = bt
        # Resaltar borde en azul
        try:
            self.app.canvas.itemconfig(bt['border_id'], outline='#0055ff', width=2.5)
        except Exception:
            pass
        self.app.drag_data["x"] = event.x
        self.app.drag_data["y"] = event.y
        self._bt_drag_last = (event.x, event.y)

    def _on_bt_drag(self, event, bt):
        """Mueve el BT mientras se arrastra (coordenadas de pantalla -> delta)."""
        last = getattr(self, '_bt_drag_last', (event.x, event.y))
        dx_screen = event.x - last[0]
        dy_screen = event.y - last[1]
        self._bt_drag_last = (event.x, event.y)

        # Convertir delta de pantalla a mundo respetando zoom
        try:
            zoom = getattr(self.app.canvas, 'zoom_level', 1.0)
            dx_w = dx_screen / zoom
            dy_w = dy_screen / zoom
        except Exception:
            dx_w, dy_w = dx_screen, dy_screen

        # Movimiento horizontal si BT está pegado al riel DIN
        if bt.get('snapped_to_rail'):
            # Solo permitir movimiento horizontal
            dy_w = 0

            # DETECTAR DESACOPLE: Si se desliza fuera de los límites del riel
            if dx_w != 0 and hasattr(self.app, 'shape_manager'):
                rail_id = bt.get('snapped_rail_id')
                for rail in getattr(self.app.shape_manager, 'shapes', []):
                    if id(rail) == rail_id:
                        # Bounding box del riel
                        rail_x_min = rail.x - rail.width / 2
                        rail_x_max = rail.x + rail.width / 2
                        # Bounding box del BT (usar x0, total_w)
                        bt_x_min = bt['x0'] + dx_w
                        bt_x_max = bt_x_min + bt['total_w']

                        # Si el BT se salió del riel en X, despegarlo
                        if bt_x_min < rail_x_min or bt_x_max > rail_x_max:
                            bt['snapped_to_rail'] = False
                            if 'snapped_rail_id' in bt:
                                del bt['snapped_rail_id']
                            if hasattr(self.app, 'set_status'):
                                self.app.set_status("📌 Block Terminal despegado del riel DIN", "blue")
                        break

        # Mover todos los items del grupo usando el tag — un solo call
        try:
            self.app.canvas.move(bt['bt_tag'], dx_w, dy_w)
        except Exception:
            for cid in bt['canvas_ids']:
                try:
                    self.app.canvas.move(cid, dx_w, dy_w)
                except Exception:
                    pass

        bt['x']  += dx_w;  bt['y']  += dy_w
        bt['x0'] += dx_w;  bt['y0'] += dy_w

    def _on_bt_right_click(self, event, bt):
        """Clic derecho: selecciona y abre directamente el diálogo de etiqueta."""
        self.app.canvas.focus_set()
        self.app.canvas.update_idletasks()
        self._on_bt_click(event, bt)
        self._open_bt_label_dialog(bt)

    def _open_bt_label_dialog(self, bt):
        """Diálogo de etiqueta del Block Terminal — delegado a ui.label_editors"""
        from ui.label_editors import BlockTerminalLabelEditor
        BlockTerminalLabelEditor(self.app, bt)

    # Eliminación

    def _delete_bt_canvas_ids(self, bt):
        """Borra del canvas todos los primitivos del BT."""
        for cid in bt.get('canvas_ids', []):
            try:
                self.app.canvas.delete(cid)
            except Exception:
                pass
        bt['canvas_ids'] = []

    def _delete_bt(self, bt):
        """Elimina completamente un BT del canvas y de la lista."""
        self._delete_bt_canvas_ids(bt)
        if hasattr(self.app, 'block_terminals') and bt in self.app.block_terminals:
            self.app.block_terminals.remove(bt)
        if getattr(self.app, '_selected_block_terminal', None) is bt:
            self.app._selected_block_terminal = None
        if hasattr(self.app, 'save_undo_checkpoint'):
            self.app.save_undo_checkpoint()

    def _redraw_block_terminals_after_zoom(self):
        """
        Redibuja todos los Block Terminals aplicando el zoom actual.
        Necesario porque canvas.create_image() no escala con canvas.scale(),
        a diferencia de rectángulos y líneas normales.
        """
        if not hasattr(self.app, 'block_terminals') or not self.app.block_terminals:
            return

        zoom = getattr(self.app.canvas, 'zoom_level', 1.0)

        import io
        try:
            import cairosvg
            from PIL import Image, ImageTk
            has_cairo = True
        except Exception:
            has_cairo = False

        # Limpiar referencias de imágenes anteriores para este redibujado
        if hasattr(self.app, '_bt_photo_refs'):
            self.app._bt_photo_refs = []

        for bt in self.app.block_terminals:
            # 1. Borrar primitivos anteriores del canvas
            self._delete_bt_canvas_ids(bt)

            filas  = bt['filas']
            bornas = bt['bornas']
            wx, wy = bt['x'], bt['y']

            svg_key  = bt.get('svg_key', '2F' if filas <= 2 else ('3F' if filas == 3 else '4F'))
            module_w = self.BLOCK_MODULE_W * zoom
            module_h = self.BLOCK_HEIGHT[svg_key] * zoom
            total_w  = module_w * bornas
            total_h  = module_h

            # Las coordenadas wx/wy están en espacio-mundo; el canvas ya tiene zoom
            # aplicado internamente, así que dibujamos en coordenadas mundo × zoom
            x0 = wx * zoom - total_w / 2
            y0 = wy * zoom - total_h / 2

            canvas     = self.app.canvas
            canvas_ids = []
            rendered   = False

            # 2. Intentar renderizar SVG al tamaño con zoom
            if has_cairo:
                try:
                    svg_bytes = self.BLOCK_SVG[svg_key].encode('utf-8')
                    png_data  = cairosvg.svg2png(
                        bytestring=svg_bytes,
                        output_width=round(module_w),
                        output_height=round(module_h)
                    )
                    img   = Image.open(io.BytesIO(png_data))
                    photo = ImageTk.PhotoImage(img)
                    if not hasattr(self.app, '_bt_photo_refs'):
                        self.app._bt_photo_refs = []
                    for i in range(bornas):
                        xi  = x0 + i * module_w
                        cid = canvas.create_image(round(xi), round(y0), anchor='nw', image=photo)
                        canvas_ids.append(cid)
                        self.app._bt_photo_refs.append(photo)
                    rendered = True
                except Exception:
                    pass

            # 3. Fallback: rectángulos escalados
            if not rendered:
                screw_r = module_w * 0.28
                for i in range(bornas):
                    xi = x0 + i * module_w
                    canvas_ids.append(canvas.create_rectangle(
                        xi, y0, xi + module_w, y0 + total_h,
                        fill='#afc6e9', outline='black', width=1))
                    scx = xi + module_w / 2
                    for frac, color in [(0.28, '#5599ff'), (0.72, '#eaaff5')]:
                        sy = y0 + total_h * frac
                        canvas_ids.append(canvas.create_oval(
                            scx - screw_r, sy - screw_r,
                            scx + screw_r, sy + screw_r,
                            fill=color, outline='black', width=0.8))

            # 3.5 Dibujar divisiones / separadores con zoom
            ld = bt.get('label_data', {})
            division_str = ld.get('division', 'Sin división')
            N = 0
            if "2P" in division_str:
                N = 2
            elif "3P" in division_str:
                N = 3
            elif "4P" in division_str:
                N = 4

            if N > 0:
                sep_w = 2.0 * zoom
                for i in range(bornas):
                    if (i + 1) % N == 0 and (i + 1) < bornas:
                        x_div = x0 + (i + 1) * module_w
                        div_id = canvas.create_rectangle(
                            x_div - sep_w/2, y0, x_div + sep_w/2, y0 + total_h,
                            fill='#555555', outline='black', width=0.5
                        )
                        canvas_ids.append(div_id)

            # 4. Borde exterior (invisible por defecto, visible al seleccionar)
            bt_tag = bt['bt_tag']
            border_id = canvas.create_rectangle(
                x0, y0, x0 + total_w, y0 + total_h,
                outline='', width=1.5, fill='', tags=(bt_tag,))
            canvas_ids.append(border_id)

            # 5. Etiqueta superior
            nombre = bt['label_data'].get('name', 'BT?') or 'BT?'
            font_size = max(6, int(8 * zoom))
            # Color adaptativo para el redibujado tras zoom
            IS_DARK = self.app.is_dark_mode() if hasattr(self.app, 'is_dark_mode') else False
            TEXT_COLOR_ZOOM = 'white' if IS_DARK else 'black'

            label_id = canvas.create_text(
                wx * zoom, y0 - 10 * zoom,
                text=nombre,
                font=('Arial', font_size, 'bold'),
                fill=TEXT_COLOR_ZOOM, anchor='center',
                tags=(bt_tag,))
            canvas_ids.append(label_id)

            # 6. Aplicar tag y re-registrar bindings
            for cid in canvas_ids:
                try:
                    canvas.addtag_withtag(bt_tag, cid)
                except Exception:
                    pass

            canvas.tag_bind(bt_tag, '<Button-1>',  lambda e, b=bt: self._on_bt_click(e, b))
            canvas.tag_bind(bt_tag, '<Button-3>',  lambda e, b=bt: self._on_bt_right_click(e, b))
            canvas.tag_bind(bt_tag, '<B1-Motion>', lambda e, b=bt: self._on_bt_drag(e, b))

            # 7. Actualizar referencias en el dict del bt
            bt['canvas_ids'] = canvas_ids
            bt['label_id']   = label_id
            bt['border_id']  = border_id
            bt['total_w']    = total_w
            bt['total_h']    = total_h
            bt['x0']         = x0
            bt['y0']         = y0

    def on_delete_key(self):
        """
        Maneja la tecla Delete para eliminar elementos seleccionados.
        Soporta selección individual, múltiple y líneas.

        Hacer clic sobre un punto de conexión huérfano (el que queda al borrar
        una línea de conexión) lo selecciona; presionar Delete lo elimina.
        """
        self.app.save_undo_checkpoint()
        deleted_count = 0

        # PRIORIDAD: Borrar etiqueta de numeración seleccionada (Delete)
        if getattr(self.app, '_selected_wire_label_conn', None) is not None:
            self._delete_selected_wire_label()
            return  # No procesar más elementos

        # PRIORIDAD: Borrar punto de conexión seleccionado (Delete)
        # El punto se selecciona haciendo clic sobre su halo verde (huérfano).
        sel_point = getattr(self.app, '_selected_connection_point', None)
        if sel_point is not None:
            comp_punto, idx_punto = sel_point
            deleted = False
            if hasattr(self.app, '_delete_connection_point'):
                deleted = self.app._delete_connection_point(comp_punto, idx_punto)
            # Limpiar resaltados visuales SIN flush síncrono del canvas
            # (el repintado lo hace Tk en el idle; un update() aquí fuerza un
            # render completo del lienzo y produce el "lag" al borrar en serie).
            if hasattr(self.app, 'clear_selected_connection_point'):
                self.app.clear_selected_connection_point()
            if hasattr(self.app, 'clear_connection_point_highlights'):
                self.app.clear_connection_point_highlights()
            # Si la selección del punto abrió un modo en la app, cancelarlo
            if hasattr(self.app, 'connection_mode'):
                self.app.connection_mode = False
            if hasattr(self.app, 'connection_start'):
                self.app.connection_start = None
            self.app.canvas.config(cursor="")
            if deleted:
                if hasattr(self.app, 'set_status'):
                    self.app.set_status("🗑️ Punto de conexión eliminado", "blue")
            else:
                if hasattr(self.app, 'set_status'):
                    self.app.set_status("⚠️ El punto no se puede borrar (está conectado a una línea)", "orange")
            return  # No procesar más elementos

        # PRIORIDAD: Eliminar Block Terminal seleccionado
        selected_bt = getattr(self.app, '_selected_block_terminal', None)
        if selected_bt is not None:
            self._delete_bt(selected_bt)
            if hasattr(self.app, 'set_status'):
                self.app.set_status("🗑️ Block Terminal eliminado", "orange")
            return  # No procesar más elementos

        # Eliminar línea/conexión seleccionada
        if hasattr(self.app, 'selected_connection') and self.app.selected_connection:
            connection_to_delete = self.app.selected_connection

            try:
                for line_id in connection_to_delete.line_ids:
                    self.app.canvas.delete(line_id)

                if connection_to_delete in self.app.connections:
                    self.app.connections.remove(connection_to_delete)

                # Limpiar selección de línea
                self.app.selected_connection = None
                if hasattr(self.app, 'selected_segment'):
                    self.app.selected_segment = None
                self.app.locked_segment = False

                # Limpiar resaltados
                if hasattr(self.app, 'clear_connection_highlights'):
                    self.app.clear_connection_highlights()

                # Refrescar estado de los puntos de conexión de los extremos:
                # los que quedaron sin ninguna conexión pasan a estar disponibles.
                if hasattr(self.app, '_refresh_component_point_connected'):
                    self.app._refresh_component_point_connected(connection_to_delete.start_component)
                    self.app._refresh_component_point_connected(connection_to_delete.end_component)

                self.app.force_canvas_refresh()
                self.app.set_status("🗑️ Conexión eliminada", "blue")
                return

            except Exception as e:

                pass
        # Eliminar shape seleccionada (si la hay)
        if hasattr(self.app, 'shape_manager') and getattr(self.app.shape_manager, 'selected_shape', None):
            try:
                sel_shape = self.app.shape_manager.selected_shape

                # BLOQUEO: Prevenir eliminación de estructuras de gabinete (Puerta, Tablero, etc.)
                if hasattr(sel_shape, 'metadata') and sel_shape.metadata:
                    shape_type = sel_shape.metadata.get('type', '')
                    if 'cabinet' in shape_type:
                        if hasattr(self.app, 'set_status'):
                            self.app.set_status("⚠️ No puedes eliminar la estructura base del gabinete", "orange")
                        return # Terminar sin borrar
                if hasattr(sel_shape, 'canvas_id') and sel_shape.canvas_id:
                    try:
                        self.app.canvas.delete(sel_shape.canvas_id)
                    except Exception:
                        pass
                # Limpiar inner_ids si es una forma con elementos internos (DinRail)
                if hasattr(sel_shape, 'inner_ids') and sel_shape.inner_ids:
                    try:
                        for inner_id in sel_shape.inner_ids:
                            try:
                                self.app.canvas.delete(inner_id)
                            except Exception:
                                pass
                        sel_shape.inner_ids.clear()
                    except Exception:
                        pass

                # Limpiar textos asociados al shape
                texts_to_remove = []
                if hasattr(self.app, 'text_components'):
                    try:
                        for text_comp in self.app.text_components:
                            # Verificar si el texto está asociado a este shape (proximidad)
                            if hasattr(sel_shape, 'x') and hasattr(text_comp, 'x'):
                                if hasattr(sel_shape, 'y') and hasattr(text_comp, 'y'):
                                    distance = ((sel_shape.x - text_comp.x)**2 + (sel_shape.y - text_comp.y)**2)**0.5
                                    if distance < 100:  # Umbral de 100 píxeles
                                        texts_to_remove.append(text_comp)
                    except Exception:
                        pass

                for text_comp in texts_to_remove:
                    try:
                        if hasattr(text_comp, 'delete'):
                            text_comp.delete()
                        if hasattr(self.app, 'text_components') and text_comp in self.app.text_components:
                            self.app.text_components.remove(text_comp)
                    except Exception:
                        pass

                # Liberar shapes pegados si se borra un riel DIN
                if hasattr(sel_shape, 'shape_type') and sel_shape.shape_type == 'din_rail':
                    # Buscar todos los shapes pegados a este riel y liberarlos
                    if hasattr(self.app, 'shape_manager') and hasattr(self.app.shape_manager, 'shapes'):
                        for shape in self.app.shape_manager.shapes:
                            if (hasattr(shape, 'metadata') and
                                shape.metadata.get('snapped_to_rail') and
                                shape.metadata.get('snapped_rail_id') == id(sel_shape)):
                                # Liberar el shape removiendo propiedades de snap
                                shape.metadata['snapped_to_rail'] = False
                                if 'snapped_rail_id' in shape.metadata:
                                    del shape.metadata['snapped_rail_id']

                try:
                    self.app.shape_manager.remove_shape(sel_shape)
                except Exception:
                    pass

                # Limpiar selección y estado
                try:
                    self.app.shape_manager.selected_shape = None
                except Exception:
                    pass

                if hasattr(self.app, 'set_status'):
                    try:
                        self.app.set_status("🗑️ Forma eliminada", "blue")
                    except Exception:
                        pass

                # Forzar refresh visual
                try:
                    self.app.force_canvas_refresh()
                except Exception:
                    pass

                return
            except Exception:
                pass

        if hasattr(self.app, 'shielding_manager') and self.app.shielding_manager.selected_shielding:
            try:
                self.app.shielding_manager.remove_shielding(self.app.shielding_manager.selected_shielding)
                if hasattr(self.app, 'set_status'):
                    self.app.set_status("🗑️ Apantallamiento eliminado", "blue")
                self.app.force_canvas_refresh()
                return
            except Exception:
                pass

        # Eliminar selección múltiple (1 o más elementos)
        elif hasattr(self.app, 'selected_elements') and len(self.app.selected_elements) >= 1:
            # Limpiar TODOS los círculos de selección ANTES de eliminar
            self.app.canvas.delete("selection_circle")
            self.app.canvas.delete("selection_indicator")

            elements_to_delete = self.app.selected_elements.copy()

            for element in elements_to_delete:
                try:
                    # Limpiar círculo de selección individual del componente
                    if hasattr(element, 'selection_id') and element.selection_id:
                        try:
                            self.app.canvas.delete(element.selection_id)
                            element.selection_id = None
                        except Exception:
                            pass

                    connections_to_remove = []
                    for conn in self.app.connections:
                        if (conn.start_component == element or
                            conn.end_component == element):
                            connections_to_remove.append(conn)

                    for conn in connections_to_remove:
                        for item in conn.line_ids:
                            self.app.canvas.delete(item)
                        self.app.connections.remove(conn)

                    if hasattr(element, 'delete'):
                        element.delete()

                    # Manejar shapes (Circle, Rect, Square, DinRail, etc.)
                    if hasattr(element, 'shape_type'):
                        if hasattr(element, 'canvas_id') and element.canvas_id:
                            try:
                                self.app.canvas.delete(element.canvas_id)
                            except Exception:
                                pass
                        if hasattr(self.app, 'shape_manager') and hasattr(self.app.shape_manager, 'shapes'):
                            if element in self.app.shape_manager.shapes:
                                self.app.shape_manager.shapes.remove(element)
                                if self.app.shape_manager.selected_shape == element:
                                    self.app.shape_manager.selected_shape = None

                    # Limpiar textos asociados a componentes o shapes
                    texts_to_remove = []
                    if hasattr(self.app, 'text_components'):
                        if hasattr(element, 'x') and hasattr(element, 'y'):
                            for text_comp in self.app.text_components:
                                if hasattr(text_comp, 'x') and hasattr(text_comp, 'y'):
                                    distance = ((element.x - text_comp.x)**2 + (element.y - text_comp.y)**2)**0.5
                                    if distance < 100:  # Umbral de 100 píxeles
                                        texts_to_remove.append(text_comp)

                    for text_comp in texts_to_remove:
                        try:
                            if hasattr(text_comp, 'delete'):
                                text_comp.delete()
                            if text_comp in self.app.text_components:
                                self.app.text_components.remove(text_comp)
                        except Exception:
                            pass

                    # Limpiar inner_ids si es un shape con elementos internos (DinRail)
                    if hasattr(element, 'inner_ids') and element.inner_ids:
                        try:
                            for inner_id in element.inner_ids:
                                try:
                                    self.app.canvas.delete(inner_id)
                                except Exception:
                                    pass
                            element.inner_ids.clear()
                        except Exception:
                            pass

                    # Manejar eliminación según tipo de componente
                    if hasattr(self.app, 'text_components') and element in self.app.text_components:
                        # Es un componente de texto
                        if element in self.app.text_components:
                            self.app.text_components.remove(element)

                    elif element in self.app.components:
                        self.app.components.remove(element)

                    deleted_count += 1

                except Exception as e:

                    pass
            # Limpiar selección múltiple
            self.app.selected_elements.clear()
            self.app.selected_component = None

            # MEJORA: Limpiar indicadores visuales explícitamente
            # Limpiar todos los indicadores de selección múltiple
            if hasattr(self.app, 'clear_selection_indicators'):
                self.app.clear_selection_indicators()
            if hasattr(self.app, 'update_selection_indicators'):
                self.app.update_selection_indicators()

            # Redibujar todo después de eliminación múltiple
            if hasattr(self.app, 'redraw_components'):
                self.app.redraw_components()
            self.app.force_canvas_refresh()

        # Eliminar componente de texto seleccionado
        elif (hasattr(self.app, 'selected_component') and self.app.selected_component and
              hasattr(self.app, 'text_components') and self.app.selected_component in self.app.text_components):
            text_component = self.app.selected_component
            text_name = getattr(text_component, 'text', 'Texto')

            try:
                if hasattr(text_component, 'canvas_id'):
                    self.app.canvas.delete(text_component.canvas_id)
                if hasattr(text_component, 'delete'):
                    text_component.delete()

                # Remover de la lista de componentes de texto
                self.app.text_components.remove(text_component)

                # Limpiar selección
                self.app.selected_component = None

                if hasattr(self.app, 'update_selection_indicators'):
                    self.app.update_selection_indicators()

                self.app.force_canvas_refresh()
                return

            except Exception as e:

                pass
        # FUNCIONALIDAD ORIGINAL: Eliminar selección individual
        elif self.app.selected_component:
            # Confirmar eliminación para componentes importantes
            component_name = self.app.selected_component.name

            # Limpiar círculo de selección ANTES de eliminar el componente
            if hasattr(self.app.selected_component, 'selection_id') and self.app.selected_component.selection_id:
                try:
                    self.app.canvas.delete(self.app.selected_component.selection_id)
                    self.app.selected_component.selection_id = None
                except Exception:
                    pass

            # Limpiar todos los indicadores de selección del canvas
            self.app.canvas.delete("selection_circle")
            self.app.canvas.delete("selection_indicator")

            connections_to_remove = []
            for conn in self.app.connections:
                if (conn.start_component == self.app.selected_component or
                    conn.end_component == self.app.selected_component):
                    connections_to_remove.append(conn)

            for conn in connections_to_remove:
                for item in conn.line_ids:
                    self.app.canvas.delete(item)
                self.app.connections.remove(conn)

            self.app.selected_component.delete()
            self.app.components.remove(self.app.selected_component)
            self.app.selected_component = None

            self.app.force_canvas_refresh()

        else:
            pass

    def _clear_selection(self):
        """Limpia todas las selecciones actuales (componentes, hilos, formas, etc.)"""
        # 1. Componentes individuales
        if self.app.selected_component:
            self.app.selected_component.selected = False
            self.app.selected_component = None

        # 2. Selección múltiple
        if hasattr(self.app, 'selected_elements'):
            for elem in self.app.selected_elements:
                if hasattr(elem, 'selected'):
                    elem.selected = False
            self.app.selected_elements.clear()

        if hasattr(self.app, 'shape_manager') and self.app.shape_manager:
            try:
                self.app.shape_manager.clear_selection()
            except Exception as e:
                print(f"⚠️ Error limpiando selección de formas: {e}")

        if getattr(self.app, '_selected_block_terminal', None) is not None:
            try:
                bt = self.app._selected_block_terminal
                self.app.canvas.itemconfig(bt['border_id'], outline='', width=1.5)
            except Exception:
                pass
            self.app._selected_block_terminal = None

        # 5. Apantallamientos
        if hasattr(self.app, 'shielding_manager'):
            try:
                self.app.shielding_manager.select_shielding(None)
            except Exception:
                pass

        # 6. Conexiones/Líneas
        if hasattr(self.app, 'selected_connection'):
            self.app.selected_connection = None
        if hasattr(self.app, 'selected_segment'):
            self.app.selected_segment = None
        if hasattr(self.app, 'clear_connection_highlights'):
            self.app.clear_connection_highlights()

        # 7. Punto de conexión seleccionado (para borrar con <delete>)
        if hasattr(self.app, 'clear_selected_connection_point'):
            self.app.clear_selected_connection_point()

    def _clear_selection_unless_click_inside_selected(self, x=None, y=None):
        """Limpia la selección a menos que el punto (x,y) esté dentro
        de alguno de los elementos actualmente seleccionados.
        Si x/y son None, se comporta como _clear_selection normal.
        """
        # Si no se pasan coordenadas, limpiar como siempre
        if x is None or y is None:
            return self._clear_selection()

        # Si hay selección múltiple, comprobar si el click ocurrió sobre alguno
        try:
            if hasattr(self.app, 'selected_elements') and self.app.selected_elements:
                for el in self.app.selected_elements:
                    try:
                        if hasattr(el, 'contains_point') and el.contains_point(x, y):
                            # Click dentro de un elemento seleccionado: NO limpiar
                            return
                        # Fallback simple para shapes con posición/size
                        if hasattr(el, 'x') and hasattr(el, 'y'):
                            ex = getattr(el, 'x')
                            ey = getattr(el, 'y')
                            # usar bounding heurístico si hay width/height/radius
                            w = getattr(el, 'width', None) or getattr(el, 'side_length', None)
                            h = getattr(el, 'height', None) or getattr(el, 'side_length', None)
                            r = getattr(el, 'radius', None)
                            if r is not None:
                                if (x - ex) ** 2 + (y - ey) ** 2 <= (r ** 2):
                                    return
                            if w is not None and h is not None:
                                if ex - w/2 <= x <= ex + w/2 and ey - h/2 <= y <= ey + h/2:
                                    return
                    except Exception:
                        continue
        except Exception:
            pass

        # Si no se detectó click dentro de selección, limpiar normalmente
        return self._clear_selection()

    def _toggle_shape_in_multi_selection(self, shape):
        """Alterna un shape dentro de la selección múltiple (Ctrl+Click).

        Los dispositivos de las hojas 'Hoja de Gabinete 2D' y 'Tapa' se guardan
        como shapes (metadata 'component', 'door_component', 'relay_socket') y no
        como componentes eléctricos, por lo que no pasan por el manejador de
        Ctrl+Click de app.components.  Esta rutina reproduce esa misma semántica
        usando app.selected_elements, que el arrastre en grupo ya soporta porque
        todos los shapes implementan contains_point()/move()/selected.

        Los shapes fijos (tablero/tapa/medidas) nunca entran en la selección.
        """
        if shape is None:
            return False

        # No seleccionar estructura fija del gabinete (tablero, tapa, medidas)
        meta = getattr(shape, 'metadata', {}) or {}
        if meta.get('locked') or meta.get('type') == 'cabinet_background':
            return False

        if not hasattr(self.app, 'selected_elements'):
            return False

        selected_elements = self.app.selected_elements

        # La forma suelta no debe coexistir con un grupo: el primer elemento
        # del grupo transfiere la selección individual al conjunto.
        if shape in selected_elements:
            selected_elements.remove(shape)
            self._set_shape_selected_flag(shape, False)
            accion = f"Elemento quitado de la selección ({len(selected_elements)} restantes)"
        else:
            # Al crear el grupo, la selección individual de shape se transfiere
            # al grupo para que el arrastre mueva todo junto.
            loose = self.app.get_selected_shape()
            if loose is not None and loose is not shape and loose not in selected_elements:
                if not (getattr(loose, 'metadata', {}) or {}).get('locked') and \
                   (getattr(loose, 'metadata', {}) or {}).get('type') != 'cabinet_background':
                    selected_elements.append(loose)
                    self._set_shape_selected_flag(loose, True)
            try:
                self.app.shape_manager.selected_shape = None
            except Exception:
                pass

            selected_elements.append(shape)
            self._set_shape_selected_flag(shape, True)
            accion = f"📥 Elemento añadido a la selección ({len(selected_elements)} totales)"

        # Congelar el grupo como objetivo de arrastre para que el clic no mute
        # la selección mientras se mueve.
        try:
            self.app._group_drag_targets = list(selected_elements)
        except Exception:
            self.app._group_drag_targets = None

        # Pintar el estado visual de cada miembro del grupo
        self.app.canvas.delete("selection_indicator")
        if hasattr(self.app, 'redraw_all_shapes'):
            self.app.redraw_all_shapes()

        if hasattr(self.app, 'set_status'):
            self.app.set_status(accion, "blue")

        return True

    def _set_shape_selected_flag(self, shape, selected):
        """Marca visualmente un shape como seleccionado usando el editor de shapes."""
        try:
            editor = getattr(self.app.shape_manager, 'editor', None)
            if editor:
                editor._update_shape_color(shape, selected)
            else:
                shape.selected = selected
        except Exception:
            try:
                shape.selected = selected
            except Exception:
                pass

    def on_escape_key(self):
        """
        Maneja la tecla Escape según especificación: DESELECCIONAR
        """
        # Cancelar interacción con etiqueta de numeración (deseleccionar)
        if getattr(self.app, '_dragging_wire_label', False):
            self.app._dragging_wire_label = False
            self.app._dragging_wire_label_conn = None
        if getattr(self.app, '_selected_wire_label_conn', None) is not None:
            self.app._selected_wire_label_conn = None

        # Despegar shape del riel DIN
        selected_shape = self.app.get_selected_shape()
        if selected_shape and hasattr(selected_shape, 'metadata') and selected_shape.metadata.get('snapped_to_rail'):
            # Remover las propiedades de snap
            selected_shape.metadata['snapped_to_rail'] = False
            if 'snapped_rail_id' in selected_shape.metadata:
                del selected_shape.metadata['snapped_rail_id']
            if hasattr(self.app, 'set_status'):
                self.app.set_status("📌 Shape despegado del riel DIN", "blue")
            return  # Salir tras despegarelse

        #  AGREGAR ESTE BLOQUE AL INICIO:
        # PRIORIDAD 0: CANCELAR DIBUJO DE SHAPES
        if self.shape_drawing.shape_type or self.shape_drawing.is_drawing:
            self.shape_drawing.cancel()
            self.app.set_status("🛑 Dibujo de forma cancelado", "blue")
            return  # Terminar aquí

        # Cancelar Apantallamiento o Deseleccionar
        if hasattr(self.app, 'shielding_manager'):
            if self.app.shielding_manager.active_preview:
                self.app.shielding_manager.clear_preview()
                # Usar _toggle_shielding_mode para que el botón se ponga OFF visualmente
                if hasattr(self.app, 'shielding_mode_enabled') and self.app.shielding_mode_enabled.get():
                    if hasattr(self.app, '_toggle_shielding_mode'):
                        self.app._toggle_shielding_mode()
                    else:
                        self.app.shielding_mode_enabled.set(False)
                        self.app.canvas.config(cursor="")
                return
            # Si el modo está activo sin preview, ESC también desactiva el botón
            elif getattr(self.app, 'shielding_mode_enabled', None) and self.app.shielding_mode_enabled.get():
                if hasattr(self.app, '_toggle_shielding_mode'):
                    self.app._toggle_shielding_mode()
                if hasattr(self.app, 'shielding_drag_start'):
                    self.app.shielding_drag_start = None
                return
            elif self.app.shielding_manager.selected_shielding:
                self.app.shielding_manager.select_shielding(None)
                self.app.set_status("Deseleccionado", "black")
                return

        # 0. PRIORIDAD MÁXIMA: Cancelar manual routing si está activo
        try:
            from core.unified_line_system import get_manhattan_router
            manual_router = get_manhattan_router(self.app)

            if manual_router.manual_active:
                manual_router.cancel_manual_routing()
                # Asegurar que el botón 8 se desactive visualmente
                if hasattr(self.app, '_check_and_deactivate_button8'):
                    self.app._check_and_deactivate_button8()
                self.app.set_status("🛑 Ruteo manual cancelado", "blue")
                return  # Terminar aquí - ESC cancela manual routing
            else:
                # Si el manual routing no está activo pero el botón 8 sí, desactivarlo
                if hasattr(self.app, '_check_and_deactivate_button8'):
                    self.app._check_and_deactivate_button8()
        except Exception as e:
            pass

        # 1. Cancelar clonado de fase si está activo
        if (hasattr(self.app, 'fase_cloning_active') and self.app.fase_cloning_active):
            self._cancel_fase_cloning()
            return

        # 2. Cancelar preview de componente si está activo
        if self.app.component_preview_mode:
            if hasattr(self.app, 'cancelar_preview_componente'):
                self.app.cancelar_preview_componente()
                self.app.set_status("🛑 Colocación de componente cancelada", "blue")
            else:
                self.app.component_preview_mode = False
                self.app.current_component = None

        # DESACTIVAR MODO DE INSERCIÓN DE PUNTOS SI ESTÁ ACTIVO
        elif hasattr(self.app, 'is_insert_point_mode') and self.app.is_insert_point_mode:
            self.app.is_insert_point_mode = False
            self.app.canvas.config(cursor="arrow")
            if hasattr(self.app, 'set_status'):
                self.app.set_status("📍 Modo insertar punto DESACTIVADO", "black")
            # DESACTIVAR BOTÓN 4 (GRIS CUANDO INACTIVO)
            if hasattr(self.app, '_deactivate_button'):
                self.app._deactivate_button("button4")

        # 2. Deseleccionar línea si está seleccionada
        elif hasattr(self.app, 'selected_connection') and self.app.selected_connection:
            self.app.canvas.config(cursor="")  # Restaurar cursor normal
            self.app.selected_connection = None
            if hasattr(self.app, 'selected_segment'):
                self.app.selected_segment = None
            if hasattr(self.app, 'clear_connection_highlights'):
                self.app.clear_connection_highlights()

        # 3. Cancelar modo conexión si está activo
        elif hasattr(self.app, 'connection_mode') and self.app.connection_mode:
            self.app.connection_mode = False
            self.app.connection_start = None
            # Limpiar también el punto de conexión que pudiera haberse seleccionado
            if hasattr(self.app, 'clear_selected_connection_point'):
                self.app.clear_selected_connection_point()
            if hasattr(self.app, 'set_status'):
                self.app.set_status("Modo conexión cancelado", "black")

        # 4. DESELECCIONAR: Limpiar todas las selecciones
        else:
            self._clear_selection()
            if hasattr(self.app, 'set_status'):
                self.app.set_status("Deseleccionado", "black")
            # MEDIDA DE SEGURIDAD: Desactivar botón 8 si es necesario
            if hasattr(self.app, '_check_and_deactivate_button8'):
                self.app._check_and_deactivate_button8()

    def _run_coordinated_eventhandler_preview(self, x, y):
        """
        Ejecuta solo el preview de EventHandler cuando no hay otros sistemas activos.

        Esto coordina todos los sistemas de preview para evitar conflictos.
        """
        # Detección de puntos de contacto para crosshair Y SNAP AUTOMÁTICO
        # Buscar componentes cercanos al cursor para cambiar cursor y hacer snap
        near_connection_point = False
        closest_point = None
        closest_distance_sq = float('inf')
        click_threshold = 8     # Radio exacto del círculo amarillo para click funcional

        # DOS NIVELES DE TOLERANCIA (al cuadrado para evitar sqrt en el bucle)
        visual_threshold_sq = 15 * 15
        click_threshold_sq = click_threshold * click_threshold
        margin = 20  # Margen de seguridad para el rechazo por caja delimitadora

        # MODIFICADO: Compensar pan offset en la conversión de coordenadas
        x_comp = x
        y_comp = y

        for comp in self.app.components:
            # Rechazo rápido por caja delimitadora ANTES de
            # recorrer los puntos (mismo criterio que on_mouse_motion)
            if not (comp.x - margin <= x_comp <= comp.x + comp.size[0] + margin and
                    comp.y - margin <= y_comp <= comp.y + comp.size[1] + margin):
                continue

            for i, (global_x, global_y, point) in enumerate(comp.get_connection_points_global()):
                # Verificar distancia al punto (al cuadrado; sqrt solo si gana)
                distance_sq = (x_comp - global_x) ** 2 + (y_comp - global_y) ** 2

                # DETECCIÓN DE PROXIMIDAD PARA FEEDBACK VISUAL
                if distance_sq <= visual_threshold_sq:
                    near_connection_point = True
                    if distance_sq < closest_distance_sq:
                        closest_distance_sq = distance_sq
                        closest_point = {
                            'component': comp,
                            'point_idx': i,
                            'canvas_x': global_x,
                            'canvas_y': global_y,
                            'distance': distance_sq ** 0.5 if distance_sq <= click_threshold_sq else 15,
                            'within_click_area': distance_sq <= click_threshold_sq # NUEVA PROPIEDAD
                        }

        # SNAP AUTOMÁTICO CON FEEDBACK PRECISO
        if near_connection_point and closest_point:
            self._set_canvas_cursor("crosshair")

            # SNAP AUTOMÁTICO: Activar modo de conexión si no está activo
            if not hasattr(self.app, 'connection_mode'):
                self.app.connection_mode = False
            if not hasattr(self.app, 'connection_start'):
                self.app.connection_start = None

            if hasattr(self.app, 'status_label'):
                comp_name = closest_point['component'].name

                if closest_point['within_click_area']:  # Dentro del área de click
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status(f"🎯 ÁREA DE CLICK: {comp_name} - Click aquí para conectar", "lime", duration=1000)

                    # SNAP VISUAL: Resaltar SOLO cuando está en área de click
                    if hasattr(self.app, 'highlight_connection_point'):
                        self.app.highlight_connection_point(
                            closest_point['component'],
                            closest_point['point_idx']
                        )
                else:  # Cerca pero fuera del área de click
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status(f"📍 Punto cercano: {comp_name} - Acérquese más para conectar", "orange", duration=1000)

                    # NO mostrar círculo amarillo cuando está fuera del área de click
                    if hasattr(self.app, 'clear_connection_point_highlights'):
                        self.app.clear_connection_point_highlights()

        else:
            # Restaurar cursor normal cuando no está cerca de puntos de conexión
            if not (hasattr(self.app, 'selected_connection') and self.app.selected_connection):
                self._set_canvas_cursor("")

            # Limpiar información de status
            if hasattr(self.app, 'set_status'):
                if not hasattr(self.app, 'connection_mode') or not self.app.connection_mode:
                    # No hacemos nada, el temporizador de set_status lo reseteará a "Listo"
                    pass

            # Limpiar resaltado de puntos
            if hasattr(self.app, 'clear_connection_point_highlights'):
                self.app.clear_connection_point_highlights()

        # FUNCIONALIDAD ORIGINAL SIN CAMBIOS
        if self.app.highlighted_component:
            self.app.highlighted_component.highlighted = False
            self.app.highlighted_component = None

        # MODIFICADO: Compensar pan offset para highlight
        x_comp = x
        y_comp = y

        for comp in self.app.components:
            if comp.contains_point(x_comp, y_comp):
                comp.highlighted = True
                self.app.highlighted_component = comp
                break

    def _handle_manual_routing_preview(self, x, y):
        """
        Maneja el preview en tiempo real del manual routing.

        Args:
            x, y: Coordenadas del mouse (pantalla)
        """
        try:
            from core.unified_line_system import get_manhattan_router
            from utils.coordinates import event_to_canvas_coords
            manual_router = get_manhattan_router(self.app)

            if manual_router.manual_active:
                # Usar event_to_canvas_coords que convierte correctamente pantalla -> mundo
                event_obj = type('Event', (), {'x': x, 'y': y})()
                world_x, world_y = event_to_canvas_coords(event_obj, self.app.canvas)

                # Actualizar preview con coordenadas del mundo directamente
                manual_router.update_manual_preview_world(world_x, world_y)

        except Exception as e:
            # Error silencioso para no interrumpir otros procesos
            pass

    def on_middle_button_press(self, event):
        """
        PAN NATIVO: Iniciando scan_mark nativo para pan fluido

        """
        self.app.canvas.scan_mark(event.x, event.y)

        # SOLUCIÓN REAL: Actualizar crosshair al iniciar pan
        self.app._draw_crosshair(event)

        self.app.canvas.config(cursor="fleur")

    def on_middle_button_drag(self, event):
        """
        Pan FLUIDO usando scan_dragto nativo de Tkinter

        """
        # PAN NATIVO: Usar scan_dragto nativo para máxima fluidez
        self.app.canvas.scan_dragto(event.x, event.y, gain=1)
        self.app.update_info_bar()

        # SOLUCIÓN REAL: Actualizar crosshair durante el pan
        self.app._draw_crosshair(event)

        # Si estamos en modo manual routing, actualizar el preview para que siga al mouse relativo al mundo
        if hasattr(self.app, 'unified_line_system') and self.app.unified_line_system.manual_active:
             self._handle_manual_routing_preview(event.x, event.y)

    def on_middle_button_release(self, event):
        """
        PAN NATIVO: Finalizando pan con cursor normal

        """
        # Restaurar cursor normal
        self.app.canvas.config(cursor="")

    # CLONADO DE LÍNEAS DE FASE

    def _is_fase_connection(self, connection):
        """
        Detecta si una conexión pertenece a una línea de fase.

        Args:
            connection: Objeto Connection a verificar

        Returns:
            bool: True si es una conexión de fase
        """
        if not connection:
            return False

        # BLOQUEAR CLONACIÓN DE FASE EN PLANO UNIFILAR
        sheet = self.app.project.get_active_sheet()
        if getattr(sheet, 'name', '').startswith('Plano Unifilar'):
            return False

        # Verificar si alguno de los componentes es fase.svg
        start_is_fase = (hasattr(connection.start_component, 'svg_file') and
                        connection.start_component.svg_file == "fase.svg")
        end_is_fase = (hasattr(connection.end_component, 'svg_file') and
                      connection.end_component.svg_file == "fase.svg")

        return start_is_fase or end_is_fase

    def _get_fase_cloning_axis(self, connection):
        """Devuelve el eje perpendicular al que se replica la fase.

        La fase normal se replica hacia arriba/abajo.  Una fase girada 90° o
        270° genera una línea vertical y se replica hacia izquierda/derecha.
        """
        fase = (connection.start_component if getattr(connection.start_component, 'svg_file', None) == 'fase.svg'
                else connection.end_component)
        return 'x' if getattr(fase, 'rotation', 0) % 180 else 'y'

    def _handle_fase_cloning_drag(self, event, connection):
        """
        Maneja el arrastre vertical de líneas de fase para crear clones.

        Args:
            event: Evento de mouse drag
            connection: Conexión de fase being dragged

        Returns:
            bool: True si está en modo clonado, False para arrastre normal
        """
        if not hasattr(self.app, 'fase_cloning_active'):
            self.app.fase_cloning_active = False
        if not hasattr(self.app, 'fase_cloning_start_y'):
            self.app.fase_cloning_start_y = None
        if not hasattr(self.app, 'fase_cloning_previews'):
            self.app.fase_cloning_previews = []
        if not hasattr(self.app, 'fase_cloning_original_connection'):
            self.app.fase_cloning_original_connection = None
        if not hasattr(self.app, 'fase_cloning_direction'):
            self.app.fase_cloning_direction = None
        if not hasattr(self.app, 'fase_cloning_initial_y'):
            self.app.fase_cloning_initial_y = None
        if not hasattr(self.app, 'fase_cloning_initial_x'):
            self.app.fase_cloning_initial_x = None
        if not hasattr(self.app, 'fase_cloning_axis'):
            self.app.fase_cloning_axis = None
        if not hasattr(self.app, 'fase_cloning_orig_pos'):
            self.app.fase_cloning_orig_pos = None

        # Ensure drag_data is initialized before accessing it
        if not hasattr(self.app, 'drag_data') or 'y' not in self.app.drag_data:
            # Initialize drag_data if it doesn't exist
            self.app.drag_data = {"x": event.x, "y": event.y}
            # Don't return False - continue to allow activation on first significant movement
            current_dy = 0  # No movement on first frame
        else:
            # Calcular desplazamiento vertical desde el inicio del arrastre
            current_dy = event.y - self.app.drag_data["y"]

        # ACTIVACIÓN DIRECTA: Si se detecta movimiento vertical significativo, activar clonado
        # Usar umbral de 10 píxeles totales desde el inicio para mayor estabilidad
        axis = getattr(self.app, 'fase_cloning_axis', None) or self._get_fase_cloning_axis(connection)
        initial_coord = (getattr(self.app, 'fase_cloning_initial_x', None)
                         if axis == 'x' else getattr(self.app, 'fase_cloning_initial_y', None))

        # PROTECCIÓN: Si initial_y es None, intentar recuperar de drag_data o usar actual
        if initial_coord is None:
            initial_coord = self.app.drag_data.get(axis, getattr(event, axis))
            setattr(self.app, f'fase_cloning_initial_{axis}', initial_coord)

        total_offset = getattr(event, axis) - initial_coord

        if not self.app.fase_cloning_active and abs(total_offset) > 0: # no cambiar este valor de 0 porque se produce efecto escalera en la clonacion de fases
            self.app.fase_cloning_active = True
            self.app.fase_cloning_start_y = getattr(event, axis) # Para el espaciado de previews
            self.app.fase_cloning_original_connection = connection
            self.app.fase_cloning_axis = axis
            self.app.fase_cloning_direction = "down" if total_offset > 0 else "up"

            # RESTAURAR POSICIÓN ORIGINAL: Asegurar que el componente no se haya movido antes de activar
            orig_pos = getattr(self.app, 'fase_cloning_orig_pos', None)
            if orig_pos:
                start_x, start_y = orig_pos['start']
                end_x, end_y = orig_pos['end']
                connection.start_component.x = start_x
                connection.start_component.y = start_y
                connection.end_component.x = end_x
                connection.end_component.y = end_y

            return True  # Activación exitosa

        # Si ya está en modo clonado, manejar previews
        if self.app.fase_cloning_active:
            # MANTENER FIJO: Asegurar que los componentes originales no se muevan durante el clonado
            orig_pos = getattr(self.app, 'fase_cloning_orig_pos', None)
            if orig_pos:
                start_x, start_y = orig_pos['start']
                end_x, end_y = orig_pos['end']
                connection.start_component.x = start_x
                connection.start_component.y = start_y
                connection.end_component.x = end_x
                connection.end_component.y = end_y

            # Procesar previews de clonado activo
            self._update_fase_cloning_previews(event, connection)
            return True  # Confirmar que está en modo clonado

        # Si no se activó el clonado por movimiento vertical significativo,
        return False  # Permitir arrastre normal de líneas de fase cuando no se está clonando

    def _update_fase_cloning_previews(self, event, connection):
        """
        Actualiza los previews de clonado cada 15 píxeles verticales.

        Args:
            event: Evento de mouse
            connection: Conexión original de fase

        Returns:
            bool: True (siempre en modo clonado)
        """
        # Calcular cuántos clones según el eje perpendicular de la fase.
        axis = getattr(self.app, 'fase_cloning_axis', 'y')
        dy_total = getattr(event, axis) - self.app.fase_cloning_start_y

        # Determinar número de clones - más sensible cuando grid está OFF
        spacing = 20 if not self.app.snap_to_grid_enabled.get() else 25
        clone_count = abs(dy_total) // spacing
        clone_count = min(clone_count, 4)  # Máximo 4 clones (L2, L3, neutro, PE)
        self.app.fase_cloning_preview_clone_count = clone_count

        # Limpiar previews anteriores
        self._clear_fase_cloning_previews()

        if clone_count > 0:
            self._create_fase_cloning_previews(connection, clone_count, dy_total > 0, axis)

        return True

    def _create_fase_cloning_previews(self, original_connection, count, direction_down, axis='y'):
        """
        Crea los previews de las líneas clonadas.

        Args:
            original_connection: Conexión original de fase
            count: Número de clones a crear
            direction_down: True si va hacia abajo, False hacia arriba
        """
        fase_component = None
        conxn_component = None

        if (hasattr(original_connection.start_component, 'svg_file') and
            original_connection.start_component.svg_file == "fase.svg"):
            fase_component = original_connection.start_component
            conxn_component = original_connection.end_component
        else:
            fase_component = original_connection.end_component
            conxn_component = original_connection.start_component

        if not fase_component or not conxn_component:
            return

        clone_names = self._get_fase_clone_sequence(fase_component)

        for i in range(count):
            clone_name = clone_names[i] if i < len(clone_names) else f"Clone{i+1}"

            # Calcular offset perpendicular (dinámico según grid)
            spacing = 20 if not self.app.snap_to_grid_enabled.get() else 25
            y_offset = (i + 1) * spacing
            if not direction_down:
                y_offset = -y_offset

            self._create_single_fase_clone_preview(
                fase_component, conxn_component, clone_name, y_offset, axis,
                original_connection
            )

    def _get_fase_color_for_cloning(self, clone_name):
        """
        Determina el color específico para una fase basada en su tipo.

        Args:
            clone_name: Nombre del clon (L1, L2, L3, N, PE, etc.)

        Returns:
            dict: Diccionario con 'fill' y 'dash' para el color de la línea
        """
        clone_name = clone_name.upper() if clone_name else ""

        # Mapeo de colores específicos para fases
        if clone_name == "N":  # Neutro - azul sólido
            color_info = {
                "fill": "#0000ff",  # Azul sólido
                "dash": None        # Sin línea punteada
            }
        elif clone_name == "PE":  # Proteccion tierra - verde punteado
            color_info = {
                "fill": "#008000",  # Verde
                "dash": (3, 3)      # Línea más segmentada (como panel de líneas)
            }
        elif clone_name in ["L1", "L2", "L3"]:  # Fases de línea - cyan por defecto
            color_info = {
                "fill": "cyan",     # Cyan por defecto para fases L1, L2, L3
                "dash": (5, 5)      # Línea punteada por defecto
            }
        else:  # Otros tipos - usar cyan por defecto
            color_info = {
                "fill": "cyan",
                "dash": (5, 5)
            }

        # Si el componente tiene el método adapt_color_for_display, usarlo para modo oscuro
        try:
            # Obtener referencia a un componente existente para usar su método
            if self.app.components:
                sample_component = self.app.components[0]
                if hasattr(sample_component, 'adapt_color_for_display'):
                    adapted_fill = sample_component.adapt_color_for_display(color_info["fill"])
                    color_info["fill"] = adapted_fill
        except Exception as e:
            pass

            # Continuar con color original

        return color_info

    def _get_orthogonal_clone_segments(self, segments):
        """Devuelve la ruta clonada sin segmentos diagonales."""
        orthogonal_segments = []
        for ((x1, y1), (x2, y2)) in segments:
            if x1 == x2 or y1 == y2:
                orthogonal_segments.append(((x1, y1), (x2, y2)))
                continue

            previous = orthogonal_segments[-1] if orthogonal_segments else None
            previous_is_vertical = (previous and previous[0][0] == previous[1][0])
            if previous_is_vertical:
                corner = (x2, y1)
            else:
                corner = (x1, y2)
            orthogonal_segments.extend([
                ((x1, y1), corner),
                (corner, (x2, y2))
            ])
        return orthogonal_segments

    def _create_single_fase_clone_preview(self, fase_comp, conxn_comp, clone_name,
                                          y_offset, axis='y', original_connection=None):
        """
        Crea un preview individual de una línea de fase clonada.

        Args:
            fase_comp: Componente fase original
            conxn_comp: Componente connx original
            clone_name: Nombre del clon
            y_offset: Offset vertical en píxeles
        """
        try:
            # CLON VERTICAL (axis='x'): usar la misma geometría exacta del clon
            # real para que cada carril quede paralelo y separado (no converja).
            if axis == 'x':
                self._create_vertical_fase_clone_preview(fase_comp, conxn_comp, clone_name, y_offset)
                return

            original_segments = self._get_orthogonal_clone_segments(
                getattr(original_connection, 'segments', []))
            if original_segments:
                offset_x = y_offset if axis == 'x' else 0
                offset_y = y_offset if axis == 'y' else 0
                start_pts = fase_comp.get_connection_points_global()
                end_pts = conxn_comp.get_connection_points_global()
                if start_pts and end_pts:
                    s_x = start_pts[0][0] + offset_x
                    s_y = start_pts[0][1] + offset_y
                    e_x = end_pts[0][0] + offset_x
                    e_y = end_pts[0][1] + offset_y
                    if s_x != e_x and s_y != e_y:
                        if axis == 'x':
                            original_segments = [
                                ((s_x, s_y), (s_x, e_y)),
                                ((s_x, e_y), (e_x, e_y)),
                            ]
                        else:
                            original_segments = [
                                ((s_x, s_y), (e_x, s_y)),
                                ((e_x, s_y), (e_x, e_y)),
                            ]
                color = self._get_fase_color_for_cloning(clone_name)
                zoom = getattr(self.app.canvas, 'zoom_level', 1.0)
                line_ids = [self.app.canvas.create_line(
                    (x1 + offset_x) * zoom, (y1 + offset_y) * zoom,
                    (x2 + offset_x) * zoom, (y2 + offset_y) * zoom,
                    fill=color['fill'], width=1, dash=color['dash'])
                    for ((x1, y1), (x2, y2)) in original_segments]
                self.app.fase_cloning_previews.extend(line_ids)
                return

            # La implementación horizontal existente se conserva sin cambios.

            # Calcular nuevas posiciones
            new_fase_y = fase_comp.y + y_offset
            new_conxn_y = conxn_comp.y + y_offset

            fase_x = fase_comp.x
            fase_y = new_fase_y
            conxn_x = conxn_comp.x
            conxn_y = new_conxn_y

            # PREVIEW ESTILO IMAGEN: Solo segmentos cortos al inicio y final
            fase_color_info = self._get_fase_color_for_cloning(clone_name)

            segment_length = 60  # píxeles para segmentos cortos

            # Aplicar zoom a las coordenadas del mundo
            zoom = getattr(self.app.canvas, 'zoom_level', 1.0)

            # Segmento del lado izquierdo (inicio)
            left_segment = self.app.canvas.create_line(
                fase_x * zoom, fase_y * zoom,
                (fase_x + segment_length) * zoom, fase_y * zoom,
                fill=fase_color_info["fill"],
                width=1,
                dash=fase_color_info["dash"]
            )

            # Segmento del lado derecho (final)
            right_segment = self.app.canvas.create_line(
                (conxn_x - segment_length) * zoom, conxn_y * zoom,
                conxn_x * zoom, conxn_y * zoom,
                fill=fase_color_info["fill"],
                width=1,
                dash=fase_color_info["dash"]
            )

            # PREVIEW ESTILO ORIGINAL: Texto perpendicular con indicadores
            mid_x = (fase_x + conxn_x) / 2
            mid_y = (fase_y + conxn_y) / 2

            # Determinar posición perpendicular (arriba de la línea)
            text_y = mid_y - 15  # 15 píxeles arriba de la línea

            # Color del texto según el tipo de fase
            text_color = "blue"  # Color por defecto
            clone_name_upper = clone_name.upper() if clone_name else ""
            if clone_name_upper == "N":
                text_color = "#0000ff"  # Azul oscuro para N
            elif clone_name_upper == "PE":
                text_color = "#008000"  # Verde para PE
            elif clone_name_upper in ["L1", "L2", "L3"]:
                text_color = "cyan"     # Cyan para fases L

            try:
                if self.app.components:
                    sample_component = self.app.components[0]
                    if hasattr(sample_component, 'adapt_color_for_display'):
                        text_color = sample_component.adapt_color_for_display(text_color)
            except Exception:
                pass  # Usar color original si hay error

            indicator_left = self.app.canvas.create_text(
                fase_x - 15, mid_y,
                text=clone_name, fill=text_color, font=("Arial", 8, "bold")
            )

            # Texto del nombre del clon en posición perpendicular
            preview_text = self.app.canvas.create_text(
                mid_x, text_y,
                text=clone_name, fill=text_color, font=("Arial", 8, "bold")
            )

            indicator_right = self.app.canvas.create_text(
                conxn_x + 15, mid_y,
                text=clone_name, fill=text_color, font=("Arial", 8, "bold")
            )

            # Almacenar previews para limpiar después
            self.app.fase_cloning_previews.extend([left_segment, right_segment, preview_text, indicator_left, indicator_right])

        except Exception as e:
            pass

    def _create_vertical_fase_clone_preview(self, fase_comp, conxn_comp, clone_name, x_offset):
        """Preview vertical con la misma geometría que tendrá el clon final.

        La fase se desplaza únicamente en X (misma altura, copia trasladada) y el
        conxn conserva su columna original (mismo X) escalonándose en Y, para que
        todos los conxns queden alineados en una columna y los carriles lleguen
        paralelos a distinta altura.
        """
        try:
            zoom = getattr(self.app.canvas, 'zoom_level', 1.0)
            color = self._get_fase_color_for_cloning(clone_name)
            start_pts = fase_comp.get_connection_points_global()
            end_pts = conxn_comp.get_connection_points_global()
            if not start_pts or not end_pts:
                return
            s_x = start_pts[0][0] + x_offset
            s_y = start_pts[0][1]
            e_x = end_pts[0][0]
            e_y = end_pts[0][1] + x_offset
            preview_segments = [
                ((s_x, s_y), (s_x, e_y)),
                ((s_x, e_y), (e_x, e_y)),
            ]

            line_ids = [self.app.canvas.create_line(
                x1 * zoom, y1 * zoom, x2 * zoom, y2 * zoom,
                fill=color['fill'], width=1, dash=color['dash'])
                for ((x1, y1), (x2, y2)) in preview_segments]
            (start_x, start_y), _ = preview_segments[0]
            _, (end_x, end_y) = preview_segments[-1]
            mid_x, mid_y = (start_x + end_x) / 2, (start_y + end_y) / 2
            label = self.app.canvas.create_text((mid_x + 15) * zoom, mid_y * zoom, text=clone_name,
                                                fill=color['fill'], font=('Arial', 8, 'bold'))
            left = self.app.canvas.create_text(start_x * zoom, (start_y + 15) * zoom, text=clone_name,
                                               fill=color['fill'], font=('Arial', 8, 'bold'))
            right = self.app.canvas.create_text(end_x * zoom, (end_y - 15) * zoom, text=clone_name,
                                                fill=color['fill'], font=('Arial', 8, 'bold'))
            self.app.fase_cloning_previews.extend(line_ids + [label, left, right])
        except Exception:
            pass
    def _clear_fase_cloning_previews(self):
        """Limpia todos los previews de clonado existentes."""
        if hasattr(self.app, 'fase_cloning_previews'):
            for preview_id in self.app.fase_cloning_previews:
                try:
                    self.app.canvas.delete(preview_id)
                except:
                    pass
            self.app.fase_cloning_previews.clear()

    def _get_fase_clone_sequence(self, original_fase):
        """
        Determina la secuencia de etiquetas para clonado basada en el componente original.

        Args:
            original_fase: Componente fase original

        Returns:
            list: Lista de etiquetas siguientes en secuencia
        """
        current_label = getattr(original_fase, 'label_data', {}).get('name', 'L1')
        if not current_label:
            current_label = 'L1'  # Fallback si no tiene etiqueta

        # Secuencia completa de etiquetas de fase
        full_sequence = ["L1", "L2", "L3", "N", "PE"]

        try:
            # Encontrar índice actual en la secuencia
            current_index = full_sequence.index(current_label)
            next_labels = full_sequence[current_index + 1:]

            return next_labels
        except ValueError:
            # Si la etiqueta actual no está en la secuencia, usar secuencia completa

            return full_sequence

    def _finalize_fase_cloning(self):
        """
        Finaliza el clonado de fase, creando las líneas reales.
        """
        if not hasattr(self.app, 'fase_cloning_active') or not self.app.fase_cloning_active:

            return

        original_connection = self.app.fase_cloning_original_connection
        if not original_connection:

            self._cancel_fase_cloning()
            return

        # Determinar componentes originales
        fase_component = None
        conxn_component = None

        if (hasattr(original_connection.start_component, 'svg_file') and
            original_connection.start_component.svg_file == "fase.svg"):
            fase_component = original_connection.start_component
            conxn_component = original_connection.end_component
        else:
            fase_component = original_connection.end_component
            conxn_component = original_connection.start_component

        if not fase_component or not conxn_component:

            self._cancel_fase_cloning()
            return

        # Calcular número de clones basado en previews
        preview_count = len(self.app.fase_cloning_previews)
        clone_count = getattr(self.app, 'fase_cloning_preview_clone_count', preview_count // 5)

        clone_names = self._get_fase_clone_sequence(fase_component)

        created_count = 0
        for i in range(clone_count):
            if i >= len(clone_names):
                break

            clone_name = clone_names[i]
            spacing = 20 if not self.app.snap_to_grid_enabled.get() else 25
            y_offset = (i + 1) * spacing
            if self.app.fase_cloning_direction == "up":
                y_offset = -y_offset

            if self._create_real_fase_clone(
                    fase_component, conxn_component, clone_name, y_offset,
                    getattr(self.app, 'fase_cloning_axis', 'y')):
                created_count += 1

        # Limpiar modo clonado
        self._cancel_fase_cloning()

        # Limpiar selección de línea residual: si queda selected_connection/
        # selected_segment tras el clonado, el siguiente arrastre de un componente
        # sería interceptado como arrastre/clonado de línea.
        self.app.locked_segment = False
        if hasattr(self.app, 'selected_connection'):
            self.app.selected_connection = None
        if hasattr(self.app, 'selected_segment'):
            self.app.selected_segment = None
        if hasattr(self.app, 'clear_connection_highlights'):
            self.app.clear_connection_highlights()
        try:
            self.app.canvas.config(cursor="")
        except Exception:
            pass

        if hasattr(self.app, 'canvas'):
            self.app.canvas.update_idletasks()

    def _create_real_fase_clone(self, original_fase, original_conxn, clone_name, y_offset_px, axis='y'):
        """
        Crea una línea de fase clonada real (no preview).

        Args:
            original_fase: Componente fase original
            original_conxn: Componente connx original
            clone_name: Nombre del clon
            y_offset_px: Offset vertical en píxeles

        Returns:
            bool: True si se creó exitosamente, False si hubo error
        """
        try:
            pass

            # Convertir offset a coordenadas del mundo
            y_offset_world = y_offset_px

            # Buscar datos de fase y conxn en configuración
            fase_data = None
            conxn_data = None
            fase_category = None
            conxn_category = None

            # Buscar en todas las categorías
            for category, components in self.app.config["components"].items():
                for component_data in components:
                    svg_file = component_data.get("svg_file", component_data.get("svg", ""))
                    if svg_file == "fase.svg" and not fase_data:
                        fase_data = component_data
                        fase_category = category

                    elif svg_file == "conxn.svg" and not conxn_data:
                        conxn_data = component_data
                        conxn_category = category

            if not fase_data or not conxn_data:

                return False

            # Ambos extremos siguen el sentido del clonado.
            # CLON VERTICAL (axis='x'): la fase queda como copia trasladada
            # (solo se desplaza en X, sin diagonal) y el conxn conserva SIEMPRE su
            # columna original (mismo X) escalonándose en Y, para que las líneas
            # lleguen alineadas al panel y no se dispersen en diagonal.
            offset_x = y_offset_world if axis == 'x' else 0
            offset_y = y_offset_world if axis == 'y' else 0
            new_fase_x = original_fase.x + offset_x
            new_fase_y = original_fase.y + offset_y
            new_conxn_x = original_conxn.x
            new_conxn_y = original_conxn.y + y_offset_world

            from models.connection import Connection

            # Buscar la clase Component en el contexto global de la aplicación
            Component = None

            # Método 1: Buscar en el módulo de la aplicación
            if hasattr(self.app, '__class__') and hasattr(self.app.__class__, '__module__'):
                import sys
                app_module = sys.modules[self.app.__class__.__module__]
                if hasattr(app_module, 'Component'):
                    Component = app_module.Component

            # Método 2: Buscar en el espacio global de la aplicación (fallback)
            if not Component and hasattr(self.app, '__dict__'):
                for attr_name, attr_value in self.app.__dict__.items():
                    if hasattr(attr_value, '__name__') and attr_value.__name__ == 'Component':
                        Component = attr_value
                        break

            # Método 3: Buscar en globals() de la aplicación (último recurso)
            if not Component:
                try:
                    import sys
                    main_module = sys.modules['__main__']
                    if hasattr(main_module, 'Component'):
                        Component = main_module.Component

                except:
                    pass

            if not Component:

                return False

            fase_size = self.app.get_component_real_size(
                fase_data.get("svg_file", fase_data.get("svg", "")),
                fase_category
            )
            if not fase_size:
                fase_size = [20, 20]  # Tamaño por defecto

            conxn_size = self.app.get_component_real_size(
                conxn_data.get("svg_file", conxn_data.get("svg", "")),
                conxn_category
            )
            if not conxn_size:
                conxn_size = [20, 20]  # Tamaño por defecto

            new_fase = Component(
                self.app.canvas,
                fase_data.get("svg_file", fase_data.get("svg", "")),
                clone_name,
                fase_size,
                new_fase_x,
                new_fase_y,
                self.app.config["svg_path"],
                fase_category,
                self.app.config
            )
            if getattr(original_fase, 'rotation', 0):
                new_fase.rotate(original_fase.rotation)

            if hasattr(new_fase, 'label_data'):
                new_fase.label_data['name'] = clone_name

                if hasattr(new_fase, 'draw_label'):
                    if hasattr(new_fase, 'clear_label'):
                        new_fase.clear_label()
                    new_fase.draw_label()

                # SOLUCIÓN MINIMALISTA: Permitir que el sistema normal maneje la visualización

            new_conxn = Component(
                self.app.canvas,
                conxn_data.get("svg_file", conxn_data.get("svg", "")),
                f"{clone_name}_conxn",
                conxn_size,
                new_conxn_x,
                new_conxn_y,
                self.app.config["svg_path"],
                conxn_category,
                self.app.config
            )
            if getattr(original_conxn, 'rotation', 0):
                new_conxn.rotate(original_conxn.rotation)

            if hasattr(new_conxn, 'label_data'):
                new_conxn.label_data['name'] = clone_name

                if hasattr(new_conxn, 'draw_label'):
                    if hasattr(new_conxn, 'clear_label'):
                        new_conxn.clear_label()
                    new_conxn.draw_label()

            self.app.components.append(new_fase)
            self.app.components.append(new_conxn)

            new_connection = Connection(
                start_component=new_fase,
                start_point_idx=0,
                end_component=new_conxn,
                end_point_idx=0
            )

            # COLORES: específicos para N/PE, configuración del usuario para L1-L3
            clone_name_upper = clone_name.upper() if clone_name else ""

            if clone_name_upper in ["N", "PE"]:
                fase_color_info = self._get_fase_color_for_cloning(clone_name)
                new_connection.line_color = fase_color_info["fill"]
                if fase_color_info["dash"] is None:
                    new_connection.line_dash = ""
                else:
                    new_connection.line_dash = str(fase_color_info["dash"])
                new_connection.line_width = self.app.current_line_width.get()
            else:
                new_connection.line_color = self.app.current_line_color.get()
                new_connection.line_width = self.app.current_line_width.get()
                new_connection.line_dash = self.app.current_line_dash.get()

            self.app.connections.append(new_connection)

            try:
                if hasattr(self.app, 'manhattan_router'):
                    start_pts = new_fase.get_connection_points_global()
                    end_pts = new_conxn.get_connection_points_global()
                    if not start_pts or not end_pts:
                        return False
                    s_x, s_y = start_pts[0][0], start_pts[0][1]
                    e_x, e_y = end_pts[0][0], end_pts[0][1]
                    corner = (s_x, e_y) if s_x < e_x else (e_x, s_y)
                    new_connection.segments = [
                        ((s_x, s_y), corner),
                        (corner, (e_x, e_y)),
                    ]
                    new_connection.manually_modified = True
                    new_connection.fase_clone_axis = axis
                    self.app.manhattan_router.update_manhattan_line(new_connection)

                self._clear_fase_cloning_previews()

                return True
            except Exception as e:
                import traceback
                traceback.print_exc()
                return False
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False

    def _cancel_fase_cloning(self):
        """Cancela el modo de clonado de fase."""
        if hasattr(self.app, 'fase_cloning_active'):
            self._clear_fase_cloning_previews()
            self.app.fase_cloning_active = False
            self.app.fase_cloning_start_y = None
            self.app.fase_cloning_previews = []
            self.app.fase_cloning_original_connection = None
            self.app.fase_cloning_direction = None
            self.app.fase_cloning_initial_y = None
            self.app.fase_cloning_initial_x = None
            self.app.fase_cloning_axis = None
            self.app.fase_cloning_preview_clone_count = 0
            self.app.fase_cloning_orig_pos = None

    def _crear_linea_fase_manhattan(self, fase_component):
        """Crea automáticamente una línea horizontal desde fase.svg hasta el borde derecho del canvas"""
        try:
            # Calcular el ancho visible del canvas para posicionar conxn en el borde derecho
            canvas_width = self.app.canvas.winfo_width()
            scale_factor = getattr(self.app.canvas, 'scale_factor', 1.0)

            # Convertir ancho del canvas a coordenadas del mundo
            world_width = canvas_width / scale_factor if scale_factor > 0 else canvas_width

            # Posicionar conxn cerca del borde derecho (con margen de 50 píxeles)
            conxn_x = world_width - 50

            # Buscar conxn.svg en la configuración
            conxn_data = None
            for category, components in self.app.config["components"].items():
                for component_data in components:
                    svg_file = component_data.get("svg_file", component_data.get("svg", ""))
                    if svg_file == "conxn.svg":
                        conxn_data = component_data
                        preview_category = category
                        break
                if conxn_data:
                    break

            if not conxn_data:
                return

            fase_points = fase_component.get_connection_points_global()
            if not fase_points:
                return

            # Usar el primer punto de conexión del fase como referencia
            fase_conn_y = fase_points[0][1]  # Coordenada Y del punto de conexión

            # Calcular la posición Y del conxn para que su punto de conexión coincida
            # Necesitamos calcular el offset interno del conxn.svg
            original_preview_mode = self.app.component_preview_mode
            original_preview_component = self.app.preview_component
            original_preview_data = self.app.preview_component_data

            try:
                self.app.activar_preview_componente(conxn_data, preview_category)

                temp_canvas_x = conxn_x * scale_factor
                temp_canvas_y = fase_component.y * scale_factor
                temp_world_x = temp_canvas_x / self.app.canvas.zoom_level
                temp_world_y = temp_canvas_y / self.app.canvas.zoom_level
                conxn_component = self.app.finalizar_preview_componente(temp_world_x, temp_world_y, ejecutar_autoconexion=False)

                if not conxn_component:
                    return

                conxn_points = conxn_component.get_connection_points_global()
                if not conxn_points:
                    return

                conxn_conn_y = conxn_points[0][1]  # Coordenada Y del punto de conexión

                # Calcular la diferencia entre puntos de conexión
                y_diff = fase_conn_y - conxn_conn_y

                # Ajustar la posición Y del conxn para que los puntos sean colineales
                nueva_conxn_y = conxn_component.y + y_diff
                conxn_component.y = nueva_conxn_y

                # Actualizar las coordenadas del canvas del componente
                conxn_component.canvas_x = conxn_x * scale_factor
                conxn_component.canvas_y = nueva_conxn_y * scale_factor
                if hasattr(conxn_component, 'refresh_display'):
                    conxn_component.refresh_display()
                else:
                    conxn_component.draw()  # Fallback al método draw() básico
            finally:
                self.app.component_preview_mode = original_preview_mode
                self.app.preview_component = original_preview_component
                self.app.preview_component_data = original_preview_data

            from models.connection import Connection

            if fase_points and conxn_points:

                connection = Connection(
                    start_component=fase_component,
                    start_point_idx=0,
                    end_component=conxn_component,
                    end_point_idx=0
                )

                self.app.connections.append(connection)

                # Al ser colineales, Manhattan será una línea horizontal perfecta
                # Método especializado para líneas horizontales perfectas
                if hasattr(self.app, 'manhattan_router'):
                    self.app.manhattan_router.update_manhattan_line_special(
                        fase_component, 0,  # componente_inicio, punto_inicio
                        conxn_component, 0,  # componente_fin, punto_fin
                        connection
                    )

        except Exception as e:
            pass  # Fallar silenciosamente

    def _move_shape_preview(self, x, y):
        """Mueve el preview de la forma siguiendo el cursor."""
        try:
            app = self.app
            if not hasattr(app, 'shape_preview_mode') or not app.shape_preview_mode:
                return

            shape_type = getattr(app, 'shape_preview_type', None)
            if not shape_type:
                return

            if hasattr(app, 'shape_preview_id') and app.shape_preview_id:
                app.canvas.delete(app.shape_preview_id)

            preview_id = None

            if shape_type == "circle":
                preview_id = app.canvas.create_oval(
                    x - 15, y - 15, x + 15, y + 15,
                    outline="blue", width=2, stipple="gray50"
                )
            elif shape_type == "square":
                preview_id = app.canvas.create_rectangle(
                    x - 15, y - 15, x + 15, y + 15,
                    outline="blue", width=2, stipple="gray50"
                )
            elif shape_type == "rectangle":
                preview_id = app.canvas.create_rectangle(
                    x - 20, y - 12, x + 20, y + 12,
                    outline="blue", width=2, stipple="gray50"
                )
            elif shape_type == "ellipse":
                preview_id = app.canvas.create_oval(
                    x - 25, y - 15, x + 25, y + 15,
                    outline="blue", width=2, stipple="gray50"
                )
            elif shape_type == "fase":
                # Para fase, usar el preview de componente existente
                pass  # Se maneja por el sistema de preview de componentes

            if preview_id:
                app.shape_preview_id = preview_id

        except Exception as e:
            pass

class EventBinder:
    """
    Clase utilitaria para configurar todos los bindings de eventos.

    Centraliza la configuración de eventos para mantener el código organizado.
    """

    def __init__(self, canvas, event_handler):
        """
        Inicializa el configurador de eventos.

        Args:
            canvas: Canvas de la aplicación
            event_handler: Instancia de EventHandler
        """
        self.canvas = canvas
        self.event_handler = event_handler

    def bind_all_events(self):
        """
        Configura todos los bindings de eventos de la aplicación.
        """
        self.setup_canvas_bindings()
        self.setup_keyboard_bindings()

    def setup_canvas_bindings(self):
        """
        Configura los eventos del canvas.
        """
        canvas = self.canvas

        # Mouse events básicos
        canvas.bind("<Button-1>", self.event_handler.on_canvas_click)
        canvas.bind("<Button-3>", self.event_handler.on_right_click)
        canvas.bind("<B1-Motion>", self.event_handler.on_canvas_drag)
        canvas.bind("<ButtonRelease-1>", self.event_handler.on_canvas_release)

        # NUEVOS BINDINGS PARA SEGMENTOS: Click derecho y arrastre
        canvas.bind("<B3-Motion>", self.event_handler.on_canvas_drag)
        canvas.bind("<ButtonRelease-3>", self.event_handler.on_canvas_release)

        canvas.bind("<Motion>", self.event_handler.on_mouse_motion)

        # EVENTOS CON Ctrl PARA SELECCIÓN MÚLTIPLE
        # Eventos con Ctrl para selección múltiple (funcionalidad válida)
        canvas.bind("<Control-Button-1>", self.event_handler.on_canvas_click)
        canvas.bind("<Control-B1-Motion>", self.event_handler.on_canvas_drag)
        canvas.bind("<Control-ButtonRelease-1>", self.event_handler.on_canvas_release)

        # Botón central para mover pantalla (PAN)
        canvas.bind("<Button-2>", self.event_handler.on_middle_button_press)    # Botón central presionado
        canvas.bind("<B2-Motion>", self.event_handler.on_middle_button_drag)    # Arrastre con botón central
        canvas.bind("<ButtonRelease-2>", self.event_handler.on_middle_button_release)  # Liberación botón central

        canvas.bind("<Configure>", self.event_handler.on_canvas_resize)

        # Focus mejorado
        # Asegurar que el canvas puede recibir eventos de teclado y mouse
        canvas.focus_set()
        canvas.bind("<FocusIn>", lambda e: None)
        canvas.bind("<FocusOut>", lambda e: None)

        # Windows / MacOS
        canvas.bind("<Control-MouseWheel>", self.event_handler.on_mouse_wheel_zoom)
        # Linux (Button-4 = Up/In, Button-5 = Down/Out)
        canvas.bind("<Control-Button-4>", self.event_handler.on_mouse_wheel_zoom)
        canvas.bind("<Control-Button-5>", self.event_handler.on_mouse_wheel_zoom)

        # Forzar focus cuando se hace click en el canvas
        def force_focus(event):
            canvas.focus_set()
            canvas.focus_force()
            return self.event_handler.on_canvas_click(event)

        # Reemplazar el binding normal con uno que fuerza el focus
        canvas.bind("<Button-1>", force_focus)

    def setup_keyboard_bindings(self):
        """
        Configura los eventos de teclado.
        """
        # Keyboard events en el canvas (necesita focus)
        self.canvas.bind("<KeyPress>", self.event_handler.on_key_press)
        self.canvas.bind("<Key>", self.event_handler.on_key_press)  # Alternativo para mejor compatibilidad

        # ATAJOS ESPECÍFICOS SEGÚN ESPECIFICACIÓN
        # Delete key para eliminar elementos
        self.canvas.bind("<Delete>", lambda e: self.event_handler.on_delete_key())

        # Escape para deseleccionar
        self.canvas.bind("<Escape>", lambda e: self.event_handler.on_escape_key())

        # ATAJOS CON Ctrl - Solo un binding por atajo (sin duplicados)
        self.canvas.bind("<Control-r>", self.event_handler.on_key_press)  # Ctrl+R: giro derecha
        self.canvas.bind("<Control-Shift-R>", self.event_handler.on_key_press)  # Ctrl+Shift+R: giro izquierda
        self.canvas.bind("<Control-o>", self.event_handler.on_key_press)  # Ctrl+O: abrir
        self.canvas.bind("<Control-n>", self.event_handler.on_key_press)  # Ctrl+N: nuevo
        self.canvas.bind("<Control-s>", self.event_handler.on_key_press)  # Ctrl+S: guardar
        self.canvas.bind("<Control-e>", self.event_handler.on_key_press)  # Ctrl+E: exportar PDF
        self.canvas.bind("<Control-q>", self.event_handler.on_key_press)  # Ctrl+Q: salir
        self.canvas.bind("<Control-h>", self.event_handler.on_key_press)  # Ctrl+H: alineamiento vertical
        self.canvas.bind("<Control-u>", self.event_handler.on_key_press)  # Ctrl+U: seleccionar todo

        # ATAJOS DE ZOOM - Bindings optimizados
        self.canvas.bind("<Control-plus>", self.event_handler.on_key_press)
        self.canvas.bind("<Control-equal>", self.event_handler.on_key_press)
        self.canvas.bind("<Control-minus>", self.event_handler.on_key_press)
        self.canvas.bind("<Control-0>", self.event_handler.on_key_press)
        self.canvas.bind("<Control-KP_Add>", self.event_handler.on_key_press)
        self.canvas.bind("<Control-KP_Subtract>", self.event_handler.on_key_press)
        self.canvas.bind("<Control-KP_0>", self.event_handler.on_key_press)

        # DISTRIBUCIÓN DE COMPONENTES - ¡CRÍTICO!
        self.canvas.bind("<Control-j>", self.event_handler.on_key_press)  # Ctrl+J: distribución vertical
        self.canvas.bind("<Control-k>", self.event_handler.on_key_press)  # Ctrl+K: distribución horizontal

        # BLOCK TERMINAL - Solo en Hoja Gabinete 2D
        self.canvas.bind("<Control-b>", self.event_handler.on_key_press)  # Ctrl+B: insertar block terminal

        # ALINEAMIENTO - Ctrl+H para alineamiento horizontal

        # Asegurar que el canvas puede recibir eventos de teclado
        self.canvas.focus_set()

        # Hacer que el canvas sea "clickeable" para recibir focus
        self.canvas.config(takefocus=True)

        # MEJORA: Bindings globales para atajos importantes
        # Agregar también bindings globales en la ventana principal para que funcionen siempre
        if hasattr(self.event_handler.app, 'root'):
            root = self.event_handler.app.root

            # Atajos críticos con binding global
            root.bind_all("<Control-o>", self.event_handler.on_key_press)  # Ctrl+O: abrir
            root.bind_all("<Control-n>", self.event_handler.on_key_press)  # Ctrl+N: nuevo
            root.bind_all("<Control-s>", self.event_handler.on_key_press)  # Ctrl+S: guardar
            root.bind_all("<Control-e>", self.event_handler.on_key_press)  # Ctrl+E: exportar PDF
            root.bind_all("<Control-q>", self.event_handler.on_key_press)  # Ctrl+Q: salir
            root.bind_all("<Control-u>", self.event_handler.on_key_press)  # Ctrl+U: seleccionar todo

            # ATAJOS DE ZOOM - Globales
            root.bind_all("<Control-plus>", self.event_handler.on_key_press)
            root.bind_all("<Control-equal>", self.event_handler.on_key_press)
            root.bind_all("<Control-minus>", self.event_handler.on_key_press)
            root.bind_all("<Control-0>", self.event_handler.on_key_press)
            root.bind_all("<Control-KP_Add>", self.event_handler.on_key_press)
            root.bind_all("<Control-KP_Subtract>", self.event_handler.on_key_press)
            root.bind_all("<Control-KP_0>", self.event_handler.on_key_press)

            # DISTRIBUCIÓN - Globales críticos
            root.bind_all("<Control-j>", self.event_handler.on_key_press)  # Ctrl+J: distribución vertical
            root.bind_all("<Control-k>", self.event_handler.on_key_press)  # Ctrl+K: distribución horizontal

            root.bind_all("<F8>", self.event_handler.app.toggle_unifilar_tab)
            self.event_handler.app.toggle_unifilar_tab()

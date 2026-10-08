import time
from models.connection import Connection
from utils.utility_functions import adapt_color_for_display

class UnifiedLineSystem:
    """
    Sistema unificado de líneas que combina:
    - Manual routing (preservar exactamente como funciona actualmente)
    - Automatic orthogonal routing (nuevo para conexiones entre puntos)
    """

    def __init__(self, app):
        """Inicializa el sistema unificado de líneas"""
        self.app = app
        self.canvas = app.canvas

        # SISTEMA MANUAL (PRESERVAR EXACTO)
        self._init_manual_system()

        # SISTEMA AUTOMÁTICO ORTOGONAL
        self._init_orthogonal_system()

        # CONFIGURACIÓN UNIFICADA
        self.scale_factor = 1.0

        self._init_performance_optimizations()

    # SISTEMA MANUAL (PRESERVAR EXACTO)

    def _init_manual_system(self):
        """Inicializa el sistema manual exactamente como funciona actualmente"""

        # Estado del sistema manual
        self.manual_active = False
        self.manual_start_point = None  # (component, point_idx)
        self.manual_angle_points = []   # Lista de puntos de ángulo [(x, y), ...]
        self.manual_current_end_point = None  # Punto final temporal

        # Referencias visuales
        self.manual_preview_lines = []
        self.manual_preview_points = []
        self.manual_highlight_ids = []

        # Configuración
        self.manual_angle_point_radius = 2
        self.manual_preview_line_width = 1.5
        self._preview_line_color = "blue"  # Color base, se adaptará automáticamente

    def _adapt_color_for_display(self, color: str) -> str:
        """Adapta colores para el tema actual (oscuro/claro)"""
        try:
            canvas_bg = self.app.canvas.cget("bg")
        except:
            canvas_bg = None
        return adapt_color_for_display(color, canvas_bg)

    def activate_manual_routing(self, start_component, start_point_idx: int) -> bool:
        """
        Activa el modo manual routing para conexiones ortogonales

        Args:
            start_component: Componente inicial
            start_point_idx: Índice del punto de conexión inicial
        """
        try:
            connection_points = start_component.get_connection_points_global()
            start_x, start_y, _ = connection_points[start_point_idx]

            # DESACTIVAR MANHATTAN Y MODO CONEXIÓN NORMAL
            if hasattr(self.app, 'connection_mode'):
                self.app.connection_mode = False

            if hasattr(self.app, 'connection_start'):
                self.app.connection_start = None

            self.manual_active = True
            self.manual_start_point = (start_component, start_point_idx)
            self.manual_angle_points = []
            self.manual_current_end_point = (start_x, start_y)

            # ASEGURAR QUE EL BOTÓN 8 Y CROSSHAIR SE MANTENGAN ACTIVOS
            if hasattr(self.app, '_activate_button') and hasattr(self.app, 'button_active_states'):
                if self.app.button_active_states.get("button8", False):
                    self.app._activate_button("button8")

            # ASEGURAR QUE EL CROSSHAIR SIGA FUNCIONANDO DURANTE MANUAL ROUTING
            if hasattr(self.app, '_draw_crosshair') and hasattr(self.app, '_crosshair_bound'):
                # Forzar una actualización del crosshair al inicio del manual routing
                current_event = type('Event', (), {
                    'x': getattr(self.app.canvas, 'winfo_width', lambda: 800)() // 2,
                    'y': getattr(self.app.canvas, 'winfo_height', lambda: 600)() // 2
                })()
                self.app._draw_crosshair(current_event)

            # Limpiar visualizaciones anteriores
            self._clear_manual_preview()

            self._show_manual_start_feedback(start_component, start_point_idx)

            return True

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False

    def update_manual_preview_world(self, world_x: float, world_y: float):
        """
        Actualiza la línea de preview.
        
        Args:
            world_x, world_y: Coordenadas del mundo
        """
        if not self.manual_active:
            return

        try:
            # Usar coordenadas directas para permitir preview en L (ángulo)
            # No forzar colinealidad aquí para que el usuario vea el camino ortogonal (H-V)
            self.manual_current_end_point = (world_x, world_y)
            self._update_manual_preview()

        except Exception as e:

            pass

    def finish_manual_connection(self, end_component, end_point_idx: int) -> bool:
        """
        Finaliza la conexión manual y la registra en el sistema
        """

        if not self.manual_active:
            return False

        try:
            # Verificar componentes válidos
            if not end_component or not hasattr(end_component, 'get_connection_points_global'):
                return False

            connection_points = end_component.get_connection_points_global()
            if end_point_idx >= len(connection_points):
                return False

            # Obtener coordenadas del punto final
            end_x, end_y, _ = connection_points[end_point_idx]

            connection = Connection(
                start_component=self.manual_start_point[0],
                start_point_idx=self.manual_start_point[1],
                end_component=end_component,
                end_point_idx=end_point_idx
            )

            connection.line_color = self.app.current_line_color.get()
            connection.line_width = self.app.current_line_width.get()
            connection.line_dash = self.app.current_line_dash.get()  # Guardar string original, no procesado

            self._create_manual_segments(connection, end_x, end_y)

            # Marcar como conexión manual
            connection.line_type = "manual"
            connection.manually_modified = True

            # Segmentos creados para conexión manual

            self.app.connections.append(connection)

            self._redraw_connection(connection)

            # LIMPIAR PREVIEW ANTES DE DESACTIVAR
            self._clear_manual_preview()

            # Desactivar
            self._deactivate_manual_routing()

            return True

        except Exception as e:
            import traceback
            traceback.print_exc()

            # LIMPIAR PREVIEW INCLUSO EN ERROR
            try:
                self._clear_manual_preview()
            except:
                pass

            try:
                self._deactivate_manual_routing()
            except:
                pass

            return False

    def finish_manual_on_line(self, world_x: float, world_y: float) -> bool:
        """
        Finaliza la conexión manual sobre una línea existente.
        Inserta un punto de empalme y conecta a él.
        
        Args:
            world_x: Coordenada X en mundo
            world_y: Coordenada Y en mundo
            
        Returns:
            bool: True si se finalizó correctamente
        """
        if not self.manual_active:
            return False

        try:
            # Buscar línea en la posición
            line_info = self.app._find_line_at_position(world_x, world_y)
            if not line_info:
                return False

            connection, segment_idx = line_info

            # Calcular punto exacto sobre el segmento
            (x1, y1), (x2, y2) = connection.segments[segment_idx]

            # Proyectar punto sobre el segmento
            if x1 == x2:  # Línea vertical
                insert_x = x1
                insert_y = max(min(world_y, max(y1, y2)), min(y1, y2))
            elif y1 == y2:  # Línea horizontal
                insert_x = max(min(world_x, max(x1, x2)), min(x1, x2))
                insert_y = y1
            else:  # Línea diagonal
                insert_x = world_x
                insert_y = world_y

            # Insertar punto de empalme
            junction = self.app.insert_junction_point(connection, (insert_x, insert_y), segment_idx)
            if not junction:
                return False

            # Finalizar conexión manual al punto de empalme
            return self.finish_manual_connection(junction, 0)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False

    def cancel_manual_routing(self):
        """Cancela el modo manual routing sin crear conexión"""
        self._deactivate_manual_routing()

    def cancel(self):
        """
        Cancelar manual routing - compatibilidad con sistema anterior
        """
        self.cancel_manual_routing()

    def add_angle_point(self, x, y):
        """
        Añadir punto de ángulo durante manual routing - compatibilidad con sistema anterior

        Args:
            x, y: Coordenadas del punto de ángulo (pantalla)
        """
        try:
            from utils.coordinates import event_to_canvas_coords

            # En el sistema manual actual, esto se maneja internamente
            # Por ahora, registramos el punto para compatibilidad
            if self.manual_active:
                # Convertir de pantalla a mundo
                event_obj = type('Event', (), {'x': x, 'y': y})()
                world_x, world_y = event_to_canvas_coords(event_obj, self.app.canvas)

                self.manual_angle_points.append((world_x, world_y))

                # NO actualizar manual_current_end_point aquí
                # Se actualizará automáticamente cuando el mouse se mueva

                self._update_manual_preview()
            return True
        except Exception as e:

            pass
            return False

    def update_preview(self, x, y):
        """
        Actualizar preview durante manual routing - compatibilidad con sistema anterior

        Args:
            x, y: Coordenadas del preview
        """
        try:

            # En el sistema manual actual, esto actualiza la línea de preview
            if self.manual_active:
                self.manual_current_end_point = (x, y)
                self._update_manual_preview()
            return True
        except Exception as e:

            pass
            return False

    def update_manhattan_line_special(self, start_component, start_point_idx,
                                    end_component, end_point_idx, connection):
        """
        Actualizar línea Manhattan especializada - compatibilidad con sistema anterior

        Args:
            start_component, start_point_idx: Componente y punto de inicio
            end_component, end_point_idx: Componente y punto final
            connection: Conexión a actualizar

        Returns:
            Connection: Conexión actualizada
        """
        try:

            # Usar el método básico de actualización
            return self.update_manhattan_line(connection)
        except Exception as e:

            pass
            return connection

    def _create_manual_segments(self, connection, end_x: float, end_y: float):
        """
        Crea los segmentos de línea para la conexión manual - COPIADO EXACTAMENTE
        """
        try:
            # 1. Preservar puntos de ángulo para cálculo dinámico
            connection.manual_angle_points = self.manual_angle_points[:]  # Copia para preservar

            # 2. Crear segmentos iniciales (se recalcularán dinámicamente)
            # Usar el mismo método que el recalculo dinámico
            start_points = self.manual_start_point[0].get_connection_points_global()
            start_x, start_y, _ = start_points[self.manual_start_point[1]]

            # Construir lista de puntos: inicio + ángulos + fin
            all_points = [(start_x, start_y)] + connection.manual_angle_points + [(end_x, end_y)]

            connection.segments = []
            for i in range(len(all_points) - 1):
                point1 = all_points[i]
                point2 = all_points[i + 1]

                x1, y1 = point1
                x2, y2 = point2

                # ALGORITMO ORTOGONAL: Crear camino en L (90°)
                # Punto intermedio para crear línea ortogonal
                mid_x = x2
                mid_y = y1

                connection.segments.append(((x1, y1), (mid_x, mid_y)))
                # Segmento 2: vertical (midpoint -> point2)
                connection.segments.append(((mid_x, mid_y), (x2, y2)))

        except Exception as e:

            pass
    def _update_manual_preview(self):
        """Actualiza la visualización del preview"""
        try:
            # Throttling para evitar lag durante preview
            current_ts = getattr(self, '_last_preview_ts', 0)

            # Solo actualizar si han pasado más de 33ms (30 FPS throttle)
            if current_ts and (time.time() - current_ts) < 0.033:
                return  # Saltar actualización para reducir lag

            self._last_preview_ts = time.time()

            # Cache de preview para evitar recrear líneas idénticas
            if not hasattr(self, '_last_preview_data'):
                self._last_preview_data = None

            zoom_level = getattr(self.app.canvas, 'zoom_level', 1.0)

            self._clear_manual_preview()

            if not self.manual_active or not self.manual_start_point or not self.manual_current_end_point:
                return

            start_points = self.manual_start_point[0].get_connection_points_global()
            start_x, start_y, _ = start_points[self.manual_start_point[1]]

            # Construir lista de puntos: inicio + ángulos + cursor actual
            all_points = [(start_x, start_y)] + self.manual_angle_points + [self.manual_current_end_point]

            preview_color = self.app.current_line_color.get()
            preview_width = self.app.current_line_width.get()

            # Adaptar color para el tema actual
            preview_color = self._adapt_color_for_display(preview_color)

            for i in range(len(all_points) - 1):
                x1, y1 = all_points[i]
                x2, y2 = all_points[i + 1]

                # ALGORITMO ORTOGONAL: Crear camino en L (90°)
                # Punto intermedio para crear línea ortogonal
                mid_x = x2
                mid_y = y1

                # CORRECCIÓN DESFASE: Escalar por zoom para coordenadas del canvas
                # canvas.create_line espera coordenadas del canvas, no de pantalla
                zoom = getattr(self.app.canvas, 'zoom_level', 1.0)
                canvas_x1, canvas_y1 = x1 * zoom, y1 * zoom
                canvas_mid_x, canvas_mid_y = mid_x * zoom, mid_y * zoom

                # No dibujar líneas de longitud cero
                if abs(canvas_x1 - canvas_mid_x) > 0.5 or abs(canvas_y1 - canvas_mid_y) > 0.5:
                    line_id1 = self.app.canvas.create_line(
                        canvas_x1, canvas_y1, canvas_mid_x, canvas_mid_y,
                        fill=preview_color,
                        width=preview_width,
                        dash=(5, 5)  # Línea punteada para preview
                    )
                    self.manual_preview_lines.append(line_id1)

                canvas_x2, canvas_y2 = x2 * zoom, y2 * zoom

                # No dibujar líneas de longitud cero
                if abs(canvas_mid_x - canvas_x2) > 0.5 or abs(canvas_mid_y - canvas_y2) > 0.5:
                    line_id2 = self.app.canvas.create_line(
                        canvas_mid_x, canvas_mid_y, canvas_x2, canvas_y2,
                        fill=preview_color,
                        width=preview_width,
                        dash=(5, 5)  # Línea punteada para preview
                    )
                    self.manual_preview_lines.append(line_id2)

            for angle_point in self.manual_angle_points:
                x, y = angle_point
                zoom = getattr(self.app.canvas, 'zoom_level', 1.0)
                canvas_x, canvas_y = x * zoom, y * zoom

                point_id = self.app.canvas.create_oval(
                    canvas_x - self.manual_angle_point_radius,
                    canvas_y - self.manual_angle_point_radius,
                    canvas_x + self.manual_angle_point_radius,
                    canvas_y + self.manual_angle_point_radius,
                    fill="orange", outline="red"
                )

                self.manual_preview_points.append(point_id)

            if not self.manual_angle_points:
                zoom = getattr(self.app.canvas, 'zoom_level', 1.0)
                canvas_start_x, canvas_start_y = start_x * zoom, start_y * zoom

                start_id = self.app.canvas.create_oval(
                    canvas_start_x - self.manual_angle_point_radius,
                    canvas_start_y - self.manual_angle_point_radius,
                    canvas_start_x + self.manual_angle_point_radius,
                    canvas_start_y + self.manual_angle_point_radius,
                    fill="green", outline="darkgreen"
                )

                self.manual_preview_points.append(start_id)

            self.app.canvas.update()

        except Exception as e:

            pass
    def _clear_manual_preview(self):
        """Limpia todas las visualizaciones de preview - COPIADO EXACTAMENTE"""
        try:
            # Limpiar líneas de preview
            for line_id in self.manual_preview_lines:
                self.app.canvas.delete(line_id)
            self.manual_preview_lines = []

            # Limpiar puntos de preview
            for point_id in self.manual_preview_points:
                self.app.canvas.delete(point_id)
            self.manual_preview_points = []

            for highlight_id in self.manual_highlight_ids:
                self.app.canvas.delete(highlight_id)
            self.manual_highlight_ids = []

            self.app.canvas.update()

        except Exception as e:

            pass
    def _show_manual_start_feedback(self, component, point_idx: int):
        """
        Muestra feedback visual del punto inicial - COPIADO EXACTAMENTE
        """
        try:
            if hasattr(self.app, 'highlight_connection_point'):
                self.app.highlight_connection_point(component, point_idx)

            if hasattr(self.app, 'set_status'):
                self.app.set_status("📐 MODO RUTA MANUAL: Click para añadir ángulos, Ctrl+Click en punto final para terminar", "blue")

        except Exception as e:

            pass
    def _deactivate_manual_routing(self):
        """Desactiva el modo manual routing - COPIADO EXACTAMENTE"""
        try:

            # Limpiar visualizaciones
            self._clear_manual_preview()

            # Restaurar interfaz
            if hasattr(self.app, 'clear_connection_point_highlights'):
                self.app.clear_connection_point_highlights()

            if hasattr(self.app, 'set_status'):
                # No hacemos nada, el temporizador de set_status lo reseteará a "Listo"
                pass

            # Limpiar estado
            self.manual_active = False
            self.manual_start_point = None
            self.manual_angle_points = []
            self.manual_current_end_point = None

            # LIMPIAR BINDING DEL MOTION EVENT SOLO DEL MANUAL ROUTING
            # NO deshabilitar completamente - solo aseguramos que el crosshair siga funcionando
            try:
                # NO usar unbind("<Motion>") porque elimina también el binding del crosshair
                # Solo aseguramos que el crosshair esté activo
                if hasattr(self.app, '_draw_crosshair'):
                    # Forzar una actualización del crosshair
                    current_event = type('Event', (), {
                        'x': self.app.canvas.winfo_width()//2,
                        'y': self.app.canvas.winfo_height()//2
                    })()
                    self.app._draw_crosshair(current_event)

                # Re-añadir el binding del crosshair si se perdió
                # Crosshair ahora se maneja en función consolidada de event_handlers
                # No se necesitan múltiples bindings de Motion

            except Exception as e:
                import traceback
                traceback.print_exc()

            # Desactivar botón 8 visualmente cuando termine el modo manual
            if hasattr(self.app, '_deactivate_button'):
                self.app._deactivate_button("button8")

            self.app.canvas.update()

        except Exception as e:
            import traceback
            traceback.print_exc()
    # SISTEMA AUTOMÁTICO ORTOGONAL

    def _init_orthogonal_system(self):
        """Inicializa el sistema automático orthogonal"""
        self.orthogonal_enabled = True

    def _init_performance_optimizations(self):
        """Inicializa optimizaciones de rendimiento para reducir lag"""

        # Cache de posiciones para evitar recálculos innecesarios
        self._position_cache = {}  # {connection_id: (last_start_pos, last_end_pos, cached_segments)}
        self._cache_threshold = 5  # Diferencia mínima para considerar cambio significativo

        # Control de frecuencia de actualizaciones
        self._last_update_time = 0
        self._update_interval = 0.016  # ~60 FPS máximo (16ms)

        # Estadísticas de rendimiento
        self._recalc_count = 0
        self._cache_hits = 0
        self._cache_misses = 0

        # Modo de movimiento rápido - diferir recálculos
        self._fast_move_mode = False
        self._in_fast_move_mode = False  # Flag para bypass de throttling durante drag
        self._pending_updates = {}  # {component_id: [connection_ids]}

    def _update_position_cache(self, connection, segments):
        """Actualizar cache de posición para la conexión"""
        conn_id = id(connection)

        try:
            start_points = connection.start_component.get_connection_points_global()
            end_points = connection.end_component.get_connection_points_global()

            start_pos = start_points[connection.start_point_idx][:2]  # (x, y)
            end_pos = end_points[connection.end_point_idx][:2]        # (x, y)

            self._position_cache[conn_id] = (start_pos, end_pos, segments[:])

        except Exception as e:

            pass

    def clear_position_cache(self):
        """
        Limpiar el cache de posiciones para forzar recálculo de todas las conexiones.
        
        Este método debe llamarse cuando se cambia de hoja/lienzo para asegurar que
        todas las líneas se dibujen correctamente en la nueva hoja.
        """
        self._position_cache.clear()

    def _positions_changed_significantly(self, connection, threshold=None):
        """Verificar si las posiciones han cambiado significativamente"""
        if threshold is None:
            threshold = self._cache_threshold

        conn_id = id(connection)
        cached = self._position_cache.get(conn_id)

        if not cached:
            return True  # No hay cache, considerar como cambio

        try:
            start_points = connection.start_component.get_connection_points_global()
            end_points = connection.end_component.get_connection_points_global()

            current_start = start_points[connection.start_point_idx][:2]
            current_end = end_points[connection.end_point_idx][:2]

            cached_start, cached_end, _ = cached

            # Calcular distancias euclidianas
            start_diff = ((current_start[0] - cached_start[0])**2 +
                         (current_start[1] - cached_start[1])**2)**0.5
            end_diff = ((current_end[0] - cached_end[0])**2 +
                       (current_end[1] - cached_end[1])**2)**0.5

            # Si cualquiera cambió significativamente, actualizar
            return start_diff > threshold or end_diff > threshold

        except Exception as e:

            pass
            return True

    def _should_update_now(self):
        """Verificar si es momento de actualizar (control de frecuencia)"""
        import time
        current_time = time.time()

        if current_time - self._last_update_time >= self._update_interval:
            self._last_update_time = current_time
            return True

        return False

    def _batch_update_connections(self, component):
        """Actualizar múltiples conexiones de un componente de forma eficiente"""
        # BYPASS THROTTLING: Durante drag activo, actualizar inmediatamente
        if not self._in_fast_move_mode and not self._should_update_now():
            # Agregar a lista de pendientes en lugar de actualizar inmediatamente
            comp_id = id(component)
            if comp_id not in self._pending_updates:
                self._pending_updates[comp_id] = []
            return True

        try:
            updated_count = 0
            connections_to_update = []

            # Recopilar todas las conexiones que necesitan actualización
            for connection in self.app.connections:
                if (connection.start_component == component or
                    connection.end_component == component):

                    # Durante fast move, usar threshold=0 para actualizar en cada píxel
                    threshold = 0 if self._in_fast_move_mode else self._cache_threshold
                    if self._positions_changed_significantly(connection, threshold=threshold):
                        connections_to_update.append(connection)

            if not connections_to_update:
                self._cache_hits += 1
                return True

            # Actualizar todas las conexiones en un solo lote
            for connection in connections_to_update:
                self._recalculate_connection_segments_fast(connection)
                self._redraw_connection_fast(connection)
                updated_count += 1

            return True

        except Exception as e:

            pass
            return False

    def _process_pending_updates(self):
        """Procesar actualizaciones pendientes al final del movimiento"""
        if not self._pending_updates:
            return

        try:
            total_updated = 0

            for comp_id, connection_ids in self._pending_updates.items():
                # Encontrar el componente (esto es una simplificación)
                component = None
                for comp in getattr(self.app, 'components', []):
                    if id(comp) == comp_id:
                        component = comp
                        break

                if component:
                    for conn in self.app.connections:
                        if id(conn) in connection_ids:
                            self._recalculate_connection_segments_fast(conn)
                            self._redraw_connection_fast(conn)
                            total_updated += 1

            if total_updated > 0:
                pass

        except Exception as e:

            pass
        finally:
            self._pending_updates.clear()

    def _calculate_orthogonal_path(self, start_x, start_y, end_x, end_y,
                                   ref_start_x=None, ref_end_x=None,
                                   ref_start_y=None, ref_end_y=None,
                                   start_orient=None, end_orient=None):
        """
        Calcular ruta ortogonal óptima entre dos puntos.
        MANTIENE PARALELISMO con giros escalonados (Staggered).

        Args:
            start_x, start_y: Punto inicial
            end_x, end_y: Punto final
            ref_start_x, ref_end_x, ref_start_y, ref_end_y: Puntos de referencia (centros)

        Returns:
            list: Lista de segmentos [(start, end),...]
        """
        # Usar puntos de referencia si existen para coordinar el punto de giro central
        calc_start_x = ref_start_x if ref_start_x is not None else start_x
        calc_end_x = ref_end_x if ref_end_x is not None else end_x
        calc_start_y = ref_start_y if ref_start_y is not None else start_y
        calc_end_y = ref_end_y if ref_end_y is not None else end_y

        dx = abs(end_x - start_x)
        dy = abs(end_y - start_y)

        # Caso especial: línea recta perfecta -> devolver un solo segmento directo
        if dy < 2:  # Perfectamente horizontales (fase.svg alineados)
            return [((start_x, start_y), (end_x, end_y))]
        if dx < 2:  # Perfectamente verticales
            return [((start_x, start_y), (end_x, end_y))]

        # Si tenemos orientación, usarla para decidir; si no, regla original
        if start_orient in ['N', 'S']:
            use_hvh = False
        elif start_orient in ['E', 'O', 'W']:
            use_hvh = True
        else:
            use_hvh = (dx >= dy)

        if use_hvh:
            # Patrón Horizontal-Vertical-Horizontal (H-V-H)
            # ESCALONADO: Solo si el desplazamiento vertical (quiebre) es significativo (> 5px)
            # Esto evita el efecto escalera cuando los componentes están perfectamente alineados
            y_offset = (start_y - calc_start_y) if abs(end_y - start_y) > 5 else 0
            mid_x = (calc_start_x + calc_end_x) // 2 + y_offset

            segments = [
                ((start_x, start_y), (mid_x, start_y)),      # Horizontal inicial
                ((mid_x, start_y), (mid_x, end_y)),          # Vertical central
                ((mid_x, end_y), (end_x, end_y))             # Horizontal final
            ]
        else:
            # Patrón Vertical-Horizontal-Vertical (V-H-V)
            # ESCALONADO: Solo si el desplazamiento horizontal (quiebre) es significativo (> 5px)
            x_offset = (start_x - calc_start_x) if abs(end_x - start_x) > 5 else 0
            mid_y = (calc_start_y + calc_end_y) // 2 + x_offset

            segments = [
                ((start_x, start_y), (start_x, mid_y)),      # Vertical inicial
                ((start_x, mid_y), (end_x, mid_y)),          # Horizontal central
                ((end_x, mid_y), (end_x, end_y))             # Vertical final
            ]

        return segments

    def _normalize_point_orientation(self, point_orient):
        """Normaliza la orientación de un punto de conexión a un código N/S/E/O."""
        if point_orient is None:
            return 'N'

        # Casos comunes: objeto con atributo orientation, string directo o tupla (x, y, orientation)
        if hasattr(point_orient, 'orientation'):
            return str(getattr(point_orient, 'orientation', 'N')).upper()

        if isinstance(point_orient, str):
            return point_orient.upper()

        if isinstance(point_orient, (tuple, list)) and len(point_orient) >= 3:
            return self._normalize_point_orientation(point_orient[2])

        return 'N'

    def _calculate_rotation_aware_manhattan(self, start_component, start_point_idx,
                                          end_component, end_point_idx,
                                          start_x, start_y, end_x, end_y,
                                          ref_start_x=None, ref_end_x=None,
                                          ref_start_y=None, ref_end_y=None):
        """
        Calcular ruta Manhattan adaptada a componentes rotados
        MANTIENE PARALELISMO con giros escalonados (Staggered).

        Genera formas "L", "Γ", "Z" según las orientaciones rotadas de los puntos

        Args:
            start_component, start_point_idx: Componente y punto inicial
            end_component, end_point_idx: Componente y punto final  
            start_x, start_y: Coordenadas del punto inicial
            end_x, end_y: Coordenadas del punto final
            ref_start_x, ref_end_x, ref_start_y, ref_end_y: Puntos de referencia

        Returns:
            list: Lista de segmentos [(start, end),...] adaptados a rotación
        """
        try:
            # Usar puntos de referencia si existen
            calc_start_x = ref_start_x if ref_start_x is not None else start_x
            calc_end_x = ref_end_x if ref_end_x is not None else end_x
            calc_start_y = ref_start_y if ref_start_y is not None else start_y
            calc_end_y = ref_end_y if ref_end_y is not None else end_y
            # Obtener orientaciones de los puntos (ya calculadas con rotación)
            start_points = start_component.get_connection_points_global()
            end_points = end_component.get_connection_points_global()

            start_point = start_points[start_point_idx]
            end_point = end_points[end_point_idx]

            # Extraer información de orientación del punto rotado; no asumir que sea un string literal
            start_orientation = self._normalize_point_orientation(start_point[2] if len(start_point) > 2 else 'N')
            end_orientation = self._normalize_point_orientation(end_point[2] if len(end_point) > 2 else 'N')
            if start_orientation not in ['N', 'S', 'E', 'O']:
                start_orientation = 'N'
            if end_orientation not in ['N', 'S', 'E', 'O']:
                end_orientation = 'N'

            start_rotation = getattr(start_component, 'rotation', 0)
            end_rotation = getattr(end_component, 'rotation', 0)

            # Determinar patrón basado en orientaciones y rotaciones
            segments = []

            # Caso 1: Ambos componentes sin rotación (fallback al método tradicional)
            if start_rotation == 0 and end_rotation == 0:
                return self._calculate_orthogonal_path(
                    start_x, start_y, end_x, end_y,
                    ref_start_x=calc_start_x, ref_end_x=calc_end_x,
                    ref_start_y=calc_start_y, ref_end_y=calc_end_y,
                    start_orient=start_orientation, end_orient=end_orientation
                )

            # Caso 2: Un componente rotado - crear forma "L" adaptada
            if start_rotation != 0 and end_rotation == 0:
                actual_start_cx = start_component.x + start_component.size[0] / 2
                actual_start_cy = start_component.y + start_component.size[1] / 2
                has_stagger = (abs(calc_start_x - actual_start_cx) > 1) or (abs(calc_start_y - actual_start_cy) > 1)

                if start_orientation in ['N', 'S']:
                    if has_stagger:
                        x_offset = start_x - calc_start_x
                        mid_y = (actual_start_cy + calc_end_y) // 2 + x_offset
                        segments = [
                            ((start_x, start_y), (start_x, mid_y)),
                            ((start_x, mid_y), (end_x, mid_y)),
                            ((end_x, mid_y), (end_x, end_y))
                        ]
                    else:
                        mid_x = start_x
                        mid_y = end_y
                        segments = [
                            ((start_x, start_y), (mid_x, start_y)),
                            ((mid_x, start_y), (mid_x, mid_y)),
                            ((mid_x, mid_y), (end_x, end_y))
                        ]
                else:
                    if has_stagger:
                        y_offset = start_y - calc_start_y
                        mid_x = (actual_start_cx + calc_end_x) // 2 + y_offset
                        segments = [
                            ((start_x, start_y), (mid_x, start_y)),
                            ((mid_x, start_y), (mid_x, end_y)),
                            ((mid_x, end_y), (end_x, end_y))
                        ]
                    else:
                        mid_x = end_x
                        mid_y = start_y
                        segments = [
                            ((start_x, start_y), (start_x, mid_y)),
                            ((start_x, mid_y), (mid_x, mid_y)),
                            ((mid_x, mid_y), (end_x, end_y))
                        ]

            # Caso 3: Componente final rotado - crear forma "L" adaptada
            elif start_rotation == 0 and end_rotation != 0:
                actual_end_cx = end_component.x + end_component.size[0] / 2
                actual_end_cy = end_component.y + end_component.size[1] / 2
                has_stagger = (abs(calc_end_x - actual_end_cx) > 1) or (abs(calc_end_y - actual_end_cy) > 1)

                if end_orientation in ['N', 'S']:
                    if has_stagger:
                        x_offset = end_x - calc_end_x
                        mid_y = (calc_start_y + actual_end_cy) // 2 + x_offset
                        segments = [
                            ((start_x, start_y), (start_x, mid_y)),
                            ((start_x, mid_y), (end_x, mid_y)),
                            ((end_x, mid_y), (end_x, end_y))
                        ]
                    else:
                        mid_x = end_x
                        mid_y = start_y
                        segments = [
                            ((start_x, start_y), (start_x, mid_y)),
                            ((start_x, mid_y), (mid_x, mid_y)),
                            ((mid_x, mid_y), (end_x, end_y))
                        ]
                else:
                    if has_stagger:
                        y_offset = end_y - calc_end_y
                        mid_x = (calc_start_x + actual_end_cx) // 2 + y_offset
                        segments = [
                            ((start_x, start_y), (mid_x, start_y)),
                            ((mid_x, start_y), (mid_x, end_y)),
                            ((mid_x, end_y), (end_x, end_y))
                        ]
                    else:
                        mid_x = start_x
                        mid_y = end_y
                        segments = [
                            ((start_x, start_y), (mid_x, start_y)),
                            ((mid_x, start_y), (mid_x, mid_y)),
                            ((mid_x, mid_y), (end_x, end_y))
                        ]

            # Caso 4: Ambos componentes rotados - crear forma "Z" compleja
            else:
                start_is_vertical = start_orientation in ['N', 'S']
                end_is_vertical = end_orientation in ['N', 'S']

                if start_is_vertical and end_is_vertical:
                    stagger = 0
                    if getattr(start_component, 'svg_file', '') == 'fase.svg':
                        stagger = start_x - calc_start_x
                    elif getattr(end_component, 'svg_file', '') == 'fase.svg':
                        stagger = end_x - calc_end_x
                    mid_y = (calc_start_y + calc_end_y) // 2 + stagger
                    segments = [
                        ((start_x, start_y), (start_x, mid_y)),
                        ((start_x, mid_y), (end_x, mid_y)),
                        ((end_x, mid_y), (end_x, end_y))
                    ]
                elif not start_is_vertical and not end_is_vertical:
                    stagger = 0
                    if getattr(start_component, 'svg_file', '') == 'fase.svg':
                        stagger = start_y - calc_start_y
                    elif getattr(end_component, 'svg_file', '') == 'fase.svg':
                        stagger = end_y - calc_end_y
                    mid_x = (calc_start_x + calc_end_x) // 2 + stagger
                    segments = [
                        ((start_x, start_y), (mid_x, start_y)),
                        ((mid_x, start_y), (mid_x, end_y)),
                        ((mid_x, end_y), (end_x, end_y))
                    ]
                elif start_is_vertical:
                    segments = [
                        ((start_x, start_y), (start_x, end_y)),
                        ((start_x, end_y), (end_x, end_y))
                    ]
                else:
                    segments = [
                        ((start_x, start_y), (end_x, start_y)),
                        ((end_x, start_y), (end_x, end_y))
                    ]

            # Caso 5: Conexión a líneas de fases (componentes pueden tener líneas fasor)
            # Verificar si los puntos de conexión son para líneas fasor
            start_has_fasor = hasattr(start_component, 'get_fasor_lines') and start_point_idx >= len(start_points) - 4
            end_has_fasor = hasattr(end_component, 'get_fasor_lines') and end_point_idx >= len(end_points) - 4

            if start_has_fasor or end_has_fasor:
                # Para conexiones fasor, usar ruta simplificada y directa
                return self._calculate_orthogonal_path(
                    start_x, start_y, end_x, end_y,
                    ref_start_x=calc_start_x, ref_end_x=calc_end_x,
                    ref_start_y=calc_start_y, ref_end_y=calc_end_y
                )

            return segments

        except Exception as e:
            # En caso de error, fallback al método tradicional
            return self._calculate_orthogonal_path(start_x, start_y, end_x, end_y)

    def _get_fase_stagger_offset(self, connection):
        """Calcula el desplazamiento de escalonamiento para conexiones de fase (L1, L2, L3, N, PE)."""
        fase_comp = None
        if hasattr(connection, 'start_component') and hasattr(connection.start_component, 'svg_file') and connection.start_component.svg_file == "fase.svg":
            fase_comp = connection.start_component
        elif hasattr(connection, 'end_component') and hasattr(connection.end_component, 'svg_file') and connection.end_component.svg_file == "fase.svg":
            fase_comp = connection.end_component

        if not fase_comp:
            return 0

        label_name = ""
        if hasattr(fase_comp, 'label_data') and isinstance(fase_comp.label_data, dict):
            label_name = str(fase_comp.label_data.get('name', '')).upper().strip()
        if not label_name and hasattr(fase_comp, 'name'):
            label_name = str(fase_comp.name).upper().strip()

        fase_order = {
            "L1": 0, "R": 0, "U": 0, "1": 0, "FASE 1": 0, "FASE1": 0,
            "L2": 1, "S": 1, "V": 1, "2": 1, "FASE 2": 1, "FASE2": 1,
            "L3": 2, "T": 2, "W": 2, "3": 2, "FASE 3": 2, "FASE3": 2,
            "N": 3, "NEU": 3, "NEUTRO": 3, "NEUTRAL": 3, "4": 3,
            "PE": 4, "GND": 4, "TIERRA": 4, "GROUND": 4, "5": 4
        }
        stagger_idx = fase_order.get(label_name, None)
        if stagger_idx is None:
            try:
                all_fases = [c for c in getattr(self.app, 'components', []) if getattr(c, 'svg_file', '') == "fase.svg"]
                col_fases = [c for c in all_fases if abs(c.x - fase_comp.x) < 25 or abs(c.y - fase_comp.y) < 25]
                col_fases.sort(key=lambda c: (c.x, c.y))
                if fase_comp in col_fases:
                    stagger_idx = col_fases.index(fase_comp)
                else:
                    stagger_idx = 0
            except Exception:
                stagger_idx = 0

        spacing = 20
        try:
            if hasattr(self.app, 'snap_to_grid_enabled') and self.app.snap_to_grid_enabled.get():
                spacing = 25
        except Exception:
            pass

        return stagger_idx * spacing

    def _rebuild_fase_clone_segments(self, connection):
        """
        Reconstruye la geometría canónica de un clon de fase para conservar la forma
        y la ortogonalidad cuando se mueven la fase y/o el conxn (solos o agrupados).

        Eje 'x' (fase vertical): escalera en L reconstruida desde los pines actuales
        (la fase va a su columna y el conxn conserva el mismo X un escalón más abajo).

        Eje 'y' (fase horizontal): ruta ortogonal entre los pines actuales SIN el
        escalonamiento de fases, para evitar que el stagger deforme el clon.

        Returns:
            bool: True si se pudo reconstruir la geometría
        """
        try:
            start_points = connection.start_component.get_connection_points_global()
            end_points = connection.end_component.get_connection_points_global()
            if (not start_points or not end_points or
                    connection.start_point_idx >= len(start_points) or
                    connection.end_point_idx >= len(end_points)):
                return False

            start_pt = start_points[connection.start_point_idx]
            end_pt = end_points[connection.end_point_idx]
            s_x, s_y = start_pt[0], start_pt[1]
            e_x, e_y = end_pt[0], end_pt[1]

            if s_x != e_x and s_y != e_y:
                corner = (s_x, e_y) if s_x < e_x else (e_x, s_y)
                connection.segments = [
                    ((s_x, s_y), corner),
                    (corner, (e_x, e_y)),
                ]
                return True

            template_segments = getattr(connection, 'fase_clone_template_segments', None)
            if template_segments:
                template_x, template_y = template_segments[0][0]
                dx = s_x - template_x
                dy = s_y - template_y
                connection.segments = [
                    ((x1 + dx, y1 + dy), (x2 + dx, y2 + dy))
                    for ((x1, y1), (x2, y2)) in template_segments
                ]
                return True

            if getattr(connection, 'fase_clone_axis', 'x') == 'x':
                # Fase vertical: escalera en L idéntica a la línea madre
                connection.segments = [
                    ((s_x, s_y), (s_x, e_y)),
                    ((s_x, e_y), (e_x, e_y)),
                ]
                return True

            # Fase horizontal: ruta ortogonal sin escalonamiento
            start_rotation = getattr(connection.start_component, 'rotation', 0)
            end_rotation = getattr(connection.end_component, 'rotation', 0)
            start_orient = self._normalize_point_orientation(
                start_pt[2] if len(start_pt) > 2 else 'N')
            end_orient = self._normalize_point_orientation(
                end_pt[2] if len(end_pt) > 2 else 'N')

            start_cx = connection.start_component.x + connection.start_component.size[0] / 2
            start_cy = connection.start_component.y + connection.start_component.size[1] / 2
            end_cx = connection.end_component.x + connection.end_component.size[0] / 2
            end_cy = connection.end_component.y + connection.end_component.size[1] / 2

            if start_rotation != 0 or end_rotation != 0:
                connection.segments = self._calculate_rotation_aware_manhattan(
                    connection.start_component, connection.start_point_idx,
                    connection.end_component, connection.end_point_idx,
                    s_x, s_y, e_x, e_y,
                    ref_start_x=start_cx, ref_end_x=end_cx,
                    ref_start_y=start_cy, ref_end_y=end_cy
                )
            else:
                connection.segments = self._calculate_orthogonal_path(
                    s_x, s_y, e_x, e_y,
                    ref_start_x=start_cx, ref_end_x=end_cx,
                    ref_start_y=start_cy, ref_end_y=end_cy,
                    start_orient=start_orient, end_orient=end_orient
                )
            return True

        except Exception:
            return False

    def _recalculate_connection_segments_fast(self, connection):
        """
        Versión rápida de recalculado (sin prints debug)

        Args:
            connection: Conexión a recalcular
        """
        try:
            start_component = connection.start_component
            end_component = connection.end_component
            is_fase_conxn = {
                getattr(start_component, 'svg_file', ''),
                getattr(end_component, 'svg_file', '')
            } == {'fase.svg', 'conxn.svg'}
            if is_fase_conxn:
                start_points = start_component.get_connection_points_global()
                end_points = end_component.get_connection_points_global()
                if (start_points and end_points and
                        connection.start_point_idx < len(start_points) and
                        connection.end_point_idx < len(end_points)):
                    start_x, start_y = start_points[connection.start_point_idx][:2]
                    end_x, end_y = end_points[connection.end_point_idx][:2]
                    if start_x != end_x and start_y != end_y:
                        corner = ((start_x, end_y) if start_x < end_x
                                  else (end_x, start_y))
                        connection.segments = [
                            ((start_x, start_y), corner),
                            (corner, (end_x, end_y)),
                        ]
                        self._update_position_cache(connection, connection.segments)
                        return True

            # Recalcular ante cualquier cambio de posición. Con threshold=2 el
            # recálculo se saltaba cuando la corrección era de 1-2 px y el
            # quiebre quedaba congelado en los segmentos viejos.
            if not self._positions_changed_significantly(connection, threshold=0):
                return True

            # CLON DE FASE: reconstruir geometría canónica para no deformar el clon
            if getattr(connection, 'fase_clone_axis', None):
                if self._rebuild_fase_clone_segments(connection):
                    self._update_position_cache(connection, connection.segments)
                    return True

            # Obtener coordenadas actuales
            start_points = connection.start_component.get_connection_points_global()
            start_pt = start_points[connection.start_point_idx]
            start_x, start_y = start_pt[0], start_pt[1]
            start_orient = self._normalize_point_orientation(start_pt[2] if len(start_pt) > 2 else 'N')

            end_points = connection.end_component.get_connection_points_global()
            end_pt = end_points[connection.end_point_idx]
            end_x, end_y = end_pt[0], end_pt[1]
            end_orient = self._normalize_point_orientation(end_pt[2] if len(end_pt) > 2 else 'N')

            # Recalcular segmentos
            if hasattr(connection, 'manual_angle_points') and connection.manual_angle_points:
                all_points = [(start_x, start_y)] + connection.manual_angle_points + [(end_x, end_y)]
                connection.segments = []
                # Crear segmentos ortogonales L-shaped para líneas manuales
                for i in range(len(all_points) - 1):
                    x1, y1 = all_points[i]
                    x2, y2 = all_points[i + 1]

                    # ALGORITMO ORTOGONAL: Crear camino en L (90°) - mismo que preview
                    mid_x = x2
                    mid_y = y1

                    # Primer segmento: horizontal
                    connection.segments.append(((x1, y1), (mid_x, mid_y)))

                    # Segundo segmento: vertical
                    connection.segments.append(((mid_x, mid_y), (x2, y2)))
            else:
                start_cx = connection.start_component.x + connection.start_component.size[0] / 2
                start_cy = connection.start_component.y + connection.start_component.size[1] / 2
                end_cx = connection.end_component.x + connection.end_component.size[0] / 2
                end_cy = connection.end_component.y + connection.end_component.size[1] / 2

                # ESCALONAMIENTO PARA FASES: Ajustar centro de referencia para evitar superposición
                fase_stagger = self._get_fase_stagger_offset(connection)
                if fase_stagger:
                    fase_comp = None
                    if getattr(getattr(connection, 'start_component', None), 'svg_file', '') == 'fase.svg':
                        fase_comp = connection.start_component
                    elif getattr(getattr(connection, 'end_component', None), 'svg_file', '') == 'fase.svg':
                        fase_comp = connection.end_component
                    fase_rotation = getattr(fase_comp, 'rotation', 0) if fase_comp else 0
                    is_vertical_fase = fase_rotation % 180 != 0

                    if getattr(connection.start_component, 'svg_file', '') == 'fase.svg':
                        if is_vertical_fase:
                            start_cx -= fase_stagger
                        else:
                            start_cy -= fase_stagger
                    else:
                        if is_vertical_fase:
                            end_cx -= fase_stagger
                        else:
                            end_cy -= fase_stagger

                # CRITERIO DE APLICACIÓN: Detectar si algún componente tiene rotación
                start_rotation = getattr(connection.start_component, 'rotation', 0)
                end_rotation = getattr(connection.end_component, 'rotation', 0)

                if start_rotation != 0 or end_rotation != 0:
                    # Usar algoritmo adaptativo para componentes rotados
                    connection.segments = self._calculate_rotation_aware_manhattan(
                        connection.start_component, connection.start_point_idx,
                        connection.end_component, connection.end_point_idx,
                        start_x, start_y, end_x, end_y,
                        ref_start_x=start_cx, ref_end_x=end_cx,
                        ref_start_y=start_cy, ref_end_y=end_cy
                    )
                else:
                    # CONDUCTA TRADICIONAL: Usar algoritmo estándar preservado exactamente
                    connection.segments = self._calculate_orthogonal_path(
                        start_x, start_y, end_x, end_y,
                        ref_start_x=start_cx, ref_end_x=end_cx,
                        ref_start_y=start_cy, ref_end_y=end_cy,
                        start_orient=start_orient, end_orient=end_orient
                    )

            self._update_position_cache(connection, connection.segments)
            return True

        except Exception as e:

            pass
            return False

    def _redraw_connection(self, connection):
        """
        Redibuja una conexión en el canvas

        """
        try:
            if getattr(connection, 'fase_clone_axis', None):
                self._rebuild_fase_clone_segments(connection)

            if ({getattr(connection.start_component, 'svg_file', ''),
                 getattr(connection.end_component, 'svg_file', '')} == {'fase.svg', 'conxn.svg'}
                    and not getattr(connection, 'fase_clone_axis', None)
                    and not getattr(connection, 'fase_clone_template_segments', None)):
                start_points = connection.start_component.get_connection_points_global()
                end_points = connection.end_component.get_connection_points_global()
                if start_points and end_points:
                    start_x, start_y = start_points[connection.start_point_idx][:2]
                    end_x, end_y = end_points[connection.end_point_idx][:2]
                    if start_x != end_x and start_y != end_y:
                        connection.segments = [
                            ((start_x, start_y), (end_x, start_y)),
                            ((end_x, start_y), (end_x, end_y)),
                        ]

            # Si ya hay segmentos definidos Y la conexión es manualmente modificada
            # (ej: inserción de empalme), NO recalcular para preservar geometría exacta
            has_segments = hasattr(connection, 'segments') and connection.segments
            is_manually_modified = getattr(connection, 'manually_modified', False)

            if has_segments and is_manually_modified:
                # Solo redibujar sin recalcular
                self._redraw_connection_fast(connection)
            else:
                # Recalcular normalmente (caso normal cuando se mueve un componente)
                if not self._recalculate_connection_segments_fast(connection):
                    pass
                self._redraw_connection_fast(connection)

        except Exception as e:

            pass
            import traceback
            traceback.print_exc()

    def _redraw_connection_fast(self, connection):
        """
        Versión optimizada de redibujado (sin logs debug)

        Args:
            connection: Conexión a redibujar
        """
        try:
            line_color = getattr(connection, 'line_color', 'black')
            line_width = getattr(connection, 'line_width', 1)
            line_dash_str = getattr(connection, 'line_dash', "")

            # ADAPTAR COLOR PARA TEMA (CRÍTICO para N y PE)
            from utils.utility_functions import adapt_color_for_display
            line_color = adapt_color_for_display(line_color, self.app.canvas.cget("bg"))

            # CORREGIR: Convertir string de patrón a tuple para Tkinter
            from config.settings import AppConstants
            line_dash_pattern = AppConstants.DASH_PATTERNS.get(line_dash_str, "")

            # CORRECCIÓN ZOOM: Obtener zoom_level del canvas dinámicamente
            zoom_level = getattr(self.app.canvas, 'zoom_level', 1.0)

            line_ids = getattr(connection, 'line_ids', None) or []
            segments = connection.segments

            # si ya existen en el canvas tantas líneas como
            # segmentos, actualizar coordenadas con canvas.coords en lugar de
            # borrar y recrear todos los items (caso típico del arrastre).
            # Se verifica por tag con find_withtag (NO por len(line_ids)):
            # tras canvas.delete("all") (p. ej. al cambiar de hoja o generar
            # tabla de cableado) los ids quedan huérfanos y Tk hace coords/
            # itemconfig como no-ops SILENCIOSOS, dejando la línea sin dibujar.
            try:
                valid_ids = self.app.canvas.find_withtag(f"connection_{id(connection)}")
            except Exception:
                valid_ids = ()

            if len(valid_ids) == len(segments) and segments and line_ids:
                line_ids = list(valid_ids)
                connection.line_ids = line_ids
                try:
                    style_key = (line_color, line_width, line_dash_pattern)
                    if getattr(connection, '_last_style', None) != style_key:
                        for line_id in line_ids:
                            self.app.canvas.itemconfig(
                                line_id, fill=line_color, width=line_width, dash=line_dash_pattern
                            )
                        connection._last_style = style_key
                    for i, (start, end) in enumerate(segments):
                        self.app.canvas.coords(
                            line_ids[i],
                            start[0] * zoom_level, start[1] * zoom_level,
                            end[0] * zoom_level, end[1] * zoom_level
                        )
                    # Solo actualizar canvas si no está en modo de movimiento rápido
                    if not self._fast_move_mode:
                        self.app.canvas.update()
                    return True
                except Exception:
                    # IDs huérfanos o inválidos: reconstruir las líneas desde cero
                    pass

            # Limpiar líneas existentes más eficientemente
            for line_id in line_ids:
                try:
                    self.app.canvas.delete(line_id)
                except Exception:
                    pass

            connection.line_ids = []

            # Dibujar todos los segmentos en una sola operación batch
            for i, (start, end) in enumerate(segments):
                line_id = self.app.canvas.create_line(
                    start[0] * zoom_level, start[1] * zoom_level,
                    end[0] * zoom_level, end[1] * zoom_level,
                    fill=line_color, width=line_width, dash=line_dash_pattern,
                    tags=(f"connection_{id(connection)}", f"segment_{i}")
                )
                connection.line_ids.append(line_id)

            connection._last_style = (line_color, line_width, line_dash_pattern)

            # Solo actualizar canvas si no está en modo de movimiento rápido
            if not self._fast_move_mode:
                self.app.canvas.update()

        except Exception as e:

            pass

    def update_all_connections_for_component(self, component, exclude_connection=None):
        """
        Actualizar todas las conexiones de un componente

        """
        try:
            # Usar batch update inteligente
            return self._batch_update_connections(component)

        except Exception as e:

            pass
    def start_fast_move_mode(self):
        """Activar modo de movimiento rápido (diferir actualizaciones)"""
        self._fast_move_mode = True
        self._in_fast_move_mode = True # Bypass throttling durante drag

    def end_fast_move_mode(self):
        """Finalizar modo de movimiento rápido (procesar actualizaciones pendientes)"""
        self._fast_move_mode = False
        self._in_fast_move_mode = False # Restaurar throttling
        # Fast Move finalizado

        # Procesar todas las actualizaciones pendientes
        self._process_pending_updates()
        self.app.canvas.update()

    # Functions consolidated below with proper implementation

    # FUNCIONES ADICIONALES COMPLETANDO EL SISTEMA

    # Function moved to proper implementation locations
    # Function consolidated with proper implementation
    def find_line_at_position(self, x, y, tolerance=5):
        """
        Encontrar línea en posición específica.

        Args:
            x, y: Posición a buscar
            tolerance: Tolerancia para detección

        Returns:
            tuple: (connection, segment_idx) o None si no se encuentra
        """
        try:
            from core.segment_operations import SegmentOperations
            if not hasattr(self, 'segment_ops'):
                self.segment_ops = SegmentOperations(self.app)

            return self.segment_ops.find_line_at_position(x, y, tolerance)
        except Exception as e:

            pass
            return None

    def update_manhattan_line(self, connection):
        """
        Actualizar línea Manhattan - RESPETA LÍNEAS MANUALES
        CORRECCIÓN: La preservación de ángulos manuales ya está en _recalculate_connection_segments_fast()

        Returns:
            Connection: Conexión actualizada
        """
        try:
            # SOLO REDIBUJAR: La lógica de preservación de ángulos ya existe en _recalculate_connection_segments_fast()
            # _recalculate_connection_segments_fast() ya preserva manual_angle_points correctamente

            # Marcar como modificada manualmente para preservar forma
            if hasattr(connection, 'manual_angle_points') and connection.manual_angle_points:
                connection.manually_modified = True

            # Re-dibujar la conexión (ángulos preservados automáticamente)
            self._redraw_connection(connection)
            return connection

        except Exception as e:

            pass
            return connection

    def draw_connection_lines(self, connection):
        """
        Dibujar líneas de conexión - compatibilidad con ManhattanRouter

        Returns:
            bool: True si se drew correctamente
        """
        try:
            pass

            # Usar el método de redibujado del sistema unificado
            self._redraw_connection(connection)
            return True

        except Exception as e:

            pass
            return False

    def is_active(self):
        """
        Verificar si el manual routing está activo - compatibilidad con sistema anterior

        Returns:
            bool: True si manual routing está activo
        """
        return self.manual_active

    def activate(self, component, point_idx):
        """
        Activar manual routing - compatibilidad con sistema anterior

        Returns:
            bool: True si se activó correctamente
        """
        return self.activate_manual_routing(component, point_idx)

# FUNCIONES DE COMPATIBILIDAD PARA MIGRACIÓN GRADUAL

_global_unified_system = None

def get_unified_line_system(app):
    """
    Obtener instancia singleton del sistema unificado de líneas.

    Esta función proporciona compatibilidad con el sistema anterior.
    Mapea ManhattanRouter a UnifiedLineSystem.
    """
    global _global_unified_system
    if _global_unified_system is None:
        _global_unified_system = UnifiedLineSystem(app)

    return _global_unified_system

def get_manhattan_router(app):
    """
    Alias de compatibilidad - mapea ManhattanRouter a UnifiedLineSystem.

    Args:
        app: Aplicación principal (debe tener atributo 'canvas')

    Returns:
        UnifiedLineSystem: Instancia del sistema unificado
    """
    return get_unified_line_system(app)

"""
Controlador principal de simulación
Maneja el estado global de la simulación (Play/Stop/Pause)
y el bloqueo de edición durante la simulación.
"""

# Atributos dinámicos que la simulación escribe en los componentes.
# Deben volver a su valor de reposo al detener para no dejar residuos visuales.
_DYNAMIC_RESET = {
    'is_active': False,
    'volt_pct': 0.0,
    'current_volt_pct': 0.0,
    'current_rpm': 0.0,
    'current_freq': 0.0,
    'current_position': 0,
    'analog_speed_pct': 0.0,
    'layer_running': False,
    'motor_direction': 0,
    'is_driven': False,
    'voltage': None,
    'motor_fault': None,
    'motor_temp': 'NORMAL',
    'last_update_time': None,
    'ramp_pct': 0.0,
}

# Tags de overlays dinámicos dibujados ENCIMA del componente durante la simulación.
# Se borran explícitamente al detener para no dejar texto flotando sobre el esquema.
_DYNAMIC_TAGS = ('vdf_metrics_{0}', 'ssf_metrics_{0}', 'motor_metrics_{0}')

class SimulationController:
    """
    Controlador principal del sistema de simulación.
    Maneja el ciclo de vida de la simulación y el bloqueo de edición.
    """

    def __init__(self, app):
        """
        Inicializa el controlador de simulación.
        
        Args:
            app: Referencia a la aplicación principal (PlanoElectrico)
        """
        self.app = app
        self.is_running = False
        self.is_paused = False
        self._blink_id = None  # ID del timer de parpadeo
        self._step_id = None   # ID del timer del tick de simulación

        # ESTADO GLOBAL DE SEÑALES (Cross-Page)
        # Diccionario: { page_index: { "K1": True, "K2": False } }
        self.global_signal_state = {}

    def update_page_signals(self, page_index, signals_dict):
        """
        Actualiza el estado de las señales de una página específica.
        Se llama al salir de una página.
        """
        self.global_signal_state[page_index] = signals_dict

    def get_all_active_signals(self):
        """
        Obtiene un set de todos los nombres de señales activas en páginas INACTIVAS.
        Usado por behavior_manager para saber qué bobinas externas están ON.
        """
        active_names = set()
        for page_idx, signals in self.global_signal_state.items():
            for name, is_active in signals.items():
                if is_active:
                    active_names.add(name)
        return active_names

    def start(self):
        """
        Inicia la simulación.

        Returns:
            bool: True si se inició correctamente
        """
        if not self.is_running:
            self.is_running = True
            self.is_paused = False
            self._disable_editing()
            self._update_status("🎬 Simulación en ejecución", "green")
            self._start_blinking()
            self._run_simulation_step()
            return True
        return False

    def stop(self, keep_error_message=False):
        """
        Detiene la simulación y habilita edición.
        """
        self.is_running = False
        self.is_paused = False
        self._stop_blinking()
        self._cancel_pending_step()

        # Limpiar señales globales al detener
        self.global_signal_state = {}

        self._reset_simulation_state()
        self._enable_editing()
        if not keep_error_message:
            self._update_status("⏹️ Simulación detenida", "black")

    def _cancel_pending_step(self):
        """Cancela el tick pendiente para que no se reancle la simulación al parar."""
        if self._step_id is not None:
            try:
                self.app.root.after_cancel(self._step_id)
            except Exception:
                pass
            self._step_id = None

    def _reset_simulation_state(self):
        """
        Resetea TODOS los componentes y visuales a estado inicial (OFF).

        IMPORTANTE — el trabajo sobre el canvas se hace ÚNICAMENTE con los objetos de
        la hoja que está en pantalla (self.app.components / self.app.connections).
        Los componentes y conexiones de las demás hojas existen en memoria pero sus
        IDs de canvas fueron invalidados al hacer delete("all") en switch_to_sheet;
        dibujarlos o repintarlos aquí dejaría imágenes fantasma de otras hojas sobre el
        esquema actual (contaminación visual) y, al reutilizarse los IDs de Tk,
        podría recolorear líneas ajenas.
        """
        canvas = getattr(self.app, 'canvas', None)
        visible_components = list(getattr(self.app, 'components', []) or [])
        visible_component_ids = set(id(c) for c in visible_components)
        visible_connections = list(getattr(self.app, 'connections', []) or [])

        # Tags de overlays a borrar de la hoja visible (se borran en un solo
        # round-trip con Tk al final, en vez de 3 llamadas por componente).
        overlay_tags = []

        # 1. Estado dinámico de componentes de TODAS las hojas (solo datos, sin canvas)
        all_components = self.app.get_all_project_components()
        for comp in all_components:
            # ¿Algún atributo dinámico se apartó del reposo? Si todos ya están en
            # reposo, la imagen en pantalla también: no hace falta re-renderizar
            # (load_image+draw costaba ~15 ms por componente: cientos de ms al parar).
            dirty = False
            for attr, default in _DYNAMIC_RESET.items():
                if hasattr(comp, attr):
                    try:
                        if getattr(comp, attr) != default:
                            dirty = True
                        setattr(comp, attr, default)
                    except Exception:
                        pass

            # 2. Quitar overlays dinámicos (VDF / SST-C / métricas de motor).
            #    Se borran por tag: draw() sólo limpia label_{id} y points_{id}.
            if canvas is not None and id(comp) in visible_component_ids:
                overlay_tags.extend(tag_fmt.format(id(comp)) for tag_fmt in _DYNAMIC_TAGS)

            # 3. Recargar el SVG en estado de reposo.
            # load_image() sólo renderiza el SVG a PIL/PhotoImage (además de leer
            # canvas.cget("bg") para el modo oscuro): NO dibuja nada, así que es seguro
            # correrlo para componentes de cualquier hoja. Es indispensable hacerlo en
            # TODAS: load_image() hornea las capas ON/OFF según el is_active del
            # momento, así que un componente de otra hoja energizado conserva en su
            # 'photo' la imagen encendida y switch_to_sheet la vuelca tal cual al
            # volver (draw() sólo copia el photo cacheado, no reevalúa el estado).
            # El draw() sí queda limitado a la hoja visible: dibujar componentes
            # ajenos dejaría imágenes fantasma sobre el esquema actual.
            # Sólo se re-renderiza lo que de verdad cambió (dirty).
            if dirty and hasattr(comp, 'load_image') and getattr(comp, 'svg_path', None):
                try:
                    comp.load_image(comp.svg_path)
                    if id(comp) in visible_component_ids and hasattr(comp, 'draw'):
                        comp.draw()
                except Exception:
                    pass

        if canvas is not None and overlay_tags:
            try:
                canvas.delete(*overlay_tags)
            except Exception:
                pass

        # 4. Restaurar el estilo original de las líneas de la hoja visible
        if canvas is not None:
            for conn in visible_connections:
                line_ids = getattr(conn, 'line_ids', None)
                if not line_ids:
                    continue
                color = getattr(conn, 'line_color', 'black') or 'black'
                width = getattr(conn, 'line_width', 1.0)
                dash = getattr(conn, 'line_dash', None)
                for line_id in line_ids:
                    try:
                        if dash:
                            canvas.itemconfig(line_id, fill=color, width=width, dash=dash)
                        else:
                            canvas.itemconfig(line_id, fill=color, width=width, dash='')
                    except Exception:
                        # El ID ya no existe en el canvas (hoja cambiada): ignorar
                        pass

        # 5. Limpiar cachés de simulación para evitar estado sucio en el próximo arranque
        # bfs_cache: caché del último resultado de propagación BFS
        #    Vive en self.app para sobrevivir entre ticks; debe limpiarse al detener.
        # _sim_line_style: estilo de línea ya aplicado por _update_visuals.
        #    Se limpia aquí porque el paso 4 acabó de restaurar los colores originales
        #    directamente sobre el canvas, sin pasar por esa caché.
        for attr in ('_bfs_cache', '_sim_line_style'):
            if hasattr(self.app, attr):
                try:
                    getattr(self.app, attr).clear()
                except Exception:
                    pass

        # 6. Limpiar flags temporales de visibilidad y el mapa de hojas del tick
        for attr in ('_visible_components_only', '_visible_connections_only', '_sim_sheet_map'):
            if hasattr(self.app, attr):
                try:
                    delattr(self.app, attr)
                except Exception:
                    pass

    def pause(self):
        """
        Pausa la simulación.

        Returns:
            bool: True si estaba corriendo y quedó pausada
        """
        if not self.is_running or self.is_paused:
            return False

        self.is_paused = True
        self._update_status("⏸️ Simulación pausada", "orange")
        self._cancel_blink_timer()
        self._cancel_pending_step()
        if hasattr(self.app, 'sim_blink_label'):
            self.app.sim_blink_label.config(text="⏸️ PAUSADA", fg="orange")
            self.app.sim_blink_label.pack(side="left", padx=15, pady=5)
        return True

    def resume(self):
        """
        Reanuda la simulación pausada.

        Returns:
            bool: True si estaba pausada y volvió a correr
        """
        if not self.is_running or not self.is_paused:
            return False

        self.is_paused = False
        self._update_status("▶️ Simulación reanudada", "green")
        self._start_blinking()
        if self._step_id is None:
            self._run_simulation_step()
        return True

    def toggle(self):
        """
        Alterna entre Play y Pause.

        Returns:
            bool: True si está corriendo después del toggle
        """
        if not self.is_running:
            return self.start()
        if self.is_paused:
            self.resume()
            return True
        self.pause()
        return False

    def _disable_editing(self):
        """
        Deshabilita todas las funciones de edición durante la simulación.
        """
        app = self.app
        app.simulation_mode = True

        if app.selected_component:
            app.selected_component.selected = False
            app.selected_component = None

        if hasattr(app, 'selected_elements'):
            for elem in app.selected_elements:
                if hasattr(elem, 'selected'):
                    elem.selected = False
            app.selected_elements.clear()

        if hasattr(app, 'selected_connection'):
            app.selected_connection = None
            app.selected_segment = None
            if hasattr(app, 'clear_connection_highlights'):
                app.clear_connection_highlights()

        app.connection_mode = False
        app.connection_start = None
        if hasattr(app, 'shape_drawing'):
            app.shape_drawing.cancel()

        app.canvas.config(cursor="arrow")
        print("🔒 Modo Simulación: Edición deshabilitada")

    def _enable_editing(self):
        """
        Habilita nuevamente las funciones de edición.
        """
        self.app.simulation_mode = False
        print("🔓 Modo Edición: Habilitado")

    def _update_status(self, text, color, duration=3000):
        """
        Actualiza el estado visual en la barra de estado.
        Errores (rojo) se muestran en MAYÚSCULAS.
        duration=None deja el mensaje fijo hasta que otro evento lo cambie
        (se usa para las fallas, que el usuario debe poder leer con calma).
        """
        if hasattr(self.app, 'set_status'):
            display_text = text.upper() if color == "red" else text
            self.app.set_status(display_text, color, duration)

    def _start_blinking(self):
        """Inicia el parpadeo del aviso de simulación."""
        self._stop_blinking()
        if hasattr(self.app, 'sim_blink_label'):
            self.app.sim_blink_label.config(text="⚡ SIMULACIÓN EN EJECUCIÓN", fg="red")
            self.app.sim_blink_label.pack(side="left", padx=15, pady=5)
            self._blink_step(True)

    def _stop_blinking(self):
        """Detiene el parpadeo del aviso de simulación."""
        self._cancel_blink_timer()
        if hasattr(self.app, 'sim_blink_label'):
            self.app.sim_blink_label.pack_forget()
            self.app.sim_blink_label.config(text="", fg="black")

    def _cancel_blink_timer(self):
        """Cancela solo el temporizador de parpadeo, sin tocar la etiqueta."""
        if self._blink_id is not None:
            try:
                self.app.root.after_cancel(self._blink_id)
            except Exception:
                pass
            self._blink_id = None

    def _blink_step(self, visible):
        """Alterna la visibilidad del aviso para crear efecto de parpadeo."""
        if not self.is_running or self.is_paused:
            if hasattr(self.app, 'sim_blink_label'):
                self.app.sim_blink_label.pack_forget()
            return
        if visible:
            if hasattr(self.app, 'sim_blink_label'):
                self.app.sim_blink_label.config(text="⚡ SIMULACIÓN EN EJECUCIÓN", fg="red")
        else:
            if hasattr(self.app, 'sim_blink_label'):
                self.app.sim_blink_label.config(text="", fg="black")
        self._blink_id = self.app.root.after(500, lambda: self._blink_step(not visible))

    # LÓGICA DE SIMULACIÓN

    def _format_fault_message(self, conflicts):
        """
        Divide la falla en dos partes para la barra de estado:

        Returns:
            tuple: (rotulo_alerta, detalle, color)
        - rótulo_alerta: el tipo de falla (" CORTOCIRCUITO"), que va en el
                  label de alerta con parpadeo en video inverso.
                - detalle: hoja, componente y naturaleza, en el label normal.
                - color: rojo para cortocircuito/conflicto, naranja paraderivación.
        """
        first = conflicts[0]

        # Rótulo de alerta: el título sin el emoji del separador, en mayúsculas
        titulo = str(first.get('title') or 'CORTOCIRCUITO').upper()
        detalle = f"Hoja \"{first.get('sheet', 'Hoja ?')}\" | " \
                  f"{first.get('designator', 'DESCONOCIDO')}"

        tipo = first.get('component_name', '')
        if tipo and tipo.upper() != str(first.get('designator', '')).upper():
            detalle += f" ({tipo})"
        detalle += f": {first.get('detail', '')}"

        # Los cortocircuitos y los conflictos AC/DC son rojos; unaderivación a
        # tierra es una advertencia (ámbar) para que no se confunda con un corto.
        color = "#d32f2f" if "TERRA" not in titulo else "#e07b00"

        total = len(conflicts)
        if total > 1:
            otras = sorted({c.get('sheet', 'Hoja ?') for c in conflicts[1:] if c.get('sheet')})
            sufijo = f" | +{total - 1} más en: {', '.join(otras)}" if otras else f" | +{total - 1} más"
            detalle += sufijo

        return titulo, detalle + " — ⛔ SIMULACIÓN DETENIDA", color

    def _run_simulation_step(self):
        """
        Ejecuta un paso de la simulación.
        Se llama periódicamente mientras is_running es True.
        """
        if not self.is_running or self.is_paused:
            self._step_id = None
            return

        self._step_id = None
        fault_alert = None

        try:
            all_components = self.app.get_all_project_components()
            all_connections = self.app.get_all_project_connections()

            self.app._visible_components_only = set(id(c) for c in self.app.components)
            self.app._visible_connections_only = set(id(c) for c in self.app.connections)

            from simulation.energy_propagation import EnergyPropagator
            propagator = EnergyPropagator(self.app)

            # Mapa id(componente) -> hoja, congelado ANTES del swap para que los
            # mensajes de falla indiquen la hoja correcta aunque self.app.components
            # esté temporalmente reemplazado por el agregado de todas las hojas.
            # ANTES y no después: build_component_sheet_map() usa self.components
            # para la hoja activa, así que si se construyera con el agregado ya
            # puesto le adjudicaría TODOS los componentes a la hoja activa y la
            # propagación de energía los creería de la misma página (una fase
            # saltaría a otra hoja y los cortes no se respetarían).
            if hasattr(self.app, 'build_component_sheet_map'):
                self.app._sim_sheet_map = self.app.build_component_sheet_map()

            old_components = self.app.components
            old_connections = self.app.connections
            self.app.components = all_components
            self.app.connections = all_connections

            try:
                network_state = propagator.propagate()

                from simulation.short_circuit_detector import ShortCircuitDetector
                short_detector = ShortCircuitDetector(self.app)
                conflicts = short_detector.detect(network_state)

                if conflicts:
                    # Se recuerda la falla y se detiene DESPUÉS del finally: parar
                    # aquí redibujaría los componentes de las demás hojas sobre el
                    # canvas de la hoja actual (imágenes fantasma) y recolorearía
                    # líneas con IDs de canvas ya reciclados por Tk.
                    fault_alert = self._format_fault_message(conflicts)
                else:
                    from simulation.component_behavior import ComponentBehaviorManager
                    behavior_manager = ComponentBehaviorManager(self.app)
                    behavior_manager.update_behaviors(network_state)

                    from simulation.plc_logic import PLCLogicManager
                    plc_manager = PLCLogicManager(self.app)
                    plc_manager.update(network_state)

                    from simulation.driver_logic import DriverLogicManager
                    driver_manager = DriverLogicManager(self.app)
                    driver_manager.update(network_state)

                    from simulation.motor_logic import MotorLogic
                    motor_logic = MotorLogic(self.app)
                    for comp in all_components:
                        is_motor = False
                        if hasattr(comp, 'category') and comp.category == 'Motors':
                            is_motor = True
                        elif hasattr(comp, 'svg_file') and comp.svg_file and 'motor' in comp.svg_file.lower() and 'circuit-breaker' not in comp.svg_file.lower():
                            is_motor = True
                        if is_motor:
                            motor_logic.analyze_motor(comp, network_state)

                    self._update_visuals(network_state, only_visible=True)

            finally:
                self.app.components = old_components
                self.app.connections = old_connections
                if hasattr(self.app, '_visible_components_only'):
                    del self.app._visible_components_only
                if hasattr(self.app, '_visible_connections_only'):
                    del self.app._visible_connections_only
                if hasattr(self.app, '_sim_sheet_map'):
                    del self.app._sim_sheet_map

            if fault_alert:
                # Falla: primero parar (y limpiar el canvas), después reportar, para que
                # ningún efecto secundario del reset pise el mensaje de la falla.
                # Se hace fuera del swap para no contaminar el canvas con otras hojas.
                self.stop(keep_error_message=True)

                rotulo, detalle, color = fault_alert
                if hasattr(self.app, 'show_fault_status'):
                    # show_fault_status enclava el mensaje: sobrevive a las refrescas
                    # periódicas de la barra que antes lo pisaban con "Listo".
                    self.app.show_fault_status(detalle, rotulo, color)
                else:
                    self._update_status(detalle, "red", duration=None)
                return

            self._step_id = self.app.root.after(100, self._run_simulation_step)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._step_id = None
            self._update_status(f"❌ Error: {str(e)}", "red", duration=None)
            self.stop(keep_error_message=True)

    def _update_visuals(self, network_state, only_visible=False):
        """
        Actualiza el color de las líneas basado en el estado de la red.
        network_state: {(id(comp), point_idx): set(potentials)}
        """
        PHASE_COLORS = {
            'L1': '#8B4513',
            'L2': '#000000',
            'L3': '#808080',
            'N':  '#0000FF',
            'PE': '#00FF00',
            '+':      '#FF0000',
            '+24V':   '#FF0000',
            '+24VDC': '#FF0000',
            '+24DCV': '#FF0000',
            '+V':     '#FF0000',
            '-':      '#0000EE',
            'GND':    '#0000EE',
            '0V':     '#0000EE',
            'NEG':    '#0000EE',
        }

        # Estilo ya aplicado en el tick anterior: {(id(conn), line_ids): (color, width)}.
        # Sin esto se hacían cientos de itemconfig() por tick (10 veces por segundo)
        # aunque el color no hubiera cambiado, lo que saturaba a Tk.
        styling = getattr(self.app, '_sim_line_style', None)
        if styling is None:
            styling = {}
            self.app._sim_line_style = styling

        for conn in self.app.connections:
            if only_visible and hasattr(self.app, '_visible_connections_only'):
                if id(conn) not in self.app._visible_connections_only:
                    continue

            start_key = (id(conn.start_component), conn.start_point_idx)
            potentials = network_state.get(start_key, set())

            color = 'black'
            width = 1.0

            if potentials:
                if len(potentials) > 1:
                    color = 'red'
                    width = 3.0
                else:
                    pot = list(potentials)[0]
                    color = PHASE_COLORS.get(pot, 'red')
                    width = 2.0

            if hasattr(conn, 'line_ids'):
                line_ids = conn.line_ids
                if not line_ids:
                    continue
                # line_ids forma parte de la clave: si las líneas se redibujaron
                # (cambio de hoja) los IDs nuevos fuerzan el repintado.
                style_key = (id(conn), tuple(line_ids))
                if styling.get(style_key) == (color, width):
                    continue
                styling[style_key] = (color, width)
                for line_id in line_ids:
                    self.app.canvas.itemconfig(line_id, fill=color, width=width)

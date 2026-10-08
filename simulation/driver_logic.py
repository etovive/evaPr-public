import time

class DriverLogicManager:
    def __init__(self, app):
        self.app = app

    def update(self, network_state):
        """Actualiza todos los controladores en el proyecto."""
        ssf_states = {} # {name: {'is_ready': bool, 'is_running': bool, 'volt_pct': float}}
        vdf_states = {} # {name: {'is_active': bool, 'is_running': bool, 'direction': int, 'freq': float}}
        vdf_power_status = {} # {name: bool}

        # 1. Identificar componentes y estados base
        for comp in self.app.components:
            fname = (getattr(comp, 'svg_file', '') or '').lower()
            name = self._get_label(comp)

            if "sst-c" in fname:
                state = self._analyze_sst_c(comp, network_state)
                ssf_states[name] = state

            elif "vdf-e" in fname:
                # VDF-E: Verificar alimentación (R, S, T -> L1, L2, L3)
                has_power = False
                for idx in [0, 1, 2]:
                    pots = network_state.get((id(comp), idx), set())
                    if any(p in ['L1', 'L2', 'L3'] for p in pots):
                        has_power = True
                        break
                vdf_power_status[name] = has_power

            elif "power_supply_dc" in fname:
                self._analyze_power_supply(comp, network_state)

            elif "power_supply_ac" in fname:
                self._analyze_power_supply_ac(comp, network_state)

        # 2. Analizar VDF-C (con alimentación interna desde VDF-E)
        for comp in self.app.components:
            fname = (getattr(comp, 'svg_file', '') or '').lower()
            if "vdf-c" in fname:
                name = self._get_label(comp)
                is_powered = vdf_power_status.get(name, False)
                state = self._analyze_vdf_c(comp, network_state, is_powered)
                vdf_states[name] = state

        # 3. Aplicar estados a las unidades de potencia
        for comp in self.app.components:
            fname = (getattr(comp, 'svg_file', '') or '').lower()
            name = self._get_label(comp)

            if "sst-e" in fname and name in ssf_states:
                state = ssf_states[name]

                # ACTIVACIÓN: Flag 'is_active' representa el BYPASS (Luz Verde/Full Voltage)
                # Se activa solo al completar la rampa.
                new_active = state['is_ready'] and state['is_running'] and state['volt_pct'] >= 99.0

                comp.volt_pct = state['volt_pct']

                if getattr(comp, 'is_active', False) != new_active:
                    comp.is_active = new_active
                    if hasattr(comp, 'load_image'):
                        comp.load_image(comp.svg_path)
                        if hasattr(comp, 'draw'):
                            if not hasattr(self.app, '_visible_components_only') or id(comp) in self.app._visible_components_only:
                                comp.draw()

            elif "vdf-e" in fname and name in vdf_states:
                state = vdf_states[name]
                # VDF-E conduce cuando está en marcha Y tiene frecuencia
                new_active = state['is_running'] and state['freq'] > 0

                if getattr(comp, 'is_active', False) != new_active:
                    comp.is_active = new_active
                    if hasattr(comp, 'load_image'):
                        comp.load_image(comp.svg_path)
                        if hasattr(comp, 'draw'):
                            if not hasattr(self.app, '_visible_components_only') or id(comp) in self.app._visible_components_only:
                                comp.draw()

                comp.motor_direction = state['direction']
                comp.current_freq = state['freq']

        # 4. Vincular rampa/frecuencia a los motores físicos
        self._update_driven_motors(network_state)

    def _update_driven_motors(self, network_state):
        """Busca motores alimentados por drivers y les transmite la rampa/frecuencia."""
        power_units = []
        for comp in self.app.components:
            fname = (getattr(comp, 'svg_file', '') or '').lower()
            if "sst-e" in fname or "vdf-e" in fname:
                power_units.append(comp)

        for comp in self.app.components:
            fname = (getattr(comp, 'svg_file', '') or '').lower()
            if "motor" in fname:
                if not getattr(comp, 'is_active', False):
                    # Si no tiene energía, resetear
                    comp.current_rpm = 0
                    comp.current_volt_pct = 0
                    continue

                # Buscar si alguna de sus fases (terminales 0, 1, 2) viene de un driver
                found_driver = None
                for drv in power_units:
                    # El driver debe estar transmitiendo energía (Bypass o Rampa)
                    is_conducting = getattr(drv, 'is_active', False) or getattr(drv, 'volt_pct', 0) > 0 or getattr(drv, 'current_freq', 0) > 0
                    if not is_conducting: continue

                    # Intersección de potenciales entre entrada motor y salida driver
                    motor_pots = set()
                    for m_idx in [0, 1, 2]: motor_pots.update(network_state.get((id(comp), m_idx), set()))

                    drv_pots = set()
                    for d_idx in [4, 5, 6]: drv_pots.update(network_state.get((id(drv), d_idx), set()))

                    if motor_pots.intersection(drv_pots):
                        found_driver = drv
                        break

                motor_nom_rpm = float(comp.label_data.get('vdf_motor_rpm', 1500))
                if not found_driver:
                    comp.current_rpm = motor_nom_rpm
                    comp.current_volt_pct = 100.0
                    comp.current_volt_pct = 100.0
                    if hasattr(comp, 'is_driven'): del comp.is_driven # Resetear flag
                else:
                    comp.is_driven = True # Marca para evitar que MotorLogic lo sobreescriba
                    drv_fname = (getattr(found_driver, 'svg_file', '') or '').lower()
                    if "sst" in drv_fname:
                        pct = getattr(found_driver, 'volt_pct', 100.0)
                        comp.current_rpm = motor_nom_rpm * (pct / 100.0)
                        comp.current_volt_pct = pct
                        comp.motor_direction = getattr(found_driver, 'motor_direction', 1 if pct > 0 else 0)

                        if not comp.is_active and pct > 0:
                            comp.is_active = True
                            if hasattr(comp, 'load_image'): comp.load_image(comp.svg_path)
                            if hasattr(comp, 'draw'): comp.draw()
                    else:
                        freq = getattr(found_driver, 'current_freq', 0.0)
                        comp.current_rpm = motor_nom_rpm * (abs(freq) / 60.0)

                        # FORZAR REVERSA: Si la dirección es -1, RPM negativas para visualización
                        direction = getattr(found_driver, 'motor_direction', 0)
                        if direction == -1:
                            comp.current_rpm *= -1

                        # Detectar cambios visuales para forzar redibujado
                        old_dir = getattr(comp, 'motor_direction', 0)
                        old_active = getattr(comp, 'is_active', False)

                        comp.current_volt_pct = 100.0
                        comp.motor_direction = direction

                        # Si cambia dirección o actividad, redibujar SVG (capas ACTIVA-L/R)
                        should_redraw = (old_dir != direction) or (not old_active and abs(freq) > 0)

                        if abs(freq) > 0:
                            comp.is_active = True
                        else:
                            comp.is_active = False # Si freq es 0, desactivar
                            should_redraw = should_redraw or old_active # Si estaba activo y pasa a inactivo, redibujar

                        if should_redraw:
                            if hasattr(comp, 'load_image'): comp.load_image(comp.svg_path)
                            if hasattr(comp, 'draw'): comp.draw()

    def _get_label(self, comp):
        """Obtiene la etiqueta principal (Marca o Nombre) para vinculación."""
        if hasattr(comp, 'label_data') and comp.label_data:
            m = comp.label_data.get('Marca', '').strip().upper()
            if m: return m
            return comp.label_data.get('name', '').strip().upper()
        return getattr(comp, 'name', '').strip().upper()

    def _analyze_sst_c(self, comp, network_state):
        """Lógica para el Soft Starter Control (SST-C)."""
        points = comp.get_connection_points_global()
        if not points or len(points) < 3:
            return {'is_ready': False, 'is_running': False, 'volt_pct': 0}

        # Identificación geométrica: IN(top-left), A1(top-right), A2(bottom)
        sorted_by_y = sorted(enumerate(points), key=lambda x: x[1][1])
        top_points = sorted_by_y[:2]
        a2_idx = sorted_by_y[2][0]

        top_sorted_by_x = sorted(top_points, key=lambda x: x[1][0])
        in_idx = top_sorted_by_x[0][0]
        a1_idx = top_sorted_by_x[1][0]

        pots_a1 = network_state.get((id(comp), a1_idx), set())
        pots_a2 = network_state.get((id(comp), a2_idx), set())
        pots_in = network_state.get((id(comp), in_idx), set())

        # 1. READY (ACTIVA) -> Alimentación A1-A2
        is_ready = bool(pots_a1 and pots_a2 and not pots_a1.intersection(pots_a2))

        # 2. RUN (ACTIVA 2) -> Mando en IN
        dc_pos = {'+', '24V', '24VDC', 'V+', 'VCC', 'POS'}
        dc_neg = {'-', '0V', '0VDC', 'V-', 'GND', 'NEG', 'N'}
        def has_potential(p_set):
            return any(p in ['L1', 'L2', 'L3', 'N'] or p in dc_pos or p in dc_neg for p in p_set)

        is_running = bool(pots_in and has_potential(pots_in))

        changed = False
        if getattr(comp, 'is_active', False) != is_ready:
            comp.is_active = is_ready
            changed = True
        if getattr(comp, 'layer_running', False) != is_running:
            comp.layer_running = is_running
            changed = True

        if changed and hasattr(comp, 'load_image'):
            comp.load_image(comp.svg_path)
            if hasattr(comp, 'draw'): comp.draw()

        if is_ready and hasattr(comp, 'draw_ssf_display'):
            if not hasattr(self.app, '_visible_components_only') or id(comp) in self.app._visible_components_only:
                comp.draw_ssf_display()

        # Rampa basada en TIEMPO REAL
        current_time = time.time()
        last_time = getattr(comp, 'last_update_time', current_time)
        dt = current_time - last_time
        comp.last_update_time = current_time

        # Recuperar estado actual
        current_pct = getattr(comp, 'current_volt_pct', 0.0)

        # Evitar saltos excesivos solo si es el primer frame o una pausa muy larga (>1s)
        if dt > 1.0: dt = 0.0

        def get_cfg(keys, default):
            for k in keys:
                val = comp.label_data.get(k)
                if val is not None:
                    try: return float(val)
                    except: pass
            return default

        start_t = get_cfg(['ssf_start_time', 'tiempo_arranque', 'arranque_t'], 5.0)
        stop_t = get_cfg(['ssf_stop_time', 'tiempo_paro', 'paro_t'], 5.0)
        init_v = get_cfg(['ssf_init_volt_pct', 'tension_inicial', 'voltaje_init'], 30.0)

        # Evitar división por cero
        if start_t < 0.1: start_t = 0.1
        if stop_t < 0.1: stop_t = 0.1

        # Calcular cambio por segundo (%/s)
        inc_rate = (100.0 - init_v) / start_t  # Sube desde init_v hasta 100
        dec_rate = 100.0 / stop_t

        step_inc = inc_rate * dt
        step_dec = dec_rate * dt

        if is_running and is_ready:
            if current_pct < 100:
                if current_pct < init_v: current_pct = init_v
                current_pct = min(100.0, current_pct + step_inc)
        else:
            if current_pct > 0:
                current_pct = max(0.0, current_pct - step_dec)

        comp.current_volt_pct = current_pct
        return {'is_ready': is_ready, 'is_running': is_running, 'volt_pct': current_pct}

    def _analyze_vdf_c(self, comp, network_state, is_powered):
        """Lógica del Variador de Frecuencia (VDF-C).
        
        VDF-C y VDF-E son el mismo equipo físicamente.
        El terminal + tiene alimentación INTERNA desde VDF-E.
        """
        if not is_powered:
            comp.is_active = False
            comp.current_freq = 0.0
            comp.layer_running = False
            if hasattr(comp, 'draw_vdf_display'):
                if not hasattr(self.app, '_visible_components_only') or id(comp) in self.app._visible_components_only:
                    comp.draw_vdf_display()
            return {'is_active': False, 'is_running': False, 'direction': 0, 'freq': 0.0}

        # VDF-C se energiza cuando VDF-E tiene alimentación
        comp.is_active = True

        # CLAVE: El terminal + (índice 6) tiene alimentación INTERNA del VDF-E
        # No necesita conexión externa, se energiza automáticamente
        internal_plus_potential = {'+VDF_INTERNAL'}

        # Entradas digitales: I1(2), I2(3), I3(4), I4(5)
        pots_i1 = network_state.get((id(comp), 2), set())
        pots_i2 = network_state.get((id(comp), 3), set())
        pots_i3 = network_state.get((id(comp), 4), set())
        pots_i4 = network_state.get((id(comp), 5), set())

        # Terminal + (índice 6) - inyectar potencial interno
        pots_plus = network_state.get((id(comp), 6), set())
        if not pots_plus:
            pots_plus = internal_plus_potential
            network_state[(id(comp), 6)] = pots_plus

        # Verificar si cada entrada está conectada al +
        def is_input_active(pots_in):
            if not pots_in: return False
            return bool(pots_in.intersection(pots_plus))

        i1 = is_input_active(pots_i1)
        i2 = is_input_active(pots_i2)
        i3 = is_input_active(pots_i3)
        i4 = is_input_active(pots_i4)

        # Dirección: I1=adelante, I2=reversa (Prioridad Reversa si ambos activos)
        if i2:
            direction = -1
            is_running = True
        elif i1:
            direction = 1
            is_running = True
        else:
            direction = 0
            is_running = False

        # OVERRIDE ANALÓGICO: Si está habilitado, el slider arranca el equipo
        use_analog = comp.label_data.get('vdf_analog_enabled', False)
        if use_analog and not is_running:
            # Si hay consigna de velocidad en el slider, asumimos comando de marcha (Forward)
            if getattr(comp, 'analog_speed_pct', 0.0) > 0:
                is_running = True
                direction = 1 # Forward por defecto en modo local/analógico

        nom_rpm = float(comp.label_data.get('vdf_motor_rpm', 1800))

        # Velocidades: I3, I4, I3+I4 O Control Analógico
        target_freq = 0.0

        # use_analog ya definido arriba
        # use_analog ya definido arriba

        if is_running:
            if use_analog:
                # MODO ANALÓGICO: Slider (0-100%) escala sobre Frecuencia Máxima
                pct = getattr(comp, 'analog_speed_pct', 0.0)
                max_f = float(comp.label_data.get('vdf_max_freq', 60.0))
                target_freq = (pct / 100.0) * max_f
            else:
                # MODO DIGITAL: Presets I3/I4
                target_input_val = 0.0

                if i3 and i4:
                    target_input_val = float(comp.label_data.get('vdf_speed_3', 60))
                elif i4:
                    target_input_val = float(comp.label_data.get('vdf_speed_2', 45))
                elif i3:
                    target_input_val = float(comp.label_data.get('vdf_speed_1', 30))

                # Conversión Heurística (RPM vs Hz)
                # Si input > 65, asumimos RPM. Si no, asumimos Hz.
                if target_input_val > 65:
                     target_freq = (target_input_val / nom_rpm) * 60.0
                else:
                     target_freq = target_input_val

        # Rampa de aceleración/deceleración basada en TIEMPO REAL
        current_time = time.time()
        if not hasattr(comp, 'last_update_time'):
            comp.last_update_time = current_time
            dt = 0.0
        else:
            last_time = comp.last_update_time
            dt = current_time - last_time
            comp.last_update_time = current_time

        # Evitar saltos grandes si el delta es demasiado grande (ej: pausa larga)
        if dt > 1.0: dt = 0.0

        curr_f = getattr(comp, 'current_freq', 0.0)
        acc_r = float(comp.label_data.get('vdf_accel_ramp', 5))
        dec_r = float(comp.label_data.get('vdf_decel_ramp', 5))

        # LÓGICA DE RAMPA SOLICITADA POR USUARIO: "5 seg para llegar a esa velocidad"
        # Esto significa que la pendiente es (Target / Tiempo).
        # A diferencia del industrial (Max / Tiempo), aquí ajustamos la rampa al target actual.

        # Evitar división por cero
        if acc_r < 0.1: acc_r = 0.1
        if dec_r < 0.1: dec_r = 0.1

        # Usamos target_freq como referencia de escala para el tiempo solicitado
        ref_freq_acc = max(target_freq, 0.1) if target_freq > 0 else 60.0
        ref_freq_dec = max(curr_f, 0.1) if curr_f > 0 else 60.0 # Al frenar, usamos la velocidad actual como referencia de "todo"

        # Pendiente = Delta / Tiempo.
        # Si queremos ir de 0 a Target en 'acc_r' segundos:
        acc_step = (ref_freq_acc / acc_r) * dt

        # Frenado: ir de Current a 0 en 'dec_r' segundos
        # Si frenamos desde la velocidad actual, tomamos esa como referencia
        dec_step = (60.0 / dec_r) * dt # Fallback a estándar para frenado si target es 0
        if target_freq == 0 and curr_f > 0:
             # Frenado puro hacia STOP
             # Si queremos detenernos en dec_r segundos DESDE AHORA:
             # dec_step = (curr_f / dec_r) * dt <-- Esto haría una curva exponencial (Zeno).
             # Mejor usar una pendiente lineal fija basada en el pico alcanzado o Max.
             # Para complacer al usuario: "tarda 5seg en frenar" -> Usar MaxFreq como referencia estándar o
             # interpretar que desde SU velocidad actual tarda 5seg.
             # Probemos estándar lineal escalado:
             dec_step = (60.0 / dec_r) * dt
        else:
             dec_step = (60.0 / dec_r) * dt

        # Refinamiento solicitado: "Tarda X seg en llegar a ESA velocidad"
        # Si voy a 100 RPM, tardo 5s. Si voy a 500 RPM, tardo 5s.
        # Entonces el step siempre depende de target_freq.
        if target_freq > 0:
            acc_step = (target_freq / acc_r) * dt

        if curr_f < target_freq:
            curr_f = min(target_freq, curr_f + acc_step)
        elif curr_f > target_freq:
            curr_f = max(target_freq, curr_f - dec_step)

        comp.current_freq = curr_f

        # Calcular RPM para display
        nom_rpm = float(comp.label_data.get('vdf_motor_rpm', 1800))
        comp.current_rpm = (curr_f / 60.0) * nom_rpm

        if getattr(comp, 'layer_running', False) != is_running:
            comp.layer_running = is_running
            if hasattr(comp, 'load_image'):
                comp.load_image(comp.svg_path)
                if hasattr(comp, 'draw'): comp.draw()

        if hasattr(comp, 'draw_vdf_display'):
            if not hasattr(self.app, '_visible_components_only') or id(comp) in self.app._visible_components_only:
                comp.draw_vdf_display()

        return {'is_active': True, 'is_running': is_running, 'direction': direction, 'freq': curr_f}

    def _analyze_power_supply(self, comp, network_state):
        """Lógica para la fuente de poder DC (POWER_SUPPLY_DC)."""
        # Terminales de entrada AC: 4 (L), 5 (N)
        pots_l = network_state.get((id(comp), 4), set())
        pots_n = network_state.get((id(comp), 5), set())

        # Verificar si hay diferencia de potencial
        is_powered = False
        if pots_l and pots_n:
            if not pots_l.intersection(pots_n):
                is_powered = True

        if getattr(comp, 'is_active', False) != is_powered:
            comp.is_active = is_powered
            if hasattr(comp, 'load_image'):
                comp.load_image(comp.svg_path)
                if hasattr(comp, 'draw'): comp.draw()
    def _analyze_power_supply_ac(self, comp, network_state):
        """Lógica para la fuente de poder AC (POWER_SUPPLY_AC)."""
        # Terminales de entrada: 0, 1 (Top)
        pots_input1 = network_state.get((id(comp), 0), set())
        pots_input2 = network_state.get((id(comp), 1), set())

        # Verificar si hay diferencia de potencial
        is_powered = False
        if pots_input1 and pots_input2:
            # Si no hay intersección, hay diferencia de potencial (ej: L1-N o L1-L2)
            if not pots_input1.intersection(pots_input2):
                is_powered = True

        if getattr(comp, 'is_active', False) != is_powered:
            comp.is_active = is_powered
            if hasattr(comp, 'load_image'):
                comp.load_image(comp.svg_path)
                if hasattr(comp, 'draw'): comp.draw()

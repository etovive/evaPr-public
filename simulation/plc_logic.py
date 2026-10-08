"""
Lógica de Simulación para PLCs Delta DVP
Especializado en verificación de conexionado físico (Wiring).
"""

class PLCLogicManager:
    def __init__(self, app):
        self.app = app
        self.last_status_msg = ""
        self.error_shown_this_tick = False

    def update(self, network_state):
        """Analiza el estado de los PLCs y expansiones en el proyecto."""
        self.error_shown_this_tick = False

        # 1. Identificar componentes PLC
        plcs = []
        expansions = []

        for comp in self.app.components:
            fname = (getattr(comp, 'svg_file', '') or '').lower()
            if "dvp20sx2" in fname:
                plcs.append(comp)
            elif "dvp16sp" in fname:
                expansions.append(comp)

        # 2. Analizar PLCs principales
        for plc in plcs:
            self._analyze_dvp20sx2(plc, network_state)

        for exp in expansions:
            self._analyze_dvp16sp(exp, network_state, plcs)

    def _analyze_dvp20sx2(self, comp, network_state):
        """
        Reglas para PLC-DVP20SX2:
        - Alimentación 24VDC (Índices 36, 37)
        - S/S (Índice 2)
        - Entradas X0-X7 (Índices 3-10)
        - Salidas Y0-Y5 (Índices 13-18)
        - Comunes UP/ZP (Índices 11, 12)
        """
        # 1. VERIFICACIÓN DE PODER (Terminales 36, 37 son +24V y 0V en este SVG)
        pots_vplus = network_state.get((id(comp), 36), set())
        pots_vminus = network_state.get((id(comp), 37), set())

        all_pots = pots_vplus.union(pots_vminus)

        # Criterio de Componente Quemado (AC en DC)
        if any(p in ['L1', 'L2', 'L3', 'N'] for p in all_pots):
            self._report_error(comp, "❌ COMPONENTE QUEMADO: Voltaje AC detectado en terminales DC del PLC")
            return

        # Criterio de Voltaje Incorrecto
        is_powered = False
        if pots_vplus and pots_vminus:
            positives = {'+', '24V', '24VDC', '+24V', 'V+', '+V'}
            negatives = {'-', '0V', '0VDC', 'GND', 'V-', 'NEG', '0V'}

            has_pos = any(p in positives for p in pots_vplus)
            has_neg = any(p in negatives for p in pots_vminus)

            if has_pos and has_neg:
                is_powered = True
            else:
                self._report_error(comp, "❌ DISPOSITIVO INOPERANTE: Voltaje incorrecto (requiere 24VDC)")
                return

        comp.is_active = is_powered
        if not is_powered:
            return

        # 2. LÓGICA S/S (Índice 2)
        pots_ss = network_state.get((id(comp), 2), set())
        is_sink = any(p in {'+', '24V', '24VDC', 'V+'} for p in pots_ss)
        is_source = any(p in {'-', '0V', '0VDC', 'GND', '0V'} for p in pots_ss)

        # 3. VERIFICACIÓN DE ENTRADAS (X0-X7: 3-10)
        for i in range(3, 11):
            pots_x = network_state.get((id(comp), i), set())
            if pots_x:
                if not pots_ss:
                    # Falta referencia S/S pero hay señal en X
                    # No es un error fatal, pero la entrada no funcionará
                    pass
                elif is_sink: # S/S a +24V -> Se activa con 0V
                    if not any(p in {'-', '0V', '0VDC', 'GND', '0V'} for p in pots_x):
                        # Podría ser un error de lógica Sink/Source
                        pass
                elif is_source: # S/S a 0V -> Se activa con +24V
                    if not any(p in {'+', '24V', '24VDC', 'V+'} for p in pots_x):
                        pass

        # 4. VERIFICACIÓN DE SALIDAS (Y0-Y5: 13-18)
        # Comunes UP (11) y ZP (12)
        pots_up = network_state.get((id(comp), 11), set())
        pots_zp = network_state.get((id(comp), 12), set())

        if not pots_up or not pots_zp:
            # Si se intenta usar una salida sin alimentar los comunes
            for i in range(13, 19):
                if network_state.get((id(comp), i)):
                    pass

    def _analyze_dvp16sp(self, comp, network_state, main_plcs):
        """
        Módulo DVP16SP: 8 Entradas / 8 Salidas.
        - Requiere bus de comunicación.
        """
        # 1. VERIFICAR BUS DE COMUNICACIÓN (Se asume acoplado si existe un PLC principal)
        has_main_plc = len(main_plcs) > 0

        if not has_main_plc:
            self._report_error(comp, "❌ EXPANSIÓN INOPERANTE: No se detecta un PLC principal en el proyecto")
            comp.is_active = False
            return

        comp.is_active = True

        # 2. LÓGICA S/S de la expansión (Índice 0)
        pots_ss = network_state.get((id(comp), 0), set())
        # ... similar a PLC ...

    def _report_error(self, comp, msg):
        """Reporta error a la UI."""
        if self.error_shown_this_tick: return

        if hasattr(self.app, 'simulation_controller'):
            self.app.simulation_controller._update_status(msg, "red")
            self.error_shown_this_tick = True

        # Visual feedback on component
        if hasattr(comp, 'set_error_state'):
            comp.set_error_state(True)

        print(f"PLC SIM ERROR: {msg}")

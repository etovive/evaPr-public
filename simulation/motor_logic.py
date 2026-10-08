"""
Lógica de control para motores eléctricos (Trifásicos y Monofásicos).
Implementa reglas estrictas de física eléctrica IEC:
"""

_PHASE_ORDER = {'L1': 1, 'L2': 2, 'L3': 3}
_SEQ_CW  = {(1,2,3),(2,3,1),(3,1,2)}
_SEQ_CCW = {(3,2,1),(2,1,3),(1,3,2)}

class MotorLogic:
    def __init__(self, app):
        self.app = app

    # Punto de entrada principal
    def analyze_motor(self, motor, network_state):
        if not hasattr(motor, 'conn_points') or not motor.conn_points:
            return
        if getattr(motor, 'is_driven', False):
            return

        fname = (getattr(motor, 'svg_file', '') or '').lower()

        if 'motor-1p-dosi' in fname:
            self._analyze_m4_dosi(motor, network_state)
        elif 'motor-1pc' in fname:
            self._analyze_m5_dahlander(motor, network_state)
        elif 'motor-1p' in fname:
            self._analyze_m2_mono(motor, network_state)
        elif 'motor-3p-st' in fname:
            self._analyze_m6_star_delta(motor, network_state)
        elif 'motor-3pt' in fname:
            self._analyze_m3_tri(motor, network_state)
        elif 'motor-3p' in fname:
            self._analyze_m1_cap(motor, network_state)
        else:
            self._stop_motor(motor)

    # M2: motor-1p.svg — Monofásico sin capacitor, SOLO 110V fase+neutro
    def _analyze_m2_mono(self, motor, network_state):
        idx_u1, idx_v1 = self._get_top_two(motor)
        if idx_u1 is None:
            self._stop_motor(motor)
            return

        t_u1 = network_state.get((id(motor), idx_u1), set())
        t_v1 = network_state.get((id(motor), idx_v1), set())
        ph_u1 = {p for p in t_u1 if p in _PHASE_ORDER}
        ph_v1 = {p for p in t_v1 if p in _PHASE_ORDER}
        n_u1  = 'N' in t_u1
        n_v1  = 'N' in t_v1

        # Dos fases sin neutro = 220V -> BURNED
        if ph_u1 and ph_v1:
            self._fault(motor, 'BURNED',
                        f'⚠️ {self._label(motor)}: 220V en motor de 110V — QUEMADO')
            return

        if ph_u1 and n_v1:
            self._run_motor(motor, 1, 110)
        elif n_u1 and ph_v1:
            self._run_motor(motor, -1, 110)
        else:
            self._stop_motor(motor)

    # M1: motor-3p.svg — Monofásico 220V con capacitor interno V1–W1
    # 4 conn_points. Scan Y luego X:
    #   fila superior cy≈2.36: idx0=V1(x34), idx1=U1(x14), idx2=W1(x54)
    #   fila inferior cy≈65.4: idx3=PE(x54)
    # El capacitor es INTERNO al SVG entre V1 y W1 — no aparece en
    # network_state. La lógica correcta es:
    #   U1->L1, W1->L2 (o cualquier 2 fases distintas) -> gira
    #   V1 queda como aux capacitor, no necesita conexión externa.
    #   Dirección: L1 en U1 -> CW; L1 en W1 -> CCW
    def _analyze_m1_cap(self, motor, network_state):
        pts = motor.conn_points
        if len(pts) < 3:
            self._stop_motor(motor)
            return

        # Los 3 superiores ordenados por X: U1(x14), V1(x34), W1(x54)
        top3 = sorted(enumerate(pts[:3]), key=lambda x: x[1].x)
        idx_u1 = top3[0][0]   # x más pequeña = U1
        # top3[1] = V1 (terminal del capacitor, conexión externa opcional)
        idx_w1 = top3[2][0]   # x más grande = W1

        t_u1 = network_state.get((id(motor), idx_u1), set())
        t_w1 = network_state.get((id(motor), idx_w1), set())

        ph_u1 = {p for p in t_u1 if p in _PHASE_ORDER}
        ph_w1 = {p for p in t_w1 if p in _PHASE_ORDER}
        n_u1  = 'N' in t_u1
        n_w1  = 'N' in t_w1

        # Necesita dos potenciales distintos entre U1 y W1
        # Puede ser: fase+neutro (110V) o dos fases distintas (220V)
        if ph_u1 and ph_w1 and not (ph_u1 & ph_w1):
            # 220V entre dos fases distintas — correcto para este motor
            o_u = _PHASE_ORDER[list(ph_u1)[0]]
            o_w = _PHASE_ORDER[list(ph_w1)[0]]
            direction = 1 if o_u < o_w else -1
            self._run_motor(motor, direction, 220)
        elif ph_u1 and n_w1:
            self._run_motor(motor, 1, 110)
        elif n_u1 and ph_w1:
            self._run_motor(motor, -1, 110)
        else:
            self._stop_motor(motor)

    # M3: motor-3pT.svg — Trifásico estándar con PE
    def _analyze_m3_tri(self, motor, network_state):
        if len(motor.conn_points) < 3:
            self._stop_motor(motor)
            return

        top3 = sorted(enumerate(motor.conn_points[:3]), key=lambda x: x[1].x)
        idx_u = top3[0][0]
        idx_v = top3[1][0]
        idx_w = top3[2][0]

        t_u = network_state.get((id(motor), idx_u), set())
        t_v = network_state.get((id(motor), idx_v), set())
        t_w = network_state.get((id(motor), idx_w), set())

        direction = self._tri_direction(t_u, t_v, t_w)
        if direction != 0:
            self._run_motor(motor, direction, 220)
        else:
            self._stop_motor(motor)

    # M5: motor-1pC.svg — Dahlander 2 velocidades
    # 5 conn_points. Fila sup (cy≈1.76): U1(x15), V1(x55), PE(x75)
    #                Fila inf (cy≈70.5): U2(x15), V2(x55)
    # Alta velocidad (devanado paralelo): U1->L1, V1->L2, U2 y V2 abiertos
    # Baja velocidad (devanado serie): U2->L1, V2->L2, U1 y V1 abiertos
    # Configuración Dahlander: U1->L1, V1->L2, V1 puenteado a U2, U1 puenteado a V2
    #   -> esto es baja velocidad con puenteo cruzado
    # REGLA: Ambos devanados con tensión simultáneamente -> BURNED
    def _analyze_m5_dahlander(self, motor, network_state):
        pts = motor.conn_points
        if len(pts) < 5:
            self._stop_motor(motor)
            return

        indexed = sorted(enumerate(pts), key=lambda x: x[1].y)
        top3    = sorted(indexed[:3], key=lambda x: x[1].x)
        bottom2 = sorted(indexed[3:], key=lambda x: x[1].x)

        idx_u1 = top3[0][0]
        idx_v1 = top3[1][0]
        idx_u2 = bottom2[0][0]
        idx_v2 = bottom2[1][0]

        t_u1 = network_state.get((id(motor), idx_u1), set())
        t_v1 = network_state.get((id(motor), idx_v1), set())
        t_u2 = network_state.get((id(motor), idx_u2), set())
        t_v2 = network_state.get((id(motor), idx_v2), set())

        ph_u1 = {p for p in t_u1 if p in _PHASE_ORDER}
        ph_v1 = {p for p in t_v1 if p in _PHASE_ORDER}
        ph_u2 = {p for p in t_u2 if p in _PHASE_ORDER}
        ph_v2 = {p for p in t_v2 if p in _PHASE_ORDER}
        n_u1  = 'N' in t_u1
        n_v1  = 'N' in t_v1
        n_u2  = 'N' in t_u2
        n_v2  = 'N' in t_v2

        # Verificar que haya al menos una fase y al menos un neutro en todo el motor
        any_phase = bool(ph_u1 or ph_v1 or ph_u2 or ph_v2)
        any_neutral = bool(n_u1 or n_v1 or n_u2 or n_v2)
        if not any_phase or not any_neutral:
            self._stop_motor(motor)
            return

        # GIRO HORARIO (CW, direction=1):
        #   L1 -> U1, N -> V2
        #   Puente 1: U1 <-> V1 (V1 queda en fase por el puente)
        #   Puente 2: U2 <-> V2 (U2 queda en neutro por el puente)
        #   Resultado en terminales:
        #     U1 = fase, V1 = fase (via puente U1-V1), U2 = N (via puente U2-V2), V2 = N
        #   Patrón clave: U1 y V1 comparten fase, U2 y V2 comparten neutro
        cw_pattern = (
            bool(ph_u1) and bool(ph_v1) and bool(ph_u1 & ph_v1) and  # U1 y V1 misma fase
            bool(n_u2) and bool(n_v2)                                  # U2 y V2 en neutro
        )

        # GIRO ANTIHORARIO (CCW, direction=-1):
        #   L1 -> U1, N -> V2
        #   Puente 1: U1 <-> U2 (U2 queda en fase por el puente)
        #   Puente 2: V1 <-> V2 (V1 queda en neutro por el puente)
        #   Resultado en terminales:
        #     U1 = fase, U2 = fase (via puente U1-U2), V1 = N (via puente V1-V2), V2 = N
        #   Patrón clave: U1 y U2 comparten fase, V1 y V2 comparten neutro
        ccw_pattern = (
            bool(ph_u1) and bool(ph_u2) and bool(ph_u1 & ph_u2) and  # U1 y U2 misma fase
            bool(n_v1) and bool(n_v2)                                  # V1 y V2 en neutro
        )

        # Ambos patrones simultáneos -> cortocircuito -> BURNED
        if cw_pattern and ccw_pattern:
            self._fault(motor, 'BURNED',
                        f'⚠️ {self._label(motor)}: Ambos devanados activos — QUEMADO')
            return

        if cw_pattern:
            self._run_motor(motor, 1, 110)
        elif ccw_pattern:
            self._run_motor(motor, -1, 110)
        else:
            self._stop_motor(motor)

    # M4: motor-1p-dosi.svg — Bomba dosificadora CI, sin inversión
    # Acepta alimentación a 110V (fase + neutro) o 220V (fase + fase).
    def _analyze_m4_dosi(self, motor, network_state):
        idx_u1, idx_v1 = self._get_top_two(motor)
        if idx_u1 is None:
            self._stop_motor(motor)
            return

        t_u1 = network_state.get((id(motor), idx_u1), set())
        t_v1 = network_state.get((id(motor), idx_v1), set())
        ph_u1 = {p for p in t_u1 if p in _PHASE_ORDER}
        ph_v1 = {p for p in t_v1 if p in _PHASE_ORDER}
        n_u1  = 'N' in t_u1
        n_v1  = 'N' in t_v1

        # Dos fases DISTINTAS = 220V fase-fase (configuración válida de la bomba)
        if ph_u1 and ph_v1 and not (ph_u1 & ph_v1):
            self._run_motor(motor, 1, 220)  # dirección fija, no invertible
            return

        # Fase + neutro = 110V
        if (ph_u1 and n_v1) or (n_u1 and ph_v1):
            self._run_motor(motor, 1, 110)  # dirección fija, no invertible
            return

        # Misma fase en ambos extremos (cortocircuito interno) o sin alimentación
        self._stop_motor(motor)

    # M6: motor-3p-ST.svg — Trifásico 6 bornes Y/Δ
    # 7 conn_points.
    # Fila sup (cy≈1.75) por X: U1(x14), V1(x34), W1(x54), PE(x74)
    # Fila inf (cy≈70.3) por X: U2(x14), V2(x34), W2(x54)
    # Configuración Y (estrella): U2-V2-W2 puenteados al mismo punto
    # Configuración Δ (triángulo): U1-W2, V1-U2, W1-V2 puenteados
    # Sin configurar (U2,V2,W2 abiertos): funciona igual si U1,V1,W1 tienen 3 fases
    # Mezcla Y+Δ simultáneo -> BURNED
    def _analyze_m6_star_delta(self, motor, network_state):
        if len(motor.conn_points) < 7:
            self._stop_motor(motor)
            return

        indexed = sorted(enumerate(motor.conn_points), key=lambda x: x[1].y)
        top4    = sorted(indexed[:4], key=lambda x: x[1].x)
        bottom3 = sorted(indexed[4:], key=lambda x: x[1].x)

        idx_u1 = top4[0][0]
        idx_v1 = top4[1][0]
        idx_w1 = top4[2][0]
        idx_u2 = bottom3[0][0]
        idx_v2 = bottom3[1][0]
        idx_w2 = bottom3[2][0]

        t_u1 = network_state.get((id(motor), idx_u1), set())
        t_v1 = network_state.get((id(motor), idx_v1), set())
        t_w1 = network_state.get((id(motor), idx_w1), set())
        t_u2 = network_state.get((id(motor), idx_u2), set())
        t_v2 = network_state.get((id(motor), idx_v2), set())
        t_w2 = network_state.get((id(motor), idx_w2), set())

        # Estrella: U2, V2, W2 comparten potencial entre sí
        star = (bool(t_u2 and t_v2 and t_u2 & t_v2) and
                bool(t_v2 and t_w2 and t_v2 & t_w2))

        # Triángulo: cada bobina tiene sus dos extremos puenteados correctamente
        delta = (bool(t_u1 and t_w2 and t_u1 & t_w2) and
                 bool(t_v1 and t_u2 and t_v1 & t_u2) and
                 bool(t_w1 and t_v2 and t_w1 & t_v2))

        if star and delta:
            self._fault(motor, 'BURNED',
                        f'⚠️ {self._label(motor)}: Mezcla Y+Δ simultánea — QUEMADO')
            return

        # La dirección siempre viene de la secuencia en U1, V1, W1
        direction = self._tri_direction(t_u1, t_v1, t_w1)
        if direction != 0:
            self._run_motor(motor, direction, 220)
        else:
            self._stop_motor(motor)

    # Helpers
    def _label(self, motor):
        """Designador real del motor (M1, M2, ...) para los avisos de falla."""
        label_data = getattr(motor, 'label_data', None) or {}
        name = (label_data.get('name') or '').strip()
        if not name:
            name = (getattr(motor, 'name', '') or '').strip()
        return name or 'Motor'

    def _get_top_two(self, motor):
        """Devuelve (idx_izq, idx_der) de los 2 terminales con menor Y."""
        if len(motor.conn_points) < 2:
            return None, None
        indexed = sorted(enumerate(motor.conn_points), key=lambda x: x[1].y)
        top2 = sorted(indexed[:2], key=lambda x: x[1].x)
        return top2[0][0], top2[1][0]

    def _tri_direction(self, t_u, t_v, t_w):
        """1=CW, -1=CCW, 0=sin giro (falta de fase o cortocircuito)."""
        ph_u = {p for p in t_u if p in _PHASE_ORDER}
        ph_v = {p for p in t_v if p in _PHASE_ORDER}
        ph_w = {p for p in t_w if p in _PHASE_ORDER}

        if not ph_u or not ph_v or not ph_w:
            return 0
        if len(ph_u | ph_v | ph_w) < 3:
            return 0
        if ph_u & ph_v or ph_v & ph_w or ph_u & ph_w:
            return 0

        vals = (
            _PHASE_ORDER[list(ph_u)[0]],
            _PHASE_ORDER[list(ph_v)[0]],
            _PHASE_ORDER[list(ph_w)[0]],
        )
        if vals in _SEQ_CW:  return 1
        if vals in _SEQ_CCW: return -1
        return 0

    def _run_motor(self, motor, direction, voltage):
        motor.voltage          = voltage
        motor.current_volt_pct = 100.0
        motor.current_freq     = 60.0
        motor.motor_fault      = None
        motor.motor_temp       = 'NORMAL'
        self._set_state(motor, True, direction)

    def _fault(self, motor, code, msg):
        """Registra falla, detiene motor y reporta en barra de estado."""
        motor.motor_fault = code
        motor.motor_temp  = 'CRITICAL'
        self._set_state(motor, False, 0)
        if hasattr(self.app, 'set_status'):
            self.app.set_status(msg, 'red')

    def _stop_motor(self, motor):
        motor.motor_fault = None
        self._set_state(motor, False, 0)

    def _set_state(self, motor, is_active, direction):
        changed = False
        if getattr(motor, 'is_active', False) != is_active:
            motor.is_active = is_active
            changed = True
        if getattr(motor, 'motor_direction', 0) != direction:
            motor.motor_direction = direction
            changed = True

        if changed:
            if hasattr(motor, 'load_image') and hasattr(motor, 'svg_path'):
                motor.load_image(motor.svg_path)
                if hasattr(motor, 'draw'):
                    if hasattr(self.app, '_visible_components_only'):
                        if id(motor) in self.app._visible_components_only:
                            motor.draw()
                    else:
                        motor.draw()

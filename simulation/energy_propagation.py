import logging
import os
from collections import deque

_logger = logging.getLogger("evaPr.sim")

# Traza por componente de la propagación (ON/OFF de cada elemento).
# _is_component_active() se llama N veces por cada tick de simulación (10 Hz), así que
# activarlo por omisión escribía cientos de MB por sesión. Es opt-in:
#   EVAPR_SIM_DEBUG=1 python evaPr.py
_SIM_DEBUG = os.environ.get('EVAPR_SIM_DEBUG', '').strip() not in ('', '0', 'false', 'False')

# Orden de lectura para un componente sin posición conocida: al final de la última
# hoja, para que quede al final de la cadena de saltos.
_NO_POSITION = (1 << 20, 0.0, 0.0, 0)

# Símbolos NC/NO combinados: se comparan contra el SVG ya en minúsculas.
_NC_NO_SVGS = tuple(s.lower() for s in (
    'BotonNCNO.svg',
    'MushroomNCNO.svg',
    'SwitchNCNO.svg',
    'Contactor-auxiliar.svg',
))

# Unidades de control y cargas: no transmiten corriente internamente.
_CONTROL_UNITS = ('sst-c', 'vdf-c')
_LOAD_KEYWORDS = ('resistor', 'coil', 'pilot', 'buzzer', 'lamp', 'load')

class EnergyPropagator:
    """
    Responsable de propagar el potencial eléctrico (L1, L2, L3, N) desde las fuentes
    a través de los componentes conductores.

    Cada símbolo 'fase' (etiquetado L1/L2/L3/N/PE) es una fuente de ese potencial. El
    potencial avanza por los cables y los conductores internos hasta un 'conxn'
    ("Conexión Salida"), que lo teletransporta por el cable al 'conxn2'
    ("Conexión Entrada") del MISMO nombre, normalmente en la hoja siguiente, donde el
    ciclo se repite. Ese cable conduce en los DOS sentidos, así que también se puede
    recorrer a la inversa (del conxn2 al conxn): es el mismo tramo de cable.
    """

    # Símbolos de salto entre hojas (ver config/settings.py -> "Connection").
    LINK_EMITTER = 'conxn.svg' # Conexión Salida -> transporta la energía
    LINK_RECEIVER = 'conxn2.svg'  # Conexión Entrada -> la recibe

    def __init__(self, app):
        self.app = app
        # Orden de lectura de los saltos, calculado una vez por propagate().
        # {id(componente): (indice_hoja, x, y, orden_de_llegada)}
        self._link_pos = None
        # Parejas de cable de los saltos, calculadas una vez por propagate().
        # {id(componente): [componentes con los que comparte ese cable]}
        self._link_pairs = None
        # Índice de adyacencia del cableado: {(id_comp, puerto): [(vecino, puerto)]}.
        # Sin él, cada nodo del BFS tenía que recorrer TODAS las conexiones del
        # proyecto (O(nodos × cables)), que es lo que hacía el tick tan lento.
        self._adjacency = None
        # Destino inalámbrico (conxn <-> conxn2 / fase) precalculado por propagate().
        self._wireless_targets = None
        # Memo de _can_pass_internally del tick en curso (el estado de los
        # componentes no cambia mientras se propaga).
        self._pass_cache = None

    def propagate(self):
        """
        Ejecuta el algoritmo de propagación.
        
        Returns:
            dict: Mapa de {Componente: {Terminal_Index: Potencial}}
            # Ejemplo: {Motor1: {0: 'L1', 1: 'L2', 2: 'L3'}}
        """
        # 1. Identificar fuentes
        sources = self._find_sources()
        if not sources:
            return {}

        # 2. Propagar desde cada fuente (BFS)
        # Mapa global de potenciales en puntos de conexión
        # key: (id(component), point_index) -> value: set(potentials)
        # Usamos set para detectar cortocircuitos (más de 1 potencial distinto)
        network_state = {}

        # Orden de lectura de la cadena de saltos (hoja, luego de izquierda a
        # derecha). Se calcula una sola vez: lo consulta _check_wireless_connection
        # en cada nodo del BFS.
        self._link_pos = self._build_link_positions()
        # Con qué salto comparte cable cada conxn/conxn2 (en los dos sentidos).
        self._link_pairs = self._build_link_pairs()
        # Índices construidos UNA sola vez y consultados O(1) en cada nodo.
        self._adjacency = self._build_adjacency()
        self._wireless_targets = self._build_wireless_targets()
        self._pass_cache = {}

        try:
            for source_comp, potential in sources.items():
                if isinstance(potential, dict):
                    # Caso fuente múltiple (ej: Power Supply DC)
                    for pt_idx, pot in potential.items():
                        start_node = (source_comp, pt_idx)
                        self._bfs(start_node, pot, network_state)
                else:
                    # Caso fuente simple
                    start_node = (source_comp, 0)
                    self._bfs(start_node, potential, network_state)
        finally:
            self._link_pos = None
            self._link_pairs = None
            self._adjacency = None
            self._wireless_targets = None
            self._pass_cache = None

        return network_state

    def _build_adjacency(self):
        """
        Índice de cableado: {(id(componente), puerto): [(componente_vecino, puerto)]}.
        Se construye una sola vez por tick y reemplaza el barrido lineal de
        self.app.connections que hacía cada nodo visitado del BFS.
        """
        adjacency = {}
        for conn in self.app.connections:
            start = (id(conn.start_component), conn.start_point_idx)
            end = (id(conn.end_component), conn.end_point_idx)
            adjacency.setdefault(start, []).append(
                (conn.end_component, conn.end_point_idx))
            adjacency.setdefault(end, []).append(
                (conn.start_component, conn.start_point_idx))
        return adjacency

    def _build_link_positions(self):
        """
        Calcula la posición de lectura de cada componente: (hoja, x, y, llegada).

        La cadena de saltos avanza de izquierda a derecha y de hoja en hoja, así que
        ordenar por (índice de hoja, x) es lo que convierte un conjunto de conxn/conxn2
        homónimos en una SECUENCIA:

            Hoja 1  conxn L1  --salto-->  Hoja 2  conxn2 L1... conxn L1
                                                     --salto-->  Hoja 3  conxn2 L1

        Y no en un nodo único, que es lo que pasaba al emparejar por nombre sin más.
        """
        positions = {}
        project = getattr(self.app, 'project', None)
        sheets = getattr(project, 'sheets', None) if project is not None else None

        if not sheets:
            # Sin proyecto multi-hoja: un único plano, orden de la lista.
            for n, comp in enumerate(self.app.components):
                positions[id(comp)] = self._position_key(comp, 0, n)
            return positions

        # La hoja de cada componente se saca de las instancias vivas de cada hoja.
        # Es la única fuente que no depende de self.app.components, que durante el
        # tick de simulación es el agregado de todas las hojas.
        index_by_name = {getattr(s, 'name', str(i)): i for i, s in enumerate(sheets)}
        active_idx = getattr(project, 'active_sheet_index', 0)
        index_of = {}
        for i, sheet in enumerate(sheets):
            for comp in getattr(sheet, 'live_components', None) or []:
                index_of.setdefault(id(comp), i)

        # El mapa congelado de la app sólo se consulta para lo que no aparezca en
        # ninguna hoja viva, y se descarta si contradice a las instancias vivas: si
        # el mapa dijera que un componente de otra hoja está en la activa, la fase
        # saltaría de página y la energía aparecería sin traversing los cortes.
        sim_map = getattr(self.app, '_sim_sheet_map', None)
        for comp in self.app.components:
            idx = index_of.get(id(comp))
            if idx is None and sim_map:
                idx = index_by_name.get(sim_map.get(id(comp)))
            if idx is None:
                idx = active_idx
            positions[id(comp)] = self._position_key(comp, idx)
        return positions

    @staticmethod
    def _position_key(comp, sheet_idx, arrival=0):
        """(hoja, x, y, orden de llegada) -> posición de lectura comparable."""
        if sheet_idx is None:
            sheet_idx = 1 << 20  # sin hoja conocida: se trata como la última
        try:
            x = float(getattr(comp, 'x', 0) or 0)
            y = float(getattr(comp, 'y', 0) or 0)
        except (TypeError, ValueError):
            x = y = 0.0
        return (sheet_idx, x, y, arrival)

    def _find_sources(self):
        """Identifica componentes fuente (L1, L2, L3, N, PE, +, -, etc)."""
        sources = {}
        for comp in self.app.components:
            if getattr(comp, 'component_type', '') == 'fase':
                name = self._get_label(comp)
                if name:
                    sources[comp] = name

            elif getattr(comp, 'svg_file', None) and "power_supply_dc" in comp.svg_file.lower():
                if getattr(comp, 'is_active', False):
                    # Inyectar +24V en terminales 0 y 2, y GND en terminales 1 y 3
                    v_out = comp.label_data.get('voltaje', '24VDC')
                    if not v_out.endswith('V'): v_out += 'V'
                    if not v_out.startswith('+'): v_out = '+' + v_out

                    sources[comp] = {
                        0: v_out,
                        2: v_out,
                        1: 'GND',
                        3: 'GND'
                    }

            # VDF-C: Terminal '+' (índice 6) es fuente interna
            elif getattr(comp, 'svg_file', None) and "vdf-c" in comp.svg_file.lower():
                if getattr(comp, 'is_active', False):
                    sources[comp] = {
                        6: '+VDF_INTERNAL'
                    }

            elif getattr(comp, 'svg_file', None) and "power_supply_ac" in comp.svg_file.lower():
                if getattr(comp, 'is_active', False):
                    v_out = comp.label_data.get('voltaje', '24V AC').replace(' ', '').upper()
                    sources[comp] = {
                        2: v_out + "_L",
                        3: v_out + "_N"
                    }
        return sources

    def _get_label(self, comp):
        if hasattr(comp, 'label_data') and comp.label_data:
            return comp.label_data.get('name', '').strip().upper()
        return comp.name.strip().upper()

    def _bfs(self, start_node, potential, network_state):
        """
        Realiza BFS para propagar un potencial específico.
        start_node: (component, point_index)
        """
        queue = deque([start_node])
        visited = set() # (id(comp), point_index)
        adjacency = self._adjacency or {}
        pass_cache = self._pass_cache if self._pass_cache is not None else {}

        while queue:
            curr_comp, curr_idx = queue.popleft()
            state_key = (id(curr_comp), curr_idx)

            if state_key in visited:
                continue
            visited.add(state_key)

            # Registrar potencial en este punto
            if state_key not in network_state:
                network_state[state_key] = set()
            network_state[state_key].add(potential)

            # 1. Propagar a través de CONEXIONES EXTERNAS
            # Vecinos de este punto por el índice de adyacencia (O(1))
            queue.extend(adjacency.get(state_key, ()))

            # 2. Propagar INTERNAMENTE en el componente
            # De curr_idx a otros puntos del MISMO componente
            conn_points = getattr(curr_comp, 'conn_points', None)
            if conn_points:
                comp_key = id(curr_comp)
                for other_idx in range(len(conn_points)):
                    if other_idx == curr_idx:
                        continue

                    # Verificar si permite paso interno (memoizado por tick)
                    pass_key = (comp_key, curr_idx, other_idx)
                    can_pass = pass_cache.get(pass_key)
                    if can_pass is None:
                        can_pass = self._can_pass_internally(curr_comp, curr_idx, other_idx)
                        pass_cache[pass_key] = can_pass
                    if can_pass:
                        queue.append((curr_comp, other_idx))

            # 3. Propagar INALÁMBRICAMENTE (Wireless)
            # Por el cable que une un conxn y un conxn2 del MISMO NOMBRE, en los dos
            # sentidos (el cable conduce igual hacia los dos extremos). Cada extremo
            # sólo se salta a SU pareja, no a todos los saltos de su nombre: si se
            # fusionaran, la cadena entre hojas se recorrería "por arriba" de los
            # cortes, de modo que un breaker abierto en una hoja no impediría que la
            # fase siguiera en las siguientes. Destinos precalculados por tick.
            wireless_targets = (self._wireless_targets or {}).get(id(curr_comp))
            if wireless_targets:
                queue.extend(wireless_targets)

    def _can_pass_internally(self, comp, p1_idx, p2_idx):
        """
        Determina si la corriente pasa internamente entre p1 y p2.
        """
        # LOGICA NC/NO (PRIORIDAD ALTA para manejar estados OFF/ON correctamente)
        svg_file = getattr(comp, 'svg_file', '') or ''
        svg_lower = svg_file.lower()

        # Verificar si es uno de los componentes especiales
        is_nc_no = any(s in svg_lower for s in _NC_NO_SVGS)

        if is_nc_no:
            return self._check_nc_no_connection(comp, p1_idx, p2_idx)

        # RELÉ TÉRMICO (Handler Dedicado - PRIORIDAD ALTA)
        # Debe ir ANTES de la lógica de "Cargas/Loads" porque "overload" contiene "load"
        if 'thermal-overload' in svg_lower:
            return self._check_thermal_overload_logic(comp, p1_idx, p2_idx)

        # LOGICA SELECTOR 3 POSICIONES
        if 'selector-3.svg' in svg_lower:
            return self._check_selector_3_logic(comp, p1_idx, p2_idx)

        # LOGICA DRIVERS (Arrancador Suave / Variador)
        if "sst-e" in svg_lower or "vdf-e" in svg_lower:
            # Conduce si está activo (bypass) O si tiene rampa/frecuencia activa
            can_conduct = getattr(comp, 'is_active', False)
            if not can_conduct:
                if "sst-e" in svg_lower:
                    # INTERPRETACIÓN: "Activo" para flujo de energía = "Conduciendo" (Voltaje > 0)
                    # "Activo" para el componente = "Bypass Cerrado" (Full Voltage)
                    # Al permitir flujo con volt_pct > 0, respetamos las rampas de inicio y fin.
                    can_conduct = getattr(comp, 'volt_pct', 0) > 0
                else:
                    can_conduct = getattr(comp, 'current_freq', 0) > 0

            if not can_conduct:
                return False

            # Pares de potencia longitudinales
            power_pairs = ((0, 4), (4, 0), (1, 5), (5, 1), (2, 6), (6, 2), (3, 7), (7, 3))
            return (p1_idx, p2_idx) in power_pairs

        # UNIDADES DE CONTROL Y CARGAS (Aislamiento Interno)
        # 1. SST-C y VDF-C no deben pasar corriente internamente.
        # 2. Cargas (Resistencias, Bobinas, Pilotos, Buzzers) consumen energía pero NO la pasan.
        if any(x in svg_lower for x in _CONTROL_UNITS + _LOAD_KEYWORDS):
            # EXCEPCIÓN: RA y RC del VDF-C actúan como un relé
            if "vdf-c" in svg_lower:
                # Terminales 0 y 1 son RA y RC
                if (p1_idx, p2_idx) in ((0, 1), (1, 0)):
                    # Cierra SOLAMENTE si está EN MARCHA ("Run Relay")
                    # El usuario indicó "solo se activa si están cerrados" (implicando Run)
                    return getattr(comp, 'layer_running', False)

                # EXCEPCIÓN CRÍTICA: Terminal + (6) es la FUENTE.
                # NO debe tener continuidad interna con las entradas (2,3,4,5).
                # La continuidad se da por FUERA (switches).
                # Aquí solo permitimos RA-RC.
                pass
            return False

        # AISLAMIENTO AISLAMIENTO INTERNO PARA FUENTE PODER DC/AC
        if "power_supply_dc" in svg_lower or "power_supply_ac" in svg_lower:
            return False

        # RELÉ TÉRMICO (Handler Dedicado) -> MOVIDO ARRIBA
        # (Bloque removido para evitar duplicidad, ya se maneja al inicio)

        # 1. Verificar si el componente está ACTIVO (Switch ON, Breaker ON)
        if not self._is_component_active(comp):
            return False

        # 2. Tipos simples (cables, uniones) -> SIEMPRE PASA
        comp_type = getattr(comp, 'component_type', 'normal')
        if comp_type in ['junction', 'conxn', 'conxn2', 'line', 'fase']:
            return True

        # 3. Motores y Cargas -> NO PASA (son sumideros para efectos de fase)
        # Esto evita que L1 entre por U1 y salga por V1 "coloreando" la red de retorno
        if getattr(comp, 'component_activation_mode', '') == 'motor':
            return False
        # Detectar motores por nombre de SVG
        if 'motor' in svg_lower and 'circuit-breaker' not in svg_lower:
            return False
        comp_name = getattr(comp, 'name', '') or ''
        if 'coil' in comp_name.lower(): # Bobinas consumen, no pasan fase
             return False
        if 'pilot' in comp_name.lower(): # Pilotos consumen
             return False

        # 4. Componentes de 2 Terminales (Interruptores, Fusibles, etc.)
        # Si tiene exactamente 2 puntos y está activo -> CONECTA SIEMPRE
        if hasattr(comp, 'conn_points') and len(comp.conn_points) == 2:
            return True

        # 5. Componentes Multipolares (Contactores 3P, Disyuntores 3P)
        # Usar GEOMETRÍA para evitar mezclar fases
        if hasattr(comp, 'conn_points') and len(comp.conn_points) > p1_idx and len(comp.conn_points) > p2_idx:
            p1 = comp.conn_points[p1_idx]
            p2 = comp.conn_points[p2_idx]

            TOLERANCE = 10.0

            # Misma fila (Y similar) -> NO CONECTA (Lado entrada vs Lado entrada)
            if abs(p1.y - p2.y) < TOLERANCE:
                return False

            # Misma columna (X similar) -> SI CONECTA (Flujo vertical)
            if abs(p1.x - p2.x) < TOLERANCE:
                return True

            # Diagonal -> NO CONECTA
            return False

        return True

    def _check_thermal_overload_logic(self, comp, p1_idx, p2_idx):
        """
        Manejo robusto para Relé Térmico (F1).
        Reglas:
        1. Estado OFF (is_active=False) -> Conduce (Normal).
        2. Estado ON (is_active=True) -> No conduce (Disparado).
        3. Conducción Vertical (Entrada con Salida alineada).
        """
        # 1. Chequeo de Estado (Disparo)
        if getattr(comp, 'is_active', False):
            # Si está ACTIVO significa que ha saltado por sobrecarga -> CIRCUITO ABIERTO
            return False

        # 2. Chequeo Geométrico (Conducción Fase a Fase)
        points = comp.conn_points
        if not points or p1_idx >= len(points) or p2_idx >= len(points):
            return False

        p1 = points[p1_idx]
        p2 = points[p2_idx]

        # Deben estar alineados verticalmente (misma columna)
        # Usamos una tolerancia estricta pero suficiente para dibujo manual
        TOLERANCE_X = 1.0

        # Si están offset en X más de la tolerancia, es cruce de fase -> NO
        if abs(p1.x - p2.x) > TOLERANCE_X:
            return False

        # Si están en X similar, asumimos que es entrada-salida de la misma fase.
        # No chequeamos Y porque a veces los puntos están muy cerca o invertidos
        return True

    def _check_nc_no_connection(self, comp, p1_idx, p2_idx):
        """
        Lógica especial para componentes NC + NO combinados.
        Asume disposición geométrica en columnas:
        - Columna Izquierda: NC (Cerrado en reposo)
        - Columna Derecha: NO (Abierto en reposo)
        """
        points = comp.conn_points
        p1 = points[p1_idx]
        p2 = points[p2_idx]

        TOLERANCE = 10.0

        # 1. Regla Básica: Solo flujo VERTICAL (misma X)
        # Nunca cruzar de izquierda a derecha
        if abs(p1.x - p2.x) > TOLERANCE:
            return False

        # 2. Identificar pares verticales (Columnas)
        # Agrupar puntos por coordenada X promedio
        x_coords = sorted(list(set([p.x for p in points])))

        # Agrupar columnas con tolerancia
        columns = []
        for x in x_coords:
            found = False
            for col in columns:
                if abs(col['x'] - x) < TOLERANCE:
                    found = True
                    break
            if not found:
                columns.append({'x': x, 'points': []})

        # Ordenar columnas de Izquierda a Derecha
        columns.sort(key=lambda c: c['x'])

        # Determinar en qué columna estamos
        current_col_idx = -1
        for i, col in enumerate(columns):
            if abs(col['x'] - p1.x) < TOLERANCE:
                current_col_idx = i
                break

        if current_col_idx == -1:
            return False

        # 3. Regla NC vs NO
        # Columna 0 (Izquierda) -> NC -> Conduce si NO está activo
        # Columna 1 (Derecha) -> NO -> Conduce si SI está activo
        is_active = getattr(comp, 'is_active', False)

        if current_col_idx == 0: # NC
            return not is_active
        else: # NO
            return is_active

    def _check_selector_3_logic(self, comp, p1_idx, p2_idx):
        """
        Lógica para selector de 3 posiciones (OFF, ON-2, ON-3)
        Geometría esperada:
        - 1 Terminal Superior (Común / Entrada) -> Index ?
        - 2 Terminales Inferiores (Salidas 2 y 3) -> Index ?
        
        Mapeo aproximado:
        - Top: Terminal 1
        - Bottom-Left: Terminal 2
        - Bottom-Right: Terminal 3
        """
        points = comp.conn_points
        if len(points) != 3:
            return False # Estructura desconocida

        # 1. Identificar geometrías
        # Ordenar por Y (Top vs Bottom)
        # Usar tolerancia por si no están perfectamente alineados
        y_sorted = sorted(enumerate(points), key=lambda x: x[1].y)

        # El punto con menor Y es el de arriba (Top) -> Terminal 1
        top_idx, top_point = y_sorted[0]

        # Los otros dos son los de abajo -> Ordenar por X
        bottom_points = sorted(y_sorted[1:], key=lambda x: x[1].x)

        bottom_left_idx, bottom_left_point = bottom_points[0]  # Terminal 2
        bottom_right_idx, bottom_right_point = bottom_points[1] # Terminal 3

        # 2. Verificar que los puntos consultados sean válidos
        # Solo se permite paso si uno es Top y el otro es uno de los Bottom
        is_p1_top = (p1_idx == top_idx)
        is_p2_top = (p2_idx == top_idx)

        if not (is_p1_top or is_p2_top):
             # Intento de paso entre abajo-izquierda y abajo-derecha -> BLOQUEAR
             return False

        # Identificar cual es el otro punto (el que no es Top)
        target_idx = p2_idx if is_p1_top else p1_idx

        # 3. Verificar estado del selector
        current_pos = getattr(comp, 'current_position', 0)

        if current_pos == 0: # OFF
            return False # Corta todo

        elif current_pos == 1: # ON-2 (Flujo 1-2)
            # Solo permite paso si el target es Bottom-Left
            return target_idx == bottom_left_idx

        if current_pos == 2: # ON-3 (Flujo 1-3)
            # Solo permite paso si el target es Bottom-Right
            return target_idx == bottom_right_idx

        return False

    def _build_link_pairs(self):
        """
        Empareja cada salto con el que comparte cable y devuelve el mapa en los dos
        sentidos:

            {id(conxn): [conxn2], id(conxn2): [conxn]}

        Son dos reglas las que hacen que la cadena se comporte como un cable de verdad:

        1. SECUENCIAL. Cada conxn se une con el conxn2 homónimo INMEDIATAMENTE
           SIGUIENTE en orden de lectura (hoja, luego izquierda -> derecha), no con
           todos los de su nombre. Así la cadena es la que el usuario dibujó, y un
           corte en una hoja apaga esa fase en esa hoja y en las siguientes, pero no en
           las anteriores. No se fusionan todos los conxn/conxn2 de un nombre en un
           único nodo, porque entonces la cadena se recorrería "por arriba" de los
           cortes: un breaker abierto en la hoja intermedia no impediría que la fase
           siguiera en las hojas siguientes.

        2. LA PAREJA VA EN LOS DOS SENTIDOS. Un cable conduce igual hacia los dos
           extremos, así que la pareja se registra por ambos: si el conxn2 se
           energiza desde su hoja, la energía también llega al conxn del otro extremo.
           Y si un conxn2 se queda sin pareja (el cable está dibujado al revés, el
           conxn quedó en una hoja posterior), se engancha al conxn más próximo. Se
           busca primero hacia ATRÁS (caso habitual) y, si no hay ninguno, hacia
           ADELANTE, que es el otro extremo de ese mismo cable. Sin esto, ese conxn2
           se quedaría muerto aunque su conxn tuviera energía (p. ej. el salto "A",
           con los conxn2 en FUERZA y el conxn en CONTROL).
        """
        if self._link_pos is None:
            self._link_pos = self._build_link_positions()

        groups = {}
        for comp in self.app.components:
            svg_file = getattr(comp, 'svg_file', '') or ''
            if not (self._is_link_svg(svg_file, self.LINK_EMITTER)
                    or self._is_link_svg(svg_file, self.LINK_RECEIVER)):
                continue
            name = self._get_label(comp)
            if not name:
                continue
            groups.setdefault(name, []).append(comp)

        pairs = {}

        def link(a, b):
            pairs.setdefault(id(a), []).append(b)
            pairs.setdefault(id(b), []).append(a)

        for comps in groups.values():
            ordered = sorted(comps, key=lambda c: self._link_pos.get(id(c),
                                                                 _NO_POSITION))
            for i, comp in enumerate(ordered):
                if not self._is_link_svg(getattr(comp, 'svg_file', '') or '',
                                         self.LINK_EMITTER):
                    continue
                for other in ordered[i + 1:]:
                    if self._is_link_svg(getattr(other, 'svg_file', '') or '',
                                         self.LINK_RECEIVER):
                        link(comp, other)  # regla 1: el siguiente conxn2 del mismo nombre
                        break

            # Regla 2, segunda parte: conxn2 sin pareja -> conxn más próximo.
            # Normalmente el cable se dibuja hacia adelante y el conxn está ANTES,
            # así que se busca primero hacia atrás. Pero si el cable se dibujó al
            # revés y el conxn quedó en una hoja POSTERIOR (caso del salto "A":
            # conxn2 en FUERZA, conxn en CONTROL), no hay ningún conxn anterior y
            # el conxn2 se quedaría muerto. En ese caso se engancha al conxn
            # siguiente más próximo, que es el otro extremo de ese mismo cable.
            for i, comp in enumerate(ordered):
                if not self._is_link_svg(getattr(comp, 'svg_file', '') or '',
                                         self.LINK_RECEIVER):
                    continue
                if pairs.get(id(comp)):
                    continue
                found = None
                for other in reversed(ordered[:i]):
                    if self._is_link_svg(getattr(other, 'svg_file', '') or '',
                                         self.LINK_EMITTER):
                        found = other
                        break
                if found is None:
                    for other in ordered[i + 1:]:
                        if self._is_link_svg(getattr(other, 'svg_file', '') or '',
                                             self.LINK_EMITTER):
                            found = other
                            break
                if found is not None:
                    link(comp, found)

        return pairs

    def _check_wireless_connection(self, comp, potential):
        """
        Salto de energía entre hojas por el cable de un conxn (Conexión Salida) y un
        conxn2 (Conexión Entrada) del MISMO nombre:

            fase ->... -> conxn  ==(salto, mismo nombre)==>  conxn2 ->... -> conxn
                 (hoja N)                                    (hoja N+1)

        Son dos reglas las que hacen que la cadena se comporte como un cable de verdad:

        1. SECUENCIAL. Cada conxn se empareja con el conxn2 homónimo INMEDIATAMENTE
           SIGUIENTE en orden de lectura (hoja, luego izquierda -> derecha), no con
           todos los de su nombre. Así la cadena es la que el usuario dibujó, y un
           corte en una hoja apaga esa fase en esa hoja y en las siguientes, pero no en
           las anteriores.

        2. BIDIRECCIONAL. El salto se recorre en los dos sentidos. El panel nombra
           estos símbolos "Conexión Salida" / "Conexión Entrada" porque es el sentido en
           que se dibujó, no porque el cable tenga un único sentido: si la energía
           llega al conxn2, también llega al conxn de su pareja. Cada extremo sólo
           conoce a su pareja (regla 1), así que la cadena NO queda toda fusionada.
           Los conxn2 que se quedan sin pareja se enganchan al conxn inmediatamente
           anterior (ver _build_link_pairs).

        Excepción: una 'fase' alimenta al conxn2 homónimo de SU PROPIA hoja, y sólo a
        ése (no salta a la hoja siguiente: para eso está el conxn). Es la forma de
        devolver energía aguas abajo de un corte poniendo otra 'fase' con la misma
        etiqueta en esa hoja, sin que una fase colocada a media página pueda saltarse
        el corte que tiene delante.

        Devuelve [(componente_destino, indice_puerto)] -> [(pareja, 0)] o []
        """
        if self._wireless_targets is None:
            self._link_pos = self._link_pos or self._build_link_positions()
            self._link_pairs = self._link_pairs or self._build_link_pairs()
            self._wireless_targets = self._build_wireless_targets()
        return self._wireless_targets.get(id(comp), ())

    def _build_wireless_targets(self):
        """
        Precalcula, UNA sola vez por tick, a dónde salta cada componente:
        conxn <-> conxn2 por su pareja de cable, y 'fase' -> conxn2 homónimo de
        su propia hoja.

        Antes se calculaba en cada nodo visitado del BFS: para las 'fase' eso
        recorría la lista entera de componentes en cada visita (O(fases ×
        componentes) por fuente).
        """
        if self._link_pos is None:
            self._link_pos = self._build_link_positions()
        if self._link_pairs is None:
            self._link_pairs = self._build_link_pairs()

        # Llegadas (conxn2) agrupadas por (nombre, hoja)
        receivers = {}
        for comp in self.app.components:
            if not self._is_link_svg(getattr(comp, 'svg_file', '') or '',
                                     self.LINK_RECEIVER):
                continue
            name = self._get_label(comp)
            pos = self._link_pos.get(id(comp))
            if not name or pos is None:
                continue
            receivers.setdefault((name, pos[0]), []).append(comp)

        targets = {}
        for comp in self.app.components:
            svg_file = getattr(comp, 'svg_file', '') or ''
            is_link = (self._is_link_svg(svg_file, self.LINK_EMITTER)
                       or self._is_link_svg(svg_file, self.LINK_RECEIVER))
            is_fase = getattr(comp, 'component_type', '') == 'fase'
            if not (is_fase or is_link):
                continue  # los demás símbolos sólo conducen por cable

            name = self._get_label(comp)
            if not name:
                continue
            my_pos = self._link_pos.get(id(comp))
            if my_pos is None:
                continue

            if not is_fase:
                # conxn o conxn2: salta a su pareja de cable, en cualquier sentido.
                paired = self._link_pairs.get(id(comp))
                if paired:
                    targets[id(comp)] = [(other, 0) for other in paired]
                continue

            # 'fase': sólo alimenta la llegada (conxn2) de SU PROPIA hoja
            target = None
            best_rank = None
            for other_comp in receivers.get((name, my_pos[0]), ()):
                if other_comp is comp:
                    continue
                other_pos = self._link_pos.get(id(other_comp))
                if other_pos is None:
                    continue
                # En su propia hoja da igual el lado: la fase ES la llegada de la
                # energía a esa página. Se prefiere el conxn2 siguiente, y si no hay
                # ninguno se usa el más próximo.
                rank = (0 if other_pos > my_pos else 1, other_pos)
                if best_rank is None or rank < best_rank:
                    target, best_rank = other_comp, rank
            if target is not None:
                targets[id(comp)] = [(target, 0)]

        return targets

    @staticmethod
    def _is_link_svg(svg_file, kind_svg):
        """True si el archivo SVG es el símbolo de enlace buscado (conxn / conxn2)."""
        return kind_svg in (svg_file or '').lower()

    def _is_component_active(self, comp):
        """Verifica si el componente permite paso de corriente (ON/OFF)."""
        mode = getattr(comp, 'component_activation_mode', None)
        if not mode:
            return True  # Pasivos siempre conducen (salvo lógica interna)

        svg_file = getattr(comp, 'svg_file', '') or ''
        fname_lower = svg_file.lower()

        # LOG DETALLADO PARA DIAGNÓSTICO (opt-in con EVAPR_SIM_DEBUG=1)
        is_active = getattr(comp, 'is_active', False)
        is_nc = ('nc.svg' in fname_lower or '-nc' in fname_lower) and ('ncno' not in fname_lower)
        result = True

        if 'thermal-overload' in fname_lower or 'rele-thermal-overload-3' in fname_lower:
            result = not is_active
        elif mode in ['manual', 'automatic']:
            result = not is_active if is_nc else is_active
        else:
            result = True

        if _SIM_DEBUG and _logger.isEnabledFor(logging.DEBUG):
            _logger.debug("COMP: %s | SVG: %s | Mode: %s | Active: %s | NC: %s | Result: %s",
                          getattr(comp, 'name', '?'), svg_file, mode, is_active, is_nc, result)

        return result

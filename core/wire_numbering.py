class WireNumberingManager:
    """
    Gestor de Numeración por Bloques de Motor.
    Asigna rangos (100, 200, 300...) rastreando las ramas desde la carga hacia arriba,
    manteniendo las barras de alimentación (L1, N, PE) sin numeración secuencial.
    """
    RESERVED_NAMES = {'L1', 'L2', 'L3', 'L4', 'N', 'PE', 'GND', '+24V', '-24V', '24V+', '0V'}

    # Orden canonico de las fases para la Numeracion por Potencial:
    # L1 -> 1, L2 -> 2, L3 -> 3, L4 -> 4, N -> 5, GND -> 6
    # PE no aparece: segun IEC 60445:2021 §7.3.3 la designacion alfanumerica
    # del conductor de proteccion es "PE" y no un numero correlativo, por lo
    # que conserva su nombre y no consume numero en la serie.
    _PHASE_RANK = ('L1', 'L2', 'L3', 'L4', 'N', 'GND')

    # Conductores cuya identificacion es una designacion fija de la norma y no un
    # numero de la serie: IEC 60445:2021 §7.3.3 (PE). Se numeran aparte.
    _DESIGNATED_POTENTIALS = {'PE': 'PE'}

    # Componentes que AISLAN el potencial: el cable del otro lado no es del
    # mismo potencial. Mismo criterio que simulation/energy_propagation.py.
    _PHASE_ISOLATING_KEYWORDS = (
        'resistor', 'coil', 'buzzer', 'lamp', 'lampara',
        'sst-c', 'vdf-c', 'power_supply_dc', 'power_supply_ac',
    )

    def __init__(self, app):
        self.app = app
        self.net_map = {}
        self.net_labels = {}
        self.comp_map = {}

    def update_numbering(self, sheet_idx=0):
        if not hasattr(self.app, 'components') or not self.app.components:
            return

        self.comp_map = {id(c): c for c in self.app.components if c is not None}
        self.net_map = {}
        self.net_labels = {}

        self._group_equipotentials()

        numbering_type = "Numeración por Bloques de Motor"
        try:
            numbering_type = getattr(self.app, 'config', {}).get("wire_numbering_type", numbering_type)
        except Exception:
            pass
        self._dispatch_numbering(numbering_type, sheet_idx)

    def _dispatch_numbering(self, numbering_type, sheet_idx):
        """Despacha a la lógica de asignación según el tipo de numeración configurado."""
        if numbering_type == "Numeración por Código de Motor (Estructura de Bloque de Campo)":
            self._assign_labels_field_code(sheet_idx)
        elif numbering_type == "Numeración Secuencial por Regleta de Bornes":
            self._assign_labels_sequential_terminal(sheet_idx)
        elif numbering_type == "Numeración por Potencial":
            # Un disyuntor es el arranque de un circuito nuevo: su entrada y su
            # salida deben ser redes distintas para que la numeracion cambie al
            # atravesarlo (L1 = 1, salida del breaker de control = 11).
            self._group_equipotentials(split_breakers=True)
            self._assign_labels_by_potential(sheet_idx)
        else:
            # Estilo por defecto: Numeración por Bloques de Motor (sin cambios)
            self._assign_labels(sheet_idx)

    def _get_comp_tag(self, comp):
        """Extrae el nombre/tag del componente de forma segura."""
        if not comp: return ""
        label_data = getattr(comp, 'label_data', {})
        if isinstance(label_data, dict):
            return str(label_data.get('name', '') or '').upper()
        return str(getattr(label_data, 'name', '') or '').upper()

    def _group_equipotentials(self, split_breakers=False):
        """Agrupa los puntos de conexion en redes electricas (union-find).

        Cuando split_breakers=True (Numeración por Potencial) cada polo
        de un componente multi-polo (breaker, contactor, borne de 3
        posiciones...) debe conservar su propia red, porque la barra
        L1 y la L2 son POTENCIALES DISTINTOS que no deben mezclarse.
        """
        parent = {}
        point_phase = {}

        def find(i):
            if parent.setdefault(i, i) == i:
                return i
            parent[i] = find(parent[i])
            return parent[i]

        def union(i, j):
            root_i, root_j = find(i), find(j)
            if root_i != root_j:
                parent[root_i] = root_j

        for conn in self.app.connections:
            p1 = (id(conn.start_component), conn.start_point_idx)
            p2 = (id(conn.end_component), conn.end_point_idx)
            union(p1, p2)
            t1 = self._get_comp_tag(conn.start_component)
            t2 = self._get_comp_tag(conn.end_component)
            if t1 in self.RESERVED_NAMES:
                point_phase[p1] = t1
            if t2 in self.RESERVED_NAMES:
                point_phase[p2] = t2

        for comp in self.app.components:
            if comp is None: continue
            svg = str(getattr(comp, 'svg_file', '') or '').lower()
            tag = self._get_comp_tag(comp)
            is_terminal = 'borner' in svg or tag.startswith('X')
            is_bus_connector = any(x in svg for x in ['fase', 'conxn2'])
            is_junction = is_bus_connector or any(x in svg for x in ['punto', 'empalme', 'junction', 'conxn', 'distribuidor'])
            is_bridge = any(x in svg for x in ['puente', 'bridge', 'jumper'])
            is_breaker = ('breaker' in svg) or (tag == 'Q1')
            pts = getattr(comp, 'conn_points', [])
            if not pts: continue

            if is_breaker:
                # Cada polo de breaker es columna vertical; polos aislados.
                # Solo unir polos cuando NO se dividen (split_breakers=False).
                if not split_breakers:
                    half = len(pts) // 2
                    for i in range(half):
                        union((id(comp), i), (id(comp), i + half))
            elif is_junction or is_bridge:
                for i in range(len(pts) - 1):
                    pi = (id(comp), i)
                    pj = (id(comp), i + 1)
                    fi = point_phase.get(pi)
                    fj = point_phase.get(pj)
                    if fi and fj and fi != fj:
                        continue
                    union(pi, pj)
            elif is_terminal:
                if split_breakers:
                    # Bornes multi-polo (borner-3.svg): puntos [pos0,pos1,...,sal0,sal1,...].
                    # Unir SOLO dentro de cada posicion/polo.
                    n = len(pts)
                    half = n // 2
                    if n == 2 * half and half >= 1:
                        for i in range(half):
                            union((id(comp), i), (id(comp), i + half))
                    elif n == 2:
                        union((id(comp), 0), (id(comp), 1))
                else:
                    # Comportamiento original: unir pares consecutivos.
                    for i in range(0, len(pts) - 1, 2):
                        union((id(comp), i), (id(comp), i + 1))

        # conxn.svg y conxn2.svg son los dos extremos del MISMO cable.
        # Se unen solo cuando split_breakers=True (Numeración por Potencial)
        # para que el cable sea reconocido como una sola red.
        if split_breakers:
            name_comps = {}
            for comp in self.app.components:
                if comp is None: continue
                svg = str(getattr(comp, 'svg_file', '') or '').lower()
                if svg in ('conxn.svg', 'conxn2.svg'):
                    tag = self._get_comp_tag(comp)
                    name_comps.setdefault(tag, []).append(comp)
            for tag, comps_list in name_comps.items():
                if len(comps_list) < 2: continue
                for i in range(len(comps_list) - 1):
                    for p1 in range(len(getattr(comps_list[i], 'conn_points', []) or [])):
                        for p2 in range(len(getattr(comps_list[i+1], 'conn_points', []) or [])):
                            union((id(comps_list[i]), p1), (id(comps_list[i+1]), p2))

        self.net_map = {p: find(p) for p in parent}

    def _assign_labels(self, sheet_idx):
        # 1. Asignación de Nombres Reservados a la Barra (Prioridad Máxima)
        reserved_names = self.RESERVED_NAMES
        potential_reserved = {}

        for (c_id, p_idx), net_root in self.net_map.items():
            comp = self.comp_map.get(c_id)
            tag = self._get_comp_tag(comp)

            if tag in reserved_names:
                if tag not in potential_reserved:
                    potential_reserved[tag] = []
                pos_y = self._get_net_sort_key(net_root)[1]
                potential_reserved[tag].append((net_root, pos_y))

        processed_nets = set()

        # MODIFICACIÓN 2: Etiquetar todas las redes conectadas a la barra con su nombre (ej. L1)
        for name, candidates in potential_reserved.items():
            for net_root, _ in candidates:
                self.net_labels[net_root] = name
                processed_nets.add(net_root)

        # 2. Crear grafos de relación para rastreo bidireccional
        net_to_comps = {}
        comp_to_nets = {}
        for (c_id, p_idx), net_root in self.net_map.items():
            net_to_comps.setdefault(net_root, set()).add(c_id)
            comp_to_nets.setdefault(c_id, set()).add(net_root)

        # 3. Identificar motores en el plano y ordenarlos de izquierda a derecha (Eje X)
        motors = []
        for c_id, comp in self.comp_map.items():
            tag = self._get_comp_tag(comp)
            if tag.startswith('M'):
                motors.append(comp)

        motors.sort(key=lambda c: getattr(c, 'x', 0))

        # 4. Rastrear ramas de motores (BFS) y numerar por bloques (100, 200...)
        for index, motor in enumerate(motors, 1):
            base_block = index * 100
            branch_nets = set()

            queue = [id(motor)]
            visited_comps = {id(motor)}

            # Recorrer todo el circuito asociado a este motor hacia arriba
            while queue:
                curr_cid = queue.pop(0)
                connected_nets = comp_to_nets.get(curr_cid, set())

                for net in connected_nets:
                    # Ignorar cables de barra principal (ya marcados en processed_nets como L1, N, etc.)
                    if net not in processed_nets and net not in branch_nets:
                        branch_nets.add(net)
                        for next_cid in net_to_comps.get(net, set()):
                            if next_cid not in visited_comps:
                                visited_comps.add(next_cid)
                                queue.append(next_cid)

            # Ordenar las redes de esta rama de Arriba-Abajo (Y) y de Izquierda-Derecha (X)
            sorted_branch_nets = list(branch_nets)
            sorted_branch_nets.sort(key=lambda net: (
                self._get_net_sort_key(net)[1],  # Y primario (De arriba hacia abajo)
                self._get_net_sort_key(net)[0]   # X secundario
            ))

            # Asignar números 101, 102... / 201, 202... a las derivaciones
            for i, net in enumerate(sorted_branch_nets, 1):
                self.net_labels[net] = str(base_block + i)
                processed_nets.add(net)

        # 5. Numeración de cables huérfanos o de control
        all_roots = set(self.net_map.values())
        unnamed_roots = list(all_roots - processed_nets)

        if unnamed_roots:
            unnamed_roots.sort(key=lambda net: (
                self._get_net_sort_key(net)[1],
                self._get_net_sort_key(net)[0]
            ))
            control_block = 900
            for i, net in enumerate(unnamed_roots, 1):
                self.net_labels[net] = str(control_block + i)

    def _get_net_sort_key(self, net_root):
        nodes = [p for p, root in self.net_map.items() if root == net_root]
        min_x, min_y = 999999, 999999
        found = False

        for c_id, p_idx in nodes:
            comp = self.comp_map.get(c_id)
            if not comp: continue

            pts = getattr(comp, 'conn_points', [])
            if p_idx < len(pts):
                gx = comp.x + pts[p_idx].x
                gy = comp.y + pts[p_idx].y
                min_x = min(min_x, gx)
                min_y = min(min_y, gy)
                found = True

        return (min_x, min_y) if found else (999999, 999999)

    def get_label_for_connection(self, connection):
        if not connection: return ""
        try:
            p1 = (id(connection.start_component), connection.start_point_idx)
            root = self.net_map.get(p1)
            label = self.net_labels.get(root, "")

            # Corrección: cuando varias fases (L1/L2/L3/N) comparten el mismo
            # net_root (p. ej. convergen en un nodo de unión común), el mapeo
            # net_labels[root] queda con un único nombre tras la sobrescritura.
            # Para no mal-etiquetar, si el cable parte de un componente de fase,
            if label in self.RESERVED_NAMES:
                start_tag = self._get_comp_tag(connection.start_component)
                if start_tag in self.RESERVED_NAMES:
                    return start_tag
            return label
        except Exception:
            return ""

    # HELPERS COMUNES (no modifican el estilo por Bloques de Motor)

    def _collect_reserved_nets(self):
        """Marca las redes conectadas a nombres reservados (L1, N, PE, +24V...).

        Retorna (processed_nets, potential_reserved) donde
        processed_nets es un set con los roots reservados y
        potential_reserved es un dict {name: [net_root,...]}.
        """
        reserved_names = self.RESERVED_NAMES
        potential_reserved = {}

        for (c_id, p_idx), net_root in self.net_map.items():
            comp = self.comp_map.get(c_id)
            tag = self._get_comp_tag(comp)
            if tag in reserved_names:
                potential_reserved.setdefault(tag, []).append(net_root)

        processed_nets = set()
        for name, roots in potential_reserved.items():
            for net_root in roots:
                self.net_labels[net_root] = name
                processed_nets.add(net_root)
        return processed_nets, potential_reserved

    def _build_graphs(self):
        """Construye las relaciones red->componentes, componente->redes y
        componente->(red->indice de punto). El indice de punto es necesario
        para que _resolve_net_potentials NO propague el potencial entre
        polos aislados de un componente multi-polo (contactor, rele termico,
        borne, motor), donde cada polo es un circuito independiente."""
        net_to_comps = {}
        comp_to_nets = {}
        comp_to_net_points = {}
        for (c_id, p_idx), net_root in self.net_map.items():
            net_to_comps.setdefault(net_root, set()).add(c_id)
            comp_to_nets.setdefault(c_id, set()).add(net_root)
            comp_to_net_points.setdefault(c_id, {}).setdefault(net_root, []).append(p_idx)
        return net_to_comps, comp_to_nets, comp_to_net_points

    def _get_potential(self, comp):
        """Potencial declarado por una FUENTE (fuente DC/AC o Variador).

        OJO: en el resto de componentes el campo 'voltaje' de la etiqueta es la
        tension de chapa (220, 24V AC...), NO un potencial de nodo, asi que no
        debe usarse para agrupar cables; solo se lee en las fuentes, donde si
        representa la tension de salida.
        """
        if comp is None:
            return ""
        svg = str(getattr(comp, 'svg_file', '') or '').lower()
        if not any(k in svg for k in ('power_supply_dc', 'power_supply_ac', 'vdf-c')):
            return ""
        label_data = getattr(comp, 'label_data', {}) or {}
        if isinstance(label_data, dict):
            raw = label_data.get('voltaje') or label_data.get('voltage') or ''
        else:
            raw = getattr(label_data, 'voltaje', '') or ''
        return str(raw).strip().upper().replace(' ', '')

    # Protecciones: al atravesarlas arranca un circuito nuevo y por ahi cambia la
    # numeracion (L1 = 1, y la salida del breaker de control = 11).
    _PROTECTION_KEYWORDS = (
        'breaker', 'disyuntor', 'fuse', 'fusible',
        'rele-thermal', 'thermal-overload', 'rele_termico', 'termo',
    )

    def _is_supply(self, comp):
        """True si el componente es la barra de alimentacion (fase.svg: L1, L2,
        L3, N, PE...). Son el ORIGEN real del circuito y las unicas que siembran
        el numero base del potencial. Los conectores de borna (conxn/conxn2) NO
        son barras: son la entrada de alimentacion de la hoja, y aunque no
        sembren un potencial propio, ese cable pertenece al mismo circuito que
        la barra de origen.
        """
        if comp is None:
            return False
        if getattr(comp, 'component_type', '') == 'fase':
            return True
        return 'fase' in str(getattr(comp, 'svg_file', '') or '').lower()

    def _conducts_phase(self, comp):
        """True si el potencial de fase atraviesa internamente el componente.

        Las cargas (bobinas, resistencias, pilotos...) aislan: el cable del otro
        lado del componente no pertenece a la misma fase. Bornas, puntos de
        union, contactores, selectores, etc. si conducen.
        """
        if comp is None:
            return False
        svg = str(getattr(comp, 'svg_file', '') or '').lower()
        return not any(k in svg for k in self._PHASE_ISOLATING_KEYWORDS)

    def _comp_order_key(self, c_id):
        """Clave de orden estable de un componente. No usar id(): cambia entre
        ejecuciones y hacia que la numeracion dependa del orden de los elementos."""
        comp = self.comp_map.get(c_id)
        if comp is None:
            return (0.0, 0.0, '', 0)
        pts = getattr(comp, 'conn_points', []) or []
        px, py = (getattr(pts[0], 'x', 0), getattr(pts[0], 'y', 0)) if pts else (0, 0)
        return (getattr(comp, 'y', 0) + py, getattr(comp, 'x', 0) + px,
                self._get_comp_tag(comp), len(pts))

    def _net_order_key(self, net_root):
        """Clave de orden estable de una red, de arriba abajo y de izquierda a
        derecha, para que la numeracion salga siempre en el mismo orden."""
        kx, ky = self._get_net_sort_key(net_root)
        return (ky, kx)

    def _resolve_net_potentials(self):
        """Determina el potencial electrico (L1, L2, L3, N, PE...) de cada red.

        Se siembran las redes de las barras de fase y de las fuentes DC/AC/VFD, y
        luego el potencial se propaga de red a red a traves de los componentes
        conductores, de modo que un cable alimentado desde L1 hereda L1 aunque
        pase por bornas, contactores o selectores.

        La propagacion va por ondas: gana el potencial mas proximo a su barra y, a
        igualdad de distancia, el de menor rango de fase (L1 antes que L2, L2 antes
        que L3...). Asi el resultado no depende del orden en que se crea el grafo.

        Devuelve (net_potential, supply_roots, feed_roots):
          supply_roots: redes de las barras fase.svg (origen del circuito)
          feed_roots:   redes de los conectores de alimentacion de la hoja
        """
        net_to_comps, comp_to_nets, comp_to_net_points = self._build_graphs()

        net_potential = {}
        supply_roots = set()
        feed_roots = set()

        def rank(pot):
            return self._potential_rank(pot)

        # 1) Semillas: barras de fase (L1, L2, L3, N, PE...) y fuentes DC/AC/VFD
        seeds = {}
        for c_id in sorted(self.comp_map, key=self._comp_order_key):
            comp = self.comp_map[c_id]
            tag = self._get_comp_tag(comp)
            declared = self._get_potential(comp)
            if tag in self.RESERVED_NAMES:
                pot = tag
            elif declared:
                pot = declared
            else:
                continue
            is_supply = self._is_supply(comp)
            for p_idx in range(len(getattr(comp, 'conn_points', []) or [])):
                root = self.net_map.get((c_id, p_idx))
                if root is None:
                    continue
                prev = seeds.get(root)
                if prev is None or rank(pot) < rank(prev):
                    seeds[root] = pot
                (supply_roots if is_supply else feed_roots).add(root)

        # 2) Propagacion del potencial a traves de los componentes conductores.
        #   La propagacion es POR POLO: en componentes multi-polo (contactor,
        #   rele termico, borne, motor) cada polo es un circuito independiente,
        #   asi que el potencial NO salta de un polo a otro.
        net_potential.update(seeds)
        seen = set(seeds)
        frontier = sorted(seeds, key=self._net_order_key)
        while frontier:
            proposals = {}
            for root in frontier:
                pot = net_potential[root]
                comps = sorted(net_to_comps.get(root, ()), key=self._comp_order_key)
                for c_id in comps:
                    if not self._conducts_phase(self.comp_map.get(c_id)):
                        continue
                    nxt_pts = comp_to_net_points.get(c_id, {}).get(root, ())
                    half = len(getattr(self.comp_map.get(c_id), 'conn_points', []) or []) // 2
                    for nxt in comp_to_nets.get(c_id, ()):
                        if nxt in seen:
                            continue
                        # Solo propagar al MISMO POLO del componente:
                        # puntos i e i+n//2 son del mismo polo.
                        if half > 0:
                            rpts = set(nxt_pts)
                            ok = any((q % half) == (p % half)
                                     for p in rpts
                                     for q in comp_to_net_points.get(c_id, {}).get(nxt, ()))
                            if not ok:
                                continue
                        prev = proposals.get(nxt)
                        if prev is None or rank(pot) < rank(prev):
                            proposals[nxt] = pot
            if not proposals:
                break
            net_potential.update(proposals)
            seen.update(proposals)
            frontier = sorted(proposals, key=self._net_order_key)

        return net_potential, supply_roots, feed_roots

    def _starts_circuit(self, comp):
        """True si el componente es una proteccion (disyuntor, fusible, rele
        termico). Al atravesarlo arranca un circuito nuevo, y por tanto la
        numeracion cambia: la alimentacion mantiene el numero de la barra y la
        salida de la proteccion ya es una derivacion.

        Un contactor, un pulsador o una borna NO cortan el circuito: el numero se
        mantiene a lo largo de todo el recorrido.
        """
        if comp is None:
            return False
        svg = str(getattr(comp, 'svg_file', '') or '').lower()
        return any(k in svg for k in self._PROTECTION_KEYWORDS)

    def _protection_outputs(self, comp):
        """Indices de los puntos de SALIDA de una proteccion.

        En los simbolos de disyuntor los puntos van ordenados como
        [entradas..., salidas...] (un polo por columna), y en los rele termico y
        contactor como [linea..., carga...], de modo que la segunda mitad de los
        puntos son siempre las salidas. Permite propagar el circuito en un solo
        sentido: la alimentacion no puede quedar "detras" de su propio breaker.
        """
        n = len(getattr(comp, 'conn_points', []) or [])
        if n < 2:
            return ()
        return range(n // 2, n)

    def _split_by_protection(self, roots, entries, net_to_comps, comp_to_nets,
                             position_key):
        """Separa las redes de un potencial en dos conjuntos.

        continuation: redes que ANTES de la primera proteccion. Llevan el
                      numero base (1, 2, 3...) porque todavia estan
                      alimentadas directamente por la barra.
        circuits:     redes YA TRAS la primera proteccion. Todas llevan
                      el MISMO numero de derivacion (base+10, es decir
                      11, 21, 31...). DENTRO de la hoja ese numero NO
                      cambia al atravesar protecciones intermedias,
                      bornas o ramales; solo cambia cuando el circuito
                      SALE de la hoja.
        """
        group = set(roots)
        continuation = set()
        circuits = []

        pending = sorted((r for r in entries if r in group), key=position_key)
        origins = set(pending)
        crossed = {r: False for r in pending}
        seq = {r: i for i, r in enumerate(pending)}
        counter = len(pending)
        queue = list(pending)

        def reach(nxt, value):
            """Marca la red como alcanzable; una proteccion traversada la marca
            aunque llegue otro camino sin cruzar. True si hay que visitarla."""
            if nxt not in group or nxt in origins:
                return False   # la barra y los conectores son el origen: no hay
                                # proteccion "detras" de ellos
            if nxt not in crossed:
                crossed[nxt] = value
                return True
            if value and not crossed[nxt]:
                crossed[nxt] = True      # ahora pasa a ser circuito nuevo
                return True
            return False

        while queue:
            root = queue.pop(0)
            comps = sorted(net_to_comps.get(root, ()), key=self._comp_order_key)
            for c_id in comps:
                comp = self.comp_map.get(c_id)
                is_prot = self._starts_circuit(comp)
                if not is_prot and not self._conducts_phase(comp):
                    continue
                if is_prot:
                    # Solo hacia las SALIDAS de la proteccion: cruzarla arranca un
                    # circuito nuevo, pero la entrada sigue siendo alimentacion.
                    targets = [self.net_map.get((c_id, i))
                               for i in self._protection_outputs(comp)]
                else:
                    targets = comp_to_nets.get(c_id, ())
                for nxt in sorted(targets, key=self._net_order_key):
                    if reach(nxt, crossed[root] or is_prot):
                        seq[nxt] = counter
                        counter += 1
                        queue.append(nxt)

        # Redes del grupo que no enlazan con la entrada
        for root in sorted(group - set(crossed), key=position_key):
            crossed[root] = True
            seq[root] = counter
            counter += 1

        # El recorrido BFS da el orden de ramificacion: ese es el orden de las
        # derivaciones, para que 11, 12, 13... salgan en el orden real del circuito.
        for root in sorted(crossed, key=lambda r: seq[r]):
            if crossed[root]:
                circuits.append(root)
            else:
                continuation.add(root)

        return continuation, circuits

    def _potential_rank(self, pot):
        """Orden de los grupos: L1, L2, L3, L4, N, GND, otros, sin potencial.

        PE no se ordena aqui: se resuelve aparte con su designacion de norma
        (IEC 60445:2021 §7.3.3) y no entra en la serie numerica.
        """
        if pot in self._PHASE_RANK:
            return self._PHASE_RANK.index(pot)
        return len(self._PHASE_RANK) + (2 if not pot else 1)

    # ESTILO: Numeración Secuencial por Regleta de Bornes
    def _assign_labels_sequential_terminal(self, sheet_idx):
        """Numeración correlativa simple (1, 2, 3...) de arriba-abajo e izq-der,
        conservando los nombres reservados de las barras (L1, N, PE, +24V...)."""
        processed_nets, _ = self._collect_reserved_nets()

        all_roots = set(self.net_map.values())
        unnamed_roots = list(all_roots - processed_nets)
        unnamed_roots.sort(key=lambda net: (
            self._get_net_sort_key(net)[1],  # Y primario (arriba -> abajo)
            self._get_net_sort_key(net)[0]   # X secundario
        ))

        page_prefix = sheet_idx * 100
        for i, net_root in enumerate(unnamed_roots, 1):
            self.net_labels[net_root] = str(page_prefix + i)

    # ESTILO: Numeración por Código de Motor (Estructura de Bloque de Campo)
    def _assign_labels_field_code(self, sheet_idx):
        """Cada campo (motor/carga) forma un bloque de campo numerado con el
        código del campo como prefijo: '<Campo>-<n>'. Las barras reservadas
        conservan su nombre."""
        processed_nets, _ = self._collect_reserved_nets()
        net_to_comps, comp_to_nets, _ = self._build_graphs()

        # Identificar campos (motores M1, M2...) ordenados de izquierda a derecha
        fields = []
        for c_id, comp in self.comp_map.items():
            tag = self._get_comp_tag(comp)
            if tag.startswith('M'):
                fields.append((tag, comp))
        fields.sort(key=lambda item: getattr(item[1], 'x', 0))

        if not fields:
            # Sin campos detectados: numerar correlativo como respaldo
            self._assign_labels_sequential_terminal(sheet_idx)
            return

        assigned_nets = set(processed_nets)
        counter = 0

        for index, (field_tag, field_comp) in enumerate(fields, 1):
            field_code = str(index)
            branch_nets = set()
            queue = [id(field_comp)]
            visited_comps = {id(field_comp)}

            while queue:
                curr_cid = queue.pop(0)
                for net in comp_to_nets.get(curr_cid, set()):
                    if net not in assigned_nets and net not in branch_nets:
                        branch_nets.add(net)
                        for next_cid in net_to_comps.get(net, set()):
                            if next_cid not in visited_comps:
                                visited_comps.add(next_cid)
                                queue.append(next_cid)

            sorted_branch = sorted(branch_nets, key=lambda net: (
                self._get_net_sort_key(net)[1],
                self._get_net_sort_key(net)[0]
            ))
            for i, net in enumerate(sorted_branch, 1):
                self.net_labels[net] = f"{field_code}-{i}"
                assigned_nets.add(net)
                counter += 1

        # Cables que no pertenecen a ningún campo (control / huérfanos)
        all_roots = set(self.net_map.values())
        unnamed_roots = list(all_roots - assigned_nets)
        unnamed_roots.sort(key=lambda net: (
            self._get_net_sort_key(net)[1],
            self._get_net_sort_key(net)[0]
        ))
        block_code = str(len(fields) + 1)
        for i, net in enumerate(unnamed_roots, 1):
            self.net_labels[net] = f"{block_code}-{i}"

    # ESTILO: Numeración por Potencial
    def _assign_labels_by_potential(self, sheet_idx):
        """Agrupa los cables por su potencial electrico y numera cada potencial.

        La barra de alimentacion (fase.svg) fija el numero base de su fase:

            L1 -> 1,  L2 -> 2,  L3 -> 3,  L4 -> 4,  N -> 5...

        Ese numero se mantiene a lo largo de TODO el recorrido ANTES de
        la primera proteccion (disyuntor). Despues de esa proteccion el
        circuito entero (troncal Y ramales) recibe UN unico numero de
        derivacion (base+10 = 11, 21, 31...):

            L1 -> 1                              alimentacion, hasta el breaker
                  11                             TODO el circuito protegido
            L2 -> 2   con  21                    y lo mismo en cada fase

        El numero NO cambia al atravesar bornas, contactores, pulsadores
        o protecciones intermedias dentro de la hoja. Solo cambia cuando
        el cable SALE de esa hoja.

        EXCEPCION: el conductor de proteccion NO se numera. Segun
        IEC 60445:2021 §7.3.3 su designacion alfanumerica es "PE", y el
        formato L+dígito de §7.3.11 es exclusivo de conductores de linea.
        El recorrido completo de tierra lleva "PE" y no consume numero en
        la serie, de modo que los potenciales siguientes no se corren.
        """
        net_potential, supply_roots, feed_roots = self._resolve_net_potentials()
        net_to_comps, comp_to_nets, _ = self._build_graphs()
        position_key = self._net_order_key

        # 1) Agrupar las redes por potencial
        groups = {}
        for root in sorted(set(self.net_map.values()), key=position_key):
            groups.setdefault(net_potential.get(root, ''), []).append(root)

        # 1b) Potenciales con designacion fija por norma (PE): se etiquetan con
        # su designacion en TODO el recorrido y quedan fuera de la serie.
        for pot, designation in self._DESIGNATED_POTENTIALS.items():
            for root in groups.pop(pot, ()):
                self.net_labels[root] = designation

        # 2) Un numero base por potencial, en orden canonico de fase
        ordered_pots = sorted(groups, key=lambda p: (self._potential_rank(p), p))

        number = 1
        for pot in ordered_pots:
            roots = groups[pot]
            supplies = [r for r in roots if r in supply_roots]
            # Todos los puntos de entrada son el CIRCUITO de la barra, no una
            # derivacion suya: la propia barra de la hoja y sus conectores de
            # alimentacion (p. ej. la entrada de L1 en la hoja de Control).
            entries = sorted(
                set(supplies) | {r for r in roots if r in feed_roots},
                key=position_key,
            )

            if entries:
                continuation, circuits = self._split_by_protection(
                    roots, entries, net_to_comps, comp_to_nets, position_key
                )
            else:
                # Sin barra ni conector no hay de donde seguir: la primera red
                # hace de circuito y las demas cuelgan de ella.
                ordered = sorted(roots, key=position_key)
                continuation = set(ordered[:1])
                circuits = ordered[1:]

            # 3) Numero base: la barra y todo lo que continua su circuito
            for root in sorted(continuation, key=position_key):
                self.net_labels[root] = str(number)

            # 4) Derivaciones: la proteccion arranca UN circuito nuevo.
            # Cada red conserva el numero de su propia fase:
            #   L1 -> 11, L2 -> 21, L3 -> 31, N -> 41...
            # DENTRO de la hoja ese numero NO cambia al atravesar
            # protecciones intermedias, bornas o ramales; solo cambia
            # cuando el circuito SALE de la hoja.
            for root in sorted(circuits, key=position_key):
                self.net_labels[root] = f"{number}1"

            number += 1

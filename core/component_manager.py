class ComponentManager:
    """Maneja todas las operaciones relacionadas con componentes eléctricos"""

    def __init__(self, main_app):
        """
        Inicializa el gestor de componentes

        Args:
            main_app: Referencia a la aplicación principal PlanoElectrico
        """
        self.app = main_app

    def detectar_auto_conexion_componente(self, componente, conexion):
        """
        Detecta si una línea de conexión pasa por puntos de conexión de un componente.
        Retorna TODOS los índices de puntos intersectados (ordenados start->end), o None si no hay.
        """
        # Verificar que conexion tiene los atributos necesarios de Connection
        if not hasattr(conexion, 'start_component') or not hasattr(conexion, 'end_component'):
            return None

        # No procesar conexiones que ya están conectadas a este componente
        if conexion.start_component == componente or conexion.end_component == componente:
            return None

        puntos_componente = componente.get_connection_points_global()
        if not puntos_componente or not conexion.segments:
            return None

        tolerancia = 18  # Píxeles de tolerancia para detectar intersección

        candidatos = self._puntos_sobre_segmentos(
            puntos_componente, conexion.segments, tolerancia)

        if not candidatos:
            return None

        # `candidatos` viene YA ordenado por longitud de arco en dirección start->end y
        # sin índices repetidos, para que el borne más cercano al inicio de la línea
        # quede primero y las uniones no se crucen (caso típico: línea vertical donde el
        # orden interno de conn_points no coincide con el recorrido de la línea).
        # Descartar los bornes de carriles PARALELOS que la línea no recorre: al ser
        # la tolerancia mayor que la mitad del paso entre bornes, una línea vertical
        # desalineada unos pocos píxeles "ve" dos columnas del contactor de 3 polos
        # (3 arriba + 3 abajo). Al encadenarlos en orden de línea el borne superior
        # de la columna lejana quedaba unido al inferior de la columna cercana y los
        # conductores se cruzaban sobre el componente.
        candidatos = self._descartar_carriles_paralelos(candidatos, puntos_componente)

        return [(j, seg) for _arc, j, seg, _off, _along, _eje, _o in candidatos]

    def _puntos_sobre_segmentos(self, puntos_componente, segmentos, tolerancia):
        """
        Localiza los puntos de conexión que caen dentro de `tolerancia` de algún tramo
        (casi) vertical/horizontal de `segmentos`.

        Retorna una lista de tuplas, YA ORDENADA por longitud de arco start->end y sin
        índices repetidos (un mismo borne puede caer dentro de tolerancia de dos
        tramos contiguos en un quiebre Manhattan; se conserva el primero en orden
        start->end para no crear conexiones degeneradas punto->punto):

            (arc, j, seg, offset, coord_along, eje, orientacion)

            arc         longitud de arco desde el inicio de la conexión hasta el borne
            offset      distancia perpendicular del borne a la recta del tramo
            coord_along coordenada del borne sobre el eje del tramo (y si es vertical)
            eje         'V' o 'H' según el eje sobre el que se extiende el tramo
        """
        # Desviación máxima (px) para considerar un tramo vertical/horizontal.
        # Las conexiones pueden quedar ligeramente inclinadas (p.ej. 0.5 px) porque
        # los bornes de dos componentes no están perfectamente alineados; si se
        # exige x1==x2 exacto, esa fase se ignora y solo conectan las otras dos.
        eps_axis = 2.0

        # Longitud de arco al inicio de cada tramo (para ordenar en dirección start->end)
        acum_inicio = []
        acum = 0.0
        for (x1, y1), (x2, y2) in segmentos:
            acum_inicio.append(acum)
            acum += abs(x2 - x1) + abs(y2 - y1)

        candidatos = []
        for i, ((x1, y1), (x2, y2)) in enumerate(segmentos):
            dy = abs(y2 - y1)
            dx = abs(x2 - x1)
            es_vertical = dx <= eps_axis and dy > eps_axis
            es_horizontal = dy <= eps_axis and dx > eps_axis
            if not es_vertical and not es_horizontal:
                if dx <= eps_axis and dy <= eps_axis:
                    es_vertical = True  # Tramo degenerado
                else:
                    continue  # Línea diagonal - no procesar

            for j, (px, py, punto) in enumerate(puntos_componente):
                if punto.connected:  # Saltar puntos ya conectados
                    continue

                if es_vertical:
                    # Posición x del tramo interpolada a la altura del borne
                    if dy > 1e-9:
                        t = (py - y1) / (y2 - y1)
                        if not (0.0 <= t <= 1.0):
                            continue
                        x_seg = x1 + t * (x2 - x1)
                    else:
                        x_seg = x1
                    offset = abs(px - x_seg)
                    if offset > tolerancia:
                        continue
                    d_along = abs(py - y1)
                    coord_along = py
                else:  # es_horizontal
                    # Posición y del tramo interpolada a la abscisa del borne
                    if dx > 1e-9:
                        t = (px - x1) / (x2 - x1)
                        if not (0.0 <= t <= 1.0):
                            continue
                        y_seg = y1 + t * (y2 - y1)
                    else:
                        y_seg = y1
                    offset = abs(py - y_seg)
                    if offset > tolerancia:
                        continue
                    d_along = abs(px - x1)
                    coord_along = px

                candidatos.append((
                    acum_inicio[i] + d_along, j, i, offset, coord_along,
                    'V' if es_vertical else 'H',
                    getattr(punto, 'orientation', None) or 'N',
                ))

        candidatos.sort(key=lambda c: c[0])

        # Deduplicar puntos que coinciden con el vértice de un quiebre Manhattan
        vistos = set()
        unicos = []
        for c in candidatos:
            if c[1] in vistos:
                continue
            vistos.add(c[1])
            unicos.append(c)
        return unicos

    @staticmethod
    def _paso_entre_bornes(puntos_componente):
        """
        Separación mínima (px) entre dos bornes del componente.
        Se usa como escala para decidir si dos bornes son vecinos de una misma fila
        o columna. Devuelve None si el componente no tiene al menos 2 bornes o si sus
        bornes están superpuestos (p.ej. un empalme), porque entonces no existe un
        paso con el que agrupar y la comparación no aportaría información.
        """
        coords = [(p[0], p[1]) for p in puntos_componente]
        paso = None
        for a in range(len(coords)):
            for b in range(a + 1, len(coords)):
                dx = coords[a][0] - coords[b][0]
                dy = coords[a][1] - coords[b][1]
                d = (dx * dx + dy * dy) ** 0.5
                if d > 1.0 and (paso is None or d < paso):
                    paso = d
        return paso

    def _descartar_carriles_paralelos(self, candidatos, puntos_componente):
        """
        Una línea recta sólo puede pertenecer a UN carril de bornes.

        Si un tramo vertical pasa cerca de dos columnas de bornes (caso típico del
        contactor de 3 polos: 3 arriba y 3 abajo, paso de 20 px con tolerancia de
        18 px), se conservan únicamente los bornes de la columna MÁS CERCANA a la
        línea; los de la columna vecina se descartan porque la línea no pasa por
        ellos. Sin este descarte la cadena resultante unía el borne superior de una
        columna con el inferior de la otra y los conductores se cruzaban.

        Se agrupa por (eje del tramo, orientación del borne, posición a lo largo del
        tramo) y dentro de cada grupo gana el borne de menor offset perpendicular.
        La orientación del borne mantiene fuera del grupo a los pares de una misma
        columna de un dispositivo de 1 polo (N arriba, S abajo), que deben seguir
        conectándose ambos, y la coordenada a lo largo del tramo mantiene separado
        cada borne de una fila, de modo que una línea horizontal que recorre una fila
        completa sigue conectándolos a todos.
        """
        paso = self._paso_entre_bornes(puntos_componente)
        if not paso:
            return candidatos

        limite = paso * 0.5
        grupos = []  # [{'eje':, 'orient':, 'coord':, 'items': [...]}, ...]

        for c in candidatos:
            _arc, _j, _seg, _offset, coord_along, eje, orient = c
            grupo = None
            for g in grupos:
                if g['eje'] == eje and g['orient'] == orient and abs(coord_along - g['coord']) <= limite:
                    grupo = g
                    break
            if grupo is None:
                grupos.append({'eje': eje, 'orient': orient, 'coord': coord_along, 'items': [c]})
            else:
                grupo['items'].append(c)

        resultado = []
        for g in grupos:
            if len(g['items']) == 1:
                resultado.append(g['items'][0])
            else:
                # El carril más cercano a la línea gana; a igualdad el primero en
                # orden start->end (desempate estable por sort).
                resultado.append(min(g['items'], key=lambda c: c[3]))

        resultado.sort(key=lambda c: c[0])
        return resultado

    def ejecutar_auto_conexion(self, componente, conexion_original, puntos_interseccion):
        """
        Ejecuta la auto-conexión partiendo la línea original y creando nuevas conexiones a
        los puntos del componente.
        Soporta 1 punto (conexión en extremo sin dividir), 2 puntos (inserción en serie clásica:
        start->p0 y p1->end) y 3+ puntos (cadena completa start->p0->p1->...->pN-1->end, conectando
        TODOS los puntos que corta la línea).
        """
        try:
            # CRÍTICO: Mantener exactamente los puntos detectados en el preview.
            # Si ya se calculó una intersección válida, no volver a buscar otros puntos
            # ni reordenar por cercanía para evitar que la conexión final difiera del preview.
            puntos_componente = componente.get_connection_points_global()
            conexion_detectada = None
            puntos_ordenados = [] # Índices de puntos del componente a conectar (orden start->end)

            if puntos_interseccion:
                conexion_detectada = conexion_original
                # Ya vienen ordenados por posición a lo largo de la línea (start->end)
                # desde detectar_auto_conexion_componente; NO reordenar o se cruzan.
                puntos_ordenados = [j for j, _seg in puntos_interseccion]
            else:
                # 1. UBICAR los puntos de conexión del componente más cercanos a la línea
                # Encontrar qué conexión es la más cercana a los puntos del componente
                tolerancia = 12
                for conexion in self.app.connections:
                    if conexion == conexion_original:
                        continue

                    # Verificar si hay puntos del componente cerca de esta conexión
                    # (mismo criterio que detectar_auto_conexion_componente, incluyendo
                    # el descarte de carriles paralelos: si no, un tramo vertical
                    # desalineado elegiría los 2 bornes de una misma fila).
                    candidatos = self._puntos_sobre_segmentos(
                        puntos_componente, conexion.segments, tolerancia)
                    candidatos = self._descartar_carriles_paralelos(
                        candidatos, puntos_componente)

                    # Si encontramos al menos 2 puntos cerca, esta es nuestra conexión
                    if len(candidatos) >= 2:
                        # Ordenar por distancia y tomar los 2 más cercanos (comportamiento legacy)
                        candidatos.sort(key=lambda c: c[3])
                        conexion_detectada = conexion
                        puntos_ordenados = [candidatos[0][1], candidatos[1][1]]
                        break

                # Si no hay puntos de intersección válidos, usar la conexión original
                if not conexion_detectada:
                    if puntos_interseccion and len(puntos_interseccion) >= 1:
                        conexion_detectada = conexion_original
                        puntos_ordenados = [j for j, _seg in puntos_interseccion]
                    else:
                        return

            if not conexion_detectada or not puntos_ordenados:
                return

            # Importar Connection si es necesario
            if self.app.connections:
                Connection = type(self.app.connections[0])
            else:
                from models.connection import Connection

            start_comp = conexion_detectada.start_component
            start_idx = conexion_detectada.start_point_idx
            end_comp = conexion_detectada.end_component
            end_idx = conexion_detectada.end_point_idx

            # CASO DE 1 PUNTO: Conectar sin dividir la línea
            punto_mas_cercano_1 = puntos_ordenados[0]
            if len(puntos_ordenados) == 1:
                px_comp, py_comp, _ = puntos_componente[punto_mas_cercano_1]

                # Calcular distancia al inicio y al fin de la conexión
                pts_start = start_comp.get_connection_points_global()
                pts_end = end_comp.get_connection_points_global()
                sx, sy, _ = pts_start[start_idx] if start_idx < len(pts_start) else (0, 0, None)
                ex, ey, _ = pts_end[end_idx] if end_idx < len(pts_end) else (0, 0, None)
                dist_start = ((px_comp - sx) ** 2 + (py_comp - sy) ** 2) ** 0.5
                dist_end = ((px_comp - ex) ** 2 + (py_comp - ey) ** 2) ** 0.5

                # No borrar la línea original; simplemente agregar la conexión al extremo más cercano
                if dist_start <= dist_end:
                    # Conectar al inicio: componente <-> start_comp
                    nueva_conexion = Connection(componente, punto_mas_cercano_1, start_comp, start_idx)
                else:
                    # Conectar al final: componente <-> end_comp
                    nueva_conexion = Connection(componente, punto_mas_cercano_1, end_comp, end_idx)

                # Preservar estilo
                for attr in ('line_color', 'line_width', 'line_dash'):
                    if hasattr(conexion_detectada, attr):
                        setattr(nueva_conexion, attr, getattr(conexion_detectada, attr))

                self.app.connections.append(nueva_conexion)
                self.app.manhattan_router.update_manhattan_line(nueva_conexion)
                componente.draw_connection_points()
                return

            # 2. BUSCAR LOS IDs DE LAS LÍNEAS que salen de los puntos de conexión más cercanos
            line_ids_a_eliminar = self.app.obtener_line_ids_de_punto_conexion(
                conexion_detectada.start_component,
                conexion_detectada.start_point_idx
            )
            line_ids_a_eliminar.extend(
                self.app.obtener_line_ids_de_punto_conexion(
                    conexion_detectada.end_component,
                    conexion_detectada.end_point_idx
                )
            )

            # 3. BORRAR la línea original ANTES de fijar las nuevas
            if hasattr(conexion_original, 'line_ids'):
                for line_id in conexion_original.line_ids:
                    try:
                        self.app.canvas.delete(line_id)
                    except:
                        pass
            # Remover la conexión de la lista
            if conexion_original in self.app.connections:
                self.app.connections.remove(conexion_original)
            # 5. CREAR nuevas conexiones

            # Secuencia de terminales por donde pasará la línea tras el corte:
            secuencia = [(start_comp, start_idx)]
            secuencia.extend((componente, j) for j in puntos_ordenados)
            secuencia.append((end_comp, end_idx))

            # Parejas consecutivas a enlazar:
            # 2 puntos: SOLO start->p0 y p1->end (inserción en serie clásica, sin
            #     acortar el componente porque el flujo pasa por su interior).
            # 3+ puntos: cadena completa start->p0->p1->...->pN-1->end para no dejar
            #     NINGUNO de los puntos del componente sin conectar (ej. 3 arriba y 3 abajo).
            if len(puntos_ordenados) == 2:
                pares = [(0, 1), (2, 3)]
            else:
                pares = [(i, i + 1) for i in range(len(secuencia) - 1)]

            nuevas_conexiones = []
            for i_a, i_b in pares:
                comp_a, idx_a = secuencia[i_a]
                comp_b, idx_b = secuencia[i_b]
                nueva = Connection(comp_a, idx_a, comp_b, idx_b)

                # PRESERVAR propiedades de estilo de la conexión original
                for attr in ('line_color', 'line_width', 'line_dash'):
                    if hasattr(conexion_detectada, attr):
                        setattr(nueva, attr, getattr(conexion_detectada, attr))

                self.app.connections.append(nueva)
                nuevas_conexiones.append(nueva)

            # 6. REDIBUJAR las nuevas conexiones
            for nueva in nuevas_conexiones:
                self.app.manhattan_router.update_manhattan_line(nueva)

            componente.draw_connection_points()

        except Exception as e:
            pass
            import traceback
            traceback.print_exc()

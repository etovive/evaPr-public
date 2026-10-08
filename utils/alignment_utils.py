def align_component_vertically(component, app):
    """
    Alinea verticalmente el componente seleccionado
    usando SOLO el punto al que YA está conectado.
    """
    for connection in app.connections:
        # ¿Este componente está en la conexión?
        if (connection.start_component == component or
            connection.end_component == component):

            if connection.start_component == component:
                comp1 = connection.start_component      # el que movemos
                point1_idx = connection.start_point_idx
                comp2 = connection.end_component        # el fijo
                point2_idx = connection.end_point_idx
            else:
                comp1 = connection.end_component
                point1_idx = connection.end_point_idx
                comp2 = connection.start_component
                point2_idx = connection.start_point_idx

            points1 = comp1.get_connection_points_global()
            points2 = comp2.get_connection_points_global()

            if (point1_idx < len(points1) and
                point2_idx < len(points2)):

                x1, y1, _ = points1[point1_idx]   # punto del componente móvil
                x2, y2, _ = points2[point2_idx]   # punto del componente fijo

                dx = x2 - x1
                component.move(dx, 0)

                for conn in app.connections:
                    if (conn.start_component == component or
                        conn.end_component == component):
                        app.update_manhattan_line(conn)

            # Solo necesitamos la primera conexión -> salir
            break

def align_multiple_components_vertically(components, app):
    """
    Alinea verticalmente múltiples componentes
    usando SOLO el punto conectado de cada uno.
    Ignora los puntos L1, L2, L3, N, PE no conectados para evitar superposición.
    """
    # Verificar que tenemos suficientes componentes válidos
    valid_components = [comp for comp in components
                       if hasattr(comp, 'get_connection_points_global') and
                          hasattr(comp, 'move')]

    if not valid_components or len(valid_components) < 2:
        return

    # Usar el primer componente como referencia
    reference_component = valid_components[0]
    reference_points = reference_component.get_connection_points_global()

    if not reference_points:
        return

    # Buscar el punto realmente conectado del componente de referencia
    ref_connected_point_idx = None
    for connection in app.connections:
        if (connection.start_component == reference_component or
            connection.end_component == reference_component):
            if connection.start_component == reference_component:
                ref_connected_point_idx = connection.start_point_idx
            else:
                ref_connected_point_idx = connection.end_point_idx
            break

    if ref_connected_point_idx is None or ref_connected_point_idx >= len(reference_points):
        return

    # Usar el punto realmente conectado como referencia
    ref_x, ref_y, _ = reference_points[ref_connected_point_idx]

    # Alinear todos los demás componentes usando SOLO su punto conectado
    for i, component in enumerate(valid_components):
        if i == 0:
            continue  # Saltar el componente de referencia

        points = component.get_connection_points_global()
        if not points:
            continue

        # Buscar el punto realmente conectado de este componente
        comp_connected_point_idx = None
        for connection in app.connections:
            if (connection.start_component == component or
                connection.end_component == component):
                if connection.start_component == component:
                    comp_connected_point_idx = connection.start_point_idx
                else:
                    comp_connected_point_idx = connection.end_point_idx
                break

        if comp_connected_point_idx is not None and comp_connected_point_idx < len(points):
            comp_x, comp_y, _ = points[comp_connected_point_idx]
            dx = ref_x - comp_x
            component.move(dx, 0)

    for component in valid_components:
        for conn in app.connections:
            if (conn.start_component == component or
                conn.end_component == component):
                app.update_manhattan_line(conn)

def distribute_components_horizontally(components, app):
    """
    Distribuye horizontalmente múltiples componentes de manera simple.
    X SE MANTIENE FIJA, Y ES LA QUE CAMBIA.
    Alinea todos los componentes en la misma Y (misma altura).

    CORRECCIÓN: El primer componente NO se mueve (queda completamente fijo).
    Los demás componentes sí se alinean en Y.
    """
    # Verificar que tenemos suficientes componentes válidos
    valid_components = [comp for comp in components
                       if hasattr(comp, 'get_connection_points_global') and
                          hasattr(comp, 'move')]

    if not valid_components or len(valid_components) < 2:
        return

    # Calcular la distribución horizontal
    component_info = []
    for i, component in enumerate(valid_components):
        try:
            points = component.get_connection_points_global()
            if not points:
                continue

            # Calcular centro usando: ((X + X')/2, (Y + Y')/2)
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            x_inicial, x_final = min(xs), max(xs)
            y_inicial, y_final = min(ys), max(ys)

            # Centro calculado correctamente
            center_x = (x_inicial + x_final) / 2
            center_y = (y_inicial + y_final) / 2

            component_info.append({
                'component': component,
                'center_x': center_x,
                'center_y': center_y,
                'y_inicial': y_inicial,
                'y_final': y_final
            })

        except Exception as e:
            continue

    if len(component_info) < 2:
        return

    # El primer componente debe permanecer completamente fijo
    # Todos los demás se alinean con la Y del primer componente
    if len(component_info) < 2:
        return

    # El primer componente debe permanecer fijo: usar su center_y como referencia
    reference_info = component_info[0]
    reference_y = reference_info['center_y']

    # Alinear todos los demás componentes a la Y del primero (solo mover en Y)
    for i, info in enumerate(component_info):
        if i == 0:
            continue  # no mover el componente de referencia
        component = info['component']
        dy = reference_y - info['center_y']
        if dy != 0:
            component.move(0, dy)

    for info in component_info:
        component = info['component']
        for conn in app.connections:
            if (conn.start_component == component or
                conn.end_component == component):
                app.update_manhattan_line(conn)

def distribute_components_equidistant_horizontally(components, app):
    """
    Distribuye horizontalmente múltiples componentes de manera equidistante.
    Los extremos (izquierdo y derecho) se mantienen fijos en Y (y en X obviamente),
    solo los intermedios se distribuyen horizontalmente de forma equidistante.
    """
    # Verificar que tenemos suficientes componentes válidos
    valid_components = [comp for comp in components
                       if hasattr(comp, 'get_connection_points_global') and
                          hasattr(comp, 'move')]

    if not valid_components or len(valid_components) < 2:
        return

    # Calcular la distribución horizontal
    component_info = []
    for i, component in enumerate(valid_components):
        try:
            points = component.get_connection_points_global()
            if not points:
                continue

            # Calcular centro usando: ((X + X')/2, (Y + Y')/2)
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            x_inicial, x_final = min(xs), max(xs)
            y_inicial, y_final = min(ys), max(ys)

            # Centro calculado correctamente
            center_x = (x_inicial + x_final) / 2
            center_y = (y_inicial + y_final) / 2

            component_info.append({
                'component': component,
                'center_x': center_x,
                'center_y': center_y,
                'original_y': center_y,  # Guardar Y original para mantenerla fija
                'x_inicial': x_inicial,
                'x_final': x_final
            })

        except Exception as e:
            continue

    if len(component_info) < 2:
        return

    # Ordenar por posición X para identificar extremos horizontales
    component_info.sort(key=lambda x: x['center_x'])

    # Si solo hay 2 componentes, no hacer nada (ya están en extremos)
    if len(component_info) == 2:
        return

    left_extreme = component_info[0]    # El de la izquierda
    right_extreme = component_info[-1]  # El de la derecha

    # Los componentes intermedios son todos excepto el primero y último
    intermediate_components = component_info[1:-1]

    if not intermediate_components:
        return

    # Los extremos se mantienen fijos en Y, no se mueven
    # Solo los intermedios se distribuyen horizontalmente

    # Calcular distribución equidistante
    # Distancia total disponible para distribuir los componentes intermedios
    total_distance = right_extreme['center_x'] - left_extreme['center_x']

    # Número de espacios entre componentes
    num_spaces = len(intermediate_components) + 1

    # Espaciado uniforme
    spacing = total_distance / num_spaces

    # Distribuir los componentes intermedios
    for i, info in enumerate(intermediate_components):
        component = info['component']

        # Posición X objetivo para distribución equidistante
        # Los intermedios van en las posiciones: 1*spacing, 2*spacing, 3*spacing, etc.
        x_target = left_extreme['center_x'] + (i + 1) * spacing

        # Calcular desplazamiento X necesario
        dx = x_target - info['center_x']

        component.move(dx, 0)

    for info in component_info:
        component = info['component']
        for conn in app.connections:
            if (conn.start_component == component or
                conn.end_component == component):
                app.update_manhattan_line(conn)

def distribute_components_vertically(components, app):
    """
    Distribuye verticalmente múltiples componentes de manera equidistante.
    Los extremos (superior e inferior) se mantienen fijos en X,
    solo los intermedios se distribuyen verticalmente de forma equidistante.
    """
    # Verificar que tenemos suficientes componentes válidos
    valid_components = [comp for comp in components
                       if hasattr(comp, 'get_connection_points_global') and
                          hasattr(comp, 'move')]

    if not valid_components or len(valid_components) < 2:
        return

    # Calcular la distribución vertical
    component_info = []
    for i, component in enumerate(valid_components):
        try:
            points = component.get_connection_points_global()
            if not points:
                continue

            # Calcular centro usando: ((X + X')/2, (Y + Y')/2)
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            x_inicial, x_final = min(xs), max(xs)
            y_inicial, y_final = min(ys), max(ys)

            # Centro calculado correctamente
            center_x = (x_inicial + x_final) / 2
            center_y = (y_inicial + y_final) / 2

            component_info.append({
                'component': component,
                'center_x': center_x,
                'center_y': center_y,
                'original_x': center_x,  # Guardar X original para mantenerla fija
                'y_inicial': y_inicial,
                'y_final': y_final
            })

        except Exception as e:
            continue

    if len(component_info) < 2:
        return

    # Ordenar por posición Y para identificar extremos verticales
    component_info.sort(key=lambda x: x['center_y'])

    # Si solo hay 2 componentes, no hacer nada (ya están en extremos)
    if len(component_info) == 2:
        return

    top_extreme = component_info[0]    # El de arriba
    bottom_extreme = component_info[-1] # El de abajo

    # Los componentes intermedios son todos excepto el primero y último
    intermediate_components = component_info[1:-1]

    if not intermediate_components:
        return

    # Los extremos se mantienen fijos en X, no se mueven
    # Solo los intermedios se distribuyen verticalmente

    # Calcular distribución equidistante
    # Distancia total disponible para distribuir los componentes intermedios
    total_distance = bottom_extreme['center_y'] - top_extreme['center_y']

    # Número de espacios entre componentes
    num_spaces = len(intermediate_components) + 1

    # Espaciado uniforme
    spacing = total_distance / num_spaces

    # Distribuir los componentes intermedios
    for i, info in enumerate(intermediate_components):
        component = info['component']

        # Posición Y objetivo para distribución equidistante
        # Los intermedios van en las posiciones: 1*spacing, 2*spacing, 3*spacing, etc.
        y_target = top_extreme['center_y'] + (i + 1) * spacing

        # Calcular desplazamiento Y necesario
        dy = y_target - info['center_y']

        component.move(0, dy)

    for info in component_info:
        component = info['component']
        for conn in app.connections:
            if (conn.start_component == component or
                conn.end_component == component):
                app.update_manhattan_line(conn)

def create_alignment_manager(app):
    class AlignmentManager:
        def __init__(self, app):
            self.app = app

        def align_selected_vertically(self):
            if hasattr(self.app, 'selected_component') and self.app.selected_component:
                align_component_vertically(self.app.selected_component, self.app)

        def align_multiple_vertically(self):
            if (hasattr(self.app, 'selected_elements') and
                len(self.app.selected_elements) > 1):
                # Filtrar solo los componentes (que tienen get_connection_points_global)
                components = [elem for elem in self.app.selected_elements
                             if hasattr(elem, 'get_connection_points_global')]

                if len(components) > 1:
                    align_multiple_components_vertically(components, self.app)
                else:
                    # OPTIMIZACIÓN O(1): Diccionario de mensajes en lugar de elif chain O(2)
                    error_messages = {
                        1: "Solo hay 1 componente válido para alinear (necesitas al menos 2)",
                        0: "No se encontraron componentes válidos para alinear"
                    }
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status(error_messages.get(len(components), "Error desconocido"), "orange")

        def distribute_multiple_equidistant_horizontally(self):
            if (hasattr(self.app, 'selected_elements') and
                len(self.app.selected_elements) > 1):
                # Filtrar solo los componentes (que tienen get_connection_points_global)
                components = [elem for elem in self.app.selected_elements
                             if hasattr(elem, 'get_connection_points_global')]

                if len(components) > 1:
                    distribute_components_equidistant_horizontally(components, self.app)
                else:
                    # OPTIMIZACIÓN O(1): Diccionario de mensajes en lugar de elif chain O(2)
                    error_messages = {
                        1: "Solo hay 1 componente válido para distribuir (necesitas al menos 2)",
                        0: "No se encontraron componentes válidos para distribuir"
                    }
                    if hasattr(self.app, 'set_status'):
                        self.app.set_status(error_messages.get(len(components), "Error desconocido"), "orange")

    return AlignmentManager(app)

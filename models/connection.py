class Connection:
    """
    Representa una conexión entre dos puntos de conexión de componentes.

    Esta clase almacena únicamente los datos de la conexión sin lógica de renderizado.
    El renderizado se maneja en las clases de vista/UI.
    """

    def __init__(self, start_component, start_point_idx, end_component, end_point_idx):
        """
        Inicializa una conexión entre dos componentes.

        Args:
            start_component: Componente de inicio
            start_point_idx (int): Índice del punto de conexión de inicio
            end_component: Componente de fin
            end_point_idx (int): Índice del punto de conexión de fin
        """
        self.start_component = start_component
        self.start_point_idx = start_point_idx
        self.end_component = end_component
        self.end_point_idx = end_point_idx
        self.line_ids = []  # IDs de elementos en canvas (UI)
        self.segments = []  # Segmentos Manhattan
        self.mid_y_offset = 0
        self.puntos_empalme = []  # Lista vacía para compatibilidad
        # Propiedades de estilo individual para líneas
        self.line_color = "black"     # Color individual
        self.line_width = 1           # Grosor individual
        self.line_dash = None         # Patrón individual
        # Posición de la etiqueta de numeración de cables (coords mundo), si fue movida
        self.wire_label_pos = None    # (x, y) centro de la etiqueta en coords de mundo
        # Texto manual de la etiqueta de numeración (None = usar numeración automática)
        self.wire_label_manual = None
        # Si la etiqueta de numeración debe ocultarse (borrada por el usuario)
        self.wire_label_hidden = False
        # Marcar puntos como conectados
        if hasattr(start_component, 'conn_points') and start_point_idx < len(start_component.conn_points):
            start_component.conn_points[start_point_idx].connected = True
        if hasattr(end_component, 'conn_points') and end_point_idx < len(end_component.conn_points):
            end_component.conn_points[end_point_idx].connected = True

    def __repr__(self):
        """Representación en string de la conexión"""
        return f"Connection(start={self.start_component}, start_point={self.start_point_idx}, end={self.end_component}, end_point={self.end_point_idx})"

    def to_dict(self, components_list):
        """
        Convierte la conexión a diccionario para serialización.

        Args:
            components_list (list): Lista de componentes para encontrar índices

        Returns:
            dict: Representación en diccionario de la conexión
        """
        start_idx = components_list.index(self.start_component) if self.start_component in components_list else -1
        end_idx = components_list.index(self.end_component) if self.end_component in components_list else -1

        data = {
            "start_component_idx": start_idx,
            "start_point_idx": self.start_point_idx,
            "end_component_idx": end_idx,
            "end_point_idx": self.end_point_idx,
            "mid_y_offset": self.mid_y_offset,
            # Propiedades de estilo
            "line_color": self.line_color,
            "line_width": self.line_width,
            "line_dash": self.line_dash,
            # Propiedades de manual routing
            "manually_modified": getattr(self, 'manually_modified', False)
        }

        if hasattr(self, 'manual_angle_points') and self.manual_angle_points:
            data["manual_angle_points"] = self.manual_angle_points

        if hasattr(self, 'segments') and self.segments:
            data["segments"] = self.segments

        if getattr(self, 'wire_label_pos', None):
            data["wire_label_pos"] = self.wire_label_pos

        if getattr(self, 'wire_label_manual', None):
            data["wire_label_manual"] = self.wire_label_manual
        if getattr(self, 'wire_label_hidden', False):
            data["wire_label_hidden"] = True

        return data

    @classmethod
    def from_dict(cls, data, components_list):
        """
        Crea una conexión desde un diccionario.

        Args:
            data (dict): Datos de la conexión
            components_list (list): Lista de componentes

        Returns:
            Connection: Nueva instancia de conexión
        """
        start_component = components_list[data["start_component_idx"]] if data["start_component_idx"] >= 0 else None
        end_component = components_list[data["end_component_idx"]] if data["end_component_idx"] >= 0 else None

        connection = cls(
            start_component,
            data["start_point_idx"],
            end_component,
            data["end_point_idx"]
        )

        connection.mid_y_offset = data.get("mid_y_offset", 0)

        # Restaurar propiedades de estilo
        connection.line_color = data.get("line_color", "black")
        connection.line_width = data.get("line_width", 1)
        connection.line_dash = data.get("line_dash", None)

        # Restaurar propiedades de manual routing
        connection.manually_modified = data.get("manually_modified", False)
        if "manual_angle_points" in data:
            connection.manual_angle_points = data["manual_angle_points"]

        # Restaurar segmentos Manhattan si existen
        if "segments" in data:
            connection.segments = data["segments"]

        # Restaurar posición movida de la etiqueta de numeración
        if "wire_label_pos" in data:
            connection.wire_label_pos = tuple(data["wire_label_pos"])

        # Restaurar texto manual / ocultación de la etiqueta de numeración
        if "wire_label_manual" in data:
            connection.wire_label_manual = data["wire_label_manual"]
        connection.wire_label_hidden = bool(data.get("wire_label_hidden", False))

        return connection

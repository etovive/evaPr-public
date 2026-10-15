from models.connection_point import ConnectionPoint, serialize_connection_points

class JunctionComponent:
    """
    Componente de empalme programático que no requiere archivo SVG.
    """

    def __init__(self, canvas, name, x, y, config=None):
        """
        Inicializa un componente de empalme.
        
        Args:
            canvas: Canvas de tkinter donde se dibuja
            name: Nombre del empalme (ej: "J1", "J2")
            x, y: Coordenadas del centro del empalme
            config: Configuración de la aplicación (opcional)
        """
        self.canvas = canvas
        self.name = name
        self.x = x
        self.y = y
        self.config = config or {}

        # Propiedades fijas de empalme
        self.size = [16, 16]  # Tamaño fijo para detección de colisiones
        self.original_size = [16, 16]
        self.rotation = 0
        self.category = "Junction"
        self.component_type = "junction"  # Tipo especial
        self.svg_file = None  # NO usa archivo SVG
        self.svg_path = None

        # Propiedades visuales (invisible)
        self.canvas_id = None
        self.point_ids = []
        self.selection_id = None
        self._selected = False

        # Label data (sin etiqueta visible)
        self.label_data = {
            'name': name,
            'visible': False,  # Empalmes no muestran etiqueta
            'position': 'bottom',
            'font_size': 10,
            'show_details': False  # Compatibilidad con Component.draw_label()
        }

        # Exactamente 2 puntos superpuestos en (0,0) para actuar como punto único de división
        # Esto replica la lógica original del SVG donde ambos puntos estaban en el origen
        self.conn_points = [
            ConnectionPoint(0, 0, radius=0.5, orientation='N'),  # Punto para línea entrante
            ConnectionPoint(0, 0, radius=0.5, orientation='S')   # Punto para línea saliente
        ]

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, value):
        # Igual que Component: al cambiar el estado se redibuja el círculo de
        # selección. Sin esta propiedad, `elem.selected = False` creaba un
        # atributo nuevo y `_selected` quedaba en True, por lo que los puntos de
        # conexión (empalmes) no se deseleccionaban visualmente.
        if self._selected != value:
            self._selected = value
            self.update_selection_visual()

    def draw(self):
        """
        Dibuja el componente de empalme (invisible, solo puntos de conexión).
        """
        # Limpiar elementos anteriores
        self._clear_component_elements()

        # CRÍTICO: NO dibujar NINGÚN elemento visual (ni imagen ni rectángulo)
        # Asegurar que canvas_id permanece None para que no se dibuje nada
        self.canvas_id = None

        # Solo dibujar puntos de conexión (invisibles cuando están conectados)
        self.draw_connection_points()

    def draw_connection_points(self):
        """
        Dibuja los puntos de conexión del empalme.
        """
        from models.component import draw_component_points

        draw_component_points(self.canvas, self)

    def get_connection_points_global(self):
        """
        Devuelve los puntos de conexión en coordenadas globales.
        
        Returns:
            Lista de tuplas (x_global, y_global, point_info)
        """
        points = []
        for point in self.conn_points:
            # Convertir de coordenadas locales a globales
            global_x = self.x + point.x
            global_y = self.y + point.y
            points.append((global_x, global_y, point))
        return points

    def contains_point(self, x, y):
        """
        Verifica si el punto (x, y) está dentro del área del empalme.
        
        Args:
            x, y: Coordenadas del mundo (lógicas)
            
        Returns:
            bool: True si el punto está dentro del empalme
        """
        # Comparar directamente en coordenadas del mundo (lógicas)
        return (self.x <= x <= self.x + self.size[0] and
                self.y <= y <= self.y + self.size[1])

    def move(self, dx, dy):
        """
        Mueve el empalme.
        
        Args:
            dx, dy: Desplazamiento en x e y
        """
        self.x += dx
        self.y += dy
        self.draw()

    def select(self):
        """Marca el empalme como seleccionado."""
        self._selected = True
        self.update_selection_visual()

    def delete(self):
        """Elimina completamente el componente del canvas."""
        self._clear_component_elements()

    def update_selection_visual(self):
        """Actualiza el visual de selección (círculo punteado)"""
        # Limpiar selección previa
        if self.selection_id:
            try:
                self.canvas.delete(self.selection_id)
            except Exception:
                pass
            self.selection_id = None

        # Si está seleccionado, dibujar círculo
        if self._selected:
            try:
                zoom = getattr(self.canvas, 'zoom_level', 1.0)
                # El empalme tiene tamaño 16x16, x/y es la esquina superior izquierda
                center_x = (self.x + 8) * zoom
                center_y = (self.y + 8) * zoom

                # Radio para cubrir el empalme
                radius = 12 * zoom

                self.selection_id = self.canvas.create_oval(
                    center_x - radius, center_y - radius,
                    center_x + radius, center_y + radius,
                    outline="#0080ff", width=1, dash=(4, 4), fill="", tags="selection_circle"
                )
            except Exception:
                pass

    def _clear_component_elements(self):
        """Limpia todos los elementos visuales del componente."""
        # Limpiar imagen (si existe)
        if self.canvas_id:
            try:
                self.canvas.delete(self.canvas_id)
            except Exception:
                pass
            self.canvas_id = None

        # Limpiar puntos de conexión
        component_tag = f"points_{id(self)}"
        self.canvas.delete(component_tag)
        self.point_ids = []

        # Limpiar selección
        if self.selection_id:
            try:
                self.canvas.delete(self.selection_id)
            except Exception:
                pass
            self.selection_id = None

    def draw_label(self):
        """Dibuja la etiqueta del empalme (vacío - empalmes no tienen etiqueta)."""
        pass  # Empalmes no muestran etiqueta

    def clear_label(self):
        """Limpia la etiqueta del empalme (vacío)."""
        pass  # Empalmes no tienen etiqueta que limpiar

    def to_dict(self):
        """
        Convierte el empalme a diccionario para guardado.
        
        Returns:
            dict: Datos del empalme
        """
        return {
            "type": "junction",  # Identificador especial
            "svg_file": None,  # Compatibilidad con código de carga
            "svg_path": None,  # Compatibilidad con código de carga
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "size": self.size,
            "original_size": self.original_size,
            "rotation": self.rotation,
            "category": self.category,
            "conn_points": serialize_connection_points(self.conn_points),
            "label_data": self.label_data
        }

    @classmethod
    def from_dict(cls, canvas, data, config=None):
        """
        Crea un empalme desde diccionario.
        
        Args:
            canvas: Canvas de tkinter
            data: Diccionario con datos del empalme
            config: Configuración de la aplicación
            
        Returns:
            JunctionComponent: Empalme recreado
        """
        junction = cls(
            canvas=canvas,
            name=data.get("name", "J1"),
            x=data.get("x", 0),
            y=data.get("y", 0),
            config=config
        )

        # Restaurar propiedades
        junction.rotation = data.get("rotation", 0)
        junction.label_data = data.get("label_data", junction.label_data)

        # Restaurar estado de puntos de conexión si existe
        if "conn_points" in data:
            for i, point_data in enumerate(data["conn_points"]):
                if i < len(junction.conn_points):
                    junction.conn_points[i].connected = point_data.get("connected", False)

        return junction

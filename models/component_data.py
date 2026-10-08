"""
Modelo de datos para componentes eléctricos.

Este módulo contiene la representación de datos puros de un componente,
separada de la lógica de renderizado y UI.
"""

from .connection_point import serialize_connection_points, parse_connection_points

class ComponentData:
    """
    Representa los datos fundamentales de un componente eléctrico.

    Esta clase contiene únicamente los datos del componente sin lógica de UI.
    El renderizado y la interacción con el canvas se manejan en otras clases.

    Attributes:
        svg_file (str): Nombre del archivo SVG
        name (str): Nombre del componente
        original_size (list): Tamaño original [width, height]
        size (list): Tamaño actual [width, height]
        x (float): Coordenada X del componente
        y (float): Coordenada Y del componente
        rotation (int): Rotación en grados
        conn_points (list): Lista de puntos de conexión (ConnectionPoint)
        selected (bool): Estado de selección
        category (str): Categoría del componente
        config (dict): Configuración del componente
        svg_path (str): Ruta al archivo SVG
        component_type (str): Tipo especial de componente
        label_data (dict): Datos de etiquetado del componente
    """

    def __init__(self, svg_file, name, size, x, y, svg_path, category, config):
        """
        Inicializa los datos del componente.

        Args:
            svg_file (str): Nombre del archivo SVG
            name (str): Nombre del componente
            size (list): Tamaño [width, height]
            x (float): Coordenada X
            y (float): Coordenada Y
            svg_path (str): Ruta al archivo SVG
            category (str): Categoría del componente
            config (dict): Configuración del componente
        """
        self.svg_file = svg_file
        self.name = name
        self.original_size = [size[0], size[1]]
        self.size = [size[0], size[1]]
        self.x = x
        self.y = y
        self.rotation = 0
        self.flipped_h = False  # Reflejo horizontal
        self.conn_points = []
        self.selected = False
        self.category = category
        self.config = config
        self.svg_path = svg_path

        # Detectar tipo de componente especial
        self.component_type = self._detect_special_component_type()

        # Sistema de etiquetas
        self.label_data = {
            'name': self._suggest_component_name(category),
            'marca': '',
            'voltaje': '',
            'potencia': '',
            'amperios': '',
            'description': '',
            'show_details': False,
            'ssf_start_time': '10',
            'ssf_stop_time': '10',
            'ssf_init_volt_pct': '30',
            'ssf_rated_volt': '220',
            'vdf_motor_rpm': '1500',
            'vdf_speed_1': '500',
            'vdf_speed_2': '1000',
            'vdf_speed_3': '1500',
            'vdf_max_freq': '60',
            'vdf_min_freq': '0',
            'vdf_accel_ramp': '5',
            'vdf_decel_ramp': '5',
            'vdf_analog_control': '3-wire',
            'vdf_analog_enabled': False
        }

    def _detect_special_component_type(self):
        """Detecta si es un componente de conexión especial"""
        if not self.svg_file:
            return "normal"

        svg_name = self.svg_file.lower()

        # Mapeo de archivos SVG a tipos de componentes
        svg_type_mapping = {
            "fase.svg": "fase",
            "conxn.svg": "conxn",
            "conxn2.svg": "conxn2",
            "t.svg": "tierra"
        }

        if "borner" in svg_name:
            return "borner"

        return svg_type_mapping.get(svg_name, "normal")

    def _suggest_component_name(self, category):
        """Sugiere un nombre basado en la categoría y componentes especiales"""
        # OPTIMIZACIÓN O(1): Diccionario de retorno en lugar de elif chain O(3)
        special_component_names = {
            "fase": "L1",  # Valor predeterminado para fase.svg
            "tierra": "",  # Sin etiqueta para T.svg
            "conxn": "L1",  # Valor predeterminado para conexiones
            "conxn2": "L1",  # Valor predeterminado para conexiones
            "borner": "X1"   # Valor predeterminado para borneras
        }

        # Lookup directo sin elif chain
        component_name = special_component_names.get(self.component_type)
        if component_name is not None:
            return component_name

        # Componentes normales
        prefixes = {
            'Motors': 'M',
            'Contactors': 'KM',
            'Coils': 'K',
            'Breakers': 'Q',
            'Thermal': 'F',
            'Switches': 'S',
            'Lights': 'H',
            'Connection': 'X'
        }

        prefix = prefixes.get(category, 'C')  # 'C' por defecto
        return f"{prefix}1"  # Número inicial, se puede actualizar después

    def resize(self, new_width, new_height):
        """
        Cambia el tamaño del componente.

        Args:
            new_width (float): Nuevo ancho
            new_height (float): Nueva altura
        """
        self.size = [new_width, new_height]

    def rotate(self, degrees):
        """
        Rota el componente.

        Args:
            degrees (int): Grados de rotación (0, 90, 180, 270)
        """
        self.rotation = degrees % 360

    def to_dict(self):
        """
        Convierte el componente a diccionario para serialización.

        Returns:
            dict: Representación en diccionario del componente
        """
        return {
            'svg_file': self.svg_file,
            'name': self.name,
            'size': self.size.copy(),
            'original_size': self.original_size.copy(),
            'x': self.x,
            'y': self.y,
            'rotation': self.rotation,
            'flipped_h': self.flipped_h,
            'selected': self.selected,
            'category': self.category,
            'config': self.config.copy() if self.config else {},
            'svg_path': self.svg_path,
            'component_type': self.component_type,
            'label_data': self.label_data.copy(),
            'conn_points': serialize_connection_points(self.conn_points)
        }

    @classmethod
    def from_dict(cls, data):
        """
        Crea un componente desde un diccionario.

        Args:
            data (dict): Datos del componente

        Returns:
            ComponentData: Nueva instancia del componente
        """
        component = cls(
            data['svg_file'],
            data['name'],
            data['size'],
            data['x'],
            data['y'],
            data['svg_path'],
            data['category'],
            data['config']
        )

        # Restaurar propiedades adicionales
        component.original_size = data.get('original_size', data['size']).copy()
        component.rotation = data.get('rotation', 0)
        component.flipped_h = data.get('flipped_h', False)  # Compatibilidad con archivos antiguos
        component.selected = data.get('selected', False)
        component.component_type = data.get('component_type', component.component_type)
        component.label_data.update(data.get('label_data', {}))

        # Restaurar puntos de conexión
        component.conn_points = parse_connection_points(data.get('conn_points', []))

        return component

    def __repr__(self):
        """Representación en string del componente"""
        return f"ComponentData(name='{self.name}', type='{self.component_type}', x={self.x}, y={self.y})"

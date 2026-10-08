class ConnectionPoint:
    """
    Representa un punto de conexión en un componente eléctrico.

    Attributes:
        x (float): Coordenada X del punto de conexión
        y (float): Coordenada Y del punto de conexión
        radius (float): Radio del punto de conexión (por defecto 0.5)
        connected (bool): Indica si el punto está conectado a otro componente
        orientation (str): Orientación del punto ('N', 'S', 'E', 'O')
    """

    def __init__(self, x, y, radius=0.5, orientation='N'):
        """
        Inicializa un punto de conexión.

        Args:
            x (float): Coordenada X
            y (float): Coordenada Y
            radius (float): Radio del punto (por defecto 0.5)
            orientation (str): Orientación del punto ('N', 'S', 'E', 'O')
        """
        self.x = x
        self.y = y
        self.radius = radius
        self.connected = False
        self.orientation = orientation  # N, S, E, O (Norte, Sur, Este, Oeste)

    def __repr__(self):
        """Representación en string del punto de conexión"""
        return f"ConnectionPoint(x={self.x}, y={self.y}, connected={self.connected}, orientation='{self.orientation}')"

def serialize_connection_points(points):
    """
    Serializa una lista de ConnectionPoint al formato compartido guardado en .ecad.
    Fuente única para Component, ComponentData y JunctionComponent.
    """
    return [
        {
            "x": p.x,
            "y": p.y,
            "radius": getattr(p, 'radius', 0.5),
            "orientation": getattr(p, 'orientation', 'N'),
            "connected": getattr(p, 'connected', False)
        }
        for p in points
    ]

def parse_connection_points(data):
    """
    Reconstruye una lista de ConnectionPoint desde el formato compartido .ecad.

    Args:
        data: Lista de dicts serializados por serialize_connection_points.

    Returns:
        list: Lista de ConnectionPoint (entradas inválidas se omiten).
    """
    points = []
    for p in data:
        try:
            cp = ConnectionPoint(
                p.get("x", 0),
                p.get("y", 0),
                p.get("radius", 0.5),
                p.get("orientation", 'N')
            )
            cp.connected = p.get("connected", False)
            points.append(cp)
        except Exception:
            continue
    return points

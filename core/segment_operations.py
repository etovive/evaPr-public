from utils.utility_functions import distance_point_to_segment

class SegmentOperations:
    """
    Clase que contiene todas las operaciones de segmentos copiadas exactamente
    del sistema actual para preservar funcionalidad completa
    """

    def __init__(self, app):
        self.app = app
        self.canvas = app.canvas

    def find_line_at_position(self, x, y, tolerance=5):
        """
        Encontrar línea en posición específica.
        COPIADO EXACTAMENTE del sistema actual.

        Args:
            x, y: Posición a buscar
            tolerance: Tolerancia para detección

        Returns:
            tuple: (connection, segment_idx) o None si no se encuentra
        """
        try:
            best_connection = None
            best_segment_idx = None
            min_distance = float('inf')

            for connection in getattr(self.app, 'connections', []):
                if not hasattr(connection, 'line_ids') or not connection.line_ids:
                    continue

                for segment_idx, line_id in enumerate(connection.line_ids):
                    coords = self.canvas.coords(line_id)

                    if len(coords) >= 4:
                        x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]

                        # Distancia punto a segmento (lógica compartida con distance_point_to_segment)
                        dist = distance_point_to_segment(x, y, x1, y1, x2, y2)
                        if dist <= tolerance and dist < min_distance:
                            min_distance = dist
                            best_connection = connection
                            best_segment_idx = segment_idx

            if best_connection:
                return (best_connection, best_segment_idx)

            return None

        except Exception as e:
            return None

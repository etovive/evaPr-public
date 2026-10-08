from config.settings import AppConstants

class EventUtils:
    """Utilidades para el manejo de eventos y cálculos geométricos."""

    @staticmethod
    def should_ignore_line(canvas, line_id, ignore_colors=None):
        """
        Verifica si una línea debe ser ignorada para aplicación de estilos.

        Args:
            canvas: Canvas de Tkinter
            line_id: ID de la línea en el canvas
            ignore_colors: Lista de colores a ignorar

        Returns:
            bool: True si la línea debe ser ignorada
        """
        if ignore_colors is None:
            ignore_colors = [AppConstants.COLORS['SELECTED'], AppConstants.COLORS['HIGHLIGHTED']]

        try:
            current_color = canvas.itemcget(line_id, "fill")
            return current_color in ignore_colors
        except:
            return True  # Error, mejor ignorar

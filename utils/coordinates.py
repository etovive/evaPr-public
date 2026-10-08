
from config.settings import AppConstants  # noqa: F401  re-export: core/pdf_exporter.py lo importa desde aquí

def event_to_canvas_coords(event, canvas, canvas_width=None, canvas_height=None):
    """
    Convierte coordenadas de evento (pantalla) a coordenadas del canvas (mundo).
    """
    # 1. Obtener coordenada en el sistema actual del canvas (escalado)
    canvas_x = canvas.canvasx(event.x)
    canvas_y = canvas.canvasy(event.y)

    # 2. Desescalar por zoom para obtener coordenadas del mundo real
    zoom = getattr(canvas, 'zoom_level', 1.0)
    x_world = canvas_x / zoom
    y_world = canvas_y / zoom

    return x_world, y_world

def world_to_canvas_coords(world_x, world_y, canvas):
    """
    Convierte coordenadas del mundo a coordenadas del canvas (incluye zoom, no scroll).
    Ideal para dibujar elementos persistentes en el canvas.
    """
    zoom = getattr(canvas, 'zoom_level', 1.0)
    return world_x * zoom, world_y * zoom

def get_pan_offset(canvas, canvas_width=None, canvas_height=None):
    """
    Obtiene el offset de pan (scroll) actual del canvas.
    """
    pan_offset_x = canvas.canvasx(0)
    pan_offset_y = canvas.canvasy(0)

    return pan_offset_x, pan_offset_y

# HELPERS DE DIBUJADO CENTRALIZADO (WORLD COORDINATES)

def draw_world_line(canvas, x1, y1, x2, y2, **kwargs):
    """
    Dibuja una línea usando coordenadas del mundo.
    """
    sx1, sy1 = world_to_canvas_coords(x1, y1, canvas)
    sx2, sy2 = world_to_canvas_coords(x2, y2, canvas)
    return canvas.create_line(sx1, sy1, sx2, sy2, **kwargs)

def draw_world_oval(canvas, x1, y1, x2, y2, **kwargs):
    """
    Dibuja un óvalo/círculo usando coordenadas del mundo.
    """
    sx1, sy1 = world_to_canvas_coords(x1, y1, canvas)
    sx2, sy2 = world_to_canvas_coords(x2, y2, canvas)
    return canvas.create_oval(sx1, sy1, sx2, sy2, **kwargs)

def draw_world_rectangle(canvas, x1, y1, x2, y2, **kwargs):
    """
    Dibuja un rectángulo usando coordenadas del mundo.
    """
    sx1, sy1 = world_to_canvas_coords(x1, y1, canvas)
    sx2, sy2 = world_to_canvas_coords(x2, y2, canvas)
    return canvas.create_rectangle(sx1, sy1, sx2, sy2, **kwargs)

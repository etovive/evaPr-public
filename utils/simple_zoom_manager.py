#!/usr/bin/env python3
class SimpleZoomManager:
    """Gestor de zoom minimalista y optimizado."""

    MIN_ZOOM = 0.5
    MAX_ZOOM = 2.0
    ZOOM_FACTOR = 1.05
    REDRAW_DELAY_MS = 50

    def __init__(self, app):
        self.app = app
        self.canvas = app.canvas
        self._redraw_after_id = None
        if not hasattr(self.canvas, 'zoom_level'):
            self.canvas.zoom_level = 1.0

    def _schedule_redraw(self):
        """Programa el redibujado completo con debounce.

        Si llegan varios notches de zoom seguidos, se cancela el redibujado
        pendiente y se programa uno nuevo, de modo que solo se redibuja al
        estabilizarse el zoom (evita redibujar todo el canvas por cada notch).
        """
        if self._redraw_after_id is not None:
            try:
                self.canvas.after_cancel(self._redraw_after_id)
            except Exception:
                pass
            self._redraw_after_id = None
        try:
            self._redraw_after_id = self.canvas.after(self.REDRAW_DELAY_MS, self._redraw)
        except Exception:
            self._redraw()

    def zoom_in(self, event=None):
        """Aumenta zoom 10% (máximo 3.0x)"""
        if self.canvas.zoom_level < self.MAX_ZOOM:
            self.canvas.zoom_level = min(self.canvas.zoom_level * self.ZOOM_FACTOR, self.MAX_ZOOM)
            self._schedule_redraw()

    def zoom_out(self, event=None):
        """Disminuye zoom 10% (mínimo 0.3x)"""
        if self.canvas.zoom_level > self.MIN_ZOOM:
            self.canvas.zoom_level = max(self.canvas.zoom_level / self.ZOOM_FACTOR, self.MIN_ZOOM)
            self._schedule_redraw()

    def reset_zoom(self, event=None):
        """Resetea zoom a 100%"""
        self.canvas.zoom_level = 1.0
        self._schedule_redraw()

    def _redraw(self):
        """Redibuja elementos escalados por zoom_level"""
        # Escalado por zoom_level - DEBE aplicarse para que funcione
        zoom_level = self.canvas.zoom_level

        # SINCRONIZAR: Asegurar que scale_factor esté sincronizado con zoom_level
        if not hasattr(self.canvas, 'scale_factor'):
            self.canvas.scale_factor = zoom_level
        else:
            self.canvas.scale_factor = zoom_level  # Siempre actualizar con zoom actual

                    # ZOOM: zoom_level={zoom_level:.2f}, scale_factor={self.canvas.scale_factor:.2f}")

        # NO redibujar el grid por zoom: el grid es fijo hasta que el usuario lo solicite

        for comp in getattr(self.app, 'components', []):
            if hasattr(comp, 'draw'):
                comp.draw()

        for text_comp in getattr(self.app, 'text_components', []):
            if hasattr(text_comp, 'draw'):
                text_comp.draw()

        # Redibujar imágenes escaladas
        for img_comp in getattr(self.app, 'image_components', []):
            if hasattr(img_comp, 'draw'):
                img_comp.draw()

        # Redibujar formas para que respondan al zoom (las shapes usan world->screen)
        try:
            if hasattr(self.app, 'redraw_all_shapes'):
                self.app.redraw_all_shapes()
            elif hasattr(self.app, 'shape_manager'):
                self.app.shape_manager.draw_all(self.canvas)
        except Exception:
            pass

        # Las líneas manuales tienen su forma predefinida y no deben alterarse
        if hasattr(self.app, 'connections'):
            for connection in self.app.connections:
                if hasattr(self.app, 'update_manhattan_line'):
                    self.app.update_manhattan_line(connection)

                    # Zoom aplicado {zoom_level:.2f}x")

        # Esto asegura que la línea de preview se redibuje correctamente con el nuevo zoom
        if hasattr(self.app, 'event_handler') and hasattr(self.app, 'mouse_x'):
             if hasattr(self.app, 'unified_line_system') and self.app.unified_line_system.manual_active:
                 try:
                     self.app.event_handler._handle_manual_routing_preview(self.app.mouse_x, self.app.mouse_y)
                 except Exception:
                     pass

        if hasattr(self.app, 'update_info_bar'):
            self.app.update_info_bar()

        if hasattr(self.app, 'update_cross_references'):
            self.app.update_cross_references()

        if hasattr(self.app, 'update_wire_numbers'):
            self.app.update_wire_numbers()

    def get_zoom_percentage(self):
        """Retorna zoom como porcentaje"""
        return int(self.canvas.zoom_level * 100)

# Función factory simplificada
def create_simple_zoom_manager(app):
    """Crea instancia del zoom manager"""
    return SimpleZoomManager(app)

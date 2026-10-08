# Utils module for eduCAd
"""
Módulo de utilidades para la aplicación eduCAd.

Este módulo contiene clases y funciones de utilidad compartidas
entre diferentes partes de la aplicación.
"""

# Importaciones disponibles desde este módulo
try:
    from .simple_zoom_manager import SimpleZoomManager, create_simple_zoom_manager
    __all__ = ['SimpleZoomManager', 'create_simple_zoom_manager']
except ImportError:
    # Si el módulo no está disponible, continuar sin él
    __all__ = []

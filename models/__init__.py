"""
Módulo de modelos de datos para eduCAd

Este módulo contiene las clases de modelo que representan los datos
fundamentales de la aplicación sin lógica de presentación.
"""

from .connection_point import ConnectionPoint
from .connection import Connection
from .component_data import ComponentData


__all__ = ['ConnectionPoint', 'Connection', 'ComponentData']

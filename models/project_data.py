from typing import List, Dict, Any, Optional

class Sheet:
    """Representa una hoja de trabajo individual (lienzo)."""
    def __init__(self, name: str):
        self.name = name
        self.elements: List[Any] = []  # Líneas, formas, componentes
        self.connections: List[Any] = [] # Conexiones
        self.zoom_level: float = 1.0
        self.pan_offset: tuple = (0, 0)
        self.editable: bool = True  # Por defecto, las hojas son editables

    def to_dict(self) -> Dict[str, Any]:
        """Serializa la hoja a un diccionario."""
        return {
            "name": self.name,
            "zoom_level": self.zoom_level,
            "pan_offset": self.pan_offset,
            "editable": self.editable,
            # Los elementos y conexiones se serializarán externamente o aquí si se mueven los métodos
            # Por ahora mantenemos la estructura simple
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Sheet':
        """Crea una hoja desde un diccionario."""
        sheet = cls(data["name"])
        sheet.zoom_level = data.get("zoom_level", 1.0)
        sheet.pan_offset = tuple(data.get("pan_offset", (0, 0)))
        sheet.editable = data.get("editable", True)
        return sheet

class Project:
    """Representa el proyecto completo con múltiples hojas."""
    def __init__(self, name: str = "Proyecto Sin Título"):
        self.name = name
        self.sheets: List[Sheet] = []
        self.active_sheet_index: int = 0
        self.selected_cabinet: Optional[List[int]] = None  # [width, height, depth]

        # Crear hoja por defecto si no hay ninguna
        if not self.sheets:
            self.add_sheet("Hoja 1")

    def add_sheet(self, name: str) -> Sheet:
        """Agrega una nueva hoja al proyecto."""
        new_sheet = Sheet(name)
        self.sheets.append(new_sheet)
        return new_sheet

    def remove_sheet(self, index: int) -> bool:
        """Elimina una hoja por índice. Retorna True si se eliminó."""
        if 0 <= index < len(self.sheets) and len(self.sheets) > 1:
            self.sheets.pop(index)
            # Ajustar índice activo si la hoja eliminada estaba antes que la activa
            if index < self.active_sheet_index:
                self.active_sheet_index -= 1

            # Asegurar que el índice no se salga de los límites (ej: si eliminamos la última)
            if self.active_sheet_index >= len(self.sheets):
                self.active_sheet_index = len(self.sheets) - 1
            return True
        return False

    def get_active_sheet(self) -> Optional[Sheet]:
        """Retorna la hoja activa actual."""
        if 0 <= self.active_sheet_index < len(self.sheets):
            return self.sheets[self.active_sheet_index]
        return None

    def set_active_sheet(self, index: int) -> bool:
        """Cambia la hoja activa."""
        if 0 <= index < len(self.sheets):
            self.active_sheet_index = index
            return True
        return False

    def move_sheet(self, index: int, direction: int) -> bool:
        """
        Mueve una hoja hacia arriba (-1) o abajo (+1).
        Retorna True si el movimiento fue exitoso.
        """
        new_index = index + direction
        if 0 <= new_index < len(self.sheets):
            # Intercambiar
            self.sheets[index], self.sheets[new_index] = self.sheets[new_index], self.sheets[index]

            # Ajustar índice activo si es necesario
            if self.active_sheet_index == index:
                self.active_sheet_index = new_index
            elif self.active_sheet_index == new_index:
                self.active_sheet_index = index

            return True
        return False

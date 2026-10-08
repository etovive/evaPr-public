class UndoManager:
    def __init__(self, max_depth=15):
        self.undo_stack = []
        self.redo_stack = []
        self.max_depth = max_depth

    def save_state(self, state):
        """Guarda un nuevo estado y limpia la pila de rehacer (Redo)."""
        # Si el nuevo estado es idéntico al último, no duplicar para ahorrar memoria
        if self.undo_stack and self.undo_stack[-1] == state:
            return

        self.undo_stack.append(state)
        self.redo_stack.clear()

        # Limitar profundidad a 15 estados según petición de ligereza
        if len(self.undo_stack) > self.max_depth:
            self.undo_stack.pop(0)

    def undo(self, current_state):
        """Retorna el estado anterior."""
        if not self.undo_stack:
            return None

        # Al deshacer, guardamos el estado actual en la pila de rehacer
        self.redo_stack.append(current_state)
        return self.undo_stack.pop()

    def redo(self, current_state):
        """Retorna el estado que fue deshecho."""
        if not self.redo_stack:
            return None

        # Al rehacer, guardamos el estado actual en la pila de deshacer
        self.undo_stack.append(current_state)
        return self.redo_stack.pop()

    def clear(self):
        """Limpia todo el historial."""
        self.undo_stack.clear()
        self.redo_stack.clear()

import re

class ComponentBehaviorManager:
    """
    Gestiona el comportamiento activo de los componentes.
    Su principal función es activar contactos cuando sus bobinas asociadas
    (mismo nombre) están energizadas.
    """

    def __init__(self, app):
        self.app = app

    # Se construyen una vez por llamada a update_behaviors y se descartan.
    # NO se guardan en self.app porque estos datos son válidos solo
    # mientras la lista de componentes no cambie.
    # La limpieza entre simulaciones la hace SimulationController.

    def _build_tick_caches(self, components):
        """
        Construye tres cachés válidos para el tick actual:
          - _load_cache:  { id(comp): bool }   — resultado de _is_potential_load
          - _label_cache: { id(comp): str }    — resultado de _get_label
          - load_names:   { nombre }           — nombres que tienen carga/relé térmico
        Permite que _coil_exists_in_project consulte un set O(1) en lugar de
        reescanear la lista entera de componentes por cada nombre distinto.
        """
        load_cache  = {}
        label_cache = {}
        load_names  = set()
        for comp in components:
            lbl = self._get_label(comp)
            label_cache[id(comp)] = lbl
            is_load = self._is_potential_load(comp)
            load_cache[id(comp)] = is_load
            if is_load:
                if lbl:
                    load_names.add(lbl)
            elif 'thermal-overload' in (getattr(comp, 'svg_file', '') or '').lower():
                if lbl:
                    load_names.add(lbl)
        return load_cache, label_cache, load_names

    def update_behaviors(self, network_state):
        """
        Actualiza el estado (is_active) de los componentes basado en la energía.
        """
        components = self.app.components

        # Construir cachés del tick una sola vez
        load_cache, label_cache, load_names = self._build_tick_caches(components)

        # 1. Identificar Cargas Energizadas (Bobinas, Lámparas, etc.)
        active_control_names = set()

        if hasattr(self.app, 'simulation_controller'):
            active_control_names.update(
                self.app.simulation_controller.get_all_active_signals()
            )

        for comp in components:
            if not load_cache[id(comp)]:
                continue

            if self._is_device_energized(comp, network_state):
                if not getattr(comp, 'is_active', False):
                    comp.is_active = True
                    self._refresh_component(comp)
                name = label_cache[id(comp)]
                if name:
                    active_control_names.add(name)
            else:
                if getattr(comp, 'is_active', True):
                    comp.is_active = False
                    self._refresh_component(comp)

        # 1.5 Registrar thermal-overload activos manualmente
        for comp in components:
            svg_file = getattr(comp, 'svg_file', '') or ''
            if 'thermal-overload' in svg_file.lower():
                if getattr(comp, 'is_active', False):
                    name = label_cache[id(comp)]
                    if name:
                        active_control_names.add(name)

        # 2. Actualizar Contactos/Esclavos Enlazados
        for comp in components:
            if load_cache[id(comp)]:
                continue

            fname = (getattr(comp, 'svg_file', '') or '').lower()
            if "sst-e" in fname or "vdf-e" in fname:
                continue

            name = label_cache[id(comp)]
            if not name:
                continue

            if name in active_control_names:
                if not getattr(comp, 'is_active', False):
                    comp.is_active = True
                    self._refresh_component(comp)

            elif name in load_names:
                if getattr(comp, 'is_active', True):
                    comp.is_active = False
                    self._refresh_component(comp)

    # Método original conservado para compatibilidad con código externo

    def _is_potential_load(self, comp):
        """
        Determina si un componente es una Carga (Bobina, Lámpara, Piloto).
        """
        # 0. Exclusión explícita: interruptores y disyuntores no son cargas
        if hasattr(comp, 'svg_file') and comp.svg_file:
            fname = comp.svg_file.lower()
            not_loads = [
                'contact', 'switch', 'breaker', 'disyuntor',
                'seccionador', 'pulsador', 'button', 'trip',
                'power', 'thermal-overload'
            ]
            if any(nl in fname for nl in not_loads):
                return False

        # 1. Por archivo SVG (prioridad alta)
        if hasattr(comp, 'svg_file') and comp.svg_file:
            fname = comp.svg_file.lower()
            keywords = ['coil', 'bobina', 'lamp', 'light', 'pilot', 'led',
                        'solenoid', 'timbre', 'buzzer']
            if any(k in fname for k in keywords):
                return True

        if hasattr(comp, 'category') and comp.category:
            cat = comp.category.lower()
            if 'coil' in cat or 'light' in cat or 'pilot' in cat or 'bobina' in cat:
                return True

        # 3. Por nombre (estándar IEC)
        name = self._get_label(comp)
        if name:
            prefix = re.match(r'^[A-Z]+', name)
            if prefix and prefix.group(0) in ('K', 'H', 'Y', 'E'):
                return True

        return False

    def _is_device_energized(self, comp, network_state):
        """Verifica si hay diferencia de potencial entre terminales (A1-A2, X1-X2, etc)."""
        if not hasattr(comp, 'conn_points') or len(comp.conn_points) < 2:
            return False

        pots1 = network_state.get((id(comp), 0), set())
        pots2 = network_state.get((id(comp), 1), set())

        if not pots1 or not pots2:
            return False

        return not pots1.intersection(pots2)

    def _refresh_component(self, comp):
        """Recarga la imagen del componente para reflejar cambios visuales."""
        if hasattr(comp, 'load_image') and hasattr(comp, 'svg_path'):
            comp.load_image(comp.svg_path)
            if hasattr(comp, 'draw'):
                if hasattr(self.app, '_visible_components_only'):
                    if id(comp) in self.app._visible_components_only:
                        comp.draw()
                else:
                    comp.draw()

    def _get_label(self, comp):
        """Obtiene la etiqueta (nombre) del componente."""
        if hasattr(comp, 'label_data') and comp.label_data:
            return comp.label_data.get('name', '').strip().upper()
        return comp.name.strip().upper()

    def scan_current_page_signals(self, components, network_state):
        """
        Escanea la página actual y retorna un diccionario con el estado
        de todas las posibles fuentes de señal (bobinas, etc).
        Usado para actualizar el estado global al cambiar de página.

        Returns:
            dict: { "K1": True, "H1": False,... }
        """
        signals = {}
        for comp in components:
            if self._is_potential_load(comp):
                name = self._get_label(comp)
                if name:
                    signals[name] = self._is_device_energized(comp, network_state)
        return signals

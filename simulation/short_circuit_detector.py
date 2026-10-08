"""
Detector de Cortocircuitos.
Analiza el estado de la red para identificar nodos con potenciales conflictivos.
"""

class ShortCircuitDetector:
    def __init__(self, app):
        self.app = app

    # IDENTIFICACIÓN DEL COMPONENTE Y LA HOJA

    def _get_component(self, comp_id):
        """
        Localiza el objeto Component a partir de su id().
        Durante el tick de simulación self.app.components ya contiene TODAS las hojas,
        así que ese es el camino rápido; si no está, se recorre el proyecto completo.
        """
        sources = [self.app.components]
        if hasattr(self.app, 'get_all_project_components'):
            sources.append(self.app.get_all_project_components())

        seen = set()
        for source in sources:
            for comp in source:
                if id(comp) in seen:
                    continue
                seen.add(id(comp))
                if id(comp) == comp_id:
                    return comp
        return None

    def _get_designator(self, comp):
        """
        Devuelve el designador del componente (K1, M1, L1, QF2...).
        Es la etiqueta que el usuario asignó en el cajetín, no el nombre del catálogo
        ("Motor 3P+PE"), porque varios componentes del mismo tipo existirían con el
        mismo texto y sería imposible saber cuál falló.
        """
        if comp is None:
            return "DESCONOCIDO"
        if hasattr(comp, 'label_data') and comp.label_data:
            name = str(comp.label_data.get('name', '')).strip().upper()
            if name:
                return name
        return str(getattr(comp, 'name', '') or 'DESCONOCIDO').strip().upper() or "DESCONOCIDO"

    def _get_sheet_name(self, comp):
        """Nombre de la hoja donde vive el componente."""
        if comp is None or not hasattr(self.app, 'get_component_sheet_name'):
            return "Hoja ?"
        return self.app.get_component_sheet_name(comp)

    def _build_conflict(self, key, comp, title, detail):
        """
        Construye el diccionario de conflicto con toda la información de ubicación.
        title: encabezado con emoji (ej. " CORTOCIRCUITO")
        detail: descripción de los potenciales en conflicto
        """
        sheet = self._get_sheet_name(comp)
        designator = self._get_designator(comp)
        tipo = str(getattr(comp, 'name', '') or '').strip() or 'DESCONOCIDO'
        etiqueta = designator if tipo.upper() == designator.upper() else f"{designator} ({tipo})"
        return {
            'msg': f'{title} — Hoja "{sheet}" | {etiqueta} | {detail}',
            'key': key,
            'title': title,
            'detail': detail,
            'sheet': sheet,
            'designator': designator,
            'component_name': tipo,
        }

    # DETECCIÓN

    def detect(self, network_state):
        """
        Escanea el estado de la red buscando conflictos.

        Args:
            network_state: Dict {(id_comp, idx_term): {potenciales}}

        Returns:
            list: Lista de conflictos encontrados
                  [{'msg': str, 'key': (comp_id, idx), 'sheet': str, 'designator': str,...}]
        """
        conflicts = []

        # Iterar sobre todos los nodos energizados
        for key, potentials in network_state.items():
            if len(potentials) < 2:
                continue

            comp_id, term_idx = key
            comp = self._get_component(comp_id)

            # Analizar potenciales presentes
            phases = {p for p in potentials if p in ['L1', 'L2', 'L3']}
            has_neutral = 'N' in potentials
            has_ground = 'PE' in potentials

            # POTENCIALES DC (Reconocimiento flexible)
            dc_positives = {p for p in potentials if any(x in p.upper() for x in ['+', '24V', '24VDC', 'VCC', 'V+', 'POS'])}
            dc_negatives = {p for p in potentials if any(x in p.upper() for x in ['-', 'GND', '0V', '0VDC', 'V-', 'NEG'])}

            # 1. Corto entre Fases (L1-L2, etc.)
            if len(phases) > 1:
                conflicts.append(self._build_conflict(
                    key, comp, "💥 CORTOCIRCUITO", f"FASES {', '.join(sorted(phases))}"))
                continue

            # 2. Corto Fase-Neutro
            if phases and has_neutral:
                conflicts.append(self._build_conflict(
                    key, comp, "💥 CORTOCIRCUITO", f"{sorted(phases)[0]} - N"))
                continue

            # 3. Corto DC (+ vs -)
            if dc_positives and dc_negatives:
                conflicts.append(self._build_conflict(
                    key, comp, "💥 CORTOCIRCUITO DC",
                    f"{sorted(dc_positives)[0]} - {sorted(dc_negatives)[0]}"))
                continue

            # 4. Mezcla AC y DC (Peligro de daño en equipo electrónico)
            if phases and (dc_positives or dc_negatives):
                conflicts.append(self._build_conflict(
                    key, comp, "💥 CONFLICTO AC/DC", "FASE - DC"))
                continue

            # 5. Corto Fase-Tierra (Fuga Franca)
            if phases and has_ground:
                conflicts.append(self._build_conflict(
                    key, comp, "⚡ DERIVACIÓN A TIERRA", f"{sorted(phases)[0]} - PE"))
                continue

        return conflicts

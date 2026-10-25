import os
import math
import re
import atexit
import hashlib
import tempfile
from collections import defaultdict
from models.component import TextComponent
from models.shape import Rect, Circle, parse_seccion_canaleta
from utils.utils import load_medidas_config, get_engineering_size
from utils.utility_functions import sort_bom_entries, sort_bom_references
from config.disclaimer import DISCLAIMER_FOOTER
from config.settings import AppConstants

_TEMP_RENDER_PATHS = []

def _cleanup_temp_renders():
    for path in _TEMP_RENDER_PATHS:
        try:
            os.remove(path)
        except OSError:
            pass
    _TEMP_RENDER_PATHS.clear()

atexit.register(_cleanup_temp_renders)

def normalize_borner_svg(svg_file):
    """Normaliza variantes del mismo borner.

    ``borner-3-clavija.svg`` es la misma bornera de 3 polos con otro tipo de
    conexión, así que se trata como ``borner-3.svg`` para no confundir la
    detección de polos, la BOM, el unifilar ni el plano de bornes.
    """
    return re.sub(r'-clavija\b', '', str(svg_file or ''), flags=re.IGNORECASE)

def _save_render_png(png_bytes):
    """Escribe un PNG renderizado y devuelve su ruta.

    El nombre del archivo se deriva del contenido, así que regenerar el mismo
    símbolo sobrescribe el archivo en vez de crear otro. Evita el crecimiento
    sin límite de /tmp que dejaba mkstemp(delete=False) al abrir y cerrar la
    aplicación repetidamente.
    """
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "evaPr", "render")
    try:
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(
            cache_dir, hashlib.sha1(png_bytes).hexdigest()[:16] + ".png"
        )
        if not os.path.exists(path):
            with open(path, "wb") as fh:
                fh.write(png_bytes)
        return path
    except OSError:
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        with open(path, "wb") as fh:
            fh.write(png_bytes)
        _TEMP_RENDER_PATHS.append(path)
        return path

class BOMGenerator:
    """Generador de Lista de Materiales (Bill of Materials)"""

    # Hojas derivadas/no editables (2D, unifilar, Lista de Materiales, Plano de
    # Borner, Resumen de Gabinete, Tabla de Cableado, ...). Se reutiliza la lista
    # central para no mantener copias desincronizadas. Los unifilares se filtran
    # además por nombre (ver _collect_components_from_project).
    EXCLUDED_SHEETS = list(AppConstants.CROSS_REF_EXCLUDED_SHEETS)

    def __init__(self, project):
        self.project = project

    def generate_bom_sheet(self, app):
        """
        Genera o actualiza la hoja de Lista de Materiales en la aplicación dada.
        'app' es la instancia de PlanoElectrico para acceso al canvas y config.
        """
        # 1. Buscar si ya existe una hoja "Lista de Materiales"
        bom_sheet = None
        bom_index = -1

        for i, sheet in enumerate(app.project.sheets):
            if sheet.name == "Lista de Materiales":
                bom_sheet = sheet
                bom_index = i
                break

        # 2. Si no existe, crearla al final
        if not bom_sheet:
            bom_sheet = app.project.add_sheet("Lista de Materiales")
            bom_index = len(app.project.sheets) - 1

        # 3. Cambiar a esa hoja para manipularla
        app.switch_to_sheet(bom_index)

        # 4. Limpiar contenido existente en la hoja
        # Nota: app.switch_to_sheet ya carga los elementos en app.canvas/app.components
        # Así que limpiamos las listas actuales de la app
        app.canvas.delete("all")
        app.components.clear()
        app.connections.clear()
        app.text_components.clear()
        if hasattr(app, 'shape_manager'):
            app.shape_manager.shapes.clear()

        # Re-dibujar grid y configuraciones básicas
        app.draw_grid(force=True)

        # 5. Recolectar datos de TODAS las hojas (excepto la propia BOM)
        all_components = self._collect_components_from_project(app.project)

        # 6. Agrupar datos
        grouped_data = self._group_data(all_components, project=app.project)

        # 6b. Agregar ítems de infraestructura del gabinete (Gabinete, Riel DIN, Canaleta)
        self._inject_infrastructure_items(app, grouped_data)

        # 7. Dibujar Tabla en el canvas
        self._draw_bom_table(app, grouped_data)

        # 8. Marcar como modificado
        app.save_undo_checkpoint()

    def _collect_components_from_project(self, project):
        """Recolecta componentes de todas las hojas excepto la BOM y unifilares.

        Una sola pasada sobre los elementos clasifica simultáneamente:
          - componentes normales
          - block terminals
          - candidatos a bobina (coil)
          - nombres cubiertos por contactor o contactos esclavos

        Una segunda micro-pasada sobre la lista de bobinas (ya en memoria)
        decide cuáles son relés en zócalo.  Esto reemplaza las 4 pasadas
        anteriores sobre project.sheets.
        """
        EXCLUDED_SHEETS = self.EXCLUDED_SHEETS
        EXCLUDED_CATEGORIES = ['connection', 'fase', 'junction', 'bus', 'labels', 'unifilar']
        EXCLUDED_SVG_FILES = ['conxn.svg', 'conxn2.svg', 'fase.svg', 'neutro.svg', 'pe.svg', 'punto-empalme.svg']

        components = []
        coil_candidates = []                    # (elem, lname) — bobinas encontradas
        names_covered = set()                   # nombres con contactor o contactos esclavos

        for sheet in project.sheets:
            # Block Terminals (Repartidor de Cargas): se guardan en la propia
            # hoja (p. ej. 'Hoja de Gabinete 2D'), por lo que deben recolectarse
            # ANTES del filtro de hojas excluidas para sí entrar en la BOM.
            for bt in getattr(sheet, 'live_block_terminals', []):
                if not isinstance(bt, dict):
                    continue
                components.append({
                    'category': 'block_terminal',
                    'svg_file': 'block_terminal',
                    'label_data': bt['label_data']
                })

            if sheet.name in EXCLUDED_SHEETS or 'unifilar' in sheet.name.lower():
                continue

            # Elementos del esquema
            for elem in sheet.elements:
                if not isinstance(elem, dict):
                    continue
                if elem.get('type') in ['connection', 'junction', 'text']:
                    continue

                category = str(elem.get('category') or '').lower()
                svg_file  = str(elem.get('svg_file')  or '').lower()
                lname     = (elem.get('label_data') or {}).get('name', '')

                if 'unifilar' in category:
                    continue

                # Clasificar para lógica de relé en zócalo (en paralelo con el resto)
                if lname:
                    if any(x in svg_file for x in ['no.svg', 'nc.svg', 'contact', 'contacto']):
                        names_covered.add(lname)
                    if 'contactor' in svg_file or 'contactor' in category:
                        names_covered.add(lname)

                # Bobinas: registrar como candidatos, no agregar aún a components
                if any(x in svg_file for x in ['coil', 'bobina']):
                    coil_candidates.append((elem, lname))
                    # Las bobinas de contactor integrado también entran en components
                    # como elemento normal (lo decide la segunda micro-pasada abajo)
                    # -> se agregan al final solo si NO son relé en zócalo o si sí lo son.
                    # Para simplificar: siempre las agregamos al final según su condición.
                    continue

                is_borner = 'borner' in svg_file
                if not is_borner:
                    if any(exc in category for exc in EXCLUDED_CATEGORIES):
                        # Permitir componentes de puerta/tapa (como buzzer, pilotos, botones)
                        is_door_comp = any(y in svg_file for y in ['pilot', 'light', 'button', 'selector', 'piloto', 'perilla', 'buzzer', 'alarma', 'sirena', 'paro', 'mushroom', 'emergency', 'seta'])
                        if not is_door_comp:
                            continue
                    if any(exc in svg_file for exc in EXCLUDED_SVG_FILES):
                        continue

                if 'svg_file' in elem or 'category' in elem:
                    components.append(elem)

        # Micro-pasada sobre bobinas (ya en memoria)
        # RELÉ EN ZÓCALO: bobina sin contactor ni contactos esclavos asociados.
        # REGLA COMERCIAL: los contactores 3P incluyen su bobina — si hay contactor
        # con el mismo nombre, la bobina NO es relé independiente.
        for elem, lname in coil_candidates:
            svg_file = str(elem.get('svg_file') or '').lower()
            is_borner = 'borner' in svg_file
            if not is_borner:
                category = str(elem.get('category') or '').lower()
                if any(exc in category for exc in EXCLUDED_CATEGORIES):
                    continue
                if any(exc in svg_file for exc in EXCLUDED_SVG_FILES):
                    continue
            if 'svg_file' in elem or 'category' in elem:
                if lname and lname not in names_covered:
                    # Es un relé en zócalo independiente
                    relay_elem = elem.copy()
                    relay_elem['_relay_socket'] = True
                    components.append(relay_elem)
                else:
                    # Bobina integrada en contactor -> incluir como componente normal
                    components.append(elem)

        return components

    def _build_contactor_aux_map(self, project):
        """Construye un mapa {nombre_contactor: {'NO': count, 'NC': count}}
        recorriendo todos los elementos del proyecto.
        Los contactos auxiliares (no.svg / nc.svg) con el mismo nombre que un
        contactor se absorben en la descripcion del contactor en la BOM."""
        EXCLUDED_SHEETS = self.EXCLUDED_SHEETS

        # 1. recopilar nombres de contactores fisicos
        contactor_names = set()
        for sheet in project.sheets:
            if sheet.name in EXCLUDED_SHEETS or 'unifilar' in sheet.name.lower():
                continue
            for elem in sheet.elements:
                if not isinstance(elem, dict):
                    continue
                svg_lower = str(elem.get('svg_file') or '').lower()
                cat_lower = str(elem.get('category') or '').lower()
                lname = (elem.get('label_data') or {}).get('name', '')
                if lname and ('contactor' in svg_lower or 'contactor' in cat_lower):
                    contactor_names.add(lname)

        # 2. contar NO y NC auxiliares cuyo nombre coincide con un contactor
        aux_map = {}  # {name: {'NO': int, 'NC': int}}
        for sheet in project.sheets:
            if sheet.name in EXCLUDED_SHEETS or 'unifilar' in sheet.name.lower():
                continue
            for elem in sheet.elements:
                if not isinstance(elem, dict):
                    continue
                svg_lower = str(elem.get('svg_file') or '').lower()
                lname = (elem.get('label_data') or {}).get('name', '')
                if not lname or lname not in contactor_names:
                    continue
                is_contactor_itself = 'contactor' in svg_lower or 'contactor' in str(elem.get('category') or '').lower()
                if is_contactor_itself:
                    continue
                # NC: main-switch-nc-1p.svg
                if 'main-switch-nc' in svg_lower:
                    aux_map.setdefault(lname, {'NO': 0, 'NC': 0})['NC'] += 1
                elif 'main-switch' in svg_lower and 'nc' not in svg_lower:
                    aux_map.setdefault(lname, {'NO': 0, 'NC': 0})['NO'] += 1

        return aux_map

    def _group_data(self, components_data, project=None):
        """Agrupa los componentes por Referencia, Descripción y Specs, de-duplicando por nombre.
        Los contactos auxiliares NO/NC del mismo nombre que un contactor se absorben
        en la descripcion del contactor (no aparecen como fila separada)."""

        # Construir mapa de auxiliares si tenemos proyecto
        aux_map = self._build_contactor_aux_map(project) if project else {}
        ground_borner_poles = self._get_ground_borner_pole_counts(project)

        # Nombres que son contactos auxiliares de un contactor (se excluyen de la BOM)
        EXCLUDED_SHEETS = self.EXCLUDED_SHEETS
        aux_contact_keys = set()  # ids de elementos cuyos contactos NO/NC ya están absorbidos
        if project:
            contactor_names = set(aux_map.keys()) | {
                (elem.get('label_data') or {}).get('name', '')
                for sheet in project.sheets
                if sheet.name not in EXCLUDED_SHEETS and 'unifilar' not in sheet.name.lower()
                for elem in sheet.elements
                if isinstance(elem, dict) and (
                    'contactor' in str(elem.get('svg_file') or '').lower() or
                    'contactor' in str(elem.get('category') or '').lower()
                )
            }
            # Marcar como absorbibles: elementos cuyo svg es no.svg/nc.svg y nombre = contactor
            for sheet in project.sheets:
                if sheet.name in EXCLUDED_SHEETS or 'unifilar' in sheet.name.lower():
                    continue
                for elem in sheet.elements:
                    if not isinstance(elem, dict):
                        continue
                    svg_lower = str(elem.get('svg_file') or '').lower()
                    lname = (elem.get('label_data') or {}).get('name', '')
                    if lname in contactor_names and (
                        'main-switch-nc' in svg_lower or
                        ('main-switch' in svg_lower and 'nc' not in svg_lower and 'contactor' not in svg_lower)
                    ):
                        aux_contact_keys.add(id(elem))

        # 1. De-duplicar por nombre (referencia), excluyendo contactos auxiliares absorbidos
        unique_physicals = {}
        for data in components_data:
            # Saltar contactos auxiliares que ya seran absorbidos por su contactor
            if id(data) in aux_contact_keys:
                continue
            label_data = data.get('label_data', {})
            name = label_data.get('name', '??')

            # Las bornas son elementos físicos independientes. Pueden repetir
            # referencia (por ejemplo X7 gris y X7 PE), por lo que no deben
            # pasar por la deduplicación general basada en el nombre.
            if 'borner' in str(data.get('svg_file') or '').lower():
                borner_data = data.copy()
                borner_data['_bom_ground_poles'] = ground_borner_poles.get(id(data), 0)
                unique_physicals[f"borner_{id(data)}"] = borner_data
                continue

            # Si no tiene nombre, tratar como elemento individual
            if not name or name == '??':
                # Usar id del objeto para que sea único
                unique_key = f"anon_{id(data)}"
                unique_physicals[unique_key] = data
                continue

            if name not in unique_physicals:
                # Copiar para no mutar el original
                unique_physicals[name] = data.copy()
            else:
                # Combinar información (merge) en el elemento único ya registrado
                existing_label = unique_physicals[name].get('label_data', {})
                current_label = data.get('label_data', {})

                # Campos a unificar (si el existente está vacío y el nuevo tiene datos)
                for field in ['description', 'marca', 'voltaje', 'amperios', 'potencia']:
                    if not existing_label.get(field) and current_label.get(field):
                        existing_label[field] = current_label[field]

        # 2. Agrupar los elementos físicos únicos por su descripción y especificaciones
        grouped = {}
        for data in unique_physicals.values():
            label_data = data.get('label_data', {})
            name = label_data.get('name', '??')
            svg_lower = str(data.get('svg_file') or '').lower()
            is_borner = 'borner' in svg_lower

            # Priorizar campo 'description' explícito
            description = label_data.get('description', '').strip()

            # Comercialmente las borneras se adquieren por polos individuales.
            # Por ello, en la BOM todas se muestran como borna para riel, incluso
            # si el símbolo del esquema representa 2, 3 o 4 polos.
            if is_borner:
                description = "Borna para riel"
            # Si no hay descripción explícita, usar categoría o deducirla
            elif not description:
                description = self._deduce_description(data)
            else:
                # Si hay descripción explícita, agregar polos si el componente
                # es un breaker, contactor o relé térmico y aún no los tiene.
                description = self._enrich_description_with_poles(data, description)

            # Normalizar los nombres comerciales que se muestran en la BOM,
            # incluso si el usuario conservó una descripción anterior.
            description = self._normalize_bom_description(data, description)

            # ENRIQUECER DESCRIPCION DE CONTACTOR CON AUXILIARES
            # Si este elemento es un contactor Y tiene auxiliares registrados,
            # la descripcion pasa a ser "Contactor + X NO + Y NC"
            cat_lower = str(data.get('category') or '').lower()
            is_contactor = 'contactor' in svg_lower or 'contactor' in cat_lower
            if is_contactor and name in aux_map:
                aux = aux_map[name]
                poles = self._extract_poles(data) or "1p"
                base = f"Contactor {poles}"
                parts = [base]
                if aux.get('NO', 0) > 0:
                    parts.append(f"{aux['NO']} NO")
                if aux.get('NC', 0) > 0:
                    parts.append(f"{aux['NC']} NC")
                if len(parts) > 1:
                    description = " + ".join(parts)

            marca = label_data.get('marca', '').strip()
            voltaje = label_data.get('voltaje', '').strip()
            amperios = label_data.get('amperios', '').strip()
            potencia = label_data.get('potencia', '').strip()

            # Construir especificaciones combinadas
            specs_parts = [p for p in [marca, voltaje, amperios, potencia] if p]
            specs = " ".join(specs_parts)

            # Clave de agrupación
            key = (description, specs)

            if is_borner:
                total_poles = self._get_borner_pole_count(svg_lower)
                ground_poles = min(int(data.get('_bom_ground_poles', 0)), total_poles)

                # Un símbolo multipolo puede mezclar polos grises, azules y PE.
                # Solo los polos conectados a PE van a la fila de tierra.
                if ground_poles:
                    ground_key = ("Borna para riel - Tierra (PE)", specs)
                    grouped.setdefault(ground_key, []).extend([name] * ground_poles)
                    total_poles -= ground_poles

                if total_poles:
                    grouped.setdefault(key, []).extend([name] * total_poles)
                continue

            if key not in grouped:
                grouped[key] = []

            if name:
                # Una bornera multipolo equivale a tantas bornas individuales
                # para riel como polos tenga. Repetimos internamente la
                # referencia para contabilizarla, pero se muestra una sola vez.
                pole_count = self._get_borner_pole_count(svg_lower) if is_borner else 1
                grouped[key].extend([name] * pole_count)
            elif cat_lower == 'block_terminal':
                # Un Block Terminal es un elemento físico: debe contarse en la
                # BOM aunque no tenga referencia asignada (evita cantidad 0).
                grouped[key].append(label_data.get('name') or 'BT')

        return grouped

    @staticmethod
    def _get_borner_pole_count(svg_file):
        """Devuelve los polos de borner-N.svg; una bornera sin sufijo es 1 polo."""
        match = re.search(r'borner-(\d+)', normalize_borner_svg(svg_file))
        return int(match.group(1)) if match else 1

    def _get_ground_borner_pole_counts(self, project):
        """Cuenta solo los polos verdes del Plano de Borner, uno por terminal verde."""
        if not project:
            return {}

        ground_poles = {}
        plan_generator = BornerPlanGenerator(project)
        for borner in plan_generator._collect_all_borners_with_connections(project, None):
            green_poles = set()
            for connection in borner.get('entradas', []) + borner.get('salidas', []):
                color = str(connection.get('color', '')).lower()
                nombre = str(connection.get('nombre', '')).upper()
                is_green_connection = (
                    any(token in color for token in ('#90ee90', '#32cd32', '#008000', 'green', 'verde', 'gnye')) or
                    any(token in nombre for token in ('PE', 'TIERRA', 'GROUND', 'GND'))
                )
                if is_green_connection:
                    green_poles.add(int(connection.get('borner_punto', 0)))

            if not green_poles and any(token in str(borner.get('color', '')).lower() for token in ('#90ee90', '#32cd32', '#008000', 'green', 'verde', 'gnye')):
                green_poles = set(range(borner.get('num_poles', 1)))

            if green_poles:
                element = project.sheets[borner['sheet_idx']].elements[borner['comp_idx']]
                ground_poles[id(element)] = len(green_poles)
        return ground_poles

    def _extract_poles(self, data):
        """Extrae el número de polos de un componente.

        Busca en este orden:
        1. Campo 'polos' en label_data  (ej. '3' o '3p')
        2. Patrón -Xp en svg_file (ej. 'contactor-3p.svg' -> '3p')
        3. Patrón -X al final del stem (ej. 'rele-thermal-overload-3.svg' -> '3p')
        4. Patrón Xp en label_data name (ej. 'KM1-3p' -> '3p')

        Retorna un string como '1p', '2p', '3p', '4p', o '' si no se encuentra.
        """
        import re as _re
        label_data = data.get('label_data') or {}

        # 1. Campo explícito 'polos' en label_data
        polos = str(label_data.get('polos', '')).strip()
        if polos:
            if polos.isdigit():
                return f"{polos}p"
            if _re.match(r'^\d+p$', polos, _re.IGNORECASE):
                return polos.lower()

        # Stem del svg sin extensión (ej. 'rele-thermal-overload-3')
        svg_file = str(data.get('svg_file') or '').lower()
        stem = svg_file.replace('.svg', '')

        # 2. Patrón -Xp dentro del stem (ej. 'circuit-breaker-3p-magnetic')
        match = _re.search(r'-(\d+)p(?:-|$)', stem)
        if match:
            return f"{match.group(1)}p"

        # 3. Patrón -X al final del stem (ej. 'rele-thermal-overload-3')
        match = _re.search(r'-(\d+)$', stem)
        if match:
            return f"{match.group(1)}p"

        # 4. Patrón Xp en el nombre de la referencia (ej. 'KM1-3p')
        name = str(label_data.get('name', '')).lower()
        match = _re.search(r'(\d+)p', name)
        if match:
            return f"{match.group(1)}p"

        return ''

    def _enrich_description_with_poles(self, data, description):
        """Agrega el número de polos a una descripción explícita de breaker,
        disyuntor, contactor o relé térmico si aún no los contiene.

        Ejemplos:
        "Breaker iC60N 25A" + svg 'circuit-breaker-3p-magnetic.svg' -> "Breaker iC60N 25A 3p"
        "Contactor LC1-D18" + svg 'contactor-3p.svg' -> "Contactor LC1-D18 3p"
        "Relé Térmico LRD" + svg 'rele-thermal-overload-3.svg' -> "Relé Térmico LRD 3p"
        "Breaker iC60N 25A 3p" (ya tiene polos) -> sin cambio
        """
        import re as _re
        svg_file = str(data.get('svg_file') or '').lower()
        category = str(data.get('category') or '').lower()

        # Solo actuar sobre componentes con polos relevantes
        is_target = (
            'breaker'   in svg_file or 'disyuntor' in svg_file or
            'contactor' in svg_file or 'contactor' in category or
            'thermal'   in svg_file or 'termico'   in svg_file or
            'thermal'   in category or 'guardamotor' in svg_file
        )
        if not is_target:
            return description

        # Si la descripción ya tiene un patrón de polos, no tocar
        if _re.search(r'\b\d+p\b', description, _re.IGNORECASE):
            return description

        poles = self._extract_poles(data)
        # Si no se encontró número en el svg ni en el nombre, asumir 1p.
        # Los SVGs de 1 polo no llevan número (ej. 'circuit-breaker-magnetic.svg'),
        # mientras que los de 2p/3p/4p sí lo indican explícitamente.
        if not poles:
            poles = '1p'
        return f"{description} {poles}"

    def _normalize_bom_description(self, data, description):
        """Aplica la nomenclatura comercial estándar de la lista BOM."""
        normalized = str(description or '').strip()
        svg_file = str(data.get('svg_file') or '').lower()
        label_data = data.get('label_data') or {}

        # Compatibilidad con descripciones guardadas antes de esta nomenclatura.
        if normalized.casefold() == 'piloto':
            return 'Luz Piloto'
        if normalized.casefold() == 'boya':
            return 'BOYA de Nivel'

        # Los selectores 3p/4p con LOTTO activo representan el interruptor de
        # leva bloqueable. El número de polos se toma del SVG/etiqueta para que
        # 3p y 4p no se agrupen como si fueran el mismo material.
        is_loto_switch = (
            bool(label_data.get('lotto')) and
            ('selector-3p-no' in svg_file or 'selector-4p-no' in svg_file)
        )
        is_legacy_loto_description = normalized.casefold() == 'interruptor loto'
        if is_loto_switch or is_legacy_loto_description:
            poles = self._extract_poles(data) or '1p'
            return f'Interruptor de Leva (Loto) {poles}'

        return normalized

    def _deduce_description(self, data):
        """Deduce una descripción legible basada en categoría o archivo"""
        category = str(data.get('category') or '').lower()
        svg_file = str(data.get('svg_file') or '').lower()
        # Relé en Zócalo: bobina sin componente asociado (is_relay_socket marcado en _collect)
        if data.get('_relay_socket'):
            return "Relé + Zócalo"
        if category == 'block_terminal':
            ld = data.get('label_data', {})
            filas  = ld.get('bt_filas',  '2')
            bornas = ld.get('bt_bornas', '5')
            return f"Repartidor de Cargas (Block Terminal) {filas}F × {bornas} bornas"
        # Borners (borneras/regletas de terminales)
        if 'borner' in svg_file:
            svg_file = normalize_borner_svg(svg_file)
            # Detectar número de polos: borner-1.svg, borner-2.svg, etc.
            if 'borner-1' in svg_file:
                return "Bornera 1 polo"
            elif 'borner-2' in svg_file:
                return "Bornera 2 polos"
            elif 'borner-3' in svg_file:
                return "Bornera 3 polos"
            elif 'borner-4' in svg_file:
                return "Bornera 4 polos"
            else:
                return "Bornera"

        if 'motor' in category: return "Motor"
        if 'contactor' in category or 'contactor' in svg_file:
            poles = self._extract_poles(data) or '1p'
            return f"Contactor {poles}"
        # Relé Térmico: rele-thermal-overload-X.svg / rele-thermal.svg
        if 'thermal' in svg_file or 'termico' in svg_file or 'thermal' in category:
            poles = self._extract_poles(data) or '1p'
            return f"Relé Térmico {poles}"
        if 'motor-circuit-breaker' in svg_file or 'guardamotor' in svg_file or 'guardamotor' in category:
            poles = self._extract_poles(data) or '1p'
            return f"Guardamotor {poles}"
        # Breakers / Disyuntores genéricos
        if 'breaker' in svg_file or 'disyuntor' in svg_file:
            poles = self._extract_poles(data) or '1p'
            return f"Disyuntor {poles}"
        if 'fuse' in svg_file: return "Fusible"
        if 'pilot' in svg_file or 'piloto' in svg_file: return "Luz Piloto"
        if 'roller-switch' in svg_file: return "BOYA de Nivel"
        if (label_data := data.get('label_data') or {}).get('lotto') and (
                'selector-3p-no' in svg_file or 'selector-4p-no' in svg_file):
            poles = self._extract_poles(data) or '1p'
            return f"Interruptor de Leva (Loto) {poles}"
        if 'button' in svg_file or 'boton' in svg_file: return "Pulsador"
        if 'plc' in category: return "PLC"
        if 'driver' in category or 'variador' in category: return "Variador/Driver"
        if 'sst' in category or 'sst' in svg_file: return "Arrancador Suave (SSF)"
        if 'power' in category or 'fuente' in category or 'power' in svg_file: return "Fuente de Poder"

        return category.capitalize() if category else "Componente"

    def _inject_infrastructure_items(self, app, grouped_data):
        """Agrega al BOM los ítems de infraestructura del gabinete:
        Gabinete, Riel DIN Metálica perforada 35mm y Canaleta Ranurada.

        Los valores se obtienen primero desde la hoja 'Hoja de Gabinete 2D' si
        existe (datos reales), y en segundo lugar desde el cálculo de
        dimensionamiento. Si hay canaletas con distintas secciones comerciales,
        se agruparán por sección.
        """
        import math as _math
        from models.shape import DinRail, Canaleta, BarraDist

        # 1. Dimensiones del gabinete
        dim_str = ""
        qty_gabinete = 1   # siempre 1 gabinete

        # Prioridad: gabinete seleccionado manualmente en el proyecto
        if hasattr(app.project, 'selected_cabinet') and app.project.selected_cabinet:
            w, h, d = app.project.selected_cabinet
            dim_str = f"{w} × {h} × {d} mm"
        else:
            # Calcular usando CabinetSummaryGenerator de forma reutilizable
            try:
                cab_gen = CabinetSummaryGenerator(app.project)
                classified = cab_gen._classify_devices(app.project)
                results = cab_gen._calculate_dimensions_and_materials(classified, app)
                dim_str = results.get('dimensiones', '')
            except Exception:
                dim_str = ""

        if dim_str:
            key_gab = ("Gabinete", dim_str)
            if key_gab not in grouped_data:
                grouped_data[key_gab] = []
            # Agregar referencia genérica solo si la lista está vacía
            if not grouped_data[key_gab]:
                grouped_data[key_gab].append("GABINETE")

        # 2. Riel DIN y Canaleta (desde Hoja de Gabinete 2D o cálculo)
        real_riel_m = 0.0
        canaletas_por_seccion_m = {}  # seccion -> metros totales
        barras_por_tipo_m = {}        # tipo (172A/206A/263A) -> metros totales

        for sheet in app.project.sheets:
            if sheet.name == "Hoja de Gabinete 2D":
                shapes = getattr(sheet, 'live_shape_objects', [])
                for shape in shapes:
                    if isinstance(shape, DinRail):
                        real_riel_m += shape.width / 1000.0
                    elif isinstance(shape, Canaleta):
                        sec = getattr(shape, 'seccion', None) or '40X40'
                        canaletas_por_seccion_m[sec] = canaletas_por_seccion_m.get(sec, 0.0) + shape.largo / 1000.0
                    elif isinstance(shape, BarraDist):
                        tipo = getattr(shape, 'tipo', None) or '172A'
                        barras_por_tipo_m[tipo] = barras_por_tipo_m.get(tipo, 0.0) + shape.largo / 1000.0
                break

        # Si no hay hoja 2D, usar el cálculo estimado (una única sección)
        if real_riel_m == 0.0 and not canaletas_por_seccion_m and not barras_por_tipo_m:
            try:
                cab_gen = CabinetSummaryGenerator(app.project)
                classified = cab_gen._classify_devices(app.project)
                results = cab_gen._calculate_dimensions_and_materials(classified, app)
                if real_riel_m == 0.0:
                    riel_str = results.get('riel_din', '0')
                    real_riel_m = float(''.join(c for c in riel_str.split()[0] if c.isdigit() or c == '.') or '0')
                can_str = results.get('canaleta', '0')
                can_m_est = float(''.join(c for c in can_str.split()[0] if c.isdigit() or c == '.') or '0')
                if can_m_est > 0:
                    canaletas_por_seccion_m['40X40'] = can_m_est
            except Exception:
                pass

        # Riel DIN
        if real_riel_m > 0:
            tiras_riel = _math.ceil(real_riel_m / 2.0)
            specs_riel = f"{real_riel_m:.2f} m → {tiras_riel} tira(s) de 2 m"
            key_riel = ("RIEL DIN Metálica perforada 35mm", specs_riel)
            if key_riel not in grouped_data:
                grouped_data[key_riel] = []
            if not grouped_data[key_riel]:
                for i in range(1, tiras_riel + 1):
                    grouped_data[key_riel].append(f"RIEL-{i}")

        # Canaleta (una fila por cada ancho comercial)
        def _orden_seccion(item):
            dims = parse_seccion_canaleta(item[0]) or (0, 0)
            return (dims[0], dims[1], item[0])

        for idx, (seccion, metros) in enumerate(sorted(canaletas_por_seccion_m.items(), key=_orden_seccion)):
            if metros <= 0:
                continue
            tiras_can = _math.ceil(metros / 2.0)
            specs_can = f"{metros:.2f} m → {tiras_can} tira(s) de 2 m"
            key_can = (f"Canaleta Ranurada {seccion}", specs_can)
            if key_can not in grouped_data:
                grouped_data[key_can] = []
            if not grouped_data[key_can]:
                for i in range(1, tiras_can + 1):
                    grouped_data[key_can].append(f"CAN-{idx + 1}-{i}")

        # Barra de distribución de cobre (una fila por cada tipo/capacidad)
        from models.shape import get_ancho_barra_dist
        for idx, (tipo, metros) in enumerate(sorted(barras_por_tipo_m.items())):
            if metros <= 0:
                continue
            tiras_bar = _math.ceil(metros / 2.0)
            specs_bar = f"{metros:.2f} m → {tiras_bar} tira(s) de 2 m"
            ancho = get_ancho_barra_dist(tipo)
            key_bar = (f"Barra de Distribución de cobre {tipo} ({ancho:g} mm)", specs_bar)
            if key_bar not in grouped_data:
                grouped_data[key_bar] = []
            if not grouped_data[key_bar]:
                for i in range(1, tiras_bar + 1):
                    grouped_data[key_bar].append(f"BAR-{idx + 1}-{i}")

    def _draw_bom_table(self, app, grouped_data):
        """Dibuja la tabla visualmente con estilo profesional"""
        app.canvas.xview_moveto(0)
        app.canvas.yview_moveto(0)
        app.canvas.update_idletasks()
        # Configuración de dimensiones (Un poco más ancho para dar aire)
        START_X = 120
        START_Y = 20

        # Anchos de columna optimizados
        COL_REF_W = 220    # Referencias
        COL_DESC_W = 220   # Descripción
        COL_SPEC_W = 280   # Especificaciones
        COL_QTY_W = 80     # Cantidad

        ROW_HEIGHT = 45
        HEADER_HEIGHT = 55

        TOTAL_WIDTH = COL_REF_W + COL_DESC_W + COL_SPEC_W + COL_QTY_W

        # Estilos profesionales
        IS_DARK = app.is_dark_mode()
        HEADER_BG = "#37474F" if IS_DARK else "#CFD8DC" # Gris azulado adaptativo
        LINE_COLOR = "#FFFFFF" if IS_DARK else "#000000"
        TEXT_COLOR = "#FFFFFF" if IS_DARK else "#000000"

        from models.shape import Rect

        # DIBUJAR ENCABEZADO
        header_center_x = START_X + TOTAL_WIDTH / 2
        header_center_y = START_Y + HEADER_HEIGHT / 2

        header_rect = Rect(header_center_x, header_center_y, TOTAL_WIDTH, HEADER_HEIGHT)
        header_rect.outline = LINE_COLOR
        header_rect.fill = HEADER_BG
        header_rect.outline_width = 1.5

        app.shape_manager.shapes.append(header_rect)
        header_rect.draw(app.canvas)

        # TextComponent usa anchor="center", así que necesitamos calcular el CENTRO del texto
        # no el borde izquierdo. Calculamos el centro de cada columna para el texto.

        col1_center = START_X + COL_REF_W / 2  # Centro de primera columna
        col2_center = START_X + COL_REF_W + COL_DESC_W / 2  # Centro de segunda columna
        col3_center = START_X + COL_REF_W + COL_DESC_W + COL_SPEC_W / 2  # Centro de tercera columna
        col4_center = START_X + COL_REF_W + COL_DESC_W + COL_SPEC_W + COL_QTY_W / 2  # Centro de cuarta columna

        headers = [
            ("REFERENCIAS", col1_center),
            ("DESCRIPCIÓN", col2_center),
            ("ESPECIFICACIONES", col3_center),
            ("CANT.", col4_center)
        ]

        for text, x_pos in headers:
            # Texto en negrita para encabezados
            t = TextComponent(app.canvas, text, 13, x_pos, START_Y + HEADER_HEIGHT/2, color=TEXT_COLOR)
            # En la implementación actual, TextComponent no soporta bold fácil por args,
            # pero podemos setear el font directamente si el componente lo permitiera.
            # Por ahora, tamaño 13 es suficiente.
            app.text_components.append(t)

        # DIBUJAR FILAS
        current_y = START_Y + HEADER_HEIGHT

        # Ordenar datos
        sorted_keys = sort_bom_entries(grouped_data)

        for desc, specs in sorted_keys:
            names = grouped_data[(desc, specs)]
            # Ordenar referencias
            names = sort_bom_references(names)

            refs_str = ", ".join(dict.fromkeys(names))
            qty = str(len(names))

            # Fondo de fila
            row_center_x = START_X + TOTAL_WIDTH / 2
            row_center_y = current_y + ROW_HEIGHT / 2

            row_rect = Rect(row_center_x, row_center_y, TOTAL_WIDTH, ROW_HEIGHT)
            row_rect.outline = "#455A64" if IS_DARK else "#90A4AE"
            row_rect.fill = "#1E1E2E" if IS_DARK else "white"
            row_rect.outline_width = 1

            app.shape_manager.shapes.append(row_rect)
            row_rect.draw(app.canvas)

            # Usar centros de columna para el texto (TextComponent usa anchor="center")
            row_data = [
                (refs_str, col1_center, COL_REF_W - 20),
                (desc, col2_center, COL_DESC_W - 20),
                (specs, col3_center, COL_SPEC_W - 20),
                (qty, col4_center, COL_QTY_W - 20)
            ]

            for text, x_pos, max_w in row_data:
                display_text = str(text)

                # Truncado inteligente (basado en ancho aprox)
                # Un carácter ocupa ~7-9px en font 11
                max_chars = int(max_w / 8.5)
                if len(display_text) > max_chars:
                    # Si es la columna de referencias, tal vez deberíamos permitir multilinea en el futuro.
                    # Por ahora truncamos con elipses.
                    display_text = display_text[:max_chars-3] + "..."

                # Alinear Cantidad al centro de su columna si se desea,
                # por ahora todos a la izquierda con padding 15
                t = TextComponent(app.canvas, display_text, 11, x_pos, current_y + ROW_HEIGHT/2, color=TEXT_COLOR)
                app.text_components.append(t)

            current_y += ROW_HEIGHT

        table_height = current_y - START_Y
        outer_center_x = START_X + TOTAL_WIDTH / 2
        outer_center_y = START_Y + table_height / 2
        outer_rect = Rect(outer_center_x, outer_center_y, TOTAL_WIDTH, table_height)
        outer_rect.outline = LINE_COLOR
        outer_rect.fill = "" # Vacío
        outer_rect.outline_width = 1.5
        app.shape_manager.shapes.append(outer_rect)
        outer_rect.draw(app.canvas)

        # NO actualizar scrollregion aquí - esto causa el problema del pan
        # El scrollregion debe mantenerse en su valor original del canvas

class CabinetSummaryGenerator:
    """Generador de Resumen de Gabinete (Dimensionamiento y Materiales)"""

    def __init__(self, project):
        self.project = project

    def generate_cabinet_summary_sheet(self, app):
        """Genera o actualiza la hoja de Resumen de Gabinete."""
        sheet_name = "Resumen de Gabinete"
        summary_sheet = None
        summary_index = -1

        for i, sheet in enumerate(app.project.sheets):
            if sheet.name == sheet_name:
                summary_sheet = sheet
                summary_index = i
                break

        if not summary_sheet:
            summary_sheet = app.project.add_sheet(sheet_name)
            summary_index = len(app.project.sheets) - 1

        app.switch_to_sheet(summary_index)

        app.canvas.delete("all")
        app.components.clear()
        app.connections.clear()
        app.text_components.clear()
        if hasattr(app, 'shape_manager'):
            app.shape_manager.shapes.clear()
        if hasattr(app, 'image_components'):
            app.image_components.clear()

        app.draw_grid(force=True)

        # 1. Recolectar y clasificar dispositivos
        classified_devices = self._classify_devices(app.project)

        # 2. Calcular dimensionamiento y materiales
        results = self._calculate_dimensions_and_materials(classified_devices, app)

        # 3. Dibujar tabla de resultados
        self._draw_summary_table(app, results)

        app.save_undo_checkpoint()

    def _classify_devices(self, project):
        """Clasifica los dispositivos del proyecto según las reglas del usuario."""
        classification = {
            'PROTECCIÓN': [],
            'MANIOBRA': [],
            'CONTROL': [],
            'PLC': [],
            'POTENCIA ELECTRÓNICA': [],
            'FUENTE': [],
            'PUERTA': [],
            'EXTERNO': [],
            'BORNERS': []
        }

        for sheet in project.sheets:
            # Ignorar hojas de reporte y cualquier hoja unifilar
            if sheet.name in ["Lista de Materiales", "Resumen de Gabinete"]:
                continue
            if 'unifilar' in sheet.name.lower():
                continue

            for elem in sheet.elements:
                if not isinstance(elem, dict) or elem.get('type') not in ['component', 'junction']:
                    continue

                category = str(elem.get('category') or '').lower()
                svg_file = str(elem.get('svg_file') or '').lower()

                # Ignorar componentes unifilares
                if 'unifilar' in category:
                    continue

                # Reglas de clasificación
                if 'motor' in category:
                    classification['EXTERNO'].append(elem)
                elif any(x in category for x in ['button', 'pilot', 'boton', 'piloto', 'selector']):
                    classification['PUERTA'].append(elem)
                elif 'borner' in svg_file:
                    classification['BORNERS'].append(elem)
                elif 'plc' in category:
                    classification['PLC'].append(elem)
                elif any(x in category for x in ['driver', 'variador', 'sst', 'soft starter']):
                    classification['POTENCIA ELECTRÓNICA'].append(elem)
                elif any(x in category for x in ['power', 'fuente']):
                    classification['FUENTE'].append(elem)
                elif any(x in category or x in svg_file for x in ['breaker', 'disyuntor', 'fuse', 'fusible', 'thermal', 'guardamotor']):
                    classification['PROTECCIÓN'].append(elem)
                elif 'contactor' in category or 'contactor' in svg_file:
                    classification['MANIOBRA'].append(elem)
                elif any(x in category or x in svg_file for x in ['relay', 'rele', 'coil', 'temporizador']):
                    classification['CONTROL'].append(elem)

        return classification

    def _calculate_dimensions_and_materials(self, classification, app=None):
        """Calcula las dimensiones del tablero y los materiales reales con criterios REFINADOS e INGENIERILES."""

        # 1. Sumar módulos DIN y determinar profundidad
        total_modules = 0
        base_depth = 200
        max_depth = base_depth

        # PROTECCIÓN, MANIOBRA, CONTROL, PLC, FUENTE, POTENCIA ELECTRÓNICA
        for cat_name, devices in classification.items():
            if cat_name in ['EXTERNO', 'BORNERS']: continue
            for dev in devices:
                w_mm, _h_mm = get_engineering_size(dev.get('svg_file'), dev.get('category'), dev.get('label_data'))
                total_modules += (w_mm / 18.0)

                # Criterio de profundidad para Potencia Electrónica
                if cat_name == 'POTENCIA ELECTRÓNICA':
                    if w_mm >= 150: max_depth = max(max_depth, 280)
                    elif w_mm >= 70: max_depth = max(max_depth, 210)

        # BORNERS: 1 módulo por cada 3 bornes (margen de seguridad)
        total_modules += math.ceil(len(classification['BORNERS']) / 3.0)

        # 2. Algoritmo de tablero comercial
        DIN_mm = total_modules * 18

        config = load_medidas_config()

        # PRIORIDAD: Si el usuario ya seleccionó un gabinete, usar ese
        if hasattr(self.project, 'selected_cabinet') and self.project.selected_cabinet:
            w, h, d = self.project.selected_cabinet
            selected_box = (w, h, d)
            # Calcular filas necesarias para este gabinete
            ancho_util_por_fila = w * 0.8
            filas = math.ceil(DIN_mm / ancho_util_por_fila)
        else:
            comerciales = config.get("armarios_comerciales", [
                [200, 300, 150], [300, 300, 150], [300, 400, 200], [400, 400, 200], [400, 500, 200],
                [400, 600, 250], [500, 500, 250], [600, 600, 250], [600, 800, 300], [800, 800, 300],
                [800, 1000, 300], [1000, 1200, 400]
            ])

            # Buscar el gabinete más pequeño que cumpla:
            # 1. Ancho suficiente para al menos una fila (o repartido en varias)
            # 2. Alto suficiente para las filas necesarias
            # 3. Profundidad >= max_depth

            selected_box = comerciales[-1] # Fallback al más grande

            for w, h, d in comerciales:
                if d < max_depth:
                    continue

                # Calculamos cuántas filas caben en este alto
                # 150mm por fila (incluye riel y canaletas) + 100mm de margen total
                posibles_filas = max(1, math.floor((h - 100) / 150))
                ancho_util_por_fila = w * 0.8 # 80% de utilización

                capacidad_total_mm = posibles_filas * ancho_util_por_fila

                if DIN_mm <= capacidad_total_mm:
                    selected_box = (w, h, d)
                    filas = math.ceil(DIN_mm / ancho_util_por_fila)
                    break
            else:
                # Si no cabe en ninguno estándar, usar el último pero calcular filas necesarias
                w, h, d = selected_box
                filas = math.ceil(DIN_mm / (w * 0.8))

        selected_width, selected_height, selected_depth = selected_box

        # 3. Cálculo de materiales REFINADO (Calibrado con datos reales)
        # Riel DIN: Calculado por ancho de tablero y número de filas
        riel_total_m = (filas * selected_width * 0.85) / 1000.0

        # Canaleta Ranurada: Formula calibrada para incluir montantes y desperdicio
        # (Ancho * (Filas + 2)) + (Alto * 2) -> multiplicado por factor 1.5 para cubrir trayectorias dobles
        canaleta_m = (((selected_width * (filas + 2)) + (selected_height * 2)) / 1000.0) * 1.5

        # Buscar "Hoja de Gabinete 2D" y obtener riel y canaleta reales
        real_riel_m = 0.0
        real_canaleta_m = 0.0
        secciones_canaleta = []  # secciones usadas en el 2D (p. ej. ['40X60', '20X20'])

        if app:
            for sheet in app.project.sheets:
                if sheet.name == "Hoja de Gabinete 2D":
                    shapes = getattr(sheet, 'live_shape_objects', [])
                    from models.shape import DinRail, Canaleta
                    for shape in shapes:
                        if isinstance(shape, DinRail):
                            real_riel_m += shape.width / 1000.0
                        elif isinstance(shape, Canaleta):
                            real_canaleta_m += shape.largo / 1000.0
                            sec = getattr(shape, 'seccion', None)
                            if sec and sec not in secciones_canaleta:
                                secciones_canaleta.append(sec)
                    break

        if real_riel_m > 0:
            riel_total_m = real_riel_m

        if real_canaleta_m > 0:
            canaleta_m = real_canaleta_m

        tiras_2m = math.ceil(canaleta_m / 2.0)

        # Sección comercial: la más larga si hay varias, si no la estimada por profundidad
        if secciones_canaleta:
            def _largo_sec(s):
                d = parse_seccion_canaleta(s) or (0, 0)
                return (d[0], d[1])
            secciones_canaleta.sort(key=_largo_sec)
            canaleta_dim = f"{secciones_canaleta[-1].lower()} mm"
            if len(secciones_canaleta) > 1:
                canaleta_dim += f" (+{len(secciones_canaleta) - 1} sección/es)"
        else:
            canaleta_dim = "40x40 mm" if selected_depth <= 250 else "60x40 mm"

        # Cable de potencia: Calibrado a 1.0m por fase
        max_amps = 0
        for ext in classification['EXTERNO']:
            amp_str = str(ext.get('label_data', {}).get('amperios', '0')).lower()
            try:
                amps = float(''.join(filter(lambda x: x.isdigit() or x == '.', amp_str)))
                max_amps = max(max_amps, amps)
            except: pass

        if max_amps == 0: gauge_potencia = "14 AWG (2.5 mm²)"
        elif max_amps < 15: gauge_potencia = "14 AWG (2.5 mm²)"
        elif max_amps < 25: gauge_potencia = "12 AWG (4.0 mm²)"
        elif max_amps < 35: gauge_potencia = "10 AWG (6.0 mm²)"
        else: gauge_potencia = "8 AWG (10.0 mm²)"

        motores = len(classification['EXTERNO'])
        cable_potencia_m = motores * 3 * 1.0 # 1.0m por fase

        # Cable de control: Calibrado a 0.12m por conexión promedio
        n_interno = len(classification['PROTECCIÓN']) + len(classification['MANIOBRA']) + len(classification['CONTROL']) + len(classification['PLC']) + len(classification['FUENTE'])
        n_puerta = len(classification['PUERTA'])

        conexiones_totales = (n_interno * 6) + (n_puerta * 4)
        control_m = (conexiones_totales * 0.12) * 1.15
        gauge_control = "18 AWG (1.0 mm²)"

        return {
            'dimensiones': f"{selected_width} x {selected_height} x {selected_depth} mm",
            'riel_din': f"{riel_total_m:.2f} m",
            'canaleta': f"{canaleta_m:.2f} m ({tiras_2m} tiras de 2m)",
            'canaleta_dim': canaleta_dim,
            'cable_potencia': f"{cable_potencia_m:.2f} m",
            'gauge_potencia': gauge_potencia,
            'cable_control': f"{control_m:.2f} m",
            'gauge_control': gauge_control,
            'detalles': {
                'modulos_totales': round(total_modules, 1),
                'filas': filas,
                'dispositivos_puerta': n_puerta,
                'dispositivos_internos': n_interno
            }
        }

    def _draw_summary_table(self, app, results):
        """Dibuja la tabla con mejor alineación y sin marcos fantasmas en PDF."""

        # Ajustes de layout para evitar solapamientos
        START_X = 450
        START_Y = 220
        WIDTH = 700
        ROW_HEIGHT = 40
        COL1_WIDTH = 450
        COL2_WIDTH = WIDTH - COL1_WIDTH

        IS_DARK = app.is_dark_mode()
        HEADER_COLOR = "#1a252f" if IS_DARK else "#2c3e50"
        COL_HEADER_COLOR = "#2c3e50" if IS_DARK else "#34495e"
        ROW_BG_EVEN = "#243342" if IS_DARK else "#f8f9fa"
        ROW_BG_ODD = "#1e2b34" if IS_DARK else "white"
        TEXT_COLOR_MAIN = "#ecf0f1" if IS_DARK else "#2c3e50"
        SEP_COLOR = "#34495e" if IS_DARK else "#dee2e6"
        VALUE_COLOR = "#f39c12" if IS_DARK else "#e67e22"

        # 1. Título con fondo dark (estético)
        header_bg = Rect(START_X + WIDTH/2, START_Y - 55, WIDTH + 20, 50)
        header_bg.fill = HEADER_COLOR
        header_bg.outline = "" # Sin borde para evitar recuadros en PDF
        app.shape_manager.shapes.append(header_bg)
        header_bg.draw(app.canvas)

        # Posicionamiento vertical: y-55 es el centro del Rect, el texto debe estar ahí.
        title = TextComponent(app.canvas, "RESUMEN DE DIMENSIONAMIENTO Y MATERIALES", 14, START_X + WIDTH/2, START_Y - 55, color="white")
        app.text_components.append(title)

        # 2. Encabezados de columna
        col_header = Rect(START_X + WIDTH/2, START_Y, WIDTH, ROW_HEIGHT)
        col_header.fill = COL_HEADER_COLOR
        col_header.outline = ""
        app.shape_manager.shapes.append(col_header)
        col_header.draw(app.canvas)

        # +3 de offset vertical para compensar baseline en exportación
        h1 = TextComponent(app.canvas, "CONCEPTO", 11, START_X + COL1_WIDTH/2, START_Y + 2, color="white")
        h2 = TextComponent(app.canvas, "VALOR ESTIMADO", 11, START_X + COL1_WIDTH + COL2_WIDTH/2, START_Y + 2, color="white")
        app.text_components.extend([h1, h2])

        # 3. Filas de datos principal
        rows_data = [
            ("DIMENSIONES TABLERO (An x Al x Pr)", results['dimensiones']),
            ("RIEL DIN TOTAL (Corte a medida)", results['riel_din']),
            (f"CANALETA RANURADA ({results['canaleta_dim']})", results['canaleta']),
            (f"CABLE DE POTENCIA ({results['gauge_potencia']})", results['cable_potencia']),
            (f"CABLE DE CONTROL ({results['gauge_control']})", results['cable_control']),
        ]

        y = START_Y + ROW_HEIGHT
        for i, (label, value) in enumerate(rows_data):
            # Fondo alterno
            row_bg = Rect(START_X + WIDTH/2, y, WIDTH, ROW_HEIGHT)
            row_bg.fill = ROW_BG_EVEN if i % 2 == 0 else ROW_BG_ODD
            row_bg.outline = ""
            app.shape_manager.shapes.append(row_bg)
            row_bg.draw(app.canvas)

            # Línea inferior de la fila (separador horizontal)
            line = Rect(START_X + WIDTH/2, y + ROW_HEIGHT/2, WIDTH, 1)
            line.fill = SEP_COLOR
            line.outline = ""
            app.shape_manager.shapes.append(line)
            line.draw(app.canvas)

            # Texto CENTRADO (Alineado con el encabezado CONCEPTO)
            t_l = TextComponent(app.canvas, label, 10, START_X + COL1_WIDTH/2, y + 2, color=TEXT_COLOR_MAIN)
            t_v = TextComponent(app.canvas, value, 10, START_X + COL1_WIDTH + COL2_WIDTH/2, y + 2, color=VALUE_COLOR)

            # INTERACTIVIDAD: Si es la fila de dimensiones, marcar como seleccionable
            if i == 0:
                t_v.metadata = {'type': 'cabinet_dimension_selector'}
                # Agregar un pequeño indicador visual (subrayado o similar)
                underline = Rect(START_X + COL1_WIDTH + COL2_WIDTH/2, y + 12, 100, 1)
                underline.fill = VALUE_COLOR; underline.outline = ""
                app.shape_manager.shapes.append(underline)
                underline.draw(app.canvas)

            app.text_components.extend([t_l, t_v])
            y += ROW_HEIGHT

        # 4. Detalles técnicos (Caja inferior separada)
        y += 40
        DETAILS_HEADER_COLOR = "#37474F" if IS_DARK else "#eceff1"
        DETAILS_TEXT_COLOR = "#CFD8DC" if IS_DARK else "#455a64"
        DETAILS_LABEL_COLOR = "#90A4AE" if IS_DARK else "#7f8c8d"
        DETAILS_VALUE_COLOR = "#64B5F6" if IS_DARK else "#2980b9"

        details_header_rect = Rect(START_X + WIDTH/2, y, WIDTH, ROW_HEIGHT)
        details_header_rect.fill = DETAILS_HEADER_COLOR
        details_header_rect.outline = ""
        app.shape_manager.shapes.append(details_header_rect)
        details_header_rect.draw(app.canvas)

        h_det = TextComponent(app.canvas, "INFORMACIÓN TÉCNICA ADICIONAL", 10, START_X + WIDTH/2, y + 2, color=DETAILS_TEXT_COLOR)
        app.text_components.append(h_det)

        details_data = [
            ("Módulos DIN ocupados", str(results['detalles']['modulos_totales'])),
            ("Filas DIN proyectadas", str(results['detalles']['filas'])),
            ("Dispositivos Internos", str(results['detalles']['dispositivos_internos']))
        ]

        for label, value in details_data:
            y += ROW_HEIGHT
            row_box = Rect(START_X + WIDTH/2, y, WIDTH, ROW_HEIGHT)
            row_box.fill = ROW_BG_ODD
            row_box.outline = ""
            app.shape_manager.shapes.append(row_box)
            row_box.draw(app.canvas)

            # Línea separadora
            line_sep = Rect(START_X + WIDTH/2, y + ROW_HEIGHT/2, WIDTH, 1)
            line_sep.fill = SEP_COLOR
            line_sep.outline = ""
            app.shape_manager.shapes.append(line_sep)
            line_sep.draw(app.canvas)

            t_dl = TextComponent(app.canvas, label, 9, START_X + COL1_WIDTH/2, y + 2, color=DETAILS_LABEL_COLOR)
            t_dv = TextComponent(app.canvas, value, 9, START_X + COL1_WIDTH + COL2_WIDTH/2, y + 2, color=DETAILS_VALUE_COLOR)
            app.text_components.extend([t_dl, t_dv])

        # Nota al pie
        footer_y = y + ROW_HEIGHT + 40
        footer_text = "Nota: Dimensionamiento basado en criterios de ingeniería industrial (75% ocupación útil).\nMateriales incluyen margen de seguridad del 10-15%."
        footer = TextComponent(app.canvas, footer_text, 9, START_X + WIDTH/2, footer_y, color=DETAILS_LABEL_COLOR)
        app.text_components.append(footer)

class BornerPlanGenerator:
    """Generador de Plano de Borner (Terminal Board Plan) - Usa SVG borner-pdf.svg"""

    # Dispositivos externos que se agrupan individualmente por su referencia
    # (igual que los motores): M1, K22, S3, ...
    PER_NAME_TYPES = ('Motor', 'Electrovalvula', 'Presostato')

    def __init__(self, project):
        self.project = project
        self.borner_svg_path = "svgs/borner-pdf.svg"

    @staticmethod
    def _element_description(elem):
        """Descripción de un elemento, leyendo 'descripcion' y 'description'."""
        ld = elem.get('label_data') if isinstance(elem, dict) else None
        if not isinstance(ld, dict):
            return ''
        return ' '.join(str(ld.get(k, '') or '') for k in ('descripcion', 'description'))

    def get_component_type(self, svg_file, name="", description=""):
        """
        Determina el tipo de componente basado en el archivo SVG, nombre o
        descripción. Considera motores, roller-switch, electroválvulas
        (solenoide externo) y presostatos/sensores de campo.
        """
        svg_lower = str(svg_file).lower()
        name_lower = str(name).lower()
        desc_lower = str(description or '').lower()

        # Electroválvulas / solenoides externos: aunque la referencia empiece por
        # 'K' (p.ej. K22) son dispositivos de campo y llevan bornas propias. Se
        # identifican por su símbolo para no confundirlas con bobinas de relé.
        if any(k in svg_lower for k in ('selenoid', 'solenoid', 'electrovalv')):
            return 'Electrovalvula'

        # Presostatos (por descripción): son dispositivos externos con bornas
        # propias aunque su símbolo sea un contacto NC/NO. NO incluir boyas/
        # flotadores: esos usan 'roller-switch.svg' y deben conservar su
        # agrupamiento Roller-Switch (no son presostatos).
        if any(k in desc_lower for k in (
                'presostato', 'pressostato', 'presion', 'pressure')):
            return 'Presostato'

        # Mapeo simplificado: solo motores y roller-switch
        if 'motor' in svg_lower:
            return 'Motor'
        elif 'roller-switch' in svg_lower:
            return 'Roller-Switch'

        # Fallback por nombre (prefijos comunes)
        if name:
            first_char = name[0].upper()
            if first_char == 'M':
                return 'Motor'

        # Tipo genérico para todo lo demás
        return 'Componente'

    def _is_lower_connection(self, element, point_idx):
        """
        Determina si el punto de conexión está en la parte superior o inferior del componente.
        """
        if not element or not isinstance(element, dict):
            return False

        conn_points = element.get('conn_points', [])
        if not conn_points or point_idx >= len(conn_points):
            return False

        y_coords = [p.get('y', 0) for p in conn_points]
        if not y_coords:
            return False

        y_min = min(y_coords)
        y_max = max(y_coords)

        # Si la diferencia es muy pequeña (ej: todos los puntos en una línea),
        # por convención consideramos que son superiores (caso motores/sensores simples)
        if y_max - y_min < 10:
            return False

        # Punto actual
        target_y = conn_points[point_idx].get('y', 0)

        # Si el punto está más cerca del máximo Y (abajo) que del mínimo Y (arriba)
        # se considera conexión inferior.
        y_center = (y_min + y_max) / 2
        return target_y > y_center

    def _get_terminal_label(self, element, point_idx):
        """
        Resuelve el nombre del borne físico (label) basado en el índice del punto.
        Para componentes estándar, alinea los ConnectionPoints con las etiquetas del usuario.
        """
        if not element or not isinstance(element, dict):
            return str(point_idx)

        name = element.get('label_data', {}).get('name', '').upper()
        svg_file = str(element.get('svg_file', '')).lower()

        # CASO ESPECIAL: Fase/Tierra (PE, N, L1, L2, L3)
        if name in ['PE', 'N', 'L1', 'L2', 'L3'] or 'fase' in svg_file or 't.svg' in svg_file:
            return ""

        terminals_str = element.get('label_data', {}).get('terminals', '')
        if not terminals_str:
            return str(point_idx)

        # 1. Parsear etiquetas del usuario (Orden Normativo: Columna por Columna)
        terminals_str = terminals_str.replace('-', ',').replace(' ', ',').replace(';', ',')
        user_labels = [t.strip() for t in terminals_str.split(',') if t.strip()]

        # 2. Obtener puntos de conexión del componente
        conn_points = element.get('conn_points', [])
        if not conn_points or point_idx >= len(conn_points):
            return str(point_idx)

        # 3. ALINEACIÓN DINÁMICA: Mapear Pin Index (Row-first) -> Label Index (Col-first)
        # Re-ordenamos todos los puntos usando el criterio normativo (Col-first: X luego Y)
        # para que coincida con la lista de etiquetas extraídas/editadas.
        points_with_orig_idx = []
        for i, p in enumerate(conn_points):
            points_with_orig_idx.append({
                'idx': i,
                'x': p.get('x', 0),
                'y': p.get('y', 0)
            })

        # Ordenar Columna por Columna (X then Y) con tolerancia
        def col_first_sort(p):
            # Tolerancia para agrupar ejes (10px es seguro para la mayoría de SVGs)
            col_x = round(p['x'] / 10) * 10
            return (col_x, p['y'])

        sorted_by_norm = sorted(points_with_orig_idx, key=col_first_sort)

        # 4. Encontrar la posición del pin actual en el orden normativo
        norm_idx = -1
        for i, p in enumerate(sorted_by_norm):
            if p['idx'] == point_idx:
                norm_idx = i
                break

        # 5. Retornar la etiqueta correspondiente si existe
        if 0 <= norm_idx < len(user_labels):
            return user_labels[norm_idx]

        return str(point_idx)

    def generate_borner_plan_sheet(self, app):
        """
        Genera o actualiza la hoja de Plano de Borner usando SVG borner-pdf.svg.
        Agrupa las bornas por componente conectado y muestra sus conexiones de entrada/salida.
        """
        # 1. Buscar si ya existe una hoja "Plano de Borner"
        borner_sheet = None
        borner_index = -1

        for i, sheet in enumerate(app.project.sheets):
            if sheet.name == "Plano de Borner":
                borner_sheet = sheet
                borner_index = i
                break

        # 2. Si no existe, crearla al final
        if not borner_sheet:
            borner_sheet = app.project.add_sheet("Plano de Borner")
            borner_index = len(app.project.sheets) - 1

        # 3. Cambiar a esa hoja para manipularla
        app.switch_to_sheet(borner_index)

        # 4. Marcar hoja como no editable (propiedad especial)
        borner_sheet.editable = False

        # 5. Limpiar contenido existente en la hoja
        app.canvas.delete("all")
        app.components.clear()
        app.connections.clear()
        app.text_components.clear()
        if hasattr(app, 'shape_manager'):
            app.shape_manager.shapes.clear()

        # Re-dibujar grid y configuraciones básicas
        app.draw_grid(force=True)

        # 6. Recolectar datos de TODAS las bornas del proyecto
        all_borners = self._collect_all_borners_with_connections(app.project, app)

        # 7. Agrupar bornas por componente conectado
        grouped_borners = self._group_borners_by_component(all_borners)

        # 8. Dibujar Plano de Borner con SVG
        self._draw_borner_plan(app, grouped_borners)

        # 9. Marcar como modificado
        app.save_undo_checkpoint()

    def _collect_all_borners_with_connections(self, project, app):
        """
        Recolecta todos los borners del proyecto con información detallada de sus conexiones.
        ENTRADAS: conexiones que LLEGAN al borne (end_idx == borne)
        SALIDAS: conexiones que SALEN del borne (start_idx == borne)
        """
        all_borners = []
        excluded_sheets = set(AppConstants.CROSS_REF_EXCLUDED_SHEETS)

        for sheet_idx, sheet in enumerate(project.sheets):
            # Excluir hojas derivadas/informes (Plano de Borner, Lista de Materiales,
            # unifilares, 2D, ...). Sin esto, las bornas dibujadas en el unifilar se
            # vuelven a recoger (p.ej. X1:1..X1:3) y aparecen duplicadas en un grupo
            # genérico aunque ya estén en el grupo correcto (M1).
            if sheet.name in excluded_sheets or 'unifilar' in sheet.name.lower():
                continue

            # Mapa de adyacencia de los empalmes (junctions) de la hoja. Permite
            # resolver el dispositivo real al que llega una borna cuando el tramo
            # pasa por un nodo de cable (p.ej. S3 -> J17 -> X7), en vez de quedarse
            # con el propio empalme, que no es un dispositivo.
            junction_neighbors = {}
            if hasattr(sheet, 'connections'):
                for _conn in sheet.connections:
                    if not isinstance(_conn, dict):
                        continue
                    _s_i = _conn.get('start_component_idx')
                    _e_i = _conn.get('end_component_idx')
                    if _s_i is None or _e_i is None:
                        continue
                    if 0 <= _s_i < len(sheet.elements) and self._is_junction(sheet.elements[_s_i]):
                        junction_neighbors.setdefault(_s_i, set()).add(_e_i)
                    if 0 <= _e_i < len(sheet.elements) and self._is_junction(sheet.elements[_e_i]):
                        junction_neighbors.setdefault(_e_i, set()).add(_s_i)

            for comp_idx, elem in enumerate(sheet.elements):
                if isinstance(elem, dict):
                    svg_file = str(elem.get('svg_file', '')).lower()

                    if 'borner' in svg_file:
                        num_poles = self._extract_num_poles(svg_file)
                        borner = {
                            'name': elem.get('label_data', {}).get('name', f'Borner_{comp_idx}'),
                            'sheet_idx': sheet_idx,
                            'comp_idx': comp_idx,
                            'svg_file': svg_file,
                            'num_poles': num_poles,
                            'entradas': [],  # Conexiones que LLEGAN al borne
                            'salidas': [],   # Conexiones que SALEN del borne
                            'traversed': [], # Dispositivos reales alcanzados vía empalmes
                            'color': '#cccccc'  # Color por defecto
                        }

                        # Detectar si es PE (equipotencial) para color verde
                        if 'PE' in borner['name'].upper():
                            borner['color'] = '#90EE90'  # Verde claro

                        # Buscar conexiones para este borner
                        far_junctions = set()
                        if hasattr(sheet, 'connections'):
                            for conn_idx, conn in enumerate(sheet.connections):
                                if isinstance(conn, dict):
                                    start_idx = conn.get('start_component_idx')
                                    end_idx = conn.get('end_component_idx')
                                    line_color = conn.get('line_color', '#000000')

                                    # Si el borne es el END de la conexión = ENTRADA
                                    if end_idx == comp_idx and start_idx is not None:
                                        start_elem = sheet.elements[start_idx] if 0 <= start_idx < len(sheet.elements) else None
                                        if start_elem:
                                            if self._is_junction(start_elem):
                                                far_junctions.add(start_idx)
                                            # Obtener etiqueta real del borne (ej: "2" en lugar de índice 3)
                                            label_punto = self._get_terminal_label(start_elem, conn.get('start_point_idx', 0))

                                            entrada = {
                                                'nombre': start_elem.get('label_data', {}).get('name') or start_elem.get('name', 'UNKNOWN'),
                                                'punto': label_punto,
                                                'borner_punto': conn.get('end_point_idx', 0),  # Punto de conexión en el borner
                                                'color': line_color,
                                                'tipo': start_elem.get('svg_file', ''),
                                                'desc': self._element_description(start_elem)
                                            }
                                            borner['entradas'].append(entrada)

                                    # Si el borne es el START de la conexión = SALIDA
                                    elif start_idx == comp_idx and end_idx is not None:
                                        end_elem = sheet.elements[end_idx] if 0 <= end_idx < len(sheet.elements) else None
                                        if end_elem:
                                            if self._is_junction(end_elem):
                                                far_junctions.add(end_idx)
                                            label_punto = self._get_terminal_label(end_elem, conn.get('end_point_idx', 0))

                                            salida = {
                                                'nombre': end_elem.get('label_data', {}).get('name') or end_elem.get('name', 'UNKNOWN'),
                                                'punto': label_punto,
                                                'borner_punto': conn.get('start_point_idx', 0),  # Punto de conexión en el borner
                                                'color': line_color,
                                                'tipo': end_elem.get('svg_file', ''),
                                                'desc': self._element_description(end_elem)
                                            }
                                            borner['salidas'].append(salida)

                        # Resolver empalmes: si alguna conexión directa de la borna
                        # es un nodo de cable (junction), seguir la red de empalmes
                        # para registrar el dispositivo real del otro lado. Así una
                        # borna como X7 (S3 -> J17 -> X7) se agrupa con su presostato
                        # S3 en lugar de quedar como "Componente" genérico.
                        _traversed_names = set()
                        for _j_idx in far_junctions:
                            for _dev in self._resolve_junction_devices(
                                    sheet, _j_idx, comp_idx, junction_neighbors):
                                _dev_name = (_dev.get('label_data', {}).get('name') or
                                             _dev.get('name', 'UNKNOWN'))
                                if _dev_name in _traversed_names:
                                    continue
                                _traversed_names.add(_dev_name)
                                borner['traversed'].append({
                                    'nombre': _dev_name,
                                    'punto': '',
                                    'borner_punto': 0,
                                    'color': '#000000',
                                    'tipo': _dev.get('svg_file', ''),
                                    'desc': self._element_description(_dev)
                                })

                        # Detección de tierra (PE): por nombre del conector, símbolo
                        # de tierra (t.svg) o color de cable. Marca el borne en verde.
                        if borner['color'] != '#90EE90':
                            for _c in borner['entradas'] + borner['salidas']:
                                _cn = str(_c.get('nombre', '')).upper()
                                _ct = str(_c.get('tipo', '')).lower()
                                _cc = str(_c.get('color', '')).lower()
                                _is_ground_partner = (
                                    len(_cn) > 0 and
                                    any(_t in _cn for _t in ('PE', 'GND', 'TIERRA', 'GROUND')))
                                _is_ground_symbol = (
                                    _ct == 't.svg' or
                                    'tierra' in _ct or 'ground' in _ct or 'gnd' in _ct)
                                _is_green_wire = any(
                                    _t in _cc for _t in (
                                        'green', 'verde', 'gnye',
                                        '#90ee90', '#32cd32', '#008000'))
                                if _is_ground_partner or _is_ground_symbol or _is_green_wire:
                                    borner['color'] = '#90EE90'
                                    break

                        all_borners.append(borner)

        return all_borners

    @staticmethod
    def _is_junction(elem):
        """True si el elemento es un nodo/empalme de cable (no un dispositivo)."""
        if not isinstance(elem, dict):
            return False
        if str(elem.get('type', '')).lower() == 'junction':
            return True
        return str(elem.get('category', '')).lower() == 'junction'

    @staticmethod
    def _is_borner_elem(elem):
        """True si el elemento es una borner o un bloque de bornas."""
        if not isinstance(elem, dict):
            return False
        return 'borner' in str(elem.get('svg_file', '')).lower()

    def _resolve_junction_devices(self, sheet, junction_idx, borner_idx, junction_neighbors):
        """
        Dispositivos reales alcanzables desde un empalme siguiendo cadenas de
        empalmes. Excluye empalmes, bornas y el propio borne de origen.
        """
        visited = {junction_idx}
        stack = [junction_idx]
        devices = []
        while stack:
            current = stack.pop()
            for neighbor in junction_neighbors.get(current, ()):
                if neighbor in visited or neighbor == borner_idx:
                    continue
                visited.add(neighbor)
                if neighbor < 0 or neighbor >= len(sheet.elements):
                    continue
                elem = sheet.elements[neighbor]
                if self._is_junction(elem):
                    stack.append(neighbor)
                elif self._is_borner_elem(elem):
                    continue
                else:
                    devices.append(elem)
        return devices

    def _extract_num_poles(self, svg_file):
        """Extrae el número de polos del nombre del archivo SVG"""
        svg_file = normalize_borner_svg(svg_file)
        if 'borner-1' in svg_file:
            return 1
        elif 'borner-2' in svg_file:
            return 2
        elif 'borner-3' in svg_file:
            return 3
        elif 'borner-4' in svg_file:
            return 4
        return 2

    def _group_borners_by_component(self, borners):
        """
        Agrupa los borners por el TIPO de componente al que están conectados.
        IMPORTANTE: Agrupa bornes individuales en clusters usando Union-Find 
        cuando comparten componentes comunes, SOLAMENTE aplicable a `Roller-Switch`.
        Para otros elementos como `Motores`, se agrupa estrictamente por la referencia única del componente.
        Finalmente expande bornes múltiples en símbolos individuales (polos).
        """
        parent = {}
        def find(i):
            if parent.setdefault(i, i) == i: return i
            parent[i] = find(parent[i])
            return parent[i]

        def union(i, j):
            root_i = find(i)
            root_j = find(j)
            if root_i != root_j:
                parent[root_i] = root_j

        # 1. Identificar conexiones relevantes de cada borne completo (todos sus polos)
        for borner in borners:
            connected_components = []
            for salida in borner['salidas']:
                comp_type = self.get_component_type(salida['tipo'], salida['nombre'], salida.get('desc', ''))
                connected_components.append((comp_type, salida['nombre'], 'salida'))
            for entrada in borner['entradas']:
                comp_type = self.get_component_type(entrada['tipo'], entrada['nombre'], entrada.get('desc', ''))
                connected_components.append((comp_type, entrada['nombre'], 'entrada'))
            # Dispositivos reales detectados al cruzar empalmes: cuentan para la
            # agrupación (p.ej. X7 -> J17 -> S3 se agrupa con el presostato S3).
            for traversed in borner.get('traversed', []):
                comp_type = self.get_component_type(traversed['tipo'], traversed['nombre'], traversed.get('desc', ''))
                connected_components.append((comp_type, traversed['nombre'], 'traves'))

            borner['connected_components'] = connected_components

            # Clasificar el borne determinando a qué componente pertenece realmente
            # (Prioridad: Motor -> dispositivos por-referencia -> Roller-Switch -> Other)
            motor_connection = None
            per_name_connection = None
            roller_connections = []
            other_connection = None

            for comp_type, comp_name, direction in connected_components:
                if comp_type == 'Motor':
                    motor_connection = (comp_type, comp_name)
                    break # Motor toma precedencia total y absoluta
                elif comp_type in self.PER_NAME_TYPES:
                    if per_name_connection is None:
                        per_name_connection = (comp_type, comp_name)
                elif comp_type == 'Roller-Switch':
                    if comp_name not in roller_connections:
                        roller_connections.append(comp_name)
                elif direction == 'salida' and other_connection is None:
                    other_connection = (comp_type, comp_name)
                elif other_connection is None:
                    other_connection = (comp_type, comp_name)

            if motor_connection:
                borner['group_type'] = 'Motor'
                borner['group_target'] = [motor_connection[1]] # ej: ['M1']
            elif per_name_connection:
                # Electroválvulas, presostatos, ...: agrupados por referencia (K22, S3)
                borner['group_type'] = per_name_connection[0]
                borner['group_target'] = [per_name_connection[1]]
            elif roller_connections:
                borner['group_type'] = 'Roller-Switch'
                borner['group_target'] = roller_connections # ej: ['SW1', 'SW2']
            elif other_connection:
                borner['group_type'] = 'Other'
                borner['group_target'] = [other_connection[1]] # ej: ['Pulsador1']
                borner['other_type'] = other_connection[0]
            else:
                borner['group_type'] = 'None'
                borner['group_target'] = [] # Sin conexión

            # SOLO agrupar con Union-Find si son instancias de Roller-Switch.
            if borner['group_type'] == 'Roller-Switch':
                find(borner['name'])
                for sw_name in borner['group_target']:
                    union(borner['name'], sw_name)

        # 2. Agrupar los borners completos en clusters
        clusters = {}
        for borner in borners:
            if borner['group_type'] in self.PER_NAME_TYPES:
                # Agrupado individual estricto por referencia (M1, K22, S3, ...),
                # igual que los motores.
                root = f"{borner['group_type']}_{borner['group_target'][0]}"
                if root not in clusters:
                    clusters[root] = {'borners': [], 'comp_names': set(), 'comp_type': borner['group_type']}
                clusters[root]['borners'].append(borner)
                clusters[root]['comp_names'].add(borner['group_target'][0])

            elif borner['group_type'] == 'Roller-Switch':
                # Agrupado por el nodo combinado del Union-Find
                root = find(borner['name'])
                if root not in clusters:
                    clusters[root] = {'borners': [], 'comp_names': set(), 'comp_type': 'Roller-Switch'}
                clusters[root]['borners'].append(borner)
                for sw_name in borner['group_target']:
                    clusters[root]['comp_names'].add(sw_name)

            elif borner['group_type'] == 'Other':
                # Agrupar individual por nombre de este elemento (ej: Pulsadores)
                root = f"Other_{borner['group_target'][0]}"
                if root not in clusters:
                    clusters[root] = {'borners': [], 'comp_names': set(), 'comp_type': borner.get('other_type', 'Other')}
                clusters[root]['borners'].append(borner)
                clusters[root]['comp_names'].add(borner['group_target'][0])

            else:
                # Instancias sin conexión válida
                root = f"None_{borner['name']}"
                if root not in clusters:
                    clusters[root] = {'borners': [], 'comp_names': set(), 'comp_type': 'SIN CONEXIÓN'}
                clusters[root]['borners'].append(borner)
                clusters[root]['comp_names'].add('SIN CONEXIÓN')

        # 3. Expandir a polos individuales (group_key ya resuelto) y asignar
        grouped = {}

        # Helper para garantizar ordenamiento natural de polos
        def sort_polos(p):
            name = p['name']
            import re
            parts = re.split(r'(\d+)', name)
            return [int(part) if part.isdigit() else part for part in parts]

        for root, cluster_data in clusters.items():
            comp_names = sorted(list(cluster_data['comp_names']))
            comp_type = cluster_data['comp_type']

            if comp_type in self.PER_NAME_TYPES:
                # Motores, electroválvulas, presostatos, ...: una entrada por
                # referencia del dispositivo.
                component_type = comp_type
                component_name = comp_names[0]
                group_key = component_name
            elif comp_type == "Roller-Switch":
                component_type = "Roller-Switch"
                component_name = " + ".join(comp_names)
                group_key = component_name
            else:
                if comp_type != "SIN CONEXIÓN" and comp_names:
                    component_type = comp_type
                    component_name = comp_names[0]
                else:
                    component_type = "SIN CONEXIÓN"
                    component_name = "SIN CONEXIÓN"
                # Fallback genérico para category/types no nativos
                group_key = component_type if component_type != "SIN CONEXIÓN" else root

            if group_key not in grouped:
                grouped[group_key] = []

            # Expandir los borners del cluster en polos individuales
            cluster_individual_poles = []
            for borner in cluster_data['borners']:
                num_poles = borner['num_poles']
                if num_poles == 1:
                    polo = {
                        'name': borner['name'],
                        'num_poles': 1,
                        'color': borner['color'],
                        'entradas': borner['entradas'],
                        'salidas': borner['salidas'],
                        'comp_idx': borner['comp_idx'],
                        'polo_idx': 0,
                        'connection_side': 'upper'
                    }
                    cluster_individual_poles.append(polo)
                else:
                    for polo_idx in range(num_poles):
                        polo = {
                            'name': f"{borner['name']}:{polo_idx + 1}",
                            'num_poles': 1,
                            'color': borner['color'],
                            'entradas': [e for e in borner['entradas'] if e.get('borner_punto', 0) == polo_idx],
                            'salidas': [s for s in borner['salidas'] if s.get('borner_punto', 0) == polo_idx],
                            'comp_idx': borner['comp_idx'],
                            'polo_idx': polo_idx,
                            'connection_side': 'upper'
                        }
                        cluster_individual_poles.append(polo)

            sorted_polos_cluster = sorted(cluster_individual_poles, key=sort_polos)

            # DEDUPLICACIÓN DE POLOS POR NOMBRE (solo para grupos de Motor)
            # Dos situaciones generan entradas sobrantes:
            # 1. Duplicado exacto: el mismo borne de 1 polo aparece dos veces en el
            #    cluster (ej. X1, X1, X2 -> debe quedar X1, X2).
            # 2. Padre + hijos expandidos: un borner-N de nombre "X1" genera los polos
            #    "X1:1", "X1:2", …, "X1:N" mediante el bloque `else`, pero a la vez
            #    puede existir en el cluster un borne de 1 polo también llamado "X1"
            #    (el componente padre sin expandir), produciendo "X1, X1:1, X1:2, …".
            #    El "X1" suelto es redundante y debe eliminarse.
            if cluster_data.get('comp_type') in self.PER_NAME_TYPES:
                # Paso A: recopilar todos los prefijos que tienen hijos expandidos
                # Un polo expandido tiene el formato "PREFIJO:N" (contiene ':')
                prefijos_expandidos = set()
                for polo in sorted_polos_cluster:
                    if ':' in polo['name']:
                        prefijo = polo['name'].rsplit(':', 1)[0]
                        prefijos_expandidos.add(prefijo)

                # Paso B: descartar el borne padre bare si sus hijos ya están presentes,
                # y descartar cualquier nombre exactamente duplicado
                seen_polo_names = set()
                deduped = []
                for polo in sorted_polos_cluster:
                    nombre = polo['name']
                    # Saltar el bare-parent cuando sus polos expandidos existen
                    if nombre in prefijos_expandidos:
                        continue
                    # Saltar duplicados exactos
                    if nombre in seen_polo_names:
                        continue
                    seen_polo_names.add(nombre)
                    deduped.append(polo)
                sorted_polos_cluster = deduped

            for polo in sorted_polos_cluster:
                polo['component_name'] = component_name
                polo['component_type'] = component_type
                polo['group_key'] = group_key

                # Detectar lado de conexión (connection_side)
                found_elem = None
                for s in self.project.sheets:
                    for e in s.elements:
                        if e.get('label_data', {}).get('name') in comp_names or (not comp_names and e.get('label_data', {}).get('name') == component_name):
                            found_elem = e
                            break
                    if found_elem: break

                if found_elem:
                    elem_name = found_elem.get('label_data', {}).get('name')
                    for s in self.project.sheets:
                        if not hasattr(s, 'connections'): continue
                        for c in s.connections:
                            polo_num = polo['polo_idx']
                            if (c.get('end_component_idx') == polo['comp_idx'] and c.get('end_point_idx') == polo_num and
                                s.elements[c.get('start_component_idx')].get('label_data', {}).get('name') == elem_name):
                                if self._is_lower_connection(found_elem, c.get('start_point_idx', 0)):
                                    polo['connection_side'] = 'lower'
                            elif (c.get('start_component_idx') == polo['comp_idx'] and c.get('start_point_idx') == polo_num and
                                  s.elements[c.get('end_component_idx')].get('label_data', {}).get('name') == elem_name):
                                if self._is_lower_connection(found_elem, c.get('end_point_idx', 0)):
                                    polo['connection_side'] = 'lower'

                grouped[group_key].append(polo)

        return grouped

    def _draw_borner_plan(self, app, grouped_borners):
        """
        Dibuja el plano de bornes completo según el layout profesional:
        - Etiquetas de ENTRADA arriba (componentes que llegan al borne)
        - Símbolos de bornes entre las dos líneas paralelas
        - Etiquetas de BORNE debajo (X1, X2, X3, etc.)
        - Líneas verticales conectando a componentes externos
        - Símbolos de componentes externos abajo
        """

        canvas_width = app.canvas.winfo_width()
        if canvas_width < 1000:
            canvas_width = 1200

        # 0. Título Profesional
        from models.shape import Rect
        TITLE_Y = 30           # Más arriba (antes 80)
        TITLE_X = 400          # Más a la izquierda (antes canvas_width/2)
        TITLE_WIDTH = 800
        TITLE_HEIGHT = 50

        IS_DARK = app.is_dark_mode()
        HEADER_BG_COLOR = "#1a252f" if IS_DARK else "#2c3e50"
        TITLE_TEXT_COLOR = "white"
        LINE_COLOR = "white" if IS_DARK else "black"
        BORNER_TEXT_COLOR = "#ecf0f1" if IS_DARK else "#000000"
        LABEL_BLUE = "#3498db" if IS_DARK else "#0000FF"

        header_bg = Rect(TITLE_X, TITLE_Y, TITLE_WIDTH, TITLE_HEIGHT)
        header_bg.fill = HEADER_BG_COLOR
        header_bg.outline = ""
        if hasattr(app, 'shape_manager'):
            app.shape_manager.shapes.append(header_bg)
        header_bg.draw(app.canvas)

        title = TextComponent(app.canvas, "PLANO DE CONEXIONES DE BORNES", 16, TITLE_X, TITLE_Y, color=TITLE_TEXT_COLOR)
        app.text_components.append(title)

        # Posiciones Y para las líneas del riel DIN
        rail_y1 = 400
        rail_y2 = 490
        center_y = (rail_y1 + rail_y2) / 2

        from models.shape import Line
        rail_line1 = Line(0, rail_y1, canvas_width, rail_y1)
        rail_line1.width = 3
        rail_line1.fill = LINE_COLOR
        app.shape_manager.shapes.append(rail_line1)
        rail_line1.draw(app.canvas)

        rail_line2 = Line(0, rail_y2, canvas_width, rail_y2)
        rail_line2.width = 3
        rail_line2.fill = LINE_COLOR
        app.shape_manager.shapes.append(rail_line2)
        rail_line2.draw(app.canvas)

        # Configuración para dibujar bornes
        current_x = 100  # Posición X inicial
        borne_width = 42   # Ancho real del SVG (15mm ≈ 42px a 72 DPI)
        borne_height = 164 # Alto real del SVG (58mm ≈ 164px a 72 DPI)
        borne_pitch = 32   # Distancia entre bornes (Paso)
        group_spacing = 30  # Espaciado entre grupos de componentes

        # Iterar sobre grupos de bornes ordenados por nombre de componente
        for group_key in sorted(grouped_borners.keys()):
            # Excluir bornas de bloque agrupadas (None_X1, None_X2, etc.): ya existen en la lógica del plano de bornas
            if group_key.startswith('None_'):
                continue

            borners = grouped_borners[group_key]

            # Determinar el tipo y label del componente para este grupo.
            # Motores y electroválvulas se agrupan por nombre específico (M1, K22),
            # por lo que group_key YA es el nombre; el resto usa el tipo como label.
            group_component_type = None
            for b in borners:
                ct = b.get('component_type')
                if ct in ("Motor", "Electrovalvula", "Presostato"):
                    group_component_type = ct
                    break
            if group_component_type:
                component_type = group_component_type
                component_label = group_key
            else:
                component_type = group_key  # Tipo como Roller-Switch
                component_label = group_key  # Label como Roller-Switch

            group_start_x = current_x
            terminal_centers = []

            for borner in borners:
                # Calcular posición central del borne basado en el pitch para alineación perfecta
                borne_center_x = current_x + borne_pitch / 2
                terminal_centers.append(borne_center_x)

                # 1. ETIQUETAS DE ENTRADA ARRIBA (componentes que llegan al borne)
                entrada_y = rail_y1 - 120

                # Lógica de Referencias Superiores: elegir el lado que realmente
                # indica DE DÓNDE VIENE la alimentación del borne. Se prefiere lo
                # que LLEGA al borne (entradas); si queda vacío —porque el único
                # elemento era el propio componente de agrupación (p.ej. el motor
                # del que cuelga el borne, o al que alimenta)— se cae a las salidas.
                # Así, un borner X2 de motor recibe M1->X2 (entradas) y F1->X2
                # (salidas); se muestra "F1-2/F1-4/F1-6" en lugar de nada.
                comp_agrupacion = borner.get('component_name')
                entradas = [e for e in borner.get('entradas', []) if e.get('nombre') != comp_agrupacion]
                if not entradas:
                    entradas = [s for s in borner.get('salidas', []) if s.get('nombre') != comp_agrupacion]

                # Detección profesional de terminales de tierra (PE)
                is_ground_terminal = (
                    borner.get('color') == '#90EE90' or
                    'PE' in borner['name'].upper() or
                    any(c in borner['name'].upper() for c in ['TIERRA', 'GROUND', 'GND'])
                )

                # Verificar conexiones para confirmar si es PE
                if not is_ground_terminal:
                    all_conns = borner.get('entradas', []) + borner.get('salidas', [])
                    for conn in all_conns:
                        conn_color = str(conn.get('color', '')).lower()
                        conn_name = str(conn.get('nombre', '')).upper()
                        if (any(c in conn_color for c in ['green', 'verde', 'gnye', '#90ee90', '#32cd32', '#008000']) or
                            any(c in conn_name for c in ['PE', 'GND', 'TIERRA'])):
                            is_ground_terminal = True
                            break

                # Los bornes de tierra (PE) se muestran en verde con referencia "PE"
                if is_ground_terminal:
                    entradas = [{'nombre': 'PE', 'punto': '', 'color': '#008000'}]

                if entradas:
                    for i, entrada in enumerate(entradas):
                        # Formato: "F1-2" o "PE"
                        entrada_nombre = entrada['nombre']
                        entrada_punto = entrada.get('punto', '')
                        line_color = entrada.get('color', '#0000FF')

                        # Si tiene punto, agregar guión
                        if entrada_punto != '':
                            entrada_label = f"{entrada_nombre}-{entrada_punto}"
                        else:
                            entrada_label = entrada_nombre

                        entrada_text = TextComponent(
                            app.canvas,
                            entrada_label,
                            9,
                            borne_center_x,
                            entrada_y - (i * 15),  # Apilar si hay múltiples entradas
                            color=BORNER_TEXT_COLOR
                        )
                        app.text_components.append(entrada_text)

                        v_line = Line(
                            borne_center_x, entrada_y + 10 - (i * 15),
                            borne_center_x, rail_y1 - 5
                        )
                        v_line.color = line_color
                        app.shape_manager.shapes.append(v_line)
                        v_line.draw(app.canvas)
                0
                # 2. SÍMBOLO DE BORNE ENTRE LAS LÍNEAS
                self._render_borner_svg(app, borne_center_x, center_y, borne_width, borne_height, borner)

                # 3. ETIQUETA DE BORNE DEBAJO (X1, X2, X3, etc.)
                borne_label_y = rail_y2 + 70  # Bajamos un poco más la etiqueta
                borne_label = TextComponent(
                    app.canvas,
                    borner['name'],
                    10,
                    borne_center_x,
                    borne_label_y,
                    color=LABEL_BLUE
                )
                app.text_components.append(borne_label)

                # Línea vertical desde el borne hasta la línea de agrupación
                # NACEN DEL EXTREMO DEL BORNE (center_y + borne_height/2)
                borne_bottom_y = center_y + (borne_height / 2)
                grouping_line_y = borne_bottom_y + 25

                # Si es un grupo de Roller-Switches compartidos, aguantamos dibujar la línea de bajada individual. Solo la dibujamos si no pertenece a un grupo "A + B".
                if " + " not in group_key:
                    b_line = Line(
                        borne_center_x, borne_bottom_y - 5,
                        borne_center_x, grouping_line_y
                    )
                    b_line.width = 2
                    b_line.fill = LINE_COLOR
                    app.shape_manager.shapes.append(b_line)
                    b_line.draw(app.canvas)
                else:
                    # Dibujamos solo un segmento cortito para tocar la línea agrupadora
                    b_line = Line(
                        borne_center_x, borne_bottom_y - 5,
                        borne_center_x, grouping_line_y
                    )
                    b_line.width = 2
                    b_line.fill = LINE_COLOR
                    app.shape_manager.shapes.append(b_line)
                    b_line.draw(app.canvas)

                # Avanzar posición X un paso (pitch)
                current_x += borne_pitch

            # 4. LÍNEA VERTICAL HACIA COMPONENTE EXTERNO
            # Calcular el centro del grupo
            group_end_x = current_x
            group_center_x = (group_start_x + group_end_x) / 2

            # Dibujar línea horizontal que agrupa los bornes (PEINE)
            # La línea va EXACTAMENTE desde el primer borne hasta el último del grupo
            if terminal_centers:
                line_start_x = min(terminal_centers)
                line_end_x = max(terminal_centers)

                if len(terminal_centers) > 1:
                    h_line = Line(
                        line_start_x, grouping_line_y,
                        line_end_x, grouping_line_y
                    )
                    h_line.width = 2
                    h_line.fill = LINE_COLOR
                    app.shape_manager.shapes.append(h_line)
                    h_line.draw(app.canvas)

                # Calcular centro exacto del grupo de bornes para bajar la línea
                group_center_x = (line_start_x + line_end_x) / 2
            else:
                group_center_x = (group_start_x + group_end_x) / 2

            component_y = rail_y2 + 130 # Bajamos más el componente

            # Si es un grupo compartido o normal, baja una sola línea central
            down_line = Line(
                group_center_x, grouping_line_y,
                group_center_x, component_y + 15
            )
            down_line.width = 2
            down_line.fill = LINE_COLOR
            app.shape_manager.shapes.append(down_line)
            down_line.draw(app.canvas)

            # 5. SÍMBOLO Y ETIQUETA DEL COMPONENTE EXTERNO
            self._draw_external_component_symbol(app, component_type, component_label, group_center_x, component_y + 40, LINE_COLOR, BORNER_TEXT_COLOR)

            current_x += group_spacing

    def _draw_external_component_symbol(self, app, component_type, component_label, x, y, line_color, text_color):
        """
        Dibuja el símbolo del componente externo basado en el tipo (motor, roller-switch, etc.)
        Simplificado para solo motores y roller-switch por ahora.
        """

        # Determinar el símbolo basado en el tipo
        type_lower = component_type.lower()

        if 'motor' in type_lower:
            # Motor: círculo con M dentro
            from models.shape import Circle
            radius = 25
            motor_circle = Circle(x, y, radius)
            motor_circle.outline = line_color
            motor_circle.outline_width = 2
            app.shape_manager.shapes.append(motor_circle)
            motor_circle.draw(app.canvas)
            # Símbolo M
            motor_label = TextComponent(
                app.canvas,
                "M",
                14,
                x, y,
                color=text_color
            )
            app.text_components.append(motor_label)

            # Etiqueta del motor debajo
            comp_name = TextComponent(
                app.canvas,
                component_label,
                11,
                x, y + radius + 15,
                color=text_color
            )
            app.text_components.append(comp_name)

            # Terminales U, V, W (si es motor trifásico)
            if '3' in component_label or len(component_label.split()) <= 2:
                terminal_y = y + radius + 35
                terminals = ['U1', 'V1', 'W1']
                for i, term in enumerate(terminals):
                    term_x = x - 20 + (i * 20)
                    term_label = TextComponent(
                        app.canvas,
                        term,
                        8,
                        term_x, terminal_y,
                        color=text_color
                    )
                    app.text_components.append(term_label)

        elif 'roller' in type_lower or 'switch' in type_lower:
            # Soportar múltiples componentes Roller-Switch agrupados (Ej: "SW1 + SW2")
            rollers = [r.strip() for r in component_label.split('+') if r.strip()]
            num_rollers = len(rollers)

            width = 35
            height = 20

            if num_rollers == 1:
                # Dibujado estándar unico
                from models.shape import Rect
                switch_rect = Rect(x, y, width, height)
                switch_rect.outline = line_color
                switch_rect.outline_width = 2
                app.shape_manager.shapes.append(switch_rect)
                switch_rect.draw(app.canvas)
                switch_label = TextComponent(
                    app.canvas,
                    "SW",
                    10,
                    x, y,
                    color=text_color
                )
                app.text_components.append(switch_label)

                comp_name = TextComponent(
                    app.canvas,
                    rollers[0],
                    11,
                    x, y + height/2 + 15,
                    color=text_color
                )
                app.text_components.append(comp_name)
            else:
                # Comportamiento para Roller-Switches compartidos
                spacing = 50 # Espaciado horizontal entre símbolos
                total_width_needed = (num_rollers - 1) * spacing
                start_x = x - (total_width_needed / 2)

                from models.shape import Line, Rect
                h_cable = Line(
                    start_x, y - 25,
                    start_x + total_width_needed, y - 25
                )
                h_cable.width = 2
                h_cable.fill = line_color
                app.shape_manager.shapes.append(h_cable)
                h_cable.draw(app.canvas)

                for i, roller_name in enumerate(rollers):
                    rx = start_x + (i * spacing)

                    # Cable vertical hacia el símbolo
                    v_cable = Line(
                        rx, y - 25,
                        rx, y - height/2
                    )
                    v_cable.width = 2
                    v_cable.fill = line_color
                    app.shape_manager.shapes.append(v_cable)
                    v_cable.draw(app.canvas)

                    # Símbolo
                    switch_rect = Rect(rx, y, width, height)
                    switch_rect.outline = line_color
                    switch_rect.outline_width = 2
                    app.shape_manager.shapes.append(switch_rect)
                    switch_rect.draw(app.canvas)

                    switch_label = TextComponent(
                        app.canvas,
                        "SW",
                        10,
                        rx, y,
                        color=text_color
                    )
                    app.text_components.append(switch_label)

                    # Etiqueta individual
                    comp_name = TextComponent(
                        app.canvas,
                        roller_name,
                        11,
                        rx, y + height/2 + 15,
                        color=text_color
                    )
                    app.text_components.append(comp_name)

        elif 'electrovalv' in type_lower or 'selenoid' in type_lower or 'solenoid' in type_lower:
            # Electroválvula / solenoide externo: bobina con referencia (K22, ...)
            from models.shape import Rect
            width = 46
            height = 28
            coil_rect = Rect(x, y, width, height)
            coil_rect.outline = line_color
            coil_rect.outline_width = 2
            app.shape_manager.shapes.append(coil_rect)
            coil_rect.draw(app.canvas)

            # Símbolo de solenoide dentro del rectángulo
            solenoid_label = TextComponent(
                app.canvas,
                "YV",
                10,
                x, y,
                color=text_color
            )
            app.text_components.append(solenoid_label)

            # Referencia del dispositivo debajo (K22, K23, ...)
            comp_name = TextComponent(
                app.canvas,
                component_label,
                11,
                x, y + height/2 + 15,
                color=text_color
            )
            app.text_components.append(comp_name)

        elif 'presostato' in type_lower or 'pressostato' in type_lower or 'sensor' in type_lower:
            # Presostato / sensor de campo: contacto con su referencia (S3, ...)
            from models.shape import Rect
            width = 44
            height = 24
            sensor_rect = Rect(x, y, width, height)
            sensor_rect.outline = line_color
            sensor_rect.outline_width = 2
            app.shape_manager.shapes.append(sensor_rect)
            sensor_rect.draw(app.canvas)

            symbol_label = TextComponent(
                app.canvas,
                "PS",
                10,
                x, y,
                color=text_color
            )
            app.text_components.append(symbol_label)

            comp_name = TextComponent(
                app.canvas,
                component_label,
                11,
                x, y + height/2 + 15,
                color=text_color
            )
            app.text_components.append(comp_name)

        else:
            # Componente genérico: rectángulo con nombre
            width = 35
            height = 35
            from models.shape import Rect
            gen_rect = Rect(x, y, width, height)
            gen_rect.outline = line_color
            gen_rect.outline_width = 2
            app.shape_manager.shapes.append(gen_rect)
            gen_rect.draw(app.canvas)
            comp_name = TextComponent(
                app.canvas,
                component_label,
                10,
                x, y,
                color=text_color
            )
            app.text_components.append(comp_name)

    def refresh_current_sheet(self, app):
        """Regenera el contenido de la hoja actual (útil para redibujado)."""
        # 5. Limpiar contenido existente en la hoja
        app.canvas.delete("all")
        app.components.clear()
        app.connections.clear()
        app.text_components.clear()
        if hasattr(app, 'shape_manager'):
            app.shape_manager.shapes.clear()
        if hasattr(app, 'image_components'):
            app.image_components.clear()

        app.draw_grid(force=True)

        # 6. Recolectar datos
        all_borners = self._collect_all_borners_with_connections(app.project, app)

        # 7. Agrupar bornas
        grouped_borners = self._group_borners_by_component(all_borners)

        # 8. Dibujar Plano
        self._draw_borner_plan(app, grouped_borners)

    def _render_borner_svg(self, app, x, y, width, height, borner=None):
        """
        Renderiza el SVG borner-pdf.svg en la posición especificada.
        x, y son las coordenadas del CENTRO del símbolo.
        borner: Diccionario con información del borne (opcional, para detectar fase)
        """
        import os
        import io
        import re

        try:
            import cairosvg

            # Buscar el SVG (ruta absoluta)
            from utils.utils import get_app_dir
            base_svg_path = str(get_app_dir() / "svgs")
            if not os.path.exists(base_svg_path):
                base_svg_path = "svgs"

            svg_path = os.path.join(base_svg_path, "borner-pdf.svg")

            if not os.path.exists(svg_path):
                # Fallback: dibujar rectángulo
                from models.shape import Rect
                box = Rect(x, y, width, height)
                box.fill = "#cccccc"
                box.outline = "#000000"
                box.outline_width = 1
                app.shape_manager.shapes.append(box)
                box.draw(app.canvas)
                return

            # Leer el SVG como texto para modificar las capas
            with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()

            # ESTRATEGIA DE DETECCIÓN DE FASE ROBUSTA
            detected_phase = None

            # 1. Prioridad 1: Nombre del propio borne (ej: "X1:PE" o "PE")
            if borner and 'name' in borner:
                name_upper = str(borner['name']).upper()
                if 'PE' in name_upper:
                    detected_phase = 'PE'
                elif ' N' in name_upper or name_upper.endswith(':N') or name_upper == 'N':
                    detected_phase = 'N'

            # 2. Prioridad 2: Color de los cables (Entradas y Salidas)
            if not detected_phase and borner:
                all_conns = borner.get('entradas', []) + borner.get('salidas', [])
                for conn in all_conns:
                    color = str(conn.get('color', '')).lower()
                    if any(c in color for c in ['green', 'verde', 'gnye', '#90ee90', '#32cd32', '#008000']):
                        detected_phase = 'PE'
                        break
                    elif any(c in color for c in ['blue', 'azul', 'bu', '#87aade', '#0000ff']):
                        detected_phase = 'N'
                        # No break inmediato para permitir que PE gane si aparece después

            # 3. Prioridad 3: Nombres de los componentes conectados
            if not detected_phase and borner:
                all_conns = borner.get('entradas', []) + borner.get('salidas', [])
                for conn in all_conns:
                    nombre = str(conn.get('nombre', '')).upper().strip()
                    if nombre in ['PE', 'N', 'L1', 'L2', 'L3', 'TIERRA', 'GND', 'GROUND']:
                        detected_phase = nombre
                        if detected_phase == 'PE': break

            # Si el color base del borne ya es verde (asignado en recolección), forzar PE
            if not detected_phase and borner and borner.get('color') == '#90EE90':
                detected_phase = 'PE'

            # Normalizar alias de tierra a PE: un borne alimentado por un símbolo
            # TIERRA/GND/GROUND (p.ej. T.svg) es un terminal de protección y debe
            # activar la capa verde del SVG, no caer en la rama "otras fases".
            if detected_phase in ('TIERRA', 'GND', 'GROUND'):
                detected_phase = 'PE'

            # Activar capa PE o N según la fase detectada (Regex Ajustado)
            if detected_phase == 'PE':
                # Activar capa PE
                svg_content = re.sub(
                    r'(inkscape:label="PE"[^>]*?)style="display:none"',
                    r'\1style="display:inline"',
                    svg_content,
                    flags=re.IGNORECASE
                )
                # Asegurar que N esté desactivada
                svg_content = re.sub(
                    r'(inkscape:label="N"[^>]*?)style="display:inline"',
                    r'\1style="display:none"',
                    svg_content,
                    flags=re.IGNORECASE
                )
            elif detected_phase == 'N':
                # Activar capa N
                svg_content = re.sub(
                    r'(inkscape:label="N"[^>]*?)style="display:none"',
                    r'\1style="display:inline"',
                    svg_content,
                    flags=re.IGNORECASE
                )
                # Asegurar que PE esté desactivada
                svg_content = re.sub(
                    r'(inkscape:label="PE"[^>]*?)style="display:inline"',
                    r'\1style="display:none"',
                    svg_content,
                    flags=re.IGNORECASE
                )
            else:
                # Fases L1, L2, L3 u otras: Desactivar AMBAS capas decorativas
                # La base (Rect id="rect1") es el gris por defecto
                svg_content = re.sub(
                    r'(inkscape:label="PE"[^>]*?)style="display:inline"',
                    r'\1style="display:none"',
                    svg_content,
                    flags=re.IGNORECASE
                )
                svg_content = re.sub(
                    r'(inkscape:label="N"[^>]*?)style="display:inline"',
                    r'\1style="display:none"',
                    svg_content,
                    flags=re.IGNORECASE
                )

            # Convertir SVG modificado a PNG en memoria
            png_data = io.BytesIO()
            cairosvg.svg2png(bytestring=svg_content.encode('utf-8'), write_to=png_data, output_width=int(width), output_height=int(height))
            png_data.seek(0)

            # USAR ImageComponent para soporte de ZOOM
            from models.component import ImageComponent
            # Nota: ImageComponent necesita ruta de archivo, pero ya tenemos los datos en memoria.
            # Sin embargo, el sistema espera que ImageComponent recargue desde disco en draw().
            # Solución temporal: Guardar SVG modificado a un archivo temporal o usar ImageComponent adaptado.
            # Dado que borner-pdf.svg es estático pero sus capas cambian, usaremos un archivo temporal.
            tmp_path = _save_render_png(png_data.getvalue())

            img_comp = ImageComponent(app.canvas, tmp_path, x, y, size=[width, height])
            # Origen vectorial y fase detectada: permiten que el exportador DXF
            # dibuje la borna como SVG (borner-pdf.svg) en vez de raster.
            img_comp.source_svg = "borner-pdf.svg"
            img_comp.borner_phase = detected_phase
            if not hasattr(app, 'image_components'):
                app.image_components = []
            app.image_components.append(img_comp)
            img_comp.draw()

        except Exception as e:
            print(f"Error renderizando borner SVG: {e}")
            # Fallback
            from models.shape import Rect
            box = Rect(x, y, width, height)
            box.fill = "#cccccc"
            box.outline = "#000000"
            box.outline_width = 1
            app.shape_manager.shapes.append(box)
            box.draw(app.canvas)

class SafetySheetGenerator:
    """Generador de Hoja de Seguridad (Safety Sheet) con logo y textos profesionales."""

    def __init__(self, project):
        self.project = project

    def generate_safety_sheet(self, app):
        """Genera o actualiza la hoja de Prescripciones de Seguridad."""
        sheet_name = "Prescripciones de Seguridad"
        safety_sheet = None
        safety_index = -1

        for i, sheet in enumerate(app.project.sheets):
            if sheet.name == sheet_name:
                safety_sheet = sheet
                safety_index = i
                break

        if safety_index == -1: # Si no existe, crearla
            safety_sheet = app.project.add_sheet(sheet_name)
            safety_index = len(app.project.sheets) - 1

        app.switch_to_sheet(safety_index)

        app.canvas.delete("all")
        app.components.clear()
        app.connections.clear()
        app.text_components.clear()
        if hasattr(app, 'shape_manager'):
            app.shape_manager.shapes.clear()
        if hasattr(app, 'image_components'):
            app.image_components.clear()
        else:
            app.image_components = []

        app.draw_grid(force=True)

        # DIBUJAR MARCO Y LOGO
        from models.shape import Rect
        from models.component import ImageComponent

        # Logo del programa - buscar en múltiples ubicaciones
        from utils.utils import get_app_dir, get_resource_dir
        logo_paths = [
            str(get_resource_dir() / "logo-evaPr.png"),
            str(get_app_dir() / "logo-evaPr.png"),
            str(get_app_dir() / "svgs" / "logo-evaPr.png"),
        ]
        logo_path = None
        for path in logo_paths:
            if os.path.exists(path):
                logo_path = path
                break

        if logo_path:
            # Posicionar el logo dentro del marco del encabezado (a la derecha)
            logo = ImageComponent(app.canvas, logo_path, 1100, 60, size=[75, 75])
            app.image_components.append(logo)
            logo.draw()

        IS_DARK = app.is_dark_mode()
        TEXT_COLOR = "white" if IS_DARK else "black"
        LINE_COLOR = "white" if IS_DARK else "black"

        # 1. Título Pincipal
        header_rect = Rect(600, 60, 1100, 80)
        header_rect.outline = LINE_COLOR
        header_rect.outline_width = 1.5
        app.shape_manager.shapes.append(header_rect)
        header_rect.draw(app.canvas)

        title = TextComponent(app.canvas, "PRESCRIPCIONES DE SEGURIDAD", 18, 600, 60, color=TEXT_COLOR, anchor="e")
        app.text_components.append(title)

        # 2. Sección Generales
        # Cuadro grande de generales
        gen_rect = Rect(630, 480, 1180, 720)
        gen_rect.outline = LINE_COLOR
        gen_rect.outline_width = 1
        app.shape_manager.shapes.append(gen_rect)
        gen_rect.draw(app.canvas)

        # Recuadro del subtítulo (hoy: nota legal de exención de responsabilidad)
        sub_title_rect = Rect(590, 145, 1100, 45)
        sub_title_rect.outline = LINE_COLOR
        sub_title_rect.outline_width = 1
        app.shape_manager.shapes.append(sub_title_rect)
        sub_title_rect.draw(app.canvas)

        # Nota legal de exención de responsabilidad (antes: subtítulo de generales)
        _corte = DISCLAIMER_FOOTER.index("matriculado.") + len("matriculado.")
        _aviso = DISCLAIMER_FOOTER[:_corte] + "\n" + DISCLAIMER_FOOTER[_corte:].strip()
        sub_title = TextComponent(app.canvas, _aviso, 14, 60, 145, color=TEXT_COLOR, anchor="w")
        app.text_components.append(sub_title)

        # ICONO DE PELIGRO (USANDO SVG Warning.svg)
        tri_x, tri_y = 135, 275
        tri_size = 110

        # Renderizar el SVG Warning.svg en la posición del triángulo
        self._render_warning_svg(app, tri_x, tri_y, tri_size)

        danger_text = TextComponent(app.canvas, "¡ PELIGRO !", 14, tri_x, tri_y + 70, color=TEXT_COLOR)
        app.text_components.append(danger_text)

        # TEXTO DE ADVERTENCIA
        adv_texts = [
            "Las dimensiones, selecciones de componentes y recomendaciones generadas por evaPR son sugerencias basadas en estánda-",
            "res comunes. El Profesional eléctrico responsable del proyecto debe verificar y validar todos los cálculos y selecciones",
            "finales. evaPR no sustituye el criterio profesional ni la revisión detallada del diseño.",
            "Durante el funcionamiento de la instalación, hay ciertos ítems con tensiones peligrosas. La inobservancia de las indicaciones",
            "de seguridad puede causar la muerte,lesiones graves y daños materiales.",
            "Solo personal cualificado debe ejecutar los trabajos de transporte, instalación y puesta en marcha. Se deben observar las nor-",
            "mas vigentes, así como las prescripciones de prevención de accidentes nacionales y / o propias de la empresa."
        ]

        y_pos = 225
        for line in adv_texts:
            t = TextComponent(app.canvas, line, 14, 220, y_pos, color=TEXT_COLOR, anchor="w")
            app.text_components.append(t)
            y_pos += 24

        # LISTA DE INDICACIONES (BULLET POINTS)
        y_pos += 30
        intro_list = TextComponent(app.canvas, "Deben respetarse las siguientes indicaciones de seguridad:", 14, 60, y_pos, color=TEXT_COLOR, anchor="w")
        app.text_components.append(intro_list)
        y_pos += 30

        bullet_points = [
            "        -La operaciones de montaje, puesta en marcha, detección de averías y reparación de la instalación  solo  puede llevarlas a  cabo  el personal",
                     "con una formación adecuada y familiarizado con los correspondientes manuales de uso.",
            "",
            "        -El montaje de los dispositivos debe efectuarse según las normas vigentes y las prescripciones estatales y locales.",
            "        -Debe garantizarse una puesta a tierra y un dimensionamiento de los conductores correctos, así como una protección adecuada contra cortocircuitos.",
            "        -Estas medidas sirven para garantizar la seguridad de la instalación y de los operadores.",
            "",
            "        -Antes de realizar comprobaciones de seguridad y tomar medidas de mantenimiento y reparación debe garantizarse que todas las fuentes de alimenta-",
            "         tación estén desconectadas, aseguradas contra una reconexión y debidamente identificadas.",
            "        -Para realizar las mediciones, solo deben utilizarse equipos de comprobación en perfecto estado técnico y adecuados para cada medición en cuestión.",
            "",
            "        -Deben seguirse exactamente las instrucciones que se indican en los correspondientes manuales.",
            "        -Es obligatorio observar las indicaciones de seguridad, advertencia y peligro.",
            "        -Todas las puertas y los elementos protectores de la instalación deben mantenerse cerrados durante el funcionamiento.",
            "        -Si en la instalación se han montado refrigeradores, debe procurarse  que  esos sistemas funcionen correctamente.",
            "        -Esto contempla también la limpieza regular de los filtros si los hay."
        ]

        for line in bullet_points:
            # Alinear a la izquierda con anchor="w"
            t = TextComponent(app.canvas, line, 14, 60, y_pos, color=TEXT_COLOR, anchor="w")
            app.text_components.append(t)
            y_pos += 24

        app.save_undo_checkpoint()

    def _render_warning_svg(self, app, x, y, size):
        """
        Renderiza el SVG Warning.svg en la posición especificada.
        x, y son las coordenadas del CENTRO del símbolo.
        size: tamaño del icono (ancho y alto).
        """
        import os
        import io

        try:
            import cairosvg

            # Buscar el SVG Warning.svg
            # Primero intentar en la ruta relativa al archivo reports.py
            from utils.utils import get_app_dir
            svg_path = str(get_app_dir() / "svgs" / "Warning.svg")

            if not os.path.exists(svg_path):
                # Fallback: dibujar rectángulo
                from models.shape import Rect
                box = Rect(x, y, size, size)
                box.fill = "#ffcc00"
                line_color = "white" if app.is_dark_mode() else "black"
                box.outline = line_color
                box.outline_width = 2
                app.shape_manager.shapes.append(box)
                box.draw(app.canvas)
                return

            # Leer el SVG
            with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()

            # Convertir SVG a PNG en memoria
            png_data = io.BytesIO()
            cairosvg.svg2png(
                bytestring=svg_content.encode('utf-8'),
                write_to=png_data,
                output_width=int(size),
                output_height=int(size)
            )
            png_data.seek(0)

            # USAR ImageComponent para soporte de ZOOM
            from models.component import ImageComponent
            tmp_path = _save_render_png(png_data.getvalue())

            img_comp = ImageComponent(app.canvas, tmp_path, x, y, size=[size, size])
            # Conservar el origen vectorial para que las exportaciones que no
            # admiten el PNG temporal (como DXF) puedan reconstruir el símbolo.
            img_comp.source_svg = "Warning.svg"
            if not hasattr(app, 'image_components'):
                app.image_components = []
            app.image_components.append(img_comp)
            img_comp.draw()

        except Exception as e:
            print(f"Error renderizando Warning.svg: {e}")
            # Fallback: dibujar rectángulo
            from models.shape import Rect
            box = Rect(x, y, size, size)
            box.fill = "#ffcc00"
            box.outline = "#000000"
            box.outline_width = 2
            app.shape_manager.shapes.append(box)
            box.draw(app.canvas)

def _unifilar_build_obstacles(app):
    """Rectángulos de los componentes (no uniones/símbolos) para que el rutado
    del unifilar no atraviese por el interior de una caja de componente."""
    rects = []
    for c in app.components:
        if getattr(c, 'component_type', '') in ('junction', 'conxn', 'conxn2'):
            continue
        pad = 2
        rects.append((c.x - pad, c.y - pad, c.x + c.size[0] + pad, c.y + c.size[1] + pad))
    return rects

def _unifilar_route(sx, sy, ex, ey, rects):
    """Ruta ortogonal entre dos puntos evitando el interior de los rectángulos
    dados. Trabaja sobre las columnas y filas definidas por los extremos y los
    bordes de los obstáculos, con búsqueda A*. Devuelve la lista de puntos o
    None si no hay camino."""
    try:
        sx, sy, ex, ey = float(sx), float(sy), float(ex), float(ey)
    except Exception:
        return None

    xs = sorted({sx, ex} | {r[0] for r in rects} | {r[2] for r in rects})
    ys = sorted({sy, ey} | {r[1] for r in rects} | {r[3] for r in rects})

    def strict(x, y):
        for (ox, oy, ox2, oy2) in rects:
            if ox < x < ox2 and oy < y < oy2:
                return True
        return False

    def h_open(y, x1, x2):
        lo, hi = min(x1, x2), max(x1, x2)
        for (ox, oy, ox2, oy2) in rects:
            if oy < y < oy2 and ox < hi and lo < ox2:
                return False
        return True

    def v_open(x, y1, y2):
        lo, hi = min(y1, y2), max(y1, y2)
        for (ox, oy, ox2, oy2) in rects:
            if ox < x < ox2 and oy < hi and lo < oy2:
                return False
        return True

    goal = (ex, ey)
    if abs(sx - ex) < 0.5 and abs(sy - ey) < 0.5:
        return [goal]

    import heapq
    start = (sx, sy)
    open_heap = [(0.0, 0, start)]
    gscore = {start: 0.0}
    prev = {}
    visited = set()
    while open_heap:
        f, g, node = heapq.heappop(open_heap)
        if node in visited:
            continue
        visited.add(node)
        if node == goal:
            path = [node]
            while node in prev:
                node = prev[node]
                path.append(node)
            path.reverse()
            return path
        nx, ny = node
        for cx in xs:
            if abs(cx - nx) < 0.01:
                continue
            if not h_open(ny, nx, cx):
                continue
            nb = (cx, ny)
            if strict(*nb):
                continue
            ng = g + abs(cx - nx)
            if ng < gscore.get(nb, float('inf')):
                gscore[nb] = ng
                prev[nb] = node
                heapq.heappush(open_heap, (ng + abs(cx - ex) + abs(ny - ey), ng, nb))
        for cy in ys:
            if abs(cy - ny) < 0.01:
                continue
            if not v_open(nx, ny, cy):
                continue
            nb = (nx, cy)
            if strict(*nb):
                continue
            ng = g + abs(cy - ny)
            if ng < gscore.get(nb, float('inf')):
                gscore[nb] = ng
                prev[nb] = node
                heapq.heappush(open_heap, (ng + abs(nx - ex) + abs(cy - ey), ng, nb))
    return None

class UnifilarGenerator:
    # Mapeo de componentes multifilares a sus equivalentes unifilares: (svg_file, category)
    COMPONENT_MAPPING = {
        # PROTECCIONES (se mantienen en Protection si existen ahí)
        "circuit-breaker-3p-magnetic.svg": ("switch.svg", "unifilar"),
        "circuit-breaker-2p-magnetic.svg": ("switch.svg", "unifilar"),
        "circuit-breaker-thermal-magnetic-3p.svg": ("switch.svg", "unifilar"),
        "circuit-breaker-thermal-magnetic-2p.svg": ("switch.svg", "unifilar"),
        "motor-circuit-breaker-3p.svg": ("switch.svg", "unifilar"),
        "motor-circuit-breaker-2p.svg": ("switch.svg", "unifilar"),
        "fuse-switch-disconnector-3p.svg": ("fuse-switch-1p.svg", "Protection"),
        "fuse-switch-disconnector-2p.svg": ("fuse-switch-1p.svg", "Protection"),
        "switch diferencial-3p.svg": ("switch.svg", "unifilar"),

        # RELÉS TÉRMICOS (En la carpeta unifilar)
        "rele-thermal-overload-3.svg": ("rele-thermal.svg", "unifilar"),
        "rele-thermal.svg": ("rele-thermal.svg", "unifilar"),

        "Contactor-3p-auto.svg": ("Contactor-1p-auto.svg", "Protection"),
        "contactor-3p.svg": ("Contactor-1p-auto.svg", "Protection"),
        "contactor-3p-automatic-tripping.svg": ("Contactor-1p-auto.svg", "Protection"),
        "selector-3.svg": ("selector.svg", "unifilar"),

        # MOTORES Y DOSIFICADORAS (Carpeta unifilar o motors)
        "motor-3p.svg": ("motor.svg", "unifilar"),
        "motor-3pT.svg": ("motor.svg", "unifilar"),
        "motor-1pC.svg": ("motor.svg", "unifilar"),
        "motor-3p-ST.svg": ("motor.svg", "unifilar"),
        "motor-1p.svg": ("motor.svg", "unifilar"),  # Forzar al de la carpeta unifilar para estética
        "motor-1p-dosi.svg": ("motorD.svg", "unifilar"),  # hipotético

        "POWER_SUPPLY_DC.svg": ("POWER_SUPPLY.svg", "unifilar"),
        "POWER_SUPPLY_AC.svg": ("POWER_SUPPLY.svg", "unifilar"),

        "borner-3.svg": ("borner-1.svg", "Connection"),
        "borner-2.svg": ("borner-1.svg", "Connection"),
        "borner-4.svg": ("borner-1.svg", "Connection"),
        # Borneras con conexión tipo clavija: su símbolo unifilar propio.
        "borner-3-clavija.svg": ("borner-clavija.svg", "unifilar"),
        "borner-1-clavija.svg": ("borner-clavija.svg", "unifilar"),
    }

    def __init__(self, project):
        self.project = project

    def _route_unifilar_connection(self, app, conn, extra_rects=None):
        """Rutado ortogonal del unifilar evitando que los tramos crucen por el
        interior de los componentes (sólo los extremos del propio hilo se
        exceptúan, porque salen/entran legítimamente de su caja). extra_rects
        permite sumar obstáculos temporales (p.ej. el stub comp->nudo) para que
        un tramo no se pinte dos veces sobre la misma columna. Si no se encuentra
        ruta sin obstáculos, se usa el router estándar."""
        try:
            sp = conn.start_component.get_connection_points_global()[conn.start_point_idx]
            ep = conn.end_component.get_connection_points_global()[conn.end_point_idx]
            sx, sy = sp[0], sp[1]
            ex, ey = ep[0], ep[1]
            rects = _unifilar_build_obstacles(app)
            if extra_rects:
                rects = rects + list(extra_rects)

            def strictly(r, x, y):
                return r[0] < x < r[2] and r[1] < y < r[3]

            def _carve(r, px, py, gap):
                """Parte un corredor en dos dejando una ventana libre de 'gap'
                alrededor de (px, py). Devuelve los sub-rectángulos válidos."""
                x1, y1, x2, y2 = r
                out = []
                if (x2 - x1) > (y2 - y1):
                    if px - gap > x1:
                        out.append((x1, y1, px - gap, y2))
                    if px + gap < x2:
                        out.append((px + gap, y1, x2, y2))
                else:
                    if py - gap > y1:
                        out.append((x1, y1, x2, py - gap))
                    if py + gap < y2:
                        out.append((x1, py + gap, x2, y2))
                return out

            # Corredores quirúrgicos: si este hilo termina en una unión real (no
            # un nudo de abanico), las aristas previas que llegan a ESA unión ya
            # pintaron su columna. Se evita apilarse encima dejando únicamente la
            # ventana (5px) del propio borne. Así no salen 'dos líneas de fase'
            # colineales hacia la misma unión.
            try:
                ep_comp = conn.end_component
                if (getattr(ep_comp, 'component_type', '') in ('junction', 'conxn', 'conxn2')
                        and not str(getattr(ep_comp, 'name', '') or '').startswith('J-')):
                    for c2 in app.connections:
                        if c2 is conn:
                            continue
                        if c2.end_component is not ep_comp and c2.start_component is not ep_comp:
                            continue
                        for (x1, y1), (x2, y2) in getattr(c2, 'segments', []) or []:
                            if abs(x1 - x2) < 0.01:
                                r = (x1 - 3, min(y1, y2), x1 + 3, max(y1, y2))
                            elif abs(y1 - y2) < 0.01:
                                r = (min(x1, x2), y1 - 3, max(x1, x2), y1 + 3)
                            else:
                                continue
                            rects.extend(_carve(r, ex, ey, 5))
            except Exception:
                pass

            rects = [r for r in rects if not (strictly(r, sx, sy) or strictly(r, ex, ey))]
            path = _unifilar_route(sx, sy, ex, ey, rects)
            if not path:
                app.update_manhattan_line(conn)
                return
            conn.segments = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
            conn.manually_modified = True
            app._redraw_connection_fast(conn)
        except Exception:
            try:
                app.update_manhattan_line(conn)
            except Exception:
                pass

    def generate_unifilar_sheet(self, app):
        """
        Genera una nueva hoja con el plano unifilar basado en la hoja activa actual.
        """
        import logging
        logging.basicConfig(filename='/tmp/unifilar_debug.log', level=logging.DEBUG,
                            format='%(asctime)s - %(levelname)s - %(message)s')

        source_sheet = app.project.get_active_sheet()
        if not source_sheet:
            return False

        sheet_name = f"Plano Unifilar - {source_sheet.name}"

        # Buscar si ya existe la hoja para sobrescribirla o crear una nueva
        unifilar_sheet = None
        unifilar_index = -1

        for i, sheet in enumerate(app.project.sheets):
            if sheet.name == sheet_name:
                unifilar_sheet = sheet
                unifilar_index = i
                break

        if not unifilar_sheet:
            unifilar_sheet = app.project.add_sheet(sheet_name)
            unifilar_index = len(app.project.sheets) - 1

        app.switch_to_sheet(unifilar_index)

        app.canvas.delete("all")
        app.components.clear()
        app.connections.clear()
        app.text_components.clear()
        if hasattr(app, 'shape_manager'):
            app.shape_manager.shapes.clear()

        app.draw_grid(force=True)

        comp_map = {}

        # ALGORITMO DE LIMPIEZA UNIFILAR
        # Un plano unifilar ("un solo hilo") NO muestra los símbolos de L2, L3,
        # N ni el bus de PE: se filtran por su nombre (o por el de su etiqueta).
        # Eso se hacía también filtrando por coordenada Y de fila, pero la limpieza
        # por Y borraba uniones que el unifilar necesita: al girar L1 comparte Y
        # con L2/L3 y, en hojas multifilares, los nodos de reparto de las cargas
        # caen en la fila de un conductor secundario (p.ej. el neutro), con lo que
        # las ramas se quedaban sin hilo o se partían en grupos sueltos.
        # Las filas secundarias se colapsan solas al fusionar los nodos cercanos
        # (J_X_TOL/J_Y_TOL), lo que además reencabla sus conexiones.
        def _source_phase_name(elem):
            """Obtiene el potencial de una fase tanto de su nombre como de su
            etiqueta guardada (los proyectos antiguos pueden usar cualquiera)."""
            if not isinstance(elem, dict):
                return ''
            label_data = elem.get('label_data') or {}
            label_name = label_data.get('name', '') if isinstance(label_data, dict) else ''
            return str(label_name or elem.get('name') or '').upper().strip()

        src_elems = [e for e in getattr(source_sheet, 'elements', []) if isinstance(e, dict)]
        src_conns = [c for c in getattr(source_sheet, 'connections', []) if isinstance(c, dict)]

        neighbours = defaultdict(list)
        for _c in src_conns:
            _a, _b = _c.get('start_component_idx'), _c.get('end_component_idx')
            if (isinstance(_a, int) and isinstance(_b, int)
                    and 0 <= _a < len(src_elems) and 0 <= _b < len(src_elems)):
                neighbours[_a].append(_b)
                neighbours[_b].append(_a)

        accepted_bornas_coords = []

        def get_unifilar_svg(elem):
            orig_svg_raw = elem.get('svg_file') or ''
            orig_svg = orig_svg_raw.lower()
            orig_cat = (elem.get('category') or '')
            safe_name = (elem.get('name') or '').lower()

            # Revisar TODOS los nombres posibles de etiqueta del componente.
            # El texto "loto" puede venir en name, label_data['name'], description o label_data['descripcion'].
            label_candidates = []
            for key in ['name', 'description', 'descripcion', 'text']:
                value = elem.get(key)
                if value is not None:
                    if isinstance(value, dict):
                        label_candidates.extend(str(v) for v in value.values())
                    else:
                        label_candidates.append(str(value))

            label_data = elem.get('label_data') or {}
            if isinstance(label_data, dict):
                for key in ['name', 'description', 'descripcion', 'text']:
                    value = label_data.get(key)
                    if value is not None:
                        if isinstance(value, dict):
                            label_candidates.extend(str(v) for v in value.values())
                        else:
                            label_candidates.append(str(value))

            combined_name = ' '.join([safe_name, *label_candidates, orig_svg, str(orig_cat)]).lower()

            # Prioridad 1: Reglas específicas por nombre/categoría
            if 'dosificadora' in safe_name or 'dosi' in orig_svg:
                return ('motorD.svg', 'unifilar')

            # el símbolo LOTO solo se usa si la etiqueta o nombre contiene
            # la palabra literal 'loto' (ej. 'LOTO SWITCH', 'LOTO', etc.).
            # No debe activarse por ser breaker o por un nombre fijo como S0.
            # Acepta ambas grafías: 'loto' y 'lotto'.
            if 'loto' in combined_name or 'lotto' in combined_name:
                return ('loto.svg', 'unifilar')

            # Prioridad 2: Relés térmicos explícitos: deben respetar su símbolo unifilar
            # aunque también se identifiquen como protecciones por el nombre o la descripción.
            if any(token in combined_name for token in ['rele-thermal', 'rele termico', 'relé térmico', 'thermal overload', 'relé térmico', 'thermal-overload']):
                return ('rele-thermal.svg', 'unifilar')

            # Prioridad 3: Detección robusta de Protecciones (Breakers, Magnetotérmicos, etc.)
            protection_keywords = ['breaker', 'magnetic', 'thermal', 'magnetotermico', 'disyuntor', 'termico', 'magnetotermico']
            is_protection = any(kw in orig_svg for kw in protection_keywords) or any(kw in combined_name for kw in protection_keywords)

            # Excluir explícitamente los reles térmicos para usar su propio símbolo unifilar
            if is_protection and 'rele' not in combined_name and 'relay' not in combined_name:
                return ('switch.svg', 'unifilar')

            # Prioridad 4: Búsqueda exacta en el mapeo estático
            if orig_svg_raw in self.COMPONENT_MAPPING:
                return self.COMPONENT_MAPPING[orig_svg_raw]

            # Prioridad 4: Búsqueda case-insensitive
            for key, val in self.COMPONENT_MAPPING.items():
                if key.lower() == orig_svg:
                    return val

            # Fallback
            return (orig_svg_raw, orig_cat)

        # Registra las posiciones donde ya se instanció cada tipo de símbolo unifilar.
        # Clave: svg_unifilar | Valor: lista de (x, y, componente) ya colocados
        placed_by_type = {}
        # Tolerancias por tipo:
        # Uniones (svg ''): |dx|<50 Y |dy|<100. En unifilar las 3 fases (L1/L2/L3) de un
        #   ramal comparten columna X pero se apilan en Y (25/45/65...), así que deben
        #   fusionarse; pero el bus de fase (arriba) y el de neutro (abajo) comparten
        #   columna y NO deben fusionarse porque su diferencia de Y es grande.
        # Componentes: solo si están casi coincidentes (|dx|<50 Y |dy|<15), para NO
        #   fusionar dispositivos idénticos apilados en la misma columna ni los saltos
        #   (conxn) que comparten columna (p.ej. los 4 saltos de salida de hoja).
        J_X_TOL, J_Y_TOL = 50, 100
        C_X_TOL, C_Y_TOL = 50, 15

        for elem in getattr(source_sheet, 'elements', []):
            if not isinstance(elem, dict) or elem.get('type') not in ['component', 'junction']:
                continue

            x = elem.get('x', 50)
            y = elem.get('y', 50)

            name = elem.get('name') or 'Unknown'
            # El potencial puede vivir únicamente en label_data (fase.svg y los
            # conxn de bus): se usa para decidir si pertenece a un bus, pero el
            # nombre visible del elemento NO se reescribe.
            name_u = (_source_phase_name(elem) or name).upper().strip()
            if (name_u in ("L2", "L3", "L4", "N", "PE", "NEUTRO", "TIERRA")
                    or re.match(r'^(L2|L3|L4|N|PE|NEUTRO|TIERRA)([_\-\s].*)?$', name_u)):
                continue

            safe_svg = (elem.get('svg_file') or '').lower()
            size = elem.get('size')
            label_data = elem.get('label_data', {}).copy()

            # Bornas: una por celda de 60px
            if 'borner' in safe_svg:
                if any(abs(x - bx) < 60 and abs(y - by) < 60 for bx, by in accepted_bornas_coords):
                    continue
                accepted_bornas_coords.append((x, y))

            unifilar_svg, unifilar_cat = get_unifilar_svg(elem)

            # DEDUPLICACIÓN POR TIPO + POSICIÓN (X e Y):
            # Si ya existe un componente de este mismo tipo en una posición cercana,
            # NO instanciar otro — redirigir sus conexiones al que ya existe.
            is_junc = elem.get('type') == 'junction'
            xtol = J_X_TOL if is_junc else C_X_TOL
            ytol = J_Y_TOL if is_junc else C_Y_TOL
            placed_list = placed_by_type.get(unifilar_svg, [])
            existing = next(((px, py, comp) for (px, py, comp) in placed_list
                             if abs(px - x) < xtol and abs(py - y) < ytol), None)
            if existing:
                # Alias: las conexiones de este elem apuntan al componente ya dibujado
                comp_map[id(elem)] = existing[2]
                continue

            unifilar_svg, unifilar_cat = get_unifilar_svg(elem)

            if elem.get('type') == 'junction':
                from models.junction_component import JunctionComponent
                new_comp = JunctionComponent.from_dict(app.canvas, elem, app.config)
            else:
                from models.component import Component
                # Normalizar categoría a minúsculas para rutas Linux (case-sensitive)
                unifilar_cat_norm = (unifilar_cat or "").lower()
                try:
                    real_size = app.get_component_real_size(unifilar_svg, unifilar_cat_norm)
                except Exception:
                    real_size = size
                new_comp = Component(
                    app.canvas, unifilar_svg, name, real_size, x, y,
                    app.config.get("svg_path", ""), unifilar_cat_norm, app.config
                )

            app.components.append(new_comp)
            if new_comp:
                new_comp.draw()
                new_comp.label_data.update(label_data)
                # El nombre siempre debe quedar visible SIN tener que mover el
                # componente: si la fuente no trae 'name' en label_data se usa
                # el nombre del elemento (o la sugerencia del constructor).
                if not (new_comp.label_data.get('name') or '').strip():
                    new_comp.label_data['name'] = name
                # El unifilar usa la geometría de los terminales para formar
                # las conexiones. Sin esta rotación, una fase girada conserva
                # el punto de conexión de su orientación original y puede
                # parecer ausente o quedar desconectada en el plano generado.
                if getattr(new_comp, 'component_type', '') == 'fase':
                    new_comp.rotation = int(elem.get('rotation', 0) or 0) % 360
                    new_comp.draw()
                try:
                    new_comp.draw_label()
                except Exception:
                    pass
                comp_map[id(elem)] = new_comp
                # Registrar posición para deduplicar futuros componentes del mismo tipo
                if unifilar_svg not in placed_by_type:
                    placed_by_type[unifilar_svg] = []
                placed_by_type[unifilar_svg].append((x, y, new_comp))

        processed_pairs = set()

        def _device_orientation(comp):
            """Determina la orientación del dispositivo por la geometría real de
            sus puntos de conexión: 'v' (apilados en vertical), 'h' (al lado) o
            None (puntos coincidentes/unión, usar dirección global)."""
            try:
                pts = comp.get_connection_points_global()
            except Exception:
                return None
            if not pts or len(pts) < 2:
                return None
            x0, y0 = pts[0][0], pts[0][1]
            x1, y1 = pts[1][0], pts[1][1]
            dx = abs(x0 - x1)
            dy = abs(y0 - y1)
            if dy > dx:
                return 'v'
            if dx > dy:
                return 'h'
            return None

        def _pick_end_point(comp, other_x, other_y, direction):
            """Elige el punto de conexión del dispositivo según su propia
            orientación: en un dispositivo vertical arriba=punto0/abajo=punto1,
            en uno horizontal izquierda=punto0/derecha=punto1. Si no se puede
            determinar la orientación se usa la dirección global de la conexión."""
            if len(getattr(comp, 'conn_points', [])) <= 1:
                return 0
            orient = _device_orientation(comp)
            if orient == 'v':
                return 0 if other_y <= getattr(comp, 'y', other_y) else 1
            if orient == 'h':
                return 0 if other_x <= getattr(comp, 'x', other_x) else 1
            # Fallback: dirección global (unión o puntos coincidentes)
            if direction == 'horizontal':
                return 0 if other_x <= getattr(comp, 'x', other_x) else 1
            return 0 if other_y <= getattr(comp, 'y', other_y) else 1

        # SISTEMA DE ASIGNACIÓN DE PUNTOS POR DIRECCIÓN
        # Los componentes unifilares tienen 2 puntos de conexión:
        # Borneo/dispositivo vertical: punto 0 (arriba) y punto 1 (abajo)
        # Dispositivo horizontal: punto 0 (izquierda) y punto 1 (derecha)
        # La selección del punto se basa en la DIRECCIÓN de la conexión respecto
        # al propio dispositivo (no al par fuente/destino), para que a un mismo
        # punto no le caigan hilos que en realidad entran por arriba y salen por
        # abajo (p.ej. el retorno del neutro de una bobina vs. su alimentación).

        for conn_data in getattr(source_sheet, 'connections', []):
            if not isinstance(conn_data, dict):
                continue

            try:
                start_comp_dict = source_sheet.elements[conn_data['start_component_idx']]
                end_comp_dict = source_sheet.elements[conn_data['end_component_idx']]

                new_start = comp_map.get(id(start_comp_dict))
                new_end = comp_map.get(id(end_comp_dict))

                if new_start and new_end and new_start is not new_end:
                    from models.connection import Connection

                    # DEDUPLICACIÓN POR DESTINO UNIFILAR:
                    # Usar los ids de los componentes YA INSTANCIADOS en el unifilar,
                    # no los de la fuente multifilar. Así L1, L2, L3 -> misma línea.
                    pair_key = tuple(sorted((id(new_start), id(new_end))))
                    if pair_key in processed_pairs:
                        continue
                    processed_pairs.add(pair_key)

                    # DETERMINAR DIRECCIÓN DE LA CONEXIÓN:
                    # Basado en la diferencia de posición entre los componentes originales
                    start_x = start_comp_dict.get('x', 0)
                    start_y = start_comp_dict.get('y', 0)
                    end_x = end_comp_dict.get('x', 0)
                    end_y = end_comp_dict.get('y', 0)

                    dx = abs(end_x - start_x)
                    dy = abs(end_y - start_y)

                    # Dirección dominante global (solo para el fallback)
                    direction = 'horizontal' if dx >= dy else 'vertical'

                    # ASIGNACIÓN DE PUNTOS POR ORIENTACIÓN DEL DISPOSITIVO:
                    # Cada extremo usa el punto de conexión que corresponde a la
                    # cara del propio dispositivo por la que llega el hilo.
                    start_point_idx = _pick_end_point(new_start, end_x, end_y, direction)
                    end_point_idx = _pick_end_point(new_end, start_x, start_y, direction)

                    new_conn = Connection(new_start, start_point_idx, new_end, end_point_idx)
                    IS_DARK = app.is_dark_mode()
                    new_conn.line_color = "white" if IS_DARK else "black"
                    new_conn.line_width = 2  # grosor de la línea unifilar
                    app.connections.append(new_conn)
                    self._route_unifilar_connection(app, new_conn)
            except Exception as e:
                logging.error(f"Error procesando conexión: {e}")

        # LIMPIEZA DE "MÁS DE UN HILO" EN UN MISMO PUNTO
        # Si un punto de conexión de un componente (no unión) recibe varias
        # conexiones y una de ellas termina en un componente HOJA (grado 1 en el
        # grafo del unifilar), esa rama es un resto muerto: p.ej. el lado de
        # neutro de un motor cuya bornera quedó conectada únicamente al motor
        # porque su bus de neutro se filtró (banda del neutro). Se descarta esa
        # conexión para que al componente sólo le llegue el hilo de alimentación.
        degree = defaultdict(int)
        for conn in app.connections:
            degree[id(conn.start_component)] += 1
            degree[id(conn.end_component)] += 1

        per_point = defaultdict(list)
        for conn in app.connections:
            per_point[(id(conn.start_component), conn.start_point_idx)].append(conn)
            per_point[(id(conn.end_component), conn.end_point_idx)].append(conn)

        junction_types = ('junction', 'conxn', 'conxn2')
        drop_conns = set()

        # RAMAS DEL LADO DEL NEUTRO (rail N/NEUTRO nombrado en la fuente)
        # En diagramas donde existen elementos nombrados N/NEUTRO (p.ej. el plano
        # FUERZA), el retorno por neutro de una carga se dibujaría como un 2º hilo
        # entrando a la misma carga. Por convención del unifilar, a la carga sólo
        # llega el hilo de fase y el lado N queda en el rail. Se detectan por BFS
        # (profundidad acotada) los elementos que cuelgan del rail N y se descarta
        # la conexión redundante de la carga con ese lado.
        rail_comp_ids = None
        rail_names = ('N', 'NEUTRO', 'NEUTRAL')
        seed_ids = []
        src_elems = getattr(source_sheet, 'elements', [])
        conns_src = getattr(source_sheet, 'connections', [])
        if any((str(e.get('name') or '').upper() in rail_names) for e in src_elems
               if isinstance(e, dict) and e.get('type') == 'component'):
            adj = defaultdict(list)
            elem_idx_ids = {}
            transparent = {}
            for i, e in enumerate(src_elems):
                if isinstance(e, dict):
                    elem_idx_ids[i] = id(e)
                    svg = (e.get('svg_file') or '').lower()
                    transparent[i] = (e.get('type') == 'junction' or 'borner' in svg)
            for c in conns_src:
                if not isinstance(c, dict):
                    continue
                a, b = c.get('start_component_idx'), c.get('end_component_idx')
                if a in elem_idx_ids and b in elem_idx_ids:
                    adj[a].append(b)
                    adj[b].append(a)
            for i, e in enumerate(src_elems):
                if isinstance(e, dict) and str(e.get('name') or '').upper() in rail_names:
                    seed_ids.append(i)
            if seed_ids:
                # BFS limitado a nodos "transparentes al rail" (uniones y bornas):
                # no cruza motores/breakers, así el lado de fase no se contamina.
                rail_idx = set(seed_ids)
                frontier = list(seed_ids)
                for _ in range(4):
                    nxt = []
                    for node in frontier:
                        for nb in adj.get(node, []):
                            # Se expande sólo hacia nodos transparentes (uniones/bornas):
                            # no cruza motores/breakers, así el lado de fase no se contamina.
                            if nb not in rail_idx and transparent.get(nb):
                                rail_idx.add(nb)
                                nxt.append(nb)
                    frontier = nxt
                    if not frontier:
                        break
                rail_comp_ids = {id(comp_map.get(elem_idx_ids[i])) for i in rail_idx if i in elem_idx_ids}
                rail_comp_ids.discard(None)

        for comp in app.components:
            if getattr(comp, 'component_type', '') in junction_types:
                continue
            npts = max(1, len(getattr(comp, 'conn_points', [])))
            for p in range(npts):
                conns_at_point = per_point.get((id(comp), p), [])
                if len(conns_at_point) <= 1:
                    continue
                for conn in conns_at_point:
                    other = conn.end_component if conn.start_component is comp else conn.start_component
                    if (getattr(other, 'component_type', '') not in junction_types
                            and degree.get(id(other), 0) == 1):
                        drop_conns.add(id(conn))
                        continue
                    # Si el otro extremo cuelga del rail de neutro, es el retorno
                    # redundante: se descarta quedándose sólo con el hilo de fase.
                    if rail_comp_ids and id(other) in rail_comp_ids:
                        drop_conns.add(id(conn))

        if drop_conns:
            # SEGURIDAD ANTI-ÓRFANO
            # La limpieza anterior puede marcar TODAS las conexiones de una carga
            # (p.ej. cuando el BFS del rail de neutro alcanza también el borner
            # de fase de un motor-3pT). Eso apagaría el motor entero. Se reincorpora
            # una conexión a cada carga que quedaría sin ningún hilo, priorizando
            # la que NO cuelga del rail de neutro (queda el hilo de fase -> alimentada).
            changed = True
            while changed:
                changed = False
                remaining = defaultdict(int)
                for conn in app.connections:
                    if id(conn) in drop_conns:
                        continue
                    remaining[id(conn.start_component)] += 1
                    remaining[id(conn.end_component)] += 1
                rail_ids = rail_comp_ids or set()
                for comp in list(app.components):
                    if getattr(comp, 'component_type', '') in junction_types:
                        continue
                    if getattr(comp, 'component_type', '') == 'fase':
                        continue
                    if remaining.get(id(comp), 0) > 0:
                        continue
                    cands = [c for c in app.connections
                             if id(c) in drop_conns
                             and (c.start_component is comp or c.end_component is comp)]
                    if not cands:
                        continue
                    cands.sort(key=lambda c: 1 if (
                        id(c.start_component) in rail_ids
                        or id(c.end_component) in rail_ids) else 0)
                    keep = cands[0]
                    drop_conns.discard(id(keep))
                    changed = True

            dropped = [c for c in app.connections if id(c) in drop_conns]
            app.connections = [c for c in app.connections if id(c) not in drop_conns]
            for conn in dropped:
                for lid in getattr(conn, 'line_ids', []):
                    try:
                        app.canvas.delete(lid)
                    except Exception:
                        pass

            # Retirar los componentes que quedaron totalmente aislados (sin
            # ninguna conexión): normalmente el terminal de neutro del motor.
            alive = set()
            for conn in app.connections:
                alive.add(id(conn.start_component))
                alive.add(id(conn.end_component))
            orphaned = [c for c in app.components
                        if id(c) not in alive
                        and getattr(c, 'component_type', '') not in junction_types
                        and getattr(c, 'component_type', '') != 'fase']
            orphan_ids = {id(o) for o in orphaned}
            for comp in orphaned:
                try:
                    comp.delete()
                except Exception:
                    pass
            app.components = [c for c in app.components if id(c) not in orphan_ids]

        # UNIFICAR BORNERS: un solo borner por carga
        # Cada carga (motor, bobina, etc.) recibe UN único borner en el unifilar:
        # el más cercano a la carga. Sobran los borners que sólo unen símbolos de
        # conexión (conxn/junction) —no alimentan ninguna carga— y los borners
        # extra del mismo motor (p.ej. el retorno de neutro/tierra que cuelga
        # debajo: quedaría un "puente" sin alimentar).
        def _is_borner_comp(c):
            return (getattr(c, 'component_type', '') == 'borner'
                    or 'borner' in str(getattr(c, 'svg_file', '')).lower())

        def _is_bridge_comp(c):
            return getattr(c, 'component_type', '') in ('junction', 'conxn', 'conxn2')

        # borners -> partners de conexión
        bore_partners = defaultdict(list)
        for conn in app.connections:
            for b in (conn.start_component, conn.end_component):
                if _is_borner_comp(b):
                    other = conn.end_component if b is conn.start_component else conn.start_component
                    if other is not b:
                        bore_partners[id(b)].append(other)

        # BORNERS DE TIERRA (PE)
        # El unifilar dibuja UNA sola línea: no muestra el conductor de
        # protección. La bornera que sólo une la carga con el símbolo de tierra
        # (T.svg / PE) por eso se descarta; si no, "gana" la selección por
        # proximidad (queda debajo del motor, más cerca que la bornera de
        # alimentación) y se pierde la cadena relé térmico -> bornera -> motor,
        # que es la que sí lleva energía.
        def _is_earth_anchor(c):
            if getattr(c, 'component_type', '') in ('junction', 'conxn', 'conxn2'):
                return False
            svg = os.path.basename(str(getattr(c, 'svg_file', '') or '').lower())
            if svg == 't.svg':
                return True
            lbl = getattr(c, 'label_data', None)
            names = [str(getattr(c, 'name', '') or '')]
            if isinstance(lbl, dict):
                names.append(str(lbl.get('name', '') or ''))
            return any(n.upper().strip() in ('PE', 'TIERRA', 'GROUND', 'GND', 'EARTH',
                                             'ATERRAMIENTO', 'PROTECCION')
                       for n in names)

        def _is_earth_elem_dict(e):
            if not isinstance(e, dict) or e.get('type') != 'component':
                return False
            if os.path.basename(str(e.get('svg_file') or '').lower()) == 't.svg':
                return True
            return _source_phase_name(e) in ('PE', 'TIERRA', 'GROUND', 'GND', 'EARTH',
                                             'ATERRAMIENTO', 'PROTECCION')

        # Se mira la HOJA ORIGEN: en el unifilar el símbolo de tierra ya se
        # filtró, así que la bornera PE quedaría sin ningún indicio de que lo es.
        borner_by_id = {id(c): c for c in app.components if _is_borner_comp(c)}
        pe_src = {i for i, e in enumerate(src_elems) if _is_earth_elem_dict(e)}
        pe_borner_src = set(pe_src)
        for i in pe_src:
            pe_borner_src.update(neighbours.get(i, []))

        pe_borners = set()
        for i in pe_borner_src:
            if 0 <= i < len(src_elems):
                comp = comp_map.get(id(src_elems[i]))
                if comp is not None and _is_borner_comp(comp):
                    pe_borners.add(id(comp))
        for b_id, b in borner_by_id.items():
            if (_is_earth_anchor(b)
                    or any(_is_earth_anchor(p) for p in bore_partners.get(b_id, ()))):
                pe_borners.add(b_id)

        # borners asociados directamente a una carga (no a un símbolo de unión)
        loads_of_borner = defaultdict(list)   # id(borner) -> [(load, conn)]
        for conn in app.connections:
            for b in (conn.start_component, conn.end_component):
                if not _is_borner_comp(b):
                    continue
                other = conn.end_component if b is conn.start_component else conn.start_component
                if (not _is_borner_comp(other) and not _is_bridge_comp(other)
                        and getattr(other, 'component_type', '') != 'fase'):
                    loads_of_borner[id(b)].append((other, conn))

        # Mapa completo (incluye las de PE) para poder rescatar una bornera si
        # el filtrado dejara a una carga sin ninguna.
        all_load_borners = defaultdict(list)   # id(load) -> [(id(borner), load)]
        for b_id, pairs in loads_of_borner.items():
            for (load, _c) in pairs:
                all_load_borners[id(load)].append((b_id, load))
        for b_id in pe_borners:
            loads_of_borner.pop(b_id, None)

        drop_borners = set()
        # Carga -> borners que la alimentan; entre varias, sólo se descarta una
        # bornera MUERTA (su único hilo es el de la carga).  Una bornera en
        # serie —carga <-> nudo/otra bornera— forma parte del camino y quitarla
        # deja la rama sin conexión (p.ej. X4 entre M3 y J6 en SAN_ISIDRO).
        def _borner_conn_count(b):
            return sum(1 for c in app.connections
                       if b is c.start_component or b is c.end_component)

        load_borners = defaultdict(list)
        for b_id, pairs in loads_of_borner.items():
            for (load, _c) in pairs:
                load_borners[id(load)].append((borner_by_id[b_id], _c, load))
        for load_id, lst in load_borners.items():
            keep = min(lst, key=lambda t: (
                abs(t[0].x - t[2].x) + abs(t[0].y - t[2].y)))
            for borner, conn, _load in lst:
                if borner is not keep[0] and _borner_conn_count(borner) <= 1:
                    drop_borners.add(id(borner))
        # Borners puente (sólo unen uniones/conexiones) o sin ninguna conexión.
        for b in list(app.components):
            if not _is_borner_comp(b):
                continue
            if id(b) in drop_borners:
                continue
            if not loads_of_borner.get(id(b)):
                drop_borners.add(id(b))

        # SEGURIDAD: ninguna carga puede quedar sin bornera. Si el filtro de PE
        # dejó a un equipo con todas sus borneras marcadas se recupera la más
        # cercana, para no apagar su conexión en el plano.
        for load_id, entries in all_load_borners.items():
            if any(b_id not in drop_borners for b_id, _l in entries):
                continue
            load_comp = entries[0][1]
            cands = [borner_by_id[b_id] for b_id, _l in entries if b_id in borner_by_id]
            if not cands:
                continue
            keep = min(cands, key=lambda bb: abs(bb.x - load_comp.x) + abs(bb.y - load_comp.y))
            drop_borners.discard(id(keep))

        if drop_borners:
            app.connections = [c for c in app.connections
                               if id(c.start_component) not in drop_borners
                               and id(c.end_component) not in drop_borners]
            for c in list(app.components):
                if id(c) in drop_borners:
                    try:
                        c.delete()
                    except Exception:
                        pass
            app.components = [c for c in app.components if id(c) not in drop_borners]

        # Abanicos: un nudo en cada terminal del que sale más de un hilo
        self._fan_out_unifilar(app)

        # Auto-bucles (juncion conectada a sí misma): artefactos, sin topología
        for conn in list(app.connections):
            try:
                if conn.start_component is conn.end_component:
                    app.connections.remove(conn)
            except Exception:
                pass

        # Corregir solapes colineales residuales entre hilos distintos
        self._heal_unifilar_overlaps(app)

        # Evitar que hilos atraviesen el interior de cajas de componentes
        self._avoid_box_crossings(app)

        # Colocar saltos (conxn.svg) en los cruces reales del unifilar generado
        self._place_unifilar_jumps(app)

        # GARANTIZAR ETIQUETAS VISIBLES: draw() limpia las etiquetas al redibujar,
        # así que se vuelven a dibujar TODAS al terminar, para que el nombre de cada
        # componente aparezca sin necesidad de moverlo (sí incluye conxn/conxn2).
        for comp in list(app.components):
            try:
                if getattr(comp, 'component_type', '') == 'junction':
                    continue
                comp.clear_label()
                comp.draw_label()
            except Exception:
                pass

        app.set_status(f"✓ Plano unifilar generado con éxito en '{sheet_name}'", "green")
        app.save_undo_checkpoint()
        return True

    def _fan_out_unifilar(self, app):
        """Convierte los puntos de componente con más de un hilo en un nudo
        separador (unión) para que no salgan hilos paralelos superpuestos de un
        mismo terminal. De cada terminal sólo sale UNA arista hasta el nudo y de
        ahí se reparte a cada destino: elimina el tramo inicial duplicado que se
        veía como 'doble hilo'."""
        try:
            from models.junction_component import JunctionComponent
            from models.connection import Connection

            used_names = {c.name for c in app.components
                          if getattr(c, 'component_type', '') == 'junction'}
            junction_types = ('junction', 'conxn', 'conxn2')
            is_dark = app.is_dark_mode()

            def spot_free(hx, hy):
                for c in app.components:
                    if getattr(c, 'component_type', '') in junction_types:
                        if abs(c.x - hx) < 10 and abs(c.y - hy) < 10:
                            return False
                    else:
                        pad = 4
                        if (c.x - pad <= hx <= c.x + c.size[0] + pad and
                                c.y - pad <= hy <= c.y + c.size[1] + pad):
                            return False
                return True

            for comp in list(app.components):
                if getattr(comp, 'component_type', '') in junction_types:
                    continue
                npts = max(1, len(getattr(comp, 'conn_points', [])))
                for p in range(npts):
                    conns = [conn for conn in app.connections
                             if ((conn.start_component is comp and conn.start_point_idx == p) or
                                 (conn.end_component is comp and conn.end_point_idx == p))]
                    if len(conns) < 2:
                        continue
                    try:
                        px, py = comp.get_connection_points_global()[p][:2]
                    except Exception:
                        continue
                    sx = sy = 0.0
                    for conn in conns:
                        o = conn.end_component if conn.start_component is comp else conn.start_component
                        try:
                            ow, oh = getattr(o, 'size', [0, 0])
                        except Exception:
                            ow, oh = 0, 0
                        sx += (o.x + ow / 2) - px
                        sy += (o.y + oh / 2) - py
                    axis_vertical = abs(sy) >= abs(sx)
                    sign = 1 if (sy if axis_vertical else sx) >= 0 else -1

                    body = (comp.x, comp.y, comp.size[0], comp.size[1])
                    cand = []
                    base_off = max(7, body[3] if axis_vertical else body[2])
                    for sign_ in (sign, -sign):
                        for off in (6, 10, 14, 20, 28, 36, 46, 58, base_off + 8):
                            cand.append((px, py + sign_ * off) if axis_vertical else (px + sign_ * off, py))

                    hub = None
                    for (hx, hy) in cand:
                        if spot_free(hx, hy):
                            idx = 1
                            nm = 'J-%d' % idx
                            while nm in used_names:
                                idx += 1
                                nm = 'J-%d' % idx
                            used_names.add(nm)
                            hub = JunctionComponent(app.canvas, nm, hx, hy, app.config)
                            app.components.append(hub)
                            try:
                                hub.draw()
                            except Exception:
                                pass
                            break
                    if hub is None:
                        continue

                    # El stub (comp -> nudo) se traza PRIMERO para que las aristas
                    # hub -> destino, al rutar con el stub como obstáculo, no pisen
                    # la misma columna que sube al terminal (evita el doble hilo).
                    stub = Connection(comp, p, hub, 0)
                    stub.line_color = "white" if is_dark else "black"
                    stub.line_width = 2
                    app.connections.append(stub)
                    self._route_unifilar_connection(app, stub)

                    def _seg_rects(conn2, pad):
                        rs = []
                        for (x1, y1), (x2, y2) in getattr(conn2, 'segments', []) or []:
                            if abs(x1 - x2) < 0.01:
                                rs.append((x1 - pad, min(y1, y2), x1 + pad, max(y1, y2)))
                            elif abs(y1 - y2) < 0.01:
                                rs.append((min(x1, x2), y1 - pad, max(x1, x2), y1 + pad))
                        return rs

                    def _segs_overlap(segs_a, segs_b):
                        """Mayor solape colineal (>= umbral) entre dos juegos de
                        tramos ortogonales de DISTINTAS conexiones."""
                        best = 0.0
                        for (x1, y1), (x2, y2) in segs_a:
                            if abs(x1 - x2) < 0.01:
                                ax = x1
                                ay1, ay2 = min(y1, y2), max(y1, y2)
                                for (x3, y3), (x4, y4) in segs_b:
                                    if abs(x3 - x4) < 0.01 and abs(ax - x3) < 0.01:
                                        lo = max(ay1, min(y3, y4))
                                        hi = min(ay2, max(y3, y4))
                                        best = max(best, hi - lo)
                            elif abs(y1 - y2) < 0.01:
                                ay = y1
                                ax1, ax2 = min(x1, x2), max(x1, x2)
                                for (x3, y3), (x4, y4) in segs_b:
                                    if abs(y3 - y4) < 0.01 and abs(ay - y3) < 0.01:
                                        lo = max(ax1, min(x3, x4))
                                        hi = min(ax2, max(x3, x4))
                                        best = max(best, hi - lo)
                        return best

                    stub_rects = _seg_rects(stub, 2)
                    sibling_segs = []

                    for conn in conns:
                        if conn.start_component is comp:
                            other = conn.end_component
                            other_pt = conn.end_point_idx
                        else:
                            other = conn.start_component
                            other_pt = conn.start_point_idx
                        if other is hub:
                            continue
                        for lid in getattr(conn, 'line_ids', []):
                            try:
                                app.canvas.delete(lid)
                            except Exception:
                                pass
                        try:
                            app.connections.remove(conn)
                        except ValueError:
                            pass
                        new_conn = Connection(hub, 0, other, other_pt)
                        new_conn.line_color = "white" if is_dark else "black"
                        new_conn.line_width = 2
                        app.connections.append(new_conn)
                        self._route_unifilar_connection(app, new_conn, stub_rects)
                        # Si quedó colineal sobre un tramo de un hermano ya ruteado
                        # (mismo nudo y mismo punto), se re-ruta evitándolo: así dos
                        # ramas que suben desde el nudo no pintan el MISMO tramo.
                        my_segs = list(getattr(new_conn, 'segments', []) or [])
                        if sibling_segs and any(
                                _segs_overlap(my_segs, s) >= 6 for s in sibling_segs):
                            avoid = []
                            for s in sibling_segs:
                                for (x1, y1), (x2, y2) in s:
                                    if abs(x1 - x2) < 0.01:
                                        avoid.append((x1 - 3, min(y1, y2), x1 + 3, max(y1, y2)))
                                    elif abs(y1 - y2) < 0.01:
                                        avoid.append((min(x1, x2), y1 - 3, max(x1, x2), y1 + 3))
                            self._route_unifilar_connection(
                                app, new_conn, stub_rects + avoid)
                            my_segs = list(getattr(new_conn, 'segments', []) or [])
                        sibling_segs.append(my_segs)
        except Exception:
            import traceback
            traceback.print_exc()

    def _heal_unifilar_overlaps(self, app):
        """Pasada correctiva: detecta solapes colineales (>= 6px) entre hilos
        DISTINTOS ya ruteados y re-rutea el segundo con el tramo del primero que
        se solapa como obstáculo (con ventana en sus propios extremos para que el
        hilo pueda seguir llegando a sus terminales). Acotado a una caja de la
        geometría para no desarmar el dibujo."""
        def colinear(a1, a2, b1, b2, axis):
            return (a2 - b2) < 0.01 if axis else (a1 - b1) < 0.01

        for _round in range(20):
            segs = []
            for conn in list(app.connections):
                try:
                    for (x1, y1), (x2, y2) in getattr(conn, 'segments', []) or []:
                        segs.append((conn, (x1, y1), (x2, y2)))
                except Exception:
                    pass
            if not segs:
                return
            target = None
            for i in range(len(segs)):
                ca, a0, a1 = segs[i]
                for j in range(i + 1, len(segs)):
                    cb, b0, b1 = segs[j]
                    if ca is cb:
                        continue
                    if abs(a0[0] - a1[0]) < 0.01 and abs(b0[0] - b1[0]) < 0.01:
                        if abs(a0[0] - b0[0]) < 0.01 and min(a0[1], a1[1]) + 0.5 < max(b0[1], b1[1]) - 0.5 and max(a0[1], a1[1]) - 0.5 > min(b0[1], b1[1]) + 0.5:
                            ov = min(max(a0[1], a1[1]), max(b0[1], b1[1])) - max(min(a0[1], a1[1]), min(b0[1], b1[1]))
                            if ov >= 6.0:
                                target = (cb, (b0, b1), (a0, a1))
                                break
                    elif abs(a0[1] - a1[1]) < 0.01 and abs(b0[1] - b1[1]) < 0.01:
                        if abs(a0[1] - b0[1]) < 0.01 and min(a0[0], a1[0]) + 0.5 < max(b0[0], b1[0]) - 0.5 and max(a0[0], a1[0]) - 0.5 > min(b0[0], b1[0]) + 0.5:
                            ov = min(max(a0[0], a1[0]), max(b0[0], b1[0])) - max(min(a0[0], a1[0]), min(b0[0], b1[0]))
                            if ov >= 6.0:
                                target = (cb, (b0, b1), (a0, a1))
                                break
                if target:
                    break
            if not target:
                return
            cb = target[0]
            avoid = []
            xa1, ya1 = target[2][0]
            xa2, ya2 = target[2][1]
            if abs(xa1 - xa2) < 0.01:
                avoid.append((xa1 - 3, min(ya1, ya2), xa1 + 3, max(ya1, ya2)))
            else:
                avoid.append((min(xa1, xa2), ya1 - 3, max(xa1, xa2), ya1 + 3))
            self._reroute_unifilar_conn(app, cb, avoid)

    def _reroute_unifilar_conn(self, app, conn, extra_rects):
        """Re-rutea conn respetando la geometría previa y los rects extra,
        con ventana de aproximación en los dos terminales del hilo."""
        try:
            p_a = conn.start_component.get_connection_points_global()[conn.start_point_idx] if getattr(conn, 'start_point_idx', None) is not None else (conn.start_component.x + 8, conn.start_component.y + 8)
            p_b = conn.end_component.get_connection_points_global()[conn.end_point_idx] if getattr(conn, 'end_point_idx', None) is not None else (conn.end_component.x + 8, conn.end_component.y + 8)
            rects = []
            for oc in app.components:
                try:
                    if oc is conn.start_component or oc is conn.end_component:
                        continue
                    st = (round(float(getattr(oc, 'x', 0)), 2), round(float(getattr(oc, 'y', 0)), 2))
                    sz = list(getattr(oc, 'size', [0, 0]) or [0, 0])
                    rects.append((st[0], st[1], st[0] + sz[0], st[1] + sz[1]))
                except Exception:
                    continue
            rects.extend(extra_rects)
            old = list(getattr(conn, 'segments', []) or [])
            try:
                self._route_unifilar_connection(app, conn, rects)
            except Exception:
                conn.segments[:] = old[:]
            new = list(getattr(conn, 'segments', []) or [])
            if len(new) == 0:
                conn.segments[:] = old[:]
        except Exception:
            import traceback
            traceback.print_exc()

    def _avoid_box_crossings(self, app):
        """Pasada correctiva: si un tramo cruza el interior de una caja de un
        componente que no es uno de sus extremos, re-rutea el hilo con esa caja
        como obstáculo (conservando la geometría de llegada a sus terminales).
        Acotado y sin deshacer el resto del dibujo."""
        for _round in range(10):
            fixed = 0
            for conn in list(app.connections):
                segs = list(getattr(conn, 'segments', []) or [])
                hit = None
                for (x1, y1), (x2, y2) in segs:
                    for c in app.components:
                        if c is conn.start_component or c is conn.end_component:
                            continue
                        try:
                            xlo = float(getattr(c, 'x', 0)) + 1
                            ylo = float(getattr(c, 'y', 0)) + 1
                            xhi = xlo + getattr(c, 'size', [0, 0])[0] - 1.5
                            yhi = ylo + getattr(c, 'size', [0, 0])[1] - 1.5
                        except Exception:
                            continue
                        if abs(y1 - y2) < 0.01:
                            y = y1
                            if xlo < xhi and ylo <= y <= yhi:
                                lo, hi = min(x1, x2), max(x1, x2)
                                if lo < xhi and hi > xlo and (lo > xlo or hi < xhi):
                                    # Toma legítima: el hilo pasa junto al punto de
                                    # conexión del símbolo -> no es un cruce a evitar
                                    tap = False
                                    try:
                                        for p in c.get_connection_points_global():
                                            if abs(p[1] - y) < 6 and lo - 6 <= p[0] <= hi + 6:
                                                tap = True
                                                break
                                    except Exception:
                                        pass
                                    if tap:
                                        continue
                                    if (lo < (xlo + xhi) / 2 < hi) or (xlo < (lo + hi) / 2 < xhi):
                                        hit = (xlo - 1, ylo - 1, xhi + 1, yhi + 1)
                                        break
                        elif abs(x1 - x2) < 0.01:
                            x = x1
                            if ylo < yhi and xlo <= x <= xhi:
                                lo, hi = min(y1, y2), max(y1, y2)
                                if lo < yhi and hi > ylo and (lo > ylo or hi < yhi):
                                    tap = False
                                    try:
                                        for p in c.get_connection_points_global():
                                            if abs(p[0] - x) < 6 and lo - 6 <= p[1] <= hi + 6:
                                                tap = True
                                                break
                                    except Exception:
                                        pass
                                    if tap:
                                        continue
                                    if (lo < (ylo + yhi) / 2 < hi) or (ylo < (lo + hi) / 2 < yhi):
                                        hit = (xlo - 1, ylo - 1, xhi + 1, yhi + 1)
                                        break
                        if hit:
                            break
                    if hit:
                        break
                if hit:
                    try:
                        old = list(segs)
                        self._reroute_unifilar_conn(app, conn, [hit])
                        if len(getattr(conn, 'segments', []) or []) == 0:
                            conn.segments[:] = old[:]
                        fixed += 1
                    except Exception:
                        pass
            if fixed == 0:
                break

    def _place_unifilar_jumps(self, app):
        """Coloca símbolos de salto (conxn.svg) sobre los cruces reales de la
        geometría unifilar final, para que ningún cruce de hilos parezca un empalme
        y cada salto quede en la posición exacta de su cruce."""
        try:
            # Recalcular segmentos Manhattan de cada conexión para tener la geometría real
            for conn in list(app.connections):
                try:
                    app.update_manhattan_line(conn)
                except Exception:
                    pass

            from models.component import Component

            segments = []
            for conn in app.connections:
                for (x1, y1), (x2, y2) in getattr(conn, 'segments', []):
                    segments.append((conn, x1, y1, x2, y2))

            horiz = [s for s in segments if abs(s[2] - s[4]) < 0.01]
            vert = [s for s in segments if abs(s[1] - s[3]) < 0.01]

            # Puntos ocupados por terminales/uniones: NO se pone salto ahí
            occupied = []
            for comp in app.components:
                try:
                    for pt in comp.get_connection_points_global():
                        occupied.append((pt[0], pt[1]))
                except Exception:
                    pass

            # Saltos conxn que ya aportó la fuente -> no duplicarlos
            existing_jumps = []
            for comp in app.components:
                if getattr(comp, 'component_type', '') in ('conxn', 'conxn2'):
                    try:
                        size = comp.size
                        existing_jumps.append((comp.x + size[0] / 2, comp.y + size[1] / 2))
                    except Exception:
                        pass

            placed = []
            EPS = 5.0
            JUMP_NEAR = 45.0

            for conn_h, hx1, hy1, hx2, hy2 in horiz:
                for conn_v, vx1, vy1, vx2, vy2 in vert:
                    if conn_h is conn_v:
                        continue
                    ix = vx1   # X del cruce (el segmento vertical es vertical: X constante)
                    iy = hy1   # Y del cruce (el segmento horizontal es horizontal: Y constante)
                    if not (min(hx1, hx2) + EPS < ix < max(hx1, hx2) - EPS):
                        continue
                    if not (min(vy1, vy2) + EPS < iy < max(vy1, vy2) - EPS):
                        continue
                    # Evitar cruces sobre terminales o uniones (ahí sí hay empalme)
                    if any(abs(ix - ox) < 8 and abs(iy - oy) < 8 for ox, oy in occupied):
                        continue
                    # Evitar duplicar un salto ya presente o ya colocado
                    if any(abs(ix - ex) < JUMP_NEAR and abs(iy - ey) < JUMP_NEAR for ex, ey in existing_jumps):
                        continue
                    if any(abs(ix - px) < JUMP_NEAR and abs(iy - py) < JUMP_NEAR for px, py in placed):
                        continue
                    placed.append((ix, iy))
                    try:
                        size = list(app.get_component_real_size('conxn.svg', 'connection'))
                    except Exception:
                        size = [24, 18]
                    jump = Component(app.canvas, 'conxn.svg', 'Conexión', size,
                                     ix - size[0] / 2, iy - size[1] / 2,
                                     app.config.get('svg_path', ''), 'connection', app.config)
                    jump.line_color = "white" if app.is_dark_mode() else "black"
                    app.components.append(jump)
                    try:
                        jump.draw()
                    except Exception:
                        pass
        except Exception:
            pass

class Cabinet2DGenerator:
    """Generador de Hoja de Gabinete 2D con componentes escalados (medidas reales) y etiquetas descriptivas."""

    def __init__(self, project):
        self.project = project

    def generate_cabinet_2d_sheet(self, app):
        """
        Genera la Hoja de Gabinete 2D (Fidelidad Técnica Total).
        - Representación 1:1 persistente.
        - Distribución por renglones: Protecciones -> Maniobra -> Bornas.
        - Dimensionado profesional con objetos Line.
        """
        sheet_name = "Hoja de Gabinete 2D"

        # 1. GESTIÓN DE LA HOJA Y PERSISTENCIA
        cabinet_index = -1
        for i, sheet in enumerate(app.project.sheets):
            if sheet.name == sheet_name:
                cabinet_index = i
                break
        if cabinet_index == -1:
            app.project.add_sheet(sheet_name)
            cabinet_index = len(app.project.sheets) - 1

        target_sheet = app.project.sheets[cabinet_index]

        # CRÍTICO FIX: Guardar shapes del usuario antes de limpiar.
        # Incluye DinRail/Canaleta (dibujadas con Ctrl+D/Ctrl+F) y cualquier forma
        # geométrica insertada manualmente por el usuario (marcada con
        # metadata['user_shape']). Sin esto, un círculo/rectángulo insertado en la
        # Hoja de Gabinete 2D se perdía al cambiar de hoja o al guardar.
        user_shapes = []
        _seen_user_ids = set()
        _sources = []
        if hasattr(target_sheet, 'live_shape_objects'):
            _sources.append(target_sheet.live_shape_objects)
        # Si la hoja 2D es la activa, la lista viva del manager es la fuente de
        # verdad (puede contener formas recién insertadas y aún sin sincronizar).
        try:
            if app.project.get_active_sheet() is target_sheet:
                _sources.append(getattr(app.shape_manager, 'shapes', []))
        except Exception:
            pass
        from models.shape import DinRail, Canaleta
        for _src in _sources:
            for s in _src:
                if id(s) in _seen_user_ids:
                    continue
                meta = getattr(s, 'metadata', {}) or {}
                if isinstance(s, (DinRail, Canaleta)) or meta.get('user_shape'):
                    user_shapes.append(s)
                    _seen_user_ids.add(id(s))

        # Rescatar Block Terminals antes de limpiar el canvas
        saved_block_terminals = [
            {
                'x':          bt['x'],
                'y':          bt['y'],
                'filas':      bt['filas'],
                'bornas':     bt['bornas'],
                'label_data': bt['label_data'].copy(),
            }
            for bt in getattr(target_sheet, 'live_block_terminals', [])
        ]

        # Smart Update: Salvar posiciones previas
        existing_positions = {}
        if hasattr(target_sheet, 'live_shape_objects'):
            for s in target_sheet.live_shape_objects:
                t = getattr(s, 'metadata', {}).get('component_tag')
                if t: existing_positions[t] = (s.x, s.y)

        # 2. PREPARACIÓN DEL ENTORNO
        medidas = load_medidas_config()
        specs = medidas.get("especificaciones_ingenieria", {})
        cab_config = medidas.get("configuracion_armario_2d", {})

        app.switch_to_sheet(cabinet_index)
        app.canvas.xview_moveto(0)
        app.canvas.yview_moveto(0)
        app.canvas.delete("all")
        app.components.clear()
        app.connections.clear()
        if not hasattr(app, 'text_components'): app.text_components = []
        app.text_components.clear()
        # NO limpiar completamente - preservar shapes del usuario
        app.shape_manager.shapes = []  # Limpiar la lista pero no destruir objetos user_shapes
        app.draw_grid(force=True)

        # 3. DATOS DE INGENIERÍA
        try:
            sum_gen = CabinetSummaryGenerator(self.project)
            classified = sum_gen._classify_devices(self.project)
            results = sum_gen._calculate_dimensions_and_materials(classified)
            parts = results['dimensiones'].split('x')
            cab_w = float(parts[0].strip())
            cab_h = float(parts[1].strip().split()[0])
        except Exception:
            cab_w = cab_config.get("fallback_ancho", 500)
            cab_h = cab_config.get("fallback_alto", 800)

        from models.shape import Line

        # Estética
        IS_DARK = app.is_dark_mode()
        TEXT_COLOR = "white" if IS_DARK else "black"
        LINE_COLOR = "white" if IS_DARK else "black"

        CABINET_COLOR = cab_config.get("color_fondo_oscuridad", "#D4C894") if IS_DARK else cab_config.get("color_fondo_claridad", "")
        PLACA_COLOR = cab_config.get("color_placa_oscuridad", "#8B5E3C") if IS_DARK else cab_config.get("color_placa_claridad", "#D2B48C")
        COMPONENT_COLOR = "#016D6B" if IS_DARK else "#018684"

        margin_x = cab_config.get("margen_x", 120)
        margin_y = cab_config.get("margen_y", 180)
        gap = cab_config.get("espacio_entre_estructuras", 150)
        margen_placa = cab_config.get("margen_placa", 25)

        cx_tablero = margin_x + cab_w/2
        cx_tapa = cx_tablero + cab_w + gap
        cy = margin_y + cab_h/2

        # 4. DIBUJO ESTRUCTURAL (TABLERO Y TAPA)
        from models.shape import RoundedRect
        tablero = Rect(cx_tablero, cy, cab_w, cab_h)
        tablero.fill = CABINET_COLOR; tablero.outline = LINE_COLOR; tablero.outline_width = 3
        tablero.metadata = {'type': 'cabinet_background'}
        app.shape_manager.shapes.append(tablero)

        useful_width = max(cab_w - margen_placa * 2, 0)
        useful_height = max(cab_h - margen_placa * 2, 0)
        useful_radius = min(35, useful_width / 2, useful_height / 2)
        useful_area = RoundedRect(cx_tablero, cy, useful_width, useful_height, useful_radius)
        useful_area.fill = PLACA_COLOR; useful_area.outline = '#8B4513'; useful_area.outline_width = 2
        useful_area.metadata = {'type': 'cabinet_background'}
        app.shape_manager.shapes.append(useful_area)

        tapa = Rect(cx_tapa, cy, cab_w, cab_h)
        tapa.fill = CABINET_COLOR; tapa.outline = LINE_COLOR; tapa.outline_width = 3
        tapa.metadata = {'type': 'cabinet_background'}
        app.shape_manager.shapes.append(tapa)

        # 4.1 LÍNEA DIVISORIA CENTRAL DE LA PUERTA (CABINET_BACKGROUND = INAMOVIBLE)
        # El límite exacto se define aquí: (cab_w > 400)
        if cab_w > 700:
            mid_line = Line(cx_tapa, cy - cab_h/2, cx_tapa, cy + cab_h/2)
            mid_line.fill = LINE_COLOR; mid_line.width = 1.5
            mid_line.metadata = {'type': 'cabinet_background'} # Bloqueo contra movimiento y edición
            app.shape_manager.shapes.append(mid_line)

        # 5. ACOTADO (DIMENSIONS) USANDO OBJETOS LINE
        aw1 = Line(cx_tablero - cab_w/2, margin_y - 50, cx_tablero + cab_w/2, margin_y - 50)
        aw1.arrow = 'both'; aw1.width = 2; aw1.fill = LINE_COLOR
        app.shape_manager.shapes.append(aw1)
        app.text_components.append(TextComponent(app.canvas, f"{int(cab_w)} mm", 10, cx_tablero, margin_y - 70, bold=True, color=TEXT_COLOR))

        # Alto Tablero

        aw2 = Line(cx_tapa - cab_w/2, margin_y - 50, cx_tapa + cab_w/2, margin_y - 50)
        aw2.arrow = 'both'; aw2.width = 2; aw2.fill = LINE_COLOR
        app.shape_manager.shapes.append(aw2)
        app.text_components.append(TextComponent(app.canvas, f"{int(cab_w)} mm", 10, cx_tapa, margin_y - 70, bold=True, color=TEXT_COLOR))

        # Alto Tapa (lado derecho)
        ah2 = Line(cx_tapa + cab_w/2 + 50, margin_y, cx_tapa + cab_w/2 + 50, margin_y + cab_h)
        ah2.arrow = 'both'; ah2.width = 2; ah2.fill = LINE_COLOR
        app.shape_manager.shapes.append(ah2)
        app.text_components.append(TextComponent(app.canvas, f"{int(cab_h)} mm", 10, cx_tapa + cab_w/2 + 85, cy, color=TEXT_COLOR))

        # Títulos
        app.text_components.append(TextComponent(app.canvas, "GABINETE (PLACA DE MONTAJE)", 12, cx_tablero, margin_y - 120, bold=True, color=TEXT_COLOR))
        app.text_components.append(TextComponent(app.canvas, "TAPA (PUERTA)", 12, cx_tapa, margin_y - 120, bold=True, color=TEXT_COLOR))

        # 6. EXTRACCIÓN SINCRONIZADA CON LA BOM (LISTA DE PARTES)
        all_comps = []
        seen_tags = set()

        # Reutilizamos la lógica del BOMGenerator para absoluta fidelidad
        bom_gen = BOMGenerator(self.project)
        raw_components = bom_gen._collect_components_from_project(self.project)

        # También comprobamos si hay componentes vivos en la app (sin guardar)
        for s in app.project.sheets:
            if s.name == sheet_name: continue
            lives = getattr(s, 'live_components', [])
            for c in lives:
                # FIX ETIQUETAS: Obtener el nombre real (Q1, KM1, etc) desde label_data o name
                t = '??'
                if hasattr(c, 'label_data') and isinstance(c.label_data, dict):
                    t = c.label_data.get('name', '??')
                if t == '??':
                    t = getattr(c, 'name', '??')

                if t not in seen_tags and t != '??':
                    raw_components.append({
                        'category': getattr(c, 'category', ''),
                        'svg_file': getattr(c, 'svg_file', ''),
                        'label_data': {'name': t, 'descripcion': getattr(c, 'name', '')}
                    })
        # Agrupar por TAG para contar cuántos polos físicos representa (ej: tres Q1 = Disyuntor 3P)
        tag_counts = {}
        unique_components = {}

        for c in raw_components:
            # Extraer TAG/Nombre
            if isinstance(c, dict):
                label_data = c.get('label_data') or {}
                name = label_data.get('name', '??')
            else:
                label_data = getattr(c, 'label_data', {}) or {}
                name = label_data.get('name', '??') if isinstance(label_data, dict) else getattr(c, 'name', '??')

            # Siempre se añade al conteo
            if name != '??':
                tag_counts[name] = tag_counts.get(name, 0) + 1

            # Guardamos la primera instancia como representativa del componente físico
            if name not in unique_components or name == '??':
                unique_components[id(c) if name == '??' else name] = c

        # 6.5 RELÉS EN ZÓCALO
        # Calcular ANTES del loop de clasificación para poder excluir sus nombres.
        g_relay_socket = []
        _names_covered = set()
        for _sheet in app.project.sheets:
            if _sheet.name == sheet_name:
                continue
            for _elem in getattr(_sheet, 'elements', []):
                if not isinstance(_elem, dict):
                    continue
                _svg_e = str(_elem.get('svg_file') or '').lower()
                _cat_e = str(_elem.get('category') or '').lower()
                _ln = (_elem.get('label_data') or {}).get('name', '')
                if not _ln:
                    continue
                if any(x in _svg_e for x in ['no.svg', 'nc.svg', 'contact', 'contacto']):
                    _names_covered.add(_ln)
                if 'contactor' in _svg_e or 'contactor' in _cat_e:
                    _names_covered.add(_ln)

        for _sheet in app.project.sheets:
            if _sheet.name == sheet_name:
                continue
            for _elem in getattr(_sheet, 'elements', []):
                if not isinstance(_elem, dict):
                    continue
                _svg_e = str(_elem.get('svg_file') or '').lower()
                if _svg_e.endswith('selenoid-coil.svg'):
                    continue
                if any(x in _svg_e for x in ['coil', 'bobina']):
                    _ln = (_elem.get('label_data') or {}).get('name', '')
                    if _ln and _ln not in _names_covered:
                        g_relay_socket.append(_elem)

        # Nombres que ya están representados como relé+zócalo -> excluir del gabinete normal
        relay_socket_names = {
            (e.get('label_data') or {}).get('name', '') for e in g_relay_socket
        }

        # FILTRADO PROFESIONAL: Solo componentes permitidos (Ignorar motores, boyas, etc.)
        g_prot, g_man, g_ctrl, g_term, g_tapa = [], [], [], [], []

        def _label_desc(ld, fallback=''):
            """Texto descriptivo del componente.

            La UI guarda la descripción en 'description' (ui/label_editors.py),
            pero el código antiguo sólo leía 'descripcion', por lo que los
            dispositivos externos (p. ej. un presostato) nunca eran detectados
            y terminaban dibujados en la Hoja de Gabinete 2D.
            """
            if not isinstance(ld, dict):
                return str(fallback or '').lower()
            return ' '.join(str(ld.get(k, '') or '') for k in ('descripcion', 'description')).lower()

        for key, c in unique_components.items():
            if isinstance(c, dict):
                cat, svg = str(c.get('category','')).lower(), str(c.get('svg_file','')).lower()
                name = str((c.get('label_data') or {}).get('name', '??')).lower()
                desc = _label_desc(c.get('label_data'))
            else:
                _ld = getattr(c, 'label_data', {})
                cat, svg = str(getattr(c, 'category', '')).lower(), str(getattr(c, 'svg_file', '')).lower()
                name = str(_ld.get('name', getattr(c, 'name', '??')) if isinstance(_ld, dict) else getattr(c, 'name', '??')).lower()
                desc = _label_desc(_ld, getattr(c, 'name', ''))

            # Recuperar el conteo de polos (si no, asumimos 1)
            pole_count = tag_counts.get(name.upper(), 1) if name != '??' else 1

            # Guardar el conteo de polos en el diccionario para pasarlo a get_engineering_size
            if isinstance(c, dict):
                if 'label_data' not in c or not isinstance(c['label_data'], dict):
                    c['label_data'] = {}
                c['label_data']['pole_count'] = pole_count

            # LISTA DE INCLUSIÓN ESTRICTA (Solo estos se permiten en el gabinete 2D)
            allowed_keywords = [
                'contactor', 'maniobra', 'breaker', 'disyuntor', 'diferencial', 'guardamotor',
                'motor-circuit-breaker', 'motor circuit breaker',
                'protec', 'rele', 'relay', 'thermal', 'perilla', 'selector', 'switch',
                'piloto', 'pilot', 'light', 'boton', 'pushbutton', 'paro', 'emergencia',
                'emergency', 'seta', 'plc', 'cpu', 'modbus', 'logo', 'zelio', 'transfo',
                'fuente', 'power', 'supply', 'lcd', 'display', 'screen', 'buzzer', 'alarma',
                'sirena', 'borner', 'terminal', 'conex', 'fusible', 'fuse', 'vdf', 'variador',
                'sst', 'soft starter', 'driver', 'inverter', 'mushroom',
            ]

            # Verificar si el componente coincide con la lista permitida
            is_allowed = any(x in cat or x in svg or x in name or x in desc for x in allowed_keywords)

            # IMPORTANTE: 'motor-circuit-breaker' contiene la palabra 'motor' pero ES un dispositivo
            # interno del gabinete (guardamotor/interruptor de protección de motor).
            # Se excluye explícitamente del filtro de externos para que no sea bloqueado.
            is_motor_circuit_breaker = 'motor-circuit-breaker' in svg or 'motor-circuit-breaker' in cat

            # Asegurar que los componentes de puerta no sean catalogados como externos por error
            is_door_comp = any(y in svg for y in ['pilot', 'light', 'button', 'selector', 'piloto', 'perilla', 'buzzer', 'alarma', 'sirena', 'paro', 'mushroom', 'emergency', 'seta'])

            is_external = (not is_motor_circuit_breaker) and (
                any(
                    x in cat or x in svg or x in name or x in desc for x in [
                        'motor', 'boya', 'solenoide', 'selenoid', 'sensor', 'presostato',
                        'pressostato', 'presion', 'pressure', 'flow-switch', 'caudal',
                        'nivel', 'level', 'flotador', 'roller', 'external', 'externo',
                        'conxn', 'dot', 'nodo', 'empalme'
                    ]
                ) or svg.endswith('selenoid-coil.svg')
            )

            if is_door_comp:
                is_external = False

            if not is_allowed or is_external or cat == 'block_terminal' or 'block_terminal' in svg:
                continue

            # Excluir componentes (bobina y contactos) cuyo nombre ya es un relé+zócalo
            comp_name_raw = (c.get('label_data') or {}).get('name', '??') if isinstance(c, dict) else str(getattr(c, 'label_data', {}).get('name', '??') if isinstance(getattr(c, 'label_data', {}), dict) else getattr(c, 'name', '??'))
            if comp_name_raw and comp_name_raw != '??' and comp_name_raw in relay_socket_names:
                continue

            if any(x in cat or x in svg or x in name or x in desc for x in ['pilot', 'light', 'button', 'selector', 'piloto', 'perilla', 'buzzer', 'lcd', 'display', 'paro', 'mushroom', 'emergency']):
                g_tapa.append(c)
            elif any(x in cat or x in svg or x in name or x in desc for x in ['breaker', 'disyuntor', 'protec', 'fusible', 'fuse', 'diferencial', 'guardamotor', 'motor-circuit-breaker']):
                g_prot.append(c)
            elif any(x in cat or x in svg or x in name or x in desc for x in ['contactor', 'thermal', 'maniobra', 'rele', 'relay', 'sst', 'vdf', 'variador']):
                g_man.append(c)
            elif any(x in cat or x in svg or x in name or x in desc for x in ['borner', 'terminal', 'conex']):
                g_term.append(c)
            else:
                g_ctrl.append(c)

        rows = [g_prot, g_man, g_ctrl, g_term]

        def _build_layout(comp_groups, ox, oy, aw, ah):
            row_y = oy + 60
            col_x_start = ox + 45

            for group in comp_groups:
                if not group: continue
                col_x = col_x_start
                max_h_in_row = 0

                # Ordenar por Referencia (Nombre) para profesionalidad
                group.sort(key=lambda x: (x.get('label_data') or {}).get('name', '??'))

                for c in group:
                    # FIX ETIQUETAS: Usar 'name' que es donde está la Referencia (Q1, KM1)
                    name = (c.get('label_data') or {}).get('name', '??')
                    cat, svg = str(c.get('category','')).lower(), str(c.get('svg_file','')).lower()
                    w_mm, h_mm = get_engineering_size(svg, cat, c.get('label_data'))

                    # BORNAS MULTIPOLO: un único bloque con divisiones internas
                    # borner-1 = 1 polo, borner-2 = 2 polos, borner-3 = 3, borner-4 = 4
                    _borner_match = re.search(r'borner-(\d+)', svg)
                    pole_count_borner = int(_borner_match.group(1)) if _borner_match else 1
                    is_multipole_borner = 'borner' in svg and pole_count_borner > 1

                    if is_multipole_borner:
                        # Ancho total = (ancho de un polo + 2mm de holgura) × número de polos
                        total_w = (w_mm + 3) * pole_count_borner

                        if name in existing_positions:
                            sx, sy = existing_positions[name]
                        else:
                            if col_x + total_w + 30 > ox + aw:  # Salto de línea
                                row_y += max_h_in_row + 40
                                col_x = col_x_start
                                max_h_in_row = 0
                            sx, sy = col_x + total_w / 2, row_y + h_mm / 2

                        # Rectángulo exterior único que abarca todos los polos con divisiones internas
                        from models.shape import MultipoleBorner
                        borner_block = MultipoleBorner(sx, sy, total_w, h_mm, pole_count_borner)
                        borner_block.fill = COMPONENT_COLOR
                        borner_block.outline = LINE_COLOR
                        borner_block.outline_width = 1.5
                        borner_block.metadata = {'component_tag': name, 'type': 'component'}
                        app.shape_manager.shapes.append(borner_block)

                        # Etiqueta única encima del bloque centrada
                        label_y = sy - h_mm / 2 - 10
                        ref_text = TextComponent(app.canvas, name, 10, sx, label_y, color=TEXT_COLOR, bold=True)
                        app.text_components.append(ref_text)

                        if name not in existing_positions:
                            col_x += total_w + 25
                            max_h_in_row = max(max_h_in_row, h_mm)

                    else:
                        # Componente normal (incluye borner-1)
                        if name in existing_positions:
                            sx, sy = existing_positions[name]
                        else:
                            if col_x + w_mm + 30 > ox + aw:  # Salto de línea
                                row_y += max_h_in_row + 40
                                col_x = col_x_start
                                max_h_in_row = 0
                            sx, sy = col_x + w_mm/2, row_y + h_mm/2

                        # Identificación básica por forma (selector/perilla/buzzer -> círculo)
                        is_circle = any(x in cat or x in svg for x in ['pilot', 'light', 'button', 'piloto', 'mushroom', 'emergency', 'paro', 'seta', 'buzzer', 'alarma', 'sirena'])

                        if is_circle:
                            shape = Circle(sx, sy, w_mm/2)
                        else:
                            shape = Rect(sx, sy, w_mm, h_mm)

                        shape.fill = COMPONENT_COLOR; shape.outline = LINE_COLOR; shape.outline_width = 1.5
                        shape.metadata = {'component_tag': name, 'type': 'component'}
                        app.shape_manager.shapes.append(shape)

                        # Etiqueta encima
                        label_y = sy - h_mm/2 - 10
                        ref_text = TextComponent(app.canvas, f"{name}", 10, sx, label_y, color=TEXT_COLOR, bold=True)
                        app.text_components.append(ref_text)

                        if name not in existing_positions:
                            col_x += w_mm + 25
                            max_h_in_row = max(max_h_in_row, h_mm)

                # Espacio entre grupos de distinta jerarquía
                row_y += max_h_in_row + 55

        # Ejecutar despliegue del tablero
        _build_layout(rows, cx_tablero - cab_w/2, margin_y, cab_w, cab_h)

        if g_relay_socket:
            # Calcular posición inicial: debajo del resto de filas
            relay_row_y = margin_y + cab_h - 100
            relay_col_x = cx_tablero - cab_w/2 + 45
            for _rs in g_relay_socket:
                _rs_name = (_rs.get('label_data') or {}).get('name', '??')

                # Detectar tamaño dinámico (Slim vs Normal)
                _rs_svg = str(_rs.get('svg_file', '')).lower()
                _rs_cat = str(_rs.get('category', '')).lower()
                relay_w, relay_h = get_engineering_size(_rs_svg, _rs_cat, _rs.get('label_data'))

                # Si el tamaño detectado es el de un relé normal, usar el tamaño de ZÓCALO estándar
                # Pero si es SLIM, usar su medida real.
                if relay_w > 10: # No es Slim
                    relay_w, relay_h = specs.get('RELE_ZOCALO', [30, 67])

                # Usar posición existente si ya fue colocado manualmente
                if _rs_name in existing_positions:
                    _sx, _sy = existing_positions[_rs_name]
                else:
                    _sx, _sy = relay_col_x + relay_w / 2, relay_row_y + relay_h / 2
                    relay_col_x += relay_w + 25

                relay_shape = Rect(_sx, _sy, relay_w, relay_h)
                relay_shape.fill = COMPONENT_COLOR
                relay_shape.outline = LINE_COLOR
                relay_shape.outline_width = 1.5
                relay_shape.metadata = {'component_tag': _rs_name, 'type': 'relay_socket'}
                app.shape_manager.shapes.append(relay_shape)

                # Etiqueta sobre el shape
                label_y_rs = _sy - relay_h / 2 - 10
                ref_text_rs = TextComponent(app.canvas, _rs_name, 10, _sx, label_y_rs, color=TEXT_COLOR, bold=True)
                app.text_components.append(ref_text_rs)

        # Despliegue de Tapa (Pilotos / Botonería)
        if g_tapa:
            door_y = cy
            door_x_start = cx_tapa - (len(g_tapa)*75)/2 + 35
            for i, c in enumerate(g_tapa):
                name = (c.get('label_data') or {}).get('name', '??')
                w_mm, h_mm = get_engineering_size(str(c.get('svg_file','')), str(c.get('category','')), c.get('label_data'))
                sx, sy = (existing_positions[name] if name in existing_positions else (door_x_start + i*85, door_y))

                # selector/perilla -> cuadrado; el resto de tapa -> círculo
                _svg_tapa = str(c.get('svg_file', '')).lower()
                _cat_tapa = str(c.get('category', '')).lower()
                is_tapa_square = any(x in _svg_tapa or x in _cat_tapa for x in ['selector', 'perilla'])
                if is_tapa_square:
                    shape = Rect(sx, sy, w_mm, h_mm)
                else:
                    shape = Circle(sx, sy, w_mm/2)
                shape.fill = COMPONENT_COLOR; shape.outline = LINE_COLOR; shape.outline_width = 1.5
                shape.metadata = {'component_tag': name, 'type': 'door_component'}
                # NO renderizar la etiqueta blanca interna
                app.shape_manager.shapes.append(shape)

                # ETIQUETA EXTERNA (Tapa): Ponerla justo arriba
                label_y = sy - h_mm/2 - 15
                ref_text = TextComponent(app.canvas, f"{name}", 10, sx, label_y, color=TEXT_COLOR, bold=True)
                app.text_components.append(ref_text)

        # 7. PERSISTENCIA Y DIBUJO FINAL
        # Dibujo en orden de capas (Z-Order)
        for s in app.shape_manager.shapes:
            s.draw(app.canvas)
        for t in app.text_components:
            t.draw()

        # CRÍTICO FIX: Restaurar shapes del usuario (DinRail y Canaleta) al final
        # Esto preserva las canaletas y rieles DIN dibujados por el usuario
        for user_shape in user_shapes:
            if user_shape not in app.shape_manager.shapes:
                # Limpiar canvas_id porque fue invalidado por canvas.delete("all")
                user_shape.canvas_id = None
                if hasattr(user_shape, 'inner_ids'):
                    user_shape.inner_ids = []
                user_shape.draw(app.canvas)
                app.shape_manager.shapes.append(user_shape)

        # CALCULAR Y MOSTRAR TOTALES DE CANALETA Y RIEL
        self._add_totals_display(app, cx_tablero, cx_tapa)

        target_sheet.live_shape_objects = list(app.shape_manager.shapes)
        target_sheet.live_texts = list(app.text_components)

    def _add_totals_display(self, app, cx_tablero=0, cx_tapa=0):
        """
        Calcula y muestra los totales de canaleta y riel como texto no editable
        en el espacio entre el tablero y la tapa.
        """
        try:
            from models.shape import DinRail, Canaleta

            total_canaleta_m = 0.0
            total_riel_m = 0.0
            canaleta_count = 0
            riel_count = 0
            canaletas_por_seccion_m = {}  # seccion -> metros

            for shape in app.shape_manager.shapes:
                if isinstance(shape, Canaleta):
                    total_canaleta_m += shape.largo / 1000.0
                    canaleta_count += 1
                    sec = getattr(shape, 'seccion', None) or '40X40'
                    canaletas_por_seccion_m[sec] = canaletas_por_seccion_m.get(sec, 0.0) + shape.largo / 1000.0
                elif isinstance(shape, DinRail):
                    total_riel_m += shape.width / 1000.0  # DinRail usa width como largo
                    riel_count += 1

            # Redondear a cantidades comerciales (siempre hacia arriba)
            import math
            canaleta_comercial_m = math.ceil(total_canaleta_m / 2.0) * 2.0 if total_canaleta_m > 0 else 0.0
            riel_comercial_m = math.ceil(total_riel_m / 2.0) * 2.0 if total_riel_m > 0 else 0.0

            # Posición: Entre gabinete y tapa, centrado en el espacio intermedio
            if cx_tablero > 0 and cx_tapa > 0:
                x_pos = (cx_tablero + cx_tapa) / 2
            else:
                canvas_width = app.canvas.winfo_width() if hasattr(app.canvas, 'winfo_width') else 1200
                x_pos = canvas_width * 0.42

            y_pos = 40

            # Color según modo
            IS_DARK = app.is_dark_mode()
            text_color = "blue"

            def _orden_seccion(item):
                d = parse_seccion_canaleta(item[0]) or (0, 0)
                return (d[0], d[1], item[0])

            # Textos de totales
            if canaleta_count > 0 or riel_count > 0:
                canaleta_text = f"Canaleta: {total_canaleta_m:.2f}m → {canaleta_comercial_m:.1f}m ({math.ceil(total_canaleta_m / 2.0)} tiras)"
                riel_text = f"Riel DIN: {total_riel_m:.2f}m → {riel_comercial_m:.1f}m ({math.ceil(total_riel_m / 2.0)} tiras)"
            else:
                canaleta_text = "Canaleta: 0.00m → 0.0m (0 tiras)"
                riel_text = "Riel DIN: 0.00m → 0.0m (0 tiras)"

            # Desglose por ancho comercial (una línea por sección)
            detalle_texts = []
            for seccion, metros in sorted(canaletas_por_seccion_m.items(), key=_orden_seccion):
                tiras = math.ceil(metros / 2.0) if metros > 0 else 0
                detalle_texts.append(
                    f"   ▪ {seccion} mm: {metros:.2f}m → {tiras} tira(s) de 2 m"
                )

            from models.component import TextComponent
            title_text = TextComponent(app.canvas, "TOTALES MATERIALES", 8, x_pos, y_pos, color="blue", bold=False)
            canaleta_disp = TextComponent(app.canvas, canaleta_text, 8, x_pos, y_pos + 20, color="blue")
            riel_disp = TextComponent(app.canvas, riel_text, 8, x_pos, y_pos + 35, color="blue")

            nuevos_textos = [title_text, canaleta_disp, riel_disp]

            # Líneas de detalle por sección comercial
            for i, det in enumerate(detalle_texts):
                t = TextComponent(app.canvas, det, 7, x_pos, y_pos + 50 + i * 14, color="blue")
                t.metadata = {'editable': False, 'type': 'totals_display', 'exportable': False}
                nuevos_textos.append(t)

            title_text.metadata = {'editable': False, 'type': 'totals_display', 'exportable': False}
            canaleta_disp.metadata = {'editable': False, 'type': 'totals_display', 'exportable': False}
            riel_disp.metadata = {'editable': False, 'type': 'totals_display', 'exportable': False}

            app.text_components.extend(nuevos_textos)

        except Exception as e:
            import logging
            logging.error(f"Error mostrando totales en 2D: {e}")

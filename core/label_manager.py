"""
Gestión de nombres, prefijos y datos de etiquetas.
"""

class LabelManager:
    KEYWORD_TO_LETTER = {
        # INTERRUPTORES, PROTECCIONES Y MANIOBRA DE POTENCIA
        'breaker': 'Q',
        'disyuntor': 'Q',
        'seccionador': 'Q',
        'diferencial': 'Q',
        'contactor': 'QA',
        'variador': 'QA',
        'sst': 'QA',
        'vdf': 'QA',

        'fuse': 'F',
        'fusible': 'F',
        'thermal': 'F',
        'guardamotor': 'QM',
        'phase-monitor': 'F',

        'plc': 'K',
        'cpu': 'K',
        'relay': 'K',
        'rele': 'K',
        'coil': 'K',
        'temporizador': 'KT',

        'motor': 'M',
        'light': 'H',
        'buzzer': 'H',
        'led': 'H',
        'piloto': 'H',

        'selector': 'S',
        'switch': 'S',
        'mushroom': 'S',
        'boton': 'S',
        'pulsador': 'S',

        'sensor': 'B',
        'limit_switch': 'B',
        'encoder': 'B',

        'transformer': 'T',
        'fuente': 'T',
        'power_supply': 'T',
        'terminal': 'X',
        'resistor': 'R',
        'cable': 'W'
    }

    @staticmethod
    def get_default_label_data(component):
        """Retorna el diccionario inicial de datos de etiqueta para un componente."""
        # Esta lógica se llamará desde el __init__ de Component
        # El nombre sugerido se calculará fuera o se pasará aquí
        return {
            'name': '',
            'marca': '',
            'voltaje': '',
            'potencia': '',
            'amperios': '',
            'description': '',
            'show_details': False,
            'derecha': True,
            'terminals': '',
            'ssf_start_time': '10',
            'ssf_stop_time': '10',
            'ssf_init_volt_pct': '30',
            'ssf_rated_volt': '220',
            'vdf_motor_rpm': '1500',
            'vdf_speed_1': '500',
            'vdf_speed_2': '1000',
            'vdf_speed_3': '1500',
            'vdf_max_freq': '60',
            'vdf_min_freq': '0',
            'vdf_accel_ramp': '5',
            'vdf_decel_ramp': '5',
            'vdf_analog_control': '3-wire',
            'vdf_analog_enabled': False,
            'cable_calibre': '',
        }

    @classmethod
    def suggest_name(cls, component, canvas):
        """Sugiere un nombre basado en el tipo de componente y categoría."""
        comp_type = getattr(component, 'component_type', 'normal')
        category = getattr(component, 'category', '')
        comp_name = getattr(component, 'name', '').lower()
        is_preview = getattr(component, 'is_preview', False)

        if comp_type == "fase":
            existing_names = set()
            if hasattr(canvas, 'components'):
                for comp in canvas.components:
                    ld = getattr(comp, 'label_data', {})
                    if ld.get('name') in ['L1', 'L2', 'L3', 'N', 'PE']:
                        existing_names.add(ld['name'])
            for name in ['L1', 'L2', 'L3', 'N', 'PE']:
                if name not in existing_names:
                    return name
            return "L1"

        elif comp_type in ["tierra", "empalme"]:
            return ""

        elif comp_type in ["conxn", "conxn2", "borner"]:
            assigned_letter = "X" if comp_type == "borner" else "L"
            return cls._get_next_numbered_name(assigned_letter, canvas, is_preview)

        # Buscar palabra clave en el diccionario
        assigned_letter = "NN"
        for keyword, letter in cls.KEYWORD_TO_LETTER.items():
            if keyword in comp_name:
                assigned_letter = letter
                break

        return cls._get_next_numbered_name(assigned_letter, canvas, is_preview)

    @classmethod
    def _get_next_numbered_name(cls, letter, canvas, is_preview):
        """Calcula el siguiente número disponible para una letra."""
        app = getattr(canvas, 'app', None)

        # Usar buffer persistente de contadores si no es preview
        if not is_preview and app and hasattr(app, 'label_counters'):
            current_count = app.label_counters.get(letter, 0)
            next_number = current_count + 1
            app.label_counters[letter] = next_number
            return f"{letter}{next_number}"

        # Fallback: conteo dinámico (para preview o si no hay buffer)
        letter_count = 0
        if hasattr(canvas, 'components'):
            for comp in canvas.components:
                ld = getattr(comp, 'label_data', {})
                name = ld.get('name', '')
                if name.startswith(letter):
                    # Evitar conflictos específicos (ej: M vs QA para motores)
                    if letter == 'Q' and name.startswith('QM'): continue
                    if letter == 'L' and any(x in name for x in ['1','2','3','N','PE']): continue

                    rest = name[len(letter):]
                    if rest.isdigit():
                        letter_count = max(letter_count, int(rest))

        return f"{letter}{letter_count + 1}"

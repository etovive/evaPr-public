"""
Módulo centralizado para todos los diálogos de edición de etiquetas.
"""

import tkinter as tk
from tkinter import ttk, messagebox, colorchooser

# Constantes de fuente compartidas (igual que AppConstants.UI_FONT_FAMILY)
_FONT_FAMILY = "Arial"
_FONT        = (_FONT_FAMILY, 8)
_FONT_B      = (_FONT_FAMILY, 8, "bold")

# Dispatcher principal

def open_label_editor(app, component):
    """
    Abre el diálogo de edición correcto según el tipo de componente.

    Parámetros
    ----------
    app: instancia de PlanoElectrico (tiene .root, .canvas, .connections, etc.)
    component: Component, TextComponent u otro objeto con etiqueta editable
    """
    if hasattr(component, "category"):
        # Es un Component SVG — diálogo complejo
        ComponentLabelEditor(app, component)
    else:
        # Es un TextComponent — diálogo simple
        TextLabelEditor(app, component)

# Utilidades internas

def _setup_grab(window):
    """Configura grab_set diferido para evitar TclError en X11."""
    def _try():
        try:
            window.grab_set()
        except tk.TclError:
            window.after(50, _try)
    window.after(10, _try)

def _smart_position(window, app):
    """
    Posiciona la ventana inteligentemente cerca del cursor del ratón,
    asegurando que permanezca dentro de los límites de la pantalla.
    """
    window.withdraw()  # Ocultar mientras calculamos para evitar parpadeo
    window.update_idletasks() # Forzar renderizado para obtener dimensiones reales

    win_w = window.winfo_width()
    win_h = window.winfo_height()
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()

    mouse_x = window.winfo_pointerx()
    mouse_y = window.winfo_pointery()

    # Intentar posicionar un poco a la derecha y abajo del cursor (offset 10px)
    pos_x = mouse_x + 10
    pos_y = mouse_y + 10

    # Ajustar si se sale por la derecha
    if pos_x + win_w > screen_w:
        pos_x = screen_w - win_w - 20

    # Ajustar si se sale por abajo
    if pos_y + win_h > screen_h:
        pos_y = screen_h - win_h - 40

    # Evitar coordenadas negativas
    pos_x = max(0, pos_x)
    pos_y = max(0, pos_y)

    window.geometry(f"+{int(pos_x)}+{int(pos_y)}")
    window.deiconify() # Mostrar ventana ya posicionada
    window.focus_set()
    window.lift()

def _apply_label_and_redraw(app, component, name_var, marca_var, voltaje_var,
                             potencia_var, amperios_var, description_var,
                             terminals_var, show_details_var, derecha_var,
                             calibre_cable_var, fname,
                             ssf_start_time_var, ssf_stop_time_var,
                             ssf_init_volt_pct_var, ssf_rated_volt_var,
                             vdf_motor_rpm_var, vdf_speed_1_var,
                             vdf_speed_2_var, vdf_speed_3_var,
                             vdf_max_freq_var, vdf_min_freq_var,
                             vdf_accel_ramp_var, vdf_decel_ramp_var,
                             vdf_analog_control_var, vdf_analog_enabled_var,
                             lotto_var=None):
    """
    Aplica todos los valores de las StringVar/BooleanVar al label_data del
    componente y dispara redibujado + referencias cruzadas.
    Lógica extraída de save_and_close / auto_save_on_close de evaPr.py.
    """
    def _is_protection(fn):
        kw = ['contactor', 'rele', 'thermal', 'disyuntor', 'diferencial',
              'breaker', 'magnetotermico', 'circuit-breaker']
        return any(k in fn.lower() for k in kw)

    ld = component.label_data

    ld['name']        = name_var.get().strip()
    ld['marca']       = marca_var.get().strip()
    ld['voltaje']     = voltaje_var.get().strip()
    ld['potencia']    = potencia_var.get().strip()
    ld['amperios']    = amperios_var.get().strip()
    ld['description'] = description_var.get().strip()
    ld['terminals']   = terminals_var.get().strip()
    ld['show_details']= show_details_var.get()
    ld['derecha']     = derecha_var.get()

    if _is_protection(fname):
        ld['calibre_cable'] = calibre_cable_var.get().strip()

    if lotto_var is not None and ('selector-3p-no' in fname or 'selector-4p-no' in fname):
        ld['lotto'] = lotto_var.get()

    ld['ssf_start_time']    = ssf_start_time_var.get().strip()
    ld['ssf_stop_time']     = ssf_stop_time_var.get().strip()
    ld['ssf_init_volt_pct'] = ssf_init_volt_pct_var.get().strip()
    ld['ssf_rated_volt']    = ssf_rated_volt_var.get().strip()

    ld['vdf_motor_rpm']      = vdf_motor_rpm_var.get().strip()
    ld['vdf_speed_1']        = vdf_speed_1_var.get().strip()
    ld['vdf_speed_2']        = vdf_speed_2_var.get().strip()
    ld['vdf_speed_3']        = vdf_speed_3_var.get().strip()
    ld['vdf_max_freq']       = vdf_max_freq_var.get().strip()
    ld['vdf_min_freq']       = vdf_min_freq_var.get().strip()
    ld['vdf_accel_ramp']     = vdf_accel_ramp_var.get().strip()
    ld['vdf_decel_ramp']     = vdf_decel_ramp_var.get().strip()
    ld['vdf_analog_control'] = vdf_analog_control_var.get()
    ld['vdf_analog_enabled'] = vdf_analog_enabled_var.get()

    component.clear_label()
    component.load_image(component.svg_path)
    component.draw()
    component.draw_label()

    # Reactividad: actualizar color de líneas conectadas si es N o PE
    try:
        from utils.utility_functions import adapt_color_for_display
        new_name_upper = ld['name'].upper()
        if new_name_upper in ["N", "PE"]:
            for conn in getattr(app, 'connections', []):
                if conn.start_component == component or conn.end_component == component:
                    if new_name_upper == "N":
                        conn.line_color = "#0000FF"
                        conn.line_dash  = ""
                    elif new_name_upper == "PE":
                        conn.line_color = "#008000"
                        conn.line_dash  = "4 2"
                    for line_id in getattr(conn, 'line_ids', []):
                        try:
                            adapted = adapt_color_for_display(
                                conn.line_color, app.canvas.cget("bg"))
                            parsed_dash = app.parse_dash_pattern(conn.line_dash)
                            app.canvas.itemconfig(
                                line_id, fill=adapted, dash=parsed_dash)
                        except Exception:
                            pass
    except Exception:
        pass

    # Referencias cruzadas
    if hasattr(app, 'update_cross_references'):
        app.update_cross_references()

class ComponentLabelEditor:
    """
    Diálogo de edición de etiqueta para objetos Component (SVG).
    Soporta: Fase, Normal, Borner/Conxn, VDF, SSF, Fuente DC/AC, Motor.
    Extraído de evaPr._edit_regular_component_label().
    """

    def __init__(self, app, component):
        self.app       = app
        self.component = component

        self.window = tk.Toplevel(app.root)
        self._build()

    def _build(self):
        comp   = self.component
        app    = self.app
        window = self.window

        fname = comp.svg_file.lower() if hasattr(comp, 'svg_file') else ""

        window.title(f"Editar Etiqueta - {comp.category}")
        window.transient(app.root)
        window.resizable(False, False)
        _setup_grab(window)

        # Tamaño dinámico según tipo de componente
        if "vdf-c" in fname:
            window.geometry("350x580")
        elif "sst-c" in fname:
            window.geometry("320x450")
        elif "power_supply_dc" in fname or "power_supply_ac" in fname:
            window.geometry("320x450")
        else:
            window.geometry("280x380")

        # Variables
        ld = comp.label_data

        self.name_var        = tk.StringVar(value=ld['name'])
        self.marca_var       = tk.StringVar(value=ld['marca'])
        self.voltaje_var     = tk.StringVar(value=ld['voltaje'])
        self.potencia_var    = tk.StringVar(value=ld['potencia'])
        self.amperios_var    = tk.StringVar(value=ld['amperios'])
        self.description_var = tk.StringVar(value=ld.get('description', ''))
        self.show_details_var= tk.BooleanVar(value=ld['show_details'])
        self.derecha_var     = tk.BooleanVar(value=ld.get('derecha', False))
        self.lotto_var       = tk.BooleanVar(value=ld.get('lotto', False))
        self.calibre_cable_var = tk.StringVar(value=ld.get('calibre_cable', ''))

        self.ssf_start_time_var    = tk.StringVar(value=ld.get('ssf_start_time', '10'))
        self.ssf_stop_time_var     = tk.StringVar(value=ld.get('ssf_stop_time', '10'))
        self.ssf_init_volt_pct_var = tk.StringVar(value=ld.get('ssf_init_volt_pct', '30'))
        self.ssf_rated_volt_var    = tk.StringVar(value=ld.get('ssf_rated_volt', '220'))

        self.vdf_motor_rpm_var     = tk.StringVar(value=ld.get('vdf_motor_rpm', '1500'))
        self.vdf_speed_1_var       = tk.StringVar(value=ld.get('vdf_speed_1', '500'))
        self.vdf_speed_2_var       = tk.StringVar(value=ld.get('vdf_speed_2', '1000'))
        self.vdf_speed_3_var       = tk.StringVar(value=ld.get('vdf_speed_3', '1500'))
        self.vdf_max_freq_var      = tk.StringVar(value=ld.get('vdf_max_freq', '60'))
        self.vdf_min_freq_var      = tk.StringVar(value=ld.get('vdf_min_freq', '0'))
        self.vdf_accel_ramp_var    = tk.StringVar(value=ld.get('vdf_accel_ramp', '5'))
        self.vdf_decel_ramp_var    = tk.StringVar(value=ld.get('vdf_decel_ramp', '5'))
        self.vdf_analog_control_var= tk.StringVar(value=ld.get('vdf_analog_control', '3-wire'))
        self.vdf_analog_enabled_var= tk.BooleanVar(value=ld.get('vdf_analog_enabled', False))

        # Terminals: extraer del SVG si está vacío
        current_terminals = ld.get('terminals', '')
        if not current_terminals and hasattr(comp, 'extract_terminal_labels_from_svg'):
            current_terminals = comp.extract_terminal_labels_from_svg()
            ld['terminals'] = current_terminals
        self.terminals_var = tk.StringVar(value=current_terminals)

        # Frame principal (scrollable si VDF)
        main_frame = tk.Frame(window, padx=20, pady=20)
        main_frame.pack(fill="both", expand=True)
        main_frame.columnconfigure(1, weight=1)

        current_row = self._build_fields(main_frame, comp, fname, current_row=0)

        # Botones
        btn_frame = tk.Frame(window)
        btn_frame.pack(side="bottom", fill="x", padx=20, pady=(0, 20))

        # Botón Sugerir (solo para componentes de protección)
        if self._is_protection(fname):
            tk.Button(
                btn_frame, text="Sugerir",
                font=_FONT_B,
                bg="#1565C0", fg="white",
                activebackground="#0D47A1", activeforeground="white",
                relief="flat", cursor="hand2", padx=8, pady=3,
                command=self._on_sugerir
            ).pack(side="left")

        # Snapshot para revertir con ESC (solo protecciones)
        if self._is_protection(fname):
            self._orig_snap = {
                'description':   self.description_var.get(),
                'marca':         self.marca_var.get(),
                'voltaje':       self.voltaje_var.get(),
                'amperios':      self.amperios_var.get(),
                'potencia':      self.potencia_var.get(),
                'calibre_cable': self.calibre_cable_var.get(),
            }
            self._brand_idx = 0   # contador de rotación de marcas
            window.bind("<Escape>", self._revert_sugerencia)

        # Protocolo de cierre -> auto-guardado
        window.protocol("WM_DELETE_WINDOW", self._auto_save_and_close)

        # Posicionamiento inteligente
        _smart_position(window, app)

    def _is_protection(self, fname):
        kw = ['contactor', 'rele', 'thermal', 'disyuntor', 'diferencial',
              'breaker', 'magnetotermico', 'circuit-breaker']
        return any(k in fname.lower() for k in kw)

    def _build_fields(self, parent, comp, fname, current_row):
        """Construye todos los campos del formulario. Retorna la fila final."""

        # Campo Nombre
        tk.Label(parent, text="Nombre (ID):", font=_FONT_B).grid(
            row=current_row, column=0, sticky="w", pady=5)

        if comp.component_type == "fase":
            fase_options = ["L1", "L2", "L3", "N", "PE"]
            name_widget = ttk.Combobox(
                parent, textvariable=self.name_var,
                values=fase_options, font=_FONT,
                width=23, state="readonly")
            name_widget.grid(row=current_row, column=1,
                             sticky="ew", pady=5, padx=(10, 0))
            name_widget.focus_set()
        else:
            name_entry = tk.Entry(parent, textvariable=self.name_var,
                                  font=_FONT, width=25)
            name_entry.grid(row=current_row, column=1,
                            sticky="ew", pady=5, padx=(10, 0))
            name_entry.focus_set()
        current_row += 1

        # N.Terminal (solo para "normal")
        if comp.component_type == "normal":
            tk.Label(parent, text="N.Terminal:", font=_FONT).grid(
                row=current_row, column=0, sticky="w", pady=5)
            tk.Entry(parent, textvariable=self.terminals_var,
                     font=_FONT, width=25).grid(
                row=current_row, column=1, sticky="ew", pady=5, padx=(10, 0))
            current_row += 1

            # Checkbox mostrar detalles
            tk.Checkbutton(
                parent, text="Mostrar campos adicionales",
                variable=self.show_details_var, font=_FONT
            ).grid(row=current_row, column=0, columnspan=2, sticky="w", pady=5)
            current_row += 1

        # Checkbox "Derecha"
        if comp.component_type in ["normal", "conxn", "conxn2", "borner"]:
            is_lotto_svg = fname in ["selector-3p-no.svg", "selector-4p-no.svg"]
            if is_lotto_svg:
                tk.Checkbutton(
                    parent, text="Derecha",
                    variable=self.derecha_var, font=_FONT
                ).grid(row=current_row, column=0, sticky="w", pady=5)
                tk.Checkbutton(
                    parent, text="LOTTO",
                    variable=self.lotto_var, font=_FONT
                ).grid(row=current_row, column=1, sticky="w", pady=5)
            else:
                tk.Checkbutton(
                    parent, text="Derecha",
                    variable=self.derecha_var, font=_FONT
                ).grid(row=current_row, column=0, columnspan=2, sticky="w", pady=5)
            current_row += 1

        # Campos adicionales para componentes normales
        if comp.component_type == "normal":
            # Separador
            tk.Frame(parent, height=1, bg="gray").grid(
                row=current_row, column=0, columnspan=2, sticky="ew", pady=5)
            current_row += 1

            tk.Label(parent, text="Descripcion:", font=_FONT).grid(
                row=current_row, column=0, sticky="w", pady=2)
            tk.Entry(parent, textvariable=self.description_var,
                     font=_FONT, width=25).grid(
                row=current_row, column=1, sticky="ew", pady=2, padx=(10, 0))
            current_row += 1

            tk.Label(parent, text="Marca:", font=_FONT).grid(
                row=current_row, column=0, sticky="w", pady=2)
            tk.Entry(parent, textvariable=self.marca_var,
                     font=_FONT, width=25).grid(
                row=current_row, column=1, sticky="ew", pady=2, padx=(10, 0))
            current_row += 1

            # Voltaje (etiqueta dinámica + widget según tipo)
            if "power_supply_dc" in fname:
                v_label = "Voltaje DC:"
            elif "power_supply_ac" in fname:
                v_label = "Voltaje AC:"
            else:
                v_label = "Voltaje:"

            tk.Label(parent, text=v_label, font=_FONT).grid(
                row=current_row, column=0, sticky="w", pady=2)

            if "power_supply_ac" in fname:
                ac_voltages = ["12V AC", "24V AC", "36V AC", "48V AC"]
                ttk.Combobox(parent, textvariable=self.voltaje_var,
                             values=ac_voltages, font=_FONT,
                             state="readonly", width=23).grid(
                    row=current_row, column=1, sticky="ew",
                    pady=2, padx=(10, 0))
            else:
                tk.Entry(parent, textvariable=self.voltaje_var,
                         font=_FONT, width=25).grid(
                    row=current_row, column=1, sticky="ew",
                    pady=2, padx=(10, 0))
            current_row += 1

            tk.Label(parent, text="Amperios:", font=_FONT).grid(
                row=current_row, column=0, sticky="w", pady=2)
            tk.Entry(parent, textvariable=self.amperios_var,
                     font=_FONT, width=25).grid(
                row=current_row, column=1, sticky="ew", pady=2, padx=(10, 0))
            current_row += 1

            # Calibre cable (solo lectura, solo para protecciones)
            if self._is_protection(fname):
                tk.Label(parent, text="Calibre Cable:", font=_FONT,
                         fg="#000000").grid(
                    row=current_row, column=0, sticky="w", pady=2)
                tk.Entry(parent, textvariable=self.calibre_cable_var,
                         font=(_FONT_FAMILY, 8, "bold"),
                         width=25, state="readonly", relief="flat",
                         readonlybackground="#fce4e4", fg="#c62828").grid(
                    row=current_row, column=1, sticky="ew",
                    pady=2, padx=(10, 0))
                current_row += 1

            # Potencia + cálculo automático para fuente DC
            if "power_supply_dc" in fname:
                tk.Label(parent, text="Potencia (Watts):", font=_FONT).grid(
                    row=current_row, column=0, sticky="w", pady=2)
                tk.Entry(parent, textvariable=self.potencia_var,
                         font=_FONT, width=25, state="readonly").grid(
                    row=current_row, column=1, sticky="ew",
                    pady=2, padx=(10, 0))
                current_row += 1

                def _calc_watts(*_):
                    try:
                        v = float(self.voltaje_var.get())
                        a = float(self.amperios_var.get())
                        self.potencia_var.set(str(v * a))
                    except ValueError:
                        pass

                self.voltaje_var.trace_add("write", _calc_watts)
                self.amperios_var.trace_add("write", _calc_watts)
                _calc_watts()

            if comp.category == 'Motors' and "power_supply_dc" not in fname:
                tk.Label(parent, text="Potencia:", font=_FONT).grid(
                    row=current_row, column=0, sticky="w", pady=2)
                tk.Entry(parent, textvariable=self.potencia_var,
                         font=_FONT, width=25).grid(
                    row=current_row, column=1, sticky="ew",
                    pady=2, padx=(10, 0))
                current_row += 1

            # SSF (Soft Starter)
            if "sst-c" in fname:
                tk.Label(parent, text="PARAMETROS SSF",
                         font=(_FONT_FAMILY, 8, "bold"),
                         fg="#2980b9").grid(
                    row=current_row, column=0, columnspan=2,
                    sticky="w", pady=(10, 5))
                current_row += 1

                ssf_fields = [
                    ("START TIME (seg):", self.ssf_start_time_var),
                    ("STOP TIME (seg):",  self.ssf_stop_time_var),
                    ("INIT VOLTAGE %:",   self.ssf_init_volt_pct_var),
                    ("RATED VOLTAGE V:",  self.ssf_rated_volt_var),
                ]
                for lbl, var in ssf_fields:
                    tk.Label(parent, text=lbl, font=_FONT).grid(
                        row=current_row, column=0, sticky="w", pady=2)
                    tk.Entry(parent, textvariable=var,
                             font=_FONT, width=25).grid(
                        row=current_row, column=1, sticky="ew",
                        pady=2, padx=(10, 0))
                    current_row += 1

            # VDF (Variador de Frecuencia)
            if "vdf-c" in fname:
                tk.Label(parent, text="PARAMETROS VDF",
                         font=(_FONT_FAMILY, 8, "bold"),
                         fg="#2980b9").grid(
                    row=current_row, column=0, columnspan=2,
                    sticky="w", pady=(10, 5))
                current_row += 1

                vdf_fields = [
                    ("Motor RPM:",      self.vdf_motor_rpm_var),
                    ("Velocidad 1:",    self.vdf_speed_1_var),
                    ("Velocidad 2:",    self.vdf_speed_2_var),
                    ("Velocidad 3:",    self.vdf_speed_3_var),
                    ("Frec Max (Hz):",  self.vdf_max_freq_var),
                    ("Frec Min (Hz):",  self.vdf_min_freq_var),
                    ("Rampa Acc (s):",  self.vdf_accel_ramp_var),
                    ("Rampa Dec (s):",  self.vdf_decel_ramp_var),
                ]
                for lbl, var in vdf_fields:
                    tk.Label(parent, text=lbl, font=_FONT).grid(
                        row=current_row, column=0, sticky="w", pady=2)
                    tk.Entry(parent, textvariable=var,
                             font=_FONT, width=25).grid(
                        row=current_row, column=1, sticky="ew",
                        pady=2, padx=(10, 0))
                    current_row += 1

                tk.Label(parent, text="Control Analog:", font=_FONT).grid(
                    row=current_row, column=0, sticky="w", pady=2)
                ttk.Combobox(
                    parent, textvariable=self.vdf_analog_control_var,
                    values=["2-wire", "3-wire"],
                    font=_FONT, state="readonly", width=22
                ).grid(row=current_row, column=1, sticky="ew",
                       pady=2, padx=(10, 0))
                current_row += 1

                tk.Checkbutton(
                    parent, text="Habilitar Control Analógico",
                    variable=self.vdf_analog_enabled_var, font=_FONT
                ).grid(row=current_row, column=0, columnspan=2,
                       sticky="w", pady=2)
                current_row += 1

        elif comp.component_type not in ["conxn", "conxn2", "borner"]:
            # Componentes especiales: fase, tierra, empalme -> info informativa
            info_map = {
                "fase":    "Fase eléctrica - Selecciona L1, L2, L3, N o PE",
                "tierra":  "Tierra - No requiere etiqueta",
                "empalme": "Empalme - No requiere etiqueta",
            }
            tk.Label(
                parent,
                text=info_map.get(comp.component_type, "Componente especial"),
                font=(_FONT_FAMILY, 8, "italic"), fg="gray"
            ).grid(row=current_row, column=0, columnspan=2,
                   sticky="w", pady=10)
            current_row += 1

        return current_row

    def _get_all_vars(self):
        """Devuelve tupla con todas las variables en el mismo orden que _apply_label_and_redraw."""
        return (
            self.name_var, self.marca_var, self.voltaje_var,
            self.potencia_var, self.amperios_var, self.description_var,
            self.terminals_var, self.show_details_var, self.derecha_var,
            self.calibre_cable_var,
            self.ssf_start_time_var, self.ssf_stop_time_var,
            self.ssf_init_volt_pct_var, self.ssf_rated_volt_var,
            self.vdf_motor_rpm_var, self.vdf_speed_1_var,
            self.vdf_speed_2_var, self.vdf_speed_3_var,
            self.vdf_max_freq_var, self.vdf_min_freq_var,
            self.vdf_accel_ramp_var, self.vdf_decel_ramp_var,
            self.vdf_analog_control_var, self.vdf_analog_enabled_var,
            self.lotto_var,
        )

    def _apply(self):
        fname = self.component.svg_file.lower() if hasattr(self.component, 'svg_file') else ""
        (nv, mv, vv, pv, av, dv, tv, sdv, drv, ccv,
         ss1, ss2, ss3, ss4,
         vr, v1, v2, v3, vf1, vf2, va1, va2, vac, vae, lotto_var) = self._get_all_vars()
        _apply_label_and_redraw(
            self.app, self.component,
            nv, mv, vv, pv, av, dv, tv, sdv, drv, ccv, fname,
            ss1, ss2, ss3, ss4,
            vr, v1, v2, v3, vf1, vf2, va1, va2, vac, vae, lotto_var
        )

    def _auto_save_and_close(self):
        """Auto-guarda si el nombre no está vacío y cierra."""
        if self.name_var.get().strip():
            self._apply()
        self.window.destroy()

    def _revert_sugerencia(self, event=None):
        """Revierte los campos de sugerencia a sus valores originales (ESC)."""
        snap = self._orig_snap
        self.description_var.set(snap['description'])
        self.marca_var.set(snap['marca'])
        self.voltaje_var.set(snap['voltaje'])
        self.amperios_var.set(snap['amperios'])
        self.potencia_var.set(snap['potencia'])
        self.calibre_cable_var.set(snap['calibre_cable'])
        self._brand_idx = 0   # reiniciar rotación al revertir

    def _on_sugerir(self):
        """Botón Sugerir: rota entre Schneider -> ABB -> Siemens -> Chint -> LS -> WEG en cada click."""
        import re as _re
        try:
            from core.protection_suggestions import (
                ProtectionSuggestionEngine,
                get_component_keyword,
                _next_breaker, _select_contactor,
                _model_name, _cable_section,
                _is_dc_source_component,
                BRAND_ROTATION,
            )
        except ImportError as e:
            messagebox.showerror("Error", f"No se pudo importar motor de sugerencias:\n{e}")
            return

        app       = self.app
        component = self.component

        # Determinar marca activa y avanzar el contador
        current_brand = BRAND_ROTATION[self._brand_idx % len(BRAND_ROTATION)]
        self._brand_idx += 1

        engine = ProtectionSuggestionEngine(app, component)
        result = engine.run()
        if not result:
            messagebox.showinfo("Sugerir", "No se encontró motor conectado.")
            return

        kw_type   = get_component_keyword(component)
        desc_text = result.get('description', '')

        # Breaker Principal: sumar amperios de todas las cargas
        if desc_text == "Breaker Principal":
            total_a = 0.0
            for c in getattr(app, 'components', []):
                ld   = getattr(c, 'label_data', {}) or {}
                cat  = getattr(c, 'category', '')
                cname= (ld.get('name', '') or getattr(c, 'name', '')).upper()
                is_load = (cat == 'Motors' or 'MOTOR' in cname or
                           any(b in cname for b in
                               ['BOMBA', 'DOSIFICADORA', 'SUMERGIBLE', 'IMPULSORA']))
                if is_load:
                    m = _re.search(r'[\d.,]+', str(ld.get('amperios', '') or ''))
                    if m:
                        try:
                            total_a += float(m.group().replace(',', '.'))
                        except ValueError:
                            pass

            if total_a > 0:
                calibre_a = _next_breaker(total_a * 1.55)
                modelo    = _model_name('breaker', calibre_a, current_brand)
                self.description_var.set(modelo)
                self.amperios_var.set(f"{calibre_a}")
                self.marca_var.set(current_brand)
                self.calibre_cable_var.set(_cable_section(calibre_a))
                if hasattr(app, 'set_status'):
                    app.set_status(
                        f"✅ {modelo} | suma={total_a:.1f}A → {calibre_a}A", "blue")
            else:
                self.description_var.set("Breaker Principal")
                self.marca_var.set(current_brand)
                if hasattr(app, 'set_status'):
                    app.set_status(
                        "✅ Breaker Principal (sin cargas con amperios)", "orange")
            return

        # Protección de rama: datos directos del motor
        charge_comp = getattr(engine, 'last_charge_component', None)
        if charge_comp is None:
            # Sin motor: ¿es una línea de control? Sumar VA
            ctrl = engine.compute_control_breaker()
            if ctrl and ctrl.get('breaker'):
                b      = ctrl['breaker']
                modelo = _model_name('breaker', b, current_brand)
                self.description_var.set(modelo)
                self.amperios_var.set(f"{b}")
                self.marca_var.set(current_brand)
                self.calibre_cable_var.set(_cable_section(ctrl['current']))
                if hasattr(app, 'set_status'):
                    app.set_status(
                        f"✅ {modelo} | Σ{ctrl['total_va']:.0f}VA @ "
                        f"{ctrl['voltage']:.0f}V → "
                        f"{ctrl['current']*1000:.0f}mA | cable "
                        f"{_cable_section(ctrl['current'])}", "blue")
            else:
                self.description_var.set(desc_text)
                self.marca_var.set(current_brand)
                if hasattr(app, 'set_status'):
                    app.set_status(f"✅ {desc_text} (sin cargas con amperios)", "orange")
            return

        # Fuente DC (POWER_SUPPLY_DC): la etiqueta es la SALIDA (ej. 24 V DC). El
        # breaker protege la ENTRADA (110/220 V), así que se convierte la potencia
        # con la eficiencia (80%) y se usa el peor caso de tensión (110 V).
        # NO aplica a fuentes AC ni a transformadores.
        if _is_dc_source_component(charge_comp):
            src = engine.compute_source_breaker()
            if src:
                calibre_a = _next_breaker(src['current'] * 1.55)
                modelo    = _model_name('breaker', calibre_a, current_brand)
                self.description_var.set(modelo)
                self.amperios_var.set(f"{calibre_a}")
                self.marca_var.set(current_brand)
                self.voltaje_var.set(f"{src['voltage']:.0f}")
                self.calibre_cable_var.set(_cable_section(src['current']))
                if hasattr(app, 'set_status'):
                    app.set_status(
                        f"✅ {modelo} | salida {src['p_out']:.0f}W @ "
                        f"{int(src['efficiency']*100)}% → entrada "
                        f"{src['current']:.2f}A @ {src['voltage']:.0f}V | cable "
                        f"{_cable_section(src['current'])}", "blue")
                return

        ld_m    = getattr(charge_comp, 'label_data', {}) or {}
        m_a     = _re.search(r'[\d.,]+', str(ld_m.get('amperios', '') or ''))
        try:
            I_motor = float(m_a.group().replace(',', '.')) if m_a else None
        except ValueError:
            I_motor = None
        raw_v   = str(ld_m.get('voltaje', '') or '').strip()
        raw_p   = str(ld_m.get('potencia', '') or '').strip()

        if I_motor is None:
            self.description_var.set(desc_text)
            self.marca_var.set(current_brand)
            if hasattr(app, 'set_status'):
                app.set_status(f"✅ {desc_text} (motor sin amperios)", "orange")
            return

        I_brk = I_motor * 1.55
        if kw_type == 'contactor':
            calibre_a = _select_contactor(I_motor, current_brand)
            modelo    = _model_name('contactor', calibre_a, current_brand)
        elif kw_type in ('rele', 'relay', 'thermal'):
            calibre_a = I_motor
            modelo    = _model_name('thermal', I_motor, current_brand)
        elif kw_type in ('guardamotor', 'guardomotor'):
            calibre_a = I_motor
            modelo    = _model_name('guardamotor', I_motor, current_brand)
        else:
            calibre_a = _next_breaker(I_brk)
            modelo    = _model_name('breaker', calibre_a, current_brand)

        self.description_var.set(modelo)
        self.voltaje_var.set(raw_v if raw_v else self.voltaje_var.get())
        self.amperios_var.set(
            f"{calibre_a:.0f}" if isinstance(calibre_a, float) else f"{calibre_a}")
        self.potencia_var.set(raw_p if raw_p else self.potencia_var.get())
        self.marca_var.set(current_brand)
        self.calibre_cable_var.set(_cable_section(I_motor))

        if hasattr(app, 'set_status'):
            app.set_status(
                f"✅ {modelo} | {I_motor}A | cable {_cable_section(I_motor)}", "blue")

class TextLabelEditor:
    """
    Diálogo de edición para TextComponent (texto libre en canvas).
    Extraído de evaPr._edit_text_component_label().
    """

    def __init__(self, app, component):
        self.app       = app
        self.component = component

        self.window = tk.Toplevel(app.root)
        self._build()

    def _build(self):
        comp   = self.component
        window = self.window

        window.title("Editar Texto Completo")
        window.geometry("350x430")
        window.transient(self.app.root)
        window.resizable(False, False)
        _setup_grab(window)

        main_frame = tk.Frame(window, padx=20, pady=20)
        main_frame.pack(fill="both", expand=True)

        # Texto
        text_frame = tk.LabelFrame(
            main_frame, text="Contenido del Texto",
            font=(_FONT_FAMILY, 10, "bold"))
        text_frame.pack(fill="x", pady=(0, 10))

        self.text_var = tk.StringVar(value=comp.text)
        tk.Label(text_frame, text="Texto:",
                 font=_FONT_B).pack(pady=(5, 2))
        tk.Entry(text_frame, textvariable=self.text_var,
                 font=(_FONT_FAMILY, 11), width=30).pack(pady=(0, 5))

        # Fuente
        font_frame = tk.LabelFrame(
            main_frame, text="Fuente",
            font=(_FONT_FAMILY, 10, "bold"))
        font_frame.pack(fill="x", pady=(0, 10))

        self.font_var = tk.StringVar(
            value=getattr(comp, 'current_font', 'Arial'))
        available_fonts = ["Arial", "Times", "Helvetica",
                           "Courier", "Georgia", "Verdana"]
        tk.Label(font_frame, text="Fuente:",
                 font=_FONT_B).pack(anchor="w", padx=10)
        ttk.Combobox(font_frame, textvariable=self.font_var,
                     values=available_fonts, state="readonly",
                     width=25).pack(padx=10, pady=(2, 5))

        # Tamaño
        size_frame = tk.LabelFrame(
            main_frame, text="Tamaño de Fuente",
            font=(_FONT_FAMILY, 10, "bold"))
        size_frame.pack(fill="x", pady=(0, 10))

        self.size_var = tk.StringVar(value=str(comp.font_size))
        tk.Label(size_frame, text="Tamaño:",
                 font=_FONT_B).pack(anchor="w", padx=10)

        size_controls = tk.Frame(size_frame)
        size_controls.pack(fill="x", padx=10, pady=(2, 5))
        tk.Button(size_controls, text="-", width=3,
                  command=lambda: self._change_size(-1)).pack(side="left")
        tk.Spinbox(size_controls, from_=6, to=72,
                   textvariable=self.size_var,
                   width=5, justify="center").pack(side="left", padx=10)
        tk.Button(size_controls, text="+", width=3,
                  command=lambda: self._change_size(1)).pack(side="left")

        # Color
        color_frame = tk.LabelFrame(
            main_frame, text="Color del Texto",
            font=(_FONT_FAMILY, 10, "bold"))
        color_frame.pack(fill="x", pady=(0, 10))

        self.color_var = tk.StringVar(value=comp.color)
        tk.Label(color_frame, text="Color:",
                 font=_FONT_B).pack(anchor="w", padx=10)

        color_controls = tk.Frame(color_frame)
        color_controls.pack(fill="x", padx=10, pady=(2, 5))

        predefined = ["black", "white", "red", "blue", "green",
                      "orange", "purple", "brown", "gray", "custom"]
        ttk.Combobox(color_controls, textvariable=self.color_var,
                     values=predefined, state="readonly",
                     width=20).pack(side="left")
        tk.Button(color_controls, text="Selector",
                  command=self._open_color_picker).pack(side="left", padx=5)

        # Botones
        btn_frame = tk.Frame(main_frame)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Aplicar",
                  command=self._save_and_close,
                  bg="#4CAF50", fg="white", width=10).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Cancelar",
                  command=window.destroy,
                  bg="#f44336", fg="white", width=10).pack(side="left", padx=5)

        # Posicionamiento inteligente
        _smart_position(window, self.app)

    def _change_size(self, delta):
        try:
            current = int(self.size_var.get())
            new_val = max(6, min(72, current + delta))
            self.size_var.set(str(new_val))
        except ValueError:
            pass

    def _open_color_picker(self):
        color = colorchooser.askcolor(
            initialcolor=self.component.color, title="Seleccionar Color")
        if color[1]:
            self.color_var.set(color[1])

    def _save_and_close(self):
        new_text = self.text_var.get().strip()
        if not new_text:
            messagebox.showerror("Error", "El texto no puede estar vacío")
            return

        try:
            new_size = int(self.size_var.get())
            if not (6 <= new_size <= 72):
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "El tamaño debe ser un número entre 6 y 72")
            return

        self.component.update_text(new_text)
        self.component.update_font_size(new_size)
        self.component.update_font(self.font_var.get())
        self.component.update_color(self.color_var.get())

        if hasattr(self.app, 'update_cross_references'):
            self.app.update_cross_references()

        self.window.destroy()

class ShieldingLabelEditor:
    """
    Diálogo de edición para objetos Shielding (apantallamiento de cable).
    - Se graba automáticamente al cerrar (igual que ComponentLabelEditor).
    - ESC restaura los valores originales sin guardar.
    - Sin botones Aplicar / Cancelar.
    """

    def __init__(self, app, shielding):
        self.app       = app
        self.shielding = shielding

        self.window = tk.Toplevel(app.root)
        self._build()

    def _build(self):
        sh     = self.shielding
        window = self.window

        try:
            from config.settings import AppConstants
            _fam = AppConstants.UI_FONT_FAMILY
        except ImportError:
            _fam = _FONT_FAMILY

        window.title("Editar Etiqueta - Apantallamiento")
        window.geometry("280x380")
        window.transient(self.app.root)
        window.resizable(False, False)
        _setup_grab(window)

        main_frame = tk.Frame(window, padx=20, pady=20)
        main_frame.pack(fill="both", expand=True)

        # Variables
        self.wires_var   = tk.StringVar(value=str(sh.num_wires))
        self.gauge_var   = tk.StringVar(value=sh.get_awg_equivalent())
        self.awg_var     = tk.StringVar(value=f"({sh.gauge} mm²)")
        self.voltage_var = tk.StringVar(value=getattr(sh, 'voltage', '300/500V'))
        self.name_var    = tk.StringVar(value=sh.cable_name)

        # Snapshot para ESC
        self._orig = {
            'num_wires':  sh.num_wires,
            'gauge':      sh.gauge,
            'voltage':    getattr(sh, 'voltage', '300/500V'),
            'cable_name': sh.cable_name,
        }

        FONT   = (_fam, 8)

        # Grupo Datos del Cable
        cable_frame = tk.LabelFrame(
            main_frame, text="Configuración de Cable",
            font=(_fam, 10), padx=10, pady=10)
        cable_frame.pack(fill="x", pady=(0, 10))
        cable_frame.columnconfigure(1, weight=1)

        tk.Label(cable_frame, text="Número de hilos:", font=FONT).grid(
            row=0, column=0, sticky="w", pady=2)
        tk.Entry(cable_frame, textvariable=self.wires_var, font=FONT).grid(
            row=0, column=1, sticky="ew", padx=(5, 0))

        # Calibre AWG: se muestra en AWG para la etiqueta y se convierte internamente a mm².
        tk.Label(cable_frame, text="Calibre AWG:", font=FONT).grid(
            row=1, column=0, sticky="w", pady=2)
        gauge_frame = tk.Frame(cable_frame)
        gauge_frame.grid(row=1, column=1, sticky="ew", padx=(5, 0))
        tk.Entry(gauge_frame, textvariable=self.gauge_var, font=FONT, width=6).pack(
            side="left")
        self._awg_lbl = tk.Label(gauge_frame, textvariable=self.awg_var,
                                 font=(_fam, 8, "italic"), fg="#c62828")
        self._awg_lbl.pack(side="left", padx=(4, 0))

        def _update_awg(*_):
            try:
                awg_float = float(self.gauge_var.get().replace(',', '.'))
                mm2_value = sh.awg_to_mm2(awg_float)
                mm2_text = str(mm2_value).rstrip('0').rstrip('.') if '.' in str(mm2_value) else str(mm2_value)
                self.awg_var.set(f"({mm2_text} mm²)")
            except Exception:
                self.awg_var.set("(? mm²)")

        self.gauge_var.trace_add("write", _update_awg)
        _update_awg()  # inicializar al abrir

        tk.Label(cable_frame, text="Tensión nominal:", font=FONT).grid(
            row=2, column=0, sticky="w", pady=2)
        ttk.Combobox(
            cable_frame, textvariable=self.voltage_var,
            values=["300/500V", "450/750V", "0.6/1kV"],
            font=FONT, width=15
        ).grid(row=2, column=1, sticky="ew", padx=(5, 0))

        # Nombre del Cable
        name_frame = tk.LabelFrame(
            main_frame, text="Nombre del Cable",
            font=(_fam, 10), padx=10, pady=10)
        name_frame.pack(fill="x", pady=(0, 10))

        name_entry = tk.Entry(name_frame, textvariable=self.name_var, font=FONT)
        name_entry.pack(fill="x")
        name_entry.focus_set()

        # Comportamiento: grabar al cerrar, ESC revierte
        window.protocol("WM_DELETE_WINDOW", self._save_and_close)
        window.bind("<Escape>", self._revert)

        # Posicionamiento inteligente
        _smart_position(window, self.app)

    def _revert(self, event=None):
        """Restaura los valores originales y cierra sin guardar."""
        orig = self._orig
        self.wires_var.set(str(orig['num_wires']))
        self.gauge_var.set(str(orig['gauge']).replace('.', ','))
        self.voltage_var.set(orig['voltage'])
        self.name_var.set(orig['cable_name'])
        self.window.destroy()

    def _save_and_close(self):
        sh = self.shielding
        try:
            sh.num_wires  = int(self.wires_var.get())
        except ValueError:
            pass
        try:
            awg_value = float(self.gauge_var.get().replace(',', '.'))
            sh.gauge = sh.awg_to_mm2(awg_value)
        except ValueError:
            pass
        sh.voltage    = self.voltage_var.get()
        sh.cable_name = self.name_var.get().strip()
        sh.update_header_from_fields()

        if hasattr(sh, 'redraw'):
            sh.redraw()
        elif hasattr(self.app, 'shielding_manager') and \
             hasattr(self.app.shielding_manager, 'redraw'):
            self.app.shielding_manager.redraw(sh)
        else:
            sh.draw(self.app.canvas)

        if hasattr(self.app, 'update_cross_references'):
            self.app.update_cross_references()

        self.window.destroy()

class BlockTerminalLabelEditor:
    """
    Diálogo de edición para Block Terminals (bt dict).
    Extraído de EventHandler._open_bt_label_dialog().
    """

    def __init__(self, app, bt):
        self.app = app
        self.bt  = bt

        self.window = tk.Toplevel(getattr(app, 'root', None))
        self._build()
        self.window.wait_window()

    def _build(self):
        bt     = self.bt
        app    = self.app
        window = self.window

        root_win = getattr(app, 'root', None)
        window.title("Editar Etiqueta - Block Terminal")
        window.geometry("280x330")
        if root_win:
            window.transient(root_win)
        window.resizable(False, False)
        _setup_grab(window)

        main_frame = tk.Frame(window, padx=20, pady=20)
        main_frame.pack(fill='both', expand=True)

        ld = bt['label_data']

        # Variables
        self.name_var  = tk.StringVar(value=ld.get('name', ''))
        self.desc_var  = tk.StringVar(value=ld.get('description', ''))
        self.marca_var = tk.StringVar(value=ld.get('marca', ''))
        self.amp_var   = tk.StringVar(value=ld.get('amperios', '') or '160A')
        self.division_var = tk.StringVar(value=ld.get('division', 'Sin división'))

        row = 0

        tk.Label(main_frame, text="Nombre (ID):", font=_FONT_B).grid(
            row=row, column=0, sticky='w', pady=5)
        name_entry = tk.Entry(main_frame, textvariable=self.name_var,
                              font=_FONT, width=25)
        name_entry.grid(row=row, column=1, sticky='ew', pady=5, padx=(10, 0))
        name_entry.focus_set()
        row += 1

        tk.Label(main_frame, text="Descripcion:", font=_FONT).grid(
            row=row, column=0, sticky='w', pady=2)
        tk.Entry(main_frame, textvariable=self.desc_var,
                 font=_FONT, width=25).grid(
            row=row, column=1, sticky='ew', pady=2, padx=(10, 0))
        row += 1

        tk.Label(main_frame, text="Marca:", font=_FONT).grid(
            row=row, column=0, sticky='w', pady=2)
        tk.Entry(main_frame, textvariable=self.marca_var,
                 font=_FONT, width=25).grid(
            row=row, column=1, sticky='ew', pady=2, padx=(10, 0))
        row += 1

        # Separador
        tk.Frame(main_frame, height=1, bg='gray').grid(
            row=row, column=0, columnspan=2, sticky='ew', pady=8)
        row += 1

        tk.Label(main_frame, text="Nº de filas:", font=_FONT_B).grid(
            row=row, column=0, sticky='w', pady=2)
        self.filas_var = tk.StringVar()
        filas_cb = ttk.Combobox(main_frame, textvariable=self.filas_var,
                                values=['2 filas', '3 filas', '4 filas'],
                                state='readonly', width=13, font=_FONT)
        filas_cb.set(f"{bt['filas']} filas")
        filas_cb.grid(row=row, column=1, sticky='w', pady=2, padx=(10, 0))
        row += 1

        tk.Label(main_frame, text="Bornas / fila:", font=_FONT_B).grid(
            row=row, column=0, sticky='w', pady=2)
        self.bornas_var = tk.StringVar()
        bornas_cb = ttk.Combobox(main_frame, textvariable=self.bornas_var,
                                 values=['5', '6', '8', '10', '14', '15', '20'],
                                 state='readonly', width=13, font=_FONT)
        bornas_cb.set(str(bt['bornas']))
        bornas_cb.grid(row=row, column=1, sticky='w', pady=2, padx=(10, 0))
        row += 1

        tk.Label(main_frame, text="División:", font=_FONT_B).grid(
            row=row, column=0, sticky='w', pady=2)
        division_cb = ttk.Combobox(main_frame, textvariable=self.division_var,
                                   values=['Sin división', '2P (Doble)', '3P (Triple)', '4P (Cuádruple)'],
                                   state='readonly', width=13, font=_FONT)
        division_cb.grid(row=row, column=1, sticky='w', pady=2, padx=(10, 0))
        row += 1

        tk.Label(main_frame, text="Amperios:", font=_FONT).grid(
            row=row, column=0, sticky='w', pady=2)
        ttk.Combobox(main_frame, textvariable=self.amp_var,
                     values=['80A', '125A', '160A', '250A', '400A', '500A'],
                     font=_FONT, width=23).grid(
            row=row, column=1, sticky='ew', pady=2, padx=(10, 0))

        # Auto-guardado al cerrar
        window.protocol('WM_DELETE_WINDOW',
                        lambda: self._save_and_close(close=True))

        # Posicionamiento inteligente
        _smart_position(window, self.app)

    def _save_and_close(self, close=True):
        bt  = self.bt
        app = self.app

        old_div = bt['label_data'].get('division', 'Sin división')
        new_div = self.division_var.get()

        bt['label_data']['name']        = self.name_var.get().strip()
        bt['label_data']['description'] = self.desc_var.get().strip()
        bt['label_data']['marca']       = self.marca_var.get().strip()
        bt['label_data']['amperios']    = self.amp_var.get().strip()
        bt['label_data']['division']    = new_div

        try:
            new_filas = int(self.filas_var.get().split()[0])
        except Exception:
            new_filas = bt['filas']
        try:
            new_bornas = int(self.bornas_var.get().split()[0])
        except Exception:
            new_bornas = bt['bornas']

        bt['label_data']['bt_filas']  = str(new_filas)
        bt['label_data']['bt_bornas'] = str(new_bornas)

        nombre = bt['label_data']['name']
        try:
            app.canvas.itemconfig(bt['label_id'],
                                  text=nombre if nombre else 'BT?')
        except Exception:
            pass

        if new_filas != bt['filas'] or new_bornas != bt['bornas'] or new_div != old_div:
            old_x, old_y = bt['x'], bt['y']
            saved_ld     = bt['label_data'].copy()
            # El EventHandler original tiene _delete_bt_canvas_ids and _place_block_terminal
            # Se accede a través del EventHandler registrado en app si está disponible
            handler = getattr(app, 'event_handler', None)
            if handler and hasattr(handler, '_delete_bt_canvas_ids'):
                handler._delete_bt_canvas_ids(bt)
                if bt in app.block_terminals:
                    app.block_terminals.remove(bt)
                handler._place_block_terminal(
                    old_x, old_y, new_filas, new_bornas, label_data=saved_ld)

        if hasattr(app, 'save_undo_checkpoint'):
            app.save_undo_checkpoint()

        if close:
            self.window.destroy()

import tkinter as tk

class DrawingPanel:
    """Panel lateral para configuración de estilos de líneas."""

    def __init__(self, parent_frame, line_width_var, line_color_var, line_dash_var, update_callback, text_mode_callback=None, shape_preview_callback=None):
        """
        Inicializa el panel de configuración de líneas.

        Args:
            parent_frame: Frame contenedor donde se creará el panel
            line_width_var: tk.DoubleVar para el grosor de línea
            line_color_var: tk.StringVar para el color de línea
            line_dash_var: tk.StringVar para el tipo de trazo
            update_callback: Función a llamar cuando se actualice algún valor
        """
        self.parent_frame = parent_frame
        self.line_width_var = line_width_var
        self.line_color_var = line_color_var
        self.line_dash_var = line_dash_var
        self.update_callback = update_callback
        self.text_mode_callback = text_mode_callback  # Callback para activar modo texto
        self.shape_preview_callback = shape_preview_callback  # Callback para activar preview de formas

        # Referencias a widgets del panel
        self.panel_frame = None
        self.preview_canvas = None

        # Variables para nuevas funcionalidades
        self.manhattan_enabled = tk.BooleanVar(value=True)
        self.shape_states = {}  # Diccionario para rastrear estado de botones de formas
        self.current_text_size = tk.IntVar(value=12)  # Variable para tamaño de texto

        # Configuración de estilos
        self.width_options = [0.5, 1.0, 1.5, 2.0]
        self.color_options = [
            ("●", "black", "Negro"),
            ("●", "white", "Blanco"), # AGREGADO: Opción blanco para modo oscuro
            ("●", "red", "Rojo"),
            ("●", "green", "Verde"),
            ("●", "blue", "Azul"),
            ("●", "#8B4513", "Café")
        ]
        self.dash_options = [
            ("────", "", "Continuo"),
            ("┅┅┅┅", "(3, 3)", "Punteado"),
            ("┄ ┄ ┄", "(8, 4)", "Cortado")
        ]
        self.shape_options = [
            ("○", "circle", "Círculo"),
            ("□", "square", "Cuadrado"),
            ("▢", "rectangle", "Rectángulo"),
            ("⬭", "ellipse", "Elipse"),
            ("T", "text", "Texto")
        ]
        self.text_size_options = [
            ("8", 8, "8pt"),
            ("12", 12, "12pt"),
            ("20", 20, "20pt")
        ]

        self.create_panel()

    def create_panel(self):
        """Crea el panel lateral para configuración de líneas."""
                # Parent frame {self.parent_frame}")

        self.panel_frame = tk.Frame(
            self.parent_frame, bg="#ffffff", width=150,
            relief=tk.RAISED, borderwidth=1
        )

        self.panel_frame.pack(fill="both", expand=True, padx=1, pady=1)

                # Configurando pack_propagate...")
        self.panel_frame.pack_propagate(False)  # Mantener ancho fijo
                # pack_propagate configurado")

        self._create_title()
        self._create_width_section()
        self._create_color_section()
        self._create_shapes_section()  # Nueva sección de formas
        self._create_dash_section()
        self._create_preview_section()
        self._create_manhattan_section()
        self._create_worksheets_section()  # Nueva sección para hojas de trabajo

        # NO activar ningún botón por defecto - todos apagados inicialmente
                # Actualizando preview final...")
        self.update_preview()
                # Panel de líneas completado exitosamente")

    def _create_title(self):
        """Crea el título del panel."""
        title_label = tk.Label(
            self.panel_frame, text="LÍNEAS", font=("Arial", 9, "bold"),
            bg="#ffffff", fg="#333333"
        )
        title_label.pack(pady=(5, 10))

    def _create_width_section(self):
        """Crea la sección de selección de grosor."""
        tk.Label(
            self.panel_frame, text="Grosor:", font=("Arial", 8), bg="#ffffff"
        ).pack(anchor="w", padx=5)

        width_frame = tk.Frame(self.panel_frame, bg="#ffffff")
        width_frame.pack(fill="x", padx=5, pady=(0, 10))

        for width in self.width_options:
            btn = tk.Radiobutton(
                width_frame, text=str(width), variable=self.line_width_var,
                value=width, font=("Arial", 7), bg="#ffffff",
                command=self.update_preview
            )
            btn.pack(side="left", padx=1)

    def _create_color_section(self):
        """Crea la sección de selección de color."""
        # Frame contenedor horizontal para color y formas
        color_shapes_container = tk.Frame(self.panel_frame, bg="#ffffff")
        color_shapes_container.pack(fill="x", padx=5, pady=(0, 10))

        # Columna de Color (izquierda)
        color_column = tk.Frame(color_shapes_container, bg="#ffffff")
        color_column.pack(side="left", fill="both", expand=True)

        tk.Label(
            color_column, text="Color:", font=("Arial", 8), bg="#ffffff"
        ).pack(anchor="w")

        color_frame = tk.Frame(color_column, bg="#ffffff")
        color_frame.pack(fill="x")

        for symbol, color, name in self.color_options:
            btn = tk.Radiobutton(
                color_frame, text=symbol, variable=self.line_color_var,
                value=color, font=("Arial", 13), fg=color, bg="#ffffff",
                command=self.update_preview
            )
            btn.pack(anchor="w", padx=5, pady=0)
        separator_line = tk.Frame(color_shapes_container, bg="#c3c3c3", width=2)
        separator_line.pack(side="left", fill="y", padx=5)
        # Columna de Formas (derecha)
        shapes_column = tk.Frame(color_shapes_container, bg="#ffffff")
        shapes_column.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(
            shapes_column, text="Formas:", font=("Arial", 8), bg="#ffffff"
        ).pack(anchor="w")

        shapes_frame = tk.Frame(shapes_column, bg="#ffffff")
        shapes_frame.pack(fill="x")

        for symbol, shape, name in self.shape_options:
            btn = tk.Button(
                shapes_frame, text=symbol, font=("Arial", 12), bg="#c3c3c3",
                relief=tk.FLAT, borderwidth=0, width=3,
                command=lambda s=shape: self._toggle_shape_button(s)
            )
            btn.pack(anchor="w", padx=1, pady=0)

            self.shape_states[shape] = {
                'button': btn,
                'active': False
            }
        horizontal_line = tk.Frame(shapes_column, bg="#c3c3c3", height=2, width=50)
        horizontal_line.pack(anchor="w", pady=(2, 0))
        # Sección de texto - aparece cuando se activa el botón de texto
        self.text_size_frame = tk.Frame(self.panel_frame, bg="#ffffff")
        tk.Label(
            self.text_size_frame, text="Texto:", font=("Arial", 8), bg="#ffffff"
        ).pack(anchor="w", padx=5, pady=(5, 0))

        text_sizes_frame = tk.Frame(self.text_size_frame, bg="#ffffff")
        text_sizes_frame.pack(fill="x", padx=5, pady=(0, 5))

        for symbol, size, name in self.text_size_options:
            btn = tk.Radiobutton(
                text_sizes_frame, text=symbol, variable=self.current_text_size,
                value=size, font=("Arial", 10), bg="#ffffff",
                command=self.update_preview
            )
            btn.pack(anchor="w", padx=2)

        # El campo de texto de entrada ha sido eliminado para simplificar el sistema.
        # Al presionar el botón "T" se inserta automáticamente una etiqueta "TEXTO"
        # que se puede editar haciendo doble-click sobre ella.

        self.text_size_frame.pack_forget()

    def _create_shapes_section(self):
        """Crea la sección de selección de formas y texto."""
        # Esta sección ya fue creada dentro de _create_color_section()
        # para colocar las formas junto al color
        pass

    def _toggle_shape_button(self, shape):
        """Activa/desactiva un botón de forma."""
        # Si el botón ya está activo, desactivarlo
        if self.shape_states[shape]['active']:
            self._deactivate_shape_button(shape)
        else:
            # Desactivar todos los botones primero
            for s in self.shape_states:
                if self.shape_states[s]['active']:
                    self._deactivate_shape_button(s)

            # Activar el botón seleccionado
            self._activate_shape_button(shape)

    def _activate_shape_button(self, shape):
        """Activa un botón de forma específico."""
        if shape in self.shape_states:
            btn_info = self.shape_states[shape]
            btn_info['button'].config(bg="#4CAF50", fg="white", relief=tk.SUNKEN)
            btn_info['active'] = True

            # Si es texto, mostrar opciones de texto Y ACTIVAR MODO TEXTO
            if shape == "text" and hasattr(self, 'text_size_frame'):
                self.text_size_frame.pack(fill="x", padx=5, pady=(0, 10))

                # ACTIVAR MODO TEXTO INMEDIATAMENTE con "TEXTO" por defecto
                if self.text_mode_callback:
                    font_size = self.get_current_text_size()
                    text_content = "TEXTO"  # Usar "TEXTO" directamente
                    line_color = self.line_color_var.get() # AGREGADO: Pasar color de línea para texto
                    self.text_mode_callback(text_content, font_size, line_color)
            else:
                if hasattr(self, 'text_size_frame'):
                    self.text_size_frame.pack_forget()
                # Si se desactiva texto, cancelar modo texto
                if self.text_mode_callback:
                    self.text_mode_callback("", 0)

            # ACTIVAR PREVIEW DE FORMA si hay callback disponible
            # Preferir el sistema de dibujo interactivo del EventHandler (primer click + mover + segundo click)
            # Si la app y el event_handler están disponibles, activar shape_drawing allí.
            if hasattr(self, 'app') and hasattr(self.app, 'event_handler') and hasattr(self.app.event_handler, 'shape_drawing') and shape != "text":
                try:
                    self.app.event_handler.shape_drawing.activate(shape)
                except Exception:
                    # Fallback al callback original si algo falla
                    if self.shape_preview_callback:
                        self.shape_preview_callback(shape)
            else:
                if self.shape_preview_callback and shape != "text":
                    self.shape_preview_callback(shape)

            self.update_preview()

    def _deactivate_shape_button(self, shape):
        """Desactiva un botón de forma específico."""
        if shape in self.shape_states:
            btn_info = self.shape_states[shape]
            btn_info['button'].config(bg="#c3c3c3", fg="black", relief=tk.RAISED)
            btn_info['active'] = False

            # Si se desactiva texto, ocultar opciones y cancelar modo texto
            if shape == "text":
                if hasattr(self, 'text_size_frame'):
                    self.text_size_frame.pack_forget()
                if hasattr(self, 'text_mode_callback'):
                    self.text_mode_callback("", 0)  # Cancelar modo texto
            else:
                if hasattr(self, 'text_size_frame'):
                    self.text_size_frame.pack_forget()
                # DESACTIVAR PREVIEW DE FORMA si hay callback disponible
                    # Cancelar el modo de dibujo interactivo si está activo
                    if hasattr(self, 'app') and hasattr(self.app, 'event_handler') and hasattr(self.app.event_handler, 'shape_drawing') and shape != "text":
                        try:
                            self.app.event_handler.shape_drawing.cancel()
                        except Exception:
                            pass

                    # Mantener compatibilidad: notificar al callback original que se canceló
                    if self.shape_preview_callback:
                        self.shape_preview_callback(None, is_manual_cancel=True)  # Pasar None para desactivar

            self.update_preview()

    def _change_text_size(self, size):
        """Cambia el tamaño de fuente y actualiza la selección."""
        self.current_text_size.set(size)

        # MANTENER EL MODO TEXTO ACTIVO después del cambio de tamaño
        if ("text" in self.shape_states and
            self.shape_states["text"]['active'] and
            self.text_mode_callback):
            text_content = "TEXTO"  # Siempre usar "TEXTO"
            line_color = self.line_color_var.get() # AGREGADO: Mantener color de línea
            self.text_mode_callback(text_content, size, line_color)

        self.update_preview()

    def clear_text_mode(self):
        """Desactiva el botón de texto desde la app principal."""
        try:
            if "text" in self.shape_states and self.shape_states["text"]['active']:
                self._deactivate_shape_button("text")
        except Exception:
            pass
    def _create_dash_section(self):
        """Crea la sección de selección de tipo de trazo."""
        tk.Label(
            self.panel_frame, text="Trazo:", font=("Arial", 8), bg="#ffffff"
        ).pack(anchor="w", padx=5)

        dash_frame = tk.Frame(self.panel_frame, bg="#ffffff")
        dash_frame.pack(fill="x", padx=5, pady=(0, 10))

        for symbol, dash_value, name in self.dash_options:
            btn = tk.Radiobutton(
                dash_frame, text=symbol, variable=self.line_dash_var,
                value=dash_value, font=("Arial", 8), bg="#ffffff",
                width=15, anchor="w", command=self.update_preview
            )
            btn.pack(anchor="w", padx=5, fill="x")

    def _create_preview_section(self):
        """Crea la sección de vista previa."""
                # Creando sección de preview...")

        tk.Label(
            self.panel_frame, text="Vista previa:", font=("Arial", 8), bg="#ffffff"
        ).pack(anchor="w", padx=5, pady=(10, 0))

                # Creando preview canvas...")
        self.preview_canvas = tk.Canvas(
            self.panel_frame, height=30, bg="white",
            relief=tk.SUNKEN, borderwidth=1
        )

                # Empaquetando preview canvas...")
        self.preview_canvas.pack(fill="x", padx=5, pady=5)
                # Preview canvas empaquetado empaquetado")

    def _create_manhattan_section(self):
        """Crea la sección para activar/desactivar líneas Manhattan."""
        # Separador
        separator = tk.Frame(self.panel_frame, height=1, bg="#cccccc")
        separator.pack(fill="x", padx=5, pady=10)

        tk.Label(
            self.panel_frame, text="Opciones:", font=("Arial", 8), bg="#ffffff"
        ).pack(anchor="w", padx=5, pady=(5, 0))

        # Checkbox para líneas Manhattan

        # Botón para activar modo dibujo

    def _create_worksheets_section(self):
        """Crea la ventana para nombres de hojas de trabajo."""
        # Separador
        separator = tk.Frame(self.panel_frame, height=2, bg="#e0e0e0")
        separator.pack(fill="x", padx=5, pady=5)

        tk.Label(
            self.panel_frame, text="Hojas de Trabajo:", font=("Arial", 8), bg="#ffffff"
        ).pack(anchor="w", padx=5, pady=(5, 0))

        # Frame principal para la ventana de hojas de trabajo
        worksheets_frame = tk.Frame(
            self.panel_frame,
            bg="#f0f0f0",
            relief=tk.SUNKEN,
            borderwidth=1,
            height=200  # Altura fija para la ventana
        )
        worksheets_frame.pack(fill="both", expand=True, padx=5, pady=(5, 10))
        worksheets_frame.pack_propagate(False)  # Mantener altura fija

        # Scrollbar para la lista de hojas de trabajo
        worksheets_scrollbar = tk.Scrollbar(worksheets_frame, orient="vertical")
        worksheets_scrollbar.pack(side="right", fill="y")

        # Listbox para mostrar los nombres de las hojas de trabajo
        self.worksheets_listbox = tk.Listbox(
            worksheets_frame,
            yscrollcommand=worksheets_scrollbar.set,
            bg="#f0f0f0",
            fg="#333333",
            font=("Arial", 8),
            selectbackground="#0078d7", # Azul Windows estándar
            selectforeground="white",
            exportselection=False, # IMPORTANTE: Mantener selección aunque pierda el foco
            relief=tk.FLAT,
            borderwidth=0
        )
        self.worksheets_listbox.pack(side="left", fill="both", expand=True)

        worksheets_scrollbar.config(command=self.worksheets_listbox.yview)

        self.worksheets_listbox.insert(0, "Hoja1")
        self.worksheets_listbox.insert(1, "Hoja2")
        self.worksheets_listbox.insert(2, "Hoja3")

        self.worksheets_frame = worksheets_frame

        # Bindings y Menú Contextual
        self.worksheets_listbox.bind('<<ListboxSelect>>', self._on_sheet_selected)
        self.worksheets_listbox.bind('<Button-3>', self._show_sheet_context_menu)

        self.sheet_context_menu = tk.Menu(self.panel_frame, tearoff=0)
        self.sheet_context_menu.add_command(label="Nueva Hoja", command=self._on_add_sheet)
        self.sheet_context_menu.add_command(label="Renombrar", command=self._on_rename_sheet)
        self.sheet_context_menu.add_separator()
        self.sheet_context_menu.add_command(label="Eliminar Hoja", command=self._on_delete_sheet)

    def _on_sheet_selected(self, event):
        """Maneja la selección de una hoja en la lista."""
        selection = self.worksheets_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        # El índice 0 es el nombre del proyecto, las hojas empiezan en 1
        if index == 0:
            return # No hacer nada si selecciona el header

        sheet_index = index - 1
        if hasattr(self, 'app'):
            self.app.switch_to_sheet(sheet_index)

    def _show_sheet_context_menu(self, event):
        """Muestra el menú contextual en la lista de hojas."""
        index = self.worksheets_listbox.nearest(event.y)
        self.worksheets_listbox.selection_clear(0, tk.END)
        self.worksheets_listbox.selection_set(index)
        self.worksheets_listbox.activate(index)

        self.sheet_context_menu.post(event.x_root, event.y_root)

    def _on_add_sheet(self):
        """Callback para agregar hoja."""
        if hasattr(self, 'app'):
            self.app.add_new_sheet()

    def _on_rename_sheet(self):
        """Callback para renombrar hoja."""
        selection = self.worksheets_listbox.curselection()
        if not selection: return

        index = selection[0]
        if index == 0:
            # Renombrar proyecto
            if hasattr(self, 'app'):
                import tkinter.simpledialog as simpledialog
                current_name = self.worksheets_listbox.get(0).replace("📂 ", "")
                new_name = simpledialog.askstring("Renombrar Proyecto", "Nuevo nombre del proyecto:", initialvalue=current_name)
                if new_name:
                    self.app.project.name = new_name
                    self.app.update_sheet_list_ui()
        else:
            # Renombrar hoja
            if hasattr(self, 'app'):
                import tkinter.simpledialog as simpledialog
                current_name = self.worksheets_listbox.get(index).replace("📄 ", "").replace("👉 ", "")
                new_name = simpledialog.askstring("Renombrar", "Nuevo nombre:", initialvalue=current_name)
                if new_name:
                    self.app.rename_current_sheet(new_name)

    def _on_delete_sheet(self):
        """Callback para eliminar hoja."""
        selection = self.worksheets_listbox.curselection()
        if not selection: return

        index = selection[0]
        if index == 0:
            return # No se puede borrar el proyecto

        if hasattr(self, 'app'):
            self.app.delete_current_sheet()

    def update_preview(self):
        """Actualiza la vista previa de la línea en el panel."""
        if not self.preview_canvas:
            return

        self.preview_canvas.delete("all")

        width = self.line_width_var.get()
        color = self.line_color_var.get()
        dash_str = self.line_dash_var.get()
        shape = self.get_current_shape()

        # Convertir string a tuple para dash de forma segura
        dash = self.parse_dash_pattern(dash_str)

        canvas_width = 130
        canvas_height = 30

        if shape == "text":
            text_content = self.get_current_text() or "Texto"
            font_size = self.get_current_text_size()

            self.preview_canvas.create_text(
                canvas_width//2, canvas_height//2,
                text=text_content,
                font=("Arial", font_size),
                fill=color,
                anchor="center"
            )
        else:
            y = 15
            self.preview_canvas.create_line(
                10, y, canvas_width, y,
                fill=color, width=width, dash=dash
            )

        # ELIMINADO: Ya no actualizamos líneas existentes
        # Las nuevas líneas usarán automáticamente el estilo seleccionado

    def parse_dash_pattern(self, dash_str):
        """Convierte string de dash pattern a tuple de forma segura."""
        if not dash_str or dash_str == "":
            return ""

        # Patrones predefinidos seguros
        dash_patterns = {
            "(3, 3)": (3, 3),
            "(8, 4)": (8, 4),
            "": ""
        }

        return dash_patterns.get(dash_str, "")

    def get_current_shape(self):
        """Retorna la forma actual activa seleccionada."""
        for shape, info in self.shape_states.items():
            if info['active']:
                return shape
        return "line"  # Valor por defecto

    def get_current_text_size(self):
        """Retorna el tamaño de texto actual."""
        return self.current_text_size.get()

    def get_current_text(self):
        """Retorna el texto actual (siempre "TEXTO" por defecto)."""
        return "TEXTO"

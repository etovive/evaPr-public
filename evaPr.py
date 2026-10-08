#!/usr/bin/env python3
# evaPr - Diagramador de Circuitos Eléctricos Industriales Nativo para Linux
# Autor: etovive
# Licencia: GPL v3 - https://www.gnu.org/licenses/gpl-3.0.html
# Dependencias: cairosvg, pillow, tkinter, reportlab

import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import json
from datetime import datetime
import os
import copy
import types
import traceback
from pathlib import Path
import math
import time
import logging
import io

# El log rota: sin tope crecía sin límite (una sesión larga de simulación llegó a
# generar cientos de MB). Máximo ~5 MB x 3 rotaciones.
from logging.handlers import RotatingFileHandler
from ui.export_dialog import (
    ask_save_changes,
    confirm_overwrite,
    show_export_success,
    show_load_success,
    show_save_success,
)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler("evaPr_debug.log", maxBytes=5 * 1024 * 1024,
                            backupCount=3, encoding='utf-8', delay=True)
    ]
)
# Silenciar logs verbosos de librerías externas.  ezdxf en particular escribía
# ~25 000 líneas DEBUG por cada exportación DXF (setup=True), lo que costaba
# segundos de E/S y ocupaba el log casi entero.
for _noisy in ("PIL", "ezdxf", "cairosvg", "cairocffi", "fontTools",
               "matplotlib", "svglib", "pypdf", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

_log = logging.getLogger("evaPr")

def _report_error(context, e):
    """Función centralizada para reportar errores sin detener la aplicación"""
    msg = f"[{context}] {type(e).__name__}: {e}"
    _log.error(msg)
    _log.debug(traceback.format_exc())

# Imports para SVG
try:
    import cairosvg
    from PIL import Image, ImageTk
    SVG_SUPPORT = True
except ImportError:
    SVG_SUPPORT = False

from config.settings import AppConstants, PAYPAL_DONATION_URL, BTC_DONATION_ADDRESS, get_btc_donation_uri

CANVAS_WIDTH = AppConstants.CANVAS_WIDTH
CANVAS_HEIGHT = AppConstants.CANVAS_HEIGHT

from models import Connection

# PDF: Módulo de exportación PDF
from core.pdf_exporter import PdfExporter

# Importaciones de módulos modularizados
from ui.drawing_panel import DrawingPanel
from ui.splash import SplashScreen
from config.settings import load_config, save_config, DEFAULT_CONFIG, CONFIG_FILE
from config.disclaimer import DISCLAIMER_FOOTER, DISCLAIMER_TEXT, DISCLAIMER_TITLE
from handlers.event_utils import EventUtils
from core.unified_line_system import get_unified_line_system
from handlers.event_handlers import EventHandler, EventBinder
from utils.utils import get_svg_dimensions, get_component_real_size_static, get_svg_title, ToolTip, get_app_dir, get_resource_dir
from utils.utility_functions import is_near_segment, adapt_color_for_display, _is_dark_bg, distance_point_to_segment
from utils.coordinates import event_to_canvas_coords, draw_world_line, world_to_canvas_coords
from models.component import Component, TextComponent
from models.junction_component import JunctionComponent
from models.shape import ShapeManager, ShapeFactory
from models.project_data import Project
from models.shielding import ShieldingManager
from utils.alignment_utils import create_alignment_manager
from core.component_manager import ComponentManager

# SIMULACIÓN: Importar controlador de simulación
from simulation import SimulationController

# DESHACER: Importar UndoManager
from core.undo_manager import UndoManager

from core.reports import (BOMGenerator, CabinetSummaryGenerator, BornerPlanGenerator,
                          SafetySheetGenerator, UnifilarGenerator, Cabinet2DGenerator)
from core.wiring_table_generator import WiringTableGenerator
from core.wire_numbering import WireNumberingManager

# Importaciones de módulos principales completadas

class PlanoElectrico:
    def __init__(self, root):
        self.root = root

        try:
            # Buscar logo .ico (mejor soporte para barra de tareas) y .png (fallback)
            ico_paths = [
                get_resource_dir() / "logo-evaPr.ico",
                get_app_dir() / "logo-evaPr.ico",
                Path.cwd() / "logo-evaPr.ico",
                "logo-evaPr.ico"
            ]
            for ico_path in ico_paths:
                try:
                    if not Path(ico_path).exists():
                        continue
                    self.root.iconbitmap(str(ico_path))
                    break
                except:
                    continue

            png_paths = [
                get_resource_dir() / "logo-evaPr.png",
                get_app_dir() / "logo-evaPr.png",
                Path.cwd() / "logo-evaPr.png",
                "logo-evaPr.png"
            ]
            for png_path in png_paths:
                try:
                    if not Path(png_path).exists():
                        continue
                    logo = tk.PhotoImage(file=str(png_path))
                    self.root.iconphoto(True, logo)
                    break
                except:
                    continue
        except Exception as e:
            # No se pudo cargar el icono - continuando
            pass

        self.config = load_config()
        # Asegurar migración completa de configuración
        self.migrate_config()

        project_name = self.config.get("pdf_config", {}).get("proyecto", "Nuevo Proyecto")
        if not project_name:
            project_name = "Nuevo Proyecto"
        self.project = Project(project_name)

        # Variables controladas por configuración (necesarias para la UI)
        self.auto_conexion_enabled = tk.BooleanVar(value=self.config.get("auto_conexion_enabled", True))
        self.invertir_deteccion = tk.BooleanVar(value=self.config.get("invertir_deteccion", False))
        self.snap_to_grid_enabled = tk.BooleanVar(value=self.config.get("snap_to_grid_enabled", False))
        self.tooltips_enabled = tk.BooleanVar(value=self.config.get("tooltips_enabled", True))
        self.enable_move_connections = tk.BooleanVar(value=self.config.get("enable_move_connections", True))
        self.proximity_preview_enabled = tk.BooleanVar(value=False)

        self.root.geometry(f"{self.config['window_width']}x{self.config['window_height']}")
        self.current_file = None  # Archivo actualmente abierto

        self.current_line_width = tk.DoubleVar(value=0.5)
        self.current_line_color = tk.StringVar(value="black")
        self.current_line_dash = tk.StringVar(value="")  # "" = continuo, (5,5) = punteado, (10,5) = cortado

        # BINDINGS DE ATAJOS DE TECLADO
        # ATAJOS - EXACTAMENTE LO MISMO QUE LOS BOTONES
        self.root.bind_all("<Control-h>", lambda e: self._center_vertically_with_indicator())
        self.root.bind_all("<Control-j>", lambda e: self._distribute_vertically_with_indicator())
        self.root.bind_all("<Control-k>", lambda e: self._distribute_horizontally_with_indicator())
        self.root.bind_all("<Control-i>", lambda e: self._insert_point_with_indicator())
        self.root.bind_all("<F7>", lambda e: self.toggle_wire_numbering())
        # Control de la simulación con teclas de función (atajo global)
        # F5 arranca/reanuda, F6 detiene por completo. Son deliberadamente
        # independientes del toggle de la barra: F5 nunca pausa, F6 siempre detiene.
        self.root.bind_all("<F5>", lambda e: self.start_simulation())
        self.root.bind_all("<F6>", lambda e: self.stop_simulation())
        # Atajo ultra-seguro por si el teclado es internacional (Ctrl + D de DIN)
        self.root.bind_all("<Control-d>", self.activate_din_rail_draw)
        self.root.bind_all("<Control-D>", self.activate_din_rail_draw)
        # Atajo para Canaleta (Ctrl + F de "Funda" o "Forro" cable)
        self.root.bind_all("<Control-f>", self.activate_canaleta_draw)
        self.root.bind_all("<Control-F>", self.activate_canaleta_draw)

        self.create_menus()
        self.create_toolbar()

        # CREAR BARRA DE ESTADO PRIMERO (antes del main_frame)
        self.status_frame = tk.Frame(root, bg="#e0e0e0", height=30, relief="sunken", bd=1)
        self.status_frame.pack(side="bottom", fill="x")
        self.status_frame.pack_propagate(False)

        # Label de alerta: tipo de falla en video inverso con parpadeo.
        # Se empaqueta antes de status_label_left para quedar en el extremo izquierdo,
        # que es donde el ojo va primero. Arranca oculto (pack_forget).
        self.status_alert_label = tk.Label(
            self.status_frame,
            text="",
            bg="#e0e0e0",
            fg="#d32f2f",
            font=(AppConstants.UI_FONT_FAMILY, 10, "bold"),
            anchor="w"
        )
        self._status_alert_blink_id = None
        self._status_alert_text = ""
        self._status_alert_color = "#d32f2f"
        # Latch de falla: mientras está activo, las refrescas periódicas de la barra
        # no pisan el mensaje de cortocircuito (antes lo reemplazaban por "Listo" al
        # cabo de ~1.3 s, dejando al usuario sin poder leerlo).
        self._status_fault_latched = False

        # Label izquierdo para mensajes de estado
        self.status_label_left = tk.Label(
            self.status_frame,
            text="Iniciando...",
            bg="#e0e0e0",
            fg="black",
            font=(AppConstants.UI_FONT_FAMILY, 10),
            anchor="w"
        )
        self.status_label_left.pack(side="left", padx=15, pady=5)

        # Label para aviso de simulación parpadeante
        self.sim_blink_label = tk.Label(
            self.status_frame,
            text="",
            bg="#e0e0e0",
            fg="black",
            font=("Arial", 10, "bold"),
            anchor="w"
        )
        self.sim_blink_label.pack(side="left", padx=15, pady=5)

        # Aviso legal permanente al pie de la ventana (nota al pie en pantalla)
        self.status_disclaimer_label = tk.Label(
            self.status_frame,
            text=DISCLAIMER_FOOTER,
            bg="#e0e0e0",
            fg="#6d6d6d",
            font=(AppConstants.UI_FONT_FAMILY, 8),
            anchor="w"
        )
        self.status_disclaimer_label.pack(side="left", padx=12, pady=5)

        # Label derecho para nombre de archivo (permanente)
        self.status_label_right = tk.Label(
            self.status_frame,
            text="📝 Sin guardar",
            bg="#e0e0e0",
            fg="black",
            font=(AppConstants.UI_FONT_FAMILY, 9),
            anchor="e"
        )
        self.status_label_right.pack(side="right", padx=15, pady=5)

        # CREAR LAYOUT PRINCIPAL: Panel lateral + Canvas (DESPUÉS de la barra)
        self.main_frame = tk.Frame(root)
        self.main_frame.pack(fill="both", expand=True)

        self.lines_panel_frame = tk.Frame(self.main_frame, width=160)
        self.lines_panel_frame.pack(side="left", fill="y")
        self.lines_panel_frame.pack_propagate(False)

        # BARRA VERTICAL DE 40px PARA BOTONES PERSONALIZADOS
        self.custom_buttons_bar = tk.Frame(self.main_frame, width=40, bg="#ffffff", relief=tk.FLAT, bd=0)
        self.custom_buttons_bar.pack(side="left", fill="y")
        self.custom_buttons_bar.pack_propagate(False)  # Mantener ancho fijo

        # BARRA ULTRA DELGADA (5px) PARA OCULTAR/MOSTRAR PANEL
        self.panel_visible = True  # Estado inicial
        self.toggle_canvas = tk.Canvas(
            self.main_frame,
            width=5,     # Exactamente 5px de ancho
            height=20,   # Altura visible
            bg="#e0e0e0",
            cursor="hand2",
            highlightthickness=0,  # Sin borde
            bd=0
        )
        self.toggle_canvas.pack(side="left", fill="y", padx=0, pady=0)
        self.toggle_canvas.bind("<Button-1>", self.toggle_lines_panel)

        # ESTADO INICIAL: Panel visible - dibujar flecha hacia izquierda
        self.update_toggle_visual()

        self.canvas_frame = tk.Frame(self.main_frame)
        self.canvas_frame.pack(side="right", fill="both", expand=True)

        # Canvas principal - A3 fijo a 300 DPI usando tk.Canvas (sin virtualización)
        self.canvas = tk.Canvas(
            self.canvas_frame,
            bg=self.config["canvas_color"],
            width=CANVAS_WIDTH,                    # A3 a 300 DPI
            height=CANVAS_HEIGHT,                  # A3 a 300 DPI
            scrollregion=(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT)  # Área scrollable
        )
        # Mantener algunas propiedades que el código espera (zoom helpers)
        self.canvas.root = self.root
        self.canvas.app = self # REFERENCIA A LA APLICACIÓN para contadores persistentes
        # Asegurar existencia de zoom_level para compatibilidad con utilidades
        self.canvas.zoom_level = getattr(self.canvas, 'zoom_level', 1.0)
        # Proveer métodos conversores mínimos (compatibles con VirtualCanvas)
        if not hasattr(self.canvas, 'screen_to_world'):
            self.canvas.screen_to_world = lambda sx, sy: (self.canvas.canvasx(sx) / self.canvas.zoom_level, self.canvas.canvasy(sy) / self.canvas.zoom_level)
        if not hasattr(self.canvas, 'world_to_screen'):
            self.canvas.world_to_screen = lambda wx, wy: (int(wx * self.canvas.zoom_level - self.canvas.canvasx(0)), int(wy * self.canvas.zoom_level - self.canvas.canvasy(0)))

        self.canvas.pack(fill="both", expand=True)
        # Canvas A3 fijo - usando tk.Canvas nativo
        # Flags para depuración del crosshair (usa color visible y mensaje una vez)

        self._crosshair_enabled = self.config.get("crosshair_enabled", True)  # Control desde configuración

        self.canvas.show_labels = True

        self.grid_size = self.config["grid_size"]
        # No dibujar grid aquí - el canvas aún no tiene dimensiones finales

        # Cache para imagen de grid tileable (clave: (grid_size, color_hex))
        self._grid_tile_cache = {}
        self._grid_bg_image = None

        self.lines = []
        self.shapes = []
        self.components = []
        self.connections = []
        self.image_components = [] # Lista de componentes de imagen
        self.text_components = [] # Lista de componentes de texto
        self.block_terminals = [] # Block Terminals (Ctrl+B)
        self.canvas.components = self.components # REFERENCIA A LA LISTA DE COMPONENTES para compatibilidad

        # Pasar el canvas para que pueda inicializar el ShapeEditor del shape_editor.py original
        self.shape_manager = ShapeManager(self.canvas)

        self.wire_numbering_enabled = tk.BooleanVar(value=self.config.get("wire_numbering_enabled", False))

        # Buffer persistente de contadores para etiquetado automático
        self.label_counters = {}  # {'Q': 6, 'KM': 2, 'M': 4, ...}

        # File operations are now integrated directly

        # Estado para modo insertar punto con Ctrl+I
        self.is_insert_point_mode = False

        # Estado para modo texto
        self.text_mode = False
        self.current_text_component = None

        self.component_manager = ComponentManager(self)

        self.alignment_manager = create_alignment_manager(self)

        try:
            self.event_handler = EventHandler(self)
            event_binder = EventBinder(self.canvas, self.event_handler)
            event_binder.bind_all_events()

            # SOLUCIÓN CRÍTICA: Marcar que EventHandler está activo
            self.event_handlers_active = True
            # Limpiar círculos amarillos de puntos de conexión cuando se activa EventHandler
            self.clear_connection_point_highlights()
        # EventHandler inicializado correctamente

        except Exception as e:
            # ERROR en inicialización de EventHandler - usando eventos básicos
            _report_error("EventHandler Init", e)
            self._setup_basic_events()
            self.event_handlers_active = False
            # Silenciar errores de EventHandler para no interferir
            pass

        self.manhattan_router = get_unified_line_system(self)
        self.wire_numbering_manager = WireNumberingManager(self)
        self.wire_numbering_dirty = True # Flag para optimizar rendimiento
        # Estado para arrastre de etiquetas de numeración de cables
        self._dragging_wire_label = False
        self._dragging_wire_label_conn = None
        self._selected_wire_label_conn = None

        # Punto de conexión seleccionado (huérfano) para borrar con <delete>
        # Contiene (component, point_idx) o None.
        self._selected_connection_point = None
        self._selected_connection_point_hl_id = None

        # Exponer también como unified_line_system para compatibilidad
        self.unified_line_system = self.manhattan_router

        self.shielding_manager = ShieldingManager(self)
        self.shielding_mode_enabled = tk.BooleanVar(value=False)

        self.crosshair_created = False
        self._init_crosshair()

        # CREAR BOTONES EN LA BARRA VERTICAL - POSPUESTO HASTA DESPUÉS DE LA INICIALIZACIÓN

        # OPTIMIZACIÓN MOTION: El crosshair ahora se maneja en la función consolidada de event_handlers
        # Esto elimina múltiples binds de Motion y mejora el rendimiento significativamente

        # Asegurar que la ventana pueda recibir eventos del teclado
        self.root.focus_set()
        self.root.focus_force()  # Forzar el foco
        # También hacer que el canvas pueda recibir foco
        self.canvas.focus_set()

        # SIMULACIÓN: Inicializar controlador de simulación
        self.simulation_controller = SimulationController(self)
        self.simulation_running = False  # Estado de simulación
        self.simulation_mode = False     # Modo de restricción de edición

        self.undo_manager = UndoManager(max_depth=15)
        self._undo_block_save = False  # Para evitar recursión durante apply_state

        # Panel lateral para configuración de líneas (después de inicializar connections)
        self.create_drawing_panel()
        self.update_sheet_list_ui() # Mostrar lista de hojas inicial

        self.selected_component = None
        self.drag_data = {"x": 0, "y": 0, "component": None}
        self.clipboard = None # Portapapeles para copiar y pegar

        # Variables para selección por área
        self.selection_box_active = False
        self.selection_box_start = None
        self.selection_box_rect = None
        self.selected_elements = []  # Lista de elementos seleccionados (componentes y conexiones)
        self.first_point = None
        self.selected_point = None
        self.selected_segment = None
        self.locked_segment = False
        self.start_x = 0
        self.start_y = 0
        self.last_motion_time = 0
        self.highlighted_component = None

        self.preview_autoconexion_activo = False

        # Variables para preview de componentes
        self.component_preview_mode = False
        self.preview_component = None
        self.preview_component_data = None
        self.preview_category = None

        # Variables para modo de conexión
        self.connection_mode = False
        self.connection_start = None  # (component, point_index)

        # (Eliminado: funcionalidad duplicada de líneas)

        # Variable para rastrear posición del mouse para zoom
        self.mouse_x = 0
        self.mouse_y = 0

        # Variables para Pan (mover vista)
        self.pan_mode = False
        self.pan_start_x = 0
        self.pan_start_y = 0
        self.is_panning = False  # Para pan con botón central del mouse

        # Configurar dibujado del grid después de que el canvas esté listo
        self.grid_initialized = False
        self.canvas.bind("<Map>", self.on_canvas_mapped)

        # También programar dibujado del grid después de la inicialización completa
        self.root.after_idle(self.ensure_grid_visible)
        # Inicializar barra de estado con "Sin guardar" después de completar init
        self.root.after_idle(self.update_status_bar)

        # ATAJOS DE UNDO/REDO
        self.root.bind_all("<Control-z>", lambda e: self.undo())
        self.root.bind_all("<Control-Z>", lambda e: self.undo()) # Mayúscula también
        self.root.bind_all("<Control-y>", lambda e: self.redo())
        self.root.bind_all("<Control-Y>", lambda e: self.redo())

        # PDF: Inicializar módulo de exportación PDF
        self.pdf_exporter = PdfExporter(self)
        from core.dxf_exporter import DxfExporter
        self.dxf_exporter = DxfExporter(self)

        # RASTREO ESTADO GUARDADO:
        self.is_dirty = False
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing_app)

    def on_closing_app(self):
        """Maneja el evento de cerrar la aplicación, preguntando si guardar si hay cambios."""
        if getattr(self, 'is_dirty', False):
            respuesta = ask_save_changes(self.root, "salir")
            if respuesta in (None, "cancel"):
                return  # Cancelar el cierre
            if respuesta == "yes" and not self.save_canvas():
                return  # No cerrar si el usuario cancela o falla el guardado

        # Proceder a cerrar la aplicación
        self.root.destroy()
        import sys
        sys.exit(0)

    # DELEGACIÓN AL MÓDULO PDF (pdf_exporter.py)

    def config_pdf(self):
        """Delega la configuración PDF al módulo pdf_exporter."""
        self.pdf_exporter.config_pdf()

    def export_dxf(self):
        """Exporta el dibujo actual a archivo DXF vectorial."""
        self.stop_simulation_if_running("se exportó a DXF")
        if hasattr(self, 'dxf_exporter') and self.dxf_exporter:
            self.dxf_exporter.export_dxf()
        else:
            from core.dxf_exporter import DxfExporter
            self.dxf_exporter = DxfExporter(self)
            self.dxf_exporter.export_dxf()

    def export_pdf(self):
        """Delega la exportación PDF al módulo pdf_exporter."""
        self.stop_simulation_if_running("se exportó a PDF")
        self.pdf_exporter.export_pdf()

    def export_bom_csv(self):
        """Exporta la lista de materiales a un archivo CSV/TXT delimitado por punto y coma."""
        from tkinter import filedialog
        from core.reports import BOMGenerator

        self.stop_simulation_if_running("se exportó el BOM a CSV")

        # Sugerir nombre basado en el proyecto
        suggested_name = f"{self.project.name}_lista_BOM"

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=suggested_name,
            filetypes=[("Archivos CSV", "*.csv"), ("Archivos de texto", "*.txt"), ("Todos los archivos", "*.*")],
            title="Exportar Lista de Materiales",
            parent=self.root,
            confirmoverwrite=False,
        )
        if not filename:
            return
        if not confirm_overwrite(self.root, filename):
            return

        try:
            generator = BOMGenerator(self.project)
            all_components = generator._collect_components_from_project(self.project)
            grouped_data = generator._group_data(all_components, project=self.project)

            # Inyectar ítems de infraestructura (Gabinete, Riel DIN, Canaleta)
            generator._inject_infrastructure_items(self, grouped_data)

            valid_keys = [k for k in grouped_data.keys() if k[0] or k[1]]
            sorted_keys = sorted(valid_keys, key=lambda k: (str(k[0]), str(k[1])))

            with open(filename, 'w', encoding='utf-8') as f:
                f.write("REFERENCIAS;DESCRIPCION;ESPECIFICACIONES;CANTIDAD\n")

                for desc, specs in sorted_keys:
                    names = grouped_data[(desc, specs)]
                    try:
                        names.sort(key=lambda x: (x[0], int(''.join(filter(str.isdigit, x))) if any(char.isdigit() for char in x) else 0))
                    except:
                        names.sort()

                    # Una bornera multipolo puede aparecer repetida para sumar
                    # sus polos; la referencia se exporta una sola vez.
                    refs_str = ", ".join(dict.fromkeys(names))
                    qty = str(len(names))

                    refs_clean = refs_str.replace(";", ",")
                    desc_clean = desc.replace(";", ",")
                    specs_clean = specs.replace(";", ",")

                    f.write(f"{refs_clean};{desc_clean};{specs_clean};{qty}\n")

            if hasattr(self, 'set_status'):
                self.set_status(f"✅ BOM exportada a {filename}", "green")
            show_export_success(
                self.root,
                "CSV",
                filename,
                description="La lista de materiales se exportó correctamente.",
            )

        except Exception as e:
            tk.messagebox.showerror("Error", f"Error exportando BOM: {str(e)}")

    def export_wiring_table_csv(self):
        """Exporta la tabla de cableado a un archivo CSV/TXT delimitado por punto y coma."""
        from tkinter import filedialog
        from core.wiring_table_generator import WiringTableGenerator

        self.stop_simulation_if_running("se exportó la tabla de cableado a CSV")

        suggested_name = f"{self.project.name}_tabla_cableado"

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=suggested_name,
            filetypes=[("Archivos CSV", "*.csv"), ("Archivos de texto", "*.txt"), ("Todos los archivos", "*.*")],
            title="Exportar Tabla de Cableado",
            parent=self.root,
            confirmoverwrite=False,
        )
        if not filename:
            return
        if not confirm_overwrite(self.root, filename):
            return

        try:
            generator = WiringTableGenerator(self.project)
            wires = generator.get_wiring_data()

            with open(filename, 'w', encoding='utf-8') as f:
                # Cabeceras alineadas con Tabla de Cableado (Punto a Punto)
                f.write("N° HILO;HOJA;ORIGEN / COMP.;ORIG. TERM.;DESTINO / COMP.;DEST. TERM.;SECCIÓN;BORNER / PASO;NOTAS\n")

                for w in wires:
                    hilo = w['hilo']
                    hoja = w['hoja'].replace(';', ',')
                    o_n = w['o_n'].replace(';', ',')
                    o_t = w['o_t'].replace(';', ',')
                    d_n = w['d_n'].replace(';', ',')
                    d_t = w['d_t'].replace(';', ',')
                    sec = w['sec']
                    borner = w.get('borner', '-').replace(';', ',')
                    nota = w.get('nota', '').replace(';', ',')

                    f.write(f"{hilo};{hoja};{o_n};{o_t};{d_n};{d_t};{sec};{borner};{nota}\n")

            if hasattr(self, 'set_status'):
                self.set_status(f"✅ Tabla de Cableado exportada a {filename}", "green")
            show_export_success(
                self.root,
                "CSV",
                filename,
                description="La tabla de cableado se exportó correctamente.",
            )

        except Exception as e:
            tk.messagebox.showerror("Error", f"Error exportando Tabla de Cableado: {str(e)}")

    def is_dark_mode(self):
        """Detecta si está activo el modo oscuro consultando directamente el color de fondo del canvas"""
        try:
            bg_color = self.canvas.cget("bg").lower()
        except Exception:
            bg_color = self.config.get("canvas_color", "#ffffff").lower()

        return _is_dark_bg(bg_color)

    def redraw_all_connections_for_theme(self):
        """Redibuja todas las conexiones aplicando la adaptación de color para el tema actual"""
        canvas_bg = self.canvas.cget("bg")
        for connection in self.connections:
            if hasattr(connection, 'line_ids') and connection.line_ids:
                # Usar el color original guardado en la conexión
                base_color = getattr(connection, 'line_color', 'black')
                adapted_color = adapt_color_for_display(base_color, canvas_bg)
                for line_id in connection.line_ids:
                    try:
                        self.canvas.itemconfig(line_id, fill=adapted_color)
                    except Exception:
                        continue

    def refresh_all_colors(self):
        """Actualiza todos los colores cuando cambia el modo de visualización"""
        try:
            for component in getattr(self, 'components', []):
                if hasattr(component, 'svg_file') and component.svg_file:
                    try:
                        component.load_image(component.svg_path)
                        component.draw()
                    except Exception:
                        pass

            for connection in getattr(self, 'connections', []):
                # Solo redibujar si no está marcada como modificada manualmente
                if not hasattr(connection, 'manually_modified') or not connection.manually_modified:
                    self.update_manhattan_line(connection)
                else:
                    # Conexión manually_modified - preservando trazado manual
                    pass

            # CRÍTICO: También actualizar conexiones desde empalmes
            for connection in getattr(self, 'conexiones_desde_empalmes', []):
                # Solo redibujar si no está marcada como modificada manualmente
                if not hasattr(connection, 'manually_modified') or not connection.manually_modified:
                    self.update_manhattan_line(connection)
                else:
                    # Conexión manually_modified - preservando trazado manual
                    pass

            # FORZAR actualización de colores para tema actual
            self.redraw_all_connections_for_theme()

            if hasattr(self, 'shielding_manager') and self.shielding_manager:
                for sh in self.shielding_manager.shieldings:
                    try:
                        sh.draw(self.canvas)
                    except Exception:
                        pass

            for text_comp in getattr(self, 'text_components', []):
                try:
                    text_comp.draw()
                except Exception:
                    pass

            # Registrar el tema con el que se renderizó la hoja activa
            current_sheet = getattr(self.project, 'get_active_sheet', lambda: None)()
            if current_sheet:
                current_sheet.last_rendered_bg = self.canvas.cget("bg")

        except Exception as e:
            # Error actualizando colores
            pass

    # MÉTODOS DE ESTADO (UNDO/REDO/SERIALIZACIÓN)

    def get_current_state(self):
        """Captura el estado actual completo del proyecto como un diccionario serializable."""
        try:
            # Reutilizar lógica de guardado de FileOperations pero retornando el dict
            # Para evitar dependencias circulares pesadas, extraemos lo esencial
            state = {
                "format_version": "2.0",
                "canvas_config": {
                    "color": self.config["canvas_color"],
                    "grid_size": self.config["grid_size"],
                    "scale_factor": getattr(self.canvas, 'scale_factor', 1.0)
                },
                "label_counters": dict(getattr(self, 'label_counters', {})),
                "components": [comp.to_dict() for comp in self.components],
                "connections": []
            }

            # Serializar conexiones
            for conn in self.connections:
                try:
                    conn_dict = conn.to_dict(self.components)
                    state["connections"].append(conn_dict)
                except Exception:
                    continue

            # Serializar shapes (geometricas)
            if hasattr(self, 'shape_manager') and self.shape_manager:
                state["shapes"] = [s.to_dict() for s in self.shape_manager.shapes if hasattr(s, 'to_dict')]

            # Serializar apantallamientos
            if hasattr(self, 'shielding_manager') and self.shielding_manager:
                state["shieldings"] = [sh.to_dict() for sh in self.shielding_manager.shieldings]

            # Serializar block terminals de la hoja activa
            if hasattr(self, 'block_terminals'):
                state["block_terminals"] = [
                    {
                        "x":          bt['x'],
                        "y":          bt['y'],
                        "filas":      bt['filas'],
                        'bornas':     bt['bornas'],
                        "label_data": bt.get('label_data', {}).copy(),
                    }
                    for bt in self.block_terminals
                ]

            return state
        except Exception as e:
            return None

    def apply_state(self, state):
        """Aplica un estado previamente capturado al proyecto."""
        if not state:
            return

        self._undo_block_save = True  # Bloquear autoguardado de undo mientras aplicamos
        try:
            # 1. Limpiar canvas y listas (sin borrar el undo_manager!)
            self.canvas.delete("all")
            self.components.clear()
            self.connections.clear()
            self.text_components.clear()
            if hasattr(self, 'shape_manager') and self.shape_manager:
                self.shape_manager.shapes.clear()

            # Limpiar selección de punto de conexión (las referencias quedarían obsoletas)
            if hasattr(self, 'clear_selected_connection_point'):
                self.clear_selected_connection_point()

            # 2. Re-inicializar elementos críticos que delete("all") borró
            self.crosshair_created = False
            self._init_crosshair()
            self.draw_grid(force=True)

            # 3. Restaurar configuración básica
            if "canvas_config" in state:
                cfg = state["canvas_config"]
                self.canvas.configure(bg=cfg.get("color", "#ffffff"))
                self.canvas.scale_factor = cfg.get("scale_factor", 1.0)

            self.label_counters = state.get("label_counters", {})

            for comp_data in state.get("components", []):
                try:
                    # Usar lógica de carga modularizada o directa
                    # Para simplificar y evitar duplicación masiva, usaremos Component.from_dict
                    is_junction = comp_data.get("type") == "junction"
                    if is_junction:
                        comp = JunctionComponent.from_dict(self.canvas, comp_data, self.config)
                    else:
                        comp = Component.from_dict(self.canvas, comp_data, self.config["svg_path"], self.config)

                    comp.draw()
                    self.components.append(comp)
                except Exception as e:
                    _report_error("Apply State: Component", e)

            # 5. Restaurar conexiones
            for conn_data in state.get("connections", []):
                try:
                    s_idx = conn_data["start_component_idx"]
                    e_idx = conn_data["end_component_idx"]
                    if 0 <= s_idx < len(self.components) and 0 <= e_idx < len(self.components):
                        conn = Connection.from_dict(conn_data, self.components)
                        self.connections.append(conn)
                        # Re-crear visualmente
                        self.update_manhattan_line(conn)
                except Exception as e:
                    _report_error("Apply State: Connection", e)

            if "shapes" in state and hasattr(self, 'shape_manager'):
                from models.shape import Circle, Rect, RoundedRect, Ellipse, Square, MultipoleBorner, DinRail, Canaleta
                shape_types = {
                    "circle": Circle, "rect": Rect, "rounded_rect": RoundedRect, "ellipse": Ellipse, "square": Square,
                    "multipole_borner": MultipoleBorner, "din_rail": DinRail, "canaleta": Canaleta
                }
                for s_data in state["shapes"]:
                    try:
                        stype = s_data.get("type")
                        if stype in shape_types:
                            shape = shape_types[stype].from_dict(s_data)
                            self.shape_manager.shapes.append(shape)
                            shape.draw(self.canvas)
                    except Exception as e:
                        pass

            # Restaurar apantallamientos
            if "shieldings" in state and hasattr(self, 'shielding_manager'):
                from models.shielding import Shielding
                for sh_data in state["shieldings"]:
                    try:
                        sh = Shielding.from_dict(sh_data)
                        self.shielding_manager.add_shielding(sh)
                    except Exception as e:
                        pass

            # 7. Actualizar UI
            self.update_status_bar()
            for comp in self.components:
                comp.draw_connection_points()

        finally:
            self._undo_block_save = False

    def save_undo_checkpoint(self):
        """Guarda el estado actual en el UndoManager."""
        if getattr(self, '_undo_block_save', False):
            return

        state = self.get_current_state()
        if state:
            self.undo_manager.save_state(state)
            self.is_dirty = True

    def undo(self):
        """Ejecuta la operación deshacer."""
        current_state = self.get_current_state()
        prev_state = self.undo_manager.undo(current_state)
        if prev_state:
            self.apply_state(prev_state)
            self.set_status("Deshacer ejecutado", "blue")
        else:
            self.set_status("No hay más cambios para deshacer", "gray")

    def redo(self):
        """Ejecuta la operación rehacer."""
        current_state = self.get_current_state()
        next_state = self.undo_manager.redo(current_state)
        if next_state:
            self.apply_state(next_state)
            self.set_status("Rehacer ejecutado", "blue")
        else:
            self.set_status("No hay cambios para rehacer", "gray")

    def copy_selection(self):
        """Copia los elementos seleccionados al portapapeles."""
        selection = []
        if hasattr(self, 'selected_elements') and self.selected_elements:
            selection = list(self.selected_elements)
        elif self.selected_component:
            selection = [self.selected_component]

        if not selection:
            return

        # Filtrar solo elementos que tienen to_dict
        serialized_components = []
        serialized_shapes = []

        components_in_selection = []
        for elem in selection:
            if hasattr(elem, 'to_dict'):
                # Es un componente o un JunctionComponent o una forma
                from models.component import Component, TextComponent
                from models.junction_component import JunctionComponent
                from models.connection import Connection

                if isinstance(elem, (Component, JunctionComponent, TextComponent)):
                    serialized_components.append(elem.to_dict())
                    components_in_selection.append(elem)
                elif isinstance(elem, Connection):
                    # Las conexiones se manejan después basadas en los componentes seleccionados
                    continue
                else:
                    # Asumimos que es una forma
                    serialized_shapes.append(elem.to_dict())

        # Capturar conexiones internas entre los componentes seleccionados
        serialized_connections = []
        for conn in self.connections:
            if conn.start_component in components_in_selection and conn.end_component in components_in_selection:
                serialized_connections.append(conn.to_dict(components_in_selection))

        self.clipboard = {
            "components": serialized_components,
            "shapes": serialized_shapes,
            "connections": serialized_connections
        }

        count = len(serialized_components) + len(serialized_shapes)
        self.set_status(f"📋 {count} elementos copiados", "blue")

    def paste_selection(self):
        """Pega los elementos del portapapeles en el lienzo."""
        if not self.clipboard:
            return

        self.save_undo_checkpoint()

        offset = 50
        new_elements = []
        new_components = []

        for comp_data in self.clipboard.get("components", []):
            try:
                # Ajustar posición - usar deep copy para evitar compartir referencias
                data_copy = copy.deepcopy(comp_data)
                data_copy["x"] += offset
                data_copy["y"] += offset

                # Determinar si es un JunctionComponent o TextComponent
                is_junction = data_copy.get("type") == "junction"

                comp = None
                if is_junction:
                    comp = JunctionComponent.from_dict(self.canvas, data_copy, self.config)
                elif data_copy.get("type") == "text" or "text" in data_copy:
                    comp = TextComponent.from_dict(self.canvas, data_copy)
                else:
                    # Usar la ruta de SVGs de la configuración
                    svg_path = self.config.get("svg_path", "svgs")

                    # Component.from_dict llama al constructor
                    comp = Component.from_dict(self.canvas, data_copy, svg_path, self.config)

                    # REFINAR NOMBRE: Asegurar que el nombre sea único
                    original_name = data_copy.get("label_data", {}).get("name", "")
                    name_exists = any(getattr(c, 'label_data', {}).get('name') == original_name for c in self.components)

                    if name_exists and original_name:
                        # Generar nombre único con sufijo incremental sin depender de método inexistente
                        counter = 2
                        new_name = f"{original_name}_{counter}"
                        while any(getattr(c, 'label_data', {}).get('name') == new_name for c in self.components):
                            counter += 1
                            new_name = f"{original_name}_{counter}"
                        comp.label_data['name'] = new_name

                if comp:
                    comp.draw()
                    self.components.append(comp)
                    new_components.append(comp)
                    new_elements.append(comp)
            except Exception as e:
                _report_error("Paste Selection: Component", e)

        # 2. Pegar conexiones internas
        for conn_data in self.clipboard.get("connections", []):
            try:
                s_idx = conn_data["start_component_idx"]
                e_idx = conn_data["end_component_idx"]

                if 0 <= s_idx < len(new_components) and 0 <= e_idx < len(new_components):
                    conn = Connection.from_dict(conn_data, new_components)
                    self.connections.append(conn)

                    # Preservar forma de líneas manuales al pegar
                    if getattr(conn, 'manually_modified', False):
                        # Ajustar puntos de ángulo manual por el offset de pegado
                        if hasattr(conn, 'manual_angle_points') and conn.manual_angle_points:
                            adjusted_points = []
                            for px, py in conn.manual_angle_points:
                                adjusted_points.append((px + offset, py + offset))
                            conn.manual_angle_points = adjusted_points

                        # Usar el sistema unificado que respeta manual_angle_points
                        if hasattr(self, 'unified_line_system'):
                            self.unified_line_system._recalculate_connection_segments_fast(conn)
                            self.unified_line_system._redraw_connection_fast(conn)
                        else:
                            # Fallback: usar manhattan router que también respeta manually_modified
                            self.update_manhattan_line(conn)
                    else:
                        # Línea automática: recalcular ruta normalmente
                        self.update_manhattan_line(conn)

                    new_elements.append(conn)
            except Exception as e:
                _report_error("Paste Selection: Connection", e)

        # 3. Pegar formas
        if hasattr(self, 'shape_manager'):
            from models.shape import Circle, Rect, RoundedRect, Ellipse, Square, MultipoleBorner, DinRail, Canaleta
            shape_types = {
                "circle": Circle, "rect": Rect, "rounded_rect": RoundedRect, "ellipse": Ellipse, "square": Square,
                "multipole_borner": MultipoleBorner, "din_rail": DinRail, "canaleta": Canaleta
            }
            for s_data in self.clipboard.get("shapes", []):
                try:
                    stype = s_data.get("type")
                    if stype in shape_types:
                        data_copy = s_data.copy()
                        data_copy["x"] += offset
                        data_copy["y"] += offset
                        shape = shape_types[stype].from_dict(data_copy)
                        self.shape_manager.shapes.append(shape)
                        shape.draw(self.canvas)
                        new_elements.append(shape)
                except Exception as e:
                    pass

        if hasattr(self, 'selected_elements'):
            for elem in self.selected_elements:
                if hasattr(elem, 'selected'):
                    elem.selected = False
            self.selected_elements.clear()

            for elem in new_elements:
                if hasattr(elem, 'selected'):
                    elem.selected = True
                self.selected_elements.append(elem)

            if self.selected_component:
                self.selected_component.selected = False
                self.selected_component = None

            if hasattr(self, 'update_selection_indicators'):
                self.update_selection_indicators()

        self.set_status(f"📋 {len(new_elements)} elementos pegados", "green")

    # FIN MÉTODOS DE ESTADO

    # FIN FUNCIONES DE MODO OSCURO

    def migrate_config(self):
        """Migra configuración antigua a nueva estructura con Tools"""
        migrated = False

        # Configuración migrada (empalme.svg ya no se usa)

        # Asegurar cable_color_map (colores de conductores en apantallamiento)
        if "cable_color_map" not in self.config:
            self.config["cable_color_map"] = dict(DEFAULT_CONFIG["cable_color_map"])
            migrated = True

        if migrated:
            from config.settings import save_config
            save_config(self.config)

    def draw_grid(self, force=False):
        """Dibuja el grid de tamaño fijo en el fondo del lienzo.

        Por defecto dibuja solo la primera vez; para forzar un redibujo pasar force=True.
        """
        # Evitar redibujos automáticos (zoom/resizes) si ya fue dibujado
        if getattr(self, '_grid_drawn', False) and not force:
            return

        # Si el grid está desactivado en config, eliminar restos y marcar no dibujado
        if not self.config.get("grid_visible", True):
            try:
                self.canvas.delete("grid_bg")
            except Exception:
                pass
            try:
                self.canvas.delete("grid")
            except Exception:
                pass
            self._grid_drawn = False
            return

        # Limpiar previos
        try:
            self.canvas.delete("grid_bg")
        except Exception:
            pass
        try:
            self.canvas.delete("grid")
        except Exception:
            pass

        # Preparar parámetros
        grid_size_fixed = max(1, int(self.grid_size))
        grid_color = adapt_color_for_display("#e0e0e0", self.canvas.cget("bg"))

        # Determinar área visible (viewport) en coordenadas del canvas
        try:
            vx1 = int(self.canvas.canvasx(0))
            vy1 = int(self.canvas.canvasy(0))
            vx2 = int(self.canvas.canvasx(self.canvas.winfo_width()))
            vy2 = int(self.canvas.canvasy(self.canvas.winfo_height()))
        except Exception:
            vx1, vy1, vx2, vy2 = 0, 0, CANVAS_WIDTH, CANVAS_HEIGHT

        view_width = max(1, vx2 - vx1)
        view_height = max(1, vy2 - vy1)

        # Intentar usar PIL para crear un fondo tileable solo para la zona visible
        try:
            from PIL import Image, ImageDraw, ImageTk

            cache_key = (grid_size_fixed, grid_color)
            tile = self._grid_tile_cache.get(cache_key)

            if tile is None:
                tile_img = Image.new('RGBA', (grid_size_fixed, grid_size_fixed), (0, 0, 0, 0))
                draw = ImageDraw.Draw(tile_img)

                def hex_to_rgba(hx, alpha=180):
                    hx = hx.lstrip('#')
                    lv = len(hx)
                    return tuple(int(hx[i:i+lv//3], 16) for i in range(0, lv, lv//3)) + (alpha,)

                rgba = hex_to_rgba(grid_color, alpha=160)
                draw.line([(0, 0), (grid_size_fixed - 1, 0)], fill=rgba, width=1)
                draw.line([(0, 0), (0, grid_size_fixed - 1)], fill=rgba, width=1)

                tile = tile_img
                self._grid_tile_cache[cache_key] = tile

            bg_img = Image.new('RGBA', (view_width, view_height), (0, 0, 0, 0))
            for y in range(0, view_height, grid_size_fixed):
                for x in range(0, view_width, grid_size_fixed):
                    bg_img.paste(tile, (x, y), tile)

            # Convertir a PhotoImage y colocarla en la posición del viewport
            self._grid_bg_image = ImageTk.PhotoImage(bg_img)
            self.canvas.create_image(vx1, vy1, image=self._grid_bg_image, anchor='nw', tags='grid_bg')
            try:
                self.canvas.lower('grid_bg')
            except Exception:
                pass

            # Marcar que el grid ya fue dibujado (hasta que se fuerce)
            self._grid_drawn = True

        except Exception:
            # Fallback: dibujar sólo las líneas visibles
            try:
                # Líneas verticales visibles
                start_x = (vx1 // grid_size_fixed) * grid_size_fixed
                for x in range(start_x, vx2 + grid_size_fixed, grid_size_fixed):
                    self.canvas.create_line(x, vy1, x, vy2, fill=grid_color, dash=(2, 2), tags='grid')
                # Líneas horizontales visibles
                start_y = (vy1 // grid_size_fixed) * grid_size_fixed
                for y in range(start_y, vy2 + grid_size_fixed, grid_size_fixed):
                    self.canvas.create_line(vx1, y, vx2, y, fill=grid_color, dash=(2, 2), tags='grid')
                try:
                    self.canvas.lower('grid')
                except Exception:
                    pass
                self._grid_drawn = True
            except Exception:
                pass

    def on_canvas_mapped(self, event):
        """Se ejecuta cuando el canvas es mapeado por primera vez"""
        if not self.grid_initialized:
            self.grid_initialized = True
            # Usar after para asegurar que el canvas tenga las dimensiones finales
            self.root.after(100, lambda: self.draw_grid(force=True))
            # Canvas mapeado - programando dibujado del grid

    def ensure_grid_visible(self):
        """Asegura que el grid sea visible después de la inicialización completa"""
        if not self.grid_initialized:
            # Si aún no se ha inicializado, intentar dibujar el grid
            width = self.canvas.winfo_width()
            height = self.canvas.winfo_height()
            if width > 1 and height > 1:
                self.draw_grid(force=True)
                self.grid_initialized = True
                # Grid forzado después de inicialización completa
            else:
                pass
                # Si aún no tiene dimensiones, programar otro intento
                self.root.after(200, self.ensure_grid_visible)
                # Canvas aún sin dimensiones - reintentando

    def snap_to_grid(self, x, y, tolerance=36):
        """
        Ajusta las coordenadas al centro de la celda del grid más cercana.

        Args:
            x, y: Coordenadas originales del componente
            tolerance: Distancia máxima para activar snap (default: 36px)

        Returns:
            tuple: (x_snapped, y_snapped) coordenadas ajustadas al grid
        """
        if not hasattr(self, 'snap_to_grid_enabled') or not self.snap_to_grid_enabled.get():
            return x, y

        grid_size = self.grid_size

        # SNAP SUAVIZADO: Dividir en dos niveles de tolerancia
        # Nivel 1: Snap muy preciso (tolerancia reducida)
        precise_tolerance = tolerance * 0.6  # 60% de la tolerancia original

        # Encontrar la celda del grid más cercana
        celda_x = round(x / grid_size)
        celda_y = round(y / grid_size)

        # Calcular el centro de esa celda
        center_x = celda_x * grid_size + grid_size / 2
        center_y = celda_y * grid_size + grid_size / 2

        # Calcular distancia desde posición actual al centro de celda
        distance = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5

        # NIVEL 1: Snap preciso (solo si está muy cerca)
        if distance <= precise_tolerance:
            return center_x, center_y

        # NIVEL 2: Snap suave (tolerancia más amplia pero con corrección gradual)
        elif distance <= tolerance:
            # Snap parcial: aplicar solo 50% de la corrección
            correction_x = (center_x - x) * 0.5
            correction_y = (center_y - y) * 0.5
            return x + correction_x, y + correction_y

        # NIVEL 3: Sin snap (mantener posición original)
        else:
            return x, y

    def update_manhattan_line(self, connection):
        """
        Delega al ManhattanRouter
        Actualiza la ruta Manhattan de una conexión.
        """
        result = self.manhattan_router.update_manhattan_line(connection)

        # Marcar numeración como sucia para recalcular (Optimización)
        self.wire_numbering_dirty = True

        return result

    def on_canvas_drag(self, event):
        """Delegación al evento de arrastre del canvas."""
        return self.event_handler.on_canvas_drag(event)

    def on_canvas_release(self, event):
        """Delegación al evento de liberación del canvas."""
        return self.event_handler.on_canvas_release(event)

    def create_connection(self, start_component, start_point_idx, end_component, end_point_idx):
        """
        Crea una nueva conexión entre dos componentes.
        Método delegado para uso por el EventHandler.
        """
        new_connection = Connection(start_component, start_point_idx, end_component, end_point_idx)

        new_connection.line_color = self.current_line_color.get()
        new_connection.line_width = self.current_line_width.get()
        new_connection.line_dash = self.current_line_dash.get()  # Guardar string original, no procesado

        # 2. Estilizado automático según nombre de fase (N o PE)
        try:
            # Verificar TANTO start_component COMO end_component
            target_names = []

            if hasattr(start_component, 'label_data') and start_component.label_data:
                target_names.append(start_component.label_data.get('name', ''))
            elif hasattr(start_component, 'name'):
                target_names.append(start_component.name)

            if hasattr(end_component, 'label_data') and end_component.label_data:
                target_names.append(end_component.label_data.get('name', ''))
            elif hasattr(end_component, 'name'):
                target_names.append(end_component.name)

            # Normalizar y buscar coincidencias
            found_n = False
            found_pe = False

            for name in target_names:
                name_upper = name.upper().strip()
                if name_upper == "N":
                    found_n = True
                elif name_upper == "PE":
                    found_pe = True

            if found_pe:
                new_connection.line_color = "#008000"  # Verde para Tierra (Green standard)
                new_connection.line_dash = "4 2"       # Segmentada (Dashed)
            elif found_n:
                new_connection.line_color = "#0000FF"  # Azul para Neutro
                new_connection.line_dash = ""          # Sólida

        except Exception as e:
            pass

        new_connection.manually_modified = False  # Conexiones nuevas no están modificadas manualmente

        self.connections.append(new_connection)
        self.canvas.itemconfig(start_component.point_ids[start_point_idx], fill=adapt_color_for_display("#808080", self.canvas.cget("bg")))
        self.canvas.itemconfig(end_component.point_ids[end_point_idx], fill=adapt_color_for_display("#808080", self.canvas.cget("bg")))
        self.update_manhattan_line(new_connection)

        if hasattr(self, 'update_wire_numbers'):
            self.update_wire_numbers()

        self.first_point = None
        return new_connection

    def _try_auto_align(self, moved_component, moved_x, moved_y, fixed_x, fixed_y):
        """
        Si el quiebre entre dos puntos de conexión es menor a 10px en un eje,
        mueve moved_component para alinear ese eje con el punto fijo.

        Returns:
            bool: True si se aplicó una corrección.
        """
        dx = fixed_x - moved_x
        dy = fixed_y - moved_y
        if 0 < abs(dx) < 10:
            moved_component.move(dx, 0)
            return True
        elif 0 < abs(dy) < 10:
            moved_component.move(0, dy)
            return True
        return False

    def _update_manhattan_for_component(self, component):
        """Actualiza las líneas Manhattan de todas las conexiones de un componente."""
        for conn in self.connections:
            if (conn.start_component == component or
                conn.end_component == component):
                self.update_manhattan_line(conn)

    def auto_align_on_connection(self, start_component, start_point_idx, end_component, end_point_idx):
        """
        Alinea el segundo componente para que la línea quede recta
        si el quiebre es menor a 10px.
        """
        try:
            # Obtener coordenadas globales de los puntos
            points1 = start_component.get_connection_points_global()
            points2 = end_component.get_connection_points_global()

            if start_point_idx < len(points1) and end_point_idx < len(points2):
                x1, y1, _ = points1[start_point_idx]
                x2, y2, _ = points2[end_point_idx]

                if self._try_auto_align(end_component, x2, y2, x1, y1):
                    self._update_manhattan_for_component(end_component)
        except Exception as e:
            pass

    def auto_align_component_to_connections(self, component):
        """
        Alinea un componente recién movido con los componentes a los que está conectado
        si el quiebre es menor a 10px.
        """
        if not component:
            return

        try:
            # Buscar conexiones que involucren a este componente
            for conn in self.connections:
                other_comp = None
                my_point_idx = None
                other_point_idx = None

                if conn.start_component == component:
                    other_comp = conn.end_component
                    my_point_idx = conn.start_point_idx
                    other_point_idx = conn.end_point_idx
                elif conn.end_component == component:
                    other_comp = conn.start_component
                    my_point_idx = conn.end_point_idx
                    other_point_idx = conn.start_point_idx

                if other_comp:
                    my_points = component.get_connection_points_global()
                    other_points = other_comp.get_connection_points_global()

                    if my_point_idx < len(my_points) and other_point_idx < len(other_points):
                        mx, my, _ = my_points[my_point_idx]
                        ox, oy, _ = other_points[other_point_idx]

                        # Si hay un quiebre pequeño, corregir y salir (solo una corrección por movimiento)
                        if self._try_auto_align(component, mx, my, ox, oy):
                            self._update_manhattan_for_component(component)
                            return
        except Exception as e:
            pass

    def finish_connection(self, end_component, end_point_idx):
        """Completa una conexión iniciada en modo conexión"""
        if not self.connection_start:
            return

        start_component, start_point_idx = self.connection_start

        # Verificar que no sea el mismo componente y punto
        if start_component == end_component and start_point_idx == end_point_idx:
            self.connection_mode = False
            self.connection_start = None
            self.set_status("Conexión cancelada - mismo punto", "red")
            return

        # Auto-alinear antes de crear la conexión
        self.auto_align_on_connection(start_component, start_point_idx, end_component, end_point_idx)

        new_connection = self.create_connection(start_component, start_point_idx, end_component, end_point_idx)

        # Limpiar estado de conexión
        self.connection_mode = False
        self.connection_start = None

        if hasattr(self, 'set_status'):
            self.set_status(f"🔗 Conexión creada: {start_component.name} → {end_component.name}", "green")

        return new_connection

    def show_status_alert(self, text, color="#d32f2f", interval=550):
        """
        Muestra el tipo de falla en el label de alerta con efecto de VIDEO INVERSO
        (fondo = color de la alerta, texto = blanco) alternando con texto en color
        plano. Queda parpadeando hasta que se llame a clear_status_alert().

        Se usa para "CORTOCIRCUITO" y demás fallas: el rótulo queda fijo e inconfundible
        a la izquierda de la barra, separado del detalle en status_label_left.
        """
        if not hasattr(self, 'status_alert_label'):
            return

        self._status_alert_text = text
        self._status_alert_color = color
        self._status_alert_interval = interval

        # Ojo: el guard de empaquetado usa winfo_manager(), NO winfo_ismapped().
        # winfo_ismapped() sigue en 0 si la ventana está oculta (root.withdraw()) y
        # también antes del primer idle del gestor de geometría, con lo que
        # pack_forget() no se ejecutaría y la alerta quedaría pegada en la barra.
        if self.status_alert_label.winfo_manager() != 'pack':
            self.status_alert_label.pack(side="left", padx=(10, 6), pady=4, before=self.status_label_left)
        self._status_alert_blink_step(True)

    def show_fault_status(self, detalle, alert_text, color="#d32f2f"):
        """
        Deja fijo el aviso de falla: rótulo de alerta parpadeante en video inverso
        ("CORTOCIRCUITO") + detalle legible a su derecha, y enclava el mensaje para
        que las refrescas periódicas de la barra no lo sobrescriban con "Listo".
        """
        if not hasattr(self, 'status_label_left'):
            return

        self._status_fault_latched = True

        # Sin temporizador: la falla persiste hasta la próxima acción del usuario.
        if getattr(self, '_status_timer', None):
            try:
                self.root.after_cancel(self._status_timer)
            except Exception:
                pass
            self._status_timer = None
        self._status_deadline = None

        self.status_label_left.config(text=detalle.upper(), fg="red")
        self._status_last_msg = detalle.upper()
        self._status_last_color = "red"

        self.show_status_alert(alert_text, color)

    def clear_status_alert(self):
        """Detiene el parpadeo de la alerta y la oculta."""
        if getattr(self, '_status_alert_blink_id', None) is not None:
            try:
                self.root.after_cancel(self._status_alert_blink_id)
            except Exception:
                pass
            self._status_alert_blink_id = None

        label = getattr(self, 'status_alert_label', None)
        if label is not None:
            try:
                label.config(text="", bg="#e0e0e0", fg="#d32f2f")
                if label.winfo_manager() == 'pack':
                    label.pack_forget()
            except Exception:
                pass

    def _status_alert_blink_step(self, reverse):
        """Alterna entre video inverso y texto plano para producir el parpadeo."""
        label = getattr(self, 'status_alert_label', None)
        if label is None or not getattr(self, '_status_alert_text', ''):
            return

        try:
            if reverse:
                # VIDEO INVERSO: relleno del color de la alerta, glifo blanco
                label.config(text=self._status_alert_text,
                             bg=self._status_alert_color, fg="#ffffff")
            else:
                # Apagado: mismo texto, sólo coloreado
                label.config(text=self._status_alert_text,
                             bg="#e0e0e0", fg=self._status_alert_color)

            interval = getattr(self, '_status_alert_interval', 550)
            self._status_alert_blink_id = self.root.after(
                interval, lambda: self._status_alert_blink_step(not reverse))
        except Exception:
            self._status_alert_blink_id = None

    def set_status(self, message, color="black", duration=3000):
        """
        Establece un mensaje en la barra de estado.
        Si duration es None, el mensaje permanece hasta que otro evento lo cambie.

        Optimizado: si se repite el mismo mensaje con el mismo color mientras el
        temporizador sigue vigente, se omite reconfigurar el label y reprogramar el
        timer (se extiende solo cuando está por expirar para evitar parpadeos).
        """
        if not hasattr(self, 'status_label_left'):
            return

        # Cualquier mensaje normal apaga la alerta: si no, un "CORTOCIRCUITO"
        # parpadeando sobreviviría a un "Listo" o a un mensaje informativo posterior.
        self._status_fault_latched = False
        self.clear_status_alert()

        now = time.monotonic()
        same_text = (message, color) == (getattr(self, '_status_last_msg', None),
                                         getattr(self, '_status_last_color', None))

        # Sin cambios y el mensaje ya es permanente: no hacer nada
        if same_text and duration is None and not getattr(self, '_status_timer', None):
            return
        # Sin cambios y el timer sigue vigente (con margen para evitar flicker): saltar
        if (same_text and duration is not None and getattr(self, '_status_timer', None)
                and self._status_deadline is not None
                and now < self._status_deadline - 0.2):
            return

        self.status_label_left.config(text=message, fg=color)

        # Cancelar cualquier retorno previo programado
        if hasattr(self, '_status_timer') and self._status_timer:
            try:
                self.root.after_cancel(self._status_timer)
            except Exception:
                pass
            self._status_timer = None

        self._status_last_msg = message
        self._status_last_color = color

        # Programar el retorno a "Listo" sólo si se especifica duración
        if duration is not None:
            self._status_timer = self.root.after(duration, self.update_status_bar)
            self._status_deadline = now + (duration / 1000.0)
        else:
            self._status_timer = None
            self._status_deadline = None

    def update_status_bar(self):
        """Actualiza la barra de estado completa"""
        self.update_info_bar()
        # Con una falla enclavada sólo se refresca el bloque derecho: el rótulo
        # de alerta y el detalle deben seguir legibles hasta que el usuario actúe.
        if getattr(self, '_status_fault_latched', False):
            return
        self.clear_status_alert()
        if hasattr(self, 'status_label_left'):
            self.status_label_left.config(text="Listo", fg="black")
            self._status_timer = None

    def update_info_bar(self):
        """Actualiza la barra de información permanente (derecha)"""
        if not hasattr(self, 'status_label_right'):
            return

        zoom_pct = 100
        if hasattr(self, 'simple_zoom_manager'):
            zoom_pct = self.simple_zoom_manager.get_zoom_percentage()
        elif hasattr(self, 'canvas') and hasattr(self.canvas, 'zoom_level'):
            zoom_pct = int(self.canvas.zoom_level * 100)

        # 2. Pan
        pan_x = 0
        pan_y = 0
        if hasattr(self, 'canvas'):
            pan_x = self.canvas.canvasx(0)
            pan_y = self.canvas.canvasy(0)

        info_filename = "Sin guardar"
        if self.current_file:
            import os
            info_filename = os.path.basename(self.current_file)

        sheet_name = "Hoja 1"
        if hasattr(self, 'project'):
            active_sheet = self.project.get_active_sheet()
            if active_sheet:
                sheet_name = active_sheet.name

        # Construir y aplicar el texto
        info_text = f"Zoom: {zoom_pct}% | Pan: ({pan_x:.0f}, {pan_y:.0f}) | {info_filename} | {sheet_name}"
        self.status_label_right.config(text=info_text)

    def toggle_insert_point_mode(self):
        """Activa/desactiva el modo de insertar puntos en líneas con Ctrl+I"""
        self.is_insert_point_mode = not self.is_insert_point_mode

        if self.is_insert_point_mode:
            self.canvas.config(cursor="crosshair")
            if hasattr(self, 'set_status'):
                self.set_status("📍 Modo insertar punto ACTIVADO - Click derecho en cualquier línea", "blue")
            self._deactivate_all_buttons()
            self._activate_button("button4")
        else:
            self.canvas.config(cursor="arrow")
            if hasattr(self, 'set_status'):
                self.set_status("📍 Modo insertar punto DESACTIVADO", "black")
            # DESACTIVAR BOTÓN 4 (GRIS CUANDO INACTIVO)
            self._deactivate_button("button4")

    def handle_text_mode_callback(self, text_content, font_size, text_color=None):
        """Maneja el callback del panel lateral para activar/cancelar modo texto."""
        # Si el contenido está vacío, cancelar el modo texto
        if not text_content or font_size == 0:
            if self.text_mode:
                # Cancelando modo texto
                self.text_mode = False
                self.current_text_info = None
                self.canvas.config(cursor="arrow")
                if hasattr(self, 'set_status'):
                    self.set_status("Modo texto CANCELADO", "red")
            return

        # Si hay contenido, activar el modo texto con el color especificado
        self.activate_text_mode(text_content, font_size, text_color)

    def handle_shape_preview_callback(self, shape_name, is_manual_cancel=False):
        """Maneja el callback del panel lateral para activar/cancelar preview de formas."""
        # Si shape_name es None, cancelar el modo preview
        if shape_name is None:
            # Cancelar modo preview de formas
            if hasattr(self, 'shape_preview_mode') and self.shape_preview_mode:
                self.shape_preview_mode = False
                self.shape_preview_type = None
                # Solo borrar el preview del canvas si es una cancelación manual
                # (no cuando se acaba de crear una forma)
                if is_manual_cancel and hasattr(self, 'shape_preview_id') and self.shape_preview_id:
                    self.canvas.delete(self.shape_preview_id)
                    self.shape_preview_id = None
                self.canvas.config(cursor="arrow")
                if hasattr(self, 'set_status'):
                    self.set_status("Modo forma CANCELADO", "red")
            return

        # Cancelar preview de componentes si está activo
        if hasattr(self, 'component_preview_mode') and self.component_preview_mode:
            self.cancelar_preview_componente()

        # Activar modo preview de formas
        self.shape_preview_mode = True
        self.shape_preview_type = shape_name

        self.canvas.config(cursor="crosshair")

        # Mensaje de estado
        if hasattr(self, 'set_status'):
            self.set_status(f"🎨 Modo {shape_name}: Click para colocar", "green")

    def handle_shape_click(self, x, y):
        """Maneja el click para crear una forma en la posición especificada."""
        if not hasattr(self, 'shape_preview_mode') or not self.shape_preview_mode:
            return None

        shape_type = getattr(self, 'shape_preview_type', None)
        if not shape_type:
            return None

        try:
            shape = self.create_shape_at_position(shape_type, x, y)

            # Cancelar modo preview después de crear (SIN borrar la forma real)
            if hasattr(self, 'shape_preview_mode') and self.shape_preview_mode:
                self.shape_preview_mode = False
                self.shape_preview_type = None
                # NO borrar el preview_id aquí porque la forma real ya está creada
                # Solo limpiar las variables de estado
                self.shape_preview_id = None
                self.canvas.config(cursor="arrow")
                if hasattr(self, 'set_status'):
                    self.set_status("✅ Forma creada correctamente", "green")

            return shape
        except Exception as e:
            return None

    def activate_text_mode(self, text_content, font_size, text_color=None):
        """Activa el modo texto para crear un nuevo componente de texto."""
        try:
            # Limpiar selección anterior
            self.selected_component = None

            # Activar modo texto
            self.text_mode = True

            self.canvas.config(cursor="crosshair")

            # AGREGADO: Configurar información del texto con color
            self.current_text_info = {
                'content': text_content,
                'size': font_size,
                'color': text_color  # Color del texto
            }

            if hasattr(self, 'set_status'):
                self.set_status(f"📝 Modo texto: Click para colocar '{text_content}' (tamaño {font_size})", "green")

            # Modo texto activado

        except Exception as e:
            # Error activando modo texto
            pass

    def _find_horizontal_alignment_reference(self, text_comp, max_chars=2):
        """Busca el texto insertado que sirve de referencia de fila para alinear.

        Solo se consideran textos ya insertados por el usuario (TextComponent), nunca
        las etiquetas fijas de los componentes.

        La distancia horizontal es irrelevante: sirve cualquier texto ya colocado en la
        fila. El único criterio es la cercanía vertical, expresada en altura de carácter
        (font_size) del texto de referencia, de modo que la tolerancia escala con el
        tamaño de fuente usado.
        """
        try:
            zoom = getattr(self.canvas, "zoom_level", 1.0) or 1.0

            text_bbox = self.canvas.bbox(text_comp.canvas_id)
            if not text_bbox:
                return None
            current_center_y = (text_bbox[1] + text_bbox[3]) / 2.0

            best_bbox = None
            best_dist = None

            for other in getattr(self, "text_components", []):
                if other is text_comp:
                    continue
                cid = getattr(other, "canvas_id", None)
                if not cid:
                    continue
                try:
                    bbox = self.canvas.bbox(cid)
                except Exception:
                    continue
                if not bbox:
                    continue

                ref_center_y = (bbox[1] + bbox[3]) / 2.0
                dist = abs(ref_center_y - current_center_y)

                # Tolerancia en píxeles de canvas: N caracteres de alto
                ref_font_size = getattr(other, "font_size", None) or 12
                tolerance = max_chars * ref_font_size * zoom
                if dist > tolerance:
                    continue

                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_bbox = bbox

            return best_bbox
        except Exception:
            return None

    def _align_text_to_nearest_label(self, text_comp):
        """Alinea horizontalmente un texto insertado con el texto insertado más cercano.

        Iguala únicamente el centro vertical del texto con el del texto de referencia,
        de modo que ambos queden en la misma fila. La coordenada X no se modifica: el
        texto permanece donde se hizo clic.

        Solo se aplica si el texto está a no más de `max_chars` caracteres de la fila del
        texto de referencia; fuera de esa distancia vertical no se ajusta nada.
        """
        try:
            if not text_comp or not text_comp.canvas_id:
                return False

            zoom = getattr(self.canvas, "zoom_level", 1.0) or 1.0

            label_bbox = self._find_horizontal_alignment_reference(text_comp)
            if not label_bbox:
                return False

            text_bbox = self.canvas.bbox(text_comp.canvas_id)
            if not text_bbox:
                return False

            # Solo se ajusta la Y (misma fila). La X permanece donde se hizo clic.
            target_center_y = (label_bbox[1] + label_bbox[3]) / 2.0
            current_center_y = (text_bbox[1] + text_bbox[3]) / 2.0

            dy_world = (target_center_y - current_center_y) / zoom

            if abs(dy_world) < 0.5:
                return False

            text_comp.move(0, dy_world)
            return True
        except Exception:
            return False

    def place_text_component(self, x, y):
        """Coloca un componente de texto en la posición especificada."""
        try:
            # Debug: Mostrar información de ubicación

            # Validación de seguridad: verificar que hay contenido válido
            if not self.current_text_info or not self.current_text_info.get('content'):
                # Intento de crear texto sin contenido - cancelando
                return

            # Snap to grid si está habilitado
            snapped_x, snapped_y = self.snap_to_grid(x, y)

            from models.component import TextComponent

            text_color = self.current_text_info.get('color')
            text_comp = TextComponent(
                canvas=self.canvas,
                text=self.current_text_info['content'],
                font_size=self.current_text_info['size'],
                x=snapped_x,
                y=snapped_y,
                color=text_color # AGREGADO: Pasar color del texto
            )

            self.text_components.append(text_comp)

            # Auto-desactivar modo texto después de colocar
            self.text_mode = False
            self.current_text_info = None
            self.canvas.config(cursor="arrow")

            # Desactivar botón en el panel
            if hasattr(self, 'drawing_panel') and self.drawing_panel:
                self.drawing_panel.clear_text_mode()

            if hasattr(self, 'set_status'):
                self.set_status(f"✅ Texto '{text_comp.text}' colocado en ({snapped_x:.1f}, {snapped_y:.1f})", "green")

            # Texto colocado correctamente

            # Alinear con la etiqueta fija más cercana (misma línea horizontal)
            self._align_text_to_nearest_label(text_comp)

            # Auto-selección para permitir movimiento inmediato
            text_comp.select()
            self.selected_component = text_comp

        except Exception as e:
            # Error colocando texto

            self.cancel_text_mode()

    def cancel_text_mode(self):
        """Cancela el modo texto."""
        self.text_mode = False
        self.current_text_info = None
        self.canvas.config(cursor="arrow")

        if hasattr(self, 'set_status'):
            self.set_status("Modo texto cancelado", "red")

    def find_component_at_position(self, x, y):
        """
        Encuentra el componente (normal o texto) en la posición especificada.
        Incluye una tolerancia de búsqueda si el punto exacto falla.
        """
        # 1. Búsqueda exacta inicial
        for component in self.components:
            if hasattr(component, 'contains_point'):
                if component.contains_point(x, y):
                    return component

        for text_comp in self.text_components:
            if hasattr(text_comp, 'contains_point') and text_comp.contains_point(x, y):
                return text_comp

        # 2. Búsqueda con tolerancia (Hit Radius de 5px)
        # Útil para compensar errores de clic o desfases milimétricos
        tolerance = 5
        for component in self.components:
            if hasattr(component, 'contains_point'):
                # Probar en un pequeño área alrededor (9 puntos)
                for dx in [-tolerance, tolerance]:
                    for dy in [-tolerance, tolerance]:
                        if component.contains_point(x + dx, y + dy):
                            return component

        return None

    def insert_junction_point(self, connection, point, segment_idx):
        """
        Inserta un punto de empalme partiendo la línea original

        Args:
            connection: Conexión original a partir
            point: Punto exacto donde insertar (x, y)
            segment_idx: Índice del segmento donde se hizo click
        """
        try:
            pass

            # 1. Crear componente de empalme usando JunctionComponent
            junction_count = len([c for c in self.components if isinstance(c, JunctionComponent)]) + 1
            junction_component = JunctionComponent(
                canvas=self.canvas,
                name=f"J{junction_count}",
                x=point[0],
                y=point[1],
                config=self.config
            )

            self.components.append(junction_component)

            # 2. Guardar información de la conexión original
            start_comp = connection.start_component
            start_point_idx = connection.start_point_idx
            end_comp = connection.end_component
            end_point_idx = connection.end_point_idx
            original_segments = connection.segments.copy()  # Copiar segmentos originales
            mid_y_offset = getattr(connection, 'mid_y_offset', 0)
            mid_x_offset = getattr(connection, 'mid_x_offset', 0)

            # 3. PARTIR EL SEGMENTO ESPECÍFICO donde se hizo click
            target_segment = original_segments[segment_idx]
            (x1, y1), (x2, y2) = target_segment

            segment_part_1 = ((x1, y1), (point[0], point[1]))  # Desde inicio del segmento hasta el punto
            segment_part_2 = ((point[0], point[1]), (x2, y2))  # Desde el punto hasta fin del segmento

            # 4. CONSTRUIR SEGMENTOS PARA PRIMERA CONEXIÓN (A -> Junction)
            segments_1 = []
            # Añadir todos los segmentos ANTES del segmento partido
            for i in range(segment_idx):
                segments_1.append(original_segments[i])
            segments_1.append(segment_part_1)

            # 5. CONSTRUIR SEGMENTOS PARA SEGUNDA CONEXIÓN (Junction -> B)
            segments_2 = []
            segments_2.append(segment_part_2)
            # Añadir todos los segmentos DESPUÉS del segmento partido
            for i in range(segment_idx + 1, len(original_segments)):
                segments_2.append(original_segments[i])

            # 6. Crear las nuevas conexiones
            from models.connection import Connection
            nueva_conexion_1 = Connection(
                start_comp,
                start_point_idx,
                junction_component,
                0  # Primer punto del empalme
            )
            nueva_conexion_1.segments = segments_1
            nueva_conexion_1.line_ids = []  # Inicializar para _redraw_connection_fast
            nueva_conexion_1.mid_y_offset = mid_y_offset
            nueva_conexion_1.mid_x_offset = mid_x_offset
            nueva_conexion_1.manually_modified = getattr(connection, 'manually_modified', False)
            # NO establecer manual_angle_points - los segmentos ya están definidos

            # PRESERVAR PROPIEDADES DE ESTILO DE LA CONEXIÓN ORIGINAL
            if hasattr(connection, 'line_color'):
                nueva_conexion_1.line_color = connection.line_color
            if hasattr(connection, 'line_width'):
                nueva_conexion_1.line_width = connection.line_width
            if hasattr(connection, 'line_dash'):
                nueva_conexion_1.line_dash = connection.line_dash

            nueva_conexion_2 = Connection(
                junction_component,
                1,  # Segundo punto del empalme
                end_comp,
                end_point_idx
            )
            nueva_conexion_2.segments = segments_2
            nueva_conexion_2.line_ids = []  # Inicializar para _redraw_connection_fast
            nueva_conexion_2.mid_y_offset = mid_y_offset
            nueva_conexion_2.mid_x_offset = mid_x_offset
            nueva_conexion_2.manually_modified = getattr(connection, 'manually_modified', False)
            # NO establecer manual_angle_points - los segmentos ya están definidos

            # PRESERVAR PROPIEDADES DE ESTILO DE LA CONEXIÓN ORIGINAL
            if hasattr(connection, 'line_color'):
                nueva_conexion_2.line_color = connection.line_color
            if hasattr(connection, 'line_width'):
                nueva_conexion_2.line_width = connection.line_width
            if hasattr(connection, 'line_dash'):
                nueva_conexion_2.line_dash = connection.line_dash

            # 7. Eliminar conexión original
            if connection in self.connections:
                # Limpiar elementos visuales
                for line_id in connection.line_ids:
                    try:
                        self.canvas.delete(line_id)
                    except:
                        pass
                self.connections.remove(connection)

            # 8. Agregar nuevas conexiones
            self.connections.extend([nueva_conexion_1, nueva_conexion_2])

            # 9. Redibujar SOLO las líneas (no recalcular Manhattan)
            self._draw_connection_lines(nueva_conexion_1)
            self._draw_connection_lines(nueva_conexion_2)

            # 10. Dibujar el componente de empalme
            junction_component.draw()

            if hasattr(self, 'set_status'):
                self.set_status(f"✅ Punto de empalme insertado: {junction_component.name}", "green")

            # DESACTIVAR BOTÓN 4 DESPUÉS DE INSERTAR PUNTO (comportamiento especial)
            self._deactivate_button("button4")
            self.is_insert_point_mode = False

        except Exception as e:
            # Error insertando punto de empalme
            import traceback
            traceback.print_exc()
            if hasattr(self, 'set_status'):
                self.set_status("Error insertando punto de empalme", "red")
            return None

        return junction_component

    def _draw_connection_lines(self, connection):
        """
        Delega al ManhattanRouter
        Dibuja las líneas de una conexión basándose en sus segmentos existentes
        (NO recalcula Manhattan - solo dibuja los segmentos que ya tiene la conexión)
        """
        return self.manhattan_router.draw_connection_lines(connection)

    def force_canvas_refresh(self):
        """Fuerza una actualización completa del canvas para eliminar trazas visuales"""
        self.canvas.update()

    def buscar_linea_intersectada(self, x, y):
        """Busca si hay una línea cerca del punto especificado"""
        tolerancia = 10  # píxeles de tolerancia

        # Buscar en conexiones normales
        for conn in self.connections:
            for i, ((x1, y1), (x2, y2)) in enumerate(conn.segments):
                if is_near_segment(x, y, x1, y1, x2, y2, tolerancia):
                    return {"tipo": "conexion", "conexion": conn, "segmento_idx": i}

        return None

    def _init_crosshair(self):
        """Crear las líneas del crosshair una sola vez para optimización"""
        try:
            width = self.canvas.winfo_width()
            height = self.canvas.winfo_height()

            # Línea horizontal inicial (fuera de vista)
            self.crosshair_h = self.canvas.create_line(
                0, -100, width, -100,
                fill="#888888", width=1,
                dash=(2, 2), tags='crosshair'
            )

            # Línea vertical inicial (fuera de vista)
            self.crosshair_v = self.canvas.create_line(
                -100, 0, -100, height,
                fill="#888888", width=1,
                dash=(2, 2), tags='crosshair'
            )

            # Asegurar que las líneas existan como atributos
            self.crosshair_created = True

        except Exception:
            # Silenciar errores para no interferir
            pass

    def _load_button_image(self, svg_file, size=(50, 50)):
        """Cargar imagen SVG optimizada"""
        if not SVG_SUPPORT:
            return None

        try:
            alto_boton = size[1]

            # Construir ruta completa al archivo SVG
            svg_path = get_app_dir() / "svgs" / svg_file

            dims = get_svg_dimensions(svg_path)
            if dims:
                ancho_original, alto_original = dims
                # Calcular nuevo ancho manteniendo proporción según el alto del botón
                ratio = alto_boton / alto_original
                nuevo_ancho = max(1, int(ancho_original * ratio))
            else:
                nuevo_ancho = alto_boton

            # Delegar en el renderizador centralizado: guarda el resultado en disco,
            # así la barra vertical deja de rasterizar los mismos SVG en cada arranque.
            from utils.svg_renderer import get_svg_renderer
            renderer = get_svg_renderer(self.config.get("svg_path"))
            return renderer.create_button_image(svg_file, (nuevo_ancho, alto_boton))

        except Exception as e:
            _report_error(f"Load Button Image ({svg_file})", e)
            return None

    def _create_custom_buttons(self):
        """Crear 7 botones con funciones de atajos en la barra vertical de 40px."""
        # Almacenar referencias a botones para indicadores visuales
        self.button_widgets = {}

        # Estado activo de botones verticales para color verde cuando activos
        self.button_active_states = {
            'button1': False,
            'button2': False,
            'button3': False,
            'button_alinear_hs': False,
            'button4': False,
            'button5': False,
            'button6': False,
            'button7': False,
            'button8': False,
            'button_cauto': True,  # Por defecto activo (Detección Automática)
            'button_cprox': False,   # Por defecto activo (Preview Proximidad)
            'button_riel_dim': False,   # Ctrl+D: Insertar Riel DIN
            'button_canaleta': False,   # Ctrl+F: Insertar Canaleta
            'button_block_t': False,    # Ctrl+B: Insertar Block Terminal
        }

        # Botón1: Ctrl+H - Centrar Verticalmente
        self.btn1_image = self._load_button_image("AlinearV.svg", size=(24, 35))
        btn1 = tk.Button(
            self.custom_buttons_bar,
            image=self.btn1_image if self.btn1_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_ctrl_h()
        )
        btn1.pack()
        btn1.image = self.btn1_image  # CRÍTICO: mantener referencia
        self.button_widgets["button1"] = btn1

        # Tooltip
        title1 = get_svg_title(get_app_dir() / "svgs" / "AlinearV.svg")
        if title1: ToolTip(btn1, title1, condition_callback=self.tooltips_enabled.get)

        # Botón2: Ctrl+J - Distribución Vertical
        self.btn2_image = self._load_button_image("AlinearVS.svg", size=(24, 35))
        btn2 = tk.Button(
            self.custom_buttons_bar,
            image=self.btn2_image if self.btn2_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_ctrl_j()
        )
        btn2.pack()
        btn2.image = self.btn2_image  # CRÍTICO: mantener referencia
        self.button_widgets["button2"] = btn2

        # Tooltip
        title2 = get_svg_title(get_app_dir() / "svgs" / "AlinearVS.svg")
        if title2: ToolTip(btn2, title2, condition_callback=self.tooltips_enabled.get)

        # Botón3: Ctrl+K - Distribución Horizontal
        self.btn3_image = self._load_button_image("AlinearH.svg", size=(24, 35))
        self.btn4_image = self._load_button_image("PConxn.svg", size=(24, 35))
        btn3 = tk.Button(
            self.custom_buttons_bar,
            image=self.btn3_image if self.btn3_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_ctrl_k()
        )
        btn3.pack()
        btn3.image = self.btn3_image  # CRÍTICO: mantener referencia
        self.button_widgets["button3"] = btn3

        # Tooltip
        title3 = get_svg_title(get_app_dir() / "svgs" / "AlinearH.svg")
        if title3: ToolTip(btn3, title3, condition_callback=self.tooltips_enabled.get)

        # Botón AlinearHS: Alinear Horizontalmente
        self.btn_alinear_hs_image = self._load_button_image("AlinearHS.svg", size=(24, 35))
        btn_alinear_hs = tk.Button(
            self.custom_buttons_bar,
            image=self.btn_alinear_hs_image if self.btn_alinear_hs_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_alinear_hs()
        )
        btn_alinear_hs.pack()
        btn_alinear_hs.image = self.btn_alinear_hs_image
        self.button_widgets["button_alinear_hs"] = btn_alinear_hs

        # Tooltip
        title_ahs = get_svg_title(get_app_dir() / "svgs" / "AlinearHS.svg")
        if title_ahs: ToolTip(btn_alinear_hs, title_ahs, condition_callback=self.tooltips_enabled.get)

        btn4 = tk.Button(
            self.custom_buttons_bar,
            image=self.btn4_image if self.btn4_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_ctrl_i()
        )
        btn4.pack()
        btn4.image = self.btn4_image  # CRÍTICO: mantener referencia
        self.button_widgets["button4"] = btn4

        # Tooltip
        title4 = get_svg_title(get_app_dir() / "svgs" / "PConxn.svg")
        if title4: ToolTip(btn4, title4, condition_callback=self.tooltips_enabled.get)

        # Botón5: Ctrl+R - Rotación derecha
        self.btn5_image = self._load_button_image("RotarD.svg", size=(24, 35))
        btn5 = tk.Button(
            self.custom_buttons_bar,
            image=self.btn5_image if self.btn5_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_ctrl_r()
        )
        btn5.pack()
        btn5.image = self.btn5_image
        self.button_widgets["button5"] = btn5

        # Tooltip
        title5 = get_svg_title(get_app_dir() / "svgs" / "RotarD.svg")
        if title5: ToolTip(btn5, title5, condition_callback=self.tooltips_enabled.get)

        # Botón6: Shift+Ctrl+R - Rotación izquierda
        self.btn6_image = self._load_button_image("RotarI.svg", size=(24, 35))
        btn6 = tk.Button(
            self.custom_buttons_bar,
            image=self.btn6_image if self.btn6_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_shift_ctrl_r()
        )
        btn6.pack()
        btn6.image = self.btn6_image
        self.button_widgets["button6"] = btn6

        # Tooltip
        title6 = get_svg_title(get_app_dir() / "svgs" / "RotarI.svg")
        if title6: ToolTip(btn6, title6, condition_callback=self.tooltips_enabled.get)

        # Botón ReflejoH: Reflejo Horizontal (sin acción asignada aún)
        self.btn_reflejo_h_image = self._load_button_image("ReflejoH.svg", size=(24, 35))
        btn_reflejo_h = tk.Button(
            self.custom_buttons_bar,
            image=self.btn_reflejo_h_image if self.btn_reflejo_h_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self.flip_selected_horizontal()
        )
        btn_reflejo_h.pack()
        btn_reflejo_h.image = self.btn_reflejo_h_image
        self.button_widgets["button_reflejo_h"] = btn_reflejo_h

        # Tooltip
        title_rh = get_svg_title(get_app_dir() / "svgs" / "ReflejoH.svg")
        if title_rh: ToolTip(btn_reflejo_h, title_rh, condition_callback=self.tooltips_enabled.get)

        # Botón ReflejoV: Reflejo Vertical (sin acción asignada aún)
        self.btn_reflejo_v_image = self._load_button_image("ReflejoV.svg", size=(24, 35))
        btn_reflejo_v = tk.Button(
            self.custom_buttons_bar,
            image=self.btn_reflejo_v_image if self.btn_reflejo_v_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self.flip_selected_vertical()  # Reflejo vertical
        )
        btn_reflejo_v.pack()
        btn_reflejo_v.image = self.btn_reflejo_v_image
        self.button_widgets["button_reflejo_v"] = btn_reflejo_v

        # Tooltip
        title_rv = get_svg_title(get_app_dir() / "svgs" / "ReflejoV.svg")
        if title_rv: ToolTip(btn_reflejo_v, title_rv, condition_callback=self.tooltips_enabled.get)

        # Botón7: Ctrl+X - Toggle invertir detección
        self.btn7_image = self._load_button_image("Invert.svg", size=(24, 35))
        btn7 = tk.Button(
            self.custom_buttons_bar,
            image=self.btn7_image if self.btn7_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_ctrl_x()
        )
        btn7.pack()
        btn7.image = self.btn7_image
        self.button_widgets["button7"] = btn7

        # Tooltip
        title7 = get_svg_title(get_app_dir() / "svgs" / "Invert.svg")
        if title7: ToolTip(btn7, title7, condition_callback=self.tooltips_enabled.get)

        # Botón8: Ctrl+Click - Línea manual
        self.btn8_image = self._load_button_image("LManual.svg", size=(24, 35))
        btn8 = tk.Button(
            self.custom_buttons_bar,
            image=self.btn8_image if self.btn8_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_ctrl_click()
        )
        btn8.pack()
        btn8.image = self.btn8_image
        self.button_widgets["button8"] = btn8

        # Tooltip
        title8 = get_svg_title(get_app_dir() / "svgs" / "LManual.svg")
        if title8: ToolTip(btn8, title8, condition_callback=self.tooltips_enabled.get)

        # Botón CAuto: Toggle Detección Automática
        self.btn_cauto_image = self._load_button_image("CAuto.svg", size=(24, 35))
        btn_cauto = tk.Button(
            self.custom_buttons_bar,
            image=self.btn_cauto_image if self.btn_cauto_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#FF5555" if self.auto_conexion_enabled.get() else "#c3c3c3",  # Verde si activo
            command=lambda: self._toggle_auto_deteccion()
        )
        btn_cauto.pack()
        btn_cauto.image = self.btn_cauto_image
        self.button_widgets["button_cauto"] = btn_cauto

        # Tooltip
        title_ca = get_svg_title(get_app_dir() / "svgs" / "CAuto.svg")
        if title_ca: ToolTip(btn_cauto, title_ca, condition_callback=self.tooltips_enabled.get)

        # Botón CProx: Toggle Preview Proximidad (líneas verdes)
        self.btn_cprox_image = self._load_button_image("CProx.svg", size=(24, 35))
        btn_cprox = tk.Button(
            self.custom_buttons_bar,
            image=self.btn_cprox_image if self.btn_cprox_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#55FF55" if self.proximity_preview_enabled.get() else "#c3c3c3",  # Verde si activo
            command=lambda: self._toggle_proximity_preview()
        )
        btn_cprox.pack()
        btn_cprox.image = self.btn_cprox_image
        self.button_widgets["button_cprox"] = btn_cprox

        # Tooltip
        title_cp = get_svg_title(get_app_dir() / "svgs" / "CProx.svg")
        if title_cp: ToolTip(btn_cprox, title_cp, condition_callback=self.tooltips_enabled.get)

        # Botón Apantallamiento: Nuevo sistema de dibujo de apantallamiento
        self.btn_apantallamiento_image = self._load_button_image("Apantallamiento.svg", size=(24, 35))
        btn_apantallamiento = tk.Button(
            self.custom_buttons_bar,
            image=self.btn_apantallamiento_image if self.btn_apantallamiento_image else None,
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._toggle_shielding_mode()
        )
        btn_apantallamiento.pack()
        btn_apantallamiento.image = self.btn_apantallamiento_image
        self.button_widgets["button_shielding"] = btn_apantallamiento

        # Tooltip
        title_ap = get_svg_title(get_app_dir() / "svgs" / "Apantallamiento.svg")
        if title_ap: ToolTip(btn_apantallamiento, title_ap, condition_callback=self.tooltips_enabled.get)

        # Separador visual antes de los botones de Gabinete 2D
        self.sep_2d = tk.Frame(self.custom_buttons_bar, height=2, bg="#999999")
        self.sep_2d.pack(fill="x", padx=4, pady=3)

        # Botón RielDim: Ctrl+D – Insertar Riel DIN
        self.btn_riel_dim_image = self._load_button_image("RielDim.svg", size=(24, 35))
        btn_riel_dim = tk.Button(
            self.custom_buttons_bar,
            image=self.btn_riel_dim_image if self.btn_riel_dim_image else None,
            text="" if self.btn_riel_dim_image else "╠═",
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_ctrl_d()
        )
        btn_riel_dim.pack()
        btn_riel_dim.image = self.btn_riel_dim_image
        self.button_widgets["button_riel_dim"] = btn_riel_dim

        # Tooltip
        title_rd = get_svg_title(get_app_dir() / "svgs" / "RielDim.svg")
        ToolTip(btn_riel_dim, title_rd or "Riel DIN (Ctrl+D)", condition_callback=self.tooltips_enabled.get)

        # Botón Canaleta: Ctrl+F – Insertar Canaleta
        self.btn_canaleta_image = self._load_button_image("Canaleta.svg", size=(24, 35))
        btn_canaleta = tk.Button(
            self.custom_buttons_bar,
            image=self.btn_canaleta_image if self.btn_canaleta_image else None,
            text="" if self.btn_canaleta_image else "▭",
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_ctrl_f()
        )
        btn_canaleta.pack()
        btn_canaleta.image = self.btn_canaleta_image
        self.button_widgets["button_canaleta"] = btn_canaleta

        # Tooltip
        title_cn = get_svg_title(get_app_dir() / "svgs" / "Canaleta.svg")
        ToolTip(btn_canaleta, title_cn or "Canaleta 40 mm (Ctrl+F)", condition_callback=self.tooltips_enabled.get)

        # Botón Block_T: Ctrl+B – Insertar Block Terminal
        self.btn_block_t_image = self._load_button_image("Block_T.svg", size=(24, 35))
        btn_block_t = tk.Button(
            self.custom_buttons_bar,
            image=self.btn_block_t_image if self.btn_block_t_image else None,
            text="" if self.btn_block_t_image else "⊞",
            width=40,
            height=40,
            compound="center",
            relief=tk.FLAT,
            borderwidth=0,
            bg="#c3c3c3",
            command=lambda: self._simulate_ctrl_b()
        )
        btn_block_t.pack()
        btn_block_t.image = self.btn_block_t_image
        self.button_widgets["button_block_t"] = btn_block_t

        # Tooltip
        title_bt = get_svg_title(get_app_dir() / "svgs" / "Block_T.svg")
        ToolTip(btn_block_t, title_bt or "Block Terminal (Ctrl+B)", condition_callback=self.tooltips_enabled.get)

    def _update_buttons_for_sheet(self, sheet_name):
        """Muestra u oculta botones de la barra vertical según la hoja activa.

        En «Hoja de Gabinete 2D» sólo se muestran:
          • Insertar Riel DIN       (button_riel_dim)
          • Insertar Canaleta       (button_canaleta)
          • Insertar Block Terminal (button_block_t)
          • Rotar derecha           (button5)
          • Rotar izquierda         (button6)
        Al salir se muestran todos los botones excepto los tres exclusivos del gabinete.
        """
        if not hasattr(self, 'button_widgets'):
            return

        # Botones exclusivos de Gabinete 2D (ocultos en el resto de hojas)
        GABINETE_ONLY = {"button_riel_dim", "button_canaleta", "button_block_t"}
        # Botones de alineación y rotación (visibilidad condicionada por configuración en Gabinete 2D)
        CONDITIONAL_GABINETE = {"button1", "button2", "button3", "button_alinear_hs", "button5", "button6"}

        is_gabinete = (sheet_name == "Hoja de Gabinete 2D")
        align_enabled = self.config.get("align_points_enabled", False)

        for key, widget in self.button_widgets.items():
            if is_gabinete:
                # Sólo visibles: exclusivos del gabinete + condicionales si están activados
                if key in GABINETE_ONLY:
                    widget.pack()
                elif key in CONDITIONAL_GABINETE:
                    if align_enabled:
                        widget.pack()
                    else:
                        widget.pack_forget()
                else:
                    widget.pack_forget()
            else:
                # Fuera del gabinete: todo excepto los exclusivos
                if key in GABINETE_ONLY:
                    widget.pack_forget()
                else:
                    widget.pack()

        # Separador: visible sólo dentro del gabinete
        if hasattr(self, 'sep_2d'):
            if is_gabinete:
                self.sep_2d.pack(fill="x", padx=4, pady=3)
            else:
                self.sep_2d.pack_forget()

    def _simulate_ctrl_h(self):
        """Simula exactamente Ctrl+H llamando al mismo event_handler que el atajo de teclado."""
        try:
            simulated_event = type('Event', (), {
                'keysym': 'h',
                'state': 4  # 4 = Ctrl presionado en Tkinter
            })()

            # Indicador visual temporal (azul claro para fondo blanco)
            if "button1" in self.button_widgets:
                self.button_widgets["button1"].config(bg="#e3f2fd", fg="#1976d2")
                self.root.update()

            # Llamar exactamente al mismo método que maneja Ctrl+H del teclado
            if hasattr(self, 'event_handler'):
                self.event_handler.on_key_press(simulated_event)

            # Restaurar color normal después de un breve momento
            if "button1" in self.button_widgets:
                self.root.after(150, lambda: self.button_widgets["button1"].config(bg="#c3c3c3", fg="#333333"))

        except Exception as e:
            # Silenciar errores para no interferir
            pass

    def _simulate_ctrl_j(self):
        """Simula exactamente Ctrl+J llamando al mismo event_handler que el atajo de teclado."""
        try:
            simulated_event = type('Event', (), {
                'keysym': 'j',
                'state': 4  # 4 = Ctrl presionado en Tkinter
            })()

            # Indicador visual temporal (verde claro para fondo blanco)
            if "button2" in self.button_widgets:
                self.button_widgets["button2"].config(bg="#e8f5e8", fg="#388e3c")
                self.root.update()

            # Llamar exactamente al mismo método que maneja Ctrl+J del teclado
            if hasattr(self, 'event_handler'):
                self.event_handler.on_key_press(simulated_event)

            # Restaurar color normal después de un breve momento
            if "button2" in self.button_widgets:
                self.root.after(150, lambda: self.button_widgets["button2"].config(bg="#c3c3c3", fg="#333333"))

        except Exception as e:
            # Silenciar errores para no interferir
            pass

    def _simulate_alinear_hs(self):
        """Simula exactamente Ctrl+M (Alinear Horizontalmente) llamando al mismo event_handler."""
        try:
            simulated_event = type('Event', (), {
                'keysym': 'm',
                'state': 4  # 4 = Ctrl presionado en Tkinter
            })()

            # Indicador visual temporal (amarillo claro para fondo blanco)
            if "button_alinear_hs" in self.button_widgets:
                self.button_widgets["button_alinear_hs"].config(bg="#fff8e1", fg="#f57c00")
                self.root.update()

            # Llamar exactamente al mismo método que maneja Ctrl+M del teclado
            if hasattr(self, 'event_handler'):
                self.event_handler.on_key_press(simulated_event)

            # Restaurar color normal después de un breve momento
            if "button_alinear_hs" in self.button_widgets:
                self.root.after(150, lambda: self.button_widgets["button_alinear_hs"].config(bg="#c3c3c3", fg="#333333"))

        except Exception as e:
            # Silenciar errores para no interferir
            pass

    def _simulate_ctrl_k(self):
        """Simula exactamente Ctrl+K llamando al mismo event_handler que el atajo de teclado."""
        try:
            # Crear evento simulado: keysym='k' y state=4 (Ctrl presionado)
            simulated_event = type('Event', (), {
                'keysym': 'k',
                'state': 4  # 4 = Ctrl presionado en Tkinter
            })()

            # Indicador visual temporal (amarillo claro para fondo blanco)
            if "button3" in self.button_widgets:
                self.button_widgets["button3"].config(bg="#fff8e1", fg="#f57c00")
                self.root.update()

            # Llamar exactamente al mismo método que maneja Ctrl+K del teclado
            if hasattr(self, 'event_handler'):
                self.event_handler.on_key_press(simulated_event)

            # Restaurar color normal después de un breve momento
            if "button3" in self.button_widgets:
                self.root.after(150, lambda: self.button_widgets["button3"].config(bg="#c3c3c3", fg="#333333"))

        except Exception as e:
            # Silenciar errores para no interferir
            pass

    def _simulate_ctrl_i(self):
        """Simula exactamente Ctrl+I llamando al mismo event_handler que el atajo de teclado."""
        try:
            # Desactivar todos los botones y activar botón 4
            self._deactivate_all_buttons()
            self._activate_button("button4")

            simulated_event = type('Event', (), {
                'keysym': 'i',
                'state': 4  # 4 = Ctrl presionado en Tkinter
            })()

            # Indicador visual temporal (púrpura claro para fondo blanco)
            if "button4" in self.button_widgets:
                self.button_widgets["button4"].config(bg="#f3e5f5", fg="#7b1fa2")
                self.root.update()

            # Llamar exactamente al mismo método que maneja Ctrl+I del teclado
            if hasattr(self, 'event_handler'):
                self.event_handler.on_key_press(simulated_event)

            # Restaurar color activo después de un breve momento
            if "button4" in self.button_widgets:
                self.root.after(150, lambda: self.button_widgets["button4"].config(bg="#4CAF50", fg="white"))

        except Exception as e:
            # Silenciar errores para no interferir
            pass

    def _simulate_ctrl_r(self):
        """Simula exactamente Ctrl+R (rotación derecha) llamando al mismo event_handler que el atajo de teclado."""
        try:
            simulated_event = type('Event', (), {
                'keysym': 'r',
                'state': 4  # 4 = Ctrl presionado en Tkinter
            })()

            # Indicador visual temporal (naranja claro para fondo blanco)
            if "button5" in self.button_widgets:
                self.button_widgets["button5"].config(bg="#fff3e0", fg="#f57c00")
                self.root.update()

            # Llamar exactamente al mismo método que maneja Ctrl+R del teclado
            if hasattr(self, 'event_handler'):
                self.event_handler.on_key_press(simulated_event)

            # Restaurar color normal después de un breve momento
            if "button5" in self.button_widgets:
                self.root.after(150, lambda: self.button_widgets["button5"].config(bg="#c3c3c3", fg="#333333"))

        except Exception as e:
            # Silenciar errores para no interferir
            pass

    def _simulate_shift_ctrl_r(self):
        """Simula exactamente Shift+Ctrl+R (rotación izquierda) llamando al mismo event_handler que el atajo de teclado."""
        try:
            simulated_event = type('Event', (), {
                'keysym': 'r',
                'state': 5  # 0x4 (Ctrl) + 0x1 (Shift) = 5
            })()

            # Indicador visual temporal (verde claro para fondo blanco)
            if "button6" in self.button_widgets:
                self.button_widgets["button6"].config(bg="#e8f5e8", fg="#388e3c")
                self.root.update()

            # Llamar exactamente al mismo método que maneja Shift+Ctrl+R del teclado
            if hasattr(self, 'event_handler'):
                self.event_handler.on_key_press(simulated_event)

            # Restaurar color normal después de un breve momento
            if "button6" in self.button_widgets:
                self.root.after(150, lambda: self.button_widgets["button6"].config(bg="#c3c3c3", fg="#333333"))

        except Exception as e:
            # Silenciar errores para no interferir
            pass

    def _simulate_ctrl_x(self):
        """Simula exactamente Ctrl+X (toggle invertir detección) llamando al mismo event_handler que el atajo de teclado."""
        try:
            # Crear evento simulado: keysym='x' y state=4 (Ctrl presionado)
            simulated_event = type('Event', (), {
                'keysym': 'x',
                'state': 4  # 4 = Ctrl presionado en Tkinter
            })()

            # Indicador visual temporal (rojo claro para fondo blanco)
            if "button7" in self.button_widgets:
                self.button_widgets["button7"].config(bg="#ffebee", fg="#d32f2f")
                self.root.update()

            # Llamar exactamente al mismo método que maneja Ctrl+X del teclado
            if hasattr(self, 'event_handler'):
                self.event_handler.on_key_press(simulated_event)

            if "button7" in self.button_widgets:
                def update_button_color():
                    if hasattr(self, 'invertir_deteccion') and self.invertir_deteccion.get():
                        # Activo: verde
                        self.button_widgets["button7"].config(bg="#4CAF50", fg="white")
                        self.button_active_states["button7"] = True
                    else:
                        # Inactivo: gris
                        self.button_widgets["button7"].config(bg="#c3c3c3", fg="#333333")
                        self.button_active_states["button7"] = False

                self.root.after(150, update_button_color)

        except Exception as e:
            # Silenciar errores para no interferir
            pass

    # BOTONES DE GABINETE 2D: Riel DIN (Ctrl+D), Canaleta (Ctrl+F), Block (Ctrl+B)
    # Patrón: activar verde al pulsar -> desactivar automáticamente cuando el
    # modo shape_drawing finaliza (finish_drawing) o se cancela (Escape / cancel).

    def _simulate_ctrl_d(self):
        """Activa el modo de dibujo de Riel DIN (Ctrl+D) con feedback visual persistente."""
        try:
            # Si el botón ya estaba activo (segundo clic = cancelar modo)
            if self.button_active_states.get("button_riel_dim", False):
                if hasattr(self, 'event_handler'):
                    self.event_handler.shape_drawing.cancel()
                self._deactivate_button("button_riel_dim")
                self.set_status("🛑 Riel DIN cancelado", "orange")
                return

            # Desactivar otros modos de dibujo 2D
            self._deactivate_button("button_canaleta")
            self._deactivate_button("button_block_t")

            # Activar color verde (modo activo)
            self._activate_button("button_riel_dim")

            self.activate_din_rail_draw()

        except Exception:
            pass

    def _simulate_ctrl_f(self):
        """Activa el modo de dibujo de Canaleta (Ctrl+F) con feedback visual persistente."""
        try:
            # Si el botón ya estaba activo (segundo clic = cancelar modo)
            if self.button_active_states.get("button_canaleta", False):
                if hasattr(self, 'event_handler'):
                    self.event_handler.shape_drawing.cancel()
                self._deactivate_button("button_canaleta")
                self.set_status("🛑 Canaleta cancelada", "orange")
                return

            # Desactivar otros modos de dibujo 2D
            self._deactivate_button("button_riel_dim")
            self._deactivate_button("button_block_t")

            # Activar color verde (modo activo)
            self._activate_button("button_canaleta")

            self.activate_canaleta_draw()

        except Exception:
            pass

    def _simulate_ctrl_b(self):
        """Inserta un Block Terminal (Ctrl+B) con feedback visual momentáneo."""
        try:
            # Desactivar otros modos de dibujo 2D activos
            self._deactivate_button("button_riel_dim")
            self._deactivate_button("button_canaleta")
            if hasattr(self, 'event_handler'):
                self.event_handler.shape_drawing.cancel()

            # Flash verde mientras se inserta
            self._activate_button("button_block_t")
            self.root.update()

            # Crear evento simulado: keysym='b' y state=4 (Ctrl presionado)
            simulated_event = type('Event', (), {
                'keysym': 'b',
                'state': 4  # 4 = Ctrl presionado en Tkinter
            })()

            if hasattr(self, 'event_handler'):
                self.event_handler.on_key_press(simulated_event)

            # Desactivar botón tras la inserción (acción instantánea)
            self.root.after(300, lambda: self._deactivate_button("button_block_t"))

        except Exception:
            pass

    def notify_shape_draw_finished(self, shape_type):
        """
        Llamar desde ShapeDrawingState.finish_drawing() o cancel() para
        desactivar el botón correspondiente una vez que la acción concluye.
        """
        mapping = {
            'din_rail': 'button_riel_dim',
            'canaleta': 'button_canaleta',
        }
        btn_name = mapping.get(shape_type)
        if btn_name:
            self._deactivate_button(btn_name)

    def _toggle_auto_deteccion(self):
        """Toggle Detección Automática (auto_conexion_enabled)."""
        try:
            current_value = self.auto_conexion_enabled.get()
            new_value = not current_value
            self.auto_conexion_enabled.set(new_value)

            # También actualizar la configuración
            self.config["auto_conexion_enabled"] = new_value

            # Si se activa CAuto, desactivar CProx
            if new_value and self.proximity_preview_enabled.get():
                self.proximity_preview_enabled.set(False)
                self.config["proximity_preview_enabled"] = False
                if "button_cprox" in self.button_widgets:
                    self.button_widgets["button_cprox"].config(bg="#c3c3c3", fg="#333333")
                    self.button_active_states["button_cprox"] = False
                    self.limpiar_preview_autoconexion()

            if "button_cauto" in self.button_widgets:
                if new_value:
                    # Activo: rojo
                    self.button_widgets["button_cauto"].config(bg="#ff5555", fg="white")
                    self.button_active_states["button_cauto"] = True
                else:
                    # Inactivo: gris
                    self.button_widgets["button_cauto"].config(bg="#c3c3c3", fg="#333333")
                    self.button_active_states["button_cauto"] = False

            # Mensaje de estado opcional
            status_text = "Detección Automática: ACTIVADA" if new_value else "Detección Automática: DESACTIVADA"
            if hasattr(self, 'set_status'):
                self.set_status(status_text, "#4CAF50" if new_value else "#ff5722")

        except Exception as e:
            # Silenciar errores para no interferir
            pass

    def _toggle_proximity_preview(self):
        """Toggle Preview de Proximidad (líneas verdes)."""
        try:
            current_value = self.proximity_preview_enabled.get()
            new_value = not current_value
            self.proximity_preview_enabled.set(new_value)

            # También actualizar la configuración
            self.config["proximity_preview_enabled"] = new_value

            # Si se activa CProx, desactivar CAuto
            if new_value and self.auto_conexion_enabled.get():
                self.auto_conexion_enabled.set(False)
                self.config["auto_conexion_enabled"] = False
                if "button_cauto" in self.button_widgets:
                    self.button_widgets["button_cauto"].config(bg="#c3c3c3", fg="#333333")
                    self.button_active_states["button_cauto"] = False

            if "button_cprox" in self.button_widgets:
                if new_value:
                    # Activo: verde
                    self.button_widgets["button_cprox"].config(bg="#55ff55", fg="white")
                    self.button_active_states["button_cprox"] = True
                else:
                    # Inactivo: gris
                    self.button_widgets["button_cprox"].config(bg="#c3c3c3", fg="#333333")
                    self.button_active_states["button_cprox"] = False
                    # Limpiar cualquier preview activo
                    self.limpiar_preview_autoconexion()

            # Mensaje de estado opcional
            status_text = "Preview Proximidad: ACTIVADO" if new_value else "Preview Proximidad: DESACTIVADO"
            if hasattr(self, 'set_status'):
                self.set_status(status_text, "#55ff55" if new_value else "#ff5722")

        except Exception as e:
            # Silenciar errores para no interferir
            pass

    def _toggle_shielding_mode(self):
        """Toggle el modo de dibujo de apantallamiento."""
        try:
            current_value = self.shielding_mode_enabled.get()
            new_value = not current_value
            self.shielding_mode_enabled.set(new_value)

            # Desactivar otros modos si se activa apantallamiento
            if new_value:
                if self.auto_conexion_enabled.get(): self._toggle_auto_deteccion()
                if self.proximity_preview_enabled.get(): self._toggle_proximity_preview()
                if self.is_insert_point_mode: self.is_insert_point_mode = False
                self._deactivate_all_buttons()
                self.canvas.config(cursor="crosshair")

                # Activar visualmente el botón
                if "button_shielding" in self.button_widgets:
                    self.button_widgets["button_shielding"].config(bg="#4CAF50", fg="white")

                if hasattr(self, 'set_status'):
                    self.set_status("Modo Apantallamiento: Click y arrastre horizontalmente sobre los cables", "#2196F3")
            else:
                self.canvas.config(cursor="")
                # Desactivar visualmente el botón
                if "button_shielding" in self.button_widgets:
                    self.button_widgets["button_shielding"].config(bg="#c3c3c3", fg="#333333")

                if hasattr(self, 'set_status'):
                    self.set_status("Modo Apantallamiento: DESACTIVADO", "#ff5722")

        except Exception:
            pass

    def _simulate_ctrl_click(self):
        """Activa el modo de línea manual (Ctrl+Click) para trazado con puntos de ángulo."""
        try:
            # Verificar si el botón 8 ya está activo
            if self.button_active_states.get("button8", False):

                return

            # Activar visualmente el botón 8 (verde)
            self._activate_button("button8")

            if hasattr(self, 'set_status'):
                self.set_status("Línea Manual: Presiona Ctrl+Click sobre un punto de conexión", "#ff9800")

        except Exception as e:
            # En caso de error, desactivar el botón
            self._deactivate_button("button8")

    def _check_and_deactivate_button8(self):
        """
        Verifica si el manual routing ya no está activo y desactiva el botón 8 si es necesario.
        Esta función debe llamarse para asegurar que el botón 8 se desactive correctamente.
        """
        try:
            from core.unified_line_system import get_manhattan_router
            manual_router = get_manhattan_router(self)

            # Si manual routing no está activo pero botón 8 sí, desactivarlo
            if not manual_router.manual_active and self.button_active_states.get("button8", False):
                self._deactivate_button("button8")

        except:
            pass

    def _activate_button(self, button_name):
        """Activa un botón vertical cambiándolo a color verde."""
        if button_name in self.button_widgets and button_name in self.button_active_states:
            if not self.button_active_states[button_name]:  # Solo cambiar si no está ya activo
                self.button_widgets[button_name].config(bg="#4CAF50", fg="white")
                self.button_active_states[button_name] = True

    def _deactivate_button(self, button_name):
        """Desactiva un botón vertical cambiándolo a color #c3c3c3."""
        if button_name in self.button_widgets and button_name in self.button_active_states:
            if self.button_active_states[button_name]:  # Solo cambiar si está activo
                self.button_widgets[button_name].config(bg="#c3c3c3", fg="#333333")
                self.button_active_states[button_name] = False

    def _deactivate_all_buttons(self):
        """Desactiva todos los botones verticales."""
        for button_name in self.button_active_states:
            self._deactivate_button(button_name)

    def _draw_crosshair(self, event):
        """Usa sistema de coordenadas centralizado"""
        try:
            # Solo procesar si el crosshair está habilitado
            if not self._crosshair_enabled:
                if hasattr(self, 'crosshair_created') and self.crosshair_created:
                    try:
                        self.canvas.move(self.crosshair_h, 0, -200)
                        self.canvas.move(self.crosshair_v, -200, 0)
                    except Exception:
                        pass
                return

            # Si no se ha inicializado, crear las líneas
            if not hasattr(self, 'crosshair_created') or not self.crosshair_created:
                self._init_crosshair()
                if not hasattr(self, 'crosshair_created') or not self.crosshair_created:
                    return

            # OPTIMIZACIÓN CRÍTICA: Solo actualizar si las coordenadas han cambiado significativamente
            current_x = getattr(self, '_last_crosshair_x', None)
            current_y = getattr(self, '_last_crosshair_y', None)
            new_x = event.x
            new_y = event.y

            # Solo procesar si hay cambio significativo (>3 píxeles) o si es la primera vez
            if current_x is not None and current_y is not None:
                if abs(new_x - current_x) <= 3 and abs(new_y - current_y) <= 3:
                    return  # Saltar actualización innecesaria

            # Guardar nuevas coordenadas
            self._last_crosshair_x = new_x
            self._last_crosshair_y = new_y

            width = self.canvas.winfo_width()
            height = self.canvas.winfo_height()

            # CORRECCIÓN REAL: Convertir coordenadas de ventana a coordenadas del canvas
            # canvasx/canvasy compensan automáticamente el pan/scroll
            canvas_x = self.canvas.canvasx(new_x)
            canvas_y = self.canvas.canvasy(new_y)

            # Línea Horizontal: debe cubrir todo el ancho visible del canvas
            # Convertir límites de la ventana a coordenadas del canvas
            canvas_x_left = self.canvas.canvasx(0)
            canvas_x_right = self.canvas.canvasx(width)

            self.canvas.coords(self.crosshair_h, canvas_x_left, canvas_y, canvas_x_right, canvas_y)

            # Línea Vertical: debe cubrir todo el alto visible del canvas
            canvas_y_top = self.canvas.canvasy(0)
            canvas_y_bottom = self.canvas.canvasy(height)

            self.canvas.coords(self.crosshair_v, canvas_x, canvas_y_top, canvas_x, canvas_y_bottom)

            # Asegurar que estén visibles (lift)
            self.canvas.tag_raise('crosshair')

        except Exception as e:
            pass

    def agregar_empalme_en_linea(self, conexion, segmento_idx, posicion_ratio):
        """Agrega un punto de empalme en una línea existente (recalculado desde archivo)."""
        try:
            if not hasattr(conexion, 'segments') or not (0 <= segmento_idx < len(conexion.segments)):
                return None
            start_x, start_y = conexion.segments[segmento_idx][0]
            end_x, end_y = conexion.segments[segmento_idx][1]
            empalme = types.SimpleNamespace(
                x=start_x + (end_x - start_x) * posicion_ratio,
                y=start_y + (end_y - start_y) * posicion_ratio,
                segmento_idx=segmento_idx,
                posicion_ratio=posicion_ratio,
                connected=True,
            )
            if not hasattr(conexion, 'puntos_empalme'):
                conexion.puntos_empalme = []
            conexion.puntos_empalme.append(empalme)
            return empalme
        except Exception:
            return None

    def detectar_auto_conexion_componente(self, componente, conexion):
        """
        Detecta si una línea de conexión pasa por puntos de conexión de un componente.
        Retorna TODOS los índices de puntos intersectados (ordenados start->end), o None si no hay.
        """
        return self.component_manager.detectar_auto_conexion_componente(componente, conexion)

    def ejecutar_auto_conexion(self, componente, conexion_original, puntos_interseccion):
        """
        Ejecuta la auto-conexión: corta la línea original y crea nuevas conexiones a los puntos del componente.
        """

        return self.component_manager.ejecutar_auto_conexion(componente, conexion_original, puntos_interseccion)

    def obtener_line_ids_de_punto_conexion(self, componente, punto_idx):
        """
        OBTIENE DIRECTAMENTE LOS IDs DE LAS LÍNEAS CONECTADAS A UN PUNTO ESPECÍFICO
        (No es búsqueda - la información ya está almacenada en self.connections)

        Args:
            componente: El componente que contiene el punto de conexión
            punto_idx: Índice del punto de conexión

        Returns:
            list: Lista de line_ids que están conectados a este punto
        """
        line_ids_conectados = []

        # Iterar conexiones existentes - la info ya está ahí, solo acceder directamente
        for conexion in self.connections:
            if ((conexion.start_component == componente and conexion.start_point_idx == punto_idx) or
                (conexion.end_component == componente and conexion.end_point_idx == punto_idx)):
                line_ids_conectados.extend(conexion.line_ids)

        return line_ids_conectados

    def mostrar_preview_autoconexion(self, componente, conexion, puntos_interseccion):
        """
        Muestra un preview visual de cómo quedaría la auto-conexión sin ejecutarla.
        Soporta múltiples llamadas acumulando todos los IDs para limpieza posterior.
        """
        try:
            # Verificar si el preview de proximidad está habilitado
            if not self.proximity_preview_enabled.get():
                return

            if not hasattr(self, 'preview_autoconexion_activo') or not self.preview_autoconexion_activo:
                self.preview_autoconexion_activo = True
                self.preview_conexiones_originales = []  # Lista de conexiones afectadas
                self.preview_line_ids = []               # Lista de IDs de líneas de preview

            # Registrar esta conexión como afectada
            self.preview_conexiones_originales.append(conexion)

            for line_id in conexion.line_ids:
                self.canvas.itemconfig(line_id, fill="#87CEEB", width=0.5, dash=(5, 3))

            # 1 punto: start->p0; 2 puntos: start->p0 y p1->end (inserción en serie);
            # 3+ puntos: cadena completa start->p0->p1->...->pN-1->end.
            start_comp = conexion.start_component
            start_idx = conexion.start_point_idx
            end_comp = conexion.end_component
            end_idx = conexion.end_point_idx

            puntos_ordenados = [j for j, _seg in puntos_interseccion]

            secuencia = (
                [('start', start_comp, start_idx)] +
                [('comp', componente, j) for j in puntos_ordenados] +
                [('end', end_comp, end_idx)]
            )

            if len(puntos_ordenados) == 2:
                pares_preview = [(0, 1), (2, 3)]
            elif len(puntos_ordenados) >= 3:
                pares_preview = [(i, i + 1) for i in range(len(secuencia) - 1)]
            else:
                pares_preview = [(0, 1)]  # 1 punto

            for i_a, i_b in pares_preview:
                _, comp_a, idx_a = secuencia[i_a]
                _, comp_b, idx_b = secuencia[i_b]
                pts_a = comp_a.get_connection_points_global()
                pts_b = comp_b.get_connection_points_global()
                if idx_a < len(pts_a) and idx_b < len(pts_b):
                    xa, ya = pts_a[idx_a][:2]
                    xb, yb = pts_b[idx_b][:2]
                    preview_line = draw_world_line(
                        self.canvas, xa, ya, xb, yb,
                        fill="#90EE90", width=1.5, dash=(3, 2))
                    self.preview_line_ids.append(preview_line)

        except Exception as e:
            pass
            self.limpiar_preview_autoconexion()
            pass

    def limpiar_preview_autoconexion(self):
        """
        Limpia TODOS los previews visuales de auto-conexión acumulados
        """
        try:
            if hasattr(self, 'preview_autoconexion_activo') and self.preview_autoconexion_activo:
                # Restaurar color original de TODAS las conexiones afectadas
                if hasattr(self, 'preview_conexiones_originales'):
                    for conexion in self.preview_conexiones_originales:
                        try:
                            for line_id in conexion.line_ids:
                                self.canvas.itemconfig(
                                    line_id,
                                    fill=adapt_color_for_display("black", self.canvas.cget("bg")),
                                    width=0.5, dash=()
                                )
                        except Exception:
                            pass
                    self.preview_conexiones_originales = []

                if hasattr(self, 'preview_line_ids'):
                    for line_id in self.preview_line_ids:
                        try:
                            self.canvas.delete(line_id)
                        except Exception:
                            pass
                    self.preview_line_ids = []

                # Limpiar estado
                self.preview_autoconexion_activo = False
                for attr in ('preview_conexion_original', 'preview_componente', 'preview_puntos'):
                    if hasattr(self, attr):
                        delattr(self, attr)

        except Exception as e:
            # Asegurar que las variables se limpien aunque haya error
            self.preview_autoconexion_activo = False
            self.preview_conexiones_originales = []
            self.preview_line_ids = []

    def mostrar_preview_conexiones_ortogonales(self, componente, mouse_direction=(0, 0)):
        """
        Mapeo secuencial escalonado:
        1. Recolecta TODAS las intersecciones posibles
        2. Las ordena espacialmente
        3. Asigna secuencialmente: punto1->intersección1, punto2->intersección2 (saltando 3px), etc.

        Args:
            componente: Componente para mostrar preview
            mouse_direction: (dx, dy) dirección del movimiento del mouse
        """
        try:
            self.limpiar_preview_conexiones_ortogonales()
            if hasattr(self, 'preview_conexiones_validas_ids'):
                for line_id in self.preview_conexiones_validas_ids:
                    if line_id:
                        try:
                            self.canvas.delete(line_id)
                        except:
                            pass
                self.preview_conexiones_validas_ids = []

            puntos_componente = componente.get_connection_points_global()

            # Listas de salida
            self.preview_conexiones_validas_ids = []
            self.conexiones_pendientes = []

            # 1. RECOLECTAR TODAS LAS INTERSECCIONES POSIBLES
            todas_las_intersecciones = []

            for punto_idx, (punto_x, punto_y, punto_data) in enumerate(puntos_componente):
                direccion = self.calcular_direccion_ortogonal(punto_data.orientation)
                dx, dy = direccion

                # Proyectar línea ortogonal
                max_distancia = 1000
                end_x = punto_x + dx * max_distancia
                end_y = punto_y + dy * max_distancia

                # Buscar intersecciones con líneas existentes
                for conexion in self.connections:
                    for seg_idx, ((seg_x1, seg_y1), (seg_x2, seg_y2)) in enumerate(conexion.segments):
                        interseccion = self.calcular_interseccion_lineas(
                            (punto_x, punto_y), (end_x, end_y),
                            (seg_x1, seg_y1), (seg_x2, seg_y2)
                        )

                        if interseccion:
                            inter_x, inter_y = interseccion
                            distancia = ((inter_x - punto_x) ** 2 + (inter_y - punto_y) ** 2) ** 0.5

                            if distancia > 10:  # Mínimo 10px del origen
                                todas_las_intersecciones.append({
                                    'punto_idx': punto_idx,
                                    'punto_origen': (punto_x, punto_y),
                                    'punto_data': punto_data,
                                    'interseccion': (inter_x, inter_y),
                                    'distancia': distancia,
                                    'desvio': 0.0,  # La intersección está sobre el rayo
                                    'conexion': conexion,
                                    'seg_idx': seg_idx
                                })

                # Buscar intersecciones con puntos de componentes
                for comp_destino in self.components:
                    if comp_destino == componente:
                        continue

                    puntos_destino = comp_destino.get_connection_points_global()
                    margen_destino = self._margen_alineacion_autoconexion(puntos_destino)
                    for idx_destino, (dest_x, dest_y, dest_data) in enumerate(puntos_destino):
                        # Verificar si está en dirección ortogonal
                        # La distancia se mide en línea recta (igual que las
                        # intersecciones con líneas de arriba) y además se guarda el
                        # desvío lateral respecto del rayo. Medir solo la proyección
                        # sobre el rayo hacía que un terminal 20 px SALVO lateralmente
                        # pareciera más cercano que el terminal que el rayo atraviesa
                        # de verdad, y el medio pixel de asimetría del SVG decidía el
                        # cruce de fase.
                        if dx != 0:  # Dirección horizontal
                            if (dx > 0 and dest_x > punto_x) or (dx < 0 and dest_x < punto_x):
                                desvio = abs(dest_y - punto_y)
                                if desvio <= 30:  # Tolerancia vertical
                                    distancia = ((dest_x - punto_x) ** 2 + (dest_y - punto_y) ** 2) ** 0.5
                                    todas_las_intersecciones.append({
                                        'punto_idx': punto_idx,
                                        'punto_origen': (punto_x, punto_y),
                                        'punto_data': punto_data,
                                        'interseccion': (dest_x, dest_y),
                                        'distancia': distancia,
                                        'desvio': desvio,
                                        'margen': margen_destino,
                                        'componente_destino': comp_destino,
                                        'punto_idx_destino': idx_destino
                                    })
                        elif dy != 0:  # Dirección vertical
                            if (dy > 0 and dest_y > punto_y) or (dy < 0 and dest_y < punto_y):
                                desvio = abs(dest_x - punto_x)
                                if desvio <= 30:  # Tolerancia horizontal
                                    distancia = ((dest_x - punto_x) ** 2 + (dest_y - punto_y) ** 2) ** 0.5
                                    todas_las_intersecciones.append({
                                        'punto_idx': punto_idx,
                                        'punto_origen': (punto_x, punto_y),
                                        'punto_data': punto_data,
                                        'interseccion': (dest_x, dest_y),
                                        'distancia': distancia,
                                        'desvio': desvio,
                                        'margen': margen_destino,
                                        'componente_destino': comp_destino,
                                        'punto_idx_destino': idx_destino
                                    })

            # 2. ORDENAR INTERSECCIONES POR DISTANCIA (MÁS CERCANA PRIMERO)
            # Ordenar de abajo hacia arriba = de la más cercana al componente a la más lejana
            # Si "Invertir" está activado, ordenar de la más lejana a la más cercana
            reverse_order = self.invertir_deteccion.get() if hasattr(self, 'invertir_deteccion') else False
            todas_las_intersecciones.sort(key=self._clave_prioridad_autoconexion, reverse=reverse_order)

            # 3. MAPEO CORRECTO POR ORDEN DE PUNTO
            # Cada punto debe conectarse a su línea correspondiente específica
            lineas_usadas = set()  # Para tracking de líneas ya ocupadas

            for punto_idx in range(len(puntos_componente)):
                # Buscar intersecciones for este punto específico
                intersecciones_este_punto = [item for item in todas_las_intersecciones if item['punto_idx'] == punto_idx]

                # Ordenar estas intersecciones por distancia para este punto
                intersecciones_este_punto.sort(key=self._clave_prioridad_autoconexion, reverse=reverse_order)

                # Un rayo sólo puede pertenecer a UN carril de terminales: probar
                # primero los destinos mejor alineados con el rayo y, si todos están
                # ocupados, recurrir al resto.
                intersecciones_este_punto = self._priorizar_alineacion_del_rayo(
                    intersecciones_este_punto)

                # Tomar la primera intersección disponible para este punto
                interseccion_asignada = None
                for item in intersecciones_este_punto:
                    if 'componente_destino' in item:
                        # Intersección con punto de componente
                        linea_id = f"COMP_{id(item['componente_destino'])}_{item['punto_idx_destino']}"
                    else:
                        # Intersección con línea existente
                        linea_id = f"CONN_{id(item['conexion'])}_{item['seg_idx']}"

                    # Verificar si esta línea ya fue usada
                    if linea_id not in lineas_usadas:
                        interseccion_asignada = item
                        lineas_usadas.add(linea_id)
                        break

                if interseccion_asignada:
                    punto_origen = interseccion_asignada['punto_origen']
                    punto_destino = interseccion_asignada['interseccion']
                    punto_data = interseccion_asignada['punto_data']

                    segmentos = self._calcular_segmentos_escalonados_preview(
                        punto_origen[0], punto_origen[1],
                        punto_destino[0], punto_destino[1],
                        punto_data.orientation
                    )

                    for (x1, y1), (x2, y2) in segmentos:
                        # Convertir de mundo a coordenadas de CANVAS (no de pantalla).
                        # canvas.create_line() espera coordenadas de canvas, que ya
                        # tienen en cuenta el desplazamiento de la vista. Usar aquí
                        # canvas.world_to_screen() restaba el offset de pan y la
                        # línea quedaba desplazada justo lo que el pan, aunque al
                        # fijar el componente la conexión real saliese correcta.
                        canvas_x1, canvas_y1 = world_to_canvas_coords(x1, y1, self.canvas)
                        canvas_x2, canvas_y2 = world_to_canvas_coords(x2, y2, self.canvas)

                        line_id = self.canvas.create_line(
                            canvas_x1, canvas_y1,
                            canvas_x2, canvas_y2,
                            fill="#FF0000", width=1, dash=(4, 4),
                            tags="preview_conexion_valida"
                        )
                        self.preview_conexiones_validas_ids.append(line_id)

                    # Almacenar para crear conexión real después
                    if 'componente_destino' in interseccion_asignada:
                        # Conexión a punto de componente
                        self.conexiones_pendientes.append((
                            punto_idx,
                            interseccion_asignada['componente_destino'],
                            interseccion_asignada['punto_idx_destino']
                        ))
                    else:
                        # Conexión a línea (intersección)
                        self.conexiones_pendientes.append((
                            punto_idx,
                            f"LINEA_INTERSECCION_{interseccion_asignada['seg_idx']}",
                            interseccion_asignada['conexion']
                        ))

        except Exception as e:
            pass
            self.limpiar_preview_conexiones_ortogonales()

    # Margen (px) de desalineación admisible entre el rayo y el terminal destino.
    # Es un tope absoluto: el margen real se calcula además a partir del paso entre
    # bornes del componente destino (ver _margen_alineacion_autoconexion), porque en
    # la biblioteca el paso va desde ~20 px en los contactores de 3 polos hasta menos
    # de 4 px en las bornas de bloque.
    MARGEN_ALINEACION_AUTOCONEXION = 6.0

    # Fracción del paso entre bornes que se considera "el mismo carril". Por debajo
    # de 0.5 el carril vecino nunca entra en la banda de alineación.
    FRACCION_PASO_ENTRE_BORNES = 0.4

    @staticmethod
    def _paso_entre_bornes(puntos):
        """
        Distancia mínima entre dos bornes distintos de un mismo componente.

        Devuelve None si el componente tiene menos de dos bornes.
        """
        if not puntos or len(puntos) < 2:
            return None
        paso = None
        for i, a in enumerate(puntos):
            for b in puntos[i + 1:]:
                d = math.hypot(a[0] - b[0], a[1] - b[1])
                if d > 0.5 and (paso is None or d < paso):
                    paso = d
        return paso

    def _margen_alineacion_autoconexion(self, puntos_destino):
        """
        Margen de alineación admisible para un componente destino.

        Un terminal cuenta como "del mismo carril que el rayo" si su desvío lateral
        no supera una fracción del paso entre bornes del propio componente. Así el
        margen se adapta: generoso en contactores de 3 polos (paso ~20 px) y muy
        estricto en bornas de bloque (paso ~3 px), donde un margen fijo permitiría
        que el borne del carril vecino se alineara y volviera a cruzar el conductor.
        """
        paso = self._paso_entre_bornes(puntos_destino)
        if paso is None:
            return self.MARGEN_ALINEACION_AUTOCONEXION
        return min(self.MARGEN_ALINEACION_AUTOCONEXION,
                   paso * self.FRACCION_PASO_ENTRE_BORNES)

    def _clave_prioridad_autoconexion(self, item):
        """
        Clave de orden de un destino candidato de la auto-conexión ortogonal.

        Prioriza la distancia real al terminal y, a igualdad, el menor desvío
        lateral respecto del rayo (el destino que el rayo atraviesa de verdad).
        """
        return (item['distancia'], item.get('desvio', 0.0))

    def _priorizar_alineacion_del_rayo(self, intersecciones):
        """
        Reordena los destinos candidatos de un terminal poniendo delante los que el
        rayo atraviesa de verdad.

        La tolerancia lateral de 30 px hace que el rayo de un terminal vea también
        los terminales del carril vecino. Ordenando solo por distancia, un terminal
        vecino podía salir elegido y desplazar al correcto: el conductor terminaba
        cruzándose y el resto de terminales se emparejaban con los destinos
        equivocados por el conjunto de líneas ya ocupadas. Aquí se agrupan primero
        los candidatos que caen dentro de su margen de alineación y, solo si todos
        están ocupados, se recurre al resto.

        Se respeta el orden de entrada (distancia ascendente o descendente según
        "Invertir detección"), por lo que dentro de cada grupo manda la distancia.
        """
        if len(intersecciones) < 2:
            return intersecciones

        mejor_desvio = min(item.get('desvio', 0.0) for item in intersecciones)

        def alineado(item):
            margen = item.get('margen', self.MARGEN_ALINEACION_AUTOCONEXION)
            return item.get('desvio', 0.0) <= mejor_desvio + margen

        alineados = [item for item in intersecciones if alineado(item)]
        if len(alineados) == len(intersecciones):
            return intersecciones
        return alineados + [item for item in intersecciones if not alineado(item)]

    def calcular_direccion_ortogonal(self, orientation):
        """
        Calcula la dirección ortogonal (dx, dy) según la orientación del punto.

        Args:
            orientation (str): 'N', 'S', 'E', 'O'

        Returns:
            tuple: (dx, dy) vector de dirección unitario
        """
        direcciones = {
            'N': (0, -1),    # Norte: hacia arriba
            'S': (0, 1),     # Sur: hacia abajo
            'E': (1, 0),     # Este: hacia derecha
            'O': (-1, 0)     # Oeste: hacia izquierda
        }
        return direcciones.get(orientation, (0, 0))

    def _calcular_segmentos_escalonados_preview(self, start_x, start_y, end_x, end_y, orientation):
        """
        Calcula segmentos escalonados para preview (H-V-H o V-H-V)

        Args:
            start_x, start_y: Punto inicial
            end_x, end_y: Punto final
            orientation: Orientación del punto inicial ('N', 'S', 'E', 'O')

        Returns:
            list: Lista de segmentos [(x1,y1), (x2,y2)]
        """
        segmentos = []

        # Calcular distancias
        dx = abs(end_x - start_x)
        dy = abs(end_y - start_y)

        # Decidir patrón según orientación y distancias
        if orientation in ['E', 'O'] or dx > dy:
            # PATRÓN H-V-H: horizontal -> vertical -> horizontal
            mid_x = (start_x + end_x) // 2

            segmentos.append(((start_x, start_y), (mid_x, start_y)))    # Horizontal inicial
            segmentos.append(((mid_x, start_y), (mid_x, end_y)))        # Vertical central
            segmentos.append(((mid_x, end_y), (end_x, end_y)))          # Horizontal final
        else:
            # PATRÓN V-H-V: vertical -> horizontal -> vertical
            mid_y = (start_y + end_y) // 2

            segmentos.append(((start_x, start_y), (start_x, mid_y)))    # Vertical inicial
            segmentos.append(((start_x, mid_y), (end_x, mid_y)))        # Horizontal central
            segmentos.append(((end_x, mid_y), (end_x, end_y)))          # Vertical final

        return segmentos

    def calcular_interseccion_lineas(self, line1_start, line1_end, line2_start, line2_end):
        """
        Calcula la intersección exacta entre dos segmentos de línea.

        Args:
            line1_start: (x1, y1) punto inicial de la primera línea
            line1_end: (x2, y2) punto final de la primera línea
            line2_start: (x3, y3) punto inicial de la segunda línea
            line2_end: (x4, y4) punto final de la segunda línea

        Returns:
            tuple: (x, y) coordenadas de intersección o None si no intersectan
        """
        x1, y1 = line1_start
        x2, y2 = line1_end
        x3, y3 = line2_start
        x4, y4 = line2_end

        # Calcular denominador
        denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)

        # Líneas paralelas
        if abs(denominator) < 1e-10:
            return None

        # Calcular parámetros de intersección
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denominator
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denominator

        # Verificar que la intersección esté dentro de ambos segmentos
        if 0 <= t <= 1 and 0 <= u <= 1:
            # Calcular punto de intersección
            intersect_x = x1 + t * (x2 - x1)
            intersect_y = y1 + t * (y2 - y1)
            return (intersect_x, intersect_y)

        return None

    def limpiar_preview_conexiones_ortogonales(self):
        """
        Limpia las líneas de preview.
        Las líneas de conexión válidas se mantienen hasta que se fijan.
        """
        try:
            try:
                self.canvas.delete("preview_ortogonal")
            except:
                pass

        except Exception as e:
            pass

    def crear_conexiones_reales_desde_preview(self, componente_nuevo):
        """
        Convierte las líneas rojas de preview en CONEXIONES ELÉCTRICAS REALES.
        Se llama al hacer click para colocar el componente.
        """
        try:
            # Primero borrar las líneas de preview rojas
            if hasattr(self, 'preview_conexiones_validas_ids'):
                for line_id in self.preview_conexiones_validas_ids:
                    if line_id:
                        try:
                            self.canvas.delete(line_id)
                        except:
                            pass
                self.preview_conexiones_validas_ids = []

            if hasattr(self, 'conexiones_pendientes'):
                for punto_origen_idx, componente_destino, punto_destino_idx in self.conexiones_pendientes:
                    try:
                        if isinstance(componente_destino, str) and componente_destino.startswith("LINEA_INTERSECCION_"):
                            # Es una intersección con línea existente
                            conexion_existente = punto_destino_idx  # En este caso contiene la conexión

                            punto_origen = componente_nuevo.get_connection_points_global()[punto_origen_idx]
                            origen_x, origen_y = punto_origen[0], punto_origen[1]

                            # Calcular dirección para encontrar la intersección otra vez
                            direccion = self.calcular_direccion_ortogonal(punto_origen[2].orientation)
                            dx, dy = direccion
                            end_x = origen_x + dx * 1000
                            end_y = origen_y + dy * 1000

                            # Buscar la intersección exacta con esta conexión
                            for seg_idx, ((seg_x1, seg_y1), (seg_x2, seg_y2)) in enumerate(conexion_existente.segments):
                                interseccion = self.calcular_interseccion_lineas(
                                    (origen_x, origen_y), (end_x, end_y),
                                    (seg_x1, seg_y1), (seg_x2, seg_y2)
                                )

                                if interseccion:
                                    inter_x, inter_y = interseccion

                                    # USAR LÓGICA EXISTENTE: Crear empalme en la intersección
                                    junction_component = self.insert_junction_point(conexion_existente, (inter_x, inter_y), seg_idx)
                                    if junction_component:
                                        nueva_conexion = self.create_connection(
                                            componente_nuevo, punto_origen_idx,
                                            junction_component, 0
                                        )

                                        # PRESERVAR PROPIEDADES DE LA LÍNEA ORIGINAL (CORREGIR BUG)
                                        if hasattr(conexion_existente, 'line_color'):
                                            nueva_conexion.line_color = conexion_existente.line_color
                                        if hasattr(conexion_existente, 'line_width'):
                                            nueva_conexion.line_width = conexion_existente.line_width
                                        if hasattr(conexion_existente, 'line_dash'):
                                            nueva_conexion.line_dash = conexion_existente.line_dash
                                    break
                        else:
                            # Es conexión normal con punto de componente
                            nueva_conexion = self.create_connection(
                                componente_nuevo,    # Componente recién creado
                                punto_origen_idx,    # Punto del componente nuevo
                                componente_destino,  # Componente existente en el canvas
                                punto_destino_idx    # Punto del componente existente
                            )

                            # VERIFICAR SI EL PUNTO DESTINO TIENE CONEXIONES EXISTENTES PARA COPIAR PROPIEDADES
                            line_ids_existentes = self.obtener_line_ids_de_punto_conexion(componente_destino, punto_destino_idx)
                            if line_ids_existentes:
                                # Buscar la primera conexión existente para copiar propiedades
                                for conexion_antigua in self.connections:
                                    if any(line_id in conexion_antigua.line_ids for line_id in line_ids_existentes):
                                        if hasattr(conexion_antigua, 'line_color'):
                                            nueva_conexion.line_color = conexion_antigua.line_color
                                        if hasattr(conexion_antigua, 'line_width'):
                                            nueva_conexion.line_width = conexion_antigua.line_width
                                        if hasattr(conexion_antigua, 'line_dash'):
                                            nueva_conexion.line_dash = conexion_antigua.line_dash
                                        break

                    except Exception as e:
                        pass

                # Limpiar lista de conexiones pendientes
                self.conexiones_pendientes = []

        except Exception as e:

            pass
            pass

    def limpiar_todas_las_lineas_preview(self):
        """
        Limpia TODAS las líneas de preview (naranjas Y rojas) cuando se cancela la operación.
        """
        try:
            # Limpiar líneas naranjas (temporales)
            self.limpiar_preview_conexiones_ortogonales()

            # Limpiar líneas rojas (conexiones válidas)
            if hasattr(self, 'preview_conexiones_validas_ids'):
                for line_id in self.preview_conexiones_validas_ids:
                    if line_id:
                        try:
                            self.canvas.delete(line_id)
                        except:
                            pass
                self.preview_conexiones_validas_ids = []

            # Limpiar datos de conexiones pendientes
            if hasattr(self, 'conexiones_pendientes'):
                self.conexiones_pendientes = []

            try:
                self.canvas.delete("preview_conexion_valida")
            except:
                pass

        except Exception as e:

            pass
            pass

    def toggle_lines_panel(self, event=None):
        """Alterna entre ocultar y mostrar el panel de líneas."""
        if self.panel_visible:
            # Panel visible - ocultarlo
            self.lines_panel_frame.pack_forget()
            self.panel_visible = False

        else:
            # Panel oculto - mostrarlo ANTES del custom_buttons_bar para mantener orden original
            # Restore in correct order: lines_panel first, then custom_buttons_bar
            self.lines_panel_frame.pack(side="left", fill="y", before=self.custom_buttons_bar)
            self.lines_panel_frame.pack_propagate(False)
            self.panel_visible = True

            # Forzar actualización para asegurar que se muestre
            self.root.update()

        self.update_toggle_visual()

    def update_toggle_visual(self):
        """Actualiza el estado visual de la barra de toggle."""
        self.toggle_canvas.delete("all")
        if self.panel_visible:
            # Panel visible
            self.toggle_canvas.create_rectangle(0, 0, 5, 20, fill="#e0e0e0", outline="")
            self.toggle_canvas.create_text(2.5, 10, text="‹", fill="#000000", font=(AppConstants.UI_FONT_FAMILY, 8))
        else:
            # Panel oculto
            self.toggle_canvas.create_rectangle(0, 0, 5, 20, fill="#a0a0a0", outline="")
            self.toggle_canvas.create_text(2.5, 10, text="›", fill="#ffffff", font=(AppConstants.UI_FONT_FAMILY, 8))

    def create_menus(self):
        self.menu_bar = tk.Menu(self.root)
        self.root.config(menu=self.menu_bar)

        # Menú Archivo con formato .ecad
        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Archivo", menu=file_menu)
        file_menu.add_command(label="Nuevo        Ctrl+N", command=self.new_canvas)
        file_menu.add_command(label="Limpiar", command=self.clear_active_sheet)
        file_menu.add_command(label="Abrir...      Ctrl+O", command=self.load_canvas)
        file_menu.add_separator()
        file_menu.add_command(label="Guardar      Ctrl+S", command=self.save_canvas)
        file_menu.add_command(label="Guardar como...", command=self.save_canvas_as)
        file_menu.add_separator()
        # Exportar PDF
        file_menu.add_command(label="Exportar PDF  Ctrl+E", command=self.export_pdf)
        file_menu.add_command(label="Exportar DXF  Ctrl+T", command=self.export_dxf)
        file_menu.add_command(label="Exportar BOM a CSV", command=self.export_bom_csv)
        file_menu.add_command(label="Exportar Cableado a CSV", command=self.export_wiring_table_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=self.on_closing_app)

        # Resto de menús igual que antes
        view_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Ver", menu=view_menu)
        view_menu.add_command(label="Color de fondo", command=self.change_bg_color)
        view_menu.add_command(label="Tamaño cuadrícula", command=self.change_grid)
        view_menu.add_separator()
        view_menu.add_command(label="🏷️ Mostrar/Ocultar etiquetas", command=self.toggle_labels_visibility)

        tools_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Herramientas", menu=tools_menu)
        tools_menu.add_command(label="Configuración", command=self.show_config)
        tools_menu.add_separator()
        tools_menu.add_command(label="Actualizar tamaños componentes", command=self.update_all_component_sizes)
        tools_menu.add_separator()

        # SIMULACIÓN: Menú de simulación
        sim_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Simulación", menu=sim_menu)
        sim_menu.add_command(label="▶️ Play/Pause      F5", command=self.toggle_simulation)
        sim_menu.add_command(label="⏹️ Stop                    F6", command=self.stop_simulation)
        sim_menu.add_separator()
        # FUNCIÓN: Configuración PDF
        tools_menu.add_command(label="Config. PDF", command=self.config_pdf)

        help_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Ayuda", menu=help_menu)
        help_menu.add_command(label="Deshacer      Ctrl+Z", command=self.undo)
        help_menu.add_command(label="Rehacer       Ctrl+Y", command=self.redo)
        help_menu.add_separator()
        help_menu.add_command(label="Atajos", command=self.show_shortcuts)
        help_menu.add_command(label="Aviso Legal", command=self.show_legal_notice)
        help_menu.add_command(label="Acerca de", command=self.show_about)

    def create_toolbar(self):
        toolbar_frame = tk.Frame(self.root, bg="#ffffff", relief=tk.FLAT, borderwidth=0)
        toolbar_frame.pack(side=tk.TOP, fill=tk.X, pady=0)

        style = ttk.Style()
        style.configure('Toolbar.TNotebook', background='#ffffff', borderwidth=0)
        style.configure('Toolbar.TNotebook.Tab', padding=[10, 2], font=('Arial', 8))
        separator = tk.Frame(toolbar_frame, width=10, bg="#ffeeaa", height=60, relief=tk.RAISED, bd=0)
        separator.pack(side=tk.LEFT, fill=tk.Y)
        separator.pack_propagate(False)
        self._ribbon_separator = separator
        self.notebook = ttk.Notebook(toolbar_frame, style='Toolbar.TNotebook', height=60)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self.motors_frame = tk.Frame(self.notebook, bg="#ffffff")
        self.notebook.add(self.motors_frame, text="Motores")

        self.protection_frame = tk.Frame(self.notebook, bg="#ffffff")
        self.notebook.add(self.protection_frame, text="Protección")

        self.connection_frame = tk.Frame(self.notebook, bg="#ffffff")
        self.notebook.add(self.connection_frame, text="Conexión")

        # Nueva pestaña de Drivers
        self.drivers_frame = tk.Frame(self.notebook, bg="#ffffff")
        self.notebook.add(self.drivers_frame, text="Drivers")

        # Nueva pestaña de Auxiliares
        self.auxiliares_frame = tk.Frame(self.notebook, bg="#ffffff")
        self.notebook.add(self.auxiliares_frame, text="Auxiliares")

        # Nueva pestaña de Unifilar
        self.unifilar_frame = tk.Frame(self.notebook, bg="#ffffff")
        self.notebook.add(self.unifilar_frame, text="Unifilar")

        # Refrescar botones para todos los frames después de crearlos
        self.refresh_buttons("Motors", clear_first=True)
        self.refresh_buttons("Protection", clear_first=True)
        self.refresh_buttons("Connection", clear_first=True)
        self.refresh_buttons("Drivers", clear_first=True)
        self.refresh_buttons("Auxiliares", clear_first=True)
        self.refresh_buttons("Unifilar", clear_first=True)

    def toggle_unifilar_tab(self, event=None):
        for tab_id in self.notebook.tabs():
            if self.notebook.tab(tab_id, "text") == "Unifilar":
                if self.notebook.tab(tab_id, "state") == "normal":
                    self.notebook.hide(tab_id)
                else:
                    self.notebook.add(tab_id)
                break

    def create_button_image(self, svg_file, size=(48, 48), category=""):
        """Usa sistema centralizado de renderizado SVG (svg_renderer.py)"""
        try:
            from utils.svg_renderer import get_svg_renderer

            # Usar ruta SVG desde configuración
            svg_base_path = self.config.get("svg_path")

            renderer = get_svg_renderer(svg_base_path)

            # CONSOLIDADO: Usar directamente el método centralizado
            return renderer.create_button_image(svg_file, size, category)

        except Exception as e:

            # Fallback al sistema anterior si falla
            return self._create_button_image_fallback(svg_file, size, category)

    def _create_button_image_fallback(self, svg_file, size=(48, 48), category=""):
        """Método de respaldo en caso de falla del sistema centralizado"""
        if not SVG_SUPPORT:
            return None
        try:
            folder = category.lower() if category else ""
            full_path = Path(self.config["svg_path"]) / folder / svg_file
            if full_path.exists():
                # Siempre usar el tamaño por defecto para botones (48x48)
                png_data = cairosvg.svg2png(url=str(full_path), output_width=size[0], output_height=size[1])
                image = Image.open(io.BytesIO(png_data))
                return ImageTk.PhotoImage(image)
            else:
                pass
                return None
        except Exception as e:

            pass
            return None

    def create_drawing_panel(self):
        """Crea el panel lateral para configuración de líneas usando módulo modularizado"""
                # Creando panel de líneas...")

        # current_line_dash configurado

        self.drawing_panel = DrawingPanel(
            self.lines_panel_frame,
            self.current_line_width,
            self.current_line_color,
            self.current_line_dash,
            self.update_all_existing_lines,
            text_mode_callback=self.handle_text_mode_callback,
            shape_preview_callback=self.handle_shape_preview_callback
        )

        # Panel frame configurado

        self.drawing_panel.app = self
                # Referencia al app agregada al panel")

    def switch_to_sheet(self, index):
        """Cambia la hoja activa del proyecto."""
        if index == self.project.active_sheet_index:
            return # Ya estamos en esa hoja

        # Limpiar selecciones de la hoja anterior antes de cambiar
        if hasattr(self, 'event_handler') and self.event_handler:
            try:
                self.event_handler._clear_selection()
            except Exception as e:
                print(f"⚠️ Error limpiando selección al cambiar de hoja: {e}")

        # 1. GUARDAR ESTADO DE LA HOJA ACTUAL
        current_sheet = self.project.get_active_sheet()
        if current_sheet:
            self._save_current_sheet_state(current_sheet)

            # CRÍTICO FIX: Actualizar live_components con los objetos actuales
            # Esto asegura que las posiciones (x, y) de los componentes se preserven
            # cuando se cambia de hoja y luego se vuelve a la hoja anterior
            current_sheet.live_components = self.components[:]
            current_sheet.live_connections = self.connections[:]
            current_sheet.live_texts = self.text_components[:]
            current_sheet.live_images = getattr(self, 'image_components', [])[:]
            current_sheet.live_shape_objects = self.shape_manager.shapes[:]
            current_sheet.live_shapes = self.shapes[:]
            if hasattr(self, 'shielding_manager'):
                current_sheet.live_shieldings = self.shielding_manager.shieldings[:]
            # Persistir block terminals de la hoja actual
            current_sheet.live_block_terminals = getattr(self, 'block_terminals', [])[:]
            print(f"[BT] Guardando {len(current_sheet.live_block_terminals)} block terminal(s) en hoja '{current_sheet.name}'")

        # 2. CAMBIAR ÍNDICE ACTIVO
        if self.project.set_active_sheet(index):
            # 3. LIMPIAR CANVAS (Visualmente)
            try:
                if hasattr(self, 'canvas') and callable(getattr(self.canvas, 'winfo_exists', None)) and self.canvas.winfo_exists():
                    self.canvas.delete("all")
                    # RESET PAN TO (0,0)
                    self.canvas.xview_moveto(0)
                    self.canvas.yview_moveto(0)
                else:
                    print("⚠️ Canvas inválido al cambiar de hoja; omitiendo limpieza visual")
            except Exception as e:
                print(f"⚠️ Error al limpiar el canvas al cambiar de hoja: {e}")

            self.crosshair_created = False # FIX: Forzar recreación del crosshair
            self.lines = []
            self.shapes = []
            self.components = []
            self.connections = []
            self.text_components = []
            self.image_components = [] # Limpiar imágenes
            self.shape_manager.shapes = [] # Limpiar también el manager
            self.block_terminals = [] # Limpiar block terminals al cambiar hoja

            # Limpiar apantallamientos al cambiar de hoja
            if hasattr(self, 'shielding_manager'):
                # Limpiar visualmente y la lista
                for sh in self.shielding_manager.shieldings:
                    sh.clear(self.canvas)
                self.shielding_manager.shieldings = []

            # Limpiar cache de posiciones para forzar redibujado de todas las líneas
            if hasattr(self, 'manhattan_router'):
                self.manhattan_router.clear_position_cache()

            # 4. CARGAR ESTADO DE LA NUEVA HOJA
            new_sheet = self.project.get_active_sheet()

            if hasattr(new_sheet, 'live_components'):
                self.components = new_sheet.live_components
                self.connections = new_sheet.live_connections
                self.lines = getattr(new_sheet, 'live_lines', [])
                self.shapes = getattr(new_sheet, 'live_shapes', [])
                self.text_components = getattr(new_sheet, 'live_texts', [])
                self.image_components = getattr(new_sheet, 'live_images', []) # NUEVO
                # Restaurar block terminals de la hoja
                self.block_terminals = getattr(new_sheet, 'live_block_terminals', [])[:]
                print(f"[BT] Restaurando {len(self.block_terminals)} block terminal(s) en hoja '{new_sheet.name}'")

                # CRÍTICO: Restaurar live_shape_objects PRIMERO (al manager)
                if hasattr(new_sheet, 'live_shape_objects'):
                    self.shape_manager.shapes = new_sheet.live_shape_objects[:]

                    # FIX Z-ORDER: Reordenar Rieles DIN al inicio para que queden detrás de componentes
                    from models.shape import DinRail
                    din_rails = [s for s in self.shape_manager.shapes if isinstance(s, DinRail)]
                    non_din_shapes = [s for s in self.shape_manager.shapes if not isinstance(s, DinRail)]
                    self.shape_manager.shapes = din_rails + non_din_shapes  # Rieles DIN al inicio

                    # CRÍTICO: Limpiar canvas_id de shapes antes de redibujar
                    # Esto es necesario porque canvas.delete("all") invalida los IDs de canvas
                    for shape in self.shape_manager.shapes:
                        shape.canvas_id = None  # Forzar que cree uno nuevo al dibujar
                        if hasattr(shape, 'inner_ids'):
                            shape.inner_ids = []  # También limpiar inner_ids

                    for shape in self.shape_manager.shapes:
                        shape.draw(self.canvas)
                else:
                    # Si no hay live_shape_objects, dibujar desde self.shapes (lista local)
                    # También limpiar canvas_id en estos shapes
                    for shape in self.shapes:
                        shape.canvas_id = None
                        if hasattr(shape, 'inner_ids'):
                            shape.inner_ids = []
                        shape.draw(self.canvas)

                # Ahora dibujar componentes (después de shapes para que queden encima)
                for comp in self.components:
                    comp.draw()
                for conn in self.connections:
                    self.update_manhattan_line(conn)
                for img in self.image_components: # NUEVO
                    img.draw()

                self.wire_numbering_dirty = True
                if hasattr(self, 'update_wire_numbers'):
                    self.update_wire_numbers()
                for line_data in getattr(new_sheet, 'live_lines_data', []):
                    # Solo redibujar líneas si no son parte de una conexión ya dibujada
                    # (Esto requiere cuidado para no duplicar, por ahora simplificamos)
                    pass

                for text in self.text_components:
                    text.draw()

                # Restaurar apantallamientos vivos
                if hasattr(self, 'shielding_manager') and hasattr(new_sheet, 'live_shieldings'):
                    self.shielding_manager.shieldings = new_sheet.live_shieldings[:]
                    for sh in self.shielding_manager.shieldings:
                        sh.draw(self.canvas)

                _eh = getattr(self, 'event_handler', None)
                if self.block_terminals and _eh and hasattr(_eh, '_place_block_terminal'):
                    bts_snapshot = [
                        (bt['x'], bt['y'], bt['filas'], bt['bornas'], bt.get('label_data', {}).copy())
                        for bt in self.block_terminals
                    ]
                    self.block_terminals = []
                    for (x, y, filas, bornas, ld) in bts_snapshot:
                        try:
                            _eh._place_block_terminal(x, y, filas, bornas, label_data=ld, auto_open=False)
                        except Exception as e:
                            import traceback
                            print(f"[BT] Error redibujando block terminal: {e}")
                            traceback.print_exc()
                    # _place_block_terminal dibuja en coords mundo (sin zoom).
                    # Al regresar a la hoja con zoom activo los BTs aparecen en tamaño normal.
                    # _redraw_block_terminals_after_zoom los redibuja escalados correctamente,
                    # igual a lo que hace el zoom ligero manual.
                    if hasattr(_eh, '_redraw_block_terminals_after_zoom'):
                        self.root.after(10, _eh._redraw_block_terminals_after_zoom)
                elif self.block_terminals:
                    print(f"[BT] No se puede redibujar: event_handler={_eh}, tiene método={hasattr(_eh, '_place_block_terminal') if _eh else 'N/A'}")
            else:
                # Carga tradicional desde diccionario (primera vez que se entra o carga desde archivo)
                self._load_sheet_state(new_sheet)

                # CRÍTICO FIX: Establecer live_shape_objects después de cargar desde elementos
                # Esto asegura que los shapes cargados se registren como "vivos" para futuras
                # restauraciones y para que Cabinet2DGenerator preserve los cambios del usuario
                if not hasattr(new_sheet, 'live_shape_objects'):
                    new_sheet.live_shape_objects = self.shape_manager.shapes[:]
                if not hasattr(new_sheet, 'live_components'):
                    new_sheet.live_components = self.components[:]
                if not hasattr(new_sheet, 'live_connections'):
                    new_sheet.live_connections = self.connections[:]
                if not hasattr(new_sheet, 'live_texts'):
                    new_sheet.live_texts = self.text_components[:]
                if not hasattr(new_sheet, 'live_images'):
                    new_sheet.live_images = getattr(self, 'image_components', [])[:]
                if not hasattr(new_sheet, 'live_block_terminals'):
                    new_sheet.live_block_terminals = getattr(self, 'block_terminals', [])[:]

                # Restaurar block terminals de la hoja
                self.block_terminals = getattr(new_sheet, 'live_block_terminals', [])[:]

                _eh2 = getattr(self, 'event_handler', None)
                if self.block_terminals and _eh2 and hasattr(_eh2, '_place_block_terminal'):
                    bts_snap2 = [
                        (bt['x'], bt['y'], bt['filas'], bt['bornas'], bt.get('label_data', {}).copy())
                        for bt in self.block_terminals
                    ]
                    self.block_terminals = []
                    for (x2, y2, filas2, bornas2, ld2) in bts_snap2:
                        try:
                            _eh2._place_block_terminal(x2, y2, filas2, bornas2, label_data=ld2, auto_open=False)
                        except Exception:
                            pass
                    # ídem rama live_components
                    if hasattr(_eh2, '_redraw_block_terminals_after_zoom'):
                        self.root.after(10, _eh2._redraw_block_terminals_after_zoom)

                # La hoja se acaba de renderizar desde el archivo con el tema actual,
                # así que ya está correctamente teñida (evita un refresh redundante al cargar).
                new_sheet.last_rendered_bg = self.canvas.cget("bg")

# Durante la exportación PDF/DXF no necesitamos regenerar informes ni actualizar UI
            if getattr(self, '_is_exporting_pdf', False) or getattr(self, '_is_exporting_dxf', False):
                return


            # Si es la hoja de Seguridad, regenerar su contenido automáticamente
            # Esto asegura que siempre se muestre correctamente al cargar el proyecto
            if new_sheet.name == "Prescripciones de Seguridad":
                try:
                    from core.reports import SafetySheetGenerator
                    generator = SafetySheetGenerator(self.project)
                    generator.generate_safety_sheet(self)
                except Exception as e:
                    print(f"⚠️ Error regenerando hoja de seguridad: {e}")

            # 5. ACTUALIZAR UI
            self.update_sheet_list_ui()
            if hasattr(self, 'set_status'):
                self.set_status(f"📄 Cambiado a: {new_sheet.name}", "blue")
            self.update_info_bar()

            if hasattr(self, 'update_cross_references'):
                self.update_cross_references()

            # REGENERAR REPORTES SI ES NECESARIO (Redibujar al cambiar de pestaña)
            # Esto soluciona problemas visuales y asegura datos actualizados
            if new_sheet.name == "Plano de Borner":
                try:
                    # BornerPlanGenerator ya está importado de core.reports
                    generator = BornerPlanGenerator(self.project)
                    generator.refresh_current_sheet(self)
                    if hasattr(self, 'set_status'):
                        self.set_status("🔄 Plano de Borner regenerado y actualizado", "blue")
                except Exception as e:
                    print(f"Error regenerando Plano de Borner: {e}")
                    import traceback
                    traceback.print_exc()

            elif new_sheet.name == "Lista de Materiales":
                try:
                    # BOMGenerator ya está importado de core.reports
                    generator = BOMGenerator(self.project)
                    generator.generate_bom_sheet(self)
                    if hasattr(self, 'set_status'):
                        self.set_status("🔄 Lista de Materiales actualizada", "blue")
                except Exception as e:
                    print(f"Error regenerando BOM: {e}")

            elif new_sheet.name == "Resumen de Gabinete":
                try:
                    # CabinetSummaryGenerator ya está importado de core.reports
                    generator = CabinetSummaryGenerator(self.project)
                    generator.generate_cabinet_summary_sheet(self)
                    if hasattr(self, 'set_status'):
                        self.set_status("🔄 Resumen de Gabinete actualizado", "blue")
                except Exception as e:
                    print(f"Error regenerando Resumen: {e}")

            elif new_sheet.name == "Hoja de Gabinete 2D":
                try:
                    # Cabinet2DGenerator ya está importado de core.reports
                    generator = Cabinet2DGenerator(self.project)
                    generator.generate_cabinet_2d_sheet(self)
                    # El status se maneja dentro del generador
                except Exception as e:
                    print(f"Error regenerando Hoja 2D: {e}")
                    import traceback
                    traceback.print_exc()
                # Aviso flotante con atajos de teclado
                self.root.after(400, lambda: self.set_status(
                    "  <Ctrl>+<D>  Traza Riel DIN          <Ctrl>+<F>  Traza Canaleta 40×40",
                    "blue", duration=6000
                ))

            elif new_sheet.name == "Tabla de Cableado":
                try:
                    self.update_wiring_table_sheet()
                    if hasattr(self, 'set_status'):
                        self.set_status("🔄 Tabla de Cableado actualizada", "blue")
                except Exception as e:
                    print(f"Error regenerando Tabla de Cableado: {e}")

            if hasattr(self, '_update_buttons_for_sheet'):
                self._update_buttons_for_sheet(new_sheet.name)

            # RE-APLICAR TEMA: Si la hoja cargada se renderizó con otro fondo
            # (ej. el modo oscuro se cambió mientras estaba activa otra hoja),
            current_bg = self.canvas.cget("bg")
            if getattr(new_sheet, 'last_rendered_bg', None) != current_bg:
                self.refresh_all_colors()

    def _save_current_sheet_state(self, sheet):
        """Guarda los elementos actuales en el objeto Sheet."""
        # NOTA: En una implementación real, aquí deberíamos serializar los objetos
        # o mover las instancias. Por ahora, moveremos las listas.

        # IMPORTANTE: Esto es un cambio fundamental.
        # En lugar de tener listas globales self.lines, ahora pertenecen a la hoja.
        # Para esta primera iteración, guardaremos una COPIA de los datos necesarios.

        # Serializar líneas
        sheet.elements = []
        for line in self.lines:
            sheet.elements.append({
                "type": "line",
                "coords": self.canvas.coords(line),
                "width": self.canvas.itemcget(line, "width"),
                "fill": self.canvas.itemcget(line, "fill"),
                "dash": self.canvas.itemcget(line, "dash"),
                "tags": self.canvas.gettags(line)
            })

        # Serializar shapes (usando el manager)
        for shape in self.shape_manager.shapes:
            if hasattr(shape, 'to_dict'):
                shape_data = shape.to_dict()
                sheet.elements.append(shape_data)
            else:
                # Fallback para shapes básicos sin to_dict (si los hay)
                shape_data = {
                    "type": getattr(shape, 'shape_type', 'unknown'),
                    "x": getattr(shape, 'x', 0),
                    "y": getattr(shape, 'y', 0),
                    "outline": getattr(shape, 'outline', '#000000'),
                    "outline_width": getattr(shape, 'outline_width', 2),
                    "fill": getattr(shape, 'fill', ''),
                    "tags": getattr(shape, 'tags', [])
                }
                sheet.elements.append(shape_data)

        for comp in self.components:
            comp_data = comp.to_dict()
            # Solo establecer type si no existe (JunctionComponent ya tiene "type": "junction")
            if "type" not in comp_data:
                comp_data["type"] = "component"

            # El estado de simulación NO se persiste.
            # is_active / current_rpm / motor_direction / etc. son estado de ejecución, no
            # del proyecto: guardarlos hacía que un Ctrl+S en medio de una simulación
            # escribiera el circuito energizado y al recargar el archivo apareciera
            # encendido, con las capas ON/OFF de los SVG y los textos de los VDF.
            # El archivo representa siempre el esquema en reposo.

            sheet.elements.append(comp_data)

        # Serializar imágenes
        if hasattr(self, 'image_components'):
            for img in self.image_components:
                sheet.elements.append(img.to_dict())

        # SIMULACIÓN: CAPTURAR SEÑALES GLOBALES (CROSS-PAGE)
        # Esto permite que bobinas en esta página afecten a contactos en otras páginas después de cambiar
        if hasattr(self, 'simulation_controller') and self.simulation_controller.is_running:
            try:
                from simulation.component_behavior import ComponentBehaviorManager
                from simulation.energy_propagation import EnergyPropagator

                # Calcular estado de red actual para esta página
                propagator = EnergyPropagator(self)
                network_state = propagator.propagate()

                # Escanear señales (bobinas, etc)
                behavior_manager = ComponentBehaviorManager(self)
                signals = behavior_manager.scan_current_page_signals(self.components, network_state)

                page_idx = self.project.active_sheet_index
                self.simulation_controller.update_page_signals(page_idx, signals)
            except Exception as e:
                print(f"⚠️ Error capturando señales cross-page: {e}")

        # Serializar textos
        for text_comp in self.text_components:
            text_data = text_comp.to_dict()
            sheet.elements.append(text_data)

        # Serializar conexiones
        sheet.connections = []
        for conn in self.connections:
            conn_data = conn.to_dict(self.components)
            conn_data["type"] = "connection"
            sheet.connections.append(conn_data)

        # Serializar apantallamientos
        if hasattr(self, 'shielding_manager') and self.shielding_manager:
            for sh in self.shielding_manager.shieldings:
                sh_data = sh.to_dict()
                sh_data["type"] = "shielding"
                sheet.elements.append(sh_data)

        sheet.zoom_level = self.canvas.zoom_level

        self.shapes = self.shape_manager.shapes[:]  # Asegurar que ambas listas estén sincronizadas
        sheet.live_components = self.components[:]
        sheet.live_connections = self.connections[:]
        sheet.live_shape_objects = self.shape_manager.shapes[:] # FIX: Guardar objetos Shape vivos (Marcos BOM, etc.)
        sheet.live_shapes = self.shapes[:] # También guardar la lista local
        sheet.live_texts = self.text_components[:]
        sheet.live_images = getattr(self, 'image_components', [])[:] # NUEVO

        if hasattr(self, 'shielding_manager'):
            sheet.live_shieldings = self.shielding_manager.shieldings[:]

        sheet.live_block_terminals = getattr(self, 'block_terminals', [])[:]

        # Las líneas son IDs de canvas, no se pueden persistir fácilmente al borrar el canvas,
        # pero las conexiones regeneran sus líneas al redibujar.

    def get_all_project_components(self):
        """Retorna una lista plana de todos los componentes de todas las hojas."""
        all_comps = []
        # Importante: Incluir los componentes de la hoja activa actual
        all_comps.extend(self.components)

        # Incluir componentes de otras hojas que están guardados
        current_sheet_idx = self.project.active_sheet_index
        for i, sheet in enumerate(self.project.sheets):
            if i == current_sheet_idx: continue

            # Si la hoja tiene instancias vivas (lo implementaremos en switch_to_sheet)
            if hasattr(sheet, 'live_components'):
                all_comps.extend(sheet.live_components)
            else:
                # Si no tiene instancias vivas, por ahora no podemos simularla
                # (switch_to_sheet se encargará de mantenerlas vivas)
                pass
        return all_comps

    def get_all_project_connections(self):
        """Retorna una lista plana de todas las conexiones de todas las hojas."""
        all_conns = []
        all_conns.extend(self.connections)

        current_sheet_idx = self.project.active_sheet_index
        for i, sheet in enumerate(self.project.sheets):
            if i == current_sheet_idx: continue

            if hasattr(sheet, 'live_connections'):
                all_conns.extend(sheet.live_connections)
        return all_conns

    def build_component_sheet_map(self):
        """
        Construye {id(componente): nombre_hoja} usando las mismas fuentes que
        get_all_project_components(), para poder identificar en qué hoja está cada
        componente sin depender del estado mutable de self.components.
        """
        mapping = {}
        try:
            active_idx = self.project.active_sheet_index
            for i, sheet in enumerate(self.project.sheets):
                comps = self.components if i == active_idx else getattr(sheet, 'live_components', [])
                for comp in comps:
                    mapping[id(comp)] = sheet.name
        except Exception:
            pass
        return mapping

    def get_component_sheet_name(self, comp):
        """
        Devuelve el nombre de la hoja a la que pertenece un componente.
        Se usa para informar en qué hoja se produjo una falla de simulación.
        """
        if comp is None:
            return "Hoja ?"

        # Durante un tick de simulación self.app.components se reemplaza temporalmente
        # por el agregado de todas las hojas, por lo que se consulta el mapa congelado.
        sheet_map = getattr(self, '_sim_sheet_map', None)
        if sheet_map:
            return sheet_map.get(id(comp), "Hoja ?")

        try:
            active_idx = self.project.active_sheet_index
            for i, sheet in enumerate(self.project.sheets):
                if i == active_idx:
                    if comp in self.components:
                        return sheet.name
                elif comp in getattr(sheet, 'live_components', []):
                    return sheet.name
        except Exception:
            pass
        return "Hoja ?"

    def _load_sheet_state(self, sheet):
        """Restaura los elementos de la hoja en el canvas."""
        # Restaurar vista
        self.canvas.zoom_level = sheet.zoom_level

        # Restaurar líneas
        for elem in sheet.elements:
            if elem["type"] == "line" and "coords" in elem:
                line_id = self.canvas.create_line(
                    *elem["coords"],
                    width=elem["width"],
                    fill=elem["fill"],
                    dash=elem["dash"],
                    tags=elem["tags"]
                )
                self.lines.append(line_id)

            elif elem.get("type") in ["circle", "square", "rect", "rounded_rect", "ellipse", "text", "line", "geom_line", "din_rail", "canaleta", "multipole_borner"]:
                # Reconstruir objeto shape
                shape_type = elem["type"]
                x = elem.get("x", 0)
                y = elem.get("y", 0)

                shape = None
                if shape_type == "circle":
                    from models.shape import Circle
                    shape = Circle.from_dict(elem)
                elif shape_type == "square":
                    from models.shape import Square
                    shape = Square.from_dict(elem)
                elif shape_type == "rect":
                    from models.shape import Rect
                    shape = Rect.from_dict(elem)
                elif shape_type == "rounded_rect":
                    from models.shape import RoundedRect
                    shape = RoundedRect.from_dict(elem)
                elif shape_type == "ellipse":
                    from models.shape import Ellipse
                    shape = Ellipse.from_dict(elem)
                elif shape_type in ["line", "geom_line"]:
                    shape = ShapeFactory.create_shape(shape_type, elem["x1"], elem["y1"], x2=elem["x2"], y2=elem["y2"])
                    shape.color = elem.get("color", "black")
                    shape.width = elem.get("width", 1)
                elif shape_type == "multipole_borner":
                    # Restaurar MultipoleBorner desde diccionario
                    from models.shape import MultipoleBorner
                    shape = MultipoleBorner.from_dict(elem)
                elif shape_type == "din_rail":
                    # Restaurar DinRail desde diccionario
                    from models.shape import DinRail
                    shape = DinRail.from_dict(elem)
                elif shape_type == "canaleta":
                    # Restaurar Canaleta desde diccionario
                    from models.shape import Canaleta
                    shape = Canaleta.from_dict(elem)
                elif shape_type == "text":
                    from models.component import TextComponent
                    text_comp = TextComponent.from_dict(self.canvas, elem)
                    text_comp.select()  # Crear el recuadro
                    self.text_components.append(text_comp)
                elif shape_type == "image":
                    from models.component import ImageComponent
                    img_comp = ImageComponent.from_dict(self.canvas, elem)
                    img_comp.draw()
                    if not hasattr(self, 'image_components'): self.image_components = []
                    self.image_components.append(img_comp)

                if shape:
                    # Restaurar propiedades visuales (para shapes genéricas)
                    if hasattr(shape, 'outline') and "outline" in elem:
                        shape.outline = elem.get("outline", "#000000")
                    if hasattr(shape, 'outline_width') and "outline_width" in elem:
                        shape.outline_width = elem.get("outline_width", 2)
                    if hasattr(shape, 'fill') and "fill" in elem:
                        shape.fill = elem.get("fill", "")
                    if hasattr(shape, 'tags') and "tags" in elem:
                        shape.tags = elem.get("tags", [])
                    self.shape_manager.add_shape(shape)
                    # IMPORTANTE: Dibujar la forma en el canvas
                    shape.draw(self.canvas)

            elif elem.get("type") in ["component", "junction"]:
                # DETECTAR EMPALMES: Verificar si es un JunctionComponent
                is_junction = (
                    elem.get("type") == "junction" or
                    elem.get("svg_file") is None and elem.get("category") == "Junction" or
                    elem.get("svg_file") == "empalme.svg"
                )

                if is_junction:
                    from models.junction_component import JunctionComponent
                    comp = JunctionComponent.from_dict(self.canvas, elem, self.config)
                else:
                    # Reconstruir componente normal
                    comp = Component.from_dict(self.canvas, elem, self.config["svg_path"], self.config)

                comp.draw()
                self.components.append(comp)

                # El estado de simulación se ignora aunque venga en el archivo.
                # Archivos guardados por versiones anteriores sí podían traer
                # "simulation_state" (Ctrl+S con la simulación en marcha); al cargar
                # un proyecto nuevo el esquema debe abrirse siempre en reposo.
                # La clave se descarta en _load_from_file para que el próximo guardado
                # limpie el archivo.

        # Restaurar conexiones después de que los componentes estén cargados
        if hasattr(sheet, 'connections') and sheet.connections:
            for conn_data in sheet.connections:
                if conn_data.get("type") == "connection":
                    try:
                        # Reconstruir conexión usando Connection.from_dict
                        connection = Connection.from_dict(conn_data, self.components)

                        self.connections.append(connection)

                        # Solo actualizar si NO tiene segmentos (preserva geometría manual)
                        has_segments = hasattr(connection, 'segments') and connection.segments
                        if not has_segments:
                            self.update_manhattan_line(connection)
                        else:
                            # Solo redibujar visualmente lo que ya existe
                            if hasattr(self, 'unified_line_system'):
                                self.unified_line_system._redraw_connection_fast(connection)
                            else:
                                self.update_manhattan_line(connection)

                    except Exception as e:
                        # Si falla la restauración de una conexión, continuar con las demás
                        pass

        # Restaurar apantallamientos
        if hasattr(self, 'shielding_manager'):
            for elem in sheet.elements:
                if elem.get("type") == "shielding":
                    from models.shielding import Shielding
                    sh = Shielding.from_dict(elem)
                    self.shielding_manager.add_shielding(sh)

        # CRÍTICO: Sincronizar self.shapes con self.shape_manager.shapes
        # Esto asegura que los shapes cargados estén disponibles para futura serialización
        self.shapes = self.shape_manager.shapes[:]

    def add_new_sheet(self, name=None):
        """Crea una nueva hoja y cambia a ella."""
        if name is None:
            count = len(self.project.sheets) + 1
            name = f"Hoja {count}"
        self.project.add_sheet(name)
        self.update_sheet_list_ui()
        self.switch_to_sheet(len(self.project.sheets) - 1)

    def rename_current_sheet(self, new_name):
        """Renombra la hoja activa."""
        sheet = self.project.get_active_sheet()
        if sheet:
            sheet.name = new_name
            self.update_sheet_list_ui()

    def delete_current_sheet(self):
        """Elimina la hoja activa."""
        if len(self.project.sheets) <= 1:
            tk.messagebox.showwarning("Aviso", "No se puede eliminar la única hoja del proyecto.")
            return

        if tk.messagebox.askyesno("Confirmar", "¿Eliminar esta hoja permanentemente?"):
            # Cambiar de hoja ANTES de eliminar para guardar estado actual y limpiar canvas
            idx_to_delete = self.project.active_sheet_index
            new_index = 1 if idx_to_delete == 0 else idx_to_delete - 1

            self.switch_to_sheet(new_index)
            self.project.remove_sheet(idx_to_delete)

            self.update_sheet_list_ui()

    def update_sheet_list_ui(self):
        """Actualiza la lista visual de hojas en el panel."""
        if hasattr(self, 'drawing_panel'):
            # Limpiar lista
            self.drawing_panel.worksheets_listbox.delete(0, tk.END)

            # Insertar nombre del proyecto (header)
            self.drawing_panel.worksheets_listbox.insert(tk.END, f"📂 {self.project.name}")
            self.drawing_panel.worksheets_listbox.itemconfig(0, {'bg': '#e0e0e0', 'fg': 'black'})

            # Insertar hojas
            for i, sheet in enumerate(self.project.sheets):
                prefix = "📄 "
                # Icono especial para reportes
                if sheet.name == "Lista de Materiales":
                    prefix = "📋 "
                elif sheet.name == "Resumen de Gabinete":
                    prefix = "📏 "

                if i == self.project.active_sheet_index:
                    prefix = "👉 " # Indicador de activa

                self.drawing_panel.worksheets_listbox.insert(tk.END, f"{prefix}{sheet.name}")

            # SELECCIONAR HOJA ACTIVA (Después de insertar todas)
            active_idx = self.project.active_sheet_index + 1
            if active_idx < self.drawing_panel.worksheets_listbox.size():
                self.drawing_panel.worksheets_listbox.selection_clear(0, tk.END)
                self.drawing_panel.worksheets_listbox.selection_set(active_idx)
                self.drawing_panel.worksheets_listbox.activate(active_idx)
                self.drawing_panel.worksheets_listbox.see(active_idx)

            self.drawing_panel.worksheets_listbox.bind("<Button-3>", self.show_sheet_context_menu)

    def show_sheet_context_menu(self, event):
        """Muestra menú contextual para gestión de hojas"""
        try:
            index = self.drawing_panel.worksheets_listbox.nearest(event.y)
            self.drawing_panel.worksheets_listbox.selection_clear(0, tk.END)
            self.drawing_panel.worksheets_listbox.selection_set(index)

            # El índice 0 es el título del proyecto
            if index == 0:
                menu = tk.Menu(self.root, tearoff=0)
                menu.add_command(label="📄 Nueva Hoja", command=self.add_new_sheet)
                menu.add_separator()
                menu.add_command(label="✏️ Renombrar Proyecto", command=self.rename_project_ui)
                menu.add_separator()
                menu.add_command(label="Insertar Hoja de Seguridad", command=self.insert_safety_sheet)
                menu.add_command(label="Insertar Lista de Materiales (BOM)", command=self.insert_bom_sheet)
                menu.add_command(label="Insertar Resumen de Gabinete", command=self.insert_cabinet_summary_sheet)
                menu.add_command(label="Insertar Plano de Borner", command=self.insert_borner_plan_sheet)
                menu.add_command(label="Insertar Hoja de Gabinete 2D", command=self.insert_cabinet_2d_sheet)
                menu.add_command(label="Insertar Tabla de Cableado", command=self.insert_wiring_table_sheet)
                menu.add_command(label="Generar Plano Unifilar", command=self.insert_unifilar_sheet)
                menu.add_separator()
                menu.add_command(label="Actualizar Reportes", command=self.update_all_reports)
                menu.tk_popup(event.x_root, event.y_root)
                return

            # Ajustar índice para obtener la hoja real (index - 1)
            sheet_index = index - 1
            if sheet_index < 0 or sheet_index >= len(self.project.sheets):
                return

            selected_sheet = self.project.sheets[sheet_index]

            menu = tk.Menu(self.root, tearoff=0)

            menu.add_command(label="📄 Nueva Hoja", command=self.add_new_sheet)
            menu.add_separator()

            # Solo mostrar "Generar" si no es ya un plano unifilar y no es una hoja de reporte
            report_names = ["Prescripciones de Seguridad", "Lista de Materiales", "Resumen de Gabinete", "Plano de Borner", "Hoja de Gabinete 2D", "Tabla de Cableado"]
            if not selected_sheet.name.startswith("Plano Unifilar") and selected_sheet.name not in report_names:
                menu.add_command(label="Generar Plano Unifilar", command=lambda: self.insert_unifilar_sheet_from_idx(sheet_index))
                menu.add_separator()

            # Opciones específicas si es reporte
            if selected_sheet.name == "Prescripciones de Seguridad":
                menu.add_command(label="🔄 Actualizar Seguridad", command=self.insert_safety_sheet)
                menu.add_separator()
            elif selected_sheet.name == "Lista de Materiales":
                menu.add_command(label="🔄 Actualizar Lista", command=self.update_bom_sheet)
                menu.add_command(label="💾 Exportar a CSV (;)", command=self.export_bom_csv)
                menu.add_separator()
            elif selected_sheet.name == "Resumen de Gabinete":
                menu.add_command(label="🔄 Actualizar Resumen", command=self.update_cabinet_summary_sheet)
                menu.add_separator()
            elif selected_sheet.name == "Hoja de Gabinete 2D":
                menu.add_command(label="🔄 Actualizar Gabinete 2D", command=self.update_cabinet_2d_sheet)
                menu.add_separator()
            elif selected_sheet.name == "Tabla de Cableado":
                menu.add_command(label="🔄 Actualizar Tabla de Cableado", command=self.update_wiring_table_sheet)
                menu.add_command(label="💾 Exportar a CSV (;)", command=self.export_wiring_table_csv)
                menu.add_separator()
            elif selected_sheet.name.startswith("Plano Unifilar"):
                menu.add_command(label="🔄 Regenerar Unifilar", command=self.update_unifilar_sheet)
                menu.add_separator()

            menu.add_command(label="Cambiar Nombre", command=lambda: self.rename_sheet_ui(sheet_index))
            menu.add_separator()

            # Opciones de movimiento
            if len(self.project.sheets) > 1:
                menu.add_command(label="⬆️ Mover Arriba", command=lambda: self.move_sheet_ui(sheet_index, -1))
                menu.add_command(label="⬇️ Mover Abajo", command=lambda: self.move_sheet_ui(sheet_index, 1))
                menu.add_separator()

            menu.add_command(label="❌ Eliminar Hoja", command=lambda: self.delete_sheet_ui(sheet_index))

            menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            print(f"Error mostrando menú contextual: {e}")

    def insert_bom_sheet(self):
        """Inserta o actualiza la hoja de Lista de Materiales"""
        try:
            generator = BOMGenerator(self.project)
            generator.generate_bom_sheet(self)
            self.update_sheet_list_ui()
            if hasattr(self, 'set_status'):
                self.set_status("✅ Lista de Materiales generada correctamente", "green")
        except Exception as e:
            tk.messagebox.showerror("Error", f"Error generando BOM: {str(e)}")

    def update_bom_sheet(self):
        """Actualiza la hoja BOM existente"""
        self.insert_bom_sheet()

    def insert_cabinet_summary_sheet(self):
        """Inserta o actualiza la hoja de Resumen de Gabinete"""
        try:
            generator = CabinetSummaryGenerator(self.project)
            generator.generate_cabinet_summary_sheet(self)
            self.update_sheet_list_ui()
            if hasattr(self, 'set_status'):
                self.set_status("✅ Resumen de Gabinete generado correctamente", "green")
        except Exception as e:
            self.set_status(f"❌ Error generando resumen: {str(e)}", "red")

    def show_cabinet_selection_menu(self, event):
        """Muestra un menú desplegable para seleccionar el tamaño del gabinete."""
        from utils.utils import load_medidas_config
        config = load_medidas_config()
        comerciales = config.get("armarios_comerciales", [])

        if not comerciales:
            return

        menu = tk.Menu(self.root, tearoff=0)

        # Opción para volver al cálculo automático
        menu.add_command(
            label="🔄 Cálculo Automático",
            command=lambda: self.set_selected_cabinet(None)
        )
        menu.add_separator()

        for w, h, d in comerciales:
            label = f"{w} x {h} x {d} mm"
            # Capturar valores en el lambda usando default args
            menu.add_command(
                label=label,
                command=lambda size=[w, h, d]: self.set_selected_cabinet(size)
            )

        menu.post(event.x_root, event.y_root)

    def set_selected_cabinet(self, size):
        """Establece el gabinete seleccionado y refresca las hojas afectadas."""
        self.project.selected_cabinet = size
        self.set_status(f"📏 Gabinete seleccionado: {size if size else 'Automático'}", "blue")

        # 1. Actualizar Resumen de Gabinete (si existe)
        self.insert_cabinet_summary_sheet()

        # 2. Actualizar Hoja de Gabinete 2D (si existe)
        # Buscarla para ver si está creada
        has_2d = any(sheet.name == "Hoja de Gabinete 2D" for sheet in self.project.sheets)
        if has_2d:
            # Si estamos en la hoja 2D, regenerarla. Si no, solo marcar que necesita update?
            # Por ahora la regeneramos siempre para que el cambio sea inmediato y visible
            self.insert_cabinet_2d_sheet()

        self.save_undo_checkpoint()

    def update_cabinet_summary_sheet(self):
        """Actualiza la hoja de Resumen de Gabinete existente"""
        self.insert_cabinet_summary_sheet()

    def insert_cabinet_2d_sheet(self):
        """Inserta o actualiza la hoja de Gabinete 2D"""
        try:
            generator = Cabinet2DGenerator(self.project)
            generator.generate_cabinet_2d_sheet(self)
            self.update_sheet_list_ui()
            if hasattr(self, 'set_status'):
                self.set_status("✅ Hoja de Gabinete 2D generada correctamente", "green")
        except Exception as e:
            tk.messagebox.showerror("Error", f"Error generando gabinete 2D: {str(e)}")

    def update_cabinet_2d_sheet(self):
        """Actualiza la hoja de Gabinete 2D existente"""
        self.insert_cabinet_2d_sheet()

    def insert_borner_plan_sheet(self):
        """Inserta o actualiza la hoja de Plano de Borner"""
        try:
            generator = BornerPlanGenerator(self.project)
            generator.generate_borner_plan_sheet(self)
            self.update_sheet_list_ui()
            if hasattr(self, 'set_status'):
                self.set_status("✅ Plano de Borner generado correctamente", "green")
        except Exception as e:
            tk.messagebox.showerror("Error", f"Error generando plano de borner: {str(e)}")

    def insert_safety_sheet(self):
        """Inserta la hoja de Prescripciones de Seguridad con contenido profesional."""
        try:
            generator = SafetySheetGenerator(self.project)
            generator.generate_safety_sheet(self)
            self.update_sheet_list_ui()
            if hasattr(self, 'set_status'):
                self.set_status("✅ Hoja de Seguridad generada correctamente", "green")
        except Exception as e:
            tk.messagebox.showerror("Error", f"Error generando hoja de seguridad: {str(e)}")

    def insert_unifilar_sheet(self):
        """Genera o actualiza el plano unifilar basado en la hoja actual"""
        try:
            generator = UnifilarGenerator(self.project)
            success = generator.generate_unifilar_sheet(self)
            if success:
                self.update_sheet_list_ui()
                if hasattr(self, 'set_status'):
                    self.set_status("✅ Plano Unifilar generado correctamente", "green")
            else:
                tk.messagebox.showwarning("Aviso", "No se pudo generar el plano unifilar desde esta hoja.")
        except Exception as e:
            tk.messagebox.showerror("Error", f"Error generando plano unifilar: {str(e)}")

    def update_unifilar_sheet(self):
        """Actualiza la hoja de Plano Unifilar existente"""
        self.insert_unifilar_sheet()

    def insert_unifilar_sheet_from_idx(self, index):
        """Cambia a la hoja seleccionada y genera el plano unifilar."""
        self.switch_to_sheet(index)
        self.insert_unifilar_sheet()

    def show_canvas_context_menu(self, event):
        """Muestra menú contextual en el canvas (área de dibujo)"""
        menu = tk.Menu(self.root, tearoff=0)

        current_sheet = self.project.get_active_sheet()
        is_unifilar = current_sheet and current_sheet.name.startswith("Plano Unifilar")
        report_names = ["Prescripciones de Seguridad", "Lista de Materiales", "Resumen de Gabinete", "Plano de Borner", "Hoja de Gabinete 2D", "Tabla de Cableado"]
        is_report = current_sheet and current_sheet.name in report_names

        # Opciones generales de la hoja
        if is_unifilar:
            menu.add_command(label="🔄 Regenerar Plano Unifilar", command=self.update_unifilar_sheet)
            menu.add_separator()
        elif not is_report:
            menu.add_command(label="Generar Plano Unifilar", command=self.insert_unifilar_sheet)
            menu.add_separator()
        menu.add_command(label="Insertar Lista de Materiales (BOM)", command=self.insert_bom_sheet)
        menu.add_command(label="Insertar Resumen de Gabinete", command=self.insert_cabinet_summary_sheet)
        menu.add_command(label="Insertar Plano de Borner", command=self.insert_borner_plan_sheet)
        menu.add_command(label="Insertar Hoja de Gabinete 2D", command=self.insert_cabinet_2d_sheet)
        menu.add_command(label="Insertar Tabla de Cableado", command=self.insert_wiring_table_sheet)
        menu.add_separator()
        menu.add_command(label="Actualizar Todos los Reportes", command=self.update_all_reports)

        menu.tk_popup(event.x_root, event.y_root)

    def update_all_reports(self):
        """Actualiza todos los reportes del proyecto."""
        self.insert_safety_sheet()
        self.insert_bom_sheet()
        self.insert_cabinet_summary_sheet()
        self.insert_cabinet_2d_sheet()
        self.insert_borner_plan_sheet()
        self.insert_wiring_table_sheet()

    def insert_wiring_table_sheet(self):
        """Inserta o actualiza la hoja de Tabla de Cableado."""
        try:
            generator = WiringTableGenerator(self.project)
            generator.generate_wiring_table_sheet(self)
            self.update_sheet_list_ui()
        except Exception as e:
            tk.messagebox.showerror("Error", f"Error generando Tabla de Cableado: {str(e)}")

    def update_wiring_table_sheet(self):
        """Actualiza la hoja de Tabla de Cableado existente."""
        self.insert_wiring_table_sheet()

    def move_sheet_ui(self, index, direction):
        """UI para mover hojas"""
        if self.project.move_sheet(index, direction):
            # Si la hoja movida era la activa, o la activa se desplazó,
            # switch_to_sheet ya maneja la carga, pero update_sheet_list_ui actualizará la selección visual
            self.update_sheet_list_ui()

            # Asegurar que se muestre la hoja correcta si cambiamos de activa
            # (Aunque move_sheet ya actualiza active_sheet_index, necesitamos refrescar si cambió)
            # No es estrictamente necesario recargar el canvas si solo cambiamos el orden en la lista,
            # a menos que el índice activo haya cambiado "lógicamente" (que ya lo hace move_sheet).

    def rename_sheet_ui(self, index):
        """UI para renombrar hoja"""
        sheet = self.project.sheets[index]
        new_name = tk.simpledialog.askstring("Renombrar Hoja", "Nuevo nombre:", initialvalue=sheet.name, parent=self.root)
        if new_name and new_name.strip():
            sheet.name = new_name.strip()
            self.update_sheet_list_ui()
            self.update_status_bar() # Actualizar nombre en barra inferior

    def rename_project_ui(self):
        """UI para renombrar el proyecto completo"""
        new_name = tk.simpledialog.askstring("Renombrar Proyecto", "Nuevo nombre del proyecto:", initialvalue=self.project.name, parent=self.root)
        if new_name:
            self.project.name = new_name

            # Sincronizar con Configuración PDF
            if "pdf_config" not in self.config:
                self.config["pdf_config"] = {}
            self.config["pdf_config"]["proyecto"] = new_name
            save_config(self.config)

            self.update_sheet_list_ui()
            if hasattr(self, 'set_status'):
                self.set_status(f"✎ Proyecto renombrado a: {new_name}", "blue")
            self.update_status_bar() # Actualizar nombre en barra inferior

    def delete_sheet_ui(self, index):
        """UI para eliminar hoja"""
        # Verificar si es la única hoja
        if len(self.project.sheets) <= 1:
            tk.messagebox.showwarning("Advertencia", "No se puede eliminar la única hoja del proyecto.")
            return

        sheet = self.project.sheets[index]
        if not tk.messagebox.askyesno("Confirmar", f"¿Eliminar permanentemente la hoja '{sheet.name}'?"):
            return

        # Solo cambiar de hoja si la que eliminamos es la ACTIVA
        if index == self.project.active_sheet_index:
            # Determinar a qué hoja cambiar (preferiblemente la anterior, o la 1 si borramos la 0)
            new_active_index = 1 if index == 0 else index - 1
            self.switch_to_sheet(new_active_index)
            # Ahora podemos eliminar la hoja original de forma segura
            self.project.remove_sheet(index)
        else:
            # Si borramos una hoja que no es la activa, simplemente la removemos.
            # Project.remove_sheet se encarga de ajustar active_sheet_index si es necesario.
            self.project.remove_sheet(index)

        self.update_sheet_list_ui()

    def parse_dash_pattern(self, dash_str):
        """Convierte string de dash pattern a tuple de forma segura - delegado al módulo"""
        return AppConstants.DASH_PATTERNS.get(dash_str, "")

    def update_all_existing_lines(self):
        """Actualiza todas las líneas existentes para usar la configuración actual"""
        current_color = self.current_line_color.get()
        current_width = self.current_line_width.get()
        current_dash = self.parse_dash_pattern(self.current_line_dash.get())

        for conn in self.connections:
            for line_id in conn.line_ids:
                # Solo actualizar si no está seleccionada (roja) o destacada (azul)
                if not EventUtils.should_ignore_line(self.canvas, line_id):
                    # Adaptar color para modo oscuro
                    display_color = adapt_color_for_display(current_color, self.canvas.cget("bg"))
                    self.canvas.itemconfig(line_id, fill=display_color, width=current_width, dash=current_dash)

    def show_component_selector(self, category):
        selector_window = tk.Toplevel(self.root)
        selector_window.title(f"Seleccionar {category}")
        selector_window.geometry("300x400")
        selector_window.transient(self.root)
        selector_window.grab_set()

        folder_path = Path(self.config["svg_path"]) / category.lower()
        folder_path.mkdir(parents=True, exist_ok=True)
        svg_files = [f.name for f in folder_path.glob("*.svg")]

        canvas = tk.Canvas(selector_window, bg="#ffffff")
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(selector_window, orient=tk.VERTICAL, command=canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scrollbar.set)

        frame = tk.Frame(canvas, bg="#ffffff")
        canvas.create_window((0, 0), window=frame, anchor="nw")

        # SCROLL CON RUEDA DEL MOUSE PARA CHECKBUTTONS
        def _on_mousewheel(event):
            # Scroll hacia arriba si delta es positivo, abajo si es negativo
            delta = event.delta
            if delta > 0:
                canvas.yview_scroll(-1, "units")
            else:
                canvas.yview_scroll(1, "units")

        def _on_mousewheel_linux(event):
            # Para Linux: Button-4 es scroll up, Button-5 es scroll down
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")

        def _bind_to_mousewheel(event):
            # Bind en todos los elementos de la ventana para capturar wheel events
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_mousewheel_linux)
            canvas.bind_all("<Button-5>", _on_mousewheel_linux)
            # También en el frame para asegurar captura
            frame.bind_all("<MouseWheel>", _on_mousewheel)
            frame.bind_all("<Button-4>", _on_mousewheel_linux)
            frame.bind_all("<Button-5>", _on_mousewheel_linux)

        def _unbind_from_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")
            frame.unbind_all("<MouseWheel>")
            frame.unbind_all("<Button-4>")
            frame.unbind_all("<Button-5>")

        # Bind events cuando el mouse entra/sale de la ventana
        selector_window.bind("<Enter>", _bind_to_mousewheel)
        selector_window.bind("<Leave>", _unbind_from_mousewheel)
        canvas.bind("<Enter>", lambda e: canvas.focus_set())  # Dar focus al canvas

        pending_changes = {}

        checks = {}
        for svg_file in svg_files:
            # Verificar si la categoría existe en la configuración
            if category in self.config["components"]:
                current_svgs = [c["svg"] for c in self.config["components"][category]]
            else:
                current_svgs = []
                self.config["components"][category] = []
            var = tk.BooleanVar(value=svg_file in current_svgs)
            chk = tk.Checkbutton(
                frame, text=svg_file.replace(".svg", ""), variable=var, bg="#ffffff", font=(AppConstants.UI_FONT_FAMILY, 8),
                anchor="w", command=lambda s=svg_file, v=var: pending_changes.update({s: v.get()})
            )
            chk.pack(fill=tk.X, padx=5, pady=2)
            checks[svg_file] = var

        frame.update_idletasks()
        canvas.config(scrollregion=canvas.bbox("all"))

        def on_closing():
            if pending_changes:
                for svg_file, state in pending_changes.items():
                    self._apply_component_change(category, svg_file, state)
                # Solo actualizar la toolbar activa una vez
                self.refresh_buttons(category)
                save_config(self.config)
            selector_window.destroy()

        selector_window.protocol("WM_DELETE_WINDOW", on_closing)
        selector_window.bind("<Escape>", lambda e: on_closing())

    def _apply_component_change(self, category, svg_file, state):
        """Aplica cambios de agregar/quitar componentes sin actualizar tiempo real"""
        # Verificar que la categoría exista, si no, crearla
        if category not in self.config["components"]:
            self.config["components"][category] = []

        if state:
            if not any(comp["svg"] == svg_file for comp in self.config["components"][category]):
                # DETECCIÓN AUTOMÁTICA: Usar función helper para consistencia
                real_size = self.get_component_real_size(svg_file, category)
                self.config["components"][category].append({
                    "svg": svg_file,
                    "name": svg_file.replace(".svg", ""),
                    "size": real_size
                })
        else:
            self.config["components"][category] = [
                comp for comp in self.config["components"][category] if comp["svg"] != svg_file
            ]

    def refresh_buttons(self, category, clear_first=True):
        """Refresca los botones de la categoría especificada"""
        # Mapa de categorías a frames
        category_frames = {
            "Motors": self.motors_frame,
            "Protection": self.protection_frame,
            "Connection": self.connection_frame,
            "Drivers": self.drivers_frame,
            "Auxiliares": self.auxiliares_frame,
            "Unifilar": self.unifilar_frame
        }

        if category not in category_frames:
            return

        frame = category_frames[category]

        # Verificar que la categoría exista en la configuración, si no crearla
        if category not in self.config["components"]:
            self.config["components"][category] = []

        # Limpiar widgets existentes si se especifica
        if clear_first:
            for widget in frame.winfo_children():
                widget.destroy()

        for i, comp_data in enumerate(self.config["components"][category]):
            # Verificar que el archivo SVG existe
            svg_path = Path(self.config["svg_path"]) / category.lower() / comp_data["svg"]
            if not svg_path.exists():
                continue

            _icon_size = self._get_ribbon_icon_size()
            photo = self.create_button_image(comp_data["svg"], size=(_icon_size, _icon_size), category=category)
            btn = tk.Button(
                frame, image=photo, width=_icon_size, height=_icon_size, relief=tk.FLAT, bg="#ffffff",
                borderwidth=0, highlightthickness=0,
                command=lambda s=comp_data["svg"]: self.add_component_to_canvas(s, category)
            )
            btn.image = photo

            title = get_svg_title(svg_path)
            if title:
                ToolTip(btn, title, condition_callback=self.tooltips_enabled.get)

            btn.pack(side=tk.LEFT, padx=0, pady=0)
            if i < len(self.config["components"][category]) - 1:
                tk.Frame(frame, width=1, bg="#cccccc").pack(side=tk.LEFT, fill=tk.Y)

        # Botón de añadir
        tk.Button(
            frame, text="➕", width=2, height=4, font=('Arial', 14), relief=tk.FLAT, bg="#ffffff",
            borderwidth=0, highlightthickness=0, command=lambda: self.show_component_selector(category)
        ).pack(side=tk.RIGHT, padx=5, pady=0, fill=tk.Y)

    def get_component_real_size(self, svg_file, category):
        """Método de instancia para detectar tamaño real de componente"""
        return get_component_real_size_static(svg_file, category, self.config["svg_path"])

    def update_all_component_sizes(self):
        """
        FUNCIÓN OPCIONAL: Re-detecta y actualiza los tamaños de todos los
        componentes existentes en la configuración.
        Útil para migrar configuraciones antiguas con tamaños hardcodeados.
        """
        updated_count = 0
        for category in self.config["components"]:
            for comp in self.config["components"][category]:
                old_size = comp["size"]
                new_size = self.get_component_real_size(comp["svg"], category)
                if old_size != new_size:
                    comp["size"] = new_size
                    updated_count += 1

        if updated_count > 0:
            save_config(self.config)
            self.refresh_toolbar()

    def _get_ribbon_icon_size(self):
        """Tamaño en píxeles del icono SVG de la cinta."""
        try:
            return max(12, min(160, int(self.config.get("ribbon_icon_size", 40))))
        except (TypeError, ValueError):
            return 40

    def set_ribbon_icon_size(self, size):
        """Aplica el tamaño y reconstruye la cinta en vivo."""
        size = max(12, min(160, int(size)))
        self.config["ribbon_icon_size"] = size
        h = size + 20
        if hasattr(self, "notebook"):
            self.notebook.configure(height=h)
        if hasattr(self, "_ribbon_separator"):
            self._ribbon_separator.configure(height=h)
        self.refresh_toolbar()

    def refresh_toolbar(self):
        for frame in [self.motors_frame, self.protection_frame, self.connection_frame, self.drivers_frame, self.auxiliares_frame, self.unifilar_frame]:
            for widget in frame.winfo_children():
                widget.destroy()
        self.refresh_buttons("Motors", clear_first=False)
        self.refresh_buttons("Protection", clear_first=False)
        self.refresh_buttons("Connection", clear_first=False)
        self.refresh_buttons("Drivers", clear_first=False)
        self.refresh_buttons("Auxiliares", clear_first=False)
        self.refresh_buttons("Unifilar", clear_first=False)

    def add_component_to_canvas(self, svg_file, category):
        """Wrapper para agregar componente desde el toolbar - ahora con preview"""

        # Verificar que la categoría existe, si no crearla
        if category not in self.config["components"]:
            self.config["components"][category] = []

        # Buscar datos del componente
        for comp_data in self.config["components"][category]:
            if comp_data["svg"] == svg_file:
                pass

                # Enfoque al canvas para asegurar que los eventos mouse van al lugar correcto
                self.canvas.focus_set()

                # Activar modo preview en lugar de crear directamente
                self.activar_preview_componente(comp_data, category)

                # Componente añadido exitosamente
                break

    def activar_preview_componente(self, comp_config, category):
        """Activa modo preview de componente"""
        try:
            # Deseleccionar cualquier elemento seleccionado antes de iniciar el preview de un nuevo componente
            if hasattr(self, 'event_handler') and self.event_handler:
                try:
                    self.event_handler._clear_selection()
                except Exception:
                    pass

            # Limpiar preview anterior si existe
            self.cancelar_preview_componente()

            # DETECCIÓN AUTOMÁTICA: Obtener tamaño real del SVG
            real_size = self.get_component_real_size(comp_config["svg"], category)

            self.preview_component = Component(
                self.canvas,
                comp_config["svg"],
                comp_config["name"],
                real_size,  # Usar tamaño real detectado
                -1000, -1000,  # Fuera de vista inicialmente
                self.config["svg_path"],
                category,
                self.config,
                is_preview=True # FLAG PARA PREVIEW
            )

            if self.preview_component.canvas_id:
                try:
                    # Intentar aplicar stipple (funciona solo con formas geométricas)
                    self.canvas.itemconfig(self.preview_component.canvas_id, stipple="gray50")
                except tk.TclError:
                    # Si stipple falla (ej: imagen), usar transparencia reducida
                    try:
                        self.canvas.itemconfig(self.preview_component.canvas_id, state="normal")
                        # Para imágenes, crear overlay semi-transparente
                        x1, y1, x2, y2 = self.canvas.bbox(self.preview_component.canvas_id)
                        overlay_id = self.canvas.create_rectangle(
                            x1, y1, x2, y2,
                            fill=adapt_color_for_display("gray", self.canvas.cget("bg")), stipple="gray50",
                            outline="", tags="preview_overlay"
                        )
                        # Asociar overlay para limpieza posterior
                        self.preview_component.overlay_id = overlay_id
                    except Exception:
                        pass

            # Activar modo preview
            self.component_preview_mode = True
            self.preview_component_data = comp_config
            self.preview_category = category

        except Exception:
            self.cancelar_preview_componente()

    def _calcular_alineacion_por_proximidad(self, componente, base_x, base_y):
        """
        Calcula el desfase (dx, dy) que mejor alinea un componente con las conexiones
        cercanas, maximizando cuántos de sus bornes quedan sobre una línea.

        A diferencia de alinear solo al primer punto detectado, evalúa todos los
        candidatos posibles y elige el que conecta MÁS bornes (y, en empate, el de
        menor desplazamiento). Así, si un componente de 3 fases se suelta con un
        desfase de un paso, se engancha a la fase correcta y no deja la tercera sin
        conectar.
        """
        try:
            orig_x, orig_y = componente.x, componente.y
            limite = max(componente.size[0], componente.size[1]) + 20

            componente.x, componente.y = base_x, base_y
            pts_base = componente.get_connection_points_global()

            xs = [p[0] for p in pts_base]
            ys = [p[1] for p in pts_base]
            min_x, max_x = min(xs) - limite, max(xs) + limite
            min_y, max_y = min(ys) - limite, max(ys) + limite

            # Candidatos: llevar cada borne hasta cada segmento ortogonal cercano
            candidatos = set()
            eps_axis = 2.0
            for conexion in self.connections:
                for (x1, y1), (x2, y2) in getattr(conexion, 'segments', []):
                    dy = abs(y2 - y1)
                    dx = abs(x2 - x1)
                    es_vertical = dx <= eps_axis and dy > eps_axis
                    es_horizontal = dy <= eps_axis and dx > eps_axis
                    if not es_vertical and not es_horizontal:
                        if dx <= eps_axis and dy <= eps_axis:
                            es_vertical = True
                        else:
                            continue
                    if es_vertical:  # Segmento (casi) vertical
                        sy0, sy1 = min(y1, y2), max(y1, y2)
                        if sy1 < min_y - 2 or sy0 > max_y + 2:
                            continue
                        for px, py, punto in pts_base:
                            if punto.connected:
                                continue
                            if not (sy0 - 2 <= py <= sy1 + 2):
                                continue
                            if dy > 1e-9:
                                t = (py - y1) / (y2 - y1)
                                if not (0.0 <= t <= 1.0):
                                    continue
                            x_seg = x1 + ((py - y1) / (y2 - y1)) * (x2 - x1) if dy > 1e-9 else x1
                            if abs(px - x_seg) <= limite:
                                candidatos.add((round(x_seg - px, 3), 0.0))
                    else:  # Segmento (casi) horizontal
                        sx0, sx1 = min(x1, x2), max(x1, x2)
                        if sx1 < min_x - 2 or sx0 > max_x + 2:
                            continue
                        for px, py, punto in pts_base:
                            if punto.connected:
                                continue
                            if not (sx0 - 2 <= px <= sx1 + 2):
                                continue
                            if dx > 1e-9:
                                t = (px - x1) / (x2 - x1)
                                if not (0.0 <= t <= 1.0):
                                    continue
                            y_seg = y1 + ((px - x1) / (x2 - x1)) * (y2 - y1) if dx > 1e-9 else y1
                            if abs(py - y_seg) <= limite:
                                candidatos.add((0.0, round(y_seg - py, 3)))

            if not candidatos:
                return (0.0, 0.0)

            # Elegir el candidato que deja MÁS bornes sobre alguna línea
            mejor_score = None
            mejor = (0.0, 0.0)
            for dx, dy in candidatos:
                componente.x, componente.y = base_x + dx, base_y + dy
                total = 0
                for conexion in self.connections:
                    try:
                        puntos = self.detectar_auto_conexion_componente(componente, conexion)
                    except Exception:
                        puntos = None
                    if puntos:
                        total += len(puntos)
                score = (total, -(abs(dx) + abs(dy)))
                if mejor_score is None or score > mejor_score:
                    mejor_score = score
                    mejor = (dx, dy)
            return mejor
        except Exception:
            return (0.0, 0.0)
        finally:
            try:
                componente.x, componente.y = orig_x, orig_y
            except Exception:
                pass

    def mover_preview_componente(self, x, y):
        """Mueve el preview del componente siguiendo el cursor"""
        if self.component_preview_mode and self.preview_component:
            try:
                # x, y ya están en coordenadas del mundo

                # Calcular nueva posición centrada en cursor
                size_x, size_y = self.preview_component.size
                new_x = x - (size_x / 2) / self.canvas.zoom_level
                new_y = y - (size_y / 2) / self.canvas.zoom_level

                current_x, current_y = self.preview_component.x, self.preview_component.y
                dx = new_x - current_x
                dy = new_y - current_y
                self.preview_component.move(dx, dy)

                # OPCIÓN 1: Calcular dirección del movimiento del mouse
                # Almacenar la dirección del mouse para la priorización
                if not hasattr(self, 'mouse_position_prev'):
                    self.mouse_position_prev = (x, y)

                mouse_prev_x, mouse_prev_y = self.mouse_position_prev
                mouse_dx = x - mouse_prev_x
                mouse_dy = y - mouse_prev_y
                self.mouse_position_prev = (x, y)

                # Normalizar dirección del mouse (evitar micro-movimientos)
                if abs(mouse_dx) < 3 and abs(mouse_dy) < 3:
                    mouse_direction = (0, 0)  # Sin dirección clara
                else:
                    pass
                    # Simplificar a dirección cardinal dominante
                    if abs(mouse_dx) > abs(mouse_dy):
                        mouse_direction = (1 if mouse_dx > 0 else -1, 0)
                    else:
                        pass
                        mouse_direction = (0, 1 if mouse_dy > 0 else -1)

                # SNAP MAGNÉTICO POR PROXIMIDAD: alinear el preview a las líneas cercanas
                # para que las líneas verdes muestren TODAS las conexiones que se crearán.
                if hasattr(self, 'proximity_preview_enabled') and self.proximity_preview_enabled.get():
                    adx, ady = self._calcular_alineacion_por_proximidad(
                        self.preview_component, self.preview_component.x, self.preview_component.y)
                    if adx or ady:
                        self.preview_component.move(adx, ady)

                # PREVIEW DE PROXIMIDAD: Mostrar líneas verdes (independiente de auto)
                if hasattr(self, 'proximity_preview_enabled') and self.proximity_preview_enabled.get():
                    self.limpiar_preview_autoconexion()

                    # Buscar conexiones cercanas para mostrar preview
                    for conexion in self.connections:
                        try:
                            puntos_interseccion = self.detectar_auto_conexion_componente(self.preview_component, conexion)
                            if puntos_interseccion:
                                self.mostrar_preview_autoconexion(self.preview_component, conexion, puntos_interseccion)
                                # No break: mostrar preview para TODAS las líneas detectadas
                        except Exception as e:
                            pass  # Ignorar errores durante el preview

                # PREVIEW DE CONEXIONES ORTOGONALES: Líneas rojas (independiente de proximidad)
                if hasattr(self, 'auto_conexion_enabled') and self.auto_conexion_enabled.get():
                    # PROTECCIÓN: Evitar que fase.svg use el sistema de preview de conexiones
                    svg_file = self.preview_component_data.get("svg_file", self.preview_component_data.get("svg", ""))
                    if svg_file != "fase.svg":
                        self.mostrar_preview_conexiones_ortogonales(self.preview_component, mouse_direction)

            except Exception as e:

                pass

    def rotate_preview_component(self, angle):
        """Rota el componente que está actualmente en preview"""
        if self.component_preview_mode and self.preview_component:
            try:
                # Rotar el componente preview
                self.preview_component.rotate(angle)
                self.set_status(f"🔄 Vista previa rotada {angle}°", "blue")

                if hasattr(self, 'mouse_x') and hasattr(self, 'mouse_y'):
                    # self.mouse_x/mouse_y guardan coordenadas de PANTALLA (event.x),
                    # pero mover_preview_componente espera coordenadas del MUNDO.
                    # Sin esta conversión, con la vista desplazada el preview se
                    # colocaba a la distancia exacta del pan.
                    _ev = type('MouseEvent', (), {'x': self.mouse_x, 'y': self.mouse_y})()
                    _wx, _wy = event_to_canvas_coords(_ev, self.canvas)
                    self.mover_preview_componente(_wx, _wy)
            except Exception as e:
                pass

    def place_component_at(self, x, y):
        """Coloca el componente preview en las coordenadas especificadas"""
        if self.component_preview_mode and self.preview_component:
            comp_real = self.finalizar_preview_componente(x, y)
            if comp_real:
                # ABRIR AUTOMÁTICAMENTE LA VENTANA DE EDICIÓN DE ETIQUETA (FUERA del try/catch)
                self._abrir_editor_etiqueta_seguro(comp_real)

    def finalizar_preview_componente(self, x, y, ejecutar_autoconexion=True):
        """Convierte el preview en componente real

        Args:
            x, y: Coordenadas del mundo donde colocar el componente
            ejecutar_autoconexion: Si False, no ejecuta auto-conexión (útil para empalmes)
        """
        if self.component_preview_mode and self.preview_component:
            try:
                # x, y ya están en coordenadas del mundo

                # Limpiar las líneas naranjas de preview (temporales)
                self.limpiar_preview_conexiones_ortogonales()

                size_x, size_y = self.preview_component.size
                final_x = x - (size_x / 2) / self.canvas.zoom_level
                final_y = y - (size_y / 2) / self.canvas.zoom_level

                # SNAP TO GRID: Ajustar al centro de celda más cercana si está habilitado
                final_x, final_y = self.snap_to_grid(final_x, final_y)

                # ALINEACIÓN POR PROXIMIDAD: Ajustar posición para que TODOS los bornes
                # coincidan con las líneas cercanas (no solo el primero detectado).
                if ejecutar_autoconexion and hasattr(self, 'proximity_preview_enabled') and self.proximity_preview_enabled.get():
                    desfase_x, desfase_y = self._calcular_alineacion_por_proximidad(
                        self.preview_component, final_x, final_y)
                    final_x += desfase_x
                    final_y += desfase_y

                # DETECCIÓN AUTOMÁTICA: Obtener tamaño real del SVG
                real_size = self.get_component_real_size(
                    self.preview_component_data["svg"],
                    self.preview_category
                )

                comp_real = Component(
                    self.canvas,
                    self.preview_component_data["svg"],
                    self.preview_component_data["name"],
                    real_size,  # Usar tamaño real detectado
                    final_x, final_y,
                    self.config["svg_path"],
                    self.preview_category,
                    self.config
                )

                # TRANSFERIR ROTACIÓN: Asegurar que el componente real tenga la misma rotación que el preview
                if hasattr(self.preview_component, 'rotation'):
                    comp_real.rotate(self.preview_component.rotation)

                self.components.append(comp_real)

                # AUTO-CONEXIÓN MAGNÉTICA (líneas verdes): Detectar líneas cercanas (SOLO si proximidad está habilitado)
                if ejecutar_autoconexion and hasattr(self, 'proximity_preview_enabled') and self.proximity_preview_enabled.get():
                    conexiones_snapshot = list(self.connections)  # Snapshot para iterar de forma segura
                    for conexion in conexiones_snapshot:
                        try:
                            puntos_interseccion = self.detectar_auto_conexion_componente(comp_real, conexion)
                            if puntos_interseccion:
                                # Verificar que la conexión todavía existe (puede haber sido eliminada por una auto-conexión anterior)
                                if conexion in self.connections:
                                    self.ejecutar_auto_conexion(comp_real, conexion, puntos_interseccion)
                                    # No break: conectar con TODAS las líneas detectadas
                        except Exception:
                            pass

                self.crear_conexiones_reales_desde_preview(comp_real)

                # AJUSTAR ETIQUETA SEGÚN CONEXIÓN (Herencia de fase)
                self._adjust_label_after_placement(comp_real)

                comp_real.draw_label()

                self.cancelar_preview_componente()

                return comp_real

            except Exception as e:
                self.cancelar_preview_componente()
                return None

        return None

    def _adjust_label_after_placement(self, component):
        """
        Ajusta la etiqueta de un componente de conexión para que coincida con la fase a la que se conecta.
        """
        if not hasattr(component, 'component_type') or component.component_type not in ["conxn", "conxn2"]:
            return

        # Buscar si está conectado a alguna fase (L1, L2, L3, N, PE)
        connected_phase_names = []
        for conn in self.connections:
            other = None
            if conn.start_component == component:
                other = conn.end_component
            elif conn.end_component == component:
                other = conn.start_component

            if other and hasattr(other, 'label_data') and other.label_data:
                name = other.label_data.get('name', '')
                if name in ['L1', 'L2', 'L3', 'N', 'PE']:
                    connected_phase_names.append(name)

        if connected_phase_names:
            # Usar el primer nombre de fase encontrado
            new_name = connected_phase_names[0]
            if hasattr(component, 'label_data'):
                component.label_data['name'] = new_name

    def _abrir_editor_etiqueta_seguro(self, comp_real):
        """Abre editor de etiqueta con manejo de errores"""
        try:
            self.edit_component_label(comp_real)
        except Exception as e:

            pass
    def cancelar_preview_componente(self):
        """Cancela el modo preview y limpia recursos"""
        try:
            if self.preview_component:
                if hasattr(self.preview_component, 'canvas_id') and self.preview_component.canvas_id:
                    self.canvas.delete(self.preview_component.canvas_id)

                if hasattr(self.preview_component, 'point_ids'):
                    for point_id in self.preview_component.point_ids:
                        self.canvas.delete(point_id)

                # Limpiar overlay de transparencia si existe
                if hasattr(self.preview_component, 'overlay_id'):
                    self.canvas.delete(self.preview_component.overlay_id)

                # Limpiar etiqueta del preview si existe
                if hasattr(self.preview_component, 'clear_label'):
                    self.preview_component.clear_label()

                self.preview_component = None

            # Limpiar overlays de preview
            self.canvas.delete("preview_overlay")

            self.limpiar_preview_autoconexion()

            # Limpiar TODAS las líneas de preview (naranjas Y rojas) al cancelar
            self.limpiar_todas_las_lineas_preview()

            # Limpiar variables
            self.component_preview_mode = False
            self.preview_component_data = None
            self.preview_category = None

            self.canvas.config(cursor="")

        except Exception as e:

            # Forzar limpieza
            self.component_preview_mode = False
            self.preview_component = None

    # FORMATO .ECAD Y PDF

    def reset_app_state(self):
        """Reinicializa completamente el estado de la aplicación, limpiando todos los buffers."""
        self.canvas.delete("all")

        # 2. Limpiar listas de elementos
        self.components.clear()
        self.connections.clear()
        self.text_components.clear()

        # Asegurar que las listas internas de líneas y formas también se limpien
        if hasattr(self, 'lines'): self.lines.clear()
        if hasattr(self, 'shapes'): self.shapes.clear()

        if hasattr(self, 'image_components'):
            self.image_components.clear()
        if hasattr(self, 'block_terminals'):
            self.block_terminals.clear()
        # Liberar referencia al PhotoImage del grid
        self._grid_bg_image = None

        self.label_counters = {}
        if hasattr(self, '_grid_tile_cache'):
            self._grid_tile_cache = {}
        if hasattr(self, 'undo_manager'):
            self.undo_manager.clear()

        self.is_dirty = False
        self.first_point = None
        self.selected_component = None

        # 3. Limpiar buffers y caches
        self.label_counters = {}
        # Mantener el cache de grid si existe pero vaciarlo si es necesario
        if hasattr(self, '_grid_tile_cache'):
            self._grid_tile_cache = {}

        # 4. Limpiar historial de Deshacer/Rehacer (BUFFER CRÍTICO)
        if hasattr(self, 'undo_manager'):
            self.undo_manager.clear()

        # 5. Reiniciar estados de selección y temporales
        self.first_point = None
        self.selected_component = None

        # 6. Limpiar gestores específicos
        if hasattr(self, 'shape_manager') and self.shape_manager:
            try:
                self.shape_manager.shapes.clear()
                self.shape_manager.selected_shape = None
            except:
                pass

        if hasattr(self, 'shielding_manager') and self.shielding_manager:
            try:
                self.shielding_manager.shieldings.clear()
                self.shielding_manager.selected_shielding = None
            except:
                pass

        # 7. Re-inicializar crosshair (se borró con delete("all"))
        if hasattr(self, '_init_crosshair'):
            self.crosshair_created = False
            self._init_crosshair()

        # 8. Redibujar elementos base
        self.draw_grid(force=True)
        if hasattr(self, 'update_info_bar'):
            self.update_info_bar()

    def new_canvas(self):
        """Crea un nuevo lienzo limpio"""
        result = ask_save_changes(self.root, "crear un proyecto nuevo")
        if result == "yes" and not self.save_canvas():
            return
        elif result in (None, "cancel"):
            return

        # Un proyecto en marcha debe detenerse antes de vaciar el estado
        self.stop_simulation_if_running("se creó un proyecto nuevo")

        # CENTRALIZADO: Reinicializar todo el estado
        self.reset_app_state()

        # Limpiar/Reiniciar Proyecto multi-hoja
        from models.project_data import Project
        self.project = Project("Nuevo Proyecto")
        self.current_file = None

        # Un proyecto nuevo debe pedir su nombre para el cajetín PDF, sin
        # arrastrar el nombre del proyecto anterior.
        self.config.setdefault("pdf_config", {})["proyecto"] = ""

        self.update_sheet_list_ui()
        self.config_pdf()
        self.set_status("🆕 Nuevo proyecto creado", "green")

    def clear_active_sheet(self):
        """Limpia todos los elementos de la HOJA ACTUAL solamente."""
        if not messagebox.askyesno("Limpiar", "¿Está seguro de que desea limpiar la hoja actual?"):
            return

        self.stop_simulation_if_running("se limpió la hoja")

        # Limpiar estado visual y variables de la hoja actual
        self.canvas.delete("all")
        self.components.clear()
        self.connections.clear()
        self.text_components.clear()

        # Limpiar block terminals: canvas.delete("all") los borra del canvas
        # pero quedan en self.block_terminals -> fantasmas en export PDF si no se limpian.
        if hasattr(self, 'block_terminals'):
            self.block_terminals.clear()
        if hasattr(self, '_selected_block_terminal'):
            self._selected_block_terminal = None

        # REINICIALIZAR BUFFER DE CONTADORES para esta hoja específica
        # (Aunque los contadores sean globales, limpiamos para re-conteo si es necesario)
        self.label_counters = {}
        self.first_point = None
        self.selected_component = None

        self.draw_grid(force=True)

        if hasattr(self, '_init_crosshair'):
            self.crosshair_created = False
            self._init_crosshair()

        self.set_status("Hoja actual limpiada", "green")

    def save_canvas(self):
        """Guarda el canvas actual en formato .ecad"""
        self.stop_simulation_if_running("se guardó el proyecto")
        if self.current_file:
            return self._save_to_file(self.current_file)
        return self.save_canvas_as()

    def save_canvas_as(self):
        """Guardar como - selecciona archivo .ecad"""
        self.stop_simulation_if_running("se guardó el proyecto")
        filename = filedialog.asksaveasfilename(
            title="Guardar circuito",
            defaultextension=".ecad",
            initialdir=self.config.get("work_dir", str(Path.home() / "Documentos" / "Proyectos")),
            filetypes=[("Archivos ECAD", "*.ecad"), ("Todos los archivos", "*.*")],
            parent=self.root,
            confirmoverwrite=False,
        )
        if not filename or not confirm_overwrite(self.root, filename):
            return False
        saved = self._save_to_file(filename)
        if saved:
            self.set_status(f"💾 Guardado como {os.path.basename(filename)}", "green")
        return saved

    def load_canvas(self):
        """Carga un archivo .ecad"""
        self.stop_simulation_if_running("se abrió otro archivo")
        filename = filedialog.askopenfilename(
            title="Abrir circuito",
            initialdir=self.config.get("work_dir", str(Path.home() / "Documentos" / "Proyectos")),
            filetypes=[("Archivos ECAD", "*.ecad"), ("Archivos JSON", "*.json"), ("Todos los archivos", "*.*")],
            parent=self.root
        )
        if filename:
            self._load_from_file(filename)

    # Resto de funciones existentes (sin cambios)
    def change_bg_color(self):
        config_window = tk.Toplevel(self.root)
        config_window.title("Color de fondo")
        config_window.geometry("300x220")
        tk.Frame(config_window).pack(pady=15)
        config_window.transient(self.root)
        config_window.grab_set()

        colors = [
            ("#fff9e6", "Amarillo pálido"),
            ("#e6ffe6", "Verde pálido"),
            ("#ffffff", "Blanco"),
            ("#f0f0f0", "Gris pálido")
        ]

        selected_color = tk.StringVar(value=self.config["canvas_color"])
        for color, name in colors:
            frame = tk.Frame(config_window, padx=0, pady=2)
            frame.pack(fill=tk.X, pady=2)
            tk.Radiobutton(
                frame, bg=color, width=12, height=1, variable=selected_color, value=color,
                indicatoron=False
            ).pack(side=tk.LEFT, padx=5)
            tk.Label(frame, text=name, font=(AppConstants.UI_FONT_FAMILY, 8)).pack(side=tk.LEFT, padx=5)

        def apply_color():
            self.config["canvas_color"] = selected_color.get()
            self.canvas.config(bg=self.config["canvas_color"])
            self.refresh_all_colors()
            save_config(self.config)
            self.set_status(f"🎨 Color de fondo cambiado", "blue")
            config_window.destroy()

        tk.Button(config_window, text="Aceptar", command=apply_color).pack(pady=10)

    def change_grid(self):
                pass

    def show_grid_warning(self):
        """Muestra advertencia cuando se intenta activar el grid"""
        warning_window = tk.Toplevel(self.root)
        warning_window.title("⚠️ Advertencia - Grid en Fase Alfa")

        # Dimensiones de la ventana
        window_width = 500
        window_height = 350

        warning_window.resizable(False, False)
        warning_window.transient(self.root)
        warning_window.grab_set()

        # Centrar ventana
        warning_window.update_idletasks()
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_width = self.root.winfo_width()
        root_height = self.root.winfo_height()

        # Calcular posición para centrar respecto a la ventana padre
        x = root_x + (root_width - window_width) // 2
        y = root_y + (root_height - window_height) // 2
        warning_window.geometry(f"{window_width}x{window_height}+{x}+{y}")

        main_frame = tk.Frame(warning_window, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Icono de advertencia (usando texto)
        warning_label = tk.Label(main_frame, text="⚠️", font=("Arial", 24))
        warning_label.pack(pady=(0, 10))

        # Título
        title_label = tk.Label(main_frame, text="ADVERTENCIA - Grid en Fase Alfa",
                              font=(AppConstants.UI_FONT_FAMILY, 12, "bold"), fg="red")
        title_label.pack(pady=(0, 15))

        # Mensaje de advertencia
        warning_text = """El sistema de Grid NO debe activarse porque:

• El código actual NO está optimizado
• Provocará LENTITUD significativa al sistema
• Está en FASE ALFA de desarrollo
• En el futuro se trabajará en una solución optimizada

¿Desea continuar y activar el Grid?"""

        message_label = tk.Label(main_frame, text=warning_text,
                                font=(AppConstants.UI_FONT_FAMILY, 10), justify=tk.LEFT, wraplength=460)
        message_label.pack(pady=(0, 20))

        # Variables para resultado
        result = {'continue': False}

        def on_continue():
            result['continue'] = True
            warning_window.destroy()

        def on_cancel():
            result['continue'] = False
            warning_window.destroy()

        # Botones
        button_frame = tk.Frame(main_frame)
        button_frame.pack(pady=10)

        continue_btn = tk.Button(button_frame, text="Continuar y Activar",
                                command=on_continue, bg="orange", fg="white",
                                font=("Arial", 10, "bold"))
        continue_btn.pack(side=tk.LEFT, padx=5)

        cancel_btn = tk.Button(button_frame, text="Cancelar",
                              command=on_cancel, bg="gray", fg="white",
                              font=(AppConstants.UI_FONT_FAMILY, 10))
        cancel_btn.pack(side=tk.LEFT, padx=5)

        # Esperar a que se cierre la ventana
        warning_window.wait_window()

        return result['continue']

    def show_config(self):
        config_window = tk.Toplevel(self.root)
        config_window.title("Configuración")
        config_window.geometry("500x620")
        config_window.resizable(False, False)
        config_window.transient(self.root)
        config_window.grab_set()

        temp_config = self.config.copy()
        main_frame = tk.Frame(config_window, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # PESTAÑAS
        nb = ttk.Notebook(main_frame)
        nb.pack(fill=tk.BOTH, expand=True)

        basico_frame = tk.Frame(nb, padx=15, pady=10)
        avanzado_frame = tk.Frame(nb, padx=15, pady=10)
        nb.add(basico_frame, text="Básico")
        nb.add(avanzado_frame, text="Avanzado")

        # PESTAÑA BÁSICO
        config_path_label = tk.Label(basico_frame, text=f"Configuración guardada en: {CONFIG_FILE}",
                                     font=(AppConstants.UI_FONT_FAMILY, 8), fg="gray")
        config_path_label.pack(anchor="w", pady=(0, 4))

        tk.Label(basico_frame, text="Color del lienzo:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 2))
        color_frame = tk.Frame(basico_frame)
        color_frame.pack(anchor="w", fill="x", pady=(0, 10))

        colors = [
            ("#F7B500", "Amarillo"),
            ("#e6ffe6", "Verde pálido"),
            ("#F5BCBC", "Naranja pálido"),
            ("#d0b6e0", "Violeta"),
            ("#0f0f23", "Modo Oscuro")
        ]

        selected_color = tk.StringVar(value=temp_config["canvas_color"])
        for color, name in colors:
            frame = tk.Frame(color_frame, padx=0, pady=2)
            frame.pack(side=tk.LEFT)
            tk.Radiobutton(
                frame, bg=color, width=10, height=3,
                variable=selected_color, value=color,
                indicatoron=False
            ).pack()
            tk.Label(frame, text=name, font=(AppConstants.UI_FONT_FAMILY, 8)).pack()

        tk.Label(basico_frame, text="Tamaño iconos cinta:",
                 font=("Arial", 10, "bold")).pack(anchor="w", pady=(12, 2))
        ribbon_frame = tk.Frame(basico_frame)
        ribbon_frame.pack(anchor="w", fill="x", pady=(0, 4))

        ribbon_spinbox = tk.Spinbox(
            ribbon_frame, from_=12, to=160, increment=1, width=8,
            font=(AppConstants.UI_FONT_FAMILY, 10),
            command=lambda: self.set_ribbon_icon_size(ribbon_spinbox.get())
        )
        ribbon_spinbox.delete(0, tk.END)
        ribbon_spinbox.insert(0, self._get_ribbon_icon_size())
        ribbon_spinbox.pack(side=tk.LEFT)
        ribbon_spinbox.bind("<Return>", lambda e: self.set_ribbon_icon_size(ribbon_spinbox.get()))
        ribbon_spinbox.bind("<FocusOut>", lambda e: self.set_ribbon_icon_size(ribbon_spinbox.get()))
        tk.Label(ribbon_frame, text="px  (se aplica al instante)",
                 font=(AppConstants.UI_FONT_FAMILY, 9), fg="gray").pack(side=tk.LEFT, padx=5)

        tk.Label(basico_frame, text="Tamaño del grid:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(5, 5))
        grid_frame = tk.Frame(basico_frame)
        grid_frame.pack(anchor="w", fill="x", pady=(0, 10))

        grid_spinbox = tk.Spinbox(grid_frame, from_=0, to=99, width=10,
                                 font=(AppConstants.UI_FONT_FAMILY, 10))
        grid_spinbox.delete(0, tk.END)
        grid_spinbox.insert(0, temp_config["grid_size"])
        grid_spinbox.pack(side=tk.LEFT)
        tk.Label(grid_frame, text="píxeles", font=(AppConstants.UI_FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=5)

        grid_visible = tk.BooleanVar(value=temp_config.get("grid_visible", True))
        grid_check = tk.Checkbutton(grid_frame, text="Grid ON/OFF", variable=grid_visible,
                                   font=(AppConstants.UI_FONT_FAMILY, 9))
        grid_check.pack(side=tk.LEFT, padx=(20, 0))

        tk.Label(basico_frame, text="Ruta de Carpeta de Trabajo:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(5, 5))
        work_dir_frame = tk.Frame(basico_frame)
        work_dir_frame.pack(anchor="w", fill="x", pady=(0, 5))

        work_dir_entry = tk.Entry(work_dir_frame, width=35, font=(AppConstants.UI_FONT_FAMILY, 9))
        work_dir_entry.insert(0, temp_config.get("work_dir", str(Path.home() / "Documentos" / "Proyectos")))
        work_dir_entry.pack(side=tk.LEFT, padx=(0, 5))

        def browse_work_dir():
            config_window.lift()
            config_window.focus_force()
            path = filedialog.askdirectory(title="Seleccionar carpeta de trabajo", parent=config_window)
            if path:
                work_dir_entry.delete(0, tk.END)
                work_dir_entry.insert(0, path)
            config_window.lift()
            config_window.focus_force()

        tk.Button(work_dir_frame, text="Examinar...", command=browse_work_dir).pack(side=tk.LEFT)

        tk.Label(basico_frame, text="Ruta de SVG:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(5, 5))
        svg_frame = tk.Frame(basico_frame)
        svg_frame.pack(anchor="w", fill="x", pady=(0, 5))

        svg_entry = tk.Entry(svg_frame, width=35, font=(AppConstants.UI_FONT_FAMILY, 9))
        svg_entry.insert(0, temp_config["svg_path"])
        svg_entry.pack(side=tk.LEFT, padx=(0, 5))

        def browse_svg():
            # Poner ventana al frente
            config_window.lift()
            config_window.focus_force()
            path = filedialog.askdirectory(title="Seleccionar carpeta de SVGs", parent=config_window)
            if path:
                svg_entry.delete(0, tk.END)
                svg_entry.insert(0, path)
            config_window.lift()
            config_window.focus_force()

        tk.Button(svg_frame, text="Examinar...", command=browse_svg).pack(side=tk.LEFT)

        tk.Label(basico_frame, text="Configuración de Medidas Genéricas de Componentes:",
                 font=("Arial", 10, "bold")).pack(anchor="w", pady=(10, 2))

        medidas_path = get_app_dir() / "config" / "medidas.json"

        medidas_frame = tk.Frame(basico_frame)
        medidas_frame.pack(anchor="w", fill="x", pady=(0, 5))

        medidas_entry = tk.Entry(medidas_frame, width=55, font=(AppConstants.UI_FONT_FAMILY, 8),
                                bg="#f0f0f0")
        medidas_entry.insert(0, str(medidas_path))
        medidas_entry.config(state='readonly')
        medidas_entry.pack(side=tk.LEFT, fill="x", expand=True)

        tk.Label(basico_frame, text="💡 Nota: Puedes editar este archivo con un editor de texto externo si lo deseas.",
                 font=(AppConstants.UI_FONT_FAMILY, 8), fg="blue").pack(anchor="w", pady=(0, 10))

        # PESTAÑA AVANZADO
        # Sección de funciones avanzadas
        tk.Label(avanzado_frame, text="Funciones avanzadas:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(5, 5))
        advanced_frame = tk.Frame(avanzado_frame)
        advanced_frame.pack(anchor="w", fill="x", pady=(0, 5))

        # Sección de funciones avanzadas reordenada
        auto_conexion_enabled = tk.BooleanVar(value=temp_config.get("auto_conexion_enabled", True))
        auto_conexion_check = tk.Checkbutton(advanced_frame,
                                           text="Deteccion Automatica de P. Conexion",
                                           variable=auto_conexion_enabled,
                                           font=(AppConstants.UI_FONT_FAMILY, 9))
        auto_conexion_check.pack(anchor="w")

        crosshair_enabled = tk.BooleanVar(value=temp_config.get("crosshair_enabled", True))
        crosshair_check = tk.Checkbutton(advanced_frame,
                                        text="Crosshair ON/OFF",
                                        variable=crosshair_enabled,
                                        font=(AppConstants.UI_FONT_FAMILY, 9))
        crosshair_check.pack(anchor="w")

        tooltips_enabled = tk.BooleanVar(value=temp_config.get("tooltips_enabled", True))
        tooltips_check = tk.Checkbutton(advanced_frame,
                                       text="ToolTip ON/OFF",
                                       variable=tooltips_enabled,
                                       font=(AppConstants.UI_FONT_FAMILY, 9))
        tooltips_check.pack(anchor="w")

        invertir_deteccion = tk.BooleanVar(value=temp_config.get("invertir_deteccion", False))
        invertir_check = tk.Checkbutton(advanced_frame,
                                      text="Invertir Deteccion",
                                      variable=invertir_deteccion,
                                      font=(AppConstants.UI_FONT_FAMILY, 9))
        invertir_check.pack(anchor="w")

        # NUMERACIÓN DE CABLES ON/OFF + TIPO (en la misma línea)
        wire_numbering_types = [
            "Numeración por Bloques de Motor",
            "Numeración por Código de Motor (Estructura de Bloque de Campo)",
            "Numeración Secuencial por Regleta de Bornes",
            "Numeración por Potencial",
        ]
        wire_numbering_enabled = tk.BooleanVar(value=temp_config.get("wire_numbering_enabled", False))
        wire_numbering_type_var = tk.StringVar(
            value=temp_config.get("wire_numbering_type", wire_numbering_types[0])
        )
        wire_numbering_row = tk.Frame(advanced_frame)
        wire_numbering_row.pack(anchor="w")
        wire_numbering_check = tk.Checkbutton(wire_numbering_row,
                                            text="Numeracion de cables ON/OFF",
                                            variable=wire_numbering_enabled,
                                            font=(AppConstants.UI_FONT_FAMILY, 9))
        wire_numbering_check.pack(side="left")
        wire_numbering_type_combo = ttk.Combobox(
            wire_numbering_row,
            textvariable=wire_numbering_type_var,
            values=wire_numbering_types,
            state="readonly",
            width=38,
            font=(AppConstants.UI_FONT_FAMILY, 9)
        )
        wire_numbering_type_combo.pack(side="left", padx=(6, 0))

        enable_move_connections = tk.BooleanVar(value=temp_config.get("enable_move_connections", True))
        enable_move_check = tk.Checkbutton(advanced_frame,
                                          text="Habilitar mover lineas de conexion",
                                          variable=enable_move_connections,
                                          font=(AppConstants.UI_FONT_FAMILY, 9))
        enable_move_check.pack(anchor="w")

        # COLORES DE CABLES (reflejados en el apantallamiento) - SECCIÓN SEPARADA en avanzado_frame
        color_label = tk.Label(
            avanzado_frame,
            text="Codigo colores de Cables:",
            font=("Arial", 9, "bold"))
        color_label.pack(anchor="w", pady=(10, 21))
        cable_color_frame = tk.Frame(avanzado_frame)
        cable_color_frame.pack(anchor="w", fill="x", pady=(0, 8))

        cable_color_options = [
            "BK", "BN", "RD", "BU", "GY", "GNYE", "OG", "PK", "VT", "YE", "WH",
        ]
        color_code_to_hex = {
            "BK": "#000000", "BN": "#8B4513", "RD": "#CC0000", "BU": "#1565C0",
            "GY": "#808080", "GNYE": "#00AA00", "OG": "#FF8C00", "PK": "#FF69B4",
            "VT": "#800080", "YE": "#FDD835", "WH": "#FFFFFF",
        }
        current_color_map = dict(DEFAULT_CONFIG["cable_color_map"])
        current_color_map.update(temp_config.get("cable_color_map", {}))
        self._cable_color_vars = {}
        cable_color_previews = {}

        def refresh_cable_color_preview(key):
            code = self._cable_color_vars[key].get()
            hexc = color_code_to_hex.get(code, "#000000")
            cable_color_previews[key].config(
                text=code, bg=hexc,
                fg="#FFFFFF" if hexc not in ("#FFFFFF", "#FDD835") else "#000000"
            )

        for ckey, ckey_label in [("L1", "L1"), ("L2", "L2"), ("L3", "L3"),
                                 ("N", "N"), ("PE", "PE")]:
            row = tk.Frame(cable_color_frame)
            row.pack(anchor="w", pady=1, padx=(30, 0))
            tk.Label(row, text=f"{ckey_label}:",
                     font=(AppConstants.UI_FONT_FAMILY, 9), width=4, anchor="w").pack(side="left")
            var = tk.StringVar(value=current_color_map.get(ckey, ""))
            self._cable_color_vars[ckey] = var
            combo = ttk.Combobox(row, textvariable=var, values=cable_color_options,
                                 state="readonly", width=6,
                                 font=(AppConstants.UI_FONT_FAMILY, 9))
            combo.pack(side="left", padx=(2, 6))
            combo.bind("<<ComboboxSelected>>",
                       lambda _e, k=ckey: refresh_cable_color_preview(k))
            preview = tk.Label(row, width=5, text=var.get(),
                               bg=color_code_to_hex.get(var.get(), "#000000"),
                               fg="#FFFFFF", font=(AppConstants.UI_FONT_FAMILY, 9, "bold"))
            preview.pack(side="left")
            cable_color_previews[ckey] = preview

        # Snap to Grid (oculto/deshabilitado como antes)
        snap_to_grid_enabled = tk.BooleanVar(value=temp_config.get("snap_to_grid_enabled", False))
        # SECCIÓN: Funciones Alinear
        tk.Label(avanzado_frame, text="Funciones Alinear:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(10, 5))
        align_frame = tk.Frame(avanzado_frame)
        align_frame.pack(anchor="w", fill="x", pady=(0, 5))

        align_both_var = tk.BooleanVar(value=temp_config.get("align_both_enabled", False))
        align_points_var = tk.BooleanVar(value=temp_config.get("align_points_enabled", False))
        align_components_var = tk.BooleanVar(value=temp_config.get("align_components_enabled", False))

        align_both_check = tk.Checkbutton(align_frame,
                                         text="Alinear y/o distribuir puntos de conexión y componentes",
                                         variable=align_both_var,
                                         font=(AppConstants.UI_FONT_FAMILY, 9))
        align_both_check.pack(anchor="w")

        align_points_check = tk.Checkbutton(align_frame,
                                           text="Activar botónes de Alineación y Rotación en Gabinete 2D",
                                           variable=align_points_var,
                                           font=(AppConstants.UI_FONT_FAMILY, 9))
        align_points_check.pack(anchor="w")

        # Ajuste de fila para el frame de botones (fuera del notebook)
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(10, 0))

        def apply_config():
            # Verificar si se está intentando activar el grid visible
            new_grid_visible = grid_visible.get()
            if new_grid_visible and not self.config.get("grid_visible", False):
                # Mostrar advertencia antes de activar el grid
                if not self.show_grid_warning():
                    return  # Cancelar si el usuario no acepta

            # Verificar si se está intentando activar snap to grid
            new_snap_enabled = snap_to_grid_enabled.get()
            if new_snap_enabled and not self.config.get("snap_to_grid_enabled", False):
                # Mostrar advertencia antes de activar snap to grid
                if not self.show_grid_warning():
                    return  # Cancelar si el usuario no acepta

            self.config["canvas_color"] = selected_color.get()
            self.config["grid_size"] = int(grid_spinbox.get())
            try:
                self.config["ribbon_icon_size"] = max(12, min(160, int(ribbon_spinbox.get())))
            except ValueError:
                pass
            self.config["grid_visible"] = grid_visible.get()
            self.config["work_dir"] = work_dir_entry.get()
            self.config["svg_path"] = svg_entry.get()
            self.config["auto_conexion_enabled"] = auto_conexion_enabled.get()
            self.config["invertir_deteccion"] = invertir_deteccion.get()  # Nuevo: Invertir detección
            self.config["snap_to_grid_enabled"] = snap_to_grid_enabled.get()  # Nuevo: Snap to Grid
            self.config["crosshair_enabled"] = crosshair_enabled.get()  # Crosshair
            self.config["align_both_enabled"] = align_both_var.get()  # Alinear ambos
            self.config["align_points_enabled"] = align_points_var.get()  # Alinear puntos
            self.config["align_components_enabled"] = align_components_var.get()  # Alinear componentes
            self.config["tooltips_enabled"] = tooltips_enabled.get()  # ToolTips
            self.config["wire_numbering_enabled"] = wire_numbering_enabled.get()  # Numeración de cables
            self.config["wire_numbering_type"] = wire_numbering_type_var.get()  # Tipo de numeración
            if hasattr(self, '_cable_color_vars') and self._cable_color_vars:
                saved = self.config.setdefault("cable_color_map", {})
                for ckey, var in self._cable_color_vars.items():
                    saved[ckey] = var.get() or DEFAULT_CONFIG["cable_color_map"].get(ckey, "")
                self.config["cable_color_map"] = saved
            self.config["enable_move_connections"] = enable_move_connections.get() # Mover líneas

            self.auto_conexion_enabled.set(auto_conexion_enabled.get())  # Actualizar instancia
            self.invertir_deteccion.set(invertir_deteccion.get())  # Actualizar instancia invertir
            self.snap_to_grid_enabled.set(snap_to_grid_enabled.get())  # Actualizar instancia snap to grid
            self.tooltips_enabled.set(tooltips_enabled.get())  # Actualizar instancia tooltips
            self.wire_numbering_enabled.set(wire_numbering_enabled.get())  # Actualizar instancia numeración
            self.enable_move_connections.set(enable_move_connections.get()) # Actualizar instancia mover líneas
            self.wire_numbering_dirty = True # Marcar para recalcular

            if hasattr(self, '_crosshair_enabled'):
                self._crosshair_enabled = crosshair_enabled.get()

            save_config(self.config)
            # Reconstruir cinta con el tamaño configurado
            self.set_ribbon_icon_size(self.config.get("ribbon_icon_size", 40))
            # Recalcular etiquetas de apantallamientos con los nuevos colores configurados
            if hasattr(self, 'shielding_manager') and self.shielding_manager:
                self.shielding_manager.refresh_all_labels()
            self.canvas.config(bg=self.config["canvas_color"])
            self.refresh_all_colors()
            self.grid_size = self.config["grid_size"]
            # Cambio manual de configuración: forzar redibujo del grid
            self.draw_grid(force=True)

            if hasattr(self, 'update_wire_numbers'):
                self.update_wire_numbers()

            if hasattr(self, 'project'):
                active_sheet = self.project.get_active_sheet()
                if active_sheet:
                    self._update_buttons_for_sheet(active_sheet.name)

            config_window.destroy()
            show_save_success(
                self.root,
                message="La configuración se guardó correctamente.",
            )

        tk.Button(button_frame, text="Aceptar", width=10, command=apply_config).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Cancelar", width=10, command=config_window.destroy).pack(side=tk.LEFT, padx=5)

    def toggle_wire_numbering(self, event=None):
        """Alterna la numeración de cables con la tecla F7"""
        new_state = not self.wire_numbering_enabled.get()
        self.wire_numbering_enabled.set(new_state)

        # Marcar como sucio para recalcular si se activa
        if new_state:
            self.wire_numbering_dirty = True

        self.config["wire_numbering_enabled"] = new_state
        save_config(self.config)

        self.update_wire_numbers()

        # Notificar en la barra de estado
        estado = "ACTIVADA" if new_state else "DESACTIVADA"
        self.set_status(f"🔢 Numeración de cables {estado}", "blue")

    def activate_din_rail_draw(self, event=None):
        """Activa el dibujo de RIEL DIN desde un atajo de teclado y provee feedback visual visualizable al instante"""
        print("Atajo del teclado recibido - Activando dibujo de RIEL DIN")

        # Validación: Solo permitir en la hoja 2D
        try:
            current_sheet = self.project.get_active_sheet()
            if not current_sheet or "2D" not in current_sheet.name.upper():
                self.set_status("⚠️ El Riel DIN solo se puede dibujar en la Hoja de Gabinete 2D", "orange")
                return
        except Exception:
            pass

        if hasattr(self, 'event_handler'):
            self.event_handler.shape_drawing.activate('din_rail')
            self.set_status("🖌️ Riel DIN Activo: Haz clic izquierdo para empezar, desliza horizontalmente, y vuelve a hacer clic", "green")
            # Forzar cursor cruz para indicar interacción
            try: self.canvas.config(cursor="crosshair")
            except: pass
            self._deactivate_button("button_canaleta")
            self._deactivate_button("button_block_t")
            self._activate_button("button_riel_dim")
        else:
            print("❌ ATENCIÓN: Aún no existe event_handler, espera 1 segundo que inicie el lienzo")

    def activate_canaleta_draw(self, event=None):
        """Activa el dibujo de CANALETA ranurada desde un atajo de teclado (Ctrl+F)"""
        print("Atajo del teclado recibido - Activando dibujo de CANALETA")

        # Validación: Solo permitir en la hoja 2D
        try:
            current_sheet = self.project.get_active_sheet()
            if not current_sheet or "2D" not in current_sheet.name.upper():
                self.set_status("⚠️ La Canaleta solo se puede dibujar en la Hoja de Gabinete 2D", "orange")
                return
        except Exception:
            pass

        if hasattr(self, 'event_handler'):
            self.event_handler.shape_drawing.activate('canaleta')
            self.set_status("🖌️ Canaleta Activo: Haz clic izquierdo para empezar, desliza, y vuelve a hacer clic. Ctrl+clic derecho cambia el ancho comercial", "green")
            # Forzar cursor cruz para indicar interacción
            try: self.canvas.config(cursor="crosshair")
            except: pass
            self._deactivate_button("button_riel_dim")
            self._deactivate_button("button_block_t")
            self._activate_button("button_canaleta")
        else:
            print("❌ ATENCIÓN: Aún no existe event_handler, espera 1 segundo que inicie el lienzo")

    def update_wire_numbers(self):
        """
        Actualiza y dibuja las etiquetas de numeración de cables en el canvas.
        """
        if not self.wire_numbering_enabled.get():
            self.canvas.delete("wire_label")
            return

        current_sheet = getattr(self.project, 'get_active_sheet', lambda: None)()
        if current_sheet and current_sheet.name.startswith('Plano Unifilar'):
            return

        # Limpiar etiquetas anteriores (solo si se va a dibujar numeración)
        self.canvas.delete("wire_label")

        # Recalcular numeración solo si la topología ha cambiado (Optimización)
        if getattr(self, 'wire_numbering_dirty', True):
            sheet_idx = getattr(self.project, 'active_sheet_index', 0)
            self.wire_numbering_manager.update_numbering(sheet_idx=sheet_idx)
            self.wire_numbering_dirty = False

        zoom = getattr(self.canvas, 'zoom_level', 1.0)

        for conn in self.connections:
            if not conn.segments:
                continue

            # Si el usuario borró la etiqueta (Delete), no se dibuja
            if getattr(conn, 'wire_label_hidden', False):
                continue

            label = self.wire_numbering_manager.get_label_for_connection(conn)
            # Texto manual (editable con clic derecho) tiene prioridad
            if getattr(conn, 'wire_label_manual', None):
                label = conn.wire_label_manual
            if not label:
                continue

            # Encontrar el segmento más largo para poner la etiqueta
            best_seg = None
            max_len = -1
            for seg in conn.segments:
                (x1, y1), (x2, y2) = seg
                length = math.sqrt((x2-x1)**2 + (y2-y1)**2)
                if length > max_len:
                    max_len = length
                    best_seg = seg

            if best_seg:
                (x1, y1), (x2, y2) = best_seg
                mid_x = (x1 + x2) / 2
                mid_y = (y1 + y2) / 2

                # EVITAR DIBUJAR DENTRO DE APANTALLAMIENTOS (Solapamiento)
                is_inside_shield = False
                if hasattr(self, 'shielding_manager'):
                    for sh in self.shielding_manager.shieldings:
                        # La cápsula del blindaje está centrada en y+10 con h=16 (y+2 a y+18)
                        # Cubrimos un área de exclusión alrededor del blindaje
                        x_min, x_max = min(sh.x1, sh.x2), max(sh.x1, sh.x2)
                        y_min, y_max = sh.y - 15, sh.y + 35
                        if (x_min - 25 <= mid_x <= x_max + 25) and (y_min <= mid_y <= y_max):
                            is_inside_shield = True
                            break

                if is_inside_shield:
                    continue

                # COMPUTAR POSICIÓN DE LA ETIQUETA (barra sobre el cable + texto desplazado)
                # Desplazar el texto ligeramente para que no tape la línea ni la barra
                offset_x = 0
                offset_y = 0
                horizontal = abs(x1 - x2) > abs(y1 - y2)
                if horizontal: # Horizontal
                    offset_y = -12
                else: # Vertical
                    offset_x = 12

                # Ancla de la barra sobre el cable: por defecto el punto medio, o la posición movida
                saved_pos = getattr(conn, 'wire_label_pos', None)
                if saved_pos:
                    bar_x, bar_y = saved_pos
                    # Asegurar que la etiqueta se mantenga sobre el cable al redibujar
                    seg_x1, seg_y1 = x1, y1
                    seg_x2, seg_y2 = x2, y2
                    if horizontal:
                        bar_x = min(max(bar_x, min(seg_x1, seg_x2)), max(seg_x1, seg_x2))
                        bar_y = saved_pos[1]
                    else:
                        bar_y = min(max(bar_y, min(seg_y1, seg_y2)), max(seg_y1, seg_y2))
                        bar_x = saved_pos[0]
                else:
                    bar_x, bar_y = mid_x, mid_y

                # DIBUJAR LA BARRA "/" CRUZANDO LA LÍNEA
                # La barra acompaña a la etiqueta movida, formando el conjunto "/nn" que se mueve junto.
                slash_size = 5 * zoom
                self.canvas.create_line(
                    (bar_x - slash_size) * zoom, (bar_y + slash_size) * zoom,
                    (bar_x + slash_size) * zoom, (bar_y - slash_size) * zoom,
                    fill="#CC0000", width=2, tags="wire_label"
                )

                self.canvas.create_text(
                    (bar_x + offset_x) * zoom, (bar_y + offset_y) * zoom,
                    text=label,
                    fill="#CC0000", # Rojo industrial para cables
                    font=("Arial", int(7 * zoom), "italic"),
                    tags=("wire_label", f"conn_{id(conn)}", "wire_label_drag")
                )

    def show_shortcuts(self):
        """Muestra ventana de atajos de teclado con formato mejorado"""
        shortcuts_window = tk.Toplevel(self.root)
        shortcuts_window.title("Atajos de Teclado")

        win_w, win_h = 600, 700
        shortcuts_window.geometry(f"{win_w}x{win_h}")
        shortcuts_window.resizable(False, False)

        # Frame principal con scroll
        main_frame = tk.Frame(shortcuts_window, bg="white")
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        canvas = tk.Canvas(main_frame, bg="white", highlightthickness=0)
        scrollbar = tk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="white")

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Definir atajos por categorías
        shortcuts_data = [
            ("ARCHIVO", [
                ("Ctrl+N", "Nuevo lienzo"),
                ("Ctrl+O", "Abrir archivo .ecad"),
                ("Ctrl+S", "Guardar archivo .ecad"),
                ("Ctrl+E", "Exportar PDF"),
                ("Ctrl+Q", "Salir"),
            ]),
            ("EDICIÓN", [
                ("Ctrl+Z", "Deshacer (Historial de 15 estados)"),
                ("Ctrl+Y", "Rehacer"),
                ("Ctrl+R", "Rotar +90°"),
                ("Ctrl+Shift+R", "Rotar -90°"),
                ("Delete", "Borrar componente, conexión o punto de conexión"),
                ("Escape", "Deseleccionar"),
                ("Alt+Clck Der hold", "Mover componente horizontalmente (fija vertical)"),
                ("Alt+Clck Izq hold", "Mover componente verticalmente (fija horizontal)"),
            ]),
            ("ALINEACIÓN Y DISTRIBUCIÓN", [
                ("Ctrl+H", "Centrar Verticalmente"),
                ("Ctrl+J", "Distribución Vertical Equidistante"),
                ("Ctrl+K", "Alineación Horizontal (misma altura)"),
                ("Ctrl+M", "Distribución Horizontal Equidistante"),
            ]),
            ("CONEXIONES", [
                ("Ctrl+I", "Insertar Punto de Conexión"),
                ("Ctrl+Click", "Routing Manual"),
                ("Ctrl+A", "Toggle Auto-Conexión"),
                ("Ctrl+X", "Toggle Invertir Detección"),
            ]),
            ("SIMULACIÓN", [
                ("F5", "▶️  Iniciar / Reanudar simulación"),
                ("F6", "⏹️  Detener simulación (restablece todas las hojas)"),
            ]),
            ("VISTA", [
                ("Ctrl++", "Zoom + (acercar)"),
                ("Ctrl+-", "Zoom - (alejar)"),
                ("Ctrl+0", "Zoom Reset (100%)"),
                ("Ctrl+G", "Toggle Grid (Snap to Grid)"),
                ("F7", "Alternar Numeración de Cables ON/OFF"),
            ]),

            ("EDICIÓN 2D", [
                ("Ctrl+D", "Insetar Riel Dim"),
                ("Ctrl+F", "Insetar Canaleta Ranurada"),
                ("Ctrl+B", "Insetar Block Terminal"),
                ("Ctrl+clic der.", "Ancho comercial de la Canaleta"),
            ])
        ]

        for category, shortcuts in shortcuts_data:
            category_label = tk.Label(
                scrollable_frame,
                text=category,
                font=("Arial", 11, "bold"),
                bg="white",
                fg="#2c3e50",
                anchor="w"
            )
            category_label.pack(fill="x", pady=(10, 5))

            # Frame para los atajos de esta categoría
            category_frame = tk.Frame(scrollable_frame, bg="white")
            category_frame.pack(fill="x", padx=20)

            for shortcut, description in shortcuts:
                # Frame para cada atajo
                shortcut_frame = tk.Frame(category_frame, bg="white")
                shortcut_frame.pack(fill="x", pady=2)

                # Atajo (izquierda)
                shortcut_label = tk.Label(
                    shortcut_frame,
                    text=shortcut,
                    font=("Courier New", 10, "bold"),
                    bg="white",
                    fg="#34495e",
                    width=20,
                    anchor="w"
                )
                shortcut_label.pack(side="left")

                # Descripción (derecha)
                desc_label = tk.Label(
                    shortcut_frame,
                    text=description,
                    font=(AppConstants.UI_FONT_FAMILY, 10),
                    bg="white",
                    fg="#555555",
                    anchor="w"
                )
                desc_label.pack(side="left", fill="x", expand=True)

        # Nota informativa
        note_frame = tk.Frame(scrollable_frame, bg="#ecf0f1", relief=tk.RIDGE, bd=1)
        note_frame.pack(fill="x", pady=(15, 5), padx=5)

        note_label = tk.Label(
            note_frame,
            text="💡 Para distribución: Seleccione 2 o más componentes (Shift+Click)",
            font=("Arial", 9, "italic"),
            bg="#ecf0f1",
            fg="#7f8c8d",
            anchor="w",
            padx=10,
            pady=5
        )
        note_label.pack(fill="x")

        # Empaquetar canvas y scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Botón cerrar
        close_button = tk.Button(
            shortcuts_window,
            text="Cerrar",
            command=shortcuts_window.destroy,
            bg="#3498db",
            fg="white",
            font=("Arial", 10, "bold"),
            relief=tk.FLAT,
            padx=20,
            pady=5,
            cursor="hand2"
        )
        close_button.pack(pady=10)

        # Centrar ventana relativo a la ventana principal (Mejorado para multimonitor)
        shortcuts_window.update_idletasks()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()

        # Calcular centro
        x = root_x + (root_w // 2) - (win_w // 2)
        y = root_y + (root_h // 2) - (win_h // 2)
        shortcuts_window.geometry(f"{win_w}x{win_h}+{x}+{y}")

        # Hacer modal
        shortcuts_window.transient(self.root)
        shortcuts_window.grab_set()

    def show_legal_notice(self):
        """Muestra el aviso legal completo (cláusula de exención de responsabilidad)."""
        win = tk.Toplevel(self.root)
        win.title(DISCLAIMER_TITLE)
        win.geometry("760x560")
        win.transient(self.root)

        header = tk.Label(
            win,
            text=DISCLAIMER_TITLE,
            font=(AppConstants.UI_FONT_FAMILY, 12, "bold"),
            anchor="w",
            padx=14,
            pady=10,
        )
        header.pack(fill="x")

        body = tk.Frame(win)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        text = tk.Text(
            body,
            wrap="word",
            font=(AppConstants.UI_FONT_FAMILY, 10),
            relief="sunken",
            bd=1,
            padx=10,
            pady=10,
        )
        scroll = tk.Scrollbar(body, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)

        text.insert("1.0", DISCLAIMER_TEXT)
        text.configure(state="disabled")

        win.grab_set()

    def show_about(self):
        about_window = tk.Toplevel(self.root)
        about_window.title("Acerca de")

        btc_address = (BTC_DONATION_ADDRESS or "").strip()
        btc_uri = get_btc_donation_uri() if btc_address else ""
        # Tope de alto: mantiene la ventana acotada y el texto largo con scroll.
        win_w, win_h = 450, 600 if btc_address else 540
        max_win_h = 600
        about_window.geometry(f"{win_w}x{win_h}")
        about_window.transient(self.root)
        about_window.grab_set()
        about_window.resizable(False, False)

        # Frame inferior para logo y botón cerrar.
        # Se empaqueta antes que el resto para que reserve su alto natural:
        # si se empaqueta al final, el texto expansivo le roba el espacio y
        # Tk comprime el logo y el botón.
        bottom_frame = tk.Frame(about_window)
        bottom_frame.pack(side="bottom", fill="x", pady=(0, 12))

        # Texto principal (con scroll porque la nota legal no entra entera)
        text_frame = tk.Frame(about_window)
        text_frame.pack(expand=True, fill="both", padx=20, pady=(20, 8))

        about_text = "evaPr v0.700\nGPL3\nDiagramador de Planos Electricos para Linux.\nHecho por etovive\nMejorado por Luka\n\n✓ Formato .ecad\n✓ Exportación PDF\n✓ Líneas consistentes\n\nAgradezco los aportes y pull requests de la comunidad,\npero no puedo brindar soporte técnico ni garantía.\nEl proyecto se comparte para quien desee colaborar.\n\nNota Legal: Las dimensiones y recomendaciones de evaPR son referenciales. La validación final de cálculos y componentes debe ser realizada por el profesional eléctrico responsable. La herramienta no sustituye el diseño detallado del proyecto.\n\nAviso legal completo en el menú Ayuda → Aviso Legal."

        text_canvas = tk.Canvas(text_frame, highlightthickness=0, bd=0)
        text_scroll = tk.Scrollbar(text_frame, orient="vertical", command=text_canvas.yview)
        text_canvas.configure(yscrollcommand=text_scroll.set)
        text_scroll.pack(side="right", fill="y")
        text_canvas.pack(side="left", fill="both", expand=True)

        text_inner = tk.Frame(text_canvas)
        text_window = text_canvas.create_window((0, 0), window=text_inner, anchor="nw")

        text_label = tk.Label(text_inner, text=about_text, justify="left", font=(AppConstants.UI_FONT_FAMILY, 10), wraplength=390)
        text_label.pack(anchor="w")

        def sync_text_width(event):
            text_canvas.itemconfigure(text_window, width=event.width)

        def scroll_text(event):
            if text_canvas.bbox("all"):
                text_canvas.yview_scroll(-1 * (event.delta // 120), "units")

        text_inner.bind("<Configure>", lambda e: text_canvas.configure(scrollregion=text_canvas.bbox("all")))
        text_canvas.bind("<Configure>", sync_text_width)
        text_canvas.bind("<MouseWheel>", scroll_text)

        donation_frame = tk.Frame(about_window, bg="#f0f0f0", relief="sunken", bd=1)
        donation_frame.pack(side="bottom", fill="x", padx=20, pady=(0, 8))

        # Título del área de donación
        donation_title = tk.Label(donation_frame, text="☕ ¿Te sirvió este software? ¡Invítame un café!",
                                font=("Arial", 9, "bold"), bg="#f0f0f0")
        donation_title.pack(pady=(8, 4))

        # Fila de botones de donación
        buttons_row = tk.Frame(donation_frame, bg="#f0f0f0")
        buttons_row.pack(fill="x", padx=8)

        # Botón de PayPal con función
        def open_paypal():
            try:
                import webbrowser
                webbrowser.open(PAYPAL_DONATION_URL)
            except Exception:
                messagebox.showinfo("PayPal", f"Visita: {PAYPAL_DONATION_URL}")

        def copy_btc():
            try:
                about_window.clipboard_clear()
                about_window.clipboard_append(btc_address)
                about_window.update_idletasks()
                messagebox.showinfo("Bitcoin", f"Dirección copiada al portapapeles:\n\n{btc_address}")
            except Exception:
                messagebox.showinfo("Bitcoin", f"Copiá la dirección manualmente:\n\n{btc_address}")

        def copy_to_clipboard(value, titulo, mensaje):
            try:
                about_window.clipboard_clear()
                about_window.clipboard_append(value)
                about_window.update_idletasks()
                messagebox.showinfo(titulo, mensaje.format(value))
            except Exception:
                messagebox.showinfo(titulo, f"Copiá el texto manualmente:\n\n{value}")

        def copy_btc_uri():
            copy_to_clipboard(
                btc_uri, "Bitcoin",
                "URI de donación copiada.\n\nPegala en Electrum para abrir la\nsolicitud de pago con la nota ya puesta:\n\n{}",
            )

        def show_btc_donation():
            """Muestra una tarjeta de donación Bitcoin con su código QR."""
            donation_window = tk.Toplevel(about_window)
            donation_window.title("Donar con Bitcoin")
            donation_window.configure(bg="#f5f5f5")
            donation_window.resizable(False, False)
            donation_window.transient(about_window)

            card = tk.Frame(donation_window, bg="white", relief="solid", bd=1)
            card.pack(fill="both", expand=True, padx=12, pady=12)

            header = tk.Frame(card, bg="white")
            header.pack(fill="x", padx=14, pady=(12, 8))
            tk.Label(header, text="Soporte a través de Crypto",
                     font=(AppConstants.UI_FONT_FAMILY, 11), bg="white",
                     fg="#333333", anchor="w").pack(fill="x")
            tk.Label(header, text="Bitcoin · Escaneá o copiá la dirección",
                     font=(AppConstants.UI_FONT_FAMILY, 9), bg="white",
                     fg="#858585", anchor="w").pack(fill="x", pady=(2, 0))
            tk.Frame(card, bg="#e5e5e5", height=1).pack(fill="x")

            qr_image = None
            qr_paths = [
                get_resource_dir() / "assets" / "bitcoin-donation-qr.png",
                get_app_dir() / "assets" / "bitcoin-donation-qr.png",
                Path.cwd() / "assets" / "bitcoin-donation-qr.png",
            ]
            for qr_path in qr_paths:
                try:
                    if qr_path.exists():
                        qr_image = tk.PhotoImage(file=str(qr_path))
                        break
                except tk.TclError:
                    continue

            if qr_image:
                qr_label = tk.Label(card, image=qr_image, bg="white")
                qr_label.image = qr_image  # Mantiene viva la imagen para Tk.
                qr_label.pack(pady=(16, 14))
            else:
                tk.Label(card, text="No se pudo cargar el código QR.",
                         font=(AppConstants.UI_FONT_FAMILY, 10), bg="white",
                         fg="#a33").pack(pady=(30, 24))

            address_area = tk.Frame(card, bg="white")
            address_area.pack(fill="x", padx=14, pady=(0, 12))
            tk.Label(address_area, text="Bitcoin Address",
                     font=(AppConstants.UI_FONT_FAMILY, 9), bg="white",
                     fg="#858585", anchor="w").pack(fill="x", pady=(0, 3))

            address_row = tk.Frame(address_area, bg="white")
            address_row.pack(fill="x")
            address_value = tk.Entry(address_row,
                                     font=(AppConstants.MONO_FONT_FAMILY, 9),
                                     readonlybackground="#fafafa", relief="solid",
                                     bd=1, highlightthickness=0)
            address_value.insert(0, btc_address)
            address_value.configure(state="readonly")
            address_value.pack(side="left", fill="x", expand=True, ipady=4)
            tk.Button(address_row, text="Copiar", command=copy_btc,
                      font=(AppConstants.UI_FONT_FAMILY, 9), bg="#f7931a",
                      fg="white", activebackground="#df7d0d", relief="flat",
                      cursor="hand2", padx=10, pady=4).pack(side="left", padx=(7, 0))

            donation_window.update_idletasks()
            width, height = 430, donation_window.winfo_reqheight() + 24
            parent_x = about_window.winfo_rootx()
            parent_y = about_window.winfo_rooty()
            donation_window.geometry(
                f"{width}x{height}+{parent_x + 10}+{parent_y + 10}"
            )

        tk.Button(buttons_row, text="☕ Me invitas un café",
                font=(AppConstants.UI_FONT_FAMILY, 9), bg="#0070ba", fg="white",
                relief="raised", bd=2, cursor="hand2",
                command=open_paypal).pack(pady=(0, 6))

        if btc_address:
            tk.Button(buttons_row, text="₿ Bitcoin",
                    font=(AppConstants.UI_FONT_FAMILY, 9), bg="#f7931a", fg="white",
                    relief="raised", bd=2, cursor="hand2",
                    command=show_btc_donation).pack(pady=(0, 6))

        # Detalle de la dirección Bitcoin
        if btc_address:
            btc_frame = tk.Frame(donation_frame, bg="#f0f0f0")
            btc_frame.pack(fill="x", padx=8, pady=(0, 6))

            tk.Label(btc_frame, text="Dirección de tu wallet (Electrum):",
                    font=("Arial", 8), bg="#f0f0f0", anchor="w"
                    ).pack(fill="x", pady=(2, 1))

            address_row = tk.Frame(btc_frame, bg="#f0f0f0")
            address_row.pack(fill="x")

            # Entry con estilo read-only: es el único widget que permite
            # edición para que la dirección no pueda ser alterada.
            BTC_NAV_KEYS = {
                "Left", "Right", "Up", "Down", "Home", "End",
                "Prior", "Next", "Shift-Left", "Shift-Right",
                "Shift-Up", "Shift-Down", "Shift-Home", "Shift-End",
                "Control-c", "Control-a",
            }
            btc_entry = tk.Entry(
                address_row, font=(AppConstants.MONO_FONT_FAMILY, 8),
                readonlybackground="#ffffff", relief="sunken", bd=1,
                highlightthickness=0, cursor="xterm",
            )
            btc_entry.insert(0, btc_address)
            btc_entry.pack(side="left", fill="x", expand=True)

            def block_edit_btc(event):
                return None if event.keysym in BTC_NAV_KEYS else "break"

            def select_all_btc(_event=None):
                btc_entry.selection_range(0, "end")
                btc_entry.focus_set()
                # "break" evita que el class binding de Entry borre la selección
                return "break"

            btc_entry.bind("<Key>", block_edit_btc, add="+")
            btc_entry.bind("<Button-1>", select_all_btc, add="+")

            tk.Button(address_row, text="Copiar", font=("Arial", 8),
                    relief="raised", bd=1, cursor="hand2",
                    command=copy_btc).pack(side="left", padx=(4, 0))

            link_row = tk.Frame(btc_frame, bg="#f0f0f0")
            link_row.pack(fill="x", pady=(4, 0))

            tk.Button(link_row, text="Copiar URI bitcoin: (con nota)",
                    font=("Arial", 8), bg="#e8e8e8", relief="raised", bd=1,
                    cursor="hand2", command=copy_btc_uri).pack(side="left")

        # Intentar cargar logo (bottom_frame ya fue empaquetado arriba)
        try:
            logo_paths = [str(get_resource_dir() / "logo-evaPr.png"), str(get_app_dir() / "logo-evaPr.png"), "logo-evaPr.png"]
            logo_loaded = False
            for logo_path in logo_paths:
                if os.path.exists(logo_path):
                    try:
                        logo_img = tk.PhotoImage(file=logo_path)
                        if logo_img.width() > 48 or logo_img.height() > 48:
                            scale = min(48/logo_img.width(), 48/logo_img.height())
                            logo_img = logo_img.subsample(int(1/scale))
                        logo_label = tk.Label(bottom_frame, image=logo_img)
                        logo_label.image = logo_img
                        logo_label.pack(side="left", padx=15, pady=10)
                        logo_loaded = True
                        break
                    except: continue
            if not logo_loaded:
                tk.Label(bottom_frame, text="⚡", font=("Arial", 24)).pack(side="left", padx=15, pady=10)
        except:
            pass

        tk.Button(bottom_frame, text="Cerrar", command=about_window.destroy,
                  width=10, bg="#3498db", fg="white", font=("Arial", 9, "bold")).pack(side="right", padx=15, pady=10)

        # Centrar ventana relativo a la principal
        about_window.update_idletasks()
        # Antes el alto fijo recortaba la franja inferior (logo y botón Cerrar).
        # Ahora se agranda solo lo necesario para esa franja, con tope de 600.
        req = about_window.winfo_reqheight()
        win_h_calc = min(max_win_h, max(win_h, req))
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        x = rx + (rw // 2) - (win_w // 2)
        y = ry + (rh // 2) - (win_h_calc // 2)
        about_window.geometry(f"{win_w}x{win_h_calc}+{x}+{y}")

    def show_vdf_analog_slider(self, component, x, y):
        """Muestra un slider flotante para controlar la velocidad del VDF (Control Analógico)"""
        if hasattr(self, 'current_slider_window') and self.current_slider_window:
            try:
                self.current_slider_window.destroy()
            except:
                pass

        slider_window = tk.Toplevel(self.root)
        self.current_slider_window = slider_window
        slider_window.title("VDF")
        # Ajustar posición
        slider_window.geometry(f"80x220+{x}+{y}")
        slider_window.resizable(False, False)
        slider_window.transient(self.root)

        frame = tk.Frame(slider_window, padx=5, pady=5, bg="#eeeeee")
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Velocidad", font=("Arial", 9, "bold"), bg="#eeeeee").pack()

        # Valor actual (0-100%)
        current_val = getattr(component, 'analog_speed_pct', 0.0)

        # Label de valor numérico
        val_label = tk.Label(frame, text=f"{int(current_val)}%", font=(AppConstants.UI_FONT_FAMILY, 10), bg="#eeeeee", fg="blue")
        val_label.pack()

        def on_scale(val):
            v = float(val)
            component.analog_speed_pct = v
            val_label.config(text=f"{int(v)}%")

        scale = tk.Scale(frame, from_=100, to=0, orient="vertical", command=on_scale, length=140, bg="#eeeeee")
        scale.set(current_val)
        scale.pack(pady=5)

        # Botón Cerrar eliminado por solicitud

    def edit_component_label(self, component):
        """Abre ventana de edición de etiqueta para el componente"""
        from ui.label_editors import open_label_editor
        open_label_editor(self, component)

    # MÉTODOS AUXILIARES para cambiar tamaño de fuente

    def _edit_shielding_label(self, shielding):
        """Edita un Shielding — delegado a ui.label_editors"""
        from ui.label_editors import ShieldingLabelEditor
        ShieldingLabelEditor(self, shielding)

    def toggle_labels_visibility(self):
        """Alterna la visibilidad de todas las etiquetas"""
        # Toggle del estado
        current_state = getattr(self.canvas, 'show_labels', True)
        self.canvas.show_labels = not current_state

        for component in self.components:
            component.clear_label()
            component.draw_label()

        state_text = "mostradas" if self.canvas.show_labels else "ocultadas"

    def _setup_basic_events(self):
        """Configura eventos básicos cuando no están disponibles los handlers externos"""

        # EVENTOS BÁSICOS ESENCIALES PARA FUNCIONAMIENTO MÍNIMO

        # CRÍTICO: Solo configurar eventos básicos si EventHandler NO está disponible
        if not getattr(self, 'event_handlers_active', False):
            # Click izquierdo - funcionalidad básica de selección y colocación
            self.canvas.bind("<Button-1>", self._on_basic_left_click)

            # Click derecho para editar etiquetas
            self.canvas.bind("<Button-3>", self._on_right_click)

            # Arrastre básico - DESHABILITAR durante shapes para evitar bucles infinitos
            self.canvas.bind("<B1-Motion>", self._on_basic_drag)

            # Soltar click
            self.canvas.bind("<ButtonRelease-1>", self._on_basic_release)

            # Sistema básico de eventos activado
        else:
            # Sistema de eventos avanzado activo - EventHandler maneja todos los eventos
            pass

        # Movimiento del mouse ahora se maneja en event_handlers
        # Binding movido a la función consolidada on_mouse_motion

        # WHEEL DEL MOUSE DESACTIVADO POR SOLICITUD DEL USUARIO
        # Wheel del mouse para zoom - DESACTIVADO

        self.canvas.bind("<KeyPress>", self._on_basic_key_press)

        # Binding para doble click (edición de texto)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)

        # Focus para recibir eventos de teclado
        self.canvas.focus_set()

    def _on_basic_key_press(self, event):
        """Maneja eventos básicos de teclado cuando se presiona cualquier tecla"""
        try:
            # Log detallado para debug
            keysym = event.keysym
            keys_num = getattr(event, 'keysym_num', None)
            state = getattr(event, 'state', 0)
            keycode = getattr(event, 'keycode', None)

            # CORRECCIÓN ATAJOS DE AYUDA - Implementar Ctrl+K y Ctrl+J
            # OPTIMIZACIÓN O(1): Diccionario de handlers para teclas Ctrl+
            ctrl_handlers = {
                'k': self._distribute_components_horizontally,
                'j': self._distribute_components_vertically
            }

            # Acceso O(1) en lugar de elif chain
            key_lower = keysym.lower()
            if key_lower in ctrl_handlers and (state & 0x4):  # Ctrl pressed
                ctrl_handlers[key_lower]()
                return "break"

            return "break"  # Prevenir propagación

        except Exception as e:

            pass
            import traceback
            traceback.print_exc()
            return "break"

    def _distribute_components_horizontally(self):
        """Distribución horizontal de componentes seleccionados (Ctrl+K)"""
        try:
            # Validar selección de componentes
            if not hasattr(self, 'selected_components') or len(self.selected_components) < 2:
                self.set_status("Seleccione al menos 2 componentes para distribución horizontal", "orange")
                return

            from utils.alignment_utils import distribute_components_horizontally

            # Ejecutar distribución
            distribute_components_horizontally(self.selected_components, self)

            # Feedback al usuario
            self.set_status(f"↔️ Distribución horizontal aplicada a {len(self.selected_components)} componentes", "blue")

        except Exception as e:
            self.set_status("❌ Error en distribución horizontal", "red")

    def _distribute_components_equidistant_horizontally(self):
        """Distribución horizontal equidistante de componentes seleccionados (Ctrl+M)"""
        try:
            current_sheet = self.project.get_active_sheet()
            is_gabinete = getattr(current_sheet, 'name', '') == "Hoja de Gabinete 2D"

            if is_gabinete:
                self._distribute_cabinet_shapes_horizontally()
                return

            # Validar selección de componentes
            if not hasattr(self, 'selected_components') or len(self.selected_components) < 2:
                self.set_status("Seleccione al menos 2 componentes para distribución horizontal equidistante", "orange")
                return

            # Ejecutar distribución a través del manager
            self.alignment_manager.distribute_multiple_equidistant_horizontally()

            # Feedback al usuario
            self.set_status(f"↔️ Distribución horizontal equidistante aplicada a {len(self.selected_components)} componentes", "blue")

        except Exception as e:
            self.set_status("❌ Error en distribución horizontal equidistante", "red")

    def _distribute_components_vertically(self):
        """Distribución vertical de componentes seleccionados (Ctrl+J)"""
        try:
            # En Gabinete 2D: operar sobre shapes válidos (Rect/Circle de componentes, no estructura)
            current_sheet = self.project.get_active_sheet()
            is_gabinete = getattr(current_sheet, 'name', '') == "Hoja de Gabinete 2D"

            if is_gabinete:
                self._distribute_cabinet_shapes_vertically()
                return

            # Validar selección de componentes
            if not hasattr(self, 'selected_components') or len(self.selected_components) < 2:
                self.set_status("Seleccione al menos 2 componentes para distribución vertical", "orange")
                return

            from utils.alignment_utils import distribute_components_vertically

            # Ejecutar distribución
            distribute_components_vertically(self.selected_components, self)

            # Feedback al usuario
            self.set_status(f"↕️ Distribución vertical aplicada a {len(self.selected_components)} componentes", "blue")

        except Exception as e:
            self.set_status("❌ Error en distribución vertical", "red")

    def _get_cabinet_distributable_shapes(self):
        """Retorna solo los shapes Rect/Circle de componentes del Gabinete 2D
        que esten en self.selected_elements, excluyendo DinRail, Canaleta,
        fondos de tablero/puerta y lineas divisorias."""
        from models.shape import Rect, Circle, DinRail, Canaleta
        excluded_types = {'cabinet_background', 'borner_divider'}
        shapes = []
        selected = set(id(e) for e in getattr(self, 'selected_elements', []))
        if not selected:
            # Si no hay seleccion, operar sobre todos los shapes validos
            candidates = self.shape_manager.shapes
        else:
            candidates = [s for s in self.shape_manager.shapes if id(s) in selected]
        for s in candidates:
            if isinstance(s, (DinRail, Canaleta)):
                continue
            meta_type = getattr(s, 'metadata', {}).get('type', '')
            if meta_type in excluded_types:
                continue
            if isinstance(s, (Rect, Circle)):
                shapes.append(s)
        return shapes

    def _distribute_cabinet_shapes_vertically(self):
        """Ctrl+J en Gabinete 2D: toma los shapes seleccionados (Rect/Circle),
        los ordena por Y, ancla el 1ro y el ultimo como limites fijos,
        alinea todos al mismo X (centro del primer shape) y redistribuye
        los intermedios con espaciado igual entre bordes."""
        shapes = self._get_cabinet_distributable_shapes()
        if len(shapes) < 3:
            self.set_status("Seleccione al menos 3 componentes (1ro y ultimo son los limites)", "orange")
            return
        shapes.sort(key=lambda s: s.y)
        first, last = shapes[0], shapes[-1]
        middle = shapes[1:-1]

        # Alinear todos al X del primero
        align_x = first.x
        for s in shapes:
            s.x = align_x
            s.canvas_id = None

        # Borde inferior del primero y borde superior del ultimo
        bot_of_first = first.y + getattr(first, 'height', getattr(first, 'h', 0)) / 2
        top_of_last  = last.y  - getattr(last,  'height', getattr(last,  'h', 0)) / 2

        # Espacio libre entre ambos limites menos el alto total de los intermedios
        middle_total_h = sum(getattr(s, 'height', getattr(s, 'h', 0)) for s in middle)
        free_space = top_of_last - bot_of_first - middle_total_h
        gap = free_space / (len(middle) + 1)

        cursor_y = bot_of_first + gap
        for s in middle:
            h = getattr(s, 'height', getattr(s, 'h', 0))
            s.y = cursor_y + h / 2
            s.canvas_id = None
            cursor_y += h + gap

        self._redraw_cabinet_shapes()
        self.set_status(f"⇕️ Distribucion vertical aplicada a {len(shapes)} componentes", "blue")

    def _distribute_cabinet_shapes_horizontally(self):
        """Ctrl+M en Gabinete 2D: toma los shapes seleccionados (Rect/Circle),
        los ordena por X, ancla el 1ro y el ultimo como limites fijos,
        alinea todos al mismo Y (centro del primer shape) y redistribuye
        los intermedios con espaciado igual entre bordes."""
        shapes = self._get_cabinet_distributable_shapes()
        if len(shapes) < 3:
            self.set_status("Seleccione al menos 3 componentes (1ro y ultimo son los limites)", "orange")
            return
        shapes.sort(key=lambda s: s.x)
        first, last = shapes[0], shapes[-1]
        middle = shapes[1:-1]

        # Alinear todos al Y del primero
        align_y = first.y
        for s in shapes:
            s.y = align_y
            s.canvas_id = None

        # Borde derecho del primero y borde izquierdo del ultimo
        right_of_first = first.x + getattr(first, 'width', getattr(first, 'w', 0)) / 2
        left_of_last   = last.x  - getattr(last,  'width', getattr(last,  'w', 0)) / 2

        # Espacio libre entre ambos limites menos el ancho total de los intermedios
        middle_total_w = sum(getattr(s, 'width', getattr(s, 'w', 0)) for s in middle)
        free_space = left_of_last - right_of_first - middle_total_w
        gap = free_space / (len(middle) + 1)

        cursor_x = right_of_first + gap
        for s in middle:
            w = getattr(s, 'width', getattr(s, 'w', 0))
            s.x = cursor_x + w / 2
            s.canvas_id = None
            cursor_x += w + gap

        self._redraw_cabinet_shapes()
        self.set_status(f"↔️ Distribucion horizontal aplicada a {len(shapes)} componentes", "blue")

    def _redraw_cabinet_shapes(self):
        """Redibuja todos los shapes del Gabinete 2D despues de una distribucion."""
        self.canvas.delete("all")
        self.draw_grid(force=True)
        for s in self.shape_manager.shapes:
            s.canvas_id = None
            if hasattr(s, 'inner_ids'):
                s.inner_ids = []
            s.draw(self.canvas)
        for t in self.text_components:
            t.draw()

        # Redibujar Block Terminals después de canvas.delete("all")
        # canvas.delete("all") invalida sus canvas IDs pero los datos siguen en self.block_terminals.
        # Sin este bloque los BTs desaparecen al alinear/distribuir hasta que se cambia y vuelve la hoja.
        _eh = getattr(self, 'event_handler', None)
        if self.block_terminals and _eh and hasattr(_eh, '_place_block_terminal'):
            bts_snapshot = [
                (bt['x'], bt['y'], bt['filas'], bt['bornas'], bt.get('label_data', {}).copy())
                for bt in self.block_terminals
            ]
            self.block_terminals = []
            for (x, y, filas, bornas, ld) in bts_snapshot:
                try:
                    _eh._place_block_terminal(x, y, filas, bornas, label_data=ld, auto_open=False)
                except Exception as e:
                    print(f"[BT] Error redibujando block terminal en _redraw_cabinet_shapes: {e}")
            # ídem rama live_components
            if hasattr(_eh, '_redraw_block_terminals_after_zoom'):
                self.root.after(10, _eh._redraw_block_terminals_after_zoom)

        self.save_undo_checkpoint()

    def _on_right_click(self, event):
        """Manejo básico del click derecho para editar etiquetas"""
        # COORDINADAS NATIVAS: Usar canvasx/y para precisión absoluta con pan/zoom
        x = self.canvas.canvasx(event.x) / self.canvas.zoom_level
        y = self.canvas.canvasy(event.y) / self.canvas.zoom_level

        # Buscar componente bajo el cursor
        clicked_component = self.find_component_at_position(x, y)

        if clicked_component:
            pass

            # NO ABRIR EDITOR para componentes sin etiqueta (T.svg)
            if clicked_component.component_type in ["tierra"]:
                messagebox.showinfo(
                    "Información",
                    f"El componente '{clicked_component.svg_file}' no requiere etiqueta."
                )
                return

            self.edit_component_label(clicked_component)

    # MÉTODOS ELIMINADOS: Los eventos de mouse son manejados por EventHandler
    # _on_left_click, _on_drag, _on_release - ahora delegados a EventHandler

    def start_selection_box(self, x, y):
        """Inicia la selección por área."""
        try:
            # Verificar que el canvas esté disponible
            if not hasattr(self, 'canvas') or self.canvas is None:
                return

            self.selection_box_active = True
            self.selection_box_start = (x, y)

            # CONVERTIR a coordenadas del mundo para que se dibuje correctamente con pan/zoom
            x_world, y_world = event_to_canvas_coords(type('Event', (), {'x': x, 'y': y})(), self.canvas)

            # usar draw_world_rectangle que compensa zoom + pan correctamente
            try:
                from utils.coordinates import draw_world_rectangle
                self.selection_box_rect = draw_world_rectangle(
                    self.canvas,
                    x_world, y_world,
                    x_world, y_world,
                    outline="#0080ff",
                    width=1,
                    fill="#0080ff",
                    stipple="gray25",  # Patrón para transparencia
                    dash=(4, 4)        # Líneas punteadas
                )

            except Exception as e:
                # Continuar aunque falle el rectángulo - la selección aún puede funcionar sin indicador visual
                self.selection_box_rect = None

        except Exception as e:

            # Resetear estado en caso de error
            self.selection_box_active = False
            self.selection_box_start = None
            self.selection_box_rect = None

    def update_selection_box(self, x, y):
        """Actualiza el rectángulo de selección durante el arrastre."""
        try:
            if not self.selection_box_active:
                return

            if not self.selection_box_rect:
                return

            if not hasattr(self, 'canvas') or self.canvas is None:
                return

            start_x, start_y = self.selection_box_start

            # canvas.coords() opera en coordenadas de pantalla del canvas (píxeles
            # del widget), no en coordenadas del mundo. Hay que convertir con zoom + pan.
            zoom  = getattr(self.canvas, 'zoom_level', 1.0)
            pan_x = getattr(self.canvas, 'pan_x', 0)
            pan_y = getattr(self.canvas, 'pan_y', 0)

            # Coordenadas del mundo -> pantalla del canvas
            start_x_world, start_y_world = event_to_canvas_coords(
                type('Event', (), {'x': start_x, 'y': start_y})(), self.canvas)
            end_x_world, end_y_world = event_to_canvas_coords(
                type('Event', (), {'x': x, 'y': y})(), self.canvas)

            sx1 = start_x_world * zoom + pan_x
            sy1 = start_y_world * zoom + pan_y
            sx2 = end_x_world   * zoom + pan_x
            sy2 = end_y_world   * zoom + pan_y

            self.canvas.coords(self.selection_box_rect, sx1, sy1, sx2, sy2)
        except Exception as e:
            pass

    def finish_selection_box(self, x_screen, y_screen):
        """Finaliza la selección por área y selecciona elementos dentro."""
        try:
            if not self.selection_box_active:
                return

            # Coordenadas de inicio (pantalla) y fin (pantalla)
            start_x, start_y = self.selection_box_start

            # Convertir a coordenadas del canvas (mundo)
            x1 = self.canvas.canvasx(start_x) / self.canvas.zoom_level
            y1 = self.canvas.canvasy(start_y) / self.canvas.zoom_level
            x2 = self.canvas.canvasx(x_screen) / self.canvas.zoom_level
            y2 = self.canvas.canvasy(y_screen) / self.canvas.zoom_level

            # Normalizar rectángulo
            min_x, max_x = min(x1, x2), max(x1, x2)
            min_y, max_y = min(y1, y2), max(y1, y2)

            # Determinar si es selección normal (dentro) o reversa (cruce)
            is_reverse = x_screen < start_x

            newly_selected = []

            # 1. Seleccionar componentes
            for comp in self.components:
                cl, ct = comp.x, comp.y
                cr, cb = comp.x + comp.size[0], comp.y + comp.size[1]

                if is_reverse:
                    if not (cr < min_x or cl > max_x or cb < min_y or ct > max_y):
                        newly_selected.append(comp)
                else:
                    if (cl >= min_x and ct >= min_y and cr <= max_x and cb <= max_y):
                        newly_selected.append(comp)

            # 2. Seleccionar conexiones
            for conn in self.connections:
                if not hasattr(conn, 'segments') or not conn.segments: continue
                all_in = True
                any_in = False
                for (px1, py1), (px2, py2) in conn.segments:
                    p1_in = (min_x <= px1 <= max_x and min_y <= py1 <= max_y)
                    p2_in = (min_x <= px2 <= max_x and min_y <= py2 <= max_y)
                    if p1_in or p2_in: any_in = True
                    if not (p1_in and p2_in): all_in = False

                if (is_reverse and any_in) or (not is_reverse and all_in):
                    newly_selected.append(conn)

            # 3. Seleccionar shapes (Hoja Gabinete 2D y cualquier hoja con formas)
            # finish_selection_box no incluía shapes — rieles, canaletas, etc.
            # nunca quedaban marcados con selección múltiple.
            if hasattr(self, 'shape_manager') and hasattr(self.shape_manager, 'shapes'):
                for shape in self.shape_manager.shapes:
                    # Excluir fondos y estructuras fijas del gabinete
                    meta = getattr(shape, 'metadata', {})
                    if meta.get('locked') or meta.get('type') == 'cabinet_background':
                        continue
                    # Usar get_bbox() si existe (cubre DinRail, Canaleta -que
                    # usa `largo` en vez de width/height-, Rect, Circle, etc.)
                    if hasattr(shape, 'get_bbox'):
                        try:
                            sl, st, sr_, sb = shape.get_bbox()
                        except Exception:
                            continue
                    else:
                        sx  = getattr(shape, 'x', 0)
                        sy  = getattr(shape, 'y', 0)
                        r   = getattr(shape, 'radius', None)
                        if r is not None:
                            sl, st, sr_, sb = sx - r, sy - r, sx + r, sy + r
                        else:
                            sw2 = getattr(shape, 'width',  0) / 2
                            sh2 = getattr(shape, 'height', 0) / 2
                            sl, sr_ = sx - sw2, sx + sw2
                            st, sb  = sy - sh2, sy + sh2
                    if is_reverse:
                        # Selección cruzada: basta con que el shape toque el área
                        if not (sr_ < min_x or sl > max_x or sb < min_y or st > max_y):
                            newly_selected.append(shape)
                    else:
                        # Selección normal: el shape debe estar completamente dentro
                        if sl >= min_x and st >= min_y and sr_ <= max_x and sb <= max_y:
                            newly_selected.append(shape)

            for element in newly_selected:
                if element not in self.selected_elements:
                    self.selected_elements.append(element)
                    if isinstance(element, Component):
                        element.selected = True

            if hasattr(self, 'update_selection_indicators'):
                self.update_selection_indicators()

            self.cancel_selection_box()

        except Exception as e:
            self.cancel_selection_box()

    def cancel_selection_box(self):
        """Cancela y limpia el rectángulo de selección."""
        self.selection_box_active = False
        self.selection_box_start = None
        if hasattr(self, 'selection_box_rect') and self.selection_box_rect:
            try:
                self.canvas.delete(self.selection_box_rect)
            except:
                pass
            self.selection_box_rect = None

    def clear_selection(self):
        """Limpia toda la selección."""
        self.selected_elements.clear()
        self.update_selection_indicators()

    def update_selection_indicators(self):
        """Actualiza los indicadores visuales de elementos seleccionados."""
        self.canvas.delete("selection_indicator")

        for element in self.selected_elements:
            def handle_component(): pass
            def handle_connection():
                for line_id in element.line_ids:
                    coords = self.canvas.coords(line_id)
                    if len(coords) >= 4:
                        self.canvas.create_line(
                            tuple(c for c in coords),
                            fill="#0080ff", width=4, dash=(6, 4),
                            tags="selection_indicator"
                        )

            is_comp = isinstance(element, Component)
            is_conn = hasattr(element, 'line_ids')

            if is_comp:
                handle_component()
            elif is_conn:
                handle_connection()
            elif hasattr(element, 'shape_type') and element.shape_type in {'circle', 'rect', 'square'}:
                # GABINETE 2D: indicador visual para shapes alineables seleccionados
                try:
                    from utils.coordinates import world_to_canvas_coords
                    st = element.shape_type
                    sx, sy = element.x, element.y
                    if st == 'circle':
                        r = getattr(element, 'radius', 0)
                        x1, y1, x2, y2 = sx - r, sy - r, sx + r, sy + r
                    elif st == 'square':
                        half = getattr(element, 'side_length', 0) / 2
                        x1, y1, x2, y2 = sx - half, sy - half, sx + half, sy + half
                    else:  # rect
                        hw = getattr(element, 'width', 0) / 2
                        hh = getattr(element, 'height', 0) / 2
                        x1, y1, x2, y2 = sx - hw, sy - hh, sx + hw, sy + hh
                    # Convertir coordenadas mundo -> canvas (aplica zoom)
                    cx1, cy1 = world_to_canvas_coords(x1, y1, self.canvas)
                    cx2, cy2 = world_to_canvas_coords(x2, y2, self.canvas)
                    self.canvas.create_rectangle(
                        cx1, cy1, cx2, cy2,
                        outline="#0080ff",
                        width=2,
                        dash=(5, 3),
                        tags="selection_indicator"
                    )
                except Exception:
                    pass

    def rotate_selected_component(self, angle):
        """
        Rota el componente seleccionado en el ángulo especificado.
        """
        if self.selected_component and hasattr(self.selected_component, 'rotate'):
            self.selected_component.rotate(angle)
            self.set_status(f"🔄 Componente rotado {angle}°", "blue")
            for conn in self.connections:
                if conn.start_component == self.selected_component or conn.end_component == self.selected_component:
                    # Solo actualizar si no está marcada como modificada manualmente
                    if not hasattr(conn, 'manually_modified') or not conn.manually_modified:
                        self.update_manhattan_line(conn)
                    else:

                        pass
            self.redraw_components()
            self.update_selection_indicators()

    def flip_selected_horizontal(self):
        """
        Refleja horizontalmente el componente seleccionado.
        """
        if self.selected_component and hasattr(self.selected_component, 'flip_horizontal'):
            self.selected_component.flip_horizontal()
            for conn in self.connections:
                if conn.start_component == self.selected_component or conn.end_component == self.selected_component:
                    # Solo actualizar si no está marcada como modificada manualmente
                    if not hasattr(conn, 'manually_modified') or not conn.manually_modified:
                        self.update_manhattan_line(conn)
            self.redraw_components()
            self.update_selection_indicators()

    def flip_selected_vertical(self):
        """
        Refleja verticalmente el componente seleccionado.
        """
        if self.selected_component and hasattr(self.selected_component, 'flip_vertical'):
            self.selected_component.flip_vertical()
            for conn in self.connections:
                if conn.start_component == self.selected_component or conn.end_component == self.selected_component:
                    # Solo actualizar si no está marcada como modificada manualmente
                    if not hasattr(conn, 'manually_modified') or not conn.manually_modified:
                        self.update_manhattan_line(conn)
            self.redraw_components()
            self.update_selection_indicators()

    def redraw_components(self):
        """
        Redibuja todos los componentes, conexiones y elementos del canvas.
        """
        for component in self.components:
            component.draw()

        self.update_cross_references()

    def _is_report_sheet(self, sheet_name):
        """Verifica si una hoja es un reporte o plano especial que debe excluirse de lógica de diagramas."""
        if sheet_name in AppConstants.CROSS_REF_EXCLUDED_SHEETS:
            return True
        # También excluir planos unifilares (que tienen nombres dinámicos)
        if sheet_name.startswith("Plano Unifilar") or sheet_name.startswith("Hoja Unifilar"):
            return True
        return False

    def _get_cross_reference_data(self):
        """Calcula los datos de referencias cruzadas para todo el proyecto"""
        if not hasattr(self, 'project') or not self.project:
            return None, None

        COLUMN_WIDTH = CANVAS_WIDTH / 10
        proyecto_maestros = {} # nombre -> {hoja, col, x, y, obj}
        proyecto_esclavos = {} # nombre -> [ {hoja, col, terminales, tipo, x, y, es_activa, obj}, ... ]

        for s_idx, hoja_obj in enumerate(self.project.sheets):
            # EXCLUSIÓN: No tomar en cuenta hojas de reporte o planos especiales
            if self._is_report_sheet(hoja_obj.name):
                continue

            es_activa = (s_idx == self.project.active_sheet_index)
            # Acceder a elementos de forma segura
            elementos = self.components if es_activa else getattr(hoja_obj, 'elements', [])

            for elem in elementos:
                try:
                    if es_activa:
                        nombre = elem.label_data.get('name', '')
                        svg = (elem.svg_file or "").lower()
                        x, y = elem.x, elem.y
                        terminales = elem.label_data.get('terminals', '')
                        es_maestro = hasattr(elem, 'is_master') and elem.is_master()
                        obj = elem
                    else:
                        if not isinstance(elem, dict) or elem.get('type') != 'component':
                            continue
                        nombre = elem.get('label_data', {}).get('name', '')
                        svg = (elem.get('svg_file') or "").lower()
                        x, y = elem.get('x', 0), elem.get('y', 0)
                        terminales = elem.get('label_data', {}).get('terminals', '')
                        es_maestro = "coil" in svg or "bobina" in svg
                        obj = None

                    if not nombre: continue

                    num_hoja = s_idx + 1
                    num_col = int(x / COLUMN_WIDTH) + 1

                    if es_maestro:
                        proyecto_maestros[nombre] = {
                            'hoja': num_hoja, 'col': num_col, 'x': x, 'y': y, 'obj': obj
                        }
                    else:
                        if nombre not in proyecto_esclavos:
                            proyecto_esclavos[nombre] = []

                        tipo = "NA"
                        if "nc" in svg and "no" not in svg: tipo = "NC"
                        elif "cerrado" in svg: tipo = "NC"

                        t_list = [t.strip() for t in terminales.split(',') if t.strip()]
                        if len(t_list) >= 4 and len(t_list) % 2 == 0:
                            for i in range(0, len(t_list), 2):
                                sub_terminals = f"{t_list[i]},{t_list[i+1]}"
                                proyecto_esclavos[nombre].append({
                                    'hoja': num_hoja, 'col': num_col, 'terminales': sub_terminals, 'tipo': tipo,
                                    'x': x, 'y': y, 'es_activa': es_activa, 'obj': obj
                                })
                        else:
                            proyecto_esclavos[nombre].append({
                                'hoja': num_hoja, 'col': num_col, 'terminales': terminales, 'tipo': tipo,
                                'x': x, 'y': y, 'es_activa': es_activa, 'obj': obj
                            })
                except:
                    continue

        return proyecto_maestros, proyecto_esclavos

    def _get_cross_ref_base_y(self):
        """Calcula una posición Y segura para el espejo de contactos (basada en mundo)"""
        max_y = 0
        if self.components:
            for comp in self.components:
                # Altura componente + etiquetas
                comp_bottom = comp.y + comp.size[1] + 10
                max_y = max(max_y, comp_bottom)
        return max(800, max_y + 0)

    def update_cross_references(self):
        """Dibuja las referencias cruzadas en el Canvas"""
        self.canvas.delete("cross_ref")

        # EXCLUSIÓN: No dibujar referencias si la hoja actual es un reporte
        active_sheet = self.project.get_active_sheet()
        if active_sheet and self._is_report_sheet(active_sheet.name):
            return

        proyecto_maestros, proyecto_esclavos = self._get_cross_reference_data()
        if not proyecto_maestros:
            return

        zoom = self.canvas.zoom_level
        y_base_world = self._get_cross_ref_base_y()
        Y_REFERENCIAS = y_base_world * zoom

        for nombre, info_maestro in proyecto_maestros.items():
            if info_maestro['hoja'] == (self.project.active_sheet_index + 1):
                contactos = proyecto_esclavos.get(nombre, [])
                if contactos:
                    self._dibujar_espejo_contactos(info_maestro, contactos, Y_REFERENCIAS)

        for nombre, contactos in proyecto_esclavos.items():
            for contacto in contactos:
                if contacto['es_activa']:
                    maestro = proyecto_maestros.get(nombre)
                    if maestro:
                        self._dibujar_ref_maestro(contacto['obj'], maestro)

    def _dibujar_ref_maestro(self, componente, info_maestro):
        zoom = self.canvas.zoom_level
        x = (componente.x + componente.size[0] + 5) * zoom
        y = (componente.y - 10) * zoom + 10 * zoom   # encima del componente, sobre la etiqueta #y = (componente.y + componente.size[1] / 2) * zoom
        ref_text = f"/{info_maestro['hoja']}.{info_maestro['col']}"
        color = adapt_color_for_display("#2E7D32", self.canvas.cget("bg"))
        self.canvas.create_text(x, y, text=ref_text, font=("Arial", 8, "bold"),
                                fill=color, anchor="w", tags="cross_ref")

    def _dibujar_espejo_contactos(self, maestro_info, lista_contactos, y_base):
        zoom = self.canvas.zoom_level
        centro_x = (maestro_info['x'] + 25) * zoom
        color_texto = adapt_color_for_display("black", self.canvas.cget("bg"))
        color_ref = adapt_color_for_display("#2E7D32", self.canvas.cget("bg"))

        lista_contactos.sort(key=lambda c: (c['hoja'], c['col']))
        self.canvas.create_text(centro_x, y_base + 15*zoom, text=maestro_info['obj'].label_data.get('name', ''),
                                font=("Arial", 9, "bold"), fill=color_texto, tags="cross_ref")

        for i, contacto in enumerate(lista_contactos):
            ty = y_base + (35 + i * 26) * zoom
            t_list = [t.strip() for t in contacto['terminales'].split(',') if t.strip()]
            t1, t2 = (t_list[0] if len(t_list)>0 else ""), (t_list[1] if len(t_list)>1 else "")

            self.canvas.create_text(centro_x - 12*zoom, ty, text=t1, font=("Arial", 7), fill=color_texto, anchor="e", tags="cross_ref")
            self.canvas.create_text(centro_x - 12*zoom, ty + 15*zoom, text=t2, font=("Arial", 7), fill=color_texto, anchor="e", tags="cross_ref")

            if contacto['tipo'] == "NC":
                self.canvas.create_line(centro_x-6*zoom, ty+4*zoom, centro_x+6*zoom, ty+4*zoom, fill=color_texto, tags="cross_ref")
                self.canvas.create_line(centro_x, ty, centro_x, ty+18*zoom, fill=color_texto, tags="cross_ref")
            else:
                self.canvas.create_line(centro_x, ty+18*zoom, centro_x+6*zoom, ty, fill=color_texto, tags="cross_ref")
                self.canvas.create_line(centro_x, ty, centro_x, ty+18*zoom, fill=color_texto, dash=(1,1), tags="cross_ref")

            ref_text = f"/{contacto['hoja']}.{contacto['col']}"
            self.canvas.create_text(centro_x + 15*zoom, ty + 9*zoom, text=ref_text, font=("Arial", 8, "bold"), fill=color_ref, anchor="w", tags="cross_ref")
            if i < len(lista_contactos) - 1:
                self.canvas.create_line(centro_x - 20*zoom, ty + 20*zoom, centro_x + 20*zoom, ty + 20*zoom, fill="#eeeeee", tags="cross_ref")

    def _get_cross_references_svg(self):
        """Genera el contenido SVG para las referencias cruzadas del PDF"""
        # EXCLUSIÓN: No generar referencias si la hoja actual es un reporte
        active_sheet = self.project.get_active_sheet()
        if active_sheet and self._is_report_sheet(active_sheet.name):
            return ""

        proyecto_maestros, proyecto_esclavos = self._get_cross_reference_data()
        if not proyecto_maestros:
            return ""

        svg = "\n  <!-- REFERENCIAS CRUZADAS (Estándar Profesional) -->"

        # Calcular Y base usando el método compartido
        y_base = self._get_cross_ref_base_y()

        # A. Espejos de contactos
        for nombre, info_maestro in proyecto_maestros.items():
            if info_maestro['hoja'] == (self.project.active_sheet_index + 1):
                contactos = proyecto_esclavos.get(nombre, [])
                if contactos:
                    centro_x = info_maestro['x'] + 25
                    svg += f'\n    <text x="{centro_x}" y="{y_base + 15}" font-family="Arial" font-size="9" font-weight="bold" text-anchor="middle">{nombre}</text>'

                    contactos.sort(key=lambda c: (c['hoja'], c['col']))
                    for i, contacto in enumerate(contactos):
                        ty = y_base + 35 + i * 26
                        t_list = [t.strip() for t in contacto['terminales'].split(',') if t.strip()]
                        t1, t2 = (t_list[0] if len(t_list)>0 else ""), (t_list[1] if len(t_list)>1 else "")

                        svg += f'\n    <text x="{centro_x - 12}" y="{ty+5}" font-family="Arial" font-size="7" text-anchor="end">{t1}</text>'
                        svg += f'\n    <text x="{centro_x - 12}" y="{ty+20}" font-family="Arial" font-size="7" text-anchor="end">{t2}</text>'

                        if contacto['tipo'] == "NC":
                            svg += f'\n    <line x1="{centro_x-6}" y1="{ty+4}" x2="{centro_x+6}" y2="{ty+4}" stroke="black" stroke-width="0.5" />'
                            svg += f'\n    <line x1="{centro_x}" y1="{ty}" x2="{centro_x}" y2="{ty+18}" stroke="black" stroke-width="0.5" />'
                        else:
                            svg += f'\n    <line x1="{centro_x}" y1="{ty+18}" x2="{centro_x+6}" y2="{ty}" stroke="black" stroke-width="0.5" />'
                            svg += f'\n    <line x1="{centro_x}" y1="{ty}" x2="{centro_x}" y2="{ty+18}" stroke="black" stroke-width="0.5" stroke-dasharray="1,1" />'

                        ref_text = f"/{contacto['hoja']}.{contacto['col']}"
                        svg += f'\n    <text x="{centro_x + 15}" y="{ty+10}" font-family="Arial" font-size="8" font-weight="bold" fill="#2E7D32">{ref_text}</text>'

        # B. Referencias en contactos
        for nombre, contactos in proyecto_esclavos.items():
            for contacto in contactos:
                if contacto['es_activa']:
                    maestro = proyecto_maestros.get(nombre)
                    if maestro:
                        comp_w = contacto['obj'].size[0] if hasattr(contacto.get('obj', None), 'size') else 0
                        cx = contacto['x'] + comp_w  + 5 # Aprox ancho contacto + margen
                        cy = contacto['y'] - 4
                        ref_text = f"/{maestro['hoja']}.{maestro['col']}"
                        svg += f'\n    <text x="{cx}" y="{cy}" font-family="Arial" font-size="8" font-weight="bold" fill="#2E7D32">{ref_text}</text>'

        return svg

    def highlight_selected_connection(self, connection, segment_idx=None):
        """
        Resalta visualmente SOLO el segmento seleccionado de una conexión

        Args:
            connection: La conexión a resaltar
            segment_idx: Índice del segmento específico (REQUERIDO para selección precisa)
        """
        if not hasattr(connection, 'line_ids') or not connection.line_ids:
            return

        # Solo resaltar el segmento específico seleccionado
        if segment_idx is not None and segment_idx < len(connection.line_ids):
            try:
                # Solo el segmento seleccionado se pone rojo
                self.canvas.itemconfig(connection.line_ids[segment_idx], fill="red", width=3, stipple="")
            except:
                pass
        else:
            pass
                        # Sin índice de segmento - no se puede resaltar segmento específico")

        self.canvas.config(cursor="sizing") # Cursor de redimensionamiento/desplazamiento

        # Almacenar información del segmento seleccionado
        if not hasattr(self, 'selected_segment_info'):
            self.selected_segment_info = {}
        self.selected_segment_info = {
            'connection': connection,
            'segment_idx': segment_idx,
            'line_id': connection.line_ids[segment_idx] if segment_idx < len(connection.line_ids) else None
        }

    def clear_connection_highlights(self):
        """Limpia el resaltado de todas las conexiones"""
        # Restaurar cursor normal
        self.canvas.config(cursor="")

        for connection in self.connections:
            if hasattr(connection, 'line_ids'):
                for line_id in connection.line_ids:
                    try:
                        # Restaurar color y grosor normal usando las propiedades de la conexión
                        connection_color = getattr(connection, 'line_color', self.current_line_color.get())
                        # SOLUCION: Adaptar color al tema antes de aplicar
                        adapted_color = adapt_color_for_display(connection_color, self.canvas.cget("bg"))
                        connection_width = getattr(connection, 'line_width', self.current_line_width.get())
                        connection_dash_str = getattr(connection, 'line_dash', self.current_line_dash.get())
                        parsed_dash = self.parse_dash_pattern(connection_dash_str)
                        self.canvas.itemconfig(line_id, fill=adapted_color, width=connection_width, dash=parsed_dash)
                    except:
                        pass

                # Resaltado de conexiones limpiado - cursor restaurado")

    def move_segment_with_connections(self, connection, segment_idx, dx, dy, moved_components=None):
        """
        Garantizar ortogonalidad ABSOLUTA - NUNCA líneas diagonales.

        REGLA FUNDAMENTAL: Si el movimiento causaría una línea diagonal,
        mover el componente para mantener la ortogonalidad perfecta.

        Args:
            connection: La conexión que contiene el segmento
            segment_idx: Índice del segmento a mover
            dx, dy: Desplazamiento en píxeles
            alt_pressed: Si Alt está presionado, aplicar restricciones ortogonales
        """
        # DEBUG SEGMENTOS

        if not hasattr(connection, 'line_ids') or segment_idx >= len(connection.line_ids):

            return

        try:
            # alt_pressed is not defined in the signature
            alt_pressed = False
            # Obtener coordenadas del segmento seleccionado
            target_line_id = connection.line_ids[segment_idx]
            target_coords = self.canvas.coords(target_line_id)

            if len(target_coords) < 4:
                return

            x1, y1, x2, y2 = target_coords[0], target_coords[1], target_coords[2], target_coords[3]

            # DETERMINAR ORIENTACIÓN ACTUAL CON TOLERANCIA MEJORADA
            delta_x = abs(x2 - x1)
            delta_y = abs(y2 - y1)

            # Umbral para determinar orientación (reducido para mejor precisión)
            threshold = 3

            # Detección directa sin evaluaciones múltiples
            # Caso 1: Línea horizontal clara
            if delta_y <= threshold:
                is_horizontal = True
            # Caso 2: Línea vertical clara
            elif delta_x <= threshold:
                is_horizontal = False
            # Caso 3: Determinar por diferencia mayor
            else:
                is_horizontal = delta_x > delta_y

            # Movimiento ortogonal FORZADO (reemplazando restricción de alt_pressed)
            if is_horizontal:
                # Segmento horizontal: SOLO se permite movimiento vertical
                if abs(dy) > 0:  # Solo mover si hay desplazamiento vertical
                    self.move_horizontal_segment_orthogonal(connection, segment_idx, dy, moved_components=moved_components)
            else:
                # Segmento vertical: SOLO se permite movimiento horizontal
                if abs(dx) > 0:  # Solo mover si hay desplazamiento horizontal
                    self.move_vertical_segment_orthogonal(connection, segment_idx, dx, moved_components=moved_components)

            # VERIFICACIÓN FINAL: Asegurar que NO hay líneas diagonales
            self.enforce_orthogonal_integrity(connection)

            # MARCAR como manually_modified para preservar trazado manual
            connection.manually_modified = True

            # SINCRONIZAR ESTRUCTURA DE DATOS (CRÍTICO)
            self.sync_connection_data_structure(connection)

            self.ensure_line_connections_integrity(connection)

            # DEBUG SEGMENTOS

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error in evaPr.move_segment_with_connections: {e}")

    def move_horizontal_segment_orthogonal(self, connection, segment_idx, dy, moved_components=None):
        """
        Mueve un segmento horizontal SOLO verticalmente, manteniendo ortogonalidad absoluta.

        """
        target_line_id = connection.line_ids[segment_idx]
        coords = self.canvas.coords(target_line_id)
        x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]

        # CORRECCIÓN ZOOM: Multiplicar delta mundo por zoom para desplazamientos en canvas
        zoom = getattr(self.canvas, 'zoom_level', 1.0)
        new_y1 = y1 + (dy * zoom)
        new_y2 = y2 + (dy * zoom)

        # Actualizar coordenadas manteniendo horizontalidad perfecta
        self.canvas.coords(target_line_id, x1, new_y1, x2, new_y2)

        # AJUSTAR SEGMENTOS ADYACENTES Y COMPONENTES SI ES NECESARIO
        self.adjust_connections_for_horizontal_move(connection, segment_idx, dy, moved_components=moved_components)

    def move_vertical_segment_orthogonal(self, connection, segment_idx, dx, moved_components=None):
        """
        Mueve un segmento vertical SOLO horizontalmente, manteniendo ortogonalidad absoluta.

        """
        target_line_id = connection.line_ids[segment_idx]
        coords = self.canvas.coords(target_line_id)
        x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]

        # CORRECCIÓN ZOOM: Multiplicar delta mundo por zoom para desplazamientos en canvas
        zoom = getattr(self.canvas, 'zoom_level', 1.0)
        new_x1 = x1 + (dx * zoom)
        new_x2 = x2 + (dx * zoom)

        # Actualizar coordenadas manteniendo verticalidad perfecta
        self.canvas.coords(target_line_id, new_x1, y1, new_x2, y2)

        # AJUSTAR SEGMENTOS ADYACENTES Y COMPONENTES SI ES NECESARIO
        self.adjust_connections_for_vertical_move(connection, segment_idx, dx, moved_components=moved_components)

    def adjust_connections_for_horizontal_move(self, connection, segment_idx, dy, moved_components=None):
        """
        Ajusta conexiones después de mover un segmento horizontal verticalmente.

        """
        # 1. Si es el primer segmento, mover el componente inicial
        if segment_idx == 0:
            self.adjust_start_component_for_horizontal_segment_move(connection, dy, moved_components=moved_components)

        # 2. Si es el último segmento, mover el componente final
        if segment_idx == len(connection.line_ids) - 1:
            self.adjust_end_component_for_horizontal_segment_move(connection, dy, moved_components=moved_components)

        # 3. Ajustar SIEMPRE los segmentos adyacentes para mantener la continuidad ortogonal
        self.adjust_adjacent_segments_orthogonal(connection, segment_idx)

    def adjust_connections_for_vertical_move(self, connection, segment_idx, dx, moved_components=None):
        """
        Ajusta conexiones después de mover un segmento vertical horizontalmente.

        """
        # 1. Si es el primer segmento, MOVER el componente inicial
        if segment_idx == 0:
            self.adjust_start_component_for_vertical_segment_move(connection, dx, moved_components=moved_components)

        # 2. Si es el último segmento, MOVER el componente final
        if segment_idx == len(connection.line_ids) - 1:
            self.adjust_end_component_for_vertical_segment_move(connection, dx, moved_components=moved_components)

        # 3. Ajustar SIEMPRE los segmentos adyacentes para mantener la continuidad ortogonal
        self.adjust_adjacent_segments_orthogonal(connection, segment_idx)

    def adjust_start_component_for_horizontal_segment_move(self, connection, dy, moved_components=None):
        """
        Ajusta el componente inicial cuando se mueve un segmento horizontal inicial.

        """
        start_component = connection.start_component

        # EVITAR DOBLE MOVIMIENTO: Si ya se movió en este 'tick', no repetir
        if moved_components is not None:
            if start_component in moved_components:
                return
            moved_components.add(start_component)

        start_component.move(0, dy)

        self.update_all_connections_for_component(start_component, exclude_connection=connection)

    def adjust_end_component_for_horizontal_segment_move(self, connection, dy, moved_components=None):
        """
        Ajusta el componente final cuando se mueve un segmento horizontal final.

        """
        end_component = connection.end_component

        # EVITAR DOBLE MOVIMIENTO
        if moved_components is not None:
            if end_component in moved_components:
                return
            moved_components.add(end_component)

        end_component.move(0, dy)

        self.update_all_connections_for_component(end_component, exclude_connection=connection)

    def adjust_start_component_for_vertical_segment_move(self, connection, dx, moved_components=None):
        """
        El componente inicial se mueve para seguir el segmento vertical.

        """
        start_component = connection.start_component

        # EVITAR DOBLE MOVIMIENTO
        if moved_components is not None:
            if start_component in moved_components:
                return
            moved_components.add(start_component)

        # UNIFICADO: Usar move() que tiene lógica de snap, igual que en horizontales
        start_component.move(dx, 0)

        self.update_all_connections_for_component(start_component, exclude_connection=connection)

    def adjust_end_component_for_vertical_segment_move(self, connection, dx, moved_components=None):
        """
        El componente final se mueve para seguir el segmento vertical.

        """
        end_component = connection.end_component

        # EVITAR DOBLE MOVIMIENTO
        if moved_components is not None:
            if end_component in moved_components:
                return
            moved_components.add(end_component)

        # UNIFICADO: Usar move() que tiene lógica de snap
        end_component.move(dx, 0)

        self.update_all_connections_for_component(end_component, exclude_connection=connection)

    def adjust_adjacent_segments_orthogonal(self, connection, segment_idx):
        """
        Asegura que los segmentos vecinos sigan al segmento movido
        manteniendo la ortogonalidad absoluta.
        FIX: Respeta la orientacion del segmento vecino al conectar extremos para no
        introducir diagonales que luego enforce_orthogonal_integrity corrige creando gaps.
        """
        try:
            target_line_id = connection.line_ids[segment_idx]
            target_coords = self.canvas.coords(target_line_id)
            if len(target_coords) < 4:
                return

            tx1, ty1, tx2, ty2 = target_coords

            # AJUSTAR SEGMENTO ANTERIOR (si existe)
            if segment_idx > 0:
                prev_line_id = connection.line_ids[segment_idx - 1]
                prev_coords = self.canvas.coords(prev_line_id)
                if len(prev_coords) >= 4:
                    px1, py1, px2, py2 = prev_coords
                    # Respetar orientacion del anterior para NO crear diagonales
                    if abs(py2 - py1) <= 3:
                        # Anterior HORIZONTAL: su extremo derecho toca tx1,ty1 del actual
                        # Mantiene su propia Y (horizontal) y adopta la X del actual
                        self.canvas.coords(prev_line_id, px1, ty1, tx1, ty1)
                    else:
                        # Anterior VERTICAL: su extremo inferior toca tx1,ty1 del actual
                        # Mantiene su propia X (vertical) y adopta la Y del actual
                        self.canvas.coords(prev_line_id, tx1, py1, tx1, ty1)

            # AJUSTAR SEGMENTO SIGUIENTE (si existe)
            if segment_idx < len(connection.line_ids) - 1:
                next_line_id = connection.line_ids[segment_idx + 1]
                next_coords = self.canvas.coords(next_line_id)
                if len(next_coords) >= 4:
                    nx1, ny1, nx2, ny2 = next_coords
                    # Respetar orientacion del siguiente para NO crear diagonales
                    if abs(ny2 - ny1) <= 3:
                        # Siguiente HORIZONTAL: su extremo izquierdo toca tx2,ty2 del actual
                        # Mantiene su propia Y (horizontal) y adopta la X del actual
                        self.canvas.coords(next_line_id, tx2, ty2, nx2, ty2)
                    else:
                        # Siguiente VERTICAL: su extremo superior toca tx2,ty2 del actual
                        # Mantiene su propia X (vertical) y adopta la Y del actual
                        self.canvas.coords(next_line_id, tx2, ty2, tx2, ny2)

        except Exception as e:
            print(f"Error in adjust_adjacent_segments_orthogonal: {e}")

    def update_all_connections_for_component(self, component, exclude_connection=None):
        """
        Actualiza todas las conexiones de un componente, excluyendo una específica.

        """
        for conn in self.connections:
            if conn == exclude_connection:
                continue

            if conn.start_component == component or conn.end_component == component:
                # CLON DE FASE: reconstruir geometría canónica para no deformar el clon
                if getattr(conn, 'fase_clone_axis', None):
                    if hasattr(self, 'unified_line_system') and \
                            self.unified_line_system._rebuild_fase_clone_segments(conn):
                        self.unified_line_system._redraw_connection_fast(conn)
                        continue
                # Solo actualizar si no está marcada como modificada manualmente
                if not hasattr(conn, 'manually_modified') or not conn.manually_modified:
                    self.update_manhattan_line(conn)
                else:
                    # RE-HABILITADO: Ajustar puntos finales para mantener conectividad
                    self.adjust_connection_endpoints(conn)

    def enforce_orthogonal_integrity(self, connection):
        """
        Verificación final que garantiza que NO hay líneas diagonales.

        """
        for i, line_id in enumerate(connection.line_ids):
            coords = self.canvas.coords(line_id)
            if len(coords) >= 4:
                x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]

                # UMBRAL ESTRICTO: Reducido a 0.5 para mayor precisión ortogonal
                if abs(x2 - x1) > 0.5 and abs(y2 - y1) > 0.5:
                    # ¡LÍNEA DIAGONAL DETECTADA! Corregir inmediatamente

                    # Determinar qué eje mantener basándose en la mayor diferencia
                    if abs(x2 - x1) > abs(y2 - y1):
                        # Mantener horizontal, forzar mismo Y
                        self.canvas.coords(line_id, x1, y1, x2, y1)

                    else:
                        # Mantener vertical, forzar mismo X
                        self.canvas.coords(line_id, x1, y1, x1, y2)

    def sync_connection_data_structure(self, connection):
        """
        Sincroniza la estructura de datos interna con las coordenadas visuales.

        Esto es ESENCIAL para que:
        1. La detección de segmentos funcione correctamente después del movimiento
        2. Los cambios se mantengan al mover componentes
        3. El hit-testing sea preciso

        Args:
            connection: La conexión a sincronizar
        """
        if not hasattr(connection, 'line_ids') or not hasattr(connection, 'segments'):
            return

        try:
            # Reconstruir la lista de segmentos basándose en las coordenadas visuales actuales
            new_segments = []

            for line_id in connection.line_ids:
                coords = self.canvas.coords(line_id)
                if len(coords) >= 4:
                    # Normalizar a coordenadas de mundo dividiendo por zoom_level
                    zoom = getattr(self.canvas, 'zoom_level', 1.0)
                    x1 = coords[0] / zoom
                    y1 = coords[1] / zoom
                    x2 = coords[2] / zoom
                    y2 = coords[3] / zoom

                    # Añadir segmento a la estructura de datos (en coordenadas de mundo)
                    new_segments.append(((x1, y1), (x2, y2)))

            connection.segments = new_segments

            # Solo actualizar manual_angle_points si la conexión ya es manual
            # o si estamos sincronizando después de un arrastre manual de segmento.
            # Esto evita que las líneas automáticas pierdan su "elasticidad".
            if getattr(connection, 'manually_modified', False) and len(new_segments) > 1:
                intermediate_points = []
                for i in range(len(new_segments) - 1):
                    intermediate_points.append(new_segments[i][1])
                connection.manual_angle_points = intermediate_points

        except Exception as e:

            pass
    def adjust_connection_endpoints(self, connection):
        """
        Ajusta puntos de conexión preservando segmentos pero forzando ortogonalidad.
        Preserva la forma manual pero corrige pequeñas desviaciones ortogonales.

        Args:
            connection: La conexión a ajustar
        """
        # Los clones conservan su geometría completa trasladada. No ajustar
        # únicamente los extremos en el canvas, porque eso puede crear diagonales.
        if getattr(connection, 'fase_clone_template_segments', None):
            line_system = getattr(self, 'unified_line_system', None)
            if line_system and line_system._rebuild_fase_clone_segments(connection):
                line_system._redraw_connection_fast(connection)
            return

        # DEBUG SEGMENTOS

        if not hasattr(connection, 'line_ids') or not connection.line_ids:

            return

        try:
            start_point_data = connection.start_component.get_connection_points_global()[connection.start_point_idx]
            end_point_data = connection.end_component.get_connection_points_global()[connection.end_point_idx]

            start_x, start_y, start_point = start_point_data
            end_x, end_y, end_point = end_point_data

            # Ajustar escala
            start_x *= 1.0
            start_y *= 1.0
            end_x *= 1.0
            end_y *= 1.0

            # DEBUG SEGMENTOS

            # CORRECCIÓN ZOOM: Obtener zoom_level del canvas
            zoom = getattr(self.canvas, 'zoom_level', 1.0)

            # Ajustar SOLO el primer segmento (punto de conexión inicial)
            if len(connection.line_ids) > 0:
                first_line_id = connection.line_ids[0]
                coords_antes = self.canvas.coords(first_line_id)
                if len(coords_antes) >= 4:
                    # Mantener el punto final del primer segmento, ajustar solo el inicio
                    # CORRECCIÓN ZOOM: Aplicar zoom a las coordenadas del mundo
                    coords_antes[0] = start_x * zoom
                    coords_antes[1] = start_y * zoom
                    self.canvas.coords(first_line_id, *coords_antes)

            # Ajustar SOLO el último segmento (punto de conexión final)
            if len(connection.line_ids) > 0:
                last_line_id = connection.line_ids[-1]
                coords_antes = self.canvas.coords(last_line_id)
                if len(coords_antes) >= 4:
                    # Mantener el punto inicial del último segmento, ajustar solo el final
                    # CORRECCIÓN ZOOM: Aplicar zoom a las coordenadas del mundo
                    coords_antes[-2] = end_x * zoom
                    coords_antes[-1] = end_y * zoom
                    self.canvas.coords(last_line_id, *coords_antes)

            # FORZAR ORTOGONALIDAD preservando forma general
            self.enforce_orthogonal_integrity(connection)

            # SINCRONIZAR ESTRUCTURA DE DATOS DESPUÉS DEL AJUSTE
            self.sync_connection_data_structure(connection)

            # DEBUG SEGMENTOS

        except Exception as e:
            pass

    def ensure_line_connections_integrity(self, connection):
        """
        Asegura que las líneas se mantengan conectadas a los puntos fijos
        después del movimiento de segmentos.

        Args:
            connection: La conexión a verificar y corregir
        """
        if not hasattr(connection, 'line_ids') or not connection.line_ids:
            return

        try:
            start_points = connection.start_component.get_connection_points_global()
            end_points = connection.end_component.get_connection_points_global()

            if (connection.start_point_idx < len(start_points) and
                connection.end_point_idx < len(end_points)):

                # Coordenadas de los puntos fijos (en coordenadas MUNDO)
                start_x, start_y, _ = start_points[connection.start_point_idx]
                end_x, end_y, _ = end_points[connection.end_point_idx]

                # Convertir mundo -> canvas para comparar/asignar con canvas.coords()
                # canvas.coords() devuelve coords canvas (× zoom), get_connection_points_global()
                # devuelve coords mundo. Sin esta conversión se produce desacoplamiento con zoom ≠ 1.
                zoom = getattr(self.canvas, 'zoom_level', 1.0)
                sx = start_x * zoom
                sy = start_y * zoom
                ex = end_x * zoom
                ey = end_y * zoom

                # Verificar y corregir primer segmento (debe conectar con el punto de inicio)
                if len(connection.line_ids) > 0:
                    first_line_id = connection.line_ids[0]
                    coords = self.canvas.coords(first_line_id)
                    if len(coords) >= 4:
                        if abs(coords[0] - sx) > 2 or abs(coords[1] - sy) > 2:
                            coords[0] = sx
                            coords[1] = sy
                            self.canvas.coords(first_line_id, *coords)

                # Verificar y corregir último segmento (debe conectar con el punto final)
                if len(connection.line_ids) > 0:
                    last_line_id = connection.line_ids[-1]
                    coords = self.canvas.coords(last_line_id)
                    if len(coords) >= 4:
                        if abs(coords[-2] - ex) > 2 or abs(coords[-1] - ey) > 2:
                            coords[-2] = ex
                            coords[-1] = ey
                            self.canvas.coords(last_line_id, *coords)

        except Exception as e:

            pass
    def _point_is_orphaned(self, component, point_idx):
        """
        Determina si un punto de conexión está huérfano, es decir, si NINGUNA
        conexión actual lo referencia como extremo. Los puntos huérfanos son los
        que quedan al borrar una línea de conexión y son los únicos que se pueden
        borrar con <delete> sin romper conexiones existentes.

        Args:
            component: El componente que contiene el punto
            point_idx: Índice del punto de conexión

        Returns:
            bool: True si el punto no está conectado a ninguna conexión.
        """
        if component is None or point_idx is None:
            return False
        try:
            for conn in self.connections:
                if (conn.start_component is component and conn.start_point_idx == point_idx) or \
                   (conn.end_component is component and conn.end_point_idx == point_idx):
                    return False
        except Exception as e:
            pass
        return True

    def select_connection_point(self, component, point_idx):
        """
        Selecciona visualmente un punto de conexión huérfano para que el usuario
        pueda borrarlo presionando <delete>. Solo se resalta si el punto realmente
        puede borrarse (no está referenciado por ninguna conexión).
        """
        self.clear_selected_connection_point()
        if not self._point_is_orphaned(component, point_idx):
            return
        try:
            global_points = component.get_connection_points_global()
            if point_idx >= len(global_points):
                return
            global_x, global_y, _ = global_points[point_idx]
            zoom = self.canvas.zoom_level
            radius = 8
            hl_id = self.canvas.create_oval(
                global_x * zoom - radius, global_y * zoom - radius,
                global_x * zoom + radius, global_y * zoom + radius,
                outline="#ff7f00", width=3, fill="", dash=(4, 3),
                tags="selected_connection_point_hl"
            )
            self._selected_connection_point = (component, point_idx)
            self._selected_connection_point_hl_id = hl_id
        except Exception as e:
            pass

    def clear_selected_connection_point(self):
        """Quita la selección del punto de conexión y borra su resaltado (si existe)."""
        self._selected_connection_point = None
        if self._selected_connection_point_hl_id:
            try:
                self.canvas.delete(self._selected_connection_point_hl_id)
            except Exception:
                pass
            self._selected_connection_point_hl_id = None
        # Seguridad: limpiar por tag por si quedó alguna traza visual
        try:
            self.canvas.delete("selected_connection_point_hl")
        except Exception:
            pass

    def _delete_connection_point(self, component, point_idx):
        """
        Borra un punto de conexión del componente (solo si está huérfano).

        Al quitar el punto, reajusta los índices de las conexiones existentes de
        ese mismo componente (los puntos posteriores se corren una posición).

        Args:
            component: El componente que contiene el punto
            point_idx: Índice del punto de conexión a borrar

        Returns:
            bool: True si se eliminó el punto exitosamente.
        """
        try:
            if component is None or point_idx is None:
                return False
            # El componente debe seguir vivo en el proyecto (tras undo/redo se recrean)
            if component not in self.components:
                return False
            if not hasattr(component, 'conn_points'):
                return False
            if not (0 <= point_idx < len(component.conn_points)):
                return False
            # No borrar puntos conectados a ninguna conexión
            if not self._point_is_orphaned(component, point_idx):
                return False

            # Quitar TODOS los puntos huérfanos superpuestos a la vez.
            # Los empalmes (J*) tienen 2 puntos en la MISMA coordenada; si el
            # usuario hace clic+Delete debe borrar el residuo de una sola vez,
            # no requerir un clic por cada punto superpuesto.
            global_pts = component.get_connection_points_global()
            sel_x, sel_y = global_pts[point_idx][0], global_pts[point_idx][1]
            to_remove = set()
            for j, (gx, gy, _pi) in enumerate(global_pts):
                if abs(gx - sel_x) <= 0.5 and abs(gy - sel_y) <= 0.5 and self._point_is_orphaned(component, j):
                    to_remove.add(j)
            if point_idx not in to_remove:
                to_remove.add(point_idx)

            # Reajustar índices de conexiones de este componente: un punto que
            # estaba en i queda en i - (cantidad de borrados con índice < i).
            conexiones_afectadas = []
            for conn in self.connections:
                if conn.start_component is component and conn.start_point_idx not in to_remove:
                    dec = sum(1 for r in to_remove if r < conn.start_point_idx)
                    if dec:
                        conn.start_point_idx -= dec
                        conexiones_afectadas.append(conn)
                if conn.end_component is component and conn.end_point_idx not in to_remove:
                    dec = sum(1 for r in to_remove if r < conn.end_point_idx)
                    if dec:
                        conn.end_point_idx -= dec
                        conexiones_afectadas.append(conn)

            # Quitar los puntos (de mayor a menor índice para no correr posiciones)
            for j in sorted(to_remove, reverse=True):
                if 0 <= j < len(component.conn_points):
                    component.conn_points.pop(j)

            # Empalme/unión sin puntos restantes: eliminar el empalme completo
            # (un empalme sin puntos es un residuo invisible que no se puede conectar)
            if not component.conn_points and getattr(component, 'component_type', '') in ('junction', 'empalme'):
                if component in self.components:
                    self.components.remove(component)
                if hasattr(component, 'delete'):
                    try:
                        component.delete()
                    except Exception:
                        pass
                if hasattr(self, 'update_wire_numbers'):
                    self.update_wire_numbers()
                self.is_dirty = True
                return True

            # y refrescar el flag 'connected' de los puntos restantes
            if hasattr(self, '_refresh_component_point_connected'):
                self._refresh_component_point_connected(component)
            elif hasattr(component, 'draw_connection_points'):
                component.draw_connection_points()

            # Recalcular y redibujar las conexiones cuyo índice se reajustó
            for conn in conexiones_afectadas:
                if hasattr(self, 'update_manhattan_line'):
                    self.update_manhattan_line(conn)

            if hasattr(self, 'update_wire_numbers'):
                self.update_wire_numbers()

            self.is_dirty = True
            return True
        except Exception as e:
            _report_error("Delete Connection Point", e)
            return False

    def _refresh_component_point_connected(self, component):
        """
        Recalcula el flag 'connected' de los puntos de un componente según las
        conexiones vigentes y redibuja sus halos. Se usa al borrar una línea de
        conexión para que los puntos huérfanos queden en verde (disponibles).
        """
        if component is None or not hasattr(component, 'conn_points'):
            return
        try:
            for i, point in enumerate(component.conn_points):
                point.connected = any(
                    (conn.start_component is component and conn.start_point_idx == i) or
                    (conn.end_component is component and conn.end_point_idx == i)
                    for conn in self.connections
                )
            if hasattr(component, 'draw_connection_points'):
                component.draw_connection_points()
        except Exception as e:
            pass

    def highlight_connection_point(self, component, point_idx):
        """
        Resalta visualmente un punto de conexión específico.

        Args:
            component: El componente que contiene el punto
            point_idx: Índice del punto de conexión a resaltar
        """
        try:
            # NO crear resaltados CONSTANTEMENTE para evitar figuras extra
            # Permitir solo cuando es realmente necesario para snap
            if hasattr(self, 'event_handlers_active') and self.event_handlers_active:
                # Solo permitir snap visual si realmente está en modo de conexión o manual routing
                if not (getattr(self, 'connection_mode', False) or self._is_manual_routing_active()):
                    return

            # Limpiar resaltados anteriores
            self.clear_connection_point_highlights()

            # Obtener coordenadas del punto
            global_points = component.get_connection_points_global()
            if point_idx < len(global_points):
                global_x, global_y, point_info = global_points[point_idx]

                # Usar coordenadas del mundo escaladas por zoom
                # El canvas aplica el pan nativamente, así que solo necesitamos escalar
                zoom = self.canvas.zoom_level
                canvas_x = global_x * zoom
                canvas_y = global_y * zoom

                radius = 8  # Radio del círculo de resaltado
                highlight_id = self.canvas.create_oval(
                    canvas_x - radius, canvas_y - radius,
                    canvas_x + radius, canvas_y + radius,
                    outline="lime", width=3, fill="yellow", stipple="gray25",
                    tags="connection_point_highlight"
                )

                if not hasattr(self, 'connection_point_highlights'):
                    self.connection_point_highlights = []
                self.connection_point_highlights.append(highlight_id)

        except Exception as e:

            pass
    def clear_connection_point_highlights(self):
        """
        Limpia todos los resaltados de puntos de conexión.

        """
        try:
            # Limpiar por tags
            self.canvas.delete("connection_point_highlight")

            # Limpiar lista de referencias
            if hasattr(self, 'connection_point_highlights'):
                self.connection_point_highlights.clear()

        except Exception as e:

            pass

    def _is_manual_routing_active(self) -> bool:
        """
        Verifica si el modo manual routing está activo.

        Returns:
            bool: True si el manual routing está activo
        """
        try:
            from core.unified_line_system import get_manhattan_router
            manual_router = get_manhattan_router(self)
            return manual_router.manual_active
        except:
            return False
    # EVENTOS BÁSICOS DE EMERGENCIA

    def _find_line_at_position(self, x, y):
        """
        Busca si hay una línea/segmento en la posición especificada.
        Retorna (connection, segment_idx) si encuentra una línea, None si no.
        """
        # Convertir coordenadas a canvas
        canvas_x = x
        canvas_y = y

        best_connection = None
        best_segment_idx = None
        min_distance = float('inf')
        tolerance = 15

        for connection in self.connections:
            for i, segment in enumerate(connection.segments):
                (x1, y1), (x2, y2) = segment
                canvas_x1 = x1
                canvas_y1 = y1
                canvas_x2 = x2
                canvas_y2 = y2

                dist = distance_point_to_segment(canvas_x, canvas_y, canvas_x1, canvas_y1, canvas_x2, canvas_y2)
                if dist <= tolerance and dist < min_distance:
                    min_distance = dist
                    best_connection = connection
                    best_segment_idx = i

        if best_connection:
            return (best_connection, best_segment_idx)

        return None

    def _on_basic_left_click(self, event):
        """Manejo básico del click izquierdo cuando EventHandler no está disponible"""
        # SOLUCIÓN CRÍTICA: SI EventHandler está activo, NO procesar
        if getattr(self, 'event_handlers_active', False):
            # EventHandler debe manejar todos los eventos - ignorar aquí
            return
        # COORDINADAS NATIVAS: Usar canvasx/y para precisión absoluta
        x = self.canvas.canvasx(event.x) / self.canvas.zoom_level
        y = self.canvas.canvasy(event.y) / self.canvas.zoom_level

        # Si estamos en modo preview, colocar componente
        if self.component_preview_mode and self.preview_component:
            self.place_component_at(x, y)
            return

        # Buscar componente para seleccionar
        clicked_component = self.find_component_at_position(x, y)

        if clicked_component:

            self.selected_component = clicked_component
            self.dragging = True
            self.drag_start_x = x
            self.drag_start_y = y
            self.update_selection_indicators()
        else:
            # No se encontró componente, buscar líneas/segmentos
            clicked_line = self._find_line_at_position(x, y)
            if clicked_line:
                connection, segment_idx = clicked_line

                # Limpiar selección anterior
                if hasattr(self, 'clear_connection_highlights'):
                    self.clear_connection_highlights()

                self.selected_component = None  # No hay componente seleccionado
                self.selected_segment = (connection, segment_idx)
                self.locked_segment = True

                # dragging se activará solo cuando el usuario empiece a mover el mouse
                self.drag_start_x = x
                self.drag_start_y = y
                self.dragging = False # FIX: No arrastrar al seleccionar, solo al mover

                # Resaltar la línea seleccionada
                if hasattr(self, 'highlight_selected_connection'):
                    self.highlight_selected_connection(connection, segment_idx)

            else:
                # Deseleccionar si no hay componente ni línea
                self.selected_component = None
                self.selected_segment = None
                self.locked_segment = False
                self.update_selection_indicators()

    def _on_basic_drag(self, event):
        """Manejo básico del arrastre cuando EventHandler no está disponible"""
        # SOLUCIÓN CRÍTICA: SI EventHandler está activo, NO procesarr
        if getattr(self, 'event_handlers_active', False):
            # EventHandler debe manejar todos los eventos - ignorar aquí
            return

        # Convertir coordenadas a sistema del mundo
        x, y = event_to_canvas_coords(event, self.canvas)

        # MANTENER CROSSHAIR ACTIVO durante shapes
        class WorldEvent:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        world_event = WorldEvent(x, y)
        self._draw_crosshair(world_event)

        # Solo procesar arrastre si no estamos en modo shapes
        if self.shapes_active:
            return

        # CORRECCIÓN CROSSHAIR: Convertir coordenadas a sistema del mundo
        x, y = event_to_canvas_coords(event, self.canvas)

        # CRÍTICO: Actualizar crosshair con coordenadas ya convertidas
        world_event = WorldEvent(x, y)
        self._draw_crosshair(world_event)

        if self.dragging and self.selected_component:
            dx = x - self.drag_start_x
            dy = y - self.drag_start_y

            # Verificar si es un TextComponent
            if hasattr(self.selected_component, 'canvas_id') and hasattr(self.selected_component, 'text'):
                # Es un componente de texto, usar su método de movimiento
                self.selected_component.move(dx, dy)
            else:
                # Es un componente normal CON SNAP SUAVIZADO
                new_x = self.selected_component.x + dx
                new_y = self.selected_component.y + dy

                # Esto evita los saltos intermedios
                snapped_x, snapped_y = self.snap_to_grid(new_x, new_y, tolerance=20)

                # Solo aplicar snap si el componente está realmente cerca del grid
                original_distance = ((new_x - snapped_x) ** 2 + (new_y - snapped_y) ** 2) ** 0.5
                if original_distance > 15:  # Si no está cerca, no snap
                    snapped_x, snapped_y = new_x, new_y

                self.selected_component.x = snapped_x
                self.selected_component.y = snapped_y

                # Solo el componente, no toda la pantalla
                self.selected_component.draw()
                self.update_selection_indicators()

            self.drag_start_x = x
            self.drag_start_y = y

        elif (hasattr(self, 'selected_segment') and self.selected_segment):
            # Si locked_segment está activo, la línea fue recién seleccionada
            # No mover — solo se seleccionó con el clic, no hay intención de arrastrar
            if getattr(self, 'locked_segment', False):
                return

            if not self.dragging:
                return

            connection, segment_idx = self.selected_segment

            # Calcular desplazamiento con coordenadas convertidas
            dx = x - self.drag_start_x
            dy = y - self.drag_start_y

            # Usar la función sofisticada para mover el segmento
            if hasattr(self, 'move_segment_with_connections'):
                self.move_segment_with_connections(connection, segment_idx, dx, dy)

            self.drag_start_x = x
            self.drag_start_y = y

    def _on_basic_release(self, event):
        """Manejo básico del release cuando EventHandler no está disponible"""
        # SOLUCIÓN CRÍTICA: SI EventHandler está activo, NO procesar
        if getattr(self, 'event_handlers_active', False):
            # EventHandler debe manejar todos los eventos - ignorar aquí
            return
        # SNAP TO GRID: Aplicar al soltar un componente arrastrado
        if self.dragging and self.selected_component:
            # Verificar si es un TextComponent
            if hasattr(self.selected_component, 'canvas_id') and hasattr(self.selected_component, 'text'):
                # Es un componente de texto
                current_x = self.selected_component.x
                current_y = self.selected_component.y

                snapped_x, snapped_y = self.snap_to_grid(current_x, current_y)

                if snapped_x != current_x or snapped_y != current_y:
                    self.selected_component.set_position(snapped_x, snapped_y)
            else:
                current_x = self.selected_component.x
                current_y = self.selected_component.y

                snapped_x, snapped_y = self.snap_to_grid(current_x, current_y)

                if snapped_x != current_x or snapped_y != current_y:
                    self.selected_component.x = snapped_x
                    self.selected_component.y = snapped_y

                    self.redraw_components()
                    self.update_selection_indicators()

                    for conn in self.connections:
                        if conn.start_component == self.selected_component or conn.end_component == self.selected_component:
                            # Solo actualizar si no está marcada como modificada manualmente
                            if not hasattr(conn, 'manually_modified') or not conn.manually_modified:
                                self.update_manhattan_line(conn)
                            else:
                                pass

        self.dragging = False

        # Flag para evitar bucles infinitos con shapes
        self.shapes_active = False

        # Limpiar selección de segmento después del arrastre
        if hasattr(self, 'selected_segment') and self.selected_segment:
            connection, segment_idx = self.selected_segment

            # Limpiar highlights visuales
            if hasattr(self, 'clear_connection_highlights'):
                self.clear_connection_highlights()

            # Mantener la selección para permitir múltiples movimientos
            # Siempre limpiar locked_segment al soltar el mouse
            self.locked_segment = False

    # FUNCIÓN ELIMINADA: _on_basic_motion
    # Su funcionalidad se movió a la función consolidada on_mouse_motion en event_handlers.py
    # Esto elimina redundancia y mejora el rendimiento

    def _on_double_click(self, event):
        """Maneja el evento de doble clic para editar textos"""
        if hasattr(self, 'project'):
            sheet = self.project.get_active_sheet()
            if sheet and sheet.name == "Lista de Materiales":
                return
        try:
            # CORRECCIÓN ZOOM+PAN: Compensar pan offset y zoom
            pan_offset_x = self.canvas.canvasx(0)
            pan_offset_y = self.canvas.canvasy(0)
            adjusted_x = event.x + pan_offset_x
            adjusted_y = event.y + pan_offset_y
            x = adjusted_x / self.canvas.zoom_level
            y = adjusted_y / self.canvas.zoom_level

            # Buscar componente de texto en la posición
            found_component = None
            for text_comp in self.text_components:
                if text_comp.contains_point(x, y):
                    found_component = text_comp
                    break

            if found_component:
                # Editar el texto encontrado
                self._edit_text_component(found_component)

        except Exception as e:

            pass
            import traceback
            traceback.print_exc()

    def _edit_text_component(self, text_component):
        """Edita un componente de texto existente."""
        try:
            edit_window = tk.Toplevel(self.root)
            edit_window.title("Editar Texto")
            edit_window.geometry("300x150")
            edit_window.transient(self.root)
            edit_window.grab_set()

            tk.Label(edit_window, text="Texto:").pack(pady=5)
            text_entry = tk.Entry(edit_window, width=30)
            text_entry.insert(0, text_component.text)
            text_entry.pack(pady=5)

            tk.Label(edit_window, text="Tamaño:").pack(pady=5)
            size_var = tk.IntVar(value=text_component.font_size)
            size_spinbox = tk.Spinbox(edit_window, from_=8, to=72, textvariable=size_var, width=10)
            size_spinbox.pack(pady=5)

            # Botones
            button_frame = tk.Frame(edit_window)
            button_frame.pack(pady=10)

            def apply_changes():
                new_text = text_entry.get().strip()
                if new_text:
                    text_component.text = new_text
                    text_component.font_size = size_var.get()
                    text_component.draw()
                    edit_window.destroy()
                else:
                    messagebox.showwarning("Advertencia", "El texto no puede estar vacío")

            def cancel():
                edit_window.destroy()

            tk.Button(button_frame, text="Aplicar", command=apply_changes, bg="#4CAF50", fg="white").pack(side="left", padx=5)
            tk.Button(button_frame, text="Cancelar", command=cancel, bg="#f44336", fg="white").pack(side="left", padx=5)

            # Centrar ventana
            edit_window.update_idletasks()
            x = (edit_window.winfo_screenwidth() // 2) - (edit_window.winfo_width() // 2)
            y = (edit_window.winfo_screenheight() // 2) - (edit_window.winfo_height() // 2)
            edit_window.geometry(f"+{x}+{y}")

            # Focus en el campo de texto
            text_entry.focus()
            text_entry.select_range(0, tk.END)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo editar el texto: {e}")

    # LÍNEAS DE GUÍA - Métodos para líneas que siguen al puntero
    # SIMPLE Y DIRECTA

    # FUNCIONES DE FILE OPERATIONS (MIGRADAS DESDE file_operations.py)

    def _save_to_file(self, filename):
        """Función interna para guardar a archivo .ecad (formato JSON) - MULTI-HOJA"""
        try:
            # 1. Guardar estado de TODAS las hojas antes de serializar
            # CRÍTICO FIX: Los shapes y componentes deben preservarse en TODAS las hojas
            for i, sheet in enumerate(self.project.sheets):
                if i == self.project.active_sheet_index:
                    # Para la hoja activa, guardar su estado actual completo
                    self._save_current_sheet_state(sheet)
                else:
                    # Para las hojas inactivas: SIEMPRE serializar sus elementos guardados
                    # Esto es crítico para preservar shapes que fueron modificados
                    # e incluso si la hoja nunca fue cargada como hoja activa

                    # Si tiene live_components, serializar desde los objetos vivos
                    if hasattr(sheet, 'live_components') and sheet.live_components:
                        # Reconstruir sheet.elements desde live_components
                        sheet.elements = []

                        # Serializar componentes vivos
                        for comp in sheet.live_components:
                            comp_data = comp.to_dict()
                            if "type" not in comp_data:
                                comp_data["type"] = "component"
                            sheet.elements.append(comp_data)

                        # Serializar conexiones vivas
                        sheet.connections = []
                        if hasattr(sheet, 'live_connections'):
                            for conn in sheet.live_connections:
                                conn_data = conn.to_dict(sheet.live_components)
                                conn_data["type"] = "connection"
                                sheet.connections.append(conn_data)

                        # Serializar shapes vivos
                        if hasattr(sheet, 'live_shape_objects'):
                            for shape in sheet.live_shape_objects:
                                if hasattr(shape, 'to_dict'):
                                    shape_data = shape.to_dict()
                                    sheet.elements.append(shape_data)

                        # Serializar textos
                        if hasattr(sheet, 'live_texts'):
                            for text in sheet.live_texts:
                                text_data = text.to_dict()
                                sheet.elements.append(text_data)

                        # Serializar imágenes
                        if hasattr(sheet, 'live_images'):
                            for img in sheet.live_images:
                                sheet.elements.append(img.to_dict())

                        # Serializar apantallamientos
                        if hasattr(sheet, 'live_shieldings'):
                            for sh in sheet.live_shieldings:
                                sh_data = sh.to_dict()
                                sh_data["type"] = "shielding"
                                sheet.elements.append(sh_data)
                    else:
                        # Si NO tiene live_components pero TIENE live_shape_objects
                        # (hoja que fue cargada pero los shapes se modificaron)
                        # Necesitamos serializar al menos los shapes
                        if hasattr(sheet, 'live_shape_objects') and sheet.live_shape_objects:
                            # Buscar si hay shapes en sheet.elements que necesiten actualización
                            # Primero limpiar shapes viejos de sheet.elements
                            sheet.elements = [e for e in sheet.elements if e.get("type") not in ["din_rail", "canaleta", "circle", "square", "rect", "ellipse", "line", "geom_line", "multipole_borner"]]

                            # Ahora serializar shapes vivos actualizados
                            for shape in sheet.live_shape_objects:
                                if hasattr(shape, 'to_dict'):
                                    shape_data = shape.to_dict()
                                    sheet.elements.append(shape_data)

                        # Si NO tiene live_components ni live_shape_objects
                        # dejamos sheet.elements como está (datos del archivo original)

            # 2. Serializar todas las hojas del proyecto
            sheets_data = []
            for sheet in self.project.sheets:
                # Serializar elementos de la hoja
                elements_data = []
                for element in sheet.elements:
                    # Los elementos ya están en formato dict
                    elements_data.append(element)

                # Serializar conexiones de la hoja
                connections_data = []
                for conn in sheet.connections:
                    # Las conexiones ya están en formato dict
                    connections_data.append(conn)

                # Serializar block terminals de la hoja.
                # En la hoja activa vienen de self.block_terminals; en las inactivas,
                # de live_block_terminals.
                bt_list = getattr(sheet, 'live_block_terminals', [])
                block_terminals_data = [
                    {
                        'x':          bt['x'],
                        'y':          bt['y'],
                        'filas':      bt['filas'],
                        'bornas':     bt['bornas'],
                        'label_data': bt.get('label_data', {}),
                    }
                    for bt in bt_list
                    if isinstance(bt, dict)
                ]

                sheet_dict = {
                    "name": sheet.name,
                    "zoom_level": getattr(sheet, 'zoom_level', 1.0),
                    "pan_offset": getattr(sheet, 'pan_offset', (0, 0)),
                    "elements": elements_data,
                    "connections": connections_data,
                    "block_terminals": block_terminals_data
                }
                sheets_data.append(sheet_dict)

            # 3. Crear estructura del proyecto en formato version 2.0
            project_data = {
                "version": "2.0",
                "format_version": "2.0",
                "created_by": "evaPr",
                "created_date": datetime.now().isoformat(),
                "project_name": self.project.name,
                "sheets": sheets_data,
                "active_sheet_index": self.project.active_sheet_index,
                "canvas_config": {
                    "color": self.config["canvas_color"],
                    "grid_size": self.config["grid_size"],
                    "scale_factor": getattr(self.canvas, 'scale_factor', 1.0)
                },
                # BUFFER PERSISTENTE DE CONTADORES DE ETIQUETADO
                "label_counters": getattr(self, 'label_counters', {}),
                "selected_cabinet": getattr(self.project, 'selected_cabinet', None)
            }

            # 4. Guardar archivo JSON
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, indent=2, ensure_ascii=False)

            self.current_file = filename
            self.is_dirty = False  # Marcar como sin cambios pendientes
            if hasattr(self, 'update_status_bar'):
                self.update_status_bar()  # Actualizar barra de estado

            print(f"✅ Proyecto guardado en formato .ecad (multi-hoja): {filename}")
            print(f"   📄 {len(self.project.sheets)} hoja(s) guardada(s)")
            self.set_status(f"💾 Proyecto guardado: {os.path.basename(filename)}", "green")
            show_save_success(
                self.root,
                filename,
                detail=f"{len(self.project.sheets)} hoja(s) guardada(s).",
            )
            return True

        except Exception as e:
            _report_error("Save Project", e)
            messagebox.showerror("Error", f"Error al guardar el archivo:\n{str(e)}")
            return False

    def _load_from_file(self, filename):
        """Función interna para cargar desde archivo .ecad (formato JSON multi-hoja)"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                circuit_data = json.load(f)

            # IMPORTANTE: Si hay una simulación en marcha se detiene ANTES de tocar
            # nada. El tick corre cada 100 ms sobre los componentes en memoria; seguir
            # propagando energía mientras se vacían las hojas dejaría el esquema a medias
            # (líneas energizadas y componentes activos de un proyecto que ya no existe).
            # Sin `reason` porque al final se informa "Proyecto cargado".
            self.stop_simulation_if_running()

            print(f"📄 Cargando proyecto multi-hoja...")

            self.project.name = circuit_data.get("project_name", "Proyecto Cargado")
            self.project.sheets = []  # Limpiar hojas existentes

            # CENTRALIZADO: Reiniciar estado antes de cargar
            self.reset_app_state()

            for sheet_data in circuit_data.get("sheets", []):
                from models.project_data import Sheet
                sheet = Sheet.from_dict(sheet_data)
                sheet.elements = sheet_data.get("elements", [])
                # Autosanado: archivos guardados por versiones anteriores podían
                # traer "simulation_state" (Ctrl+S con la simulación en marcha). Se
                # descarta al cargar para que el esquema abra en reposo y el próximo
                # guardado escriba el archivo limpio.
                for elem in sheet.elements:
                    if isinstance(elem, dict):
                        elem.pop("simulation_state", None)
                sheet.connections = sheet_data.get("connections", [])
                # Restaurar block terminals guardados en el archivo
                sheet.live_block_terminals = sheet_data.get("block_terminals", [])
                self.project.sheets.append(sheet)

            # Restaurar contadores de etiquetas si existen
            if "label_counters" in circuit_data:
                self.label_counters = circuit_data["label_counters"]

            # Restaurar gabinete seleccionado
            if "selected_cabinet" in circuit_data:
                self.project.selected_cabinet = circuit_data["selected_cabinet"]

            # Restaurar índice activo (limitado al número real de hojas del archivo)
            active_index = circuit_data.get("active_sheet_index", 0)
            if not isinstance(active_index, int) or not 0 <= active_index < len(self.project.sheets):
                active_index = 0
            self.project.active_sheet_index = active_index

            active_sheet = self.project.get_active_sheet()
            if active_sheet:
                self._load_sheet_state(active_sheet)

                # CRÍTICO FIX: Inicializar live_components solo DESPUÉS de cargar
                # En este punto, self.components, self.shapes, etc. tienen los datos correctos del archivo
                active_sheet.live_components = self.components[:]
                active_sheet.live_connections = self.connections[:]
                active_sheet.live_texts = self.text_components[:]
                active_sheet.live_images = getattr(self, 'image_components', [])[:]
                active_sheet.live_shape_objects = self.shape_manager.shapes[:]
                active_sheet.live_shapes = self.shapes[:]
                if hasattr(self, 'shielding_manager'):
                    active_sheet.live_shieldings = self.shielding_manager.shieldings[:]

                _bt_data = getattr(active_sheet, 'live_block_terminals', [])
                if _bt_data:
                    _eh = getattr(self, 'event_handler', None)
                    if _eh and hasattr(_eh, '_place_block_terminal'):
                        self.block_terminals = []
                        for bt in _bt_data:
                            try:
                                _eh._place_block_terminal(
                                    bt['x'], bt['y'],
                                    bt['filas'], bt['bornas'],
                                    label_data=bt.get('label_data', {}),
                                    auto_open=False,
                                )
                            except Exception as e:
                                print(f"[BT] Error redibujando al cargar: {e}")
                        active_sheet.live_block_terminals = list(self.block_terminals)
                        print(f"[BT] {len(self.block_terminals)} block terminal(s) redibujado(s) al cargar archivo")
                # Las hojas inactivas cargarán usando _load_sheet_state() cuando se hagan activas
                # Esto asegura que siempre cargan desde sheet.elements actualizado

            # Visitar todas las hojas para que _load_sheet_state las inicialice
            # correctamente (componentes con tamaños reales, conexiones, shapes).
            # Al final se regresa a la hoja original del archivo.
            for i in range(len(self.project.sheets)):
                if i != active_index:
                    self.switch_to_sheet(i)
            # Regresar a la hoja activa original
            self.switch_to_sheet(active_index)

            self.update_sheet_list_ui()
            self.current_file = filename

            # Limpiar el registro de cambios (el proceso de dibujo de la carga puede provocar falsos cambios)
            if hasattr(self, 'undo_manager'):
                self.undo_manager.clear()
            self.is_dirty = False

            if hasattr(self, 'update_status_bar'):
                self.update_status_bar()

            print(f"✅ Proyecto cargado: {len(self.project.sheets)} hoja(s) "
                  f"(hoja activa: '{self.project.get_active_sheet().name}')")
            self.set_status(f"📂 Proyecto cargado: {os.path.basename(filename)}", "green")
            show_load_success(
                self.root,
                filename,
                detail=f"{len(self.project.sheets)} hoja(s) cargada(s).",
            )

        except Exception as e:
            messagebox.showerror("Error", f"Error al cargar el archivo:\n{str(e)}")

    def create_shape_at_position(self, shape_type: str, x: float, y: float):
        """
        Crea una forma geométrica usando el ShapeEditor

        Args:
            shape_type: Tipo de forma ('circle', 'square', 'rectangle', 'ellipse')
            x: Coordenada X del centro
            y: Coordenada Y del centro

        Returns:
            Forma creada o None si falla
        """
        try:
            # Usar el ShapeEditor que ya está implementado
            if hasattr(self.shape_manager, 'editor') and self.shape_manager.editor:
                editor = self.shape_manager.editor

                # Mapear nombres de formas al formato esperado por ShapeEditor
                shape_mapping = {
                    'circle': 'circle',
                    'square': 'square',
                    'rectangle': 'rect',
                    'ellipse': 'ellipse'
                }

                mapped_type = shape_mapping.get(shape_type, shape_type)

                editor.current_mode = mapped_type
                editor.start_x = x
                editor.start_y = y
                editor.current_size = 50  # Tamaño por defecto

                editor._create_shape()

                # La forma ya se agrega automáticamente al manager en _create_shape
                created_shape = editor.selected_shape

                if hasattr(self, 'set_status'):
                    shape_names = {
                        'circle': 'Círculo',
                        'square': 'Cuadrado',
                        'rectangle': 'Rectángulo',
                        'ellipse': 'Elipse'
                    }
                    shape_name = shape_names.get(shape_type, 'Forma')
                    self.set_status(f"✅ {shape_name} creado en ({x:.0f}, {y:.0f})", "green")

                return created_shape
            else:
                print("ERROR: ShapeEditor no disponible")
                return None

        except Exception as e:
            print(f"Error creando forma: {e}")
            import traceback
            traceback.print_exc()
            if hasattr(self, 'set_status'):
                self.set_status(f"❌ Error creando forma: {str(e)}", "red")
            return None

    def find_shape_at_position(self, x: float, y: float):
        """
        Encuentra la forma en la posición especificada

        Args:
            x: Coordenada X
            y: Coordenada Y

        Returns:
            Forma encontrada o None
        """
        return self.shape_manager.find_shape_at_position(x, y)

    def redraw_all_shapes(self):
        """Redibuja todas las formas geométricas"""
        try:
            self.shape_manager.draw_all(self.canvas)
        except Exception as e:
            pass

    def get_selected_shape(self):
        """Retorna la forma actualmente seleccionada"""
        return self.shape_manager.selected_shape

    def select_shape(self, shape):
        """
        Selecciona una forma específica

        Args:
            shape: Forma a seleccionar
        """
        self.shape_manager.select_shape(shape)
        self.redraw_all_shapes()

    def _simulacion_bloqueada(self):
        """
        Los planos unifilares no se pueden simular: no tienen la topología de nodos
        que necesita la propagación de energía.

        Returns:
            bool: True si la hoja activa es unifilar (y ya se avisó al usuario)
        """
        current_sheet = self.project.get_active_sheet()
        if getattr(current_sheet, 'name', '').startswith('Plano Unifilar'):
            messagebox.showwarning("Simulación no disponible", "No se puede simular ni verificar un Plano Unifilar. Cambie al esquema multifilar para simular el circuito eléctrico.")
            return True
        return False

    def start_simulation(self):
        """
        Arranca o reanuda la simulación (atajo F5).

        A diferencia de toggle_simulation(), NUNCA pausa: si ya está corriendo no hace
        nada, para que F5 sea inequívoco frente a F6 (detener). Si está pausada, la
        reanuda, que es lo que espera quien pulse "play".
        """
        if self._simulacion_bloqueada():
            return

        ctl = self.simulation_controller
        if ctl.is_running and ctl.is_paused:
            ctl.resume()
        elif not ctl.is_running:
            ctl.start()
        else:
            # Ya está en marcha: no se toca nada (F5 no es un toggle).
            return

        self.simulation_running = ctl.is_running

    def toggle_simulation(self):
        """Alterna entre Play y Pause de la simulación."""
        if self._simulacion_bloqueada():
            return

        self.simulation_controller.toggle()
        self.simulation_running = self.simulation_controller.is_running

    def stop_simulation(self):
        """Detiene la simulación completamente."""
        self.simulation_controller.stop()
        self.simulation_running = False

    def stop_simulation_if_running(self, reason=None):
        """
        Detiene la simulación sólo si está activa.
        Se invoca antes de operaciones que destruyen el estado del circuito en memoria
        (cargar un archivo, crear un proyecto nuevo, cerrar): si el tick siguiera vivo
        seguiría propagando energía sobre componentes que ya no existen.

        Returns:
            bool: True si había una simulación activa y se detuvo
        """
        controller = getattr(self, 'simulation_controller', None)
        if controller is None or not controller.is_running:
            return False

        controller.stop(keep_error_message=True)
        self.simulation_running = False
        if reason and hasattr(self, 'set_status'):
            self.set_status(f"⏹️ Simulación detenida: {reason}", "black")
        return True

    # FIN MÉTODOS DE SIMULACIÓN

if __name__ == "__main__":
    root = tk.Tk(className="evaPr")
    root.title("evaPr ⚡ Diagramador ELECTRICO")
    root.withdraw()  # Ocultar mientras el splash está activo

    base_dir = get_app_dir()
    splash_path = base_dir / "svgs" / "splash.svg"
    splash_screen = SplashScreen(root, splash_path)

    root.update()  # Forzar dibujado inicial

    # AVISO LEGAL OBLIGATORIO: se muestra antes de construir la interfaz.
    # Solo vuelve a aparecer si cambia DISCLAIMER_VERSION (config/disclaimer.py).
    from ui.disclaimer import ensure_disclaimer_accepted
    if not ensure_disclaimer_accepted(root):
        root.destroy()
        raise SystemExit(1)

    # Configuración de ventana principal (se aplicará después del splash)
    def show_main_window():
        try:
            root.wm_state('normal')
            root.attributes('-zoomed', True)
        except:
            root.geometry("1200x800")
        root.deiconify()
        if splash_screen:
            splash_screen.close()

    # Programar la muestra de la ventana ANTES de construir la interfaz: así los
    # 1500 ms son un mínimo de splash que se solapan con el trabajo real, en vez
    # de añadirse a él (antes, la ventana no aparecía hasta 1500 ms después de
    # terminar de construir todo).
    root.after(1500, show_main_window)

    app = PlanoElectrico(root)

    # Botones personalizados
    if hasattr(app, 'custom_buttons_bar'):
        app._create_custom_buttons()

    root.mainloop()

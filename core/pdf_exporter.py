"""
Exportador PDF 
"""
import os
import json
import logging
import math
import re
import tempfile
import unicodedata
import html
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from config.settings import DEFAULT_CONFIG, AppConstants, save_config
from utils.utility_functions import sort_bom_entries, sort_bom_references
from ui.export_dialog import confirm_overwrite, show_export_success

_log = logging.getLogger("evaPr")

try:
    from reportlab.lib.pagesizes import A4, A3
    from reportlab.lib.units import mm
    REPORTLAB_SUPPORT = True
except ImportError:
    REPORTLAB_SUPPORT = False

# Familia tipográfica usada al exportar texto a SVG/PDF. Debe coincidir con la
# que usa el lienzo (AppConstants.DEFAULT_FONT_FAMILY) para que las métricas
# del glifo y por tanto su posición y ancho sean los mismos en ambos medios.
TEXT_FONT_FAMILY = "Arial, Helvetica, sans-serif"

class PdfExporter:
    def __init__(self, app):
        # Mantener referencia a la aplicación principal para delegación
        self.app = app
        # Indica si ReportLab está disponible para exportación PDF
        self.REPORTLAB_SUPPORT = REPORTLAB_SUPPORT
        # Plantilla PDF cargada (None si no hay plantilla)
        self._pdf_template = None
        # Cachés de datos de informes durante una exportación.  Recorre todo el
        # proyecto entero, y antes se recalculaba tres veces por hoja (para
        # contar páginas, para paginar y para dibujar).
        self._report_cache = None
        # PdfReader de la plantilla.  La plantilla no cambia durante una
        # exportación pero se reparseaba dos veces por página (dimensiones y
        # campos de formulario), y el clonado resolvía los 708 objetos otra vez.
        self._template_reader_cache = None
        self._template_reader_key = None

    def _template_pdf_reader(self, path):
        """PdfReader de la plantilla, reutilizado entre páginas.

        Reconstruirlo cuesta ~30 ms de parseo y, sobre todo, obliga al clonado a
        volver a resolver los ~700 objetos del documento en cada página.
        """
        if not path:
            return None
        try:
            st = os.stat(path)
            key = (str(path), st.st_mtime_ns, st.st_size)
        except OSError:
            key = (str(path), None, None)

        if key != self._template_reader_key:
            from pypdf import PdfReader

            self._template_reader_cache = PdfReader(str(path))
            self._template_reader_key = key
        return self._template_reader_cache

    def _bom_rows(self):
        """Filas de la Lista de Materiales, calculadas una sola vez por exportación."""
        if self._report_cache is None:
            self._report_cache = {}
        if "bom" not in self._report_cache:
            from core.reports import BOMGenerator

            bom_gen = BOMGenerator(self.project)
            all_components = bom_gen._collect_components_from_project(self.project)
            grouped_data = bom_gen._group_data(all_components, project=self.project)
            bom_gen._inject_infrastructure_items(self.app, grouped_data)

            rows = []
            for desc, specs in sort_bom_entries(grouped_data):
                names = sort_bom_references(grouped_data[(desc, specs)])
                rows.append((", ".join(names), desc, specs, str(len(names))))
            self._report_cache["bom"] = rows
        return self._report_cache["bom"]

    def _wiring_rows(self):
        """Filas de la Tabla de Cableado, calculadas una sola vez por exportación."""
        if self._report_cache is None:
            self._report_cache = {}
        if "wiring" not in self._report_cache:
            from core.wiring_table_generator import WiringTableGenerator

            self._report_cache["wiring"] = WiringTableGenerator(
                self.project
            ).get_wiring_data()
        return self._report_cache["wiring"]

    def _report_pages(self, kind, page_size, orientation):
        """Páginas físicas que ocupa una hoja de informe, sin recalcular los datos."""
        rows = self._bom_rows() if kind == "bom" else self._wiring_rows()
        if not rows:
            return 1

        width_pt, height_pt = self._get_page_dimensions(page_size, orientation)
        margin_pt, cajin_height_pt, header_gap_pt, _, _ = self._get_page_layout_metrics()
        settings = self._get_table_settings(
            "bom_table" if kind == "bom" else "wiring_table"
        )
        header_height = settings.get("header_height", 40)
        row_height = settings.get("row_height", 30 if kind == "bom" else 25)
        available_h = height_pt - (margin_pt + header_gap_pt) - cajin_height_pt - margin_pt
        rows_per_page = max(1, int((available_h - header_height) / row_height))
        return math.ceil(len(rows) / rows_per_page)

    def _resolve_pdf_template_path(self, template_path):
        """Resuelve la ruta de la plantilla .pte o retorna None si no se especifica ninguna."""
        if not template_path:
            return None

        base_dir = Path(__file__).resolve().parent.parent
        resolved = Path(os.path.expanduser(template_path))
        if not resolved.suffix:
            resolved = resolved.with_suffix(".pte")
        if not resolved.is_absolute():
            resolved = base_dir / resolved
        return resolved

    def _load_pdf_template(self, force_reload=False):
        """Carga la plantilla PDF seleccionada o la plantilla por defecto."""
        if self._pdf_template is not None and not force_reload:
            return self._pdf_template

        pdf_config = self.app.config.get("pdf_config", DEFAULT_CONFIG["pdf_config"]) if hasattr(self, 'app') else DEFAULT_CONFIG["pdf_config"]
        template_path = self._resolve_pdf_template_path(pdf_config.get("pdf_template", ""))
        # Si no se especifica plantilla, no usar marco/cajetín.
        if template_path is None:
            self._pdf_template = None
            return None

        # If the template path does not exist or can't be read, do NOT fallback
        # to an in-code default. Absence of a template means no marco/cajetín.
        if not template_path.exists():
            print(f"⚠️ Plantilla PDF no encontrada en {template_path}. Exportando sin marco/cajetín.")
            self._pdf_template = None
            return None

        try:
            with open(template_path, "r", encoding="utf-8") as f:
                self._pdf_template = json.load(f)
                self._is_pdf_template_file = False
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Comprobar si es un PDF renombrado a .pte
            try:
                with open(template_path, "rb") as f:
                    header = f.read(5)
                    if header == b"%PDF-":
                        self._pdf_template = {}
                        self._is_pdf_template_file = True
                        self._pdf_template_path = template_path
                        print(f"✅ Plantilla detectada como PDF binario: {template_path}")
                        return self._pdf_template
            except:
                pass

            print(f"⚠️ Error cargando plantilla PDF (ni JSON ni PDF válido) {template_path}")
            self._pdf_template = None
            self._is_pdf_template_file = False

        return self._pdf_template

    def _read_svg_file(self, full_path):
        """Reads and caches SVG file contents to optimize exports."""
        if not hasattr(self, '_svg_file_cache'):
            self._svg_file_cache = {}
        full_path_str = str(full_path)
        if full_path_str not in self._svg_file_cache:
            if not full_path.exists():
                self._svg_file_cache[full_path_str] = None
            else:
                with open(full_path, 'r', encoding='utf-8') as f:
                    self._svg_file_cache[full_path_str] = f.read()
        return self._svg_file_cache[full_path_str]

    def _get_template_value(self, *keys, default=None):
        template = self._load_pdf_template()
        value = template
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def _build_svg_style_block(self, default_styles=None):
        styles = self._get_template_value("styles", default={}) or {}
        merged = {} if default_styles is None else {**default_styles}
        merged.update(styles)
        style_lines = [f".{name} {{ {rules} }}" for name, rules in merged.items()]
        return "\n    ".join(style_lines)

    def _get_page_dimensions(self, page_size, orientation):
        template = self._load_pdf_template()
        page_sizes = self._get_template_value("page", "sizes", default={})
        format_info = page_sizes.get(page_size, {})
        size = format_info.get(orientation)
        if isinstance(size, (list, tuple)) and len(size) == 2:
            return tuple(size)
        if page_size == "A3":
            return (1190.55, 841.89) if orientation == "horizontal" else (841.89, 1190.55)
        return (841.89, 595.28) if orientation == "horizontal" else (595.28, 841.89)

    def _get_page_layout_metrics(self):
        margin_pt = self._get_template_value("page", "margin_pt", default=14.17)
        cajetin_height_pt = self._get_template_value("page", "cajetin", "height_mm", default=15) * mm
        header_gap_pt = self._get_template_value("page", "header_gap_pt", default=40)
        canvas_width = self._get_template_value("page", "canvas_width", default=1200)
        content_scale = self._get_template_value("page", "content_scale", default=0.95)
        return margin_pt, cajetin_height_pt, header_gap_pt, canvas_width, content_scale

    def _generate_frame_svg(self, width_pt, height_pt, margin_pt, force=False):
        """Genera el marco principal del PDF usando configuración de plantilla."""
        template = self._load_pdf_template()
        if not template:
            if not force:
                return ""
            frame = {}
        else:
            frame = self._get_template_value("frame", default={}) or {}
            if not frame.get("enabled", True):
                return ""

        stroke_color = frame.get("stroke_color", "black")
        stroke_width = frame.get("stroke_width", 1)
        fill = frame.get("fill", "none")
        rect_svg = f'''
  <!-- MARCO PRINCIPAL -->
  <rect x="{margin_pt}" y="{margin_pt}"
        width="{width_pt - 2 * margin_pt}" height="{height_pt - 2 * margin_pt}"
        fill="{fill}" stroke="{stroke_color}" stroke-width="{stroke_width}" />'''
        return rect_svg

    def _generate_divisions_svg(self, width_pt, height_pt, margin_pt):
        """Genera líneas de división internas (paneles) según la plantilla."""
        template = self._load_pdf_template()
        if not template:
            return ""

        divisions = self._get_template_value("frame", "divisions", default=None)
        if not divisions:
            return ""

        cols = int(divisions.get("cols", 1))
        rows = int(divisions.get("rows", 1))
        line_width = divisions.get("line_width", 0.5)
        stroke = divisions.get("stroke_color", "black")

        inner_x = margin_pt
        inner_y = margin_pt
        inner_w = width_pt - 2 * margin_pt
        inner_h = height_pt - 2 * margin_pt

        svg = ""
        # Vertical divisions
        if cols > 1:
            for i in range(1, cols):
                x = inner_x + inner_w * (i / cols)
                svg += f'\n  <line x1="{x}" y1="{inner_y}" x2="{x}" y2="{inner_y + inner_h}" stroke="{stroke}" stroke-width="{line_width}" />'

        # Horizontal divisions
        if rows > 1:
            for j in range(1, rows):
                y = inner_y + inner_h * (j / rows)
                svg += f'\n  <line x1="{inner_x}" y1="{y}" x2="{inner_x + inner_w}" y2="{y}" stroke="{stroke}" stroke-width="{line_width}" />'

        return svg

    def _get_table_settings(self, table_type):
        return self._get_template_value(table_type, default={}) or {}

    def _get_pdf_scale_ratio(self, pdf_config=None):
        """Devuelve el factor de escala definido en pdf_config['escala']."""
        if pdf_config is None:
            try:
                pdf_config = self.config.get("pdf_config", DEFAULT_CONFIG["pdf_config"]) if hasattr(self, 'config') else DEFAULT_CONFIG["pdf_config"]
            except Exception:
                pdf_config = DEFAULT_CONFIG["pdf_config"]

        scale_text = str(pdf_config.get("escala", "1:1") or "1:1").strip()
        match = re.match(r'^\s*([0-9]+(?:\.[0-9]+)?)\s*[:/]\s*([0-9]+(?:\.[0-9]+)?)\s*$', scale_text)
        if match:
            try:
                left = float(match.group(1))
                right = float(match.group(2))
                if right != 0:
                    return left / right
            except Exception:
                pass
        try:
            return float(scale_text)
        except Exception:
            return 1.0

    def _generate_pdf(self, filename):
        """Genera el archivo PDF con marco técnico - TODAS LAS HOJAS"""
        try:
            # Verificar que la configuración está disponible
            if not hasattr(self, 'config') or self.config is None:
                print("⚠️ Usando configuración por defecto")
                pdf_config = DEFAULT_CONFIG["pdf_config"]
            else:
                pdf_config = self.config.get("pdf_config", DEFAULT_CONFIG["pdf_config"])
        except Exception as e:
            print(f"⚠️ Error accediendo a configuración: {e}")
            pdf_config = DEFAULT_CONFIG["pdf_config"]

        if pdf_config.get("formato", "A4") == "A3":
            pagesize = A3
        else:
            pagesize = A4

        if pdf_config.get("orientacion", "vertical") == "horizontal":
            pagesize = (pagesize[1], pagesize[0])  # Intercambiar ancho y alto

        original_sheet_index = self.project.active_sheet_index
        try:
            # Cada exportación parte de datos frescos de informes.
            self._report_cache = None
            self._template_reader_cache = None
            self._template_reader_key = None
            self.app._is_exporting_pdf = True
            if hasattr(self.app, 'set_status'):
                self.app.set_status("📄 Exportando PDF... Por favor espere", "red", duration=None)
                # Sin esto la barra de estado no se repinta hasta terminar y el
                # usuario ve la ventana congelada sin ninguna señal.
                try:
                    self.app.root.update_idletasks()
                except Exception:
                    pass

            # Generar PDF con todas las hojas
            # Determinar formato y orientación
            page_format = "A3" if pdf_config.get("formato", "A4") == "A3" else "A4"
            page_orientation = "horizontal" if pdf_config.get("orientacion", "vertical") == "horizontal" else "vertical"

            # Generar PDF con todas las hojas
            marco_success = self._generate_pdf_all_sheets(filename, page_format, page_orientation)

            if not marco_success:
                raise Exception(f"Error generando PDF vectorial. Asegúrese de tener 'cairosvg' instalado. Detalles: {getattr(self, '_last_error', 'Error desconocido')}")

            if hasattr(self.app, 'set_status'):
                self.app.set_status("✅ PDF exportado con éxito", "green", duration=5000)
            print(f"✅ PDF vectorial generado exitosamente con {len(self.project.sheets)} hoja(s): {filename}")
            return  # Salir exitosamente

        except Exception as e:
            print(f"Error en generación PDF: {e}")
            if hasattr(self.app, 'set_status'):
                self.app.set_status("❌ Error exportando PDF", "red", duration=None)
            raise Exception(f"Error en proceso de generación PDF: {e}")
        finally:
            self.app._is_exporting_pdf = False
            # Restaurar hoja activa original
            try:
                self.switch_to_sheet(original_sheet_index)
            except Exception as restore_error:
                print(f"⚠️ No se pudo restaurar la hoja original tras exportación: {restore_error}")

    def _get_project_total_pages(self, page_size="A4", orientation="vertical"):
        """Calcula el número total de páginas físicas que tendrá el PDF final."""
        total_pages = 0
        original_sheet_index = self.project.active_sheet_index

        try:
            for i, sheet in enumerate(self.project.sheets):
                if sheet.name == "Lista de Materiales":
                    total_pages += self._report_pages("bom", page_size, orientation)
                elif sheet.name == "Tabla de Cableado":
                    total_pages += self._report_pages("wiring", page_size, orientation)
                else:
                    total_pages += 1
        finally:
            try:
                if hasattr(self.canvas, 'winfo_exists') and self.canvas.winfo_exists():
                    self.switch_to_sheet(original_sheet_index)
                else:
                    print("⚠️ Canvas inválido al restaurar hoja original después de calcular páginas PDF")
            except Exception as restore_error:
                print(f"⚠️ No se pudo restaurar la hoja original después de calcular páginas PDF: {restore_error}")

        return total_pages

    def _generate_pdf_all_sheets(self, filename, page_format="A4", orientation="vertical"):
        """
        Genera PDF con todas las hojas del proyecto
        Cada hoja se exporta en una página separada del PDF
        """
        try:
            import os
            import tempfile

            try:
                from pypdf import PdfWriter
            except ImportError:
                # Fallback: exportar solo la hoja actual
                return self._generate_pdf_marco_vectorial(filename, page_format, orientation)

            original_pan_x = self.canvas.canvasx(0)
            original_pan_y = self.canvas.canvasy(0)
            original_scrollregion = self.canvas.cget('scrollregion')
            original_sheet_index = self.project.active_sheet_index

            # 1. PRE-CALCULAR TOTAL DE PÁGINAS FÍSICAS
            total_pages = self._get_project_total_pages(page_format, orientation)
            print(f"📄 DEBUG: Total de páginas físicas calculadas: {total_pages}")

            # Si solo hay una hoja, no necesitamos generar archivos temporales ni combinar PDFs.
            if len(self.project.sheets) == 1:
                return self._generate_pdf_marco_vectorial(filename, page_format, orientation)

            temp_files = []
            current_page_index = 0

            for sheet_index, sheet in enumerate(self.project.sheets):
                self.switch_to_sheet(sheet_index)

                # Resetear pan a (0, 0) para exportación consistente
                self.canvas.xview_moveto(0)
                self.canvas.yview_moveto(0)

                temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf')
                os.close(temp_fd)
                temp_files.append(temp_path)

                # Determinar cuántas páginas generará esta hoja (datos ya cacheados)
                pages_this_sheet = 1
                if sheet.name == "Lista de Materiales":
                    pages_this_sheet = self._report_pages("bom", page_format, orientation)
                elif sheet.name == "Tabla de Cableado":
                    pages_this_sheet = self._report_pages("wiring", page_format, orientation)

                # Generar PDF para esta hoja (pasando el índice de página global)
                success = self._generate_pdf_marco_vectorial(
                    temp_path,
                    page_format,
                    orientation,
                    sheet_index=current_page_index, # Pasamos el índice de página global
                    total_sheets=total_pages        # Pasamos el total de páginas físicas
                )

                # Incrementar el índice de página global según cuántas páginas ocupó esta hoja
                current_page_index += pages_this_sheet

                if not success:
                    # Limpiar archivos temporales en caso de error
                    for temp_file in temp_files:
                        try: os.remove(temp_file)
                        except: pass
                    try:
                        if hasattr(self.canvas, 'winfo_exists') and self.canvas.winfo_exists():
                            self.canvas.config(scrollregion=original_scrollregion)
                            self.canvas.xview_moveto(0)
                            self.canvas.yview_moveto(0)
                            self.switch_to_sheet(original_sheet_index)
                        else:
                            print("⚠️ Canvas inválido durante restauración tras error de exportación")
                    except Exception as restore_error:
                        print(f"⚠️ No se pudo restaurar la hoja original tras error de exportación: {restore_error}")
                    return False

            # Combinar todos los PDFs
            if len(temp_files) == 1:
                import shutil
                shutil.move(temp_files[0], filename)
            else:
                merger = PdfWriter()
                for temp_file in temp_files:
                    merger.append(temp_file)
                with open(filename, 'wb') as output_file:
                    merger.write(output_file)
                merger.close()

            # Limpiar
            for temp_file in temp_files:
                try: os.remove(temp_file)
                except: pass

            # Restaurar
            try:
                if hasattr(self.canvas, 'winfo_exists') and self.canvas.winfo_exists():
                    self.canvas.config(scrollregion=original_scrollregion)
                    self.canvas.xview_moveto(0)
                    self.canvas.yview_moveto(0)
                    self.switch_to_sheet(original_sheet_index)
                else:
                    print("⚠️ Canvas inválido al restaurar la hoja original tras exportación")
            except Exception as restore_error:
                print(f"⚠️ No se pudo restaurar la hoja original tras exportación: {restore_error}")

            return True

        except Exception as e:
            print(f"Error generando PDF con todas las hojas: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _generate_pdf_marco_vectorial(self, filename, page_size="A4", orientation="vertical", sheet_index=0, total_sheets=1):
        """
        Genera marco y cajetín PDF usando SVG vectorial
        Evita ReportLab que causa borrosidad - Implementación basada en bugs.py

        Args:
            filename: Ruta del archivo PDF a generar
            page_size: Tamaño de página ("A3" o "A4")
            orientation: Orientación ("horizontal" o "vertical")
            sheet_index: Índice de la hoja actual (0-based)
            total_sheets: Número total de hojas en el proyecto
        """
        # 0. ESPECIAL: Si es la hoja de lista de materiales, usar generador paginado
        active_sheet = self.project.get_active_sheet()
        if active_sheet and active_sheet.name == "Lista de Materiales":
             return self._generate_pdf_bom_paginated(filename, page_size, orientation, sheet_index, total_sheets)

        # 0b. ESPECIAL: Si es la Tabla de Cableado, usar generador paginado
        if active_sheet and active_sheet.name == "Tabla de Cableado":
             return self._generate_pdf_wiring_table_paginated(filename, page_size, orientation, sheet_index, total_sheets)

        try:
            if hasattr(self, 'config') and self.config:
                pdf_config = self.config.get("pdf_config", {})
            else:
                pdf_config = DEFAULT_CONFIG["pdf_config"]
        except:
            pdf_config = DEFAULT_CONFIG["pdf_config"]

        pdf_scale_ratio = self._get_pdf_scale_ratio(pdf_config)
        template = self._load_pdf_template(force_reload=False)

        # MODO PDF-PLANTILLA: Si el .pte es un PDF binario, usar como fondo
        if getattr(self, '_is_pdf_template_file', False) and not self._sheet_without_cajetin():
            return self._generate_pdf_with_pdf_template(
                filename, page_size, orientation, sheet_index, total_sheets
            )

        width_pt, height_pt = self._get_page_dimensions(page_size, orientation)
        margin_pt, cajin_height_pt, header_gap_pt, canvas_width, content_scale = self._get_page_layout_metrics()

        style_block = self._build_svg_style_block({
            "coordenadas": "font-family: Helvetica, Arial, sans-serif; font-weight: bold; font-size: 10pt; fill: black;",
            "cajin": "font-family: Helvetica, Arial, sans-serif; font-size: 6pt; fill: black;",
            "label": "font-weight: normal; fill: black;",
            "valor": "font-weight: bold; fill: black;",
            "component-text": "font-family: Helvetica, Arial, sans-serif; font-size: 8pt; fill: black;"
        })

        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" 
     xmlns:xlink="http://www.w3.org/1999/xlink"
     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns:cc="http://creativecommons.org/ns#"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     width="{width_pt}pt" 
     height="{height_pt}pt" 
     viewBox="0 0 {width_pt} {height_pt}">
  
  <defs>
    <!-- Estilos CSS para texto -->
    <style>
    {style_block}
    </style>
    <!-- Marcadores de flecha para líneas de cotas -->
    <marker id="arrow-end" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L8,3 z" fill="black" />
    </marker>
    <marker id="arrow-start" markerWidth="8" markerHeight="8" refX="2" refY="3" orient="auto-start-reverse" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L8,3 z" fill="black" />
    </marker>
  </defs>
  
{self._generate_frame_svg(width_pt, height_pt, margin_pt, force=self._sheet_without_cajetin())}
{self._generate_divisions_svg(width_pt, height_pt, margin_pt)}
  <!-- 2. COORDENADAS EN MÁRGENES -->''' 

        # Calcular factores de escala y offsets para alinear las coordenadas con el dibujo
        canvas_width = self.canvas.winfo_width() or canvas_width
        canvas_height = self.canvas.winfo_height() or 600

        available_width = width_pt - 2 * margin_pt
        available_height = height_pt - 2 * margin_pt - cajin_height_pt

        scale_x = available_width / canvas_width
        scale_y = available_height / canvas_height
        scale_factor = min(scale_x, scale_y) * content_scale * pdf_scale_ratio

        content_width = canvas_width * scale_factor
        content_height = canvas_height * scale_factor

        offset_x = margin_pt + (available_width - content_width) / 2
        offset_y = margin_pt + cajin_height_pt - header_gap_pt

        # Generar coordenadas, cajetín o número de página
        if template or self._sheet_without_cajetin():
            svg_content += self._generate_coordenadas_horizontales_svg(width_pt, height_pt, margin_pt, scale_factor, offset_x)
            svg_content += self._generate_coordenadas_verticales_svg(width_pt, height_pt, margin_pt, scale_factor, offset_y)
            if self._sheet_without_cajetin():
                svg_content += self._generate_page_number_svg(width_pt, height_pt, margin_pt, sheet_index, total_sheets)
            else:
                svg_content += self._generate_cajetin_svg(
                    width_pt, height_pt, margin_pt, pdf_config,
                    sheet_index=sheet_index, total_sheets=total_sheets
                )

        # 3. CONTENIDO DEL CIRCUITO (VECTORIAL) - siempre se renderiza
        svg_content += self._generate_circuit_svg_content(width_pt, height_pt, margin_pt, pdf_scale_ratio)

        # Cerrar SVG
        svg_content += '''
</svg>'''

        # Detectar soporte SVG
        CAIROSVG_SUPPORT = False
        try:
            import cairosvg
            CAIROSVG_SUPPORT = True
        except ImportError:
            pass

        if not CAIROSVG_SUPPORT:
            raise Exception("Biblioteca 'cairosvg' no encontrada. Es necesaria para exportación vectorial.")

        try:
            # Confiar en cairosvg para validar SVG (más rápido que ET.fromstring)
            cairosvg.svg2pdf(
                bytestring=svg_content.encode('utf-8'),
                write_to=filename,
                parent_width=width_pt,
                parent_height=height_pt,
                background_color='white' if self._sheet_without_cajetin() else None
            )
            print(f"✅ Marco PDF vectorial generado: {filename}")
            return True
        except Exception as e:
            self._last_error = str(e)
            print(f"❌ Error generando marco PDF vectorial: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _generate_pdf_with_pdf_template(self, filename, page_size, orientation, sheet_index=0, total_sheets=1):
        """
        Genera el PDF usando un archivo PDF como plantilla de fondo.
        El PDF de la plantilla se usa como 'papel pre-impreso' y el
        circuito SVG se superpone encima como capa transparente.
        """
        try:
            import io
            import cairosvg
            from pypdf import PdfWriter, PdfReader
        except ImportError as e:
            self._last_error = f"Dependencia faltante: {e}"
            print(f"❌ {self._last_error}")
            return False

        template_path = str(getattr(self, '_pdf_template_path', None))
        if not template_path or not os.path.exists(template_path):
            self._last_error = "Ruta de plantilla PDF no encontrada."
            return False

        try:
            if hasattr(self, 'config') and self.config:
                pdf_config = self.config.get("pdf_config", {})
            else:
                pdf_config = DEFAULT_CONFIG["pdf_config"]
        except:
            pdf_config = DEFAULT_CONFIG["pdf_config"]

        try:
            # 1. Leer plantilla para obtener dimensiones reales de página
            reader = self._template_pdf_reader(template_path)
            template_page = reader.pages[0]
            media_box = template_page.mediabox
            width_pt  = float(media_box.width)
            height_pt = float(media_box.height)

            # 2. Generar SVG SOLO con el circuito (sin marco ni cajetín JSON)
            #    Usamos márgenes estándar para que el contenido no tape el cajetín
            margin_pt = 28.35   # ~1 cm en puntos
            cajin_height_pt = 42.52  # ~15 mm en puntos

            # No usar update_idletasks para exportación
            pdf_scale_ratio = self._get_pdf_scale_ratio(pdf_config)
            svg_circuit = self._generate_circuit_svg_content(width_pt, height_pt, margin_pt, pdf_scale_ratio)

            # Reutilizar el mismo bloque de estilos y defs que el SVG principal
            style_block = self._build_svg_style_block({
                "component-text": "font-family: Helvetica, Arial, sans-serif; font-size: 8pt;"
            })

            svg_overlay = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns:cc="http://creativecommons.org/ns#"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     width="{width_pt}pt" height="{height_pt}pt"
     viewBox="0 0 {width_pt} {height_pt}">
  <defs>
    <style>
    {style_block}
    </style>
    <marker id="arrow-end" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L8,3 z" fill="black" />
    </marker>
    <marker id="arrow-start" markerWidth="8" markerHeight="8" refX="2" refY="3" orient="auto-start-reverse" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L8,3 z" fill="black" />
    </marker>
  </defs>
{svg_circuit}
</svg>'''

            # 3. Convertir el SVG del circuito a PDF temporal
            circuit_pdf_io = io.BytesIO()

            try:
                ET.fromstring(svg_overlay.encode('utf-8'))
            except ET.ParseError as pe:
                self._last_error = f"SVG parse error: {pe}"
                print(self._last_error)
                return False

            cairosvg.svg2pdf(
                bytestring=svg_overlay.encode('utf-8'),
                write_to=circuit_pdf_io,
                parent_width=width_pt,
                parent_height=height_pt,
                background_color='transparent'
            )
            circuit_pdf_io.seek(0)

            # 4. Rellenar campos de formulario en un PDF temporal
            writer = PdfWriter()
            writer.clone_document_from_reader(reader)

            page = writer.pages[0]
            self._apply_pdf_form_field_values(writer, page, pdf_config, sheet_index, total_sheets)

            fd_filled, path_filled_pdf = tempfile.mkstemp(suffix='_filled.pdf')
            os.close(fd_filled)
            with open(path_filled_pdf, 'wb') as f_out:
                writer.write(f_out)

            # 5. Aplanar el PDF con campos usando cairosvg (textos visibles, no editables)
            fd_flat, path_flat_pdf = tempfile.mkstemp(suffix='_flat.pdf')
            os.close(fd_flat)
            self._flatten_pdf_with_cairosvg(path_filled_pdf, path_flat_pdf)

            # 6. Superponer circuito SVG sobre la plantilla aplanada
            flat_reader = PdfReader(path_flat_pdf)
            flat_page = flat_reader.pages[0]

            circuit_page = PdfReader(circuit_pdf_io).pages[0]
            flat_page.merge_page(circuit_page)

            writer2 = PdfWriter()
            writer2.add_page(flat_page)
            with open(filename, 'wb') as out_f:
                writer2.write(out_f)

            # Limpieza
            for tmp in (path_filled_pdf, path_flat_pdf):
                try:
                    os.remove(tmp)
                except:
                    pass

            print(f"✅ PDF generado con plantilla aplanada + circuito: {filename}")
            return True

        except Exception as e:
            self._last_error = str(e)
            print(f"❌ Error en _generate_pdf_with_pdf_template: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _generate_pdf_paginated(
            self, filename, page_size, orientation, sheet_index, total_sheets,
            rows, settings_key, page_svg_method, msgs):
        """
        Genera un PDF de tabla (BOM o Cableado) PAGINADO compartido.
        Si la lista es muy larga, crea múltiples páginas.
        """
        try:
            print(msgs["start"])

            # Configuración PDF para superponer plantilla binaria si corresponde
            try:
                pdf_config = self.config.get("pdf_config", DEFAULT_CONFIG["pdf_config"])
            except Exception:
                pdf_config = DEFAULT_CONFIG["pdf_config"]

            width_pt, height_pt = self._get_page_dimensions(page_size, orientation)
            margin_pt, cajin_height_pt, header_gap_pt, _, _ = self._get_page_layout_metrics()
            table_settings = self._get_table_settings(settings_key)
            header_height = table_settings.get("header_height", 40)
            row_height = table_settings.get("row_height", 30)

            start_y = margin_pt + header_gap_pt
            available_h = height_pt - start_y - cajin_height_pt - margin_pt

            print(msgs["height"].format(available_h=available_h, n=len(rows)))

            # Calcular cuántas filas caben por página
            rows_per_page = int((available_h - header_height) / row_height)
            if rows_per_page < 1: rows_per_page = 1

            # Dividir en páginas
            pages_data = []
            # Si no hay filas (lista vacía), generar al menos una página vacía
            if not rows:
                pages_data.append([])
            else:
                for i in range(0, len(rows), rows_per_page):
                    pages_data.append(rows[i:i + rows_per_page])

            print(msgs["divided"].format(n=len(pages_data)))

            # Generar PDFs temporales
            temp_pdfs = []
            import tempfile, os

            from pypdf import PdfWriter, PdfReader
            import cairosvg

            template_reader = None
            if getattr(self, '_is_pdf_template_file', False) and not self._sheet_without_cajetin():
                template_path = str(getattr(self, '_pdf_template_path', None))
                if template_path and os.path.exists(template_path):
                    try:
                        template_reader = self._template_pdf_reader(template_path)
                    except Exception as e:
                        print(msgs["template_warn"].format(e=e))

            for i, page_rows in enumerate(pages_data):
                # Usar el índice de página global (sheet_index + i)
                # total_sheets ya es el total de páginas físicas del proyecto

                svg_content = page_svg_method(
                    width_pt, height_pt, margin_pt,
                    page_rows,
                    sheet_index + i, total_sheets, # Índice de página incremental
                    sub_page_index=i, total_sub_pages=len(pages_data)
                )

                temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf')
                os.close(temp_fd)

                try:
                    ET.fromstring(svg_content.encode('utf-8'))
                except ET.ParseError as pe:
                    temp_fd, temp_path = tempfile.mkstemp(suffix='.svg')
                    with os.fdopen(temp_fd, 'wb') as f:
                        f.write(svg_content.encode('utf-8'))
                    self._last_error = f"SVG parse error: {pe}. SVG saved to: {temp_path}"
                    print(self._last_error)
                    return False
                cairosvg.svg2pdf(bytestring=svg_content.encode('utf-8'), write_to=temp_path, background_color='white')

                # Si es una plantilla PDF de fondo, fusionar encima de ella
                if template_reader is not None:
                    try:
                        writer = PdfWriter()
                        writer.clone_document_from_reader(template_reader)
                        page = writer.pages[0]
                        self._apply_pdf_form_field_values(writer, page, pdf_config, sheet_index + i, total_sheets)

                        fd_filled, path_filled_pdf = tempfile.mkstemp(suffix='_filled.pdf')
                        os.close(fd_filled)
                        with open(path_filled_pdf, 'wb') as f_out:
                            writer.write(f_out)

                        fd_flat, path_flat_pdf = tempfile.mkstemp(suffix='_flat.pdf')
                        os.close(fd_flat)
                        self._flatten_pdf_with_cairosvg(path_filled_pdf, path_flat_pdf)

                        flat_reader = PdfReader(path_flat_pdf)
                        flat_page = flat_reader.pages[0]

                        table_page = PdfReader(temp_path).pages[0]
                        flat_page.merge_page(table_page)

                        writer2 = PdfWriter()
                        writer2.add_page(flat_page)

                        # Sobrescribir temp_path con el PDF fusionado
                        with open(temp_path, 'wb') as out_f:
                            writer2.write(out_f)

                        # Limpiar temporales de esta página
                        for tmp in (path_filled_pdf, path_flat_pdf):
                            try: os.remove(tmp)
                            except: pass
                    except Exception as overlay_err:
                        print(msgs["overlay_err"].format(i=i, e=overlay_err))

                temp_pdfs.append(temp_path)

            if len(temp_pdfs) == 1:
                # Solo una página, renombrar/mover al destino final
                import shutil
                shutil.move(temp_pdfs[0], filename)
            else:
                # Múltiples páginas
                merger = PdfWriter()
                for pdf in temp_pdfs:
                    merger.append(pdf)
                # Escribir en filename directamente
                merger.write(filename)
                merger.close()

                # Limpiar
                for pdf in temp_pdfs:
                    try: os.remove(pdf)
                    except: pass

            print(msgs["end"].format(filename=filename))
            return True

        except Exception as e:
            print(msgs["fail"].format(e=e))
            import traceback
            traceback.print_exc()
            return False

    def _generate_pdf_bom_paginated(self, filename, page_size, orientation, sheet_index, total_sheets):
        """
        Genera el PDF de la Lista de Materiales PAGINADO.
        Si la lista es muy larga, crea múltiples páginas.
        """
        try:
            # 1. Datos de la lista de materiales (cacheados por esta exportación)
            rows = self._bom_rows()

            msgs = {
                "start": "📄 Generando PDF BOM Paginado...",
                "height": "📏 Altura disponible BOM: {available_h}, filas: {n}",
                "divided": "📄 Dividido en {n} páginas",
                "template_warn": "⚠️ No se pudo leer la plantilla PDF para BOM: {e}",
                "overlay_err": "⚠️ Error overlaying PDF template para página BOM {i}: {e}",
                "end": "✅ PDF BOM paginado generado: {filename}",
                "fail": "❌ Error generando BOM paginado: {e}",
            }
            return self._generate_pdf_paginated(
                filename, page_size, orientation, sheet_index, total_sheets,
                rows, "bom_table", self._generate_bom_page_svg, msgs)

        except Exception as e:
            print(f"❌ Error generando BOM paginado: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _generate_pdf_wiring_table_paginated(self, filename, page_size, orientation, sheet_index, total_sheets):
        """
        Genera el PDF de la Tabla de Cableado PAGINADO.
        Si la lista es muy larga, crea múltiples páginas para no invadir el cajetín.
        """
        try:
            # 1. Datos de la tabla de cableado (cacheados por esta exportación)
            rows = self._wiring_rows()

            msgs = {
                "start": "📄 Generando PDF Tabla de Cableado Paginado...",
                "height": "📏 Altura disponible Cableado: {available_h}, conexiones: {n}",
                "divided": "📄 Tabla de Cableado dividida en {n} páginas",
                "template_warn": "⚠️ No se pudo leer la plantilla PDF para Tabla de Cableado: {e}",
                "overlay_err": "⚠️ Error overlaying PDF template para Tabla de Cableado página {i}: {e}",
                "end": "✅ PDF Tabla de Cableado paginado generado: {filename}",
                "fail": "❌ Error generando tabla de cableado paginada: {e}",
            }
            return self._generate_pdf_paginated(
                filename, page_size, orientation, sheet_index, total_sheets,
                rows, "wiring_table", self._generate_wiring_table_page_svg, msgs)

        except Exception as e:
            print(f"❌ Error generando tabla de cableado paginada: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _generate_wiring_table_page_svg(self, width_pt, height_pt, margin_pt, rows, sheet_index, total_sheets, sub_page_index, total_sub_pages):
        """Genera el SVG para UNA página de la tabla de cableado"""
        class _SVGBuilder:
            __slots__ = ('parts',)
            def __init__(self):
                self.parts = []
            def __iadd__(self, other):
                self.parts.append(str(other))
                return self
            def __str__(self):
                return ''.join(self.parts)

        svg = _SVGBuilder()

        try:
             pdf_config = self.config.get("pdf_config", DEFAULT_CONFIG["pdf_config"])
        except:
             pdf_config = DEFAULT_CONFIG["pdf_config"]

        template = self._load_pdf_template()
        wiring_settings = self._get_table_settings("wiring_table")
        style_block = self._build_svg_style_block({
            "table-header": "font-family: Helvetica, Arial, sans-serif; font-weight: bold; font-size: 8pt; fill: black;",
            "table-row": "font-family: Helvetica, Arial, sans-serif; font-size: 7.5pt; fill: black;",
            "coordenadas": "font-family: Helvetica, Arial, sans-serif; font-weight: bold; font-size: 10pt; fill: black;",
            "cajin": "font-family: Helvetica, Arial, sans-serif; font-size: 6pt; fill: black;",
            "label": "font-weight: normal; fill: black;",
            "valor": "font-weight: bold; fill: black;"
        })

        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width_pt}pt" height="{height_pt}pt" viewBox="0 0 {width_pt} {height_pt}">
  <style>
    {style_block}
  </style>
  
{self._generate_frame_svg(width_pt, height_pt, margin_pt, force=True)}
'''
        # Calcular factores de escala para coordenadas
        canvas_width = self._get_template_value("page", "canvas_width", default=1200)
        _, cajin_height_pt, header_gap_pt, _, content_scale = self._get_page_layout_metrics()
        available_width = width_pt - 2 * margin_pt
        available_height = height_pt - 2 * margin_pt - cajin_height_pt
        scale_factor = (available_width / canvas_width) * content_scale
        offset_x = margin_pt + (available_width - canvas_width * scale_factor) / 2
        offset_y = margin_pt + cajin_height_pt - header_gap_pt

        # Coordenadas y Cajetín — solo si la plantilla lo define
        template = self._load_pdf_template()
        if template or self._sheet_without_cajetin():
            svg += self._generate_coordenadas_horizontales_svg(width_pt, height_pt, margin_pt, scale_factor, offset_x)
            svg += self._generate_coordenadas_verticales_svg(width_pt, height_pt, margin_pt, scale_factor, offset_y)
            svg += self._generate_page_number_svg(width_pt, height_pt, margin_pt, sheet_index, total_sheets)
        # DIBUJAR TABLA DE CABLEADO
        side_padding = wiring_settings.get("side_padding", 10)
        inner_margin = wiring_settings.get("inner_margin", 20)
        column_ratios = wiring_settings.get("column_widths", [0.05, 0.08, 0.15, 0.08, 0.15, 0.08, 0.08, 0.08, 0.25])
        table_y = margin_pt + header_gap_pt
        table_w = width_pt - 2 * margin_pt - inner_margin
        table_x = margin_pt + side_padding

        header_h = wiring_settings.get("header_height", 35)
        row_h = wiring_settings.get("row_height", 25)

        col_w = [table_w * float(r) for r in column_ratios]
        col_x = [table_x]
        for i in range(len(col_w)-1):
            col_x.append(col_x[-1] + col_w[i])

        svg += f'<rect x="{table_x}" y="{table_y}" width="{table_w}" height="{header_h}" fill="#2c3e50" stroke="black" stroke-width="1"/>'

        headers = wiring_settings.get("headers", ["HILO", "HOJA", "ORIGEN COMP.", "TERM.", "DESTINO COMP.", "TERM.", "COLOR", "SEC.", "NOTAS TÉCNICAS"])
        for i, h in enumerate(headers):
            cx = col_x[i] + col_w[i]/2
            cy = table_y + header_h/2 + 3
            svg += f'<text x="{cx}" y="{cy}" text-anchor="middle" fill="white" class="table-header">{h}</text>'
            if i > 0:
                svg += f'<line x1="{col_x[i]}" y1="{table_y}" x2="{col_x[i]}" y2="{table_y + header_h}" stroke="white" stroke-width="0.5"/>'

        # Rows
        curr_y = table_y + header_h
        for idx, row in enumerate(rows):
            fill = "#f8f9fa" if idx % 2 == 0 else "white"
            svg += f'<rect x="{table_x}" y="{curr_y}" width="{table_w}" height="{row_h}" fill="{fill}" stroke="black" stroke-width="0.5"/>'

            vals = [row.get('hilo',''), row.get('hoja',''), row.get('o_n',''), row.get('o_t',''),
                    row.get('d_n',''), row.get('d_t',''), "Plano", row.get('sec',''), row.get('nota','')]

            for i, val in enumerate(vals):
                cx = col_x[i] + col_w[i]/2
                cy = curr_y + row_h/2 + 3

                # Truncado
                max_chars = int((col_w[i] - 4) / 4.5)
                d_val = str(val)
                if len(d_val) > max_chars: d_val = d_val[:max_chars-2] + ".."

                color = "#d35400" if "DOBLE" in d_val else "black"
                svg += f'<text x="{cx}" y="{cy}" text-anchor="middle" fill="{color}" class="table-row">{d_val}</text>'
                if i > 0:
                    svg += f'<line x1="{col_x[i]}" y1="{curr_y}" x2="{col_x[i]}" y2="{curr_y + row_h}" stroke="#ddd" stroke-width="0.5"/>'

            curr_y += row_h

        svg += "</svg>"
        return str(svg)

    def _generate_bom_page_svg(self, width_pt, height_pt, margin_pt, rows, sheet_index, total_sheets, sub_page_index, total_sub_pages):
        """Genera el SVG para UNA página de la lista de materiales"""
        class _SVGBuilder:
            __slots__ = ('parts',)
            def __init__(self):
                self.parts = []
            def __iadd__(self, other):
                self.parts.append(str(other))
                return self
            def __str__(self):
                return ''.join(self.parts)

        svg = _SVGBuilder()

        try:
             pdf_config = self.config.get("pdf_config", DEFAULT_CONFIG["pdf_config"])
        except:
             pdf_config = DEFAULT_CONFIG["pdf_config"]

        template = self._load_pdf_template()
        bom_settings = self._get_table_settings("bom_table")
        style_block = self._build_svg_style_block({
            "bom-header": "font-family: Helvetica, Arial, sans-serif; font-weight: bold; font-size: 10pt; fill: black;",
            "bom-row": "font-family: Helvetica, Arial, sans-serif; font-size: 9pt; fill: black;",
            "coordenadas": "font-family: Helvetica, Arial, sans-serif; font-weight: bold; font-size: 10pt; fill: black;",
            "cajin": "font-family: Helvetica, Arial, sans-serif; font-size: 6pt; fill: black;",
            "label": "font-weight: normal; fill: black;",
            "valor": "font-weight: bold; fill: black;"
        })

        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width_pt}pt" height="{height_pt}pt" viewBox="0 0 {width_pt} {height_pt}">
  <style>
    {style_block}
  </style>
  
{self._generate_frame_svg(width_pt, height_pt, margin_pt, force=True)}
'''
        # Calcular factores de escala y offsets (igual que en _generate_pdf_marco_vectorial)
        # Eliminar update_idletasks - no es necesario durante exportación
        canvas_width = self.canvas.winfo_width() or self._get_template_value("page", "canvas_width", default=1200)
        canvas_height = self.canvas.winfo_height() or 600

        _, cajin_height_pt, header_gap_pt, _, content_scale = self._get_page_layout_metrics()
        available_width = width_pt - 2 * margin_pt
        available_height = height_pt - 2 * margin_pt - cajin_height_pt

        scale_x = available_width / canvas_width
        scale_y = available_height / canvas_height
        scale_factor = min(scale_x, scale_y) * content_scale

        content_width = canvas_width * scale_factor
        content_height = canvas_height * scale_factor

        offset_x = margin_pt + (available_width - content_width) / 2
        offset_y = margin_pt + cajin_height_pt - header_gap_pt

        # Coordenadas y Cajetín — solo si la plantilla lo define
        template = self._load_pdf_template()
        if template or self._sheet_without_cajetin():
            svg += self._generate_coordenadas_horizontales_svg(width_pt, height_pt, margin_pt, scale_factor, offset_x)
            svg += self._generate_coordenadas_verticales_svg(width_pt, height_pt, margin_pt, scale_factor, offset_y)
            svg += self._generate_page_number_svg(width_pt, height_pt, margin_pt, sheet_index, total_sheets)
        # DIBUJAR TABLA BOM (SOLO PDF)

        side_padding = bom_settings.get("side_padding", 20)
        inner_margin = bom_settings.get("inner_margin", 40)
        column_ratios = bom_settings.get("column_widths", [0.2, 0.3, 0.4, 0.1])

        table_y = margin_pt + header_gap_pt
        table_w = width_pt - 2 * margin_pt - inner_margin
        table_x = margin_pt + side_padding

        header_h = bom_settings.get("header_height", 30)
        row_h = bom_settings.get("row_height", 30)

        col_w = [table_w * float(r) for r in column_ratios]
        col_x = [table_x]
        for i in range(len(col_w)-1):
            col_x.append(col_x[-1] + col_w[i])

        # Header Background
        svg += f'''
  <rect x="{table_x}" y="{table_y}" width="{table_w}" height="{header_h}" fill="#CFD8DC" stroke="black" stroke-width="1"/>
'''
        headers = bom_settings.get("headers", ["REFERENCIA", "DESCRIPCIÓN", "ESPECIFICACIONES", "CANT."])
        for i, h in enumerate(headers):
            # Centrado en columna
            cx = col_x[i] + col_w[i]/2
            cy = table_y + header_h/2 + 4 # Ajuste baseline
            svg += f'''<text x="{cx}" y="{cy}" text-anchor="middle" class="bom-header">{h}</text>'''
            # Linea vertical separadora (excepto primero)
            if i > 0:
                svg += f'''<line x1="{col_x[i]}" y1="{table_y}" x2="{col_x[i]}" y2="{table_y + header_h}" stroke="black" stroke-width="1"/>'''

        # Rows
        curr_y = table_y + header_h

        for row in rows:
            # Row Background
            svg += f'''
  <rect x="{table_x}" y="{curr_y}" width="{table_w}" height="{row_h}" fill="none" stroke="black" stroke-width="1"/>'''

            # Row Text
            refs, desc, specs, qty = row
            row_vals = [refs, desc, specs, qty]

            for i, val in enumerate(row_vals):
                cx = col_x[i] + col_w[i]/2
                if i == 3: # Cantidad centrada
                    text_x = cx
                    anchor = "middle"
                else: # Resto alineado izq con padding
                    text_x = col_x[i] + 5
                    anchor = "start"

                cy = curr_y + row_h/2 + 3

                # Truncar texto si es muy largo para SVG (básico)
                # Estimación: 6px char width
                max_chars = int((col_w[i] - 10) / 6)
                display_val = str(val)
                if len(display_val) > max_chars:
                    display_val = display_val[:max_chars-3] + "..."

                svg += f'''<text x="{text_x}" y="{cy}" text-anchor="{anchor}" class="bom-row">{display_val}</text>'''

                # Separadores verticales
                if i > 0:
                     svg += f'''<line x1="{col_x[i]}" y1="{curr_y}" x2="{col_x[i]}" y2="{curr_y + row_h}" stroke="gray" stroke-width="0.5"/>'''

            curr_y += row_h

        svg += "</svg>"
        return str(svg)

    def _generate_circuit_svg_content(self, width_pt, height_pt, margin_pt, pdf_scale_ratio=1.0):
        """Genera el contenido del circuito en formato SVG"""
        class _SVGBuilder:
            __slots__ = ('parts',)
            def __init__(self):
                self.parts = []
            def __iadd__(self, other):
                self.parts.append(str(other))
                return self
            def __str__(self):
                return ''.join(self.parts)

        svg = _SVGBuilder()
        try:
            # Evitar update_idletasks durante exportación
            canvas_width = self.canvas.winfo_width() or 800
            canvas_height = self.canvas.winfo_height() or 600

            # Altura del cajetín (reservar espacio)
            _, cajin_height_pt, header_gap_pt, _, content_scale = self._get_page_layout_metrics()

            # Área disponible para el circuito
            available_width = width_pt - 2 * margin_pt
            available_height = height_pt - 2 * margin_pt - cajin_height_pt

            # Factor de escala (mantener aspecto)
            scale_x = available_width / canvas_width
            scale_y = available_height / canvas_height
            scale_factor = min(scale_x, scale_y) * content_scale * pdf_scale_ratio  # Escala según plantilla + configuración PDF

            # Centering logic
            active_sheet = self.project.get_active_sheet()
            if active_sheet and active_sheet.name == "Hoja de Gabinete 2D":
                # 1. Bounding box calculation for 2D sheet content only (shapes and components)
                min_x, min_y = float('inf'), float('inf')
                max_x, max_y = float('-inf'), float('-inf')
                has_elements = False

                # Shapes (Cabinet structures, plates, rails, etc.)
                if hasattr(self, 'shape_manager') and self.shape_manager:
                    for shape in self.shape_manager.shapes:
                        bbox = shape.get_bbox() # (x1, y1, x2, y2)
                        min_x, min_y = min(min_x, bbox[0]), min(min_y, bbox[1])
                        max_x, max_y = max(max_x, bbox[2]), max(max_y, bbox[3])
                        has_elements = True

                # Components (Devices on rails)
                for comp in self.components:
                    w, h = comp.size
                    min_x, min_y = min(min_x, comp.x), min(min_y, comp.y)
                    max_x, max_y = max(max_x, comp.x + w), max(max_y, comp.y + h)
                    has_elements = True

                # Block Terminals (Special 2D modules)
                if hasattr(self, 'block_terminals') and self.block_terminals:
                    from handlers.event_handlers import EventHandler
                    for bt in self.block_terminals:
                        svg_key = bt.get('svg_key', '2F')
                        bornas = bt.get('bornas', 5)
                        module_w = EventHandler.BLOCK_MODULE_W
                        module_h = EventHandler.BLOCK_HEIGHT.get(svg_key, 45)
                        total_w = module_w * bornas

                        bx = bt['x'] - total_w / 2
                        by = bt['y'] - module_h / 2
                        min_x, min_y = min(min_x, bx), min(min_y, by)
                        max_x, max_y = max(max_x, bx + total_w), max(max_y, by + module_h)
                        has_elements = True

                if has_elements:
                    content_w = max_x - min_x
                    content_h = max_y - min_y

                    # Recalculate scale_factor to fit this specific content
                    scale_x_c = available_width / (content_w or 1)
                    scale_y_c = available_height / (content_h or 1)
                    scale_factor = min(scale_x_c, scale_y_c) * content_scale * pdf_scale_ratio

                    # Offsets to perfectly center the content's bounding box center in the PDF center
                    offset_x = margin_pt + (available_width - content_w * scale_factor) / 2 - min_x * scale_factor
                    offset_y = margin_pt + cajin_height_pt - header_gap_pt + (available_height - content_h * scale_factor) / 2 - min_y * scale_factor
                else:
                    # Fallback if no elements
                    offset_x = margin_pt + (available_width - canvas_width * scale_factor) / 2
                    offset_y = margin_pt + cajin_height_pt - header_gap_pt
            else:
                # Standard centering logic for other sheets (center based on fixed canvas size)
                content_width = canvas_width * scale_factor
                content_height = canvas_height * scale_factor
                offset_x = margin_pt + (available_width - content_width) / 2
                offset_y = margin_pt + cajin_height_pt - header_gap_pt

            # Grupo principal del circuito con transformación
            svg += f'''
  <!-- GRUPO CIRCUITO -->
  <g transform="translate({offset_x}, {offset_y}) scale({scale_factor})">'''

            # 1. CONEXIONES (primero para que queden debajo de componentes)
            for connection in self.connections:
                if hasattr(connection, 'segments') and connection.segments:
                    color = getattr(connection, 'line_color', 'black')
                    if not color or not isinstance(color, str): color = 'black'

                    # Ancho (ajustado para que no sea muy fino al escalar)
                    width = getattr(connection, 'line_width', 1.0)
                    try: width = float(width)
                    except: width = 1.0

                    # Asegurar grosor mínimo visual
                    stroke_width = max(1.0, width)

                    # Soporte para líneas punteadas (dash)
                    dash_array = ""
                    line_dash = getattr(connection, 'line_dash', None)

                    # Intentar obtener dash del objeto canvas si no está en la conexión o es string vacío
                    if (not line_dash or line_dash == "") and hasattr(connection, 'line_ids') and connection.line_ids:
                        try:
                            line_dash = self.canvas.itemcget(connection.line_ids[0], 'dash')
                        except:
                            pass

                    # Convertir formato tkinter dash a SVG stroke-dasharray
                    if line_dash and line_dash != "":
                        # Tkinter usa tuplas o strings como (4, 4) o "4 2"
                        # SVG necesita "4,4"
                        try:
                            dash_list = []
                            if isinstance(line_dash, (tuple, list)):
                                dash_list = [float(x) for x in line_dash]
                            elif isinstance(line_dash, str) and line_dash.strip():
                                # Parsear correctamente strings como "4 2" o "4,2"
                                import re
                                numbers = re.findall(r'\d+', line_dash)
                                dash_list = [float(x) for x in numbers] if numbers else []

                            # Escalar el patrón de dash para que sea visible en PDF
                            # Multiplicamos por un factor para asegurar visibilidad (y por scale_factor)
                            if dash_list:
                                # Factor de corrección visual para PDF (los dashes suelen verse muy finos)
                                dash_scale = scale_factor * 2.0
                                scaled_dashes = [str(max(1.0, d * dash_scale)) for d in dash_list]
                                dash_array = f'stroke-dasharray="{",".join(scaled_dashes)}"'
                        except Exception as e:
                            _log.debug("Error parseando dash: %s (line_dash=%s)", e, line_dash)
                            pass

                    for segment in connection.segments:
                        start, end = segment
                        svg += f'''
    <line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" 
          stroke="{color}" stroke-width="{stroke_width}" stroke-linecap="round" {dash_array} />'''

            for comp in self.components:
                # SALTAR EMPALMES: No renderizar JunctionComponent en PDF (deben ser invisibles)
                from models.junction_component import JunctionComponent
                if isinstance(comp, JunctionComponent):
                    continue  # Saltar completamente

                # Posición y rotación
                x, y = comp.x, comp.y
                w, h = comp.size
                rot = getattr(comp, 'rotation', 0)

                # Grupo del componente
                # Transformación: trasladar al centro, rotar, trasladar de vuelta (si fuera necesario)
                # Pero aquí rotamos alrededor del centro del componente
                cx = x + w/2
                cy = y + h/2

                svg += f'''
    <g transform="translate({x}, {y})">'''

                if rot:
                    svg += f'''
      <g transform="rotate({rot}, {w/2}, {h/2})">'''

                # Intentar cargar SVG del componente
                svg_embedded = False
                if getattr(comp, 'svg_path', None) and getattr(comp, 'svg_file', None):
                    try:
                        folder = comp.category.lower() if comp.category else ""
                        full_path = Path(comp.svg_path) / folder / comp.svg_file
                        comp_svg_content = self._read_svg_file(full_path)
                        if comp_svg_content is not None:

                            # Aplicar etiquetas de terminales igual que load_image() hace para el canvas
                            if hasattr(comp, '_apply_terminal_labels_to_svg'):
                                comp_svg_content = comp._apply_terminal_labels_to_svg(comp_svg_content)
                            if hasattr(comp, '_apply_power_supply_values_to_svg'):
                                comp_svg_content = comp._apply_power_supply_values_to_svg(comp_svg_content)
                            # Aplicar visibilidad de capas (ON/OFF, LOTTO, etc.) igual que load_image() hace para el canvas
                            if hasattr(comp, '_apply_layer_visibility'):
                                comp_svg_content = comp._apply_layer_visibility(comp_svg_content)

                            # Limpiar SVG para incrustar (quitar xml declaration, doctype, etc)
                            # Extraer solo el contenido dentro de <svg>...</svg> o usar <image>
                            # Mejor: usar <svg> anidado para respetar viewBox
                            import re
                            # MEJORA: EVITAR DISTORSIÓN EN ROTACIÓN
                            vb_match = re.search(r'viewBox=["\']([^"\']+)["\']', comp_svg_content)

                            # 2. Determinar dimensiones originales (para evitar distorsión)
                            orig_w, orig_h = getattr(comp, 'original_size', [w, h])
                            if vb_match:
                                viewbox = vb_match.group(1)
                                try:
                                    vb_vals = re.findall(r'(-?\d+(?:\.\d+)?)', viewbox)
                                    if len(vb_vals) >= 4:
                                        vb_w, vb_h = float(vb_vals[2]), float(vb_vals[3])
                                        # Heurística: si el aspect ratio es opuesto, swappear orig_size
                                        if (orig_w/orig_h > 1 and vb_w/vb_h < 1) or (orig_w/orig_h < 1 and vb_w/vb_h > 1):
                                            orig_w, orig_h = orig_h, orig_w
                                except: pass
                            else:
                                viewbox = f"0 0 {orig_w} {orig_h}"

                            # 3. Calcular desplazamiento (dx, dy) para que el centro del SVG original
                            # coincida con el centro del rectángulo visual (w, h)
                            # Esto es vital para que la rotación transform="rotate(..., w/2, h/2)" sea exacta.
                            dx = (w - orig_w) / 2
                            dy = (h - orig_h) / 2

                            # Extraer contenido interno
                            content_match = re.search(r'<svg[^>]*>(.*)</svg>', comp_svg_content, re.DOTALL)
                            if content_match:
                                inner_content = content_match.group(1)
                                # Usar x, y dentro del svg anidado para posicionamiento relativo al grupo componente
                                svg += f'''
        <svg x="{dx}" y="{dy}" width="{orig_w}" height="{orig_h}" viewBox="{viewbox}" overflow="visible">
            {inner_content}
        </svg>'''
                                svg_embedded = True
                    except Exception as e:
                        print(f"Error embedding SVG for {comp.name}: {e}")

                if not svg_embedded:
                    # Fallback: rectángulo
                    svg += f'''
        <rect width="{w}" height="{h}" fill="#f0f0f0" stroke="black" stroke-width="1"/>
        <text x="{w/2}" y="{h/2}" text-anchor="middle" dominant-baseline="middle" font-size="10">{comp.name}</text>'''

                # Cerrar rotación
                if rot:
                    svg += '''
      </g>'''

                # Cerrar grupo componente
                svg += '''
    </g>'''

                if getattr(self.canvas, 'show_labels', True) and comp.label_data and comp.label_data.get('name'):
                    # Lógica de posición: Derecha o Izquierda
                    is_right = comp.label_data.get('derecha', True)

                    if is_right:
                        # Etiqueta a la DERECHA del componente
                        lx = x + w + 5
                        text_anchor = "start"
                    else:
                        # Etiqueta a la IZQUIERDA del componente
                        lx = x - 5
                        text_anchor = "end"

                    ly = y + 10

                    # Las fases se posicionan según el lado opuesto a su punto de
                    # conexión. Debe ser exactamente la misma regla que usa el
                    # canvas; de lo contrario L1/L2/L3 terminan todos a la
                    # izquierda al exportar, aunque estén centrados bajo cada
                    # terminal en pantalla.
                    if comp.component_type == 'fase':
                        from ui.label_renderer import LabelRenderer

                        canvas_lx, canvas_ly, tk_anchor = LabelRenderer._get_fase_label_position(comp)
                        zoom = float(getattr(self.canvas, 'zoom_level', 1.0) or 1.0)
                        lx, ly = canvas_lx / zoom, canvas_ly / zoom

                        # Tk ancla el texto por su caja; SVG lo hace por la línea
                        # de base. Estos ajustes conservan la posición visual.
                        anchor_map = {
                            'n': ('middle', 8), 's': ('middle', 0),
                            'w': ('start', 3), 'e': ('end', 3),
                            'nw': ('start', 8), 'ne': ('end', 8),
                        }
                        text_anchor, baseline_adjustment = anchor_map.get(tk_anchor, ('start', 8))
                        ly += baseline_adjustment

                    svg += f'''
    <text x="{lx}" y="{ly}" class="component-text" fill="black" text-anchor="{text_anchor}">{comp.label_data.get('name')}</text>'''

                    y_offset = 12
                    if comp.label_data.get('show_details', False) and comp.label_data.get('description'):
                        svg += f'''
    <text x="{lx}" y="{ly + y_offset}" class="component-text" fill="black" text-anchor="{text_anchor}" font-style="italic">{comp.label_data['description']}</text>'''
                        y_offset += 12

                    if comp.label_data.get('show_details', False) and comp.component_type == "normal":

                        # Campos comunes
                        if comp.label_data.get('marca'):
                            svg += f'''
    <text x="{lx}" y="{ly + y_offset}" class="component-text" fill="black" text-anchor="{text_anchor}">{comp.label_data['marca']}</text>'''
                            y_offset += 10

                        if comp.label_data.get('voltaje'):
                            svg += f'''
    <text x="{lx}" y="{ly + y_offset}" class="component-text" fill="black" text-anchor="{text_anchor}">{comp.label_data['voltaje']}</text>'''
                            y_offset += 10

                        if comp.label_data.get('amperios'):
                            svg += f'''
    <text x="{lx}" y="{ly + y_offset}" class="component-text" fill="black" text-anchor="{text_anchor}">{comp.label_data['amperios']}</text>'''
                            y_offset += 10

                        # Campos específicos para motores
                        if comp.category == 'Motors':
                            if comp.label_data.get('potencia'):
                                svg += f'''
    <text x="{lx}" y="{ly + y_offset}" class="component-text" fill="black" text-anchor="{text_anchor}">{comp.label_data['potencia']}</text>'''
                                y_offset += 10
                            # Nota: El campo Amperios ya se muestra como campo común arriba

            if hasattr(self, 'shape_manager') and self.shape_manager:
                # Quitar recuadro de la lista BOM solo en PDF
                is_bom_sheet = False
                try:
                    active_sheet = self.project.get_active_sheet()
                    if active_sheet and active_sheet.name == "Lista de Materiales":
                        is_bom_sheet = True
                except:
                    pass

                for shape in self.shape_manager.shapes:
                    try:
                        # Propiedades comunes
                        s_fill = getattr(shape, 'fill', 'none')
                        if not s_fill: s_fill = 'none'

                        s_outline = getattr(shape, 'outline', 'black')
                        if not s_outline: s_outline = 'black'

                        s_width = getattr(shape, 'outline_width', 1.0)

                        # Manejo específico por tipo de forma
                        if shape.shape_type in ['rect', 'square']:
                            s_x, s_y = shape.x, shape.y
                            s_w = getattr(shape, 'width', 0)
                            s_h = getattr(shape, 'height', 0)
                            if shape.shape_type == 'square':
                                s_w = s_h = getattr(shape, 'side_length', 0)

                            # Shape usa x,y como centro, SVG usa x,y como top-left
                            x_tl = s_x - s_w / 2
                            y_tl = s_y - s_h / 2

                            stroke_attr = f'stroke="{s_outline}"' if s_outline and s_outline != "" else ""
                            svg += f'''
    <rect x="{x_tl}" y="{y_tl}" width="{s_w}" height="{s_h}" 
          fill="{s_fill}" {stroke_attr} stroke-width="{s_width}" />'''

                        elif shape.shape_type == 'circle':
                            s_x, s_y = shape.x, shape.y
                            s_r = getattr(shape, 'radius', 0)
                            svg += f'''
    <circle cx="{s_x}" cy="{s_y}" r="{s_r}" 
            fill="{s_fill}" stroke="{s_outline}" stroke-width="{s_width}" />'''

                        elif shape.shape_type == 'ellipse':
                            s_x, s_y = shape.x, shape.y
                            s_rx = getattr(shape, 'radius_x', 0)
                            s_ry = getattr(shape, 'radius_y', 0)
                            svg += f'''
    <ellipse cx="{s_x}" cy="{s_y}" rx="{s_rx}" ry="{s_ry}" 
             fill="{s_fill}" stroke="{s_outline}" stroke-width="{s_width}" />'''

                        elif shape.shape_type in ['line', 'geom_line']:
                            # Line usa x1, y1, x2, y2 en lugar de x, y
                            x1, y1 = getattr(shape, 'x1', 0), getattr(shape, 'y1', 0)
                            x2, y2 = getattr(shape, 'x2', 0), getattr(shape, 'y2', 0)
                            s_arrow = getattr(shape, 'arrow', None)
                            arrow_attrs = ''
                            if s_arrow == 'both':
                                arrow_attrs = 'marker-start="url(#arrow-start)" marker-end="url(#arrow-end)"'
                            elif s_arrow in ('last',):
                                arrow_attrs = 'marker-end="url(#arrow-end)"'
                            elif s_arrow == 'first':
                                arrow_attrs = 'marker-start="url(#arrow-start)"'
                            svg += f'''
    <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" 
          stroke="{s_outline}" stroke-width="{s_width}" stroke-linecap="round" {arrow_attrs} />'''

                        elif shape.shape_type == 'din_rail':
                            x1, y1, x2, y2 = shape.get_bbox()
                            sh = y2 - y1
                            svg += f'''
                            <rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{sh}"
                                fill="{shape.fill or '#D3D3D3'}" stroke="{shape.outline or 'black'}" stroke-width="{shape.outline_width or 1.5}" />'''
                            if sh > 5:
                                line_y1 = y1 + sh * 0.15
                                line_y2 = y2 - sh * 0.15
                                svg += f'''
                            <line x1="{x1}" y1="{line_y1}" x2="{x2}" y2="{line_y1}" stroke="{shape.outline or 'black'}" stroke-width="1" />
                            <line x1="{x1}" y1="{line_y2}" x2="{x2}" y2="{line_y2}" stroke="{shape.outline or 'black'}" stroke-width="1" />'''

                        elif shape.shape_type == 'multipole_borner':
                            s_x, s_y = shape.x, shape.y
                            s_w = getattr(shape, 'width', 0)
                            s_h = getattr(shape, 'height', 0)
                            poles = getattr(shape, 'poles', 1)
                            x_tl = s_x - s_w / 2
                            y_tl = s_y - s_h / 2

                            stroke_attr = f'stroke="{s_outline}"' if s_outline and s_outline != "" else ""
                            svg += f'''
                            <rect x="{x_tl}" y="{y_tl}" width="{s_w}" height="{s_h}" 
                                fill="{s_fill}" {stroke_attr} stroke-width="{s_width}" />'''

                            # Divisiones verticales
                            pole_w = s_w / poles
                            for i in range(1, poles):
                                lx = x_tl + i * pole_w
                                svg += f'''
                            <line x1="{lx}" y1="{y_tl}" x2="{lx}" y2="{y_tl + s_h}" stroke="{s_outline}" stroke-width="{s_width}" />'''

                            # Tornillos en el centro de cada polo
                            screw_r = min(pole_w, s_h) * 0.15
                            for i in range(poles):
                                px = x_tl + (i + 0.5) * pole_w
                                py = y_tl + s_h / 2
                                svg += f'''
                            <circle cx="{px}" cy="{py}" r="{screw_r}" 
                                    fill="#cccccc" stroke="{s_outline}" stroke-width="1" />'''

                        elif shape.shape_type == 'canaleta':
                            x1, y1, x2, y2 = shape.get_bbox()
                            svg += f'''
                            <rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}"
                                fill="{shape.fill or '#C0C0C0'}" stroke="{shape.outline or '#808080'}" stroke-width="{shape.outline_width or 1.5}" />'''

                    except Exception as e:
                        print(f"Error exporting shape: {e}")

            # 5. PUNTOS DE CONEXIÓN (Red Circles)
            # 5.1 Puntos de conexión de componentes
            for comp in self.components:
                try:
                    if hasattr(comp, 'get_connection_points_global'):
                        for global_x, global_y, point in comp.get_connection_points_global():
                            # Color: rojo si conectado, verde si no (igual que en app)
                            fill_color = "red" if getattr(point, 'connected', False) else "green"
                            # Radio pequeño (2px en app -> ajustar para PDF)
                            # En app es radio 2 (diámetro 4). En PDF scale_factor afecta.
                            # Queremos que sean visibles.
                            r = 2.0

                            svg += f'''
    <circle cx="{global_x}" cy="{global_y}" r="{r}" 
            fill="{fill_color}" stroke="black" stroke-width="0.5" />'''
                except Exception as e:
                    pass

            # 5.2 Puntos de empalme en líneas (Junctions)
            for connection in self.connections:
                try:
                    if hasattr(connection, 'puntos_empalme') and connection.puntos_empalme:
                        for empalme in connection.puntos_empalme:
                            try:
                                # Calcular posición basada en segmento y ratio
                                seg_idx = getattr(empalme, 'segmento_idx', 0)
                                ratio = getattr(empalme, 'posicion_ratio', 0.5)

                                if hasattr(connection, 'segments') and len(connection.segments) > seg_idx:
                                    start, end = connection.segments[seg_idx]
                                    # Interpolación lineal
                                    ex = start[0] + (end[0] - start[0]) * ratio
                                    ey = start[1] + (end[1] - start[1]) * ratio

                                    # Dibujar círculo rojo (empalmes siempre conectados)
                                    svg += f'''
    <circle cx="{ex}" cy="{ey}" r="2.5" 
            fill="red" stroke="black" stroke-width="0.5" />'''
                            except:
                                pass
                except Exception as e:
                    pass

            # 7. BLOCK TERMINALS (Cabinet 2D)
            if hasattr(self, 'block_terminals') and self.block_terminals:
                for bt in self.block_terminals:
                    try:
                        bt_x, bt_y = bt['x'], bt['y']
                        filas = bt['filas']
                        bornas = bt['bornas']
                        svg_key = bt.get('svg_key', '2F')
                        label_data = bt.get('label_data', {})

                        from handlers.event_handlers import EventHandler
                        block_svg_template = EventHandler.BLOCK_SVG.get(svg_key)
                        module_w = EventHandler.BLOCK_MODULE_W
                        module_h = EventHandler.BLOCK_HEIGHT.get(svg_key, 45)

                        total_w = module_w * bornas
                        x0 = bt_x - total_w / 2
                        y0 = bt_y - module_h / 2

                        import re
                        inner_content = ""
                        # Extraer el contenido interno del SVG del bloque
                        content_match = re.search(r'<svg[^>]*>(.*)</svg>', block_svg_template, re.DOTALL)
                        if content_match:
                            inner_content = content_match.group(1)

                        # Extraer viewBox para el bloque
                        vb_match = re.search(r'viewBox=["\']([^"\']+)["\']', block_svg_template)
                        viewbox = vb_match.group(1) if vb_match else f"0 0 {module_w} {module_h}"

                        for i in range(bornas):
                            xi = x0 + i * module_w
                            svg += f'\n        <g transform="translate({xi}, {y0})">'
                            svg += f'\n            <svg width="{module_w}" height="{module_h}" viewBox="{viewbox}" overflow="visible">'
                            svg += f'\n                {inner_content}'
                            svg += '\n            </svg>'
                            svg += '\n        </g>'

                        division_str = label_data.get('division', 'Sin división')
                        N = 0
                        if "2P" in division_str:
                            N = 2
                        elif "3P" in division_str:
                            N = 3
                        elif "4P" in division_str:
                            N = 4

                        if N > 0:
                            sep_w = 2.0
                            for i in range(bornas):
                                if (i + 1) % N == 0 and (i + 1) < bornas:
                                    x_div = x0 + (i + 1) * module_w
                                    svg += f'''
        <rect x="{x_div - sep_w/2}" y="{y0}" width="{sep_w}" height="{module_h}" fill="#555555" stroke="black" stroke-width="0.5" />'''

                        if label_data.get('name'):
                            lx, ly = bt_x, y0 - 10
                            svg += f'''
        <text x="{lx}" y="{ly}" font-family="Arial" font-size="8" font-weight="bold" fill="black" text-anchor="middle">{label_data['name']}</text>'''

                    except Exception as e:
                        print(f"Error exporting block terminal: {e}")

            # 8. TEXTOS (TextComponent)
            for text_comp in self.text_components:
                try:
                    if getattr(text_comp, 'metadata', {}).get('exportable') is False:
                        continue
                    tx, ty = text_comp.x, text_comp.y
                    t_text = str(text_comp.text)
                    t_size = text_comp.font_size
                    t_color = getattr(text_comp, 'color', '#000000')
                    if not t_color: t_color = '#000000'

                    # Soporte de rotación del texto en SVG/PDF y escape XML
                    angle = int(getattr(text_comp, 'rotation', 0)) % 360
                    safe_text = html.escape(t_text, quote=False)

                    # Support dynamic anchors in PDF export
                    tk_anchor = getattr(text_comp, 'anchor', 'center')
                    svg_anchor = "middle"
                    if tk_anchor == "w": svg_anchor = "start"
                    elif tk_anchor == "e": svg_anchor = "end"

                    # Sentido de giro. El ángulo de Tk es antihorario
                    # (crece hacia arriba porque el eje Y de pantalla apunta
                    # abajo), mientras que rotate() de SVG es horario. Sin
                    # invertirlo, un texto girado 90° sale hacia el lado
                    # contrario al del lienzo.
                    svg_angle = (360 - angle) % 360

                    if svg_angle:
                        svg += f'''
    <g transform="rotate({svg_angle}, {tx}, {ty})">'''
                    svg += f'''
    <text x="{tx}" y="{ty}" font-family="{TEXT_FONT_FAMILY}" font-size="{t_size}" fill="{t_color}" text-anchor="{svg_anchor}" dominant-baseline="middle">{safe_text}</text>'''
                    if svg_angle:
                        svg += '''
    </g>'''
                except:
                    pass

            # 7. ELEMENTOS RAW DEL CANVAS (DIBUJADOS DIRECTAMENTE COMO EN INFORMES O BORNES)
            # Recolectamos IDs ya procesados para evitar duplicados
            handled_ids = set()
            for shape in self.shape_manager.shapes:
                if hasattr(shape, 'canvas_id') and shape.canvas_id: handled_ids.add(shape.canvas_id)
            for text_comp in self.text_components:
                if hasattr(text_comp, 'canvas_id') and text_comp.canvas_id: handled_ids.add(text_comp.canvas_id)
            for conn in self.connections:
                if hasattr(conn, 'line_ids'): handled_ids.update(conn.line_ids)
            for comp in self.components:
                if hasattr(comp, 'canvas_id') and comp.canvas_id: handled_ids.add(comp.canvas_id)
                if hasattr(comp, 'label_ids'): handled_ids.update(comp.label_ids)
                if hasattr(comp, 'point_ids'): handled_ids.update(comp.point_ids)

            # Manejar image_components explícitamente para asegurar su exportación (especialmente bornes)
            if hasattr(self, 'image_components'):
                for img_comp in self.image_components:
                    try:
                        # Intentar obtener la imagen PIL directamente para máxima calidad y fiabilidad
                        pil_img = None
                        if hasattr(img_comp, 'original_image') and img_comp.original_image:
                            pil_img = img_comp.original_image
                        else:
                            # Fallback a PhotoImage
                            import io, base64
                            from PIL import ImageTk
                            photo_obj = None
                            for attr in ['photo', 'photo_image', 'image', 'photo']:
                                if hasattr(img_comp, attr):
                                    photo_obj = getattr(img_comp, attr)
                                    break
                            if photo_obj:
                                try:
                                    pil_img = ImageTk.getimage(photo_obj)
                                except: pass

                        if pil_img:
                            import io, base64
                            buffer = io.BytesIO()
                            pil_img.save(buffer, format="PNG")
                            b64_data = base64.b64encode(buffer.getvalue()).decode()

                            ix, iy = img_comp.x, img_comp.y
                            iw, ih = img_comp.size[0], img_comp.size[1]
                            # Centrar como lo hace ImageComponent.draw()
                            ix_final, iy_final = ix - iw/2, iy - ih/2

                            # Usar href y xlink:href para máxima compatibilidad con visores PDF
                            # cairosvg lee xlink:href y cae a href; con los dos
                            # atributos la carga base64 se duplicaba en el SVG,
                            # lo que duplicaba también el trabajo de Cairo.
                            svg += f'\n    <image x="{ix_final}" y="{iy_final}" width="{iw}" height="{ih}" xlink:href="data:image/png;base64,{b64_data}" />'

                            # Marcar como manejado para evitar duplicados en el loop de find_all()
                            if hasattr(img_comp, 'canvas_id') and img_comp.canvas_id:
                                handled_ids.add(img_comp.canvas_id)
                    except Exception as e:
                        print(f"Error exportando ImageComponent direct: {e}")

            # Recorrer solo los elementos relevantes del canvas para encontrar "huérfanos"
            all_ids = set(self.canvas.find_all())
            decorative_tags = ['grid', 'grid_line', 'crosshair', 'selection_rect', 'selection_circle', 'cross_ref']
            decorative_ids = set()
            for tag in decorative_tags:
                try:
                    decorative_ids.update(self.canvas.find_withtag(tag))
                except Exception:
                    pass

            item_ids_to_process = all_ids - handled_ids - decorative_ids
            if not item_ids_to_process:
                item_ids_to_process = set()

            for item_id in item_ids_to_process:
                tags = self.canvas.gettags(item_id)
                # Ignorar elementos decorativos adicionales si hay etiquetas desconocidas
                if any(t in tags for t in decorative_tags):
                    continue

                item_type = self.canvas.type(item_id)
                coords = self.canvas.coords(item_id)
                if not coords: continue

                # Des-escalamos por el zoom_level actual del canvas para volver a unidades "mundo"
                zoom = getattr(self.canvas, 'zoom_level', 1.0)
                norm_coords = [c / zoom for c in coords]

                if item_type == 'line':
                    fill = self.canvas.itemcget(item_id, 'fill')
                    width = float(self.canvas.itemcget(item_id, 'width')) / zoom
                    svg += f'\n    <line x1="{norm_coords[0]}" y1="{norm_coords[1]}" x2="{norm_coords[2]}" y2="{norm_coords[3]}" stroke="{fill}" stroke-width="{width}" stroke-linecap="round" />'

                elif item_type == 'rectangle':
                    fill = self.canvas.itemcget(item_id, 'fill') or 'none'
                    outline = self.canvas.itemcget(item_id, 'outline') or 'none'
                    width = float(self.canvas.itemcget(item_id, 'width')) / zoom
                    x1, y1, x2, y2 = norm_coords
                    svg += f'\n    <rect x="{min(x1,x2)}" y="{min(y1,y2)}" width="{abs(x2-x1)}" height="{abs(y2-y1)}" fill="{fill}" stroke="{outline}" stroke-width="{width}" />'

                elif item_type == 'oval':
                    fill = self.canvas.itemcget(item_id, 'fill') or 'none'
                    outline = self.canvas.itemcget(item_id, 'outline') or 'none'
                    width = float(self.canvas.itemcget(item_id, 'width')) / zoom
                    x1, y1, x2, y2 = norm_coords
                    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                    rx, ry = abs(x2 - x1) / 2, abs(y2 - y1) / 2
                    if rx == ry:
                        svg += f'\n    <circle cx="{cx}" cy="{cy}" r="{rx}" fill="{fill}" stroke="{outline}" stroke-width="{width}" />'
                    else:
                        svg += f'\n    <ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" stroke="{outline}" stroke-width="{width}" />'

                elif item_type == 'text':
                    text_val = self.canvas.itemcget(item_id, 'text')
                    font_info = self.canvas.itemcget(item_id, 'font')
                    fill = self.canvas.itemcget(item_id, 'fill')
                    anchor = self.canvas.itemcget(item_id, 'anchor')

                    # Extraer tamaño de la fuente
                    import re
                    f_size = 10
                    size_match = re.search(r'\d+', font_info)
                    if size_match: f_size = float(size_match.group(0)) / zoom

                    svg_anchor = "middle"
                    if anchor == "w": svg_anchor = "start"
                    elif anchor == "e": svg_anchor = "end"

                    # mismo criterio de giro que en TextComponent: el
                    # ángulo de Tk es antihorario y rotate() de SVG es horario.
                    try:
                        raw_angle = float(self.canvas.itemcget(item_id, 'angle') or 0)
                    except (TypeError, ValueError):
                        raw_angle = 0.0
                    raw_angle = int(raw_angle) % 360
                    item_angle = (360 - raw_angle) % 360
                    tx_i, ty_i = norm_coords[0], norm_coords[1]

                    if item_angle:
                        svg += f'\n    <g transform="rotate({item_angle}, {tx_i}, {ty_i})">'

                    if '\n' in text_val:
                        lines = text_val.split('\n')
                        # Para multi-línea, necesitamos un grupo <text> con múltiples <tspan>
                        # El dy="1.2em" es un estándar razonable para el espaciado entre líneas
                        svg += f'\n    <text x="{tx_i}" y="{ty_i}" font-family="{TEXT_FONT_FAMILY}" font-size="{f_size}" fill="{fill}" text-anchor="{svg_anchor}" dominant-baseline="middle">'
                        for i, line in enumerate(lines):
                            dy = "0" if i == 0 else "1.2em"
                            # Ajuste vertical inicial para centrar el bloque de texto si es multi-línea
                            # Tkinter centra el bloque completo, así que debemos desplazar el primer tspan hacia arriba
                            if i == 0:
                                vertical_offset = -(len(lines) - 1) * 0.6
                                svg += f'<tspan x="{tx_i}" dy="{vertical_offset}em">{line}</tspan>'
                            else:
                                svg += f'<tspan x="{tx_i}" dy="1.2em">{line}</tspan>'
                        svg += '</text>'
                    else:
                        svg += f'\n    <text x="{tx_i}" y="{ty_i}" font-family="{TEXT_FONT_FAMILY}" font-size="{f_size}" fill="{fill}" text-anchor="{svg_anchor}" dominant-baseline="middle">{text_val}</text>'

                    if item_angle:
                        svg += '\n    </g>'

                elif item_type == 'image':
                    # Exportar imágenes (Borners, Warning, etc.) como Base64
                    try:
                        img_name = self.canvas.itemcget(item_id, 'image')
                        # Buscar en el buffer de imágenes del reporte (está en la instancia principal 'self')
                        photo_obj = None
                        if hasattr(self, '_borner_images'):
                            for p in self._borner_images:
                                if str(p) == img_name:
                                    photo_obj = p
                                    break

                        # También buscar en _warning_images (Warning.svg)
                        if not photo_obj and hasattr(self, '_warning_images'):
                            for p in self._warning_images:
                                if str(p) == img_name:
                                    photo_obj = p
                                    break

                        # También buscar en _bt_photo_refs (Block Terminal SVG modules)
                        if not photo_obj and hasattr(self, '_bt_photo_refs'):
                            for p in self._bt_photo_refs:
                                if str(p) == img_name:
                                    photo_obj = p
                                    break

                        # También buscar en image_components (logo-evaPr.png)
                        if not photo_obj and hasattr(self, 'image_components'):
                            for img_comp in self.image_components:
                                # Intentar múltiples formas de acceder a la imagen
                                for attr_name in ['photo_image', 'image', 'photo', 'img', '_photo_image', '_image']:
                                    if hasattr(img_comp, attr_name):
                                        attr_value = getattr(img_comp, attr_name)
                                        if attr_value and str(attr_value) == img_name:
                                            photo_obj = attr_value
                                            break
                                if photo_obj:
                                    break

                                # También intentar con la imagen directamente si es un objeto
                                if hasattr(img_comp, 'image'):
                                    try:
                                        if str(img_comp.image) == img_name:
                                            photo_obj = img_comp.image
                                            break
                                    except:
                                        pass

                                # ULTIMO RECURSO: Si no encontramos por string, intentar usar el componente directamente
                                # Intentar obtener la imagen PIL directamente del componente
                                if not photo_obj:
                                    try:
                                        # Si el componente tiene un método para obtener la imagen
                                        if hasattr(img_comp, 'get_image'):
                                            photo_obj = img_comp.get_image()
                                        # Si tiene directamente un atributo _img o similar
                                        elif hasattr(img_comp, '_image'):
                                            photo_obj = img_comp._image
                                        elif hasattr(img_comp, 'pil_image'):
                                            photo_obj = img_comp.pil_image
                                    except:
                                        pass

                                # Si aún tenemos el componente pero no pudimos obtener la imagen,
                                # intentar usar el componente directamente como fuente de imagen
                                if not photo_obj and img_comp:
                                    try:
                                        # Buscar cualquier atributo que parezca ser una imagen
                                        for attr in dir(img_comp):
                                            if not attr.startswith('__'):
                                                attr_val = getattr(img_comp, attr, None)
                                                if attr_val and hasattr(attr_val, 'width') and hasattr(attr_val, 'height'):
                                                    # Esto parece ser un objeto de imagen
                                                    photo_obj = attr_val
                                                    break
                                    except:
                                        pass

                            # Si aún no encontramos la imagen, buscar en TODOS los atributos de self que contengan "image"
                            if not photo_obj:
                                for attr_name in dir(self):
                                    if 'image' in attr_name.lower():
                                        try:
                                            attr_val = getattr(self, attr_name, None)
                                            if attr_val and isinstance(attr_val, list):
                                                for item in attr_val:
                                                    if hasattr(item, 'photo_image'):
                                                        if str(item.photo_image) == img_name:
                                                            photo_obj = item.photo_image
                                                            break
                                                    elif hasattr(item, 'image'):
                                                        if str(item.image) == img_name:
                                                            photo_obj = item.image
                                                            break
                                        except:
                                            pass

                        if photo_obj:
                            import io, base64
                            from PIL import ImageTk
                            # Extraer imagen PIL del PhotoImage
                            pil_img = ImageTk.getimage(photo_obj)
                            buffer = io.BytesIO()
                            pil_img.save(buffer, format="PNG")
                            b64_data = base64.b64encode(buffer.getvalue()).decode()

                            ix_center, iy_center = norm_coords
                            anchor = self.canvas.itemcget(item_id, 'anchor')
                            iw, ih = photo_obj.width() / zoom, photo_obj.height() / zoom

                            ix, iy = ix_center, iy_center
                            if anchor == 'center':
                                ix, iy = ix_center - iw/2, iy_center - ih/2

                            svg += f'\n    <image x="{ix}" y="{iy}" width="{iw}" height="{ih}" xlink:href="data:image/png;base64,{b64_data}" />'
                    except Exception as e:
                        print(f"Error exportando imagen a PDF: {e}")

            # 8. REFERENCIAS CRUZADAS (Estándar Profesional)
            try:
                svg += self._get_cross_references_svg()
            except Exception as e:
                print(f"Error agregando referencias al PDF: {e}")

            # Cerrar grupo circuito
            svg += '''
  </g>'''

        except Exception as e:
            print(f"Error generating circuit SVG content: {e}")
            # Retornar texto de error en el SVG
            svg += f'''<text x="50" y="50" fill="red">Error generando circuito: {str(e)}</text>'''

        return str(svg)

    def _generate_coordenadas_horizontales_svg(self, width_pt, height_pt, margin_pt, scale_factor, offset_x):
        """Genera coordenadas numéricas (1,2,3...) arriba y abajo en los márgenes del marco."""
        svg = ""
        from utils.coordinates import AppConstants
        num_cols = int(self._get_template_value("coordinates", "num_columns", default=10))
        number_spacing = self._get_template_value("coordinates", "column_spacing_pt", default=None)
        if number_spacing is None:
            number_spacing = (AppConstants.CANVAS_WIDTH / num_cols) * scale_factor
        else:
            number_spacing = number_spacing * scale_factor
        line_width = self._get_template_value("coordinates", "line_width", default=0.5)

        for i in range(num_cols):
            number = str(i + 1)
            # x_pos está alineado con el inicio del dibujo del circuito (offset_x)
            x_pos = offset_x + i * number_spacing + number_spacing / 2

            # Solo dibujar si cae dentro del área visible aproximadamente
            if x_pos > width_pt - margin_pt + 20:
                continue

            # CRÍTICO: Número arriba - FUERA DEL MARCO (por encima de la línea superior)
            svg += f'''
    <!-- Número {number} arriba - FUERA del marco -->
    <text x="{x_pos}" y="{height_pt - margin_pt/2 + 3}" 
            text-anchor="middle" class="coordenadas">{number}</text>'''

            # CRÍTICO: Número abajo - FUERA DEL MARCO (por debajo de la línea inferior)
            svg += f'''
    <!-- Número {number} abajo - FUERA del marco -->
    <text x="{x_pos}" y="{margin_pt/3 + 3}" 
            text-anchor="middle" class="coordenadas">{number}</text>'''

            # Líneas de división verticales
            if i > 0:
                line_x = offset_x + i * number_spacing

                # Línea superior
                svg += f'''
    <!-- Línea división superior {i} -->
    <line x1="{line_x}" y1="{height_pt - margin_pt}" 
            x2="{line_x}" y2="{height_pt - margin_pt/2}" 
            stroke="black" stroke-width="0.5" />'''

                # Línea inferior
                svg += f'''
    <!-- Línea división inferior {i} -->
    <line x1="{line_x}" y1="{margin_pt}" 
            x2="{line_x}" y2="{margin_pt/2}" 
            stroke="black" stroke-width="0.5" />'''

        return svg

    def _generate_coordenadas_verticales_svg(self, width_pt, height_pt, margin_pt, scale_factor, offset_y):
        """Genera coordenadas A,B,C... izquierda y derecha en SVG con espaciado escalado"""
        svg = ""

        num_rows = int(self._get_template_value("coordinates", "num_rows", default=10))
        line_width = self._get_template_value("coordinates", "line_width", default=0.5)
        number_spacing = (height_pt - 2 * margin_pt) / num_rows

        for i in range(num_rows):
            label = chr(65 + i) # A, B, C...
            y_pos = height_pt - margin_pt - i * number_spacing - number_spacing / 2

            # Número a la izquierda
            svg += f'''
  <!-- Letra {label} izquierda -->
  <text x="{margin_pt / 3}" y="{y_pos + 3}" 
        text-anchor="middle" class="coordenadas">{label}</text>'''

            # Número a la derecha
            svg += f'''
  <!-- Letra {label} derecha -->
  <text x="{width_pt - margin_pt + 6}" y="{y_pos + 3}" 
        text-anchor="middle" class="coordenadas">{label}</text>'''

        return svg

    def _normalize_pdf_field_name(self, field_name):
        """Normaliza nombres de campo PDF para comparación flexible."""
        text = str(field_name or "")
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ASCII", "ignore").decode("ASCII")
        return re.sub(r'[^A-Z0-9]', '', ascii_text.upper())

    def _build_pdf_field_value_map(self, pdf_config, sheet_index=0, total_sheets=1):
        hoja_text = f"{sheet_index + 1} de {total_sheets}"
        hoja_num = str(sheet_index + 1)
        total_hojas = str(total_sheets)
        try:
            active_sheet = self.project.get_active_sheet() if hasattr(self, 'project') else self.app.project.get_active_sheet()
            sheet_name = active_sheet.name if active_sheet else pdf_config.get("nombre_documento", "")
        except Exception:
            sheet_name = pdf_config.get("nombre_documento", "")

        return {
            "PROYECTO":          pdf_config.get("proyecto", ""),
            "NOMBREDELPROYECTO": pdf_config.get("proyecto", ""),
            "DIBUJADO":          pdf_config.get("dibujado_por", ""),
            "DIBUJADOPOR":       pdf_config.get("dibujado_por", ""),
            "REVISADO":          pdf_config.get("revisado_por", ""),
            "REVISADOPOR":       pdf_config.get("revisado_por", ""),
            "APROBADO":          pdf_config.get("aprobado_por", ""),
            "APROBADOPOR":       pdf_config.get("aprobado_por", ""),
            "EMPRESA":           pdf_config.get("empresa", ""),
            "DIRECCION":         pdf_config.get("direccion", ""),
            "ESCALA":            pdf_config.get("escala", "1:1"),
            "VERSION":           pdf_config.get("version", ""),
            "HOJA":              hoja_num,
            "HOJAS":             total_hojas,
            # La plantilla clienteUA3.pte nombra este campo "HOJA # DE #", que
            # _normalize_pdf_field_name reduce a "HOJADE"; sin esta clave la caja
            # quedaba vacía.  La caja mide 14.9 pt con fuente Helvetica 12, así
            # que solo cabe la hoja actual: "1 de 6" (33 pt) se recortaría.
            "HOJADE":            hoja_num,
            "NHOJA":             sheet_name,
            "NOMBREHOJA":        sheet_name,
            "FORMATO":           pdf_config.get("formato", "A4").upper(),
            "FECHA":             datetime.now().strftime("%d/%m/%Y"),
        }

    def _apply_pdf_form_field_values(self, writer, page, pdf_config, sheet_index=0, total_sheets=1):
        """Llena campos de formulario PDF SIN aplanar.
        El aplanado real se delega a cairosvg en _flatten_pdf_with_cairosvg,
        que renderiza todos los campos como vectores garantizando visibilidad."""
        try:
            import pypdf.generic as generic
        except ImportError:
            return

        field_values = self._build_pdf_field_value_map(pdf_config, sheet_index, total_sheets)
        if not field_values:
            return

        page_fields = {}
        try:
            if hasattr(self, '_pdf_template_path') and self._pdf_template_path:
                reader = self._template_pdf_reader(str(self._pdf_template_path))
                page_fields = (reader.get_fields() if reader else None) or {}
        except Exception:
            page_fields = {}

        updates = {}
        for field_name in page_fields:
            normalized = self._normalize_pdf_field_name(field_name)
            if normalized in field_values:
                updates[field_name] = field_values[normalized]

        if updates:
            # auto_regenerate=False evita el bug de pypdf que genera apariencias vacías.
            # flatten=False: NO aplanar aquí; cairosvg lo hará correctamente después.
            writer.update_page_form_field_values(page, updates, auto_regenerate=False)

        # Activar NeedAppearances para que los visores (y cairosvg) rendericen los valores.
        # NO eliminar /Annots ni /AcroForm: contienen los textos que necesitamos aplanar.
        try:
            root = writer._root_object
            if "/AcroForm" in root:
                acroform = root["/AcroForm"]
                acroform[generic.NameObject("/NeedAppearances")] = generic.BooleanObject(True)
        except Exception:
            pass

    def _flatten_pdf_with_cairosvg(self, input_pdf_path, output_pdf_path):
        """Aplana un PDF con campos de formulario usando cairosvg.
        cairosvg renderiza el PDF completo (incluyendo campos AcroForm) a vectores,
        produciendo un PDF limpio donde los textos son visibles y no editables."""
        import cairosvg
        # cairosvg no convierte PDF->PDF directamente, pero sí PDF->PNG y luego
        # podemos usar ReportLab, o bien usamos el enfoque SVG intermedio.
        # La forma más robusta es: PDF con campos -> PNG de alta resolución -> PDF.
        # Sin embargo, eso produce raster. La alternativa correcta es usar
        # cairosvg a través de su superficie Cairo directamente con pdf2image + cairo.
        # Enfoque óptimo: convertir con cairo a través de subprocess (pdftocairo si
        # disponible) o via la API de cairosvg con un SVG wrapper que embeba el PDF.
        # Usamos pdftocairo (parte de poppler) si está disponible, sino fallback
        # a renderizado PNG de alta resolución con cairosvg/PIL.
        import subprocess
        import shutil

        # Intento 1: pdftocairo (poppler) — produce PDF vectorial perfecto
        if shutil.which("pdftocairo"):
            try:
                result = subprocess.run(
                    ["pdftocairo", "-pdf", input_pdf_path, output_pdf_path],
                    capture_output=True, timeout=30
                )
                if result.returncode == 0 and os.path.exists(output_pdf_path):
                    print("✅ Aplanado con pdftocairo (vectorial)")
                    return True
            except Exception as e:
                print(f"⚠️ pdftocairo falló: {e}")

        # Intento 2: cairosvg vía PNG de alta resolución (raster, pero visible)
        try:
            from reportlab.pdfgen import canvas as rl_canvas
            import io

            # Leer dimensiones reales del PDF
            from pypdf import PdfReader
            reader = PdfReader(input_pdf_path)
            media_box = reader.pages[0].mediabox
            width_pt  = float(media_box.width)
            height_pt = float(media_box.height)

            # Renderizar a PNG a 150 DPI (suficiente para cajetín técnico)
            dpi = 150
            scale = dpi / 72.0 # 72 pt/inch -> DPI deseado
            png_bytes = cairosvg.svg2png(
                url=input_pdf_path,
                output_width=int(width_pt * scale),
                output_height=int(height_pt * scale),
                background_color="white"
            )

            # Incrustar PNG en un PDF ReportLab del mismo tamaño
            from reportlab.lib.utils import ImageReader
            img_reader = ImageReader(io.BytesIO(png_bytes))
            c = rl_canvas.Canvas(output_pdf_path, pagesize=(width_pt, height_pt))
            c.drawImage(img_reader, 0, 0, width_pt, height_pt)
            c.save()
            print("✅ Aplanado con cairosvg PNG→PDF (raster 150 DPI)")
            return True

        except Exception as e:
            print(f"⚠️ Aplanado cairosvg PNG falló: {e}")
            # Fallback final: usar el PDF con campos tal cual (mejor que nada)
            import shutil as _shutil
            _shutil.copy2(input_pdf_path, output_pdf_path)
            print("⚠️ Usando PDF con campos sin aplanar como fallback")
            return False

    def _cajetin_get_data_value(self, cell_id, pdf_config, sheet_index, total_sheets):
        """Resuelve el valor de datos para una celda del cajetín según su id."""
        fecha_actual = datetime.now().strftime("%d/%m/%Y")
        hoja_text = f"{sheet_index + 1} de {total_sheets}"
        try:
            active_sheet = self.project.get_active_sheet()
            sheet_name = active_sheet.name if active_sheet else "Hoja1"
        except Exception:
            sheet_name = "Hoja1"
        page_format = pdf_config.get("formato", "A4").upper()

        mapping = {
            "dibujado_por":       pdf_config.get("dibujado_por", ""),
            "drawn_by":           pdf_config.get("dibujado_por", ""),
            "revisado_por":       pdf_config.get("revisado_por", ""),
            "reviewed_by":        pdf_config.get("revisado_por", ""),
            "aprobado_por":       pdf_config.get("aprobado_por", ""),
            "approved_by":        pdf_config.get("aprobado_por", ""),
            "proyecto":           pdf_config.get("proyecto", ""),
            "project":            pdf_config.get("proyecto", ""),
            "empresa":            pdf_config.get("empresa", ""),
            "company":            pdf_config.get("empresa", ""),
            "direccion":          pdf_config.get("direccion", ""),
            "escala":             pdf_config.get("escala", "1:1"),
            "scale":              pdf_config.get("escala", "1:1"),
            "version":            pdf_config.get("version", ""),
            "fecha":              fecha_actual,
            "date":               fecha_actual,
            "hoja":               str(sheet_index + 1),
            "hojas":              str(total_sheets),
            "nhoja":              sheet_name,
            "sheet_number":       str(sheet_index + 1),
            "total_sheets":       str(total_sheets),
            "sheet_name":         sheet_name,
            "nombre_hoja":        sheet_name,
            "formato":            page_format,
            "page_format":        page_format,
            "codigo":             pdf_config.get("codigo", ""),
            "nombre_documento":   pdf_config.get("nombre_documento", ""),
            "cliente":            pdf_config.get("cliente", ""),
        }
        return mapping.get(cell_id, "")

    def _cajetin_svg_text(self, x, y, text, css_class="cajin", align="start", extra_style=""):
        """Emite un elemento SVG <text> con escape HTML básico."""
        if not text:
            return ""
        safe = (str(text).replace("&", "&amp;")
                         .replace("<", "&lt;")
                         .replace(">", "&gt;"))
        style_attr = f' style="{extra_style}"' if extra_style else ""
        return (f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{align}"'
                f' class="{css_class}"{style_attr}>{safe}</text>\n')

    def _cajetin_render_simple_columns(self, cajin_x, cajin_y, cajin_width_pt,
                                        cajin_height_pt, cajetin_template,
                                        pdf_config, sheet_index, total_sheets):
        """Formato simple: lista de anchos en columns_mm con etiqueta arriba / valor abajo."""
        svg = ""
        columns_mm_list = cajetin_template.get("columns_mm", [25, 25, 50, 65, 65, 100, 15, 12])
        col_widths = [float(mm) * float(w) for w in columns_mm_list]
        col_ids    = cajetin_template.get("column_ids", [])
        labels_map = cajetin_template.get("labels", {})

        # Separadores verticales
        cx = cajin_x
        for w in col_widths[:-1]:
            cx += w
            svg += (f'<line x1="{cx:.2f}" y1="{cajin_y:.2f}" '
                    f'x2="{cx:.2f}" y2="{cajin_y + cajin_height_pt:.2f}" '
                    f'stroke="black" stroke-width="0.5"/>\n')

        # Línea horizontal central
        medio_y = cajin_y + cajin_height_pt / 2
        svg += (f'<line x1="{cajin_x:.2f}" y1="{medio_y:.2f}" '
                f'x2="{cajin_x + cajin_width_pt:.2f}" y2="{medio_y:.2f}" '
                f'stroke="black" stroke-width="0.5"/>\n')

        y_label = cajin_y + cajin_height_pt * 0.25 + 2
        y_value = cajin_y + cajin_height_pt * 0.75 + 2

        x_pos = cajin_x
        for i, w in enumerate(col_widths):
            col_id = col_ids[i] if i < len(col_ids) else ""
            label  = labels_map.get(col_id, col_id) if col_id else ""
            label  = self._resolve_placeholders(label, pdf_config, sheet_index, total_sheets)
            value  = self._cajetin_get_data_value(col_id, pdf_config, sheet_index, total_sheets)
            if not value:
                resolved = self._resolve_placeholders(col_id, pdf_config, sheet_index, total_sheets)
                if resolved != col_id:
                    value = resolved
            cx_c   = x_pos + w / 2

            if label:
                svg += self._cajetin_svg_text(x_pos + 2, y_label, label,
                                              css_class="cajin label")
            if value:
                svg += self._cajetin_svg_text(cx_c, y_value, value,
                                              css_class="cajin valor", align="middle")
            x_pos += w
        return svg

    def _cajetin_render_sections(self, cajin_x, cajin_y, cajin_width_pt,
                                  cajin_height_pt, cajetin_template,
                                  pdf_config, sheet_index, total_sheets):
        """Formato complejo: array de sections con sub_columns, sub_rows, rows, etc."""
        svg = ""
        sections   = cajetin_template.get("sections", [])
        labels_map = cajetin_template.get("labels", {})

        total_pct = sum(s.get("width_pct", 0) for s in sections)
        if total_pct <= 0:
            return ""

        def abs_w(pct):
            return cajin_width_pt * (pct / total_pct)

        # Construir lista [(sec_dict, abs_x, abs_width)]
        rects = []
        cx = cajin_x
        for sec in sections:
            sw = abs_w(sec.get("width_pct", 0))
            rects.append((sec, cx, sw))
            cx += sw

        for sec, sx, sw in rects:
            sec_id = sec.get("id", "")
            rows   = max(1, int(sec.get("rows", 1)))
            row_h  = cajin_height_pt / rows

            right_x = sx + sw
            # Separador vertical derecho (omitir borde final)
            if right_x < cajin_x + cajin_width_pt - 0.3:
                svg += (f'<line x1="{right_x:.2f}" y1="{cajin_y:.2f}" '
                        f'x2="{right_x:.2f}" y2="{cajin_y + cajin_height_pt:.2f}" '
                        f'stroke="black" stroke-width="0.5"/>\n')

            # Caso A: sección con sub_columns
            if "sub_columns" in sec:
                sub_cols  = sec["sub_columns"]
                total_scp = sum(sc.get("width_pct", 0) for sc in sub_cols) or 1.0
                sec_label = sec.get("label", labels_map.get(sec_id, ""))
                sec_label = self._resolve_placeholders(sec_label, pdf_config, sheet_index, total_sheets)

                # Cabecera de sección (si hay etiqueta y múltiples filas)
                if sec_label and rows > 1:
                    svg += self._cajetin_svg_text(
                        sx + sw / 2, cajin_y + row_h * 0.6,
                        sec_label, css_class="cajin section-header", align="middle")

                scx = sx
                for sc in sub_cols:
                    sc_id  = sc.get("id", "")
                    sc_w   = sw * (sc.get("width_pct", 0) / total_scp)
                    sc_lbl = sc.get("label", labels_map.get(sc_id, ""))
                    sc_lbl = self._resolve_placeholders(sc_lbl, pdf_config, sheet_index, total_sheets)
                    sc_right = scx + sc_w

                    if sc_right < right_x - 0.3:
                        svg += (f'<line x1="{sc_right:.2f}" y1="{cajin_y:.2f}" '
                                f'x2="{sc_right:.2f}" y2="{cajin_y + cajin_height_pt:.2f}" '
                                f'stroke="black" stroke-width="0.5"/>\n')

                    # Cabecera de sub-columna (primera fila)
                    if sc_lbl:
                        svg += self._cajetin_svg_text(
                            scx + sc_w / 2, cajin_y + row_h * 0.6,
                            sc_lbl, css_class="cajin section-header", align="middle")

                    # Líneas horizontales entre filas de datos
                    for r in range(1, rows):
                        ry = cajin_y + row_h * r
                        svg += (f'<line x1="{scx:.2f}" y1="{ry:.2f}" '
                                f'x2="{sc_right:.2f}" y2="{ry:.2f}" '
                                f'stroke="black" stroke-width="0.3"/>\n')

                    scx += sc_w

            # Caso B: sección con sub_rows
            elif "sub_rows" in sec:
                sub_rows   = sec["sub_rows"]
                total_hrp  = sum(sr.get("height_pct", 1.0 / len(sub_rows))
                                  for sr in sub_rows) or 1.0
                sry = cajin_y

                for sr in sub_rows:
                    sr_id  = sr.get("id", "")
                    h_pct  = sr.get("height_pct", 1.0 / len(sub_rows))
                    sr_h   = cajin_height_pt * (h_pct / total_hrp)
                    sr_btm = sry + sr_h

                    # Línea inferior de sub-fila
                    if sr_btm < cajin_y + cajin_height_pt - 0.3:
                        svg += (f'<line x1="{sx:.2f}" y1="{sr_btm:.2f}" '
                                f'x2="{sx + sw:.2f}" y2="{sr_btm:.2f}" '
                                f'stroke="black" stroke-width="0.5"/>\n')

                    # Sub-fila con sub_columns propias
                    if "sub_columns" in sr:
                        sub_cols  = sr["sub_columns"]
                        total_scp = sum(sc.get("width_pct", 0) for sc in sub_cols) or 1.0
                        scx = sx
                        for sc in sub_cols:
                            sc_id    = sc.get("id", "")
                            sc_w     = sw * (sc.get("width_pct", 0) / total_scp)
                            sc_lbl   = sc.get("label", labels_map.get(sc_id, ""))
                            sc_lbl   = self._resolve_placeholders(sc_lbl, pdf_config, sheet_index, total_sheets)
                            sc_vstyle= sc.get("value_style", "")
                            sc_right = scx + sc_w

                            if sc_right < sx + sw - 0.3:
                                svg += (f'<line x1="{sc_right:.2f}" y1="{sry:.2f}" '
                                        f'x2="{sc_right:.2f}" y2="{sry + sr_h:.2f}" '
                                        f'stroke="black" stroke-width="0.5"/>\n')

                            if sc_lbl:
                                svg += self._cajetin_svg_text(
                                    scx + 2, sry + sr_h * 0.38,
                                    sc_lbl, css_class="cajin label")

                            val = self._cajetin_get_data_value(
                                sc_id, pdf_config, sheet_index, total_sheets)
                            if not val:
                                resolved = self._resolve_placeholders(sc_id, pdf_config, sheet_index, total_sheets)
                                if resolved != sc_id:
                                    val = resolved
                            if val:
                                svg += self._cajetin_svg_text(
                                    scx + sc_w / 2, sry + sr_h * 0.76,
                                    val, css_class="cajin valor",
                                    align="middle", extra_style=sc_vstyle)
                            scx += sc_w

                    # Sub-fila simple (sin sub_columns)
                    else:
                        sr_lbl    = sr.get("label", labels_map.get(sr_id, ""))
                        sr_lbl    = self._resolve_placeholders(sr_lbl, pdf_config, sheet_index, total_sheets)
                        sr_vstyle = sr.get("value_style", "")
                        if sr_lbl:
                            svg += self._cajetin_svg_text(
                                sx + 2, sry + sr_h * 0.45,
                                sr_lbl, css_class="cajin label")
                        val = self._cajetin_get_data_value(
                            sr_id, pdf_config, sheet_index, total_sheets)
                        if not val:
                            resolved = self._resolve_placeholders(sr_id, pdf_config, sheet_index, total_sheets)
                            if resolved != sr_id:
                                val = resolved
                        if val:
                            svg += self._cajetin_svg_text(
                                sx + sw / 2, sry + sr_h * 0.8,
                                val, css_class="cajin valor",
                                align="middle", extra_style=sr_vstyle)

                    sry += sr_h

            # Caso C: sección simple
            else:
                sec_lbl    = sec.get("label", labels_map.get(sec_id, ""))
                sec_lbl    = self._resolve_placeholders(sec_lbl, pdf_config, sheet_index, total_sheets)
                sub_lbl    = sec.get("sub_label", "")
                sub_lbl    = self._resolve_placeholders(sub_lbl, pdf_config, sheet_index, total_sheets)
                lbl_align  = sec.get("label_align", "center")
                lbl_valign = sec.get("label_valign", "center")
                vstyle     = sec.get("value_style", "")

                svg_align = "middle" if lbl_align == "center" else (
                            "start"  if lbl_align == "left"   else "end")
                lx     = sx + sw / 2 if lbl_align == "center" else sx + 2
                ly_frc = 0.35 if lbl_valign == "top" else (
                          0.65 if lbl_valign == "bottom" else 0.5)

                # Líneas horizontales entre filas
                for r in range(1, rows):
                    ry = cajin_y + row_h * r
                    svg += (f'<line x1="{sx:.2f}" y1="{ry:.2f}" '
                            f'x2="{sx + sw:.2f}" y2="{ry:.2f}" '
                            f'stroke="black" stroke-width="0.3"/>\n')

                if sec_lbl:
                    svg += self._cajetin_svg_text(
                        lx, cajin_y + cajin_height_pt * ly_frc,
                        sec_lbl, css_class="cajin section-header", align=svg_align)
                if sub_lbl:
                    svg += self._cajetin_svg_text(
                        sx + sw / 2, cajin_y + cajin_height_pt * 0.55,
                        sub_lbl, css_class="cajin label", align="middle")

                val = self._cajetin_get_data_value(
                    sec_id, pdf_config, sheet_index, total_sheets)
                if not val:
                    resolved = self._resolve_placeholders(sec_id, pdf_config, sheet_index, total_sheets)
                    if resolved != sec_id:
                        val = resolved
                if val:
                    svg += self._cajetin_svg_text(
                        sx + sw / 2, cajin_y + cajin_height_pt * 0.75,
                        val, css_class="cajin valor",
                        align="middle", extra_style=vstyle)

        return svg

    def _sheet_without_cajetin(self):
        """True si la hoja activa se exporta SIN cajetín (solo marco + página)."""
        try:
            sheet = self.project.get_active_sheet()
            name = sheet.name if sheet else ""
        except Exception:
            return False
        return name in ("Hoja de Gabinete 2D", "Lista de Materiales", "Tabla de Cableado")

    def _generate_page_number_svg(self, width_pt, height_pt, margin_pt, sheet_index, total_sheets):
        """Número de página pequeño para hojas que no llevan cajetín."""
        cajin_height_pt = self._get_template_value("page", "cajetin", "height_mm", default=15) * mm
        text = f"{sheet_index + 1} de {total_sheets}"
        x = width_pt - margin_pt - 6
        y = height_pt - margin_pt - (cajin_height_pt / 2) + 3
        return (f'\n  <!-- NÚMERO DE PÁGINA (hoja sin cajetín) -->\n'
                f'  <text x="{x:.2f}" y="{y:.2f}" text-anchor="end" '
                f'style="font-family: Helvetica, Arial, sans-serif; font-size: 8pt; fill: black;">{text}</text>\n')

    def _generate_cajetin_svg(self, width_pt, height_pt, margin_pt, pdf_config,
                               sheet_index=0, total_sheets=1):
        """Genera el cajetín en SVG de forma completamente genérica a partir
        de la plantilla .pte activa, sin ninguna lógica hardcodeada de columnas.

        Soporta dos formatos de plantilla:
        - **simple** (``columns_mm``): lista de anchos en mm, etiqueta/valor en dos filas.
        - **complejo** (``sections``): array de secciones con soporte para
          ``sub_columns``, ``sub_rows``, ``rows``, ``height_pct``, ``width_pct``,
          ``label_align``, ``label_valign`` y ``value_style``.

        Args:
            sheet_index: Índice 0-based de la hoja/página actual.
            total_sheets: Total de páginas físicas del proyecto.
        """
        svg = ""

        template = self._load_pdf_template()
        if not template:
            return ""

        cajetin_template = template.get("cajetin", {})
        cajin_height_pt  = self._get_template_value(
            "page", "cajetin", "height_mm", default=15) * mm

        has_sections  = bool(cajetin_template.get("sections"))
        has_col_mm    = bool(cajetin_template.get("columns_mm"))

        if not has_sections and not has_col_mm:
            return ""  # Plantilla sin información de cajetín

        # Anchura del cajetín
        if has_sections:
            # El cajetín ocupa todo el ancho interior de la página
            cajin_width_pt = width_pt - 2 * margin_pt
        else:
            cajin_width_pt = sum(
                float(mm) * float(w)
                for w in cajetin_template.get("columns_mm", []))

        # Posición: siempre en la parte inferior
        # Formato sections -> alineado al margen izquierdo (anchura total)
        # Formato columns_mm -> alineado a la derecha (comportamiento original)
        if has_sections:
            cajin_x = margin_pt
        else:
            cajin_x = width_pt - margin_pt - cajin_width_pt

        cajin_y = height_pt - margin_pt - cajin_height_pt

        # Marco exterior
        svg += (f'\n  <!-- CAJETÍN -->\n'
                f'  <rect x="{cajin_x:.2f}" y="{cajin_y:.2f}" '
                f'width="{cajin_width_pt:.2f}" height="{cajin_height_pt:.2f}" '
                f'fill="none" stroke="black" stroke-width="0.75"/>\n')

        # Contenido según formato
        if has_sections:
            svg += self._cajetin_render_sections(
                cajin_x, cajin_y, cajin_width_pt, cajin_height_pt,
                cajetin_template, pdf_config, sheet_index, total_sheets)
        else:
            svg += self._cajetin_render_simple_columns(
                cajin_x, cajin_y, cajin_width_pt, cajin_height_pt,
                cajetin_template, pdf_config, sheet_index, total_sheets)

        return svg

    # MÉTODOS DE CONTROL DE SIMULACIÓN
    # La lógica está en simulation/simulation_controller.py

    def config_pdf(self):
        """Muestra una ventana de diálogo para configurar los parámetros del PDF."""
        config_window = tk.Toplevel(self.app.root)
        config_window.title("Configuración PDF")
        config_window.geometry("450x580")
        config_window.resizable(False, False)
        config_window.transient(self.app.root)
        config_window.grab_set()

        # Usar una copia para edición temporal
        if hasattr(self, 'config') and self.config:
            pdf_config = self.config.get("pdf_config", DEFAULT_CONFIG["pdf_config"]).copy()
        else:
            pdf_config = DEFAULT_CONFIG["pdf_config"].copy()

        # Compatibilidad con configuraciones antiguas que usaban pdf_template en la raíz
        if not pdf_config.get("pdf_template") and hasattr(self, 'config'):
            pdf_config["pdf_template"] = self.config.get("pdf_template", "")

        main_frame = tk.Frame(config_window, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="Configuración del Cajetín y Página",
                 font=(AppConstants.UI_FONT_FAMILY, 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 20))

        # Función para buscar plantilla en el sistema de archivos
        def browse_template(entry_widget):
            template_dir = str(Path(__file__).resolve().parent.parent / "template")
            file_path = filedialog.askopenfilename(
                title="Seleccionar plantilla PDF",
                initialdir=template_dir,
                filetypes=[("Plantillas PTE", "*.pte"), ("JSON y PTE", "*.json;*.pte"), ("Todos los archivos", "*")]
            )
            if file_path:
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, file_path)

        # Campos de texto
        fields = [
            ("proyecto", "Nombre del Proyecto:"),
            ("dibujado_por", "Dibujado por:"),
            ("revisado_por", "Revisado por:"),
            ("aprobado_por", "Aprobado por:"),
            ("empresa", "Empresa:"),
            ("direccion", "Dirección:"),
            ("escala", "Escala:"),
            ("version", "Versión:"),
            ("pdf_template", "Plantilla PDF:")
        ]

        entries = {}
        for i, (key, label) in enumerate(fields):
            tk.Label(main_frame, text=label, font=(AppConstants.UI_FONT_FAMILY, 10)).grid(row=i+1, column=0, sticky="w", pady=5)
            entry = tk.Entry(main_frame, width=35, font=(AppConstants.UI_FONT_FAMILY, 10))
            entry.insert(0, pdf_config.get(key, ""))
            entry.grid(row=i+1, column=1, sticky="ew", pady=5)
            entries[key] = entry

            if key == "pdf_template":
                browse_btn = tk.Button(main_frame, text="Examinar", command=lambda e=entry: browse_template(e), font=(AppConstants.UI_FONT_FAMILY, 9))
                browse_btn.grid(row=i+1, column=2, sticky="w", padx=(5, 0), pady=5)

        main_frame.columnconfigure(1, weight=1)

        tk.Label(main_frame, text="Formato de página:", font=(AppConstants.UI_FONT_FAMILY, 10)).grid(row=len(fields)+1, column=0, sticky="w", pady=10)
        formato_var = tk.StringVar(value=pdf_config.get("formato", "A4"))
        formato_frame = tk.Frame(main_frame)
        formato_frame.grid(row=len(fields)+1, column=1, sticky="w", pady=10)
        tk.Radiobutton(formato_frame, text="A4", variable=formato_var, value="A4", font=(AppConstants.UI_FONT_FAMILY, 9)).pack(side=tk.LEFT)
        tk.Radiobutton(formato_frame, text="A3", variable=formato_var, value="A3", font=(AppConstants.UI_FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=10)

        tk.Label(main_frame, text="Orientación:", font=(AppConstants.UI_FONT_FAMILY, 10)).grid(row=len(fields)+2, column=0, sticky="w", pady=10)
        orientacion_var = tk.StringVar(value=pdf_config.get("orientacion", "vertical"))
        orient_frame = tk.Frame(main_frame)
        orient_frame.grid(row=len(fields)+2, column=1, sticky="w", pady=10)
        tk.Radiobutton(orient_frame, text="Vertical", variable=orientacion_var, value="vertical", font=(AppConstants.UI_FONT_FAMILY, 9)).pack(side=tk.LEFT)
        tk.Radiobutton(orient_frame, text="Horizontal", variable=orientacion_var, value="horizontal", font=(AppConstants.UI_FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=10)

        def save_and_close():
            for key, entry in entries.items():
                pdf_config[key] = entry.get()

            pdf_config["formato"] = formato_var.get()
            pdf_config["orientacion"] = orientacion_var.get()

            self.app.config["pdf_config"] = pdf_config

            # Mantener el nombre visible del proyecto y el cajetín PDF en
            # sincronía, también al crear un proyecto nuevo.
            project_name = pdf_config.get("proyecto", "").strip()
            if project_name and hasattr(self.app, "project"):
                self.app.project.name = project_name
                if hasattr(self.app, "update_sheet_list_ui"):
                    self.app.update_sheet_list_ui()

            # Persistir en disco
            save_config(self.app.config)

            # Forzar recarga de plantilla en memoria para que cambios se apliquen
            try:
                self._pdf_template = None
                self._load_pdf_template(force_reload=True)
            except Exception:
                pass

            # Informar al usuario
            self.app.set_status("✅ Configuración PDF guardada", "green")

            # Cerrar la ventana al guardar
            config_window.destroy()

        # Botones
        btn_frame = tk.Frame(main_frame)
        btn_frame.grid(row=len(fields)+3, column=0, columnspan=2, pady=20)

        tk.Button(btn_frame, text="Guardar", command=save_and_close, width=15, bg="#4CAF50", fg="white",
                  font=(AppConstants.UI_FONT_FAMILY, 10, "bold")).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancelar", command=config_window.destroy, width=15,
                  font=(AppConstants.UI_FONT_FAMILY, 10)).pack(side=tk.LEFT)

    def export_pdf(self):
        """Exporta el diagrama a PDF con marco técnico."""
        if not getattr(self, 'REPORTLAB_SUPPORT', False):
            messagebox.showerror("Error", "ReportLab no está instalado.\nInstala con: pip install reportlab", parent=getattr(self.app, 'root', None))
            return

        initial_name = ""
        if self.app.current_file:
            initial_name = os.path.splitext(os.path.basename(self.app.current_file))[0] + ".pdf"

        filename = filedialog.asksaveasfilename(
            title="Exportar a PDF",
            defaultextension=".pdf",
            initialdir=self.app.config.get("work_dir", str(Path.home() / "Documentos" / "Proyectos") if __import__("platform").system() != "Windows" else str(Path.home() / "Documents" / "Proyectos")),
            initialfile=initial_name,
            filetypes=[("Archivos PDF", "*.pdf"), ("Todos los archivos", "*.*")],
            parent=self.app.root,
            confirmoverwrite=False,
        )
        if not filename or not confirm_overwrite(getattr(self.app, "root", None), filename):
            return

        try:
            self._pdf_template = None
            self._load_pdf_template(force_reload=True)
            if not hasattr(self.app, 'config'):
                raise Exception("Configuración de aplicación no inicializada")
            if not hasattr(self.app, 'components'):
                raise Exception("Lista de componentes no inicializada")
            self._generate_pdf(filename)
            self.app.set_status("📄 PDF exportado con éxito", "green")
            show_export_success(getattr(self.app, "root", None), "PDF", filename)
        except Exception as e:
            error_msg = f"Error al exportar PDF:\n{str(e)}\n\nVerifica que:"
            error_msg += "\n- La aplicación esté completamente cargada"
            error_msg += "\n- Haya componentes en el diagrama"
            error_msg += "\n- Tienes permisos de escritura"
            messagebox.showerror("Error", error_msg, parent=getattr(self.app, 'root', None))

    def __getattr__(self, name):
        """Delega atributos no encontrados en PdfExporter hacia app."""
        if name == 'app':
            raise AttributeError(name)
        return getattr(self.app, name)

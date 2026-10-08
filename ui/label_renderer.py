"""
Módulo para el renderizado de etiquetas en el canvas de Tkinter.
"""
from utils.utility_functions import adapt_color_for_display

class LabelRenderer:
    @staticmethod
    def draw(component):
        """Dibuja la etiqueta del componente en su canvas."""
        canvas = component.canvas
        ld = component.label_data

        # 1. Verificar visibilidad global
        if not getattr(canvas, 'show_labels', True):
            return

        # 2. Casos especiales donde no se dibuja (ej: Tierra)
        if getattr(component, 'component_type', '') == "tierra":
            return

        # 3. Determinar posición y anclaje
        label_x, label_y, anchor = LabelRenderer._calculate_position(component)

        # 4. Dibujar Nombre (ID)
        if ld.get('name'):
            text_color = adapt_color_for_display("black", canvas.cget("bg"))
            name_id = canvas.create_text(
                label_x, label_y,
                text=ld['name'],
                font=("Arial", 8, "normal"),
                fill=text_color,
                anchor=anchor,
                tags=f"label_{id(component)}"
            )
            component.label_ids.append(name_id)

            # 5. Dibujar Descripción y Detalles
            LabelRenderer._draw_details(component, label_x, label_y, anchor)

        # 6. Pantallas especiales (ej: VDF)
        if "vdf-c" in getattr(component, 'svg_file', '').lower():
            LabelRenderer.draw_vdf_display(component)

    @staticmethod
    def _calculate_position(component):
        """Calcula coordenadas x, y y el anchor para la etiqueta."""
        zoom = component.canvas.zoom_level
        comp_type = getattr(component, 'component_type', 'normal')
        ld = component.label_data

        if comp_type == "fase":
            return LabelRenderer._get_fase_label_position(component)

        if comp_type in ["conxn", "conxn2", "borner", "normal"]:
            if ld.get('derecha', False):
                x = (component.x + component.size[0] + 5) * zoom  # posicion de etiqueta conxn
                y = (component.y + 9) * zoom
                return x, y, "nw"
            else:
                x = (component.x - 5) * zoom
                y = (component.y + 5) * zoom
                return x, y, "ne"

        # Por defecto a la derecha
        return (component.x + component.size[0] + 5) * zoom, component.y * zoom, "nw"

    @staticmethod
    def _draw_details(component, label_x, label_y, anchor):
        """Dibuja campos de descripción, marca, voltaje, etc."""
        canvas = component.canvas
        ld = component.label_data
        y_offset = 12

        # Descripción
        if ld.get('show_details') and ld.get('description'):
            desc_color = adapt_color_for_display("blue", canvas.cget("bg"))
            desc_id = canvas.create_text(
                label_x, (label_y + y_offset),
                text=ld['description'],
                font=("Arial", 7, "italic"),
                fill=desc_color,
                anchor=anchor,
                tags=f"label_{id(component)}"
            )
            component.label_ids.append(desc_id)
            y_offset += 12
        elif ld.get('name'):
            y_offset = 15 # Espacio si hay nombre pero no descripción visible

        # Otros campos si show_details está activo
        if ld.get('show_details') and getattr(component, 'component_type', '') == "normal":
            for field in ['marca', 'voltaje', 'amperios', 'potencia']:
                val = ld.get(field)
                if val:
                    # Omitir potencia si no es motor
                    if field == 'potencia' and getattr(component, 'category', '') != 'Motors':
                        continue

                    color = adapt_color_for_display("black", canvas.cget("bg"))
                    item_id = canvas.create_text(
                        label_x, (label_y + y_offset),
                        text=str(val),
                        font=("Arial", 8),
                        fill=color,
                        anchor=anchor,
                        tags=f"label_{id(component)}"
                    )
                    component.label_ids.append(item_id)
                    y_offset += 12

    @staticmethod
    def _get_fase_label_position(component):
        """Calcula la posición de la etiqueta para fase.svg del lado opuesto al punto de conexión."""
        zoom = component.canvas.zoom_level
        if not component.conn_points:
            return (component.x - 20) * zoom, (component.y - 4) * zoom, "nw"

        center_x = component.size[0] / 2
        center_y = component.size[1] / 2
        connection_side = "right" # por defecto

        if hasattr(component, 'get_connection_points_global'):
            global_points = component.get_connection_points_global()
            for global_x, global_y, _ in global_points:
                # Calcular la posición del punto relativa al componente transformado
                point_x = global_x - component.x
                point_y = global_y - component.y
                if point_x < center_x * 0.3: connection_side = "left"
                elif point_x > center_x * 1.7: connection_side = "right"
                elif point_y < center_y * 0.3: connection_side = "top"
                elif point_y > center_y * 1.7: connection_side = "bottom"
        else:
            for point in component.conn_points:
                point_x, point_y = point.x, point.y
                if point_x < center_x * 0.3: connection_side = "left"
                elif point_x > center_x * 1.7: connection_side = "right"
                elif point_y < center_y * 0.3: connection_side = "top"
                elif point_y > center_y * 1.7: connection_side = "bottom"

            if getattr(component, 'flipped_h', False):
                if connection_side == "left": connection_side = "right"
                elif connection_side == "right": connection_side = "left"

        if connection_side == "left":
            return (component.x + component.size[0] + 8) * zoom, (component.y + component.size[1]/2 - 2) * zoom, "w"
        elif connection_side == "right":
            return (component.x - 4) * zoom, (component.y + component.size[1]/2 - 1) * zoom, "e" # posicion de etiqueta fase,svg
        elif connection_side == "top":
            return (component.x + component.size[0]/2 + 3) * zoom, (component.y + component.size[1] + 3) * zoom, "n"
        else:
            return (component.x + component.size[0]/2 + 3) * zoom, (component.y - 17) * zoom, "s"

    @staticmethod
    def draw_vdf_display(component):
        """Dibuja métricas dinámicas en el centro del VDF-C."""
        canvas = component.canvas
        canvas.delete(f"vdf_metrics_{id(component)}")

        if not getattr(component, 'is_active', False):
            return

        zoom = canvas.zoom_level
        cx = (component.x + component.size[0]/2) * zoom
        cy = (component.y + component.size[1]/2) * zoom

        freq = getattr(component, 'current_freq', 0.0)
        rpm = getattr(component, 'current_rpm', 0.0)
        fren = "OFF" if freq > 0 else "STOP"

        metrics_text = (
            f"CONS: {freq:.1f}Hz\n"
            f"FREC: {freq:.1f}Hz\n"
            f"VELO: {rpm:.0f}RPM\n"
            f"FREN: {fren}"
        )

        item_id = canvas.create_text(
            cx, cy-10,
            text=metrics_text,
            font=("Courier", int(10 * zoom), "bold"),
            fill="#0a140a", # Verde tipo display antiguo
            anchor="center",
            justify="left",
            tags=(f"vdf_metrics_{id(component)}", "vdf_display")
        )
        component.label_ids.append(item_id)

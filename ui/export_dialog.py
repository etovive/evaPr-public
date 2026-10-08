import os
import tkinter as tk
from tkinter import ttk

_DIALOG_WIDTH = 540
_DIALOG_HEIGHT = 230

def _show_success(parent, heading, message, filename, detail=None, warnings=None):
    """Muestra una confirmación sobria y consistente para exportar o guardar."""
    window = tk.Toplevel(parent)
    window.title("evaPr")
    window.resizable(False, False)
    window.transient(parent)
    window.configure(bg="#f7f7f7")

    # Tamaño y posición deterministas para mantener el mismo estilo en todos
    # los avisos de exportación y guardado.
    window.geometry(f"{_DIALOG_WIDTH}x{_DIALOG_HEIGHT}")
    window.update_idletasks()
    if parent:
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        x = parent_x + max(0, (parent_width - _DIALOG_WIDTH) // 2)
        y = parent_y + max(0, (parent_height - _DIALOG_HEIGHT) // 2)
        window.geometry(f"{_DIALOG_WIDTH}x{_DIALOG_HEIGHT}+{x}+{y}")

    body = tk.Frame(window, bg="#f7f7f7", padx=28, pady=22)
    body.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        body,
        text=heading,
        bg="#f7f7f7",
        fg="#1f2937",
        font=("Arial", 13, "bold"),
        anchor="w",
    ).pack(fill=tk.X)
    tk.Label(
        body,
        text=message,
        bg="#f7f7f7",
        fg="#4b5563",
        font=("Arial", 10),
        anchor="w",
        pady=8,
    ).pack(fill=tk.X)

    if detail:
        tk.Label(
            body,
            text=detail,
            bg="#f7f7f7",
            fg="#4b5563",
            font=("Arial", 9),
            anchor="w",
            pady=2,
        ).pack(fill=tk.X)

    if filename:
        path_label = tk.Label(
            body,
            text=filename,
            bg="#eef2f7",
            fg="#374151",
            font=("Arial", 9),
            anchor="w",
            padx=10,
            pady=7,
        )
        path_label.pack(fill=tk.X)

    if warnings:
        # El aviso mantiene una altura fija; la barra resume incidencias sin
        # desplazar el botón ni convertir el diálogo en una ventana variable.
        tk.Label(
            body,
            text=f"Se generó con {len(warnings)} aviso(s).",
            bg="#f7f7f7",
            fg="#9a6700",
            font=("Arial", 9),
            anchor="w",
            pady=5,
        ).pack(fill=tk.X)

    separator = ttk.Separator(window, orient=tk.HORIZONTAL)
    separator.pack(fill=tk.X)
    footer = tk.Frame(window, bg="#f7f7f7", padx=20, pady=10)
    footer.pack(fill=tk.X)

    close_button = tk.Button(
        footer,
        text="Aceptar",
        command=window.destroy,
        width=14,
        bg="#ffffff",
        fg="#1f2937",
        activebackground="#e9eef5",
        relief=tk.FLAT,
        bd=1,
        highlightthickness=1,
        highlightbackground="#cbd5e1",
        font=("Arial", 10),
        cursor="hand2",
    )
    close_button.pack(side=tk.RIGHT)

    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.bind("<Escape>", lambda _event: window.destroy())
    window.bind("<Return>", lambda _event: window.destroy())
    window.grab_set()
    close_button.focus_set()
    window.wait_window()

def show_export_success(parent, file_format, filename, warnings=None, description=None):
    """Muestra una confirmación uniforme al finalizar cualquier exportación."""
    message = description or (
        f"El diagrama se exportó correctamente como archivo {file_format.upper()}."
    )
    _show_success(parent, "Exportación completada", message, filename, warnings=warnings)

def show_save_success(parent, filename=None, detail=None, message=None):
    """Muestra la misma ventana de confirmación al guardar datos."""
    _show_success(
        parent,
        "Guardado completado",
        message or "El proyecto se guardó correctamente.",
        filename,
        detail=detail,
    )

def show_load_success(parent, filename, detail=None):
    """Muestra la confirmación uniforme al cargar un proyecto."""
    _show_success(
        parent,
        "Carga completada",
        "El proyecto se cargó correctamente.",
        filename,
        detail=detail,
    )

def ask_choice(parent, heading, message, choices):
    """Muestra una pregunta modal uniforme y devuelve el valor elegido."""
    window = tk.Toplevel(parent)
    window.title("evaPr")
    window.resizable(False, False)
    window.transient(parent)
    window.configure(bg="#f7f7f7")
    window.geometry(f"{_DIALOG_WIDTH}x{_DIALOG_HEIGHT}")
    window.update_idletasks()
    if parent:
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - _DIALOG_WIDTH) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - _DIALOG_HEIGHT) // 2)
        window.geometry(f"{_DIALOG_WIDTH}x{_DIALOG_HEIGHT}+{x}+{y}")

    result = {"value": None}
    body = tk.Frame(window, bg="#f7f7f7", padx=28, pady=22)
    body.pack(fill=tk.BOTH, expand=True)
    tk.Label(
        body,
        text=heading,
        bg="#f7f7f7",
        fg="#1f2937",
        font=("Arial", 13, "bold"),
        anchor="w",
    ).pack(fill=tk.X)
    tk.Label(
        body,
        text=message,
        bg="#f7f7f7",
        fg="#4b5563",
        font=("Arial", 10),
        anchor="w",
        justify=tk.LEFT,
        wraplength=480,
        pady=10,
    ).pack(fill=tk.X)

    ttk.Separator(window, orient=tk.HORIZONTAL).pack(fill=tk.X)
    footer = tk.Frame(window, bg="#f7f7f7", padx=20, pady=10)
    footer.pack(fill=tk.X)

    def choose(value):
        result["value"] = value
        window.destroy()

    for label, value in reversed(choices):
        button = tk.Button(
            footer,
            text=label,
            command=lambda selected=value: choose(selected),
            width=14,
            bg="#ffffff",
            fg="#1f2937",
            activebackground="#e9eef5",
            relief=tk.FLAT,
            bd=1,
            highlightthickness=1,
            highlightbackground="#cbd5e1",
            font=("Arial", 10),
            cursor="hand2",
        )
        button.pack(side=tk.RIGHT, padx=(8, 0))

    window.protocol("WM_DELETE_WINDOW", lambda: choose(None))
    window.bind("<Escape>", lambda _event: choose(None))
    window.grab_set()
    if footer.winfo_children():
        footer.winfo_children()[0].focus_set()
    window.wait_window()
    return result["value"]

def ask_save_changes(parent, action="salir"):
    """Pregunta si guardar antes de descartar cambios; devuelve yes/no/None."""
    return ask_choice(
        parent,
        "Guardar cambios",
        f"¿Desea guardar los cambios antes de {action}?",
        [("Guardar", "yes"), ("No guardar", "no"), ("Cancelar", "cancel")],
    )

def confirm_overwrite(parent, filename):
    """Confirma la sobrescritura con la ventana uniforme si el archivo existe."""
    if not os.path.exists(filename):
        return True
    return ask_choice(
        parent,
        "El archivo ya existe",
        f"Ya existe un archivo con este nombre:\n{filename}\n\n¿Desea sobrescribirlo?",
        [("Sobrescribir", "yes"), ("Cancelar", "no")],
    ) == "yes"

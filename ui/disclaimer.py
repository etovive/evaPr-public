"""Diálogo modal obligatorio de aceptación del aviso legal.

Se muestra en el arranque, antes de construir la interfaz, la primera vez que
se ejecuta la aplicación (y cada vez que cambia `DISCLAIMER_VERSION`).
"""
import tkinter as tk

from config.settings import load_config, save_config
from config.disclaimer import (
    DISCLAIMER_ACCEPT_LABEL,
    DISCLAIMER_REJECT_LABEL,
    DISCLAIMER_TEXT,
    DISCLAIMER_TITLE,
    DISCLAIMER_FOOTER,
    is_accepted,
    mark_accepted,
)


def ensure_disclaimer_accepted(root, config=None):
    """Muestra el aviso legal si aún no fue aceptado.

    Returns:
        True si el usuario aceptó (o ya había aceptado); False si rechazó/cerró.
    """
    if config is None:
        config = load_config()
    if is_accepted(config):
        return True
    return _show_dialog(root, config)


def _show_dialog(root, config):
    # Estado compartido y manejadores: se definen primero porque los botones y
    # el cierre de la ventana los referencian al construirse.
    state = {"accepted": False}

    win = tk.Toplevel(root)
    win.title(DISCLAIMER_TITLE)
    win.configure(bg="#ffffff")
    win.resizable(True, True)

    def _accept():
        state["accepted"] = True
        mark_accepted(config)
        save_config(config)
        win.destroy()

    def _reject():
        state["accepted"] = False
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", _reject)

    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass

    body = tk.Frame(win, bg="#ffffff", padx=16, pady=16)
    body.pack(fill="both", expand=True)

    text = tk.Text(
        body,
        wrap="word",
        width=92,
        height=24,
        font=("Helvetica", 10),
        bg="#fafafa",
        fg="#212121",
        relief="sunken",
        bd=1,
        padx=10,
        pady=10,
        spacing1=2,
        spacing3=2,
        cursor="arrow",
    )
    scroll = tk.Scrollbar(body, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)

    text.insert("1.0", DISCLAIMER_TEXT)
    text.insert("end", "\n" + DISCLAIMER_FOOTER + "\n")
    text.configure(state="disabled")

    notice = tk.Label(
        win,
        text=DISCLAIMER_ACCEPT_LABEL + ".",
        bg="#ffffff",
        fg="#212121",
        font=("Helvetica", 10, "bold"),
        wraplength=720,
        justify="left",
        padx=16,
        pady=10,
    )
    notice.pack(fill="x")

    buttons = tk.Frame(win, bg="#ffffff", padx=16, pady=14)
    buttons.pack(fill="x")

    reject_btn = tk.Button(
        buttons,
        text=DISCLAIMER_REJECT_LABEL,
        command=_reject,
        width=16,
        bg="#eeeeee",
        fg="#212121",
        relief="raised",
        bd=1,
    )
    reject_btn.pack(side="left")

    accept_btn = tk.Button(
        buttons,
        text="Acepto",
        command=_accept,
        width=16,
        bg="#2e7d32",
        fg="white",
        activebackground="#1b5e20",
        activeforeground="white",
        relief="raised",
        bd=1,
        font=("Helvetica", 10, "bold"),
    )
    accept_btn.pack(side="right")

    # Centrar sobre la pantalla y hacerlo modal
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    x = max(0, (win.winfo_screenwidth() - w) // 2)
    y = max(0, (win.winfo_screenheight() - h) // 3)
    win.geometry(f"+{x}+{y}")

    accept_btn.focus_set()
    win.lift()
    win.grab_set()
    win.wait_window()

    if not state["accepted"]:
        print("⚠️ Aviso legal no aceptado: la aplicación se cerrará.")
    return state["accepted"]

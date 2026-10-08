import tkinter as tk
import subprocess
import re
from utils.svg_renderer import get_svg_renderer
from config.settings import APP_VERSION

_monitors_cache = None

def _get_monitors():
    """
    Obtiene la geometría de cada monitor activo usando xrandr.
    Usa caché para evitar llamar a xrandr múltiples veces.

    Retorna lista de dict con keys: x, y, w, h
    """
    global _monitors_cache
    if _monitors_cache is not None:
        return _monitors_cache

    try:
        output = subprocess.check_output(
            ["xrandr", "--query"], stderr=subprocess.DEVNULL, text=True
        )
    except Exception:
        _monitors_cache = None
        return None

    monitors = []
    for line in output.splitlines():
        # Buscar líneas como: "DVI-I-1 connected primary 1600x900+0+0"
        # o "VGA-1 connected 1600x900+1600+0"
        m = re.search(
            r'connected\s+(?:primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)', line
        )
        if m:
            monitors.append({
                "w": int(m.group(1)),
                "h": int(m.group(2)),
                "x": int(m.group(3)),
                "y": int(m.group(4)),
            })
    _monitors_cache = monitors if monitors else None
    return _monitors_cache

class SplashScreen:
    """
    Muestra una ventana de bienvenida con el logo de la aplicación.
    """
    def __init__(self, root_temp, splash_svg_path, duration_ms=2000):
        """
        Inicializa y muestra la pantalla de inicio.

        Args:
            root_temp: Una instancia temporal de tk.Tk o Toplevel para manejar eventos.
            splash_svg_path: Ruta al archivo splash.svg.
            duration_ms: Duración mínima en milisegundos (opcional).
        """
        self.splash = tk.Toplevel(root_temp)
        self.splash.overrideredirect(True)  # Sin bordes ni barra de título

        renderer = get_svg_renderer()
        width, height = 600, 400

        self.splash.withdraw()
        self.splash.update_idletasks()

        mx = self.splash.winfo_pointerx()
        my = self.splash.winfo_pointery()

        # Intentar obtener monitores reales desde xrandr (con caché)
        monitors = _get_monitors()

        if monitors:
            # Encontrar el monitor donde está el puntero
            active = None
            for mon in monitors:
                if (mon["x"] <= mx < mon["x"] + mon["w"] and
                        mon["y"] <= my < mon["y"] + mon["h"]):
                    active = mon
                    break

            # Si no se encontró (puntero fuera de todos), usar el primero
            if active is None:
                active = monitors[0]

            target_x = active["x"] + (active["w"] - width) // 2
            target_y = active["y"] + (active["h"] - height) // 2
        else:
            # Fallback: usar screen completa
            vw = self.splash.winfo_screenwidth()
            vh = self.splash.winfo_screenheight()
            target_x = (vw - width) // 2
            target_y = (vh - height) // 2

        self.splash.geometry(f"{width}x{height}+{int(target_x)}+{int(target_y)}")

        try:
            self.splash.attributes('-type', 'splash')
        except:
            pass

        self.splash.deiconify()
        self.splash.lift()
        self.splash.attributes('-topmost', True)
        self.splash.update()

        self.photo = renderer.create_button_image(
            "splash.svg", size=(width, height), high_quality=False
        )

        if self.photo:
            label = tk.Label(self.splash, image=self.photo, bg='white')
            label.pack()
        else:
            label = tk.Label(
                self.splash, text="eduCAd\nCargando...",
                font=("Helvetica", 24, "bold"),
                bg='#2c3e50', fg='white',
                width=20, height=10,
            )
            label.pack()

        version_label = tk.Label(
            self.splash,
            text=f"v{APP_VERSION}",
            font=("Helvetica", 10),
            bg='white', fg='#888888',
        )
        version_label.pack(side="bottom", pady=(0, 10))

        self.splash.update()

    def close(self):
        """Cierra la pantalla de inicio."""
        if self.splash:
            self.splash.destroy()
            self.splash = None

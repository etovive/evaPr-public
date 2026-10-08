import io
from pathlib import Path
from utils.utils import get_app_dir

try:
    import cairosvg
    SVG_SUPPORT = True
except ImportError:
    SVG_SUPPORT = False

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

class SvgRenderer:
    """Sistema centralizado para renderizado de SVG en diferentes contextos"""

    def __init__(self, svg_base_path=None):
        """
        Inicializa el renderizador SVG

        Args:
            svg_base_path (str): Ruta base donde se almacenan los archivos SVG
        """
        self.svg_base_path = Path(svg_base_path) if svg_base_path else None
        self.button_config = {
            'default_size': (128, 128), # Tamaño mayor para mejor definición
            'interpolation': (
                Image.Resampling.LANCZOS
                if PIL_AVAILABLE and hasattr(Image, 'Resampling')
                else Image.LANCZOS if PIL_AVAILABLE else None
            ),
            'background_color': None,
            'scale_factor': 4.0, # Factor de escalado 4x para máxima calidad
            # Sobremuestreo del render antes de reducir al tamaño final.  Antes el
            # caché guardaba PNG de 900x900 y se reducía con LANCZOS en cada
            # arranque: abrir 900x900 + reducir a 40x40 costaba ~1.2 s solo.
            'supersample': 4,
        }

    def create_button_image(self, svg_file, size=(48, 48), category="", high_quality=True):
        """
        Crea imagen optimizada para botones desde archivo SVG

        Args:
            svg_file (str): Nombre del archivo SVG
            size (tuple): Tamaño objetivo (width, height)
            category (str): Categoría para organizar archivos SVG
            high_quality (bool): Si es True, usa resolución ultra-alta (lento). 
                                False para imágenes grandes (Splash).

        Returns:
            ImageTk.PhotoImage: Imagen optimizada para botón o None si falla
        """
        if not SVG_SUPPORT:
            # CairoSVG no disponible
            return None

        if not PIL_AVAILABLE:
            # PIL no disponible
            return None

        try:
            # Construir ruta completa al archivo SVG
            folder = category.lower() if category else ""
            if self.svg_base_path:
                full_path = self.svg_base_path / folder / svg_file
            else:
                # Usar ruta por defecto si no se especifica base_path
                base_dir = get_app_dir()
                full_path = base_dir / "svgs" / folder / svg_file

            if not full_path.exists():
                # SVG no encontrado: {full_path}
                return None

            # 4. SISTEMA DE CACHÉ
            # Calcular hash único basado en ruta y parámetros de configuración
            import hashlib

            # Asegurar directorio de caché
            cache_dir = full_path.parent / ".cache"
            cache_dir.mkdir(exist_ok=True)

            # Parámetros que afectan el renderizado
            params = (
                f"{full_path}_{size}_{self.button_config['scale_factor']}_"
                f"{self.button_config['background_color']}_{high_quality}_"
                f"{self.button_config['supersample']}"
            )
            params_hash = hashlib.md5(params.encode()).hexdigest()

            cache_file = cache_dir / f"{full_path.stem}_{params_hash}.png"

            # Verificar si el caché es válido (existe y es más nuevo que el SVG)
            use_cache = False
            if cache_file.exists():
                svg_mtime = full_path.stat().st_mtime
                cache_mtime = cache_file.stat().st_mtime
                if cache_mtime > svg_mtime:
                    use_cache = True

            if use_cache:
                try:
                    image = Image.open(cache_file)
                    # Forzar carga para detectar archivos corruptos
                    image.load()
                except Exception:
                    # Si falla la carga del caché, regenerar
                    use_cache = False

            if not use_cache:
                # Generación de PNG
                if high_quality:
                    # Sobremuestrea el tamaño final para que la reducción con
                    # LANCZOS conserve el detalle de los trazos finos.  Se
                    # cachea este tamaño intermedio (no 900x900) para que
                    # cargarlo en cada arranque sea barato.
                    over = self.button_config['supersample']
                    png_data = cairosvg.svg2png(
                        url=str(full_path),
                        output_width=max(1, size[0] * over),
                        output_height=max(1, size[1] * over),
                        background_color=self.button_config['background_color'],
                    )
                else:
                    # Renderizado estándar/rápido para imágenes grandes (Splash)
                    png_data = cairosvg.svg2png(
                        url=str(full_path),
                        output_width=size[0],
                        output_height=size[1],
                        background_color=self.button_config['background_color'],
                        scale=1.0
                    )

                with open(cache_file, "wb") as f:
                    f.write(png_data)

                # Convertir datos PNG a imagen PIL desde memoria
                image = Image.open(io.BytesIO(png_data))

            # Aplicar interpolación de alta calidad si es necesario
            if image.size != size:
                image = image.resize(size, self.button_config['interpolation'])

            # Convertir a formato compatible con tkinter
            return ImageTk.PhotoImage(image)

        except Exception as e:
            # Error cargando SVG para botón {svg_file}: {e}
            return None

# Función de conveniencia para crear instancia global
_global_renderer = None

def get_svg_renderer(svg_base_path=None):
    """
    Obtiene instancia global del renderizador SVG

    Args:
        svg_base_path (str): Ruta base para archivos SVG

    Returns:
        SvgRenderer: Instancia del renderizador
    """
    global _global_renderer
    if _global_renderer is None or svg_base_path:
        _global_renderer = SvgRenderer(svg_base_path)
    return _global_renderer

def create_button_image(svg_file, size=(48, 48), category="", svg_base_path=None):
    """
    Función de conveniencia para crear imagen de botón

    Args:
        svg_file (str): Nombre del archivo SVG
        size (tuple): Tamaño objetivo
        category (str): Categoría del SVG
        svg_base_path (str): Ruta base para archivos SVG

    Returns:
        ImageTk.PhotoImage: Imagen optimizada para botón
    """
    renderer = get_svg_renderer(svg_base_path)
    return renderer.create_button_image(svg_file, size, category)

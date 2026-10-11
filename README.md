# evaPr - Diagramador de Circuitos Eléctricos Industriales

![Versión 0.700.1.2](https://img.shields.io/badge/version-0.700.1.2-orange.svg)
![Licencia GPL v3](https://img.shields.io/badge/license-GPL%20v3-blue.svg)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Plataforma Linux/Windows](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-lightgrey.svg)

**evaPr** (eduCAd) es un diagramador de circuitos eléctricos industriales multiplataforma (Linux/Windows) con soporte de exportación a PDF de alta calidad (300 DPI) y nuevo soporte para exportación DXF. Diseñado para crear planos eléctricos Básicos con una interfaz intuitiva basada en Tkinter.

## 🎯 Características Principales

### Diseño y Edición
- ✏️ **Editor visual** con canvas A3 de alta resolución (3273x4725 px @ 300 DPI)
- 🗂️ **Soporte Multi-hoja**: Crea proyectos complejos divididos en múltiples planos
- 🔌 **Componentes eléctricos** predefinidos: motores, protecciones, conexiones, PLCs, variadores
- 🎨 **Sistema de formas geométricas** para anotaciones y diseño
- 📐 **Grid configurable** con snap opcional para alineación precisa
- 🔄 **Rotación de componentes** en incrementos de 90°

### Inteligencia y Automatización
- 🛣️ **Enrutamiento Manhattan** automático con evitación de obstáculos
- 🏷️ **Etiquetado automático** e inteligente de componentes con contadores persistentes
- 🔗 **Auto-conexión inteligente** entre componentes cercanos
- 🛡️ **Gestión de Apantallamiento**: Visualización de cables apantallados con etiquetas de tensión
- 🎬 **Modo de Simulación**: Validación visual del flujo eléctrico básico
- ⚡ **Numeración de cables por potencial**: Automática y configurable por polo

### Reportes y Documentación Automática
Genera documentación técnica instantánea basada en el diseño:
- 📊 **BOM (Lista de Materiales)**: Resumen consolidado de componentes, marcas y cantidades
- 🏗️ **Resumen de Gabinete**: Cálculo automático de dimensiones de tablero, riel DIN y canaletas
- 🔌 **Plano de Bornes**: Detalle de conexiones de regletas de terminales
- 🛡️ **Hoja de Seguridad**: Prescripciones de seguridad normalizadas
- 📐 **Plano Unifilar**: Diagrama unifilar de las interconexiones

### Interfaz y Usabilidad
- 🌓 **Modo oscuro/claro** con adaptación automática de colores
- 📏 **Herramientas de alineación**: vertical, horizontal, distribución
- 🔍 **Selección múltiple** y selección por área rectangular
- 🔙 **Sistema Deshacer/Rehacer (Undo/Redo)** robusto
- 📋 **Copiar/Pegar** de elementos y grupos de componentes
- ⌨️ **Atajos de teclado** para operaciones frecuentes
- 📊 **Barra de estado** con información contextual y coordenadas

### Exportación y Persistencia
- 📄 **Exportación a PDF vectorial** de alta calidad (300 DPI) con plantillas personalizables
- 📐 **Exportación DXF vectorial** para CAD (capas organizadas: CONDUCTORES, SIMBOLOS, GEOMETRIA, TEXTOS, PUNTOS)
- 💾 **Formato .ecad** mejorado para guardar proyectos completos con sus metadatos
- 📋 **Metadatos de proyecto** (empresa, revisores, fecha, versión)

## 📦 Requisitos del Sistema

**Python 3.10 o superior.** Las versiones actuales de Pillow, cairosvg y ezdxf
ya no soportan Python 3.9.

### Qué hay que instalar

| Componente | Qué es | Cómo se instala |
|---|---|---|
| `tkinter` | Interfaz gráfica | Paquete del sistema (abajo). En Windows viene con Python si marcaste "tcl/tk and IDLE" |
| `libcairo` | Render de SVG (lo usa `cairosvg`) | Paquete del sistema (abajo) |
| `cairosvg`, `pillow`, `reportlab`, `pypdf`, `ezdxf`, `svgpathtools` | Dependencias de Python | `pip install -r requirements.txt` |

> Las 6 dependencias de Python son obligatorias. `pypdf` y `svgpathtools` no son
> opcionales: sin ellas la exportación a PDF falla.

### 1. Librerías del sistema

Solo hacen falta **tkinter** y **libcairo**. Todo lo demás va por `pip`.

**Ubuntu / Debian**
```bash
sudo apt update
sudo apt install python3-tk libcairo2
```

**Fedora / RHEL**
```bash
sudo dnf install python3-tkinter cairo
```

**Arch Linux**
```bash
sudo pacman -S tk cairo
```

### 2. Dependencias de Python

El método más seguro es un **entorno virtual**, porque no toca tu Python de
sistema y funciona en cualquier distribución:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # Linux/macOS
.venv\Scripts\pip install -r requirements.txt # Windows
```

Si prefieres no usar entorno virtual, instala en tu usuario:

```bash
python3 -m pip install --user -r requirements.txt
```

> **Si `pip install` falla con `error: externally-managed-environment`**
> (Arch, Debian 12+, Fedora 39+): tu distribución protege el Python de sistema.
> Usa el entorno virtual de arriba, o añade `--break-system-packages`:
> ```bash
> python3 -m pip install --user --break-system-packages -r requirements.txt
> ```

## 🚀 Instalación

### Linux — un solo comando

```bash
git clone <url-del-repositorio>
cd eduCAd
./install.sh
```

Listo. `install.sh` se encarga de todo:

1. Comprueba que tengas **Python 3.10+**.
2. Instala las librerías del sistema que falten (**tkinter** y **libcairo**)
   usando el gestor de tu distribución (`apt`, `dnf`, `pacman`, `zypper`, `apk`).
   Si no tienes `sudo`, te dice exactamente qué comando ejecutar tú.
3. Crea un entorno virtual en `~/.local/share/evaPr/venv` e instala las
   dependencias de Python. **No toca tu Python de sistema ni el repositorio.**
4. Crea el comando `evaPr` en `~/.local/bin` y el acceso directo del menú.
5. Verifica que todas las librerías importan y te avisa si falta algo.

Después:

```bash
evaPr                      # o busca "eduCAd" en tu menú de aplicaciones
./install.sh --uninstall   # desinstalar
./install.sh --build       # recompilar el ejecutable (opcional)
```

> El entorno virtual vive **fuera** del repositorio
> (`~/.local/share/evaPr/venv`), por eso el repositorio no se ensucia.
> Si mueves o borras el repositorio, vuelve a ejecutar `./install.sh`.

### Windows — instalador (NSIS)

En Windows se instala y se reparte con el instalador de NSIS: es **un solo
archivo** (`dist_installer\evaPr-Setup-<versión>.exe`) que ya incluye todo
(ejecutable + `svgs/` + `config/` + las DLLs de Cairo) y **no necesita Python
ni GTK/Cairo** en el equipo destino.

Para generarlo (una vez, en Windows):

1. Instalar [NSIS 3.x](https://nsis.sourceforge.io/Main.html) para que
   `makensis` quede en el PATH.
2. Doble clic en `build_installer.bat`. Compila `evaPr.exe` con `evaPr_win.spec`
   en `dist/`, empaqueta `svgs/` y `config/` **tal cual**, incorpora las DLLs de
   Cairo (ver más abajo) y genera `dist_installer/evaPr-Setup-<versión>.exe`.

Reparte ese `.exe`: quien lo ejecute instala la app con doble clic. NSIS es
*cross-compiler* (el instalador se puede generar en Linux), pero `evaPr.exe`
**no**: PyInstaller solo compila para el sistema operativo en el que se ejecuta.

**Alternativa — ejecutable en Windows, instalador en Linux**
1. En Windows, solo el paso de PyInstaller:
```bat
python -m PyInstaller evaPr_win.spec --noconfirm --distpath dist --workpath build\evaPr_win
```
2. Copiar esa carpeta `dist\` al repositorio en Linux.
3. Aquí, `./build_installer_linux.sh` (necesita `sudo pacman -S nsis`).

Ambos scripts leen la versión de `APP_VERSION` en `config/settings.py`, así que
el nombre del instalador se actualiza solo. `dist/` y `dist_installer/`
quedan ignorados por git.

Detalles del instalador generado:

- Se instala por usuario en `%LOCALAPPDATA%\Programs\evaPr` (no requiere
  permisos de administrador) e incluye accesos directos en Escritorio y Menú de
  Inicio, más el desinstalador en "Agregar o quitar programas".
- Los accesos directos llevan el AppUserModelID `eduCAd.evaPr` (el mismo que
  fija la app en tiempo de ejecución), para poder **anclar a la barra de tareas**.
- `svgs/` y `config/` se entregan sin modificar: la aplicación los lee desde la
  carpeta del propio `.exe` (`utils.get_app_dir()`), por eso el instalador
  **no** los copia a `Documentos`.
- Desinstalar borra el programa pero conserva los datos del usuario
  (`%APPDATA%\evaPr\config.json` y los proyectos).

> **Nota sobre Cairo:** `cairosvg` necesita `libcairo-2.dll` en tiempo de
> ejecución y PyInstaller no la empaqueta (cairocffi la carga de forma
> dinámica). `build_installer.bat` ya lo resuelve solo: ejecuta
> `bundle_cairo_dlls.py`, que localiza `libcairo-2.dll` en GTK3-Runtime, MSYS2
> o el PATH, calcula toda su cadena de dependencias y las copia a `dist/`. El
> `.nsi` incluye automáticamente cualquier `.dll` de esa carpeta y el runtime
> hook `pyi_dll_path.py` la añade al orden de búsqueda de DLL. Resultado: el
> instalador funciona en equipos **sin GTK ni Cairo** instalados.
>
> Si la máquina que compila no tiene `libcairo-2.dll`, instala
> [GTK3-Runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Installer),
> indícala con la variable `CAIRO_DLL_DIR` o con
> `python bundle_cairo_dlls.py --cairo-dir <ruta>`.

### Si quieres hacerlo a mano

```bash
sudo apt install python3-tk libcairo2       # librerías del sistema
python3 -m pip install -r requirements.txt   # dependencias de Python
python3 evaPr.py                            # ejecutar
```


## 📖 Uso Básico

### Inicio Rápido

1. **Agregar componentes**: Selecciona un componente del panel lateral y haz clic en el canvas
2. **Conectar componentes**: Haz clic en un punto de conexión (círculo rojo), luego en otro punto
3. **Mover componentes**: Arrastra los componentes con el mouse
4. **Rotar**: Selecciona un componente y usa `Ctrl+R` o el menú contextual
5. **Guardar**: `Archivo → Guardar` (formato .ecad)
6. **Exportar PDF**: `Archivo → Exportar PDF`
7. **Exportar DXF**: `Archivo → Exportar DXF`

### Atajos de Teclado

| Atajo | Acción |
|-------|--------|
| `Ctrl+Z` | Deshacer (Undo) |
| `Ctrl+Y` | Rehacer (Redo) |
| `Ctrl+C` | Copiar selección |
| `Ctrl+V` | Pegar |
| `Ctrl+S` | Guardar proyecto |
| `Ctrl+O` | Abrir proyecto |
| `Ctrl+N` | Nuevo proyecto |
| `Ctrl+R` | Rotar componente |
| `Ctrl+H` | Centrar verticalmente |
| `Ctrl+J` | Distribuir verticalmente |
| `Ctrl+K` | Distribuir horizontalmente |
| `Ctrl+I` | Insertar punto en conexión |
| `Supr` | Eliminar selección |
| Rueda Mouse| Zoom In/Out |
| Click Central| Pan (Mover vista) |
| Click Izq/Der| Rotar Formas Geométricas (Gabinete 2D) |

### Modos de Conexión

#### Modo Automático (por defecto)
- Haz clic en un punto de conexión inicial
- Haz clic en un punto de conexión final
- El sistema crea automáticamente una ruta Manhattan optimizada

#### Modo Manual
- Activa el modo manual desde el menú o panel
- Haz clic en puntos intermedios para crear ángulos ortogonales
- Finaliza haciendo clic en el punto de destino

## 📁 Estructura del Proyecto

```
eduCAd/
├ evaPr.py                 # Aplicación principal
├ logo-evaPr.png          # Icono de la aplicación
├ svgs/                   # Componentes SVG y recursos visuales
├ config/                 # Configuración del sistema
│   └── settings.py         # Constantes y gestión de config.json
├ core/                   # Lógica de negocio central
│   ├── component_manager.py      # Gestión de ciclo de vida de componentes
│   ├── reports.py                # Motores de generación de reportes
│   ├── undo_manager.py           # Gestor de estados de deshacer/rehacer
│   ├── unified_line_system.py    # Sistema de enrutamiento Manhattan
│   └── virtual_canvas.py         # Abstracción del área de dibujo
├ models/                 # Modelos de datos
│   ├── project_data.py     # Estructura de Proyecto y Hojas (Sheets)
│   ├── component.py        # Clases base de componentes
│   ├── connection.py       # Modelo de interconexión eléctrica
│   ├── shape.py            # Formas geométricas (Rect, Cir, etc)
│   └── shielding.py        # Lógica de cables apantallados
├ handlers/               # Controladores de eventos
│   ├── event_handlers.py  # Lógica de interacción del usuario
│   └── event_utils.py     # Utilidades para validación de eventos
├ simulation/             # Motor de simulación
│   └── simulation_controller.py  # Lógica de propagación eléctrica
├ ui/                     # Componentes de interfaz
│   ├── drawing_panel.py   # Panel lateral de herramientas
│   └── splash.py          # Pantalla de carga inicial
└── utils/                # Utilidades transversales
    ├── alignment_utils.py      # Algoritmos de alineación
    ├── coordinates.py          # Transformaciones mundo-pantalla
    └── svg_renderer.py         # Renderizado SVG a TK/PNG
```

## 🎨 Personalización

### Agregar Nuevos Componentes

1. **Crear SVG**: Diseña tu componente en formato SVG
2. **Puntos de conexión**: Usa círculos rojos (`#ff0000`) para marcar puntos de conexión
3. **Guardar en svgs/**: Coloca el archivo en la carpeta `svgs/`
4. **Configurar**: Edita `~/.config/evaPr/config.json` para agregar el componente:

```json
{
  "components": {
    "MiCategoria": [
      {
        "svg": "mi-componente.svg",
        "name": "Mi Componente",
        "size": [64, 64]
      }
    ]
  }
}
```

### Configuración del Canvas

El archivo de configuración se encuentra en: `~/.config/evaPr/config.json`

```json
{
  "canvas_color": "#fff9e6",     // Color de fondo
  "grid_size": 20,               // Tamaño del grid
  "grid_visible": true,          // Mostrar grid
  "snap_to_grid_enabled": false, // Snap automático
  "window_width": 1024,          // Ancho de ventana
  "window_height": 768           // Alto de ventana
}
```

### Sistema de Etiquetas

evaPr incluye un sistema automático de etiquetado de componentes. Los componentes
pueden recibir etiquetas automáticas basadas en su tipo (motores, protecciones,
PLCs, variadores, etc.). La etiqueta incluye información configurable como marca,
voltaje, potencia, amperios y descripción.

Para configurar el etiquetado automático, edita `~/.config/evaPr/config.json` y
activa las opciones de numeración de cables por potencial.

## 🔧 Características Técnicas

### Arquitectura
- **Patrón MVC**: Separación clara entre modelos, vistas y controladores
- **Sistema modular**: Componentes independientes y reutilizables
- **Event-driven**: Manejo de eventos centralizado y eficiente

### Optimizaciones
- **Throttling de eventos**: Control de frecuencia de actualización
- **Cache de imágenes**: Renderizado optimizado de componentes
- **Grid tileable**: Renderizado eficiente del grid con PIL
- **Detección inteligente**: Algoritmos optimizados para detección de colisiones

### Formatos de Archivo

#### .ecad (Formato de Proyecto)
```json
{
  "version": "0.700",
  "components": [...],
  "connections": [...],
  "shapes": [...],
  "metadata": {
    "created": "2025-11-23T04:08:25",
    "modified": "2025-11-23T04:08:25"
  }
}
```

#### DXF (Exportación Vectorial)
El exportador DXF genera archivos compatibles con AutoCAD y otros lectores DXF,
con las siguientes capas organizadas:
- **CONDUCTORES**: Las conexiones eléctricas
- **SIMBOLOS**: Los componentes y símbolos del circuito
- **GEOMETRIA**: Formas geométricas y anotaciones
- **TEXTOS**: Etiquetas y texto descriptivo
- **PUNTOS**: Puntos de conexión y nodos

## 🐛 Solución de Problemas

### SVG no se muestra
- Verifica que `cairosvg` y `pillow` estén instalados
- Asegúrate de que los archivos SVG estén en la carpeta `svgs/`
- Revisa que los SVG sean válidos (prueba abrirlos en un navegador)

### PDF no se exporta
- Verifica que `reportlab` esté instalado: `pip install reportlab`
- Comprueba los permisos de escritura en el directorio de destino

### DXF no se exporta
- Verifica que `ezdxf` esté instalado: `pip install ezdxf`
- Comprueba que los componentes tengan puntos de conexión válidos

### Componentes no se conectan
- Verifica que los puntos de conexión (círculos rojos `#ff0000`) estén presentes en el SVG
- Asegúrate de hacer clic directamente sobre los puntos de conexión

### Rendimiento lento
- Reduce el número de componentes en el canvas
- Desactiva el grid si no es necesario
- Cierra otros programas que consuman recursos

## ⚠️ Aviso de Versión

**evaPr v0.700 es una versión madura y lista para uso público.**

Agradezco enormemente los aportes y pull requests de la comunidad, pero **no puedo brindar soporte técnico ni garantía**. El proyecto se comparte para quien desee colaborar libremente.

- Se pueden reportar issues en el repositorio, pero no se garantiza respuesta ni resolución.
- Se aceptan pull requests y contribuciones de la comunidad.
- El software se distribuye **"tal cual" (as-is)** sin garantías de ningún tipo.

## 🛡️ Cláusula de Exención de Responsabilidad Legal y Técnica

### AVISO IMPORTANTE Y EXCLUSIÓN DE RESPONSABILIDAD (DISCLAIMER)

1. **Carácter únicamente informativo:** Este código, software, algoritmo o
   herramienta (en adelante, "la Herramienta") se proporciona exclusivamente
   con fines informativos, educativos y de apoyo técnico conceptual. Las
   conexiones, diagramas, cálculos de carga, dimensionamientos de protecciones
   y cualquier otro resultado generado por la Herramienta son simulaciones
   automatizadas que pueden contener errores, omisiones o imprecisiones debidas
   a la complejidad de las variables eléctricas involucradas.

2. **No sustitución de profesional calificado:** El uso de la Herramienta NO
   sustituye en ningún caso el criterio, supervisión, cálculo, revisión
   detallada ni la firma de un Ingeniero Eléctrico o Profesional Técnico
   debidamente matriculado, certificado y habilitado por las autoridades
   locales de ingeniería y seguridad eléctrica.

3. **Exclusión total de responsabilidad por daños:** Bajo ninguna circunstancia
   los desarrolladores, autores, colaboradores, la plataforma evaPR, ni los
   propietarios de los derechos de autor de la Herramienta serán responsables
   de ninguna reclamación, demanda, pérdida, gasto o daño de cualquier
   naturaleza que surja de, o esté relacionado con, el uso, la imposibilidad de
   uso, el mal funcionamiento, o la confianza depositada en los resultados de
   la Herramienta.

   Esta exclusión es absoluta y aplicable sin limitación alguna a:

   - **Daños materiales:** daños leves, graves o totales a la propiedad,
     equipos, infraestructura, instalaciones eléctricas, incendios,
     cortocircuitos o fallas de continuidad del servicio.
   - **Daños personales y fatales:** lesiones físicas de cualquier gravedad,
     incapacidad temporal o permanente, y la muerte (daños fatales) de
     operarios, usuarios o terceros, causadas por descargas eléctricas, arcos
     eléctricos, explosiones o cualquier falla técnica derivada de una mala
     conexión o diseño.
   - **Daños consecuentes o lucro cesante:** pérdidas económicas, multas
     regulatorias o interrupción de operaciones comerciales.

4. **Asunción de riesgo:** El usuario final asume de forma exclusiva,
   consciente e irrevocable el 100% del riesgo técnico y legal asociado con la
   implementación práctica de cualquier dato provisto por la Herramienta. El
   usuario es responsable de verificar de forma independiente que los diseños
   cumplan estrictamente con los códigos eléctricos vigentes (ej. NEC, NFPA 70,
   IEC, o normativas nacionales locales) aplicables a su jurisdicción.

**AL UTILIZAR ESTA HERRAMIENTA, USTED ACEPTA Y CONSIENTE QUEDAR VINCULADO POR
LOS TÉRMINOS DE ESTA EXCLUSIÓN DE RESPONSABILIDAD.**

### Buenas prácticas aplicadas en el software

- **Pantalla de aceptación obligatoria:** al abrir la aplicación por primera
  vez (y cada vez que cambia la versión del aviso) aparece un diálogo con el
  texto completo; solo se puede continuar con el botón *"Acepto y continúo"*.
  La aceptación queda registrada en la configuración del usuario.
- **Nota legal en la Hoja de Seguridad y en la ventana:** la línea *"Resultado
  referencial. Requiere validación obligatoria de un profesional eléctrico
  matriculado. Exclusión de responsabilidad aplicable."* ocupa el recuadro de
  la Hoja de Seguridad y permanece visible en la barra de estado.
- **Texto completo siempre disponible:** menú **Ayuda → Aviso Legal**.

## 📄 Licencia

Este proyecto está licenciado bajo la **GNU General Public License v3.0** (GPL v3).

Ver: https://www.gnu.org/licenses/gpl-3.0.html

```
evaPr - Diagramador de Circuitos Eléctricos Industriales
Copyright (C) 2025 etovive

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
```

## 👥 Autor

**etovive**

## 🙏 Agradecimientos

- Comunidad de Python y Tkinter
- Proyecto CairoSVG por el renderizado SVG
- ReportLab por la generación de PDF
- ezdxf por la generación de DXF
- Todos los contribuidores y usuarios

## 📞 Soporte

⚠️ **NOTA IMPORTANTE: No se da soporte técnico para esta aplicación.**

Esta herramienta ha sido desarrollada como un proyecto personal y se proporciona "tal cual" (as-is), sin garantías de ningún tipo. Los usuarios son libres de utilizar, modificar y estudiar el código fuente según los términos de la licencia GPL v3, pero **no se responderán peticiones de asistencia técnica, ayuda con instalaciones, ni resolución de problemas**.

Si encuentras algún bug, puedes abrir un issue en el repositorio, pero ten en cuenta que no se garantiza una resolución o respuesta.

## ☕ Invítame un Café

Si esta herramienta te ha sido útil, y quieres apoyar de forma voluntaria, puedes invitarme un café:

<a href="https://paypal.me/etovivePr" target="_blank"><img src="assets/pp_cc_mark_37x23.jpg" alt="PayPal" style="height: 40px !important; margin-right: 10px; vertical-align: middle;"> <span style="vertical-align: middle;">**Invítame un Café en PayPal**</span></a>

## ₿ Donar en Bitcoin

También podés donar directamente a mi wallet de **Electrum**, sin intermediarios y con comisión mínima. Acepta cualquier wallet Bitcoin (Electrum, Bitcoin Core, Exodus, Sparrow, Ledger, Trezor…).

**Dirección (segwit nativo `bc1`):**

```
bc1q8w7h0qldqfz4y0vtyjd87r55lxk2c7227khm5v
```

<p align="center">
  <img src="assets/bitcoin-donation-qr.svg" alt="Código QR para donar Bitcoin a bc1q8w7h0qldqfz4y0vtyjd87r55lxk2c7227khm5v" width="230">
  <br>
  <em>Escaneá el código QR desde tu wallet Bitcoin.</em>
</p>

- **Formato:** P2WPKH (segwit nativo, bech32) — fees más bajos
- **URI BIP21** (abre la solicitud de pago con la nota ya cargada — pegala en el campo *Enviar* de Electrum):

```
bitcoin:bc1q8w7h0qldqfz4y0vtyjd87r55lxk2c7227khm5v?message=Donaciones%20evaPr
```

> ⚠️ **Verificá siempre la dirección antes de enviar.** Copiala desde esta página (o desde *evaPr → Ayuda → Acerca de*) y comparala carácter por carácter con la que muestre tu wallet. Nunca envíes fondos a una dirección publicada en un sitio que no sea el oficial.

Dentro de evaPr podés copiar la dirección o la URI BIP21 desde **Ayuda → Acerca de** → sección **☕ ¿Te sirvió este software? ¡Invítame un café!**.

---

**¡Gracias por usar evaPr!** 🔌⚡
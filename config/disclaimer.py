"""Aviso legal de exención de responsabilidad de evaPr.

Única fuente del texto legal: lo usan el diálogo de aceptación al inicio,
el menú Ayuda > Aviso Legal, la barra de estado y el pie de cada PDF.
Si se modifica DISCLAIMER_VERSION, todos los usuarios vuelven a ver el
diálogo de aceptación en el próximo arranque.
"""
from datetime import datetime

# Cambiar este valor fuerza una nueva aceptación del aviso
DISCLAIMER_VERSION = "1"

DISCLAIMER_TITLE = "Aviso Legal — Exención de Responsabilidad"

DISCLAIMER_TEXT = """\
CLÁUSULA DE EXENCIÓN DE RESPONSABILIDAD LEGAL Y TÉCNICA
AVISO IMPORTANTE Y EXCLUSIÓN DE RESPONSABILIDAD (DISCLAIMER)

1. CARÁCTER ÚNICAMENTE INFORMATIVO: Este código, software, algoritmo o
herramienta (en adelante, "la Herramienta") se proporciona exclusivamente con
fines informativos, educativos y de apoyo técnico conceptual. Las conexiones,
diagramas, cálculos de carga, dimensionamientos de protecciones y cualquier
otro resultado generado por la Herramienta son simulaciones automatizadas que
pueden contener errores, omisiones o imprecisiones debidas a la complejidad de
las variables eléctricas involucradas.

2. NO SUSTITUCIÓN DE PROFESIONAL CALIFICADO: El uso de la Herramienta NO
sustituye en ningún caso el criterio, supervisión, cálculo, revisión detallada
ni la firma de un Ingeniero Eléctrico o Profesional Técnico debidamente
matriculado, certificado y habilitado por las autoridades locales de
ingeniería y seguridad eléctrica.

3. EXCLUSIÓN TOTAL DE RESPONSABILIDAD POR DAÑOS: Bajo ninguna circunstancia
los desarrolladores, autores, colaboradores, la plataforma evaPR, ni los
propietarios de los derechos de autor de la Herramienta serán responsables de
ninguna reclamación, demanda, pérdida, gasto o daño de cualquier naturaleza
que surja de, o esté relacionado con, el uso, la imposibilidad de uso, el mal
funcionamiento, o la confianza depositada en los resultados de la Herramienta.

Esta exclusión es absoluta y aplicable sin limitación alguna a:

  • Daños Materiales: Daños leves, graves o totales a la propiedad, equipos,
    infraestructura, instalaciones eléctricas, incendios, cortocircuitos o
    fallas de continuidad del servicio.

  • Daños Personales y Fatales: Lesiones físicas de cualquier gravedad,
    incapacidad temporal o permanente, y la muerte (daños fatales) de
    operarios, usuarios o terceros, causadas por descargas eléctricas, arcos
    eléctricos, explosiones o cualquier falla técnica derivada de una mala
    conexión o diseño.

  • Daños Consecuentes o Lucro Cesante: Pérdidas económicas, multas
    regulatorias o interrupción de operaciones comerciales.

4. ASUNCIÓN DE RIESGO: El usuario final asume de forma exclusiva, consciente e
irrevocable el 100% del riesgo técnico y legal asociado con la implementación
práctica de cualquier dato provisto por la Herramienta. El usuario es
responsable de verificar de forma independiente que los diseños cumplan
estrictamente con los códigos eléctricos vigentes (ej. NEC, NFPA 70, IEC, o
normativas nacionales locales) aplicables a su jurisdicción.

AL UTILIZAR ESTA HERRAMIENTA, USTED ACEPTA Y CONSIENTE QUEDAR VINCULADO POR
LOS TÉRMINOS DE ESTA EXCLUSIÓN DE RESPONSABILIDAD.
"""

DISCLAIMER_ACCEPT_LABEL = (
    "He leído, entiendo y acepto los términos y la exclusión de responsabilidad"
)

DISCLAIMER_REJECT_LABEL = "Salir"

# Nota fija que acompaña a la Hoja de Seguridad y a la ventana principal
DISCLAIMER_FOOTER = (
    "Resultado referencial. Requiere validación obligatoria de un profesional "
    "eléctrico matriculado. Exclusión de responsabilidad aplicable."
)


def is_accepted(config):
    """True si el usuario ya aceptó la versión vigente del aviso."""
    try:
        return str(config.get("disclaimer_accepted_version", "")) == DISCLAIMER_VERSION
    except AttributeError:
        return False


def mark_accepted(config):
    """Marca el aviso como aceptado en `config` (no persiste; ver save_config)."""
    config["disclaimer_accepted_version"] = DISCLAIMER_VERSION
    config["disclaimer_accepted_date"] = datetime.now().isoformat(timespec="seconds")
    return config

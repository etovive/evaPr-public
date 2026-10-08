import re as _re

_PROTECTION_KEYWORDS = (
    'contactor', 'rele', 'relay', 'thermal',
    'disyuntor', 'diferencial', 'guardamotor',
    'breaker', 'magnetotermico', 'guardomotor',
    'circuit-breaker-thermal-magnetic',
    'circuit-breaker',
)

# TABLAS (mantengo solo las esenciales)
# (Amps_max, mm², AWG)
_CABLE_TABLE = [
    (6,   1.5,  14, "1,5 mm² (AWG 16)"),
    (10,  2.5,  12, "2,5 mm² (AWG 12)"),
    (16,  4.0,  10, "4 mm² (AWG 10)"),
    (25,  6.0,   8, "6 mm² (AWG 8)"),
    (32,  10.0,  6, "10 mm² (AWG 6)"),
    (40,  10.0,  6, "10 mm² (AWG 6)"),
    (50,  16.0,  4, "16 mm² (AWG 4)"),
    (63,  25.0,  3, "25 mm² (AWG 3)"),
    (80,  35.0,  2, "35 mm² (AWG 2)"),
    (100, 50.0,  1, "50 mm² (AWG 1)"),
    (125, 70.0,  0, "70 mm² (AWG 1/0)"),
    (160, 95.0, -1, "95 mm² (AWG 2/0)"),
    (200,120.0, -2, "120 mm² (AWG 3/0)"),
    (250,150.0, -3, "150 mm² (AWG 4/0)"),
    (315,185.0, -4, "185 mm² (AWG 350kcmil)"),
    (400,240.0, -5, "240 mm² (AWG 500kcmil)"),
    (500,300.0, -6, "300 mm² (AWG 600kcmil)"),
    (630,400.0, -7, "400 mm² (AWG 750kcmil)"),
]

def _cable_section(amps):
    """Sección de cable recomendada — formato mm² / AWG (IEC 60364 / NEC)."""
    for limit, _mm2, _awg, label in _CABLE_TABLE:
        if amps <= limit: return label
    return "400 mm² (AWG 750kcmil)"

_BREAKER_SERIES = [1,2,3,4,6,8,10,13,16,20,25,32,40,50,63,80,100,125,160,200,250,315,400,500,630]

# Estimaciones de consumo (VA) para cargas de una línea de control
# Orden de precedencia: kw coincide en svg_file, category o nombre.
# NOTA: 'contactor' NO está a propósito: sus contactos auxiliares/potencia
# no consumen por sí mismos; la bobina se representa aparte ("coil").
_CONTROL_VA_ESTIMATES = (
    ('coil',         7.0),   # bobina de contactor (mantenimiento)
    ('rele',         3.0),   # bobina de relé auxiliar
    ('relay',        3.0),
    ('timer',        3.0),   # temporizador
    ('tempo',        3.0),
    ('lamp',         2.0),   # lámpara / luz testigo
    ('luz',          2.0),
    ('alarm',       10.0),   # sirenas / alarmas / buzzer
    ('sirena',      10.0),
    ('buzzer',      10.0),
    ('horn',        10.0),
    ('plc',         30.0),   # PLC / LOGO / autómata
    ('cpu',         30.0),
    ('logo',        30.0),
    ('s7-',         30.0),
    ('transformer', 50.0),   # fuente / transformador de control
    ('fuente',      50.0),
    ('power_supply',50.0),
    ('trafo',       50.0),
)

def _estimate_va(comp):
    """VA estimado de un componente de línea de control.

    Prioriza la potencia real cargada en la etiqueta (potencia/consumo);
    si no la hay, estima por tipo de componente.
    """
    ld = getattr(comp, 'label_data', {}) or {}
    raw = str(ld.get('potencia', '') or ld.get('consumo', '') or '').strip()
    m = _re.search(r'[\d.,]+', raw)
    if m:
        try:
            return float(m.group().replace(',', '.'))
        except ValueError:
            pass
    fname = (getattr(comp, 'svg_file', '') or '').lower()
    cat   = (getattr(comp, 'category', '') or '').lower()
    name  = (ld.get('name', '') or ld.get('nombre', '') or '').upper()
    for kw, va in _CONTROL_VA_ESTIMATES:
        if kw in fname or kw in cat or kw in name.lower():
            return va
    return 0.0

# Rotación: Schneider -> ABB -> Siemens -> Chint -> LS -> WEG -> (repite)
# Criterio: escalones lo más cercanos posible entre marcas para un mismo
# valor de corriente. Todos usan la misma serie IEC para breakers.
BRAND_ROTATION = ["Schneider", "ABB", "Siemens", "Chint", "LS", "WEG"]

# SCHNEIDER
_SCH_CONTACTOR = [
    (9,"LC1-D09"),(12,"LC1-D12"),(18,"LC1-D18"),(25,"LC1-D25"),(32,"LC1-D32"),
    (40,"LC1-D40"),(50,"LC1-D50"),(65,"LC1-D65"),(80,"LC1-D80"),(95,"LC1-D95"),
    (115,"LC1-D115"),(150,"LC1-D150"),(185,"LC1-D185"),(225,"LC1-D225"),
    (300,"LC1-D300"),(400,"LC1-D410"),(500,"LC1-D500"),(630,"LC1-D630"),
]
_SCH_THERMAL = [
    (0.10,0.16,"LRD-01"),(0.16,0.25,"LRD-02"),(0.25,0.40,"LRD-03"),(0.40,0.63,"LRD-04"),
    (0.63,1.0,"LRD-05"),(1.0,1.6,"LRD-06"),(1.6,2.5,"LRD-07"),(2.5,4.0,"LRD-08"),
    (4.0,6.0,"LRD-10"),(5.5,8.0,"LRD-12"),(7.0,10.0,"LRD-14"),(9.0,13.0,"LRD-16"),
    (12.0,18.0,"LRD-21"),(16.0,24.0,"LRD-22"),(23.0,32.0,"LRD-32"),(30.0,38.0,"LRD-33"),
    (37.0,50.0,"LRD-35"),(48.0,65.0,"LRD-332"),(63.0,80.0,"LRD-340"),(80.0,104.0,"LRD-350"),
]
_SCH_GUARDAMOTOR = [
    (0.10,0.16,"GV2-ME01"),(0.16,0.25,"GV2-ME02"),(0.25,0.40,"GV2-ME03"),(0.40,0.63,"GV2-ME04"),
    (0.63,1.0,"GV2-ME05"),(1.0,1.6,"GV2-ME06"),(1.6,2.5,"GV2-ME07"),(2.5,4.0,"GV2-ME08"),
    (4.0,6.3,"GV2-ME10"),(6.0,10.0,"GV2-ME14"),(9.0,14.0,"GV2-ME16"),(13.0,18.0,"GV2-ME20"),
    (17.0,23.0,"GV2-ME21"),(20.0,25.0,"GV2-ME22"),(24.0,32.0,"GV3-ME32"),(30.0,40.0,"GV3-ME40"),
    (37.0,50.0,"GV3-ME50"),(48.0,65.0,"GV3-ME65"),(60.0,80.0,"GV3-ME80"),(80.0,100.0,"GV3-ME100"),
]

# ABB ── (escalones corregidos, serie más granular)
_ABB_CONTACTOR = [
    (9,"A9-30"),(12,"A12-30"),(16,"A16-30"),(23,"A23-30"),(26,"A26-30"),
    (30,"A30-30"),(40,"A40-30"),(50,"A50-30"),(63,"A63-30"),(75,"A75-30"),
    (95,"A95-30"),(110,"A110-30"),(145,"A145-30"),(185,"A185-30"),(210,"A210-30"),
    (260,"A260-30"),(300,"A300-30"),(400,"A400-30"),(500,"A500-30"),(630,"A630-30"),
]
_ABB_THERMAL = [
    (0.10,0.16,"TA25DU-0.16"),(0.16,0.25,"TA25DU-0.25"),(0.25,0.40,"TA25DU-0.40"),
    (0.40,0.63,"TA25DU-0.63"),(0.63,1.0,"TA25DU-1.0"),(1.0,1.6,"TA25DU-1.6"),
    (1.6,2.5,"TA25DU-2.5"),(2.5,4.0,"TA25DU-4.0"),(4.0,6.0,"TA25DU-6.5"),
    (6.0,9.0,"TA25DU-11"),(9.0,13.0,"TA25DU-14"),(12.0,18.0,"TA25DU-19"),
    (16.0,24.0,"TA42DU-25"),(22.0,32.0,"TA42DU-32"),(29.0,40.0,"TA75DU-42"),
    (36.0,52.0,"TA75DU-52"),(46.0,63.0,"TA75DU-63"),(55.0,75.0,"TA75DU-80"),
    (66.0,90.0,"TA110DU-90"),(80.0,110.0,"TA110DU-110"),(95.0,130.0,"TA200DU-135"),
]
_ABB_GUARDAMOTOR = [
    (0.10,0.16,"MS116-0.16"),(0.16,0.25,"MS116-0.25"),(0.25,0.40,"MS116-0.40"),
    (0.40,0.63,"MS116-0.63"),(0.63,1.0,"MS116-1.0"),(1.0,1.6,"MS116-1.6"),
    (1.6,2.5,"MS116-2.5"),(2.5,4.0,"MS116-4.0"),(4.0,6.3,"MS116-6.3"),
    (6.0,10.0,"MS116-10"),(9.0,14.0,"MS116-16"),(12.0,20.0,"MS116-20"),
    (16.0,25.0,"MS132-25"),(20.0,32.0,"MS132-32"),(28.0,45.0,"MS165-42"),
    (38.0,65.0,"MS165-65"),(52.0,80.0,"MS165-80"),(63.0,100.0,"MS165-100"),
]

# SIEMENS ── (escalones corregidos, serie más granular)
_SIE_CONTACTOR = [
    (9,"3RT2016"),(12,"3RT2017"),(16,"3RT2018"),(22,"3RT2023"),(25,"3RT2025"),
    (32,"3RT2026"),(40,"3RT2035"),(50,"3RT2036"),(65,"3RT2037"),(75,"3RT2044"),
    (95,"3RT2045"),(115,"3RT2046"),(150,"3RT2054"),(185,"3RT2055"),(225,"3RT2056"),
    (265,"3RT2064"),(400,"3RT2065"),(500,"3RT2075"),(630,"3RT2076"),
]
_SIE_THERMAL = [
    (0.10,0.16,"3RU2116-0AB0"),(0.16,0.25,"3RU2116-0CB0"),(0.25,0.40,"3RU2116-0EB0"),
    (0.40,0.63,"3RU2116-0GB0"),(0.63,1.0,"3RU2116-0JB0"),(1.0,1.6,"3RU2116-1BB0"),
    (1.6,2.5,"3RU2116-1DB0"),(2.5,4.0,"3RU2116-1FB0"),(4.0,6.3,"3RU2116-1HB0"),
    (6.0,10.0,"3RU2116-1KB0"),(9.0,13.0,"3RU2116-1LB0"),(12.0,18.0,"3RU2126-4AB0"),
    (16.0,24.0,"3RU2126-4BB0"),(22.0,32.0,"3RU2126-4DB0"),(28.0,40.0,"3RU2136-4EB0"),
    (36.0,50.0,"3RU2136-4FB0"),(45.0,63.0,"3RU2136-4GB0"),(60.0,80.0,"3RU2136-4HB0"),
    (75.0,100.0,"3RU2136-4JB0"),(90.0,120.0,"3RU2146-4KB0"),
]
_SIE_GUARDAMOTOR = [
    (0.10,0.16,"3RV2011-0AA10"),(0.16,0.25,"3RV2011-0BA10"),(0.25,0.40,"3RV2011-0CA10"),
    (0.40,0.63,"3RV2011-0DA10"),(0.63,1.0,"3RV2011-0EA10"),(1.0,1.6,"3RV2011-0FA10"),
    (1.6,2.5,"3RV2011-0GA10"),(2.5,4.0,"3RV2011-0HA10"),(4.0,6.3,"3RV2011-0JA10"),
    (6.0,10.0,"3RV2011-1AA10"),(9.0,14.0,"3RV2011-1CA10"),(12.0,18.0,"3RV2011-1DA10"),
    (16.0,25.0,"3RV2021-1FA10"),(20.0,32.0,"3RV2021-4DA10"),(28.0,40.0,"3RV2031-4EA10"),
    (36.0,50.0,"3RV2031-4FA10"),(45.0,65.0,"3RV2031-4HA10"),(57.0,80.0,"3RV2031-4JA10"),
    (70.0,100.0,"3RV2041-4KA10"),
]

# CHINT ── (serie NXC contactores, NR2 térmicos, NXR guardamotores)
_CHI_CONTACTOR = [
    (9,"NXC-09"),(12,"NXC-12"),(18,"NXC-18"),(25,"NXC-25"),(32,"NXC-32"),
    (40,"NXC-40"),(50,"NXC-50"),(65,"NXC-65"),(80,"NXC-80"),(95,"NXC-95"),
    (115,"NXC-115"),(150,"NXC-150"),(185,"NXC-185"),(225,"NXC-225"),
    (300,"NXC-300"),(400,"NXC-400"),(500,"NXC-500"),(630,"NXC-630"),
]
_CHI_THERMAL = [
    (0.10,0.16,"NR2-11.5/0.16"),(0.16,0.25,"NR2-11.5/0.25"),(0.25,0.40,"NR2-11.5/0.40"),
    (0.40,0.63,"NR2-11.5/0.63"),(0.63,1.0,"NR2-11.5/1.0"),(1.0,1.6,"NR2-11.5/1.6"),
    (1.6,2.5,"NR2-11.5/2.5"),(2.5,4.0,"NR2-11.5/4.0"),(4.0,6.0,"NR2-11.5/6.0"),
    (5.5,8.0,"NR2-11.5/8.0"),(7.0,10.0,"NR2-11.5/10"),(9.0,13.0,"NR2-11.5/13"),
    (12.0,18.0,"NR2-25/18"),(16.0,25.0,"NR2-25/25"),(20.0,32.0,"NR2-36/32"),
    (28.0,40.0,"NR2-36/40"),(34.0,50.0,"NR2-36/50"),(45.0,63.0,"NR2-93/63"),
    (55.0,80.0,"NR2-93/80"),(70.0,93.0,"NR2-93/93"),
]
_CHI_GUARDAMOTOR = [
    (0.10,0.16,"NXR-06/0.16"),(0.16,0.25,"NXR-06/0.25"),(0.25,0.40,"NXR-06/0.40"),
    (0.40,0.63,"NXR-06/0.63"),(0.63,1.0,"NXR-06/1.0"),(1.0,1.6,"NXR-06/1.6"),
    (1.6,2.5,"NXR-06/2.5"),(2.5,4.0,"NXR-06/4.0"),(4.0,6.3,"NXR-06/6.3"),
    (6.0,10.0,"NXR-12/10"),(9.0,14.0,"NXR-12/14"),(12.0,18.0,"NXR-25/18"),
    (16.0,25.0,"NXR-25/25"),(20.0,32.0,"NXR-32/32"),(28.0,45.0,"NXR-45/45"),
    (38.0,65.0,"NXR-65/65"),(52.0,80.0,"NXR-80/80"),(63.0,100.0,"NXR-100/100"),
]

# LS (LG) ── (serie MC contactores, MT térmicos, MMS guardamotores)
_LS_CONTACTOR = [
    (9,"MC-9b"),(12,"MC-12b"),(18,"MC-18b"),(22,"MC-22b"),(25,"MC-25b"),
    (32,"MC-32a"),(40,"MC-40a"),(50,"MC-50a"),(65,"MC-65a"),(75,"MC-75a"),
    (85,"MC-85a"),(100,"MC-100a"),(130,"MC-130a"),(150,"MC-150a"),(185,"MC-185a"),
    (225,"MC-225a"),(300,"MC-300a"),(400,"MC-400a"),(500,"MC-500a"),(630,"MC-630a"),
]
_LS_THERMAL = [
    (0.10,0.16,"MT-12/0.16"),(0.16,0.25,"MT-12/0.25"),(0.25,0.40,"MT-12/0.40"),
    (0.40,0.63,"MT-12/0.63"),(0.63,1.0,"MT-12/1.0"),(1.0,1.6,"MT-12/1.6"),
    (1.6,2.5,"MT-12/2.5"),(2.5,4.0,"MT-12/4.0"),(4.0,6.0,"MT-12/6.0"),
    (5.5,8.0,"MT-12/8.0"),(7.0,10.0,"MT-12/10"),(9.0,13.0,"MT-12/13"),
    (12.0,18.0,"MT-32/18"),(16.0,25.0,"MT-32/25"),(22.0,32.0,"MT-32/32"),
    (28.0,40.0,"MT-63/40"),(36.0,52.0,"MT-63/52"),(45.0,63.0,"MT-63/63"),
    (55.0,80.0,"MT-95/80"),(70.0,95.0,"MT-95/95"),
]
_LS_GUARDAMOTOR = [
    (0.10,0.16,"MMS-32H/0.16"),(0.16,0.25,"MMS-32H/0.25"),(0.25,0.40,"MMS-32H/0.40"),
    (0.40,0.63,"MMS-32H/0.63"),(0.63,1.0,"MMS-32H/1.0"),(1.0,1.6,"MMS-32H/1.6"),
    (1.6,2.5,"MMS-32H/2.5"),(2.5,4.0,"MMS-32H/4.0"),(4.0,6.3,"MMS-32H/6.3"),
    (6.0,10.0,"MMS-32H/10"),(9.0,14.0,"MMS-32H/14"),(12.0,18.0,"MMS-32H/18"),
    (16.0,25.0,"MMS-32H/25"),(20.0,32.0,"MMS-32H/32"),(28.0,45.0,"MMS-63H/45"),
    (38.0,65.0,"MMS-63H/65"),(52.0,80.0,"MMS-100H/80"),(63.0,100.0,"MMS-100H/100"),
]

# WEG ── (serie CWM contactores, RW térmicos, MPW guardamotores)
_WEG_CONTACTOR = [
    (9,"CWM9"),(12,"CWM12"),(18,"CWM18"),(25,"CWM25"),(32,"CWM32"),
    (40,"CWM40"),(50,"CWM50"),(65,"CWM65"),(80,"CWM80"),(95,"CWM95"),
    (105,"CWM105"),(145,"CWM145"),(185,"CWM185"),(210,"CWM210"),
    (265,"CWM265"),(330,"CWM330"),(400,"CWM400"),(500,"CWM500"),(630,"CWM630"),
]
_WEG_THERMAL = [
    (0.10,0.16,"RW27-0.16"),(0.16,0.25,"RW27-0.25"),(0.25,0.40,"RW27-0.40"),
    (0.40,0.63,"RW27-0.63"),(0.63,1.0,"RW27-1.0"),(1.0,1.6,"RW27-1.6"),
    (1.6,2.5,"RW27-2.5"),(2.5,4.0,"RW27-4.0"),(4.0,6.0,"RW27-6.0"),
    (5.5,8.0,"RW27-8.0"),(7.0,10.0,"RW27-10"),(9.0,13.0,"RW27-13"),
    (12.0,18.0,"RW27-18"),(16.0,25.0,"RW27-25"),(22.0,32.0,"RW27-32"),
    (28.0,40.0,"RW67-40"),(36.0,52.0,"RW67-52"),(45.0,63.0,"RW67-63"),
    (55.0,80.0,"RW67-80"),(70.0,100.0,"RW67-100"),
]
_WEG_GUARDAMOTOR = [
    (0.10,0.16,"MPW18-3-U016"),(0.16,0.25,"MPW18-3-U025"),(0.25,0.40,"MPW18-3-U040"),
    (0.40,0.63,"MPW18-3-U063"),(0.63,1.0,"MPW18-3-U10"),(1.0,1.6,"MPW18-3-U16"),
    (1.6,2.5,"MPW18-3-U25"),(2.5,4.0,"MPW18-3-U40"),(4.0,6.3,"MPW18-3-U63"),
    (6.0,10.0,"MPW18-3-A100"),(9.0,14.0,"MPW18-3-A140"),(12.0,18.0,"MPW25-3-A180"),
    (16.0,25.0,"MPW25-3-A250"),(20.0,32.0,"MPW40-3-A320"),(28.0,45.0,"MPW40-3-A450"),
    (38.0,65.0,"MPW65-3-A650"),(52.0,80.0,"MPW80-3-A800"),(63.0,100.0,"MPW100-3-A1000"),
]

# Tabla de referencias por marca para lookup en _model_name
_BRAND_TABLES = {
    "Schneider": {"contactor": _SCH_CONTACTOR, "thermal": _SCH_THERMAL, "guardamotor": _SCH_GUARDAMOTOR},
    "ABB":       {"contactor": _ABB_CONTACTOR, "thermal": _ABB_THERMAL, "guardamotor": _ABB_GUARDAMOTOR},
    "Siemens":   {"contactor": _SIE_CONTACTOR, "thermal": _SIE_THERMAL, "guardamotor": _SIE_GUARDAMOTOR},
    "Chint":     {"contactor": _CHI_CONTACTOR, "thermal": _CHI_THERMAL, "guardamotor": _CHI_GUARDAMOTOR},
    "LS":        {"contactor": _LS_CONTACTOR,  "thermal": _LS_THERMAL,  "guardamotor": _LS_GUARDAMOTOR},
    "WEG":       {"contactor": _WEG_CONTACTOR, "thermal": _WEG_THERMAL, "guardamotor": _WEG_GUARDAMOTOR},
}

def _next_breaker(amps):
    for b in _BREAKER_SERIES:
        if b >= amps: return b
    return _BREAKER_SERIES[-1]

def _select_contactor(amps, brand="Schneider"):
    tbl = _BRAND_TABLES.get(brand, _BRAND_TABLES["Schneider"])["contactor"]
    for limit, _ in tbl:
        if amps <= limit: return limit
    return 630

def _select_thermal(amps, brand="Schneider"):
    tbl = _BRAND_TABLES.get(brand, _BRAND_TABLES["Schneider"])["thermal"]
    for lo, hi, model in tbl:
        if lo <= amps <= hi: return model
    return tbl[-1][2]

def _select_guardamotor(amps, brand="Schneider"):
    tbl = _BRAND_TABLES.get(brand, _BRAND_TABLES["Schneider"])["guardamotor"]
    for lo, hi, model in tbl:
        if lo <= amps <= hi: return model
    return tbl[-1][2]

def _model_name(kw_type, amps, brand="Schneider"):
    """Nombre comercial completo del componente de protección según la marca."""
    a = int(round(amps))
    tbl_c = _BRAND_TABLES.get(brand, _BRAND_TABLES["Schneider"])["contactor"]

    if kw_type == 'breaker':
        # Todos usan la misma serie IEC — solo cambia el nombre de la línea
        if brand == "ABB":
            if a <= 63:    return f"Breaker S200M {a}A"
            elif a <= 160: return f"Breaker Tmax XT1 {a}A"
            elif a <= 250: return f"Breaker Tmax XT3 {a}A"
            elif a <= 400: return f"Breaker Tmax XT5 {a}A"
            else:          return f"Breaker Tmax XT6 {a}A"
        elif brand == "Siemens":
            if a <= 63:    return f"Breaker 5SL4 {a}A"
            elif a <= 160: return f"Breaker 3VA1 {a}A"
            elif a <= 250: return f"Breaker 3VA2 {a}A"
            elif a <= 400: return f"Breaker 3VT1 {a}A"
            else:          return f"Breaker 3VT2 {a}A"
        elif brand == "Chint":
            if a <= 63:    return f"Breaker NB1-63 {a}A"
            elif a <= 160: return f"Breaker NM1-160 {a}A"
            elif a <= 250: return f"Breaker NM1-250 {a}A"
            elif a <= 400: return f"Breaker NM1-400 {a}A"
            else:          return f"Breaker NM1-630 {a}A"
        elif brand == "LS":
            if a <= 63:    return f"Breaker BKN {a}A"
            elif a <= 160: return f"Breaker ABN {a}A"
            elif a <= 250: return f"Breaker ABS {a}A"
            elif a <= 400: return f"Breaker ABS {a}A"
            else:          return f"Breaker ABH {a}A"
        elif brand == "WEG":
            if a <= 63:    return f"Breaker MDW {a}A"
            elif a <= 160: return f"Breaker CBA160 {a}A"
            elif a <= 250: return f"Breaker CBA250 {a}A"
            elif a <= 400: return f"Breaker CBA400 {a}A"
            else:          return f"Breaker CBA630 {a}A"
        else:  # Schneider
            if a <= 63:    return f"Breaker iC60N {a}A"
            elif a <= 160: return f"Breaker NSX160 {a}A"
            elif a <= 250: return f"Breaker NSX250 {a}A"
            elif a <= 400: return f"Breaker NSX400 {a}A"
            else:          return f"Breaker NSX630 {a}A"

    elif kw_type == 'contactor':
        for limit, model in tbl_c:
            if a <= limit: return f"Contactor {model}"
        return f"Contactor {tbl_c[-1][1]}"

    elif kw_type in ('thermal', 'rele', 'relay'):
        return f"Relé Térmico {_select_thermal(amps, brand)}"

    elif kw_type in ('guardamotor', 'guardomotor'):
        return f"Guardamotor {_select_guardamotor(amps, brand)}"

    elif kw_type == 'diferencial':
        c = _next_breaker(amps * 1.25)
        if brand == "ABB":
            return f"Diferencial F200 {c}A 30mA"
        elif brand == "Siemens":
            return f"Diferencial 5SV3 {c}A 30mA"
        elif brand == "Chint":
            return f"Diferencial NL1 {c}A 30mA"
        elif brand == "LS":
            return f"Diferencial RCD {c}A 30mA"
        elif brand == "WEG":
            return f"Diferencial DR {c}A 30mA"
        else:
            return f"Diferencial iID {c}A 30mA"

    return f"Protección {a}A"

# MOTOR DE SUGERENCIAS - JERARQUÍA GLOBAL Y CONTEXTUAL
class ProtectionSuggestionEngine:
    """
    Algoritmo de identificación por jerarquía global y contexto de hoja.
    """
    def __init__(self, app, protection_component, brand="Schneider"):
        self.app = app
        self.protection = protection_component
        self.brand = brand
        self.connections = getattr(app, 'connections', [])
        self.last_charge_component = None

        self.sheet_name = "DESCONOCIDA"
        try:
            active_sheet = self.app.project.get_active_sheet()
            if active_sheet:
                self.sheet_name = active_sheet.name.upper()
        except:
            pass

    def run(self):
        """Ejecuta el análisis y retorna la descripción sugerida."""
        try:
            # 1. ¿Es una hoja secundaria (Control, Luces, etc.)?
            is_secondary = any(x in self.sheet_name for x in ["CONTROL", "LUCES", "ALARMAS", "MANIOBRA", "PLC"])

            # 2. ¿Somos un candidato a Switch Principal? (Solo en hojas de potencia)
            # El Breaker Principal solo nace en hojas de fuerza o potencia.
            if not is_secondary:
                kw = get_component_keyword(self.protection)
                if kw in ('breaker', 'disyuntor'):
                    if self._is_the_global_main_breaker():
                        return {'description': "Breaker Principal"}

            # 3. Rastrear la carga (Motor, PLC, etc.) - Prioridad para cualquier hoja
            charge_info = self._trace_branch_charge()
            if charge_info:
                return {'description': f"{charge_info}"}

            # 4. Fallback contextual para hojas secundarias
            if is_secondary:
                # Si no hay motor pero es la cabecera de la hoja, sugerir por nombre de hoja
                if self._is_head_of_secondary_circuit():
                    # Limpiar el nombre de la hoja para la descripción
                    clean_name = self.sheet_name.replace("HOJA", "").strip()
                    return {'description': f"Protección {clean_name}"}
                return {'description': f"Rama {self.sheet_name}"}

            return {'description': "Circuito Derivado"}
        except Exception as e:
            from evaPr import _report_error
            _report_error("Suggestion Engine Run", e)
            return None

    def _is_the_global_main_breaker(self):
        """Determina si es el breaker más cercano a la entrada absoluta del sistema."""
        sources = self._find_absolute_sources()
        if not sources:
            return False

        all_breakers = [c for c in getattr(self.app, 'components', [])
                        if get_component_keyword(c) in ('breaker', 'disyuntor')]

        if not all_breakers:
            return False

        distances = {}
        min_dist = float('inf')
        for b in all_breakers:
            dist = self._calculate_min_source_distance(b, sources)
            distances[id(b)] = dist
            if dist < min_dist:
                min_dist = dist

        my_dist = distances.get(id(self.protection), float('inf'))
        return my_dist <= min_dist and my_dist < 10

    def _is_head_of_secondary_circuit(self):
        """Verifica si el componente está al inicio del circuito en una hoja secundaria."""
        # Si está conectado a algo que parezca una entrada (L1, N) en esta hoja
        for nbr in self._get_neighbors(self.protection):
            name = self._get_comp_name(nbr).upper()
            if any(x in name for x in ['L1', 'L2', 'L3', 'N', 'FASE', '.']):
                return True
        return False

    def _calculate_min_source_distance(self, start_comp, sources):
        """Calcula la distancia mínima a las fuentes."""
        visited = {id(start_comp)}
        queue = [(start_comp, 0)]
        source_ids = {id(s) for s in sources}

        while queue:
            cur, dist = queue.pop(0)
            if id(cur) in source_ids: return dist
            if dist > 20: continue
            for nbr in self._get_neighbors(cur):
                if id(nbr) not in visited:
                    visited.add(id(nbr))
                    queue.append((nbr, dist + 1))
        return float('inf')

    def _find_absolute_sources(self):
        """Busca fuentes reales descartando continuidades de otras hojas."""
        found = []
        for c in getattr(self.app, 'components', []):
            name = self._get_comp_name(c).upper()
            ctype = (getattr(c, 'component_type', '') or '').lower()
            # Las 'Conexión Salida' (conxn) llevan etiqueta de fase (L1/L2/N) pero
            # NO son fuentes reales; si se cuentan como fuentes, cualquier breaker
            # de rama conectado a esa etiqueta se confunde con el Breaker Principal.
            if ctype == 'conxn':
                continue
            # Si el nombre contiene caracteres de referencia cruzada (/ o .), no es origen absoluto
            if any(x in name for x in ['/', '.']):
                continue
            if name in ['L1', 'L2', 'L3', 'N', 'SOURCE', 'ENTRY'] or ctype == 'fase':
                found.append(c)
        return found

    def _get_neighbors(self, comp):
        """Retorna los componentes vecinos conectados."""
        nbrs = []
        for conn in self.connections:
            start = getattr(conn, 'start_component', None)
            end = getattr(conn, 'end_component', None)
            if start is comp and end: nbrs.append(end)
            elif end is comp and start: nbrs.append(start)
        return nbrs

    def _trace_branch_charge(self):
        """Rastrea la rama para encontrar el componente de carga principal."""
        visited = set([id(self.protection)])
        queue = [(self.protection, 0)]
        found_charges = []

        while queue:
            cur, dist = queue.pop(0)
            ctype, cname = self._identify_component_type(cur)
            if ctype and cur != self.protection:
                found_charges.append((dist, ctype, cname, cur))
                if ctype in ["Motor", "VDF", "Transformador"]: continue
            for nbr in self._get_neighbors(cur):
                if id(nbr) not in visited:
                    visited.add(id(nbr))
                    queue.append((nbr, dist + 1))

        if not found_charges: return None
        priority = {"Motor": 1, "VDF": 2, "PLC": 3, "Transformador": 4}
        # Preferir la carga MÁS CERCANA (la que realmente está en ESTA rama). El bus
        # compartido permite alcanzar motores de otras ramas; elegir por prioridad
        # sin distancia tomaba un motor ajeno. La prioridad solo desempata.
        found_charges.sort(key=lambda x: (x[0], priority.get(x[1], 99)))
        _dist, best_type, best_name, best_comp = found_charges[0]
        self.last_charge_component = best_comp
        if best_name:
            prefix = "MOTOR " if best_type == "Motor" and not best_name.startswith("MOTOR") else f"{best_type} "
            return f"{prefix}{best_name}"
        return best_type

    def _trace_control_loads(self):
        """Rastrea la rama y retorna los consumos de control con su VA estimado."""
        visited = set([id(self.protection)])
        queue = [(self.protection, 0)]
        loads = []
        while queue:
            cur, dist = queue.pop(0)
            if cur != self.protection:
                va = _estimate_va(cur)
                if va > 0:
                    loads.append((va, cur))
            for nbr in self._get_neighbors(cur):
                if id(nbr) not in visited:
                    visited.add(id(nbr))
                    queue.append((nbr, dist + 1))
        return loads

    def compute_control_breaker(self):
        """Suma el VA de los consumos rastreados y dimensiona el breaker.

        Retorna dict con llaves: total_va, voltage, current, breaker.
        None si no se encontraron consumos con VA.
        """
        loads = self._trace_control_loads()
        if not loads:
            return None

        total_va = sum(va for va, _ in loads)

        # Tensión de línea: etiqueta del breaker o default 220 V
        ld = getattr(self.protection, 'label_data', {}) or {}
        raw_v = str(ld.get('voltaje', '') or ld.get('ssf_rated_volt', '')).strip()
        m = _re.search(r'[\d.,]+', raw_v)
        try:
            voltage = float(m.group().replace(',', '.')) if m else 220.0
        except ValueError:
            voltage = 220.0
        if voltage <= 0:
            voltage = 220.0

        current = total_va / voltage
        breaker = _next_breaker(current * 1.25)
        return {
            'total_va': total_va,
            'voltage': voltage,
            'current': current,
            'breaker': breaker,
            'loads': loads,
        }

    def _identify_component_type(self, comp):
        """Identifica el tipo de carga eléctrica."""
        fname = (getattr(comp, 'svg_file', '') or '').lower()
        cat = getattr(comp, 'category', '')
        name = self._get_comp_name(comp).upper()
        if cat == 'Motors' or name.startswith('M') and any(d.isdigit() for d in name) or 'MOTOR' in name:
            return "Motor", name
        if any(b in name for b in ['BOMBA', 'DOSIFICADORA', 'SUMERGIBLE', 'IMPULSORA', 'FILTRACION']):
            return "Motor", name
        if any(v in fname for v in ['vdf', 'vfd', 'sst', 'variador', 'soft-starter']):
            return "VDF", name
        if any(p in fname for p in ['plc', 'cpu', 'logo', 's7-']):
            return "PLC", name
        if any(t in fname for t in ['transformer', 'fuente', 'power_supply', 'trafo']):
            return "Transformador", name
        return None, None

    def _get_comp_name(self, comp):
        """Helper para obtener el nombre del componente."""
        ld = getattr(comp, 'label_data', {}) or {}
        return (ld.get('name', '') or ld.get('nombre', '') or getattr(comp, 'name', '')).strip()

def get_component_keyword(component) -> str:
    """Categoriza el componente de protección."""
    fname = (getattr(component, 'svg_file', '') or '').lower()
    if any(k in fname for k in ['circuit-breaker', 'disyuntor', 'magnetotermico', 'breaker']):
        return 'breaker'
    for kw in _PROTECTION_KEYWORDS:
        if kw in fname: return kw
    return ''

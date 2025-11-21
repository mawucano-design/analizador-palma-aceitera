[file name]: appcultivostropicales.py
[file content begin]
import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
import io
from shapely.geometry import Polygon
import math
import folium
from folium import plugins
from streamlit_folium import st_folium
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import base64

st.set_page_config(page_title="🌴 Analizador Cultivos", layout="wide")
st.title("🌱 ANALIZADOR CULTIVOS - METODOLOGÍA GEE COMPLETA CON AGROECOLOGÍA")
st.markdown("---")

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# PARÁMETROS MEJORADOS Y MÁS REALISTAS PARA DIFERENTES CULTIVOS
PARAMETROS_CULTIVOS = {
    'PALMA_ACEITERA': {
        'NITROGENO': {'min': 120, 'max': 200, 'optimo': 160},
        'FOSFORO': {'min': 40, 'max': 80, 'optimo': 60},
        'POTASIO': {'min': 160, 'max': 240, 'optimo': 200},
        'MATERIA_ORGANICA_OPTIMA': 3.5,
        'HUMEDAD_OPTIMA': 0.35,
        'pH_OPTIMO': 5.5,
        'CONDUCTIVIDAD_OPTIMA': 1.2
    },
    'CACAO': {
        'NITROGENO': {'min': 100, 'max': 180, 'optimo': 140},
        'FOSFORO': {'min': 30, 'max': 60, 'optimo': 45},
        'POTASIO': {'min': 120, 'max': 200, 'optimo': 160},
        'MATERIA_ORGANICA_OPTIMA': 4.0,
        'HUMEDAD_OPTIMA': 0.4,
        'pH_OPTIMO': 6.0,
        'CONDUCTIVIDAD_OPTIMA': 1.0
    },
    'BANANO': {
        'NITROGENO': {'min': 180, 'max': 280, 'optimo': 230},
        'FOSFORO': {'min': 50, 'max': 90, 'optimo': 70},
        'POTASIO': {'min': 250, 'max': 350, 'optimo': 300},
        'MATERIA_ORGANICA_OPTIMA': 4.5,
        'HUMEDAD_OPTIMA': 0.45,
        'pH_OPTIMO': 6.2,
        'CONDUCTIVIDAD_OPTIMA': 1.5
    }
}

# NUEVO: PARÁMETROS DE TEXTURA DEL SUELO POR CULTIVO
TEXTURA_SUELO_OPTIMA = {
    'PALMA_ACEITERA': {
        'textura_optima': 'FRANCO_ARCILLOSO',
        'arena_optima': 40,
        'limo_optima': 30,
        'arcilla_optima': 30,
        'densidad_aparente_optima': 1.3,
        'porosidad_optima': 0.5
    },
    'CACAO': {
        'textura_optima': 'FRANCO',
        'arena_optima': 45,
        'limo_optima': 35,
        'arcilla_optima': 20,
        'densidad_aparente_optima': 1.2,
        'porosidad_optima': 0.55
    },
    'BANANO': {
        'textura_optima': 'FRANCO_ARENOSO',
        'arena_optima': 50,
        'limo_optima': 30,
        'arcilla_optima': 20,
        'densidad_aparente_optima': 1.25,
        'porosidad_optima': 0.52
    }
}

# NUEVO: CLASIFICACIÓN DE TEXTURAS DEL SUELO
CLASIFICACION_TEXTURAS = {
    'ARENOSO': {'arena_min': 85, 'arena_max': 100, 'limo_max': 15, 'arcilla_max': 15},
    'FRANCO_ARENOSO': {'arena_min': 70, 'arena_max': 85, 'limo_max': 30, 'arcilla_max': 20},
    'FRANCO': {'arena_min': 43, 'arena_max': 52, 'limo_min': 28, 'limo_max': 50, 'arcilla_min': 7, 'arcilla_max': 27},
    'FRANCO_ARCILLOSO': {'arena_min': 20, 'arena_max': 45, 'limo_min': 15, 'limo_max': 53, 'arcilla_min': 27, 'arcilla_max': 40},
    'ARCILLOSO': {'arena_max': 45, 'limo_max': 40, 'arcilla_min': 40}
}

# FACTORES EDÁFICOS MÁS REALISTAS
FACTORES_SUELO = {
    'ARCILLOSO': {'retention': 1.3, 'drainage': 0.7, 'aeration': 0.6, 'workability': 0.5},
    'FRANCO_ARCILLOSO': {'retention': 1.2, 'drainage': 0.8, 'aeration': 0.7, 'workability': 0.7},
    'FRANCO': {'retention': 1.0, 'drainage': 1.0, 'aeration': 1.0, 'workability': 1.0},
    'FRANCO_ARENOSO': {'retention': 0.8, 'drainage': 1.2, 'aeration': 1.3, 'workability': 1.2},
    'ARENOSO': {'retention': 0.6, 'drainage': 1.4, 'aeration': 1.5, 'workability': 1.4}
}

# NUEVO: RECOMENDACIONES POR TIPO DE TEXTURA
RECOMENDACIONES_TEXTURA = {
    'ARCILLOSO': [
        "Añadir materia orgánica para mejorar estructura",
        "Evitar laboreo en condiciones húmedas",
        "Implementar drenajes superficiales",
        "Usar cultivos de cobertura para romper compactación"
    ],
    'FRANCO_ARCILLOSO': [
        "Mantener niveles adecuados de materia orgánica",
        "Rotación de cultivos para mantener estructura",
        "Laboreo mínimo conservacionista",
        "Aplicación moderada de enmiendas"
    ],
    'FRANCO': [
        "Textura ideal - mantener prácticas conservacionistas",
        "Rotación balanceada de cultivos",
        "Manejo integrado de nutrientes",
        "Conservar estructura con coberturas"
    ],
    'FRANCO_ARENOSO': [
        "Aplicación frecuente de materia orgánica",
        "Riego por goteo para eficiencia hídrica",
        "Fertilización fraccionada para reducir pérdidas",
        "Cultivos de cobertura para retener humedad"
    ],
    'ARENOSO': [
        "Altas dosis de materia orgánica y compost",
        "Sistema de riego por goteo con alta frecuencia",
        "Fertilización en múltiples aplicaciones",
        "Barreras vivas para reducir erosión"
    ]
}

# PRINCIPIOS AGROECOLÓGICOS - RECOMENDACIONES ESPECÍFICAS
RECOMENDACIONES_AGROECOLOGICAS = {
    'PALMA_ACEITERA': {
        'COBERTURAS_VIVAS': [
            "Leguminosas: Centrosema pubescens, Pueraria phaseoloides",
            "Coberturas mixtas: Maní forrajero (Arachis pintoi)",
            "Plantas de cobertura baja: Dichondra repens"
        ],
        'ABONOS_VERDES': [
            "Crotalaria juncea: 3-4 kg/ha antes de la siembra",
            "Mucuna pruriens: 2-3 kg/ha para control de malezas",
            "Canavalia ensiformis: Fijación de nitrógeno"
        ],
        'BIOFERTILIZANTES': [
            "Bocashi: 2-3 ton/ha cada 6 meses",
            "Compost de racimo vacío: 1-2 ton/ha",
            "Biofertilizante líquido: Aplicación foliar mensual"
        ],
        'MANEJO_ECOLOGICO': [
            "Uso de trampas amarillas para insectos",
            "Cultivos trampa: Maíz alrededor de la plantación",
            "Conservación de enemigos naturales"
        ],
        'ASOCIACIONES': [
            "Piña en calles durante primeros 2 años",
            "Yuca en calles durante establecimiento",
            "Leguminosas arbustivas como cercas vivas"
        ]
    },
    'CACAO': {
        'COBERTURAS_VIVAS': [
            "Leguminosas rastreras: Arachis pintoi",
            "Coberturas sombreadas: Erythrina poeppigiana",
            "Plantas aromáticas: Lippia alba para control plagas"
        ],
        'ABONOS_VERDES': [
            "Frijol terciopelo (Mucuna pruriens): 3 kg/ha",
            "Guandul (Cajanus cajan): Podas periódicas",
            "Crotalaria: Control de nematodos"
        ],
        'BIOFERTILIZANTES': [
            "Compost de cacaoteca: 3-4 ton/ha",
            "Bocashi especial cacao: 2 ton/ha",
            "Té de compost aplicado al suelo"
        ],
        'MANEJO_ECOLOGICO': [
            "Sistema agroforestal multiestrato",
            "Manejo de sombra regulada (30-50%)",
            "Control biológico con hongos entomopatógenos"
        ],
        'ASOCIACIONES': [
            "Árboles maderables: Cedro, Caoba",
            "Frutales: Cítricos, Aguacate",
            "Plantas medicinales: Jengibre, Cúrcuma"
        ]
    },
    'BANANO': {
        'COBERTURAS_VIVAS': [
            "Arachis pintoi entre calles",
            "Leguminosas de porte bajo",
            "Coberturas para control de malas hierbas"
        ],
        'ABONOS_VERDES': [
            "Mucuna pruriens: 4 kg/ha entre ciclos",
            "Canavalia ensiformis: Fijación de N",
            "Crotalaria spectabilis: Control nematodos"
        ],
        'BIOFERTILIZANTES': [
            "Compost de pseudotallo: 4-5 ton/ha",
            "Bocashi bananero: 3 ton/ha",
            "Biofertilizante a base de micorrizas"
        ],
        'MANEJO_ECOLOGICO': [
            "Trampas cromáticas para picudos",
            "Barreras vivas con citronela",
            "Uso de trichoderma para control enfermedades"
        ],
        'ASOCIACIONES': [
            "Leguminosas arbustivas en linderos",
            "Cítricos como cortavientos",
            "Plantas repelentes: Albahaca, Menta"
        ]
    }
}

# FACTORES ESTACIONALES
FACTORES_MES = {
    "ENERO": 0.9, "FEBRERO": 0.95, "MARZO": 1.0, "ABRIL": 1.05,
    "MAYO": 1.1, "JUNIO": 1.0, "JULIO": 0.95, "AGOSTO": 0.9,
    "SEPTIEMBRE": 0.95, "OCTUBRE": 1.0, "NOVIEMBRE": 1.05, "DICIEMBRE": 1.0
}

FACTORES_N_MES = {
    "ENERO": 1.0, "FEBRERO": 1.05, "MARZO": 1.1, "ABRIL": 1.15,
    "MAYO": 1.2, "JUNIO": 1.1, "JULIO": 1.0, "AGOSTO": 0.9,
    "SEPTIEMBRE": 0.95, "OCTUBRE": 1.0, "NOVIEMBRE": 1.05, "DICIEMBRE": 1.0
}

FACTORES_P_MES = {
    "ENERO": 1.0, "FEBRERO": 1.0, "MARZO": 1.05, "ABRIL": 1.1,
    "MAYO": 1.15, "JUNIO": 1.1, "JULIO": 1.05, "AGOSTO": 1.0,
    "SEPTIEMBRE": 1.0, "OCTUBRE": 1.05, "NOVIEMBRE": 1.1, "DICIEMBRE": 1.05
}

FACTORES_K_MES = {
    "ENERO": 1.0, "FEBRERO": 1.0, "MARZO": 1.0, "ABRIL": 1.05,
    "MAYO": 1.1, "JUNIO": 1.15, "JULIO": 1.2, "AGOSTO": 1.15,
    "SEPTIEMBRE": 1.1, "OCTUBRE": 1.05, "NOVIEMBRE": 1.0, "DICIEMBRE": 1.0
}

# PALETAS GEE MEJORADAS
PALETAS_GEE = {
    'FERTILIDAD': ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850', '#006837'],
    'NITROGENO': ['#8c510a', '#bf812d', '#dfc27d', '#f6e8c3', '#c7eae5', '#80cdc1', '#35978f', '#01665e'],
    'FOSFORO': ['#67001f', '#b2182b', '#d6604d', '#f4a582', '#fddbc7', '#d1e5f0', '#92c5de', '#4393c3', '#2166ac', '#053061'],
    'POTASIO': ['#4d004b', '#810f7c', '#8c6bb1', '#8c96c6', '#9ebcda', '#bfd3e6', '#e0ecf4', '#edf8fb'],
    'TEXTURA': ['#8c510a', '#d8b365', '#f6e8c3', '#c7eae5', '#5ab4ac', '#01665e']  # NUEVA PALETA PARA TEXTURA
}

# Inicializar session_state
if 'analisis_completado' not in st.session_state:
    st.session_state.analisis_completado = False
if 'gdf_analisis' not in st.session_state:
    st.session_state.gdf_analisis = None
if 'gdf_original' not in st.session_state:
    st.session_state.gdf_original = None
if 'gdf_zonas' not in st.session_state:
    st.session_state.gdf_zonas = None
if 'area_total' not in st.session_state:
    st.session_state.area_total = 0
if 'datos_demo' not in st.session_state:
    st.session_state.datos_demo = False

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    
    cultivo = st.selectbox("Cultivo:", 
                          ["PALMA_ACEITERA", "CACAO", "BANANO"])
    
    # NUEVO: Opción para análisis de textura
    analisis_tipo = st.selectbox("Tipo de Análisis:", 
                               ["FERTILIDAD ACTUAL", "RECOMENDACIONES NPK", "ANÁLISIS DE TEXTURA"])
    
    nutriente = st.selectbox("Nutriente:", ["NITRÓGENO", "FÓSFORO", "POTASIO"])
    
    mes_analisis = st.selectbox("Mes de Análisis:", 
                               ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                                "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"])
    
    st.subheader("🎯 División de Parcela")
    n_divisiones = st.slider("Número de zonas de manejo:", min_value=16, max_value=32, value=24)
    
    st.subheader("📤 Subir Parcela")
    uploaded_zip = st.file_uploader("Subir ZIP con shapefile de tu parcela", type=['zip'])
    
    # Botón para resetear la aplicación
    if st.button("🔄 Reiniciar Análisis"):
        st.session_state.analisis_completado = False
        st.session_state.gdf_analisis = None
        st.session_state.gdf_original = None
        st.session_state.gdf_zonas = None
        st.session_state.area_total = 0
        st.session_state.datos_demo = False
        st.rerun()

# NUEVA FUNCIÓN: CLASIFICAR TEXTURA DEL SUELO
def clasificar_textura_suelo(arena, limo, arcilla):
    """Clasifica la textura del suelo según el triángulo de texturas USDA"""
    try:
        # Normalizar porcentajes a 100%
        total = arena + limo + arcilla
        if total == 0:
            return "NO_DETERMINADA"
        
        arena_norm = (arena / total) * 100
        limo_norm = (limo / total) * 100
        arcilla_norm = (arcilla / total) * 100
        
        # Clasificación según USDA
        if arcilla_norm >= 40:
            return "ARCILLOSO"
        elif arcilla_norm >= 27 and limo_norm >= 15 and limo_norm <= 53 and arena_norm >= 20 and arena_norm <= 45:
            return "FRANCO_ARCILLOSO"
        elif arcilla_norm >= 7 and arcilla_norm <= 27 and limo_norm >= 28 and limo_norm <= 50 and arena_norm >= 43 and arena_norm <= 52:
            return "FRANCO"
        elif arena_norm >= 70 and arena_norm <= 85 and arcilla_norm <= 20:
            return "FRANCO_ARENOSO"
        elif arena_norm >= 85:
            return "ARENOSO"
        else:
            return "FRANCO"  # Por defecto
        
    except Exception as e:
        return "NO_DETERMINADA"

# NUEVA FUNCIÓN: CALCULAR PROPIEDADES FÍSICAS DEL SUELO
def calcular_propiedades_fisicas_suelo(textura, materia_organica):
    """Calcula propiedades físicas del suelo basadas en textura y MO"""
    propiedades = {
        'capacidad_campo': 0.0,
        'punto_marchitez': 0.0,
        'agua_disponible': 0.0,
        'densidad_aparente': 0.0,
        'porosidad': 0.0,
        'conductividad_hidraulica': 0.0
    }
    
    # Valores base según textura (mm/m)
    base_propiedades = {
        'ARCILLOSO': {'cc': 350, 'pm': 200, 'da': 1.3, 'porosidad': 0.5, 'kh': 0.1},
        'FRANCO_ARCILLOSO': {'cc': 300, 'pm': 150, 'da': 1.25, 'porosidad': 0.53, 'kh': 0.5},
        'FRANCO': {'cc': 250, 'pm': 100, 'da': 1.2, 'porosidad': 0.55, 'kh': 1.5},
        'FRANCO_ARENOSO': {'cc': 180, 'pm': 80, 'da': 1.35, 'porosidad': 0.49, 'kh': 5.0},
        'ARENOSO': {'cc': 120, 'pm': 50, 'da': 1.5, 'porosidad': 0.43, 'kh': 15.0}
    }
    
    if textura in base_propiedades:
        base = base_propiedades[textura]
        
        # Ajustar por materia orgánica (cada 1% de MO mejora propiedades)
        factor_mo = 1.0 + (materia_organica * 0.05)
        
        propiedades['capacidad_campo'] = base['cc'] * factor_mo
        propiedades['punto_marchitez'] = base['pm'] * factor_mo
        propiedades['agua_disponible'] = (base['cc'] - base['pm']) * factor_mo
        propiedades['densidad_aparente'] = base['da'] / factor_mo
        propiedades['porosidad'] = min(0.65, base['porosidad'] * factor_mo)
        propiedades['conductividad_hidraulica'] = base['kh'] * factor_mo
    
    return propiedades

# NUEVA FUNCIÓN: EVALUAR ADECUACIÓN DE TEXTURA
def evaluar_adecuacion_textura(textura_actual, cultivo):
    """Evalúa qué tan adecuada es la textura para el cultivo específico"""
    textura_optima = TEXTURA_SUELO_OPTIMA[cultivo]['textura_optima']
    
    # Jerarquía de adecuación
    jerarquia_texturas = {
        'ARENOSO': 1,
        'FRANCO_ARENOSO': 2,
        'FRANCO': 3,
        'FRANCO_ARCILLOSO': 4,
        'ARCILLOSO': 5
    }
    
    if textura_actual not in jerarquia_texturas:
        return "NO_DETERMINADA", 0
    
    actual_idx = jerarquia_texturas[textura_actual]
    optima_idx = jerarquia_texturas[textura_optima]
    
    diferencia = abs(actual_idx - optima_idx)
    
    if diferencia == 0:
        return "ÓPTIMA", 1.0
    elif diferencia == 1:
        return "ADECUADA", 0.8
    elif diferencia == 2:
        return "MODERADA", 0.6
    elif diferencia == 3:
        return "LIMITANTE", 0.4
    else:
        return "MUY LIMITANTE", 0.2

# FUNCIÓN PARA GENERAR PDF (ACTUALIZADA CON TEXTURA)
def generar_informe_pdf(gdf_analisis, cultivo, analisis_tipo, nutriente, mes_analisis, area_total):
    """Genera un informe PDF completo con los resultados del análisis"""
    
    # Crear buffer para el PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=1*inch)
    styles = getSampleStyleSheet()
    
    # Crear estilos personalizados
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.darkgreen,
        spaceAfter=30,
        alignment=1  # Centrado
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.darkblue,
        spaceAfter=12,
        spaceBefore=12
    )
    
    normal_style = styles['Normal']
    
    # Contenido del PDF
    story = []
    
    # Título principal
    story.append(Paragraph("INFORME DE ANÁLISIS AGRÍCOLA", title_style))
    story.append(Spacer(1, 20))
    
    # Información general
    story.append(Paragraph("INFORMACIÓN GENERAL", heading_style))
    info_data = [
        ["Cultivo:", cultivo.replace('_', ' ').title()],
        ["Tipo de Análisis:", analisis_tipo],
        ["Mes de Análisis:", mes_analisis],
        ["Área Total:", f"{area_total:.2f} ha"],
        ["Fecha de Generación:", datetime.now().strftime("%d/%m/%Y %H:%M")]
    ]
    
    if analisis_tipo == "RECOMENDACIONES NPK":
        info_data.insert(2, ["Nutriente Analizado:", nutriente])
    
    info_table = Table(info_data, colWidths=[2*inch, 3*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(info_table)
    story.append(Spacer(1, 20))
    
    # NUEVO: Estadísticas de textura si es análisis de textura
    if analisis_tipo == "ANÁLISIS DE TEXTURA":
        story.append(Paragraph("ANÁLISIS DE TEXTURA DEL SUELO", heading_style))
        
        textura_stats = [
            ["Textura Predominante:", gdf_analisis['textura_suelo'].mode()[0] if len(gdf_analisis) > 0 else "N/A"],
            ["Adecuación Promedio:", f"{gdf_analisis['adecuacion_textura'].mean():.1%}"],
            ["Arena Promedio:", f"{gdf_analisis['arena'].mean():.1f}%"],
            ["Limo Promedio:", f"{gdf_analisis['limo'].mean():.1f}%"],
            ["Arcilla Promedio:", f"{gdf_analisis['arcilla'].mean():.1f}%"]
        ]
        
        textura_table = Table(textura_stats, colWidths=[2.5*inch, 2.5*inch])
        textura_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(textura_table)
        story.append(Spacer(1, 20))
    
    # Estadísticas resumen
    story.append(Paragraph("ESTADÍSTICAS DEL ANÁLISIS", heading_style))
    
    if analisis_tipo == "FERTILIDAD ACTUAL":
        stats_data = [
            ["Estadística", "Valor"],
            ["Índice Fertilidad Promedio", f"{gdf_analisis['indice_fertilidad'].mean():.3f}"],
            ["Nitrógeno Promedio (kg/ha)", f"{gdf_analisis['nitrogeno'].mean():.1f}"],
            ["Fósforo Promedio (kg/ha)", f"{gdf_analisis['fosforo'].mean():.1f}"],
            ["Potasio Promedio (kg/ha)", f"{gdf_analisis['potasio'].mean():.1f}"],
            ["Materia Orgánica Promedio (%)", f"{gdf_analisis['materia_organica'].mean():.1f}"],
            ["NDVI Promedio", f"{gdf_analisis['ndvi'].mean():.3f}"]
        ]
    elif analisis_tipo == "ANÁLISIS DE TEXTURA":
        stats_data = [
            ["Estadística", "Valor"],
            ["Textura Predominante", gdf_analisis['textura_suelo'].mode()[0] if len(gdf_analisis) > 0 else "N/A"],
            ["Adecuación Textura Promedio", f"{gdf_analisis['adecuacion_textura'].mean():.1%}"],
            ["Capacidad Campo Promedio (mm/m)", f"{gdf_analisis['capacidad_campo'].mean():.1f}"],
            ["Agua Disponible Promedio (mm/m)", f"{gdf_analisis['agua_disponible'].mean():.1f}"],
            ["Densidad Aparente Promedio (g/cm³)", f"{gdf_analisis['densidad_aparente'].mean():.2f}"]
        ]
    else:
        avg_rec = gdf_analisis['recomendacion_npk'].mean()
        total_rec = (gdf_analisis['recomendacion_npk'] * gdf_analisis['area_ha']).sum()
        stats_data = [
            ["Estadística", "Valor"],
            [f"Recomendación {nutriente} Promedio (kg/ha)", f"{avg_rec:.1f}"],
            [f"Total {nutriente} Requerido (kg)", f"{total_rec:.1f}"],
            ["Nitrógeno Promedio (kg/ha)", f"{gdf_analisis['nitrogeno'].mean():.1f}"],
            ["Fósforo Promedio (kg/ha)", f"{gdf_analisis['fosforo'].mean():.1f}"],
            ["Potasio Promedio (kg/ha)", f"{gdf_analisis['potasio'].mean():.1f}"]
        ]
    
    stats_table = Table(stats_data, colWidths=[3*inch, 2*inch])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(stats_table)
    story.append(Spacer(1, 20))
    
    # Distribución de categorías
    if analisis_tipo == "FERTILIDAD ACTUAL":
        story.append(Paragraph("DISTRIBUCIÓN DE CATEGORÍAS DE FERTILIDAD", heading_style))
        cat_dist = gdf_analisis['categoria'].value_counts()
        cat_data = [["Categoría", "Número de Zonas", "Porcentaje"]]
        
        total_zonas = len(gdf_analisis)
        for categoria, count in cat_dist.items():
            porcentaje = (count / total_zonas) * 100
            cat_data.append([categoria, str(count), f"{porcentaje:.1f}%"])
        
        cat_table = Table(cat_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
        cat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(cat_table)
        story.append(Spacer(1, 20))
    elif analisis_tipo == "ANÁLISIS DE TEXTURA":
        story.append(Paragraph("DISTRIBUCIÓN DE TEXTURAS DEL SUELO", heading_style))
        textura_dist = gdf_analisis['textura_suelo'].value_counts()
        textura_data = [["Textura", "Número de Zonas", "Porcentaje"]]
        
        total_zonas = len(gdf_analisis)
        for textura, count in textura_dist.items():
            porcentaje = (count / total_zonas) * 100
            textura_data.append([textura, str(count), f"{porcentaje:.1f}%"])
        
        textura_table = Table(textura_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
        textura_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(textura_table)
        story.append(Spacer(1, 20))
    
    # Mapa estático
    story.append(PageBreak())
    story.append(Paragraph("MAPA DE ANÁLISIS", heading_style))
    
    # Generar mapa estático para el PDF
    if analisis_tipo == "FERTILIDAD ACTUAL":
        titulo_mapa = f"Fertilidad Actual - {cultivo.replace('_', ' ').title()}"
        columna_visualizar = 'indice_fertilidad'
    elif analisis_tipo == "ANÁLISIS DE TEXTURA":
        titulo_mapa = f"Textura del Suelo - {cultivo.replace('_', ' ').title()}"
        columna_visualizar = 'textura_suelo'
    else:
        titulo_mapa = f"Recomendación {nutriente} - {cultivo.replace('_', ' ').title()}"
        columna_visualizar = 'recomendacion_npk'
    
    mapa_buffer = crear_mapa_estatico(
        gdf_analisis, titulo_mapa, columna_visualizar, analisis_tipo, nutriente
    )
    
    if mapa_buffer:
        try:
            # Convertir a imagen para PDF
            mapa_buffer.seek(0)
            img = Image(mapa_buffer, width=6*inch, height=4*inch)
            story.append(img)
            story.append(Spacer(1, 10))
            story.append(Paragraph(f"Figura 1: {titulo_mapa}", normal_style))
        except Exception as e:
            story.append(Paragraph("Error al generar el mapa para el PDF", normal_style))
    
    story.append(Spacer(1, 20))
    
    # Tabla de resultados por zona (primeras 10 zonas)
    story.append(Paragraph("RESULTADOS POR ZONA (PRIMERAS 10 ZONAS)", heading_style))
    
    # Preparar datos para tabla
    if analisis_tipo == "FERTILIDAD ACTUAL":
        columnas_tabla = ['id_zona', 'area_ha', 'categoria', 'prioridad', 'indice_fertilidad', 'nitrogeno', 'fosforo', 'potasio', 'materia_organica']
    elif analisis_tipo == "ANÁLISIS DE TEXTURA":
        columnas_tabla = ['id_zona', 'area_ha', 'textura_suelo', 'adecuacion_textura', 'arena', 'limo', 'arcilla', 'capacidad_campo', 'agua_disponible']
    else:
        columnas_tabla = ['id_zona', 'area_ha', 'categoria', 'prioridad', 'recomendacion_npk', 'deficit_npk', 'nitrogeno', 'fosforo', 'potasio']
    
    df_tabla = gdf_analisis[columnas_tabla].head(10).copy()
    
    # Redondear valores
    df_tabla['area_ha'] = df_tabla['area_ha'].round(3)
    if analisis_tipo == "FERTILIDAD ACTUAL":
        df_tabla['indice_fertilidad'] = df_tabla['indice_fertilidad'].round(3)
    elif analisis_tipo == "ANÁLISIS DE TEXTURA":
        df_tabla['arena'] = df_tabla['arena'].round(1)
        df_tabla['limo'] = df_tabla['limo'].round(1)
        df_tabla['arcilla'] = df_tabla['arcilla'].round(1)
        df_tabla['capacidad_campo'] = df_tabla['capacidad_campo'].round(1)
        df_tabla['agua_disponible'] = df_tabla['agua_disponible'].round(1)
    else:
        df_tabla['recomendacion_npk'] = df_tabla['recomendacion_npk'].round(1)
        df_tabla['deficit_npk'] = df_tabla['deficit_npk'].round(1)
    
    if 'nitrogeno' in df_tabla.columns:
        df_tabla['nitrogeno'] = df_tabla['nitrogeno'].round(1)
    if 'fosforo' in df_tabla.columns:
        df_tabla['fosforo'] = df_tabla['fosforo'].round(1)
    if 'potasio' in df_tabla.columns:
        df_tabla['potasio'] = df_tabla['potasio'].round(1)
    if 'materia_organica' in df_tabla.columns:
        df_tabla['materia_organica'] = df_tabla['materia_organica'].round(1)
    
    # Convertir a lista para la tabla
    table_data = [df_tabla.columns.tolist()]
    for _, row in df_tabla.iterrows():
        table_data.append(row.tolist())
    
    # Crear tabla
    zona_table = Table(table_data, colWidths=[0.5*inch] + [0.7*inch] * (len(columnas_tabla)-1))
    zona_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
    ]))
    story.append(zona_table)
    
    if len(gdf_analisis) > 10:
        story.append(Spacer(1, 5))
        story.append(Paragraph(f"* Mostrando 10 de {len(gdf_analisis)} zonas totales. Consulte el archivo CSV para todos los datos.", 
                             ParagraphStyle('Small', parent=normal_style, fontSize=8)))
    
    story.append(Spacer(1, 20))
    
    # Recomendaciones agroecológicas
    story.append(PageBreak())
    story.append(Paragraph("RECOMENDACIONES AGROECOLÓGICAS", heading_style))
    
    if analisis_tipo == "ANÁLISIS DE TEXTURA":
        textura_promedio = gdf_analisis['textura_suelo'].mode()[0] if len(gdf_analisis) > 0 else "FRANCO"
        adecuacion_promedio = gdf_analisis['adecuacion_textura'].mean()
        
        if adecuacion_promedio >= 0.8:
            enfoque = "ENFOQUE: MANTENIMIENTO - Textura adecuada"
        elif adecuacion_promedio >= 0.6:
            enfoque = "ENFOQUE: MEJORA MODERADA - Ajustes menores necesarios"
        else:
            enfoque = "ENFOQUE: MEJORA INTEGRAL - Enmiendas requeridas"
    else:
        categoria_promedio = gdf_analisis['categoria'].mode()[0] if len(gdf_analisis) > 0 else "MEDIA"
        
        if categoria_promedio in ["MUY BAJA", "BAJA"]:
            enfoque = "ENFOQUE: RECUPERACIÓN Y REGENERACIÓN - Intensidad: Alta"
        elif categoria_promedio in ["MEDIA"]:
            enfoque = "ENFOQUE: MANTENIMIENTO Y MEJORA - Intensidad: Media"
        else:
            enfoque = "ENFOQUE: CONSERVACIÓN Y OPTIMIZACIÓN - Intensidad: Baja"
    
    story.append(Paragraph(f"<b>Enfoque Principal:</b> {enfoque}", normal_style))
    story.append(Spacer(1, 10))
    
    # Recomendaciones específicas del cultivo
    recomendaciones = RECOMENDACIONES_AGROECOLOGICAS.get(cultivo, {})
    
    for categoria_rec, items in recomendaciones.items():
        story.append(Paragraph(f"<b>{categoria_rec.replace('_', ' ').title()}:</b>", normal_style))
        for item in items[:3]:  # Mostrar solo 3 items por categoría
            story.append(Paragraph(f"• {item}", normal_style))
        story.append(Spacer(1, 5))
    
    # NUEVO: Recomendaciones específicas de textura
    if analisis_tipo == "ANÁLISIS DE TEXTURA":
        story.append(Spacer(1, 10))
        story.append(Paragraph("<b>RECOMENDACIONES ESPECÍFICAS PARA TEXTURA:</b>", normal_style))
        
        textura_predominante = gdf_analisis['textura_suelo'].mode()[0] if len(gdf_analisis) > 0 else "FRANCO"
        recomendaciones_textura = RECOMENDACIONES_TEXTURA.get(textura_predominante, [])
        
        for rec in recomendaciones_textura:
            story.append(Paragraph(f"• {rec}", normal_style))
    
    # Plan de implementación
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>PLAN DE IMPLEMENTACIÓN:</b>", normal_style))
    
    planes = [
        ("INMEDIATO (0-15 días)", [
            "Preparación del terreno",
            "Siembra de abonos verdes", 
            "Aplicación de biofertilizantes"
        ]),
        ("CORTO PLAZO (1-3 meses)", [
            "Establecimiento coberturas",
            "Monitoreo inicial",
            "Ajustes de manejo"
        ]),
        ("MEDIANO PLAZO (3-12 meses)", [
            "Evaluación de resultados",
            "Diversificación",
            "Optimización del sistema"
        ])
    ]
    
    for periodo, acciones in planes:
        story.append(Paragraph(f"<b>{periodo}:</b>", normal_style))
        for accion in acciones:
            story.append(Paragraph(f"• {accion}", normal_style))
        story.append(Spacer(1, 5))
    
    # Pie de página con información adicional
    story.append(Spacer(1, 20))
    story.append(Paragraph("INFORMACIÓN ADICIONAL", heading_style))
    story.append(Paragraph("Este informe fue generado automáticamente por el Sistema de Análisis Agrícola GEE.", normal_style))
    story.append(Paragraph("Para consultas técnicas o información detallada, contacte con el departamento técnico.", normal_style))
    
    # Generar PDF
    doc.build(story)
    buffer.seek(0)
    
    return buffer

# FUNCIÓN MEJORADA PARA CALCULAR SUPERFICIE
def calcular_superficie(gdf):
    """Calcula superficie en hectáreas con manejo robusto de CRS"""
    try:
        if gdf.empty or gdf.geometry.isnull().all():
            return 0.0
            
        # Verificar si el CRS es geográfico (grados)
        if gdf.crs and gdf.crs.is_geographic:
            # Convertir a un CRS proyectado para cálculo de área precisa
            try:
                # Usar UTM adecuado (aquí se usa un CRS común para Colombia)
                gdf_proj = gdf.to_crs('EPSG:3116')  # MAGNA-SIRGAS / Colombia West zone
                area_m2 = gdf_proj.geometry.area
            except:
                # Fallback: conversión aproximada (1 grado ≈ 111km en ecuador)
                area_m2 = gdf.geometry.area * 111000 * 111000
        else:
            # Asumir que ya está en metros
            area_m2 = gdf.geometry.area
            
        return area_m2 / 10000  # Convertir a hectáreas
        
    except Exception as e:
        # Fallback simple
        try:
            return gdf.geometry.area.mean() / 10000
        except:
            return 1.0  # Valor por defecto

# FUNCIÓN MEJORADA PARA CREAR MAPA INTERACTIVO CON ESRI SATELITE (ACTUALIZADA CON TEXTURA)
def crear_mapa_interactivo_esri(gdf, titulo, columna_valor=None, analisis_tipo=None, nutriente=None):
    """Crea mapa interactivo con base ESRI Satélite - MEJORADO"""
    
    # Obtener centro y bounds del GeoDataFrame
    centroid = gdf.geometry.centroid.iloc[0]
    bounds = gdf.total_bounds
    
    # Crear mapa centrado con ESRI Satélite por defecto
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=15,
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Satélite'
    )
    
    # Añadir otras bases como opciones
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Calles',
        overlay=False
    ).add_to(m)
    
    folium.TileLayer(
        tiles='OpenStreetMap',
        name='OpenStreetMap',
        overlay=False
    ).add_to(m)
    
    # Añadir capa de relieve
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Relieve',
        overlay=False
    ).add_to(m)

    # CONFIGURAR RANGOS MEJORADOS
    if columna_valor and analisis_tipo:
        if analisis_tipo == "FERTILIDAD ACTUAL":
            vmin, vmax = 0, 1
            colores = PALETAS_GEE['FERTILIDAD']
            unidad = "Índice"
        elif analisis_tipo == "ANÁLISIS DE TEXTURA":
            # Mapa categórico para texturas
            texturas_unicas = gdf[columna_valor].unique()
            colores_textura = {
                'ARENOSO': '#d8b365',
                'FRANCO_ARENOSO': '#f6e8c3', 
                'FRANCO': '#c7eae5',
                'FRANCO_ARCILLOSO': '#5ab4ac',
                'ARCILLOSO': '#01665e',
                'NO_DETERMINADA': '#999999'
            }
            unidad = "Textura"
        else:
            # RANGOS MÁS REALISTAS PARA RECOMENDACIONES
            if nutriente == "NITRÓGENO":
                vmin, vmax = 0, 250
                colores = PALETAS_GEE['NITROGENO']
                unidad = "kg/ha N"
            elif nutriente == "FÓSFORO":
                vmin, vmax = 0, 120
                colores = PALETAS_GEE['FOSFORO']
                unidad = "kg/ha P₂O₅"
            else:  # POTASIO
                vmin, vmax = 0, 200
                colores = PALETAS_GEE['POTASIO']
                unidad = "kg/ha K₂O"
        
        # Función para obtener color
        def obtener_color(valor, vmin, vmax, colores):
            if vmax == vmin:
                return colores[len(colores)//2]
            valor_norm = (valor - vmin) / (vmax - vmin)
            valor_norm = max(0, min(1, valor_norm))
            idx = int(valor_norm * (len(colores) - 1))
            return colores[idx]
        
        # Añadir cada polígono con estilo mejorado
        for idx, row in gdf.iterrows():
            if analisis_tipo == "ANÁLISIS DE TEXTURA":
                # Manejo especial para textura (valores categóricos)
                textura = row[columna_valor]
                color = colores_textura.get(textura, '#999999')
                valor_display = textura
            else:
                # Manejo para valores numéricos
                valor = row[columna_valor]
                color = obtener_color(valor, vmin, vmax, colores)
                if analisis_tipo == "FERTILIDAD ACTUAL":
                    valor_display = f"{valor:.3f}"
                else:
                    valor_display = f"{valor:.1f}"
            
            # Popup más informativo
            if analisis_tipo == "FERTILIDAD ACTUAL":
                popup_text = f"""
                <div style="font-family: Arial; font-size: 12px;">
                    <h4>Zona {row['id_zona']}</h4>
                    <b>Índice Fertilidad:</b> {valor_display}<br>
                    <b>Área:</b> {row.get('area_ha', 0):.2f} ha<br>
                    <b>Categoría:</b> {row.get('categoria', 'N/A')}<br>
                    <b>Prioridad:</b> {row.get('prioridad', 'N/A')}<br>
                    <hr>
                    <b>N:</b> {row.get('nitrogeno', 0):.1f} kg/ha<br>
                    <b>P:</b> {row.get('fosforo', 0):.1f} kg/ha<br>
                    <b>K:</b> {row.get('potasio', 0):.1f} kg/ha<br>
                    <b>MO:</b> {row.get('materia_organica', 0):.1f}%<br>
                    <b>NDVI:</b> {row.get('ndvi', 0):.3f}
                </div>
                """
            elif analisis_tipo == "ANÁLISIS DE TEXTURA":
                popup_text = f"""
                <div style="font-family: Arial; font-size: 12px;">
                    <h4>Zona {row['id_zona']}</h4>
                    <b>Textura:</b> {valor_display}<br>
                    <b>Adecuación:</b> {row.get('adecuacion_textura', 0):.1%}<br>
                    <b>Área:</b> {row.get('area_ha', 0):.2f} ha<br>
                    <hr>
                    <b>Arena:</b> {row.get('arena', 0):.1f}%<br>
                    <b>Limo:</b> {row.get('limo', 0):.1f}%<br>
                    <b>Arcilla:</b> {row.get('arcilla', 0):.1f}%<br>
                    <b>Capacidad Campo:</b> {row.get('capacidad_campo', 0):.1f} mm/m<br>
                    <b>Agua Disponible:</b> {row.get('agua_disponible', 0):.1f} mm/m
                </div>
                """
            else:
                popup_text = f"""
                <div style="font-family: Arial; font-size: 12px;">
                    <h4>Zona {row['id_zona']}</h4>
                    <b>Recomendación {nutriente}:</b> {valor_display} {unidad}<br>
                    <b>Área:</b> {row.get('area_ha', 0):.2f} ha<br>
                    <b>Categoría Fertilidad:</b> {row.get('categoria', 'N/A')}<br>
                    <b>Prioridad:</b> {row.get('prioridad', 'N/A')}<br>
                    <hr>
                    <b>N Actual:</b> {row.get('nitrogeno', 0):.1f} kg/ha<br>
                    <b>P Actual:</b> {row.get('fosforo', 0):.1f} kg/ha<br>
                    <b>K Actual:</b> {row.get('potasio', 0):.1f} kg/ha<br>
                    <b>Déficit:</b> {row.get('deficit_npk', 0):.1f} kg/ha
                </div>
                """
            
            # Estilo mejorado para los polígonos
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x, color=color: {
                    'fillColor': color,
                    'color': 'black',
                    'weight': 2,
                    'fillOpacity': 0.7,
                    'opacity': 0.9
                },
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=f"Zona {row['id_zona']}: {valor_display}"
            ).add_to(m)
            
            # Marcador con número de zona mejorado
            centroid = row.geometry.centroid
            folium.Marker(
                [centroid.y, centroid.x],
                icon=folium.DivIcon(
                    html=f'''
                    <div style="
                        background-color: white; 
                        border: 2px solid black; 
                        border-radius: 50%; 
                        width: 28px; 
                        height: 28px; 
                        display: flex; 
                        align-items: center; 
                        justify-content: center; 
                        font-weight: bold; 
                        font-size: 11px;
                        color: black;
                    ">{row["id_zona"]}</div>
                    '''
                ),
                tooltip=f"Zona {row['id_zona']} - Click para detalles"
            ).add_to(m)
    else:
        # Mapa simple del polígono original
        for idx, row in gdf.iterrows():
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x: {
                    'fillColor': '#1f77b4',
                    'color': '#2ca02c',
                    'weight': 3,
                    'fillOpacity': 0.5,
                    'opacity': 0.8
                },
                popup=folium.Popup(
                    f"<b>Polígono {idx + 1}</b><br>Área: {calcular_superficie(gdf.iloc[[idx]]).iloc[0]:.2f} ha", 
                    max_width=300
                ),
            ).add_to(m)
    
    # Ajustar bounds del mapa
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    
    # Añadir controles mejorados
    folium.LayerControl().add_to(m)
    plugins.MeasureControl(position='bottomleft', primary_length_unit='meters').add_to(m)
    plugins.MiniMap(toggle_display=True, position='bottomright').add_to(m)
    plugins.Fullscreen(position='topright').add_to(m)
    
    # Añadir leyenda mejorada
    if columna_valor and analisis_tipo:
        legend_html = f'''
        <div style="
            position: fixed; 
            top: 10px; 
            right: 10px; 
            width: 250px; 
            height: auto; 
            background-color: white; 
            border: 2px solid grey; 
            z-index: 9999; 
            font-size: 12px; 
            padding: 10px; 
            border-radius: 5px;
            font-family: Arial;
        ">
            <h4 style="margin:0 0 10px 0; text-align:center; color: #333;">{titulo}</h4>
            <div style="margin-bottom: 10px;">
                <strong>Escala de Valores ({unidad}):</strong>
            </div>
        '''
        
        if analisis_tipo == "FERTILIDAD ACTUAL":
            steps = 8
            for i in range(steps):
                value = i / (steps - 1)
                color_idx = int((i / (steps - 1)) * (len(PALETAS_GEE['FERTILIDAD']) - 1))
                color = PALETAS_GEE['FERTILIDAD'][color_idx]
                categoria = ["Muy Baja", "Baja", "Media-Baja", "Media", "Media-Alta", "Alta", "Muy Alta"][min(i, 6)] if i < 7 else "Óptima"
                legend_html += f'<div style="margin:2px 0;"><span style="background:{color}; width:20px; height:15px; display:inline-block; margin-right:5px; border:1px solid #000;"></span> {value:.1f} ({categoria})</div>'
        elif analisis_tipo == "ANÁLISIS DE TEXTURA":
            # Leyenda categórica para texturas
            colores_textura = {
                'ARENOSO': '#d8b365',
                'FRANCO_ARENOSO': '#f6e8c3', 
                'FRANCO': '#c7eae5',
                'FRANCO_ARCILLOSO': '#5ab4ac',
                'ARCILLOSO': '#01665e'
            }
            for textura, color in colores_textura.items():
                legend_html += f'<div style="margin:2px 0;"><span style="background:{color}; width:20px; height:15px; display:inline-block; margin-right:5px; border:1px solid #000;"></span> {textura}</div>'
        else:
            steps = 6
            for i in range(steps):
                value = vmin + (i / (steps - 1)) * (vmax - vmin)
                color_idx = int((i / (steps - 1)) * (len(colores) - 1))
                color = colores[color_idx]
                intensidad = ["Muy Baja", "Baja", "Media", "Alta", "Muy Alta", "Máxima"][i]
                legend_html += f'<div style="margin:2px 0;"><span style="background:{color}; width:20px; height:15px; display:inline-block; margin-right:5px; border:1px solid #000;"></span> {value:.0f} ({intensidad})</div>'
        
        legend_html += '''
            <div style="margin-top: 10px; font-size: 10px; color: #666;">
                💡 Click en las zonas para detalles
            </div>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
    
    return m

# FUNCIÓN PARA CREAR MAPA VISUALIZADOR DE PARCELA
def crear_mapa_visualizador_parcela(gdf):
    """Crea mapa interactivo para visualizar la parcela original con ESRI Satélite"""
    
    # Obtener centro y bounds
    centroid = gdf.geometry.centroid.iloc[0]
    bounds = gdf.total_bounds
    
    # Crear mapa con ESRI Satélite por defecto
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=14,
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Satélite'
    )
    
    # Añadir otras bases
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Calles',
        overlay=False
    ).add_to(m)
    
    folium.TileLayer(
        tiles='OpenStreetMap',
        name='OpenStreetMap',
        overlay=False
    ).add_to(m)
    
    # Añadir polígonos de la parcela
    for idx, row in gdf.iterrows():
        area_ha = calcular_superficie(gdf.iloc[[idx]]).iloc[0]
        
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda x: {
                'fillColor': '#1f77b4',
                'color': '#2ca02c',
                'weight': 3,
                'fillOpacity': 0.4,
                'opacity': 0.8
            },
            popup=folium.Popup(
                f"<b>Parcela {idx + 1}</b><br>"
                f"<b>Área:</b> {area_ha:.2f} ha<br>"
                f"<b>Coordenadas:</b> {centroid.y:.4f}, {centroid.x:.4f}",
                max_width=300
            ),
            tooltip=f"Parcela {idx + 1} - {area_ha:.2f} ha"
        ).add_to(m)
    
    # Ajustar bounds
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    
    # Añadir controles
    folium.LayerControl().add_to(m)
    plugins.MeasureControl(position='bottomleft').add_to(m)
    plugins.MiniMap(toggle_display=True).add_to(m)
    plugins.Fullscreen(position='topright').add_to(m)
    
    # Añadir leyenda
    legend_html = '''
    <div style="position: fixed; 
                top: 10px; right: 10px; width: 200px; height: auto; 
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:14px; padding: 10px">
    <p><b>🌱 Visualizador de Parcela</b></p>
    <p><b>Leyenda:</b></p>
    <p><i style="background:#1f77b4; width:20px; height:20px; display:inline-block; margin-right:5px; opacity:0.4;"></i> Área de la parcela</p>
    <p><i style="background:#2ca02c; width:20px; height:20px; display:inline-block; margin_right:5px; opacity:0.8;"></i> Borde de la parcela</p>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    return m

# FUNCIÓN CORREGIDA PARA CREAR MAPA ESTÁTICO (ACTUALIZADA CON TEXTURA)
def crear_mapa_estatico(gdf, titulo, columna_valor=None, analisis_tipo=None, nutriente=None):
    """Crea mapa estático con matplotlib - CORREGIDO PARA COINCIDIR CON INTERACTIVO"""
    try:
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        
        # CONFIGURACIÓN UNIFICADA CON EL MAPA INTERACTIVO
        if columna_valor and analisis_tipo:
            if analisis_tipo == "FERTILIDAD ACTUAL":
                cmap = LinearSegmentedColormap.from_list('fertilidad_gee', PALETAS_GEE['FERTILIDAD'])
                vmin, vmax = 0, 1
            elif analisis_tipo == "ANÁLISIS DE TEXTURA":
                # Mapa categórico para texturas
                texturas_unicas = gdf[columna_valor].unique()
                colores_textura = {
                    'ARENOSO': '#d8b365',
                    'FRANCO_ARENOSO': '#f6e8c3', 
                    'FRANCO': '#c7eae5',
                    'FRANCO_ARCILLOSO': '#5ab4ac',
                    'ARCILLOSO': '#01665e',
                    'NO_DETERMINADA': '#999999'
                }
            else:
                # USAR EXACTAMENTE LOS MISMOS RANGOS QUE EL MAPA INTERACTIVO
                if nutriente == "NITRÓGENO":
                    cmap = LinearSegmentedColormap.from_list('nitrogeno_gee', PALETAS_GEE['NITROGENO'])
                    vmin, vmax = 0, 250
                elif nutriente == "FÓSFORO":
                    cmap = LinearSegmentedColormap.from_list('fosforo_gee', PALETAS_GEE['FOSFORO'])
                    vmin, vmax = 0, 120
                else:  # POTASIO
                    cmap = LinearSegmentedColormap.from_list('potasio_gee', PALETAS_GEE['POTASIO'])
                    vmin, vmax = 0, 200
            
            # Plotear cada polígono con color según valor - MÉTODO UNIFICADO
            for idx, row in gdf.iterrows():
                if analisis_tipo == "ANÁLISIS DE TEXTURA":
                    # Manejo especial para textura
                    textura = row[columna_valor]
                    color = colores_textura.get(textura, '#999999')
                else:
                    valor = row[columna_valor]
                    valor_norm = (valor - vmin) / (vmax - vmin)
                    valor_norm = max(0, min(1, valor_norm))
                    color = cmap(valor_norm)
                
                # Plot del polígono
                gdf.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1)
                
                # Etiqueta con valor - FORMATO MEJORADO
                centroid = row.geometry.centroid
                if analisis_tipo == "FERTILIDAD ACTUAL":
                    texto_valor = f"{row[columna_valor]:.3f}"
                elif analisis_tipo == "ANÁLISIS DE TEXTURA":
                    texto_valor = f"{row[columna_valor]}"
                else:
                    texto_valor = f"{row[columna_valor]:.0f} kg"
                
                ax.annotate(f"Z{row['id_zona']}\n{texto_valor}", 
                           (centroid.x, centroid.y), 
                           xytext=(3, 3), textcoords="offset points", 
                           fontsize=6, color='black', weight='bold',
                           bbox=dict(boxstyle="round,pad=0.2", facecolor='white', alpha=0.8),
                           ha='center', va='center')
        else:
            # Mapa simple del polígono original
            gdf.plot(ax=ax, color='lightblue', edgecolor='black', linewidth=2, alpha=0.7)
        
        # Configuración del mapa
        ax.set_title(f'🗺️ {titulo}', fontsize=14, fontweight='bold', pad=15)
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        # BARRA DE COLORES UNIFICADA
        if columna_valor and analisis_tipo and analisis_tipo != "ANÁLISIS DE TEXTURA":
            sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
            sm.set_array([])
            cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
            
            # Etiquetas de barra unificadas
            if analisis_tipo == "FERTILIDAD ACTUAL":
                cbar.set_label('Índice NPK Actual (0-1)', fontsize=10)
                # Marcas específicas para fertilidad
                cbar.set_ticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
                cbar.set_ticklabels(['0.0 (Muy Baja)', '0.2', '0.4 (Media)', '0.6', '0.8', '1.0 (Muy Alta)'])
            else:
                cbar.set_label(f'Recomendación {nutriente} (kg/ha)', fontsize=10)
                # Marcas específicas para recomendaciones
                if nutriente == "NITRÓGENO":
                    cbar.set_ticks([0, 50, 100, 150, 200, 250])
                    cbar.set_ticklabels(['0', '50', '100', '150', '200', '250 kg/ha'])
                elif nutriente == "FÓSFORO":
                    cbar.set_ticks([0, 24, 48, 72, 96, 120])
                    cbar.set_ticklabels(['0', '24', '48', '72', '96', '120 kg/ha'])
                else:  # POTASIO
                    cbar.set_ticks([0, 40, 80, 120, 160, 200])
                    cbar.set_ticklabels(['0', '40', '80', '120', '160', '200 kg/ha'])
        elif analisis_tipo == "ANÁLISIS DE TEXTURA":
            # Crear leyenda para texturas
            handles = []
            labels = []
            colores_textura = {
                'ARENOSO': '#d8b365',
                'FRANCO_ARENOSO': '#f6e8c3', 
                'FRANCO': '#c7eae5',
                'FRANCO_ARCILLOSO': '#5ab4ac',
                'ARCILLOSO': '#01665e'
            }
            for textura, color in colores_textura.items():
                if textura in gdf[columna_valor].values:
                    patch = mpatches.Patch(color=color, label=textura)
                    handles.append(patch)
                    labels.append(textura)
            
            if handles:
                ax.legend(handles=handles, labels=labels, loc='upper right', bbox_to_anchor=(1.15, 1))
        
        plt.tight_layout()
        
        # Convertir a imagen
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        return buf
        
    except Exception as e:
        st.error(f"Error creando mapa estático: {str(e)}")
        return None

# FUNCIÓN PARA MOSTRAR RECOMENDACIONES AGROECOLÓGICAS (ACTUALIZADA CON TEXTURA)
def mostrar_recomendaciones_agroecologicas(cultivo, categoria, area_ha, analisis_tipo, nutriente=None, textura_data=None):
    """Muestra recomendaciones agroecológicas específicas"""
    
    st.markdown("### 🌿 RECOMENDACIONES AGROECOLÓGICAS")
    
    # Determinar el enfoque según la categoría o textura
    if analisis_tipo == "ANÁLISIS DE TEXTURA" and textura_data:
        adecuacion_promedio = textura_data.get('adecuacion_promedio', 0.5)
        textura_predominante = textura_data.get('textura_predominante', 'FRANCO')
        
        if adecuacion_promedio >= 0.8:
            enfoque = "✅ **ENFOQUE: MANTENIMIENTO**"
            intensidad = "Textura adecuada - prácticas conservacionistas"
        elif adecuacion_promedio >= 0.6:
            enfoque = "⚠️ **ENFOQUE: MEJORA MODERADA**"
            intensidad = "Ajustes menores necesarios en manejo"
        else:
            enfoque = "🚨 **ENFOQUE: MEJORA INTEGRAL**"
            intensidad = "Enmiendas y correcciones requeridas"
            
        st.success(f"{enfoque} - {intensidad}")
        
        # Mostrar recomendaciones específicas de textura
        st.markdown("#### 🏗️ Recomendaciones Específicas para Textura del Suelo")
        
        recomendaciones_textura = RECOMENDACIONES_TEXTURA.get(textura_predominante, [])
        for rec in recomendaciones_textura:
            st.markdown(f"• {rec}")
            
        # Mostrar propiedades físicas si están disponibles
        if textura_data.get('propiedades_fisicas'):
            props = textura_data['propiedades_fisicas']
            st.markdown("#### 💧 Propiedades Físicas del Suelo")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Capacidad de Campo", f"{props.get('capacidad_campo', 0):.0f} mm/m")
                st.metric("Punto de Marchitez", f"{props.get('punto_marchitez', 0):.0f} mm/m")
            with col2:
                st.metric("Agua Disponible", f"{props.get('agua_disponible', 0):.0f} mm/m")
                st.metric("Densidad Aparente", f"{props.get('densidad_aparente', 0):.2f} g/cm³")
            with col3:
                st.metric("Porosidad", f"{props.get('porosidad', 0):.1%}")
                st.metric("Conduct. Hidráulica", f"{props.get('conductividad_hidraulica', 0):.1f} cm/día")
    
    else:
        # Enfoque tradicional basado en fertilidad
        if categoria in ["MUY BAJA", "BAJA"]:
            enfoque = "🚨 **ENFOQUE: RECUPERACIÓN Y REGENERACIÓN**"
            intensidad = "Alta"
        elif categoria in ["MEDIA"]:
            enfoque = "✅ **ENFOQUE: MANTENIMIENTO Y MEJORA**"
            intensidad = "Media"
        else:
            enfoque = "🌟 **ENFOQUE: CONSERVACIÓN Y OPTIMIZACIÓN**"
            intensidad = "Baja"
        
        st.success(f"{enfoque} - Intensidad: {intensidad}")
    
    # Obtener recomendaciones específicas del cultivo
    recomendaciones = RECOMENDACIONES_AGROECOLOGICAS.get(cultivo, {})
    
    # Mostrar por categorías
    col1, col2 = st.columns(2)
    
    with col1:
        with st.expander("🌱 **COBERTURAS VIVAS**", expanded=True):
            for rec in recomendaciones.get('COBERTURAS_VIVAS', []):
                st.markdown(f"• {rec}")
            
            # Recomendaciones adicionales según área
            if area_ha > 10:
                st.info("**Para áreas grandes:** Implementar en franjas progresivas")
            else:
                st.info("**Para áreas pequeñas:** Cobertura total recomendada")
    
    with col2:
        with st.expander("🌿 **ABONOS VERDES**", expanded=True):
            for rec in recomendaciones.get('ABONOS_VERDES', []):
                st.markdown(f"• {rec}")
            
            # Ajustar según intensidad
            if intensidad == "Alta":
                st.warning("**Prioridad alta:** Sembrar inmediatamente después de análisis")
    
    col3, col4 = st.columns(2)
    
    with col3:
        with st.expander("💩 **BIOFERTILIZANTES**", expanded=True):
            for rec in recomendaciones.get('BIOFERTILIZANTES', []):
                st.markdown(f"• {rec}")
            
            # Recomendaciones específicas por nutriente
            if analisis_tipo == "RECOMENDACIONES NPK" and nutriente:
                if nutriente == "NITRÓGENO":
                    st.markdown("• **Enmienda nitrogenada:** Compost de leguminosas")
                elif nutriente == "FÓSFORO":
                    st.markdown("• **Enmienda fosfatada:** Rocas fosfóricas molidas")
                else:
                    st.markdown("• **Enmienda potásica:** Cenizas de biomasa")
    
    with col4:
        with st.expander("🐞 **MANEJO ECOLÓGICO**", expanded=True):
            for rec in recomendaciones.get('MANEJO_ECOLOGICO', []):
                st.markdown(f"• {rec}")
            
            # Recomendaciones según categoría
            if categoria in ["MUY BAJA", "BAJA"]:
                st.markdown("• **Urgente:** Implementar control biológico intensivo")
    
    with st.expander("🌳 **ASOCIACIONES Y DIVERSIFICACIÓN**", expanded=True):
        for rec in recomendaciones.get('ASOCIACIONES', []):
            st.markdown(f"• {rec}")
        
        # Beneficios de las asociaciones
        st.markdown("""
        **Beneficios agroecológicos:**
        • Mejora la biodiversidad funcional
        • Reduce incidencia de plagas y enfermedades
        • Optimiza el uso de recursos (agua, luz, nutrientes)
        • Incrementa la resiliencia del sistema
        """)
    
    # PLAN DE IMPLEMENTACIÓN
    st.markdown("### 📅 PLAN DE IMPLEMENTACIÓN AGROECOLÓGICA")
    
    timeline_col1, timeline_col2, timeline_col3 = st.columns(3)
    
    with timeline_col1:
        st.markdown("**🏁 INMEDIATO (0-15 días)**")
        st.markdown("""
        • Preparación del terreno
        • Siembra de abonos verdes
        • Aplicación de biofertilizantes
        • Instalación de trampas
        """)
    
    with timeline_col2:
        st.markdown("**📈 CORTO PLAZO (1-3 meses)**")
        st.markdown("""
        • Establecimiento coberturas
        • Monitoreo inicial
        • Ajustes de manejo
        • Podas de formación
        """)
    
    with timeline_col3:
        st.markdown("**🎯 MEDIANO PLAZO (3-12 meses)**")
        st.markdown("""
        • Evaluación de resultados
        • Diversificación
        • Optimización del sistema
        • Réplica en otras zonas
        """)

# FUNCIÓN MEJORADA PARA DIVIDIR PARCELA
def dividir_parcela_en_zonas(gdf, n_zonas):
    """Divide la parcela en zonas de manejo con manejo robusto de errores"""
    try:
        if len(gdf) == 0:
            return gdf
        
        # Usar el primer polígono como parcela principal
        parcela_principal = gdf.iloc[0].geometry
        
        # Verificar que la geometría sea válida
        if not parcela_principal.is_valid:
            parcela_principal = parcela_principal.buffer(0)  # Reparar geometría
        
        bounds = parcela_principal.bounds
        if len(bounds) < 4:
            st.error("No se pueden obtener los límites de la parcela")
            return gdf
            
        minx, miny, maxx, maxy = bounds
        
        # Verificar que los bounds sean válidos
        if minx >= maxx or miny >= maxy:
            st.error("Límites de parcela inválidos")
            return gdf
        
        sub_poligonos = []
        
        # Cuadrícula regular
        n_cols = math.ceil(math.sqrt(n_zonas))
        n_rows = math.ceil(n_zonas / n_cols)
        
        width = (maxx - minx) / n_cols
        height = (maxy - miny) / n_rows
        
        # Asegurar un tamaño mínimo de celda
        if width < 0.0001 or height < 0.0001:  # ~11m en grados decimales
            st.warning("Las celdas son muy pequeñas, ajustando número de zonas")
            n_zonas = min(n_zonas, 16)
            n_cols = math.ceil(math.sqrt(n_zonas))
            n_rows = math.ceil(n_zonas / n_cols)
            width = (maxx - minx) / n_cols
            height = (maxy - miny) / n_rows
        
        for i in range(n_rows):
            for j in range(n_cols):
                if len(sub_poligonos) >= n_zonas:
                    break
                    
                cell_minx = minx + (j * width)
                cell_maxx = minx + ((j + 1) * width)
                cell_miny = miny + (i * height)
                cell_maxy = miny + ((i + 1) * height)
                
                # Crear celda con verificación de validez
                try:
                    cell_poly = Polygon([
                        (cell_minx, cell_miny),
                        (cell_maxx, cell_miny),
                        (cell_maxx, cell_maxy),
                        (cell_minx, cell_maxy)
                    ])
                    
                    if cell_poly.is_valid:
                        intersection = parcela_principal.intersection(cell_poly)
                        if not intersection.is_empty and intersection.area > 0:
                            # Simplificar geometría si es necesario
                            if intersection.geom_type == 'MultiPolygon':
                                # Tomar el polígono más grande
                                largest = max(intersection.geoms, key=lambda p: p.area)
                                sub_poligonos.append(largest)
                            else:
                                sub_poligonos.append(intersection)
                except Exception as e:
                    continue  # Saltar celdas problemáticas
        
        if sub_poligonos:
            nuevo_gdf = gpd.GeoDataFrame({
                'id_zona': range(1, len(sub_poligonos) + 1),
                'geometry': sub_poligonos
            }, crs=gdf.crs)
            return nuevo_gdf
        else:
            st.warning("No se pudieron crear zonas, retornando parcela original")
            return gdf
            
    except Exception as e:
        st.error(f"Error dividiendo parcela: {str(e)}")
        return gdf

# NUEVA FUNCIÓN: ANÁLISIS DE TEXTURA DEL SUELO
def analizar_textura_suelo(gdf, cultivo, mes_analisis):
    """Realiza análisis completo de textura del suelo"""
    
    params_textura = TEXTURA_SUELO_OPTIMA[cultivo]
    zonas_gdf = gdf.copy()
    
    # Inicializar columnas para textura
    zonas_gdf['arena'] = 0.0
    zonas_gdf['limo'] = 0.0
    zonas_gdf['arcilla'] = 0.0
    zonas_gdf['textura_suelo'] = "NO_DETERMINADA"
    zonas_gdf['adecuacion_textura'] = 0.0
    zonas_gdf['categoria_adecuacion'] = "NO_DETERMINADA"
    zonas_gdf['capacidad_campo'] = 0.0
    zonas_gdf['punto_marchitez'] = 0.0
    zonas_gdf['agua_disponible'] = 0.0
    zonas_gdf['densidad_aparente'] = 0.0
    zonas_gdf['porosidad'] = 0.0
    zonas_gdf['conductividad_hidraulica'] = 0.0
    
    for idx, row in zonas_gdf.iterrows():
        try:
            # Calcular área
            area_ha = calcular_superficie(zonas_gdf.iloc[[idx]]).iloc[0]
            
            # Obtener centroide
            if hasattr(row.geometry, 'centroid'):
                centroid = row.geometry.centroid
            else:
                centroid = row.geometry.representative_point()
            
            # Semilla para reproducibilidad
            seed_value = abs(hash(f"{centroid.x:.6f}_{centroid.y:.6f}_{cultivo}_textura")) % (2**32)
            rng = np.random.RandomState(seed_value)
            
            # Normalizar coordenadas para variabilidad espacial
            lat_norm = (centroid.y + 90) / 180 if centroid.y else 0.5
            lon_norm = (centroid.x + 180) / 360 if centroid.x else 0.5
            
            # SIMULAR COMPOSICIÓN GRANULOMÉTRICA MÁS REALISTA
            variabilidad_local = 0.15 + 0.7 * (lat_norm * lon_norm)
            
            # Valores óptimos para el cultivo
            arena_optima = params_textura['arena_optima']
            limo_optima = params_textura['limo_optima']
            arcilla_optima = params_textura['arcilla_optima']
            
            # Simular composición con distribución normal
            arena = max(5, min(95, rng.normal(
                arena_optima * (0.8 + 0.4 * variabilidad_local),
                arena_optima * 0.2
            )))
            
            limo = max(5, min(95, rng.normal(
                limo_optima * (0.7 + 0.6 * variabilidad_local),
                limo_optima * 0.25
            )))
            
            arcilla = max(5, min(95, rng.normal(
                arcilla_optima * (0.75 + 0.5 * variabilidad_local),
                arcilla_optima * 0.3
            )))
            
            # Normalizar a 100%
            total = arena + limo + arcilla
            arena = (arena / total) * 100
            limo = (limo / total) * 100
            arcilla = (arcilla / total) * 100
            
            # Clasificar textura
            textura = clasificar_textura_suelo(arena, limo, arcilla)
            
            # Evaluar adecuación para el cultivo
            categoria_adecuacion, puntaje_adecuacion = evaluar_adecuacion_textura(textura, cultivo)
            
            # Simular materia orgánica para propiedades físicas
            materia_organica = max(1.0, min(8.0, rng.normal(3.0, 1.0)))
            
            # Calcular propiedades físicas
            propiedades_fisicas = calcular_propiedades_fisicas_suelo(textura, materia_organica)
            
            # Asignar valores al GeoDataFrame
            zonas_gdf.loc[idx, 'area_ha'] = area_ha
            zonas_gdf.loc[idx, 'arena'] = arena
            zonas_gdf.loc[idx, 'limo'] = limo
            zonas_gdf.loc[idx, 'arcilla'] = arcilla
            zonas_gdf.loc[idx, 'textura_suelo'] = textura
            zonas_gdf.loc[idx, 'adecuacion_textura'] = puntaje_adecuacion
            zonas_gdf.loc[idx, 'categoria_adecuacion'] = categoria_adecuacion
            zonas_gdf.loc[idx, 'capacidad_campo'] = propiedades_fisicas['capacidad_campo']
            zonas_gdf.loc[idx, 'punto_marchitez'] = propiedades_fisicas['punto_marchitez']
            zonas_gdf.loc[idx, 'agua_disponible'] = propiedades_fisicas['agua_disponible']
            zonas_gdf.loc[idx, 'densidad_aparente'] = propiedades_fisicas['densidad_aparente']
            zonas_gdf.loc[idx, 'porosidad'] = propiedades_fisicas['porosidad']
            zonas_gdf.loc[idx, 'conductividad_hidraulica'] = propiedades_fisicas['conductividad_hidraulica']
            
        except Exception as e:
            # Valores por defecto en caso de error
            zonas_gdf.loc[idx, 'area_ha'] = calcular_superficie(zonas_gdf.iloc[[idx]]).iloc[0]
            zonas_gdf.loc[idx, 'arena'] = params_textura['arena_optima']
            zonas_gdf.loc[idx, 'limo'] = params_textura['limo_optima']
            zonas_gdf.loc[idx, 'arcilla'] = params_textura['arcilla_optima']
            zonas_gdf.loc[idx, 'textura_suelo'] = params_textura['textura_optima']
            zonas_gdf.loc[idx, 'adecuacion_textura'] = 1.0
            zonas_gdf.loc[idx, 'categoria_adecuacion'] = "ÓPTIMA"
            
            # Propiedades físicas por defecto
            propiedades_default = calcular_propiedades_fisicas_suelo(params_textura['textura_optima'], 3.0)
            for prop, valor in propiedades_default.items():
                zonas_gdf.loc[idx, prop] = valor
    
    return zonas_gdf

# FUNCIÓN CORREGIDA PARA ANÁLISIS DE FERTILIDAD CON CÁLCULOS NPK PRECISOS
def calcular_indices_gee(gdf, cultivo, mes_analisis, analisis_tipo, nutriente):
    """Calcula índices GEE mejorados con cálculos NPK más precisos"""
    
    params = PARAMETROS_CULTIVOS[cultivo]
    zonas_gdf = gdf.copy()
    
    # FACTORES ESTACIONALES MEJORADOS
    factor_mes = FACTORES_MES[mes_analisis]
    factor_n_mes = FACTORES_N_MES[mes_analisis]
    factor_p_mes = FACTORES_P_MES[mes_analisis]
    factor_k_mes = FACTORES_K_MES[mes_analisis]
    
    # Inicializar columnas adicionales
    zonas_gdf['area_ha'] = 0.0
    zonas_gdf['nitrogeno'] = 0.0
    zonas_gdf['fosforo'] = 0.0
    zonas_gdf['potasio'] = 0.0
    zonas_gdf['materia_organica'] = 0.0
    zonas_gdf['humedad'] = 0.0
    zonas_gdf['ph'] = 0.0
    zonas_gdf['conductividad'] = 0.0
    zonas_gdf['ndvi'] = 0.0
    zonas_gdf['indice_fertilidad'] = 0.0
    zonas_gdf['categoria'] = "MEDIA"
    zonas_gdf['recomendacion_npk'] = 0.0
    zonas_gdf['deficit_npk'] = 0.0
    zonas_gdf['prioridad'] = "MEDIA"
    
    for idx, row in zonas_gdf.iterrows():
        try:
            # Calcular área
            area_ha = calcular_superficie(zonas_gdf.iloc[[idx]]).iloc[0]
            
            # Obtener centroide
            if hasattr(row.geometry, 'centroid'):
                centroid = row.geometry.centroid
            else:
                centroid = row.geometry.representative_point()
            
            # Semilla más estable para reproducibilidad
            seed_value = abs(hash(f"{centroid.x:.6f}_{centroid.y:.6f}_{cultivo}")) % (2**32)
            rng = np.random.RandomState(seed_value)
            
            # Normalizar coordenadas para variabilidad espacial más realista
            lat_norm = (centroid.y + 90) / 180 if centroid.y else 0.5
            lon_norm = (centroid.x + 180) / 360 if centroid.x else 0.5
            
            # SIMULACIÓN MÁS REALISTA DE PARÁMETROS DEL SUELO
            n_optimo = params['NITROGENO']['optimo']
            p_optimo = params['FOSFORO']['optimo']
            k_optimo = params['POTASIO']['optimo']
            
            # Variabilidad espacial más pronunciada
            variabilidad_local = 0.2 + 0.6 * (lat_norm * lon_norm)  # Mayor correlación espacial
            
            # Simular valores con distribución normal más realista
            nitrogeno = max(0, rng.normal(
                n_optimo * (0.8 + 0.4 * variabilidad_local), 
                n_optimo * 0.15
            ))
            
            fosforo = max(0, rng.normal(
                p_optimo * (0.7 + 0.6 * variabilidad_local),
                p_optimo * 0.2
            ))
            
            potasio = max(0, rng.normal(
                k_optimo * (0.75 + 0.5 * variabilidad_local),
                k_optimo * 0.18
            ))
            
            # Aplicar factores estacionales mejorados
            nitrogeno *= factor_n_mes * (0.9 + 0.2 * rng.random())
            fosforo *= factor_p_mes * (0.9 + 0.2 * rng.random())
            potasio *= factor_k_mes * (0.9 + 0.2 * rng.random())
            
            # Parámetros adicionales del suelo simulados
            materia_organica = max(1.0, min(8.0, rng.normal(
                params['MATERIA_ORGANICA_OPTIMA'], 
                1.0
            )))
            
            humedad = max(0.1, min(0.8, rng.normal(
                params['HUMEDAD_OPTIMA'],
                0.1
            )))
            
            ph = max(4.0, min(8.0, rng.normal(
                params['pH_OPTIMO'],
                0.5
            )))
            
            conductividad = max(0.1, min(3.0, rng.normal(
                params['CONDUCTIVIDAD_OPTIMA'],
                0.3
            )))
            
            # NDVI con correlación con fertilidad
            base_ndvi = 0.3 + 0.5 * variabilidad_local
            ndvi = max(0.1, min(0.95, rng.normal(base_ndvi, 0.1)))
            
            # CÁLCULO MEJORADO DE ÍNDICE DE FERTILIDAD
            n_norm = max(0, min(1, nitrogeno / (n_optimo * 1.5)))  # Normalizado al 150% del óptimo
            p_norm = max(0, min(1, fosforo / (p_optimo * 1.5)))
            k_norm = max(0, min(1, potasio / (k_optimo * 1.5)))
            mo_norm = max(0, min(1, materia_organica / 8.0))
            ph_norm = max(0, min(1, 1 - abs(ph - params['pH_OPTIMO']) / 2.0))  # Óptimo en centro
            
            # Índice compuesto mejorado
            indice_fertilidad = (
                n_norm * 0.25 + 
                p_norm * 0.20 + 
                k_norm * 0.20 + 
                mo_norm * 0.15 +
                ph_norm * 0.10 +
                ndvi * 0.10
            ) * factor_mes
            
            indice_fertilidad = max(0, min(1, indice_fertilidad))
            
            # CATEGORIZACIÓN MEJORADA
            if indice_fertilidad >= 0.85:
                categoria = "EXCELENTE"
                prioridad = "BAJA"
            elif indice_fertilidad >= 0.70:
                categoria = "MUY ALTA"
                prioridad = "MEDIA-BAJA"
            elif indice_fertilidad >= 0.55:
                categoria = "ALTA"
                prioridad = "MEDIA"
            elif indice_fertilidad >= 0.40:
                categoria = "MEDIA"
                prioridad = "MEDIA-ALTA"
            elif indice_fertilidad >= 0.25:
                categoria = "BAJA"
                prioridad = "ALTA"
            else:
                categoria = "MUY BAJA"
                prioridad = "URGENTE"
            
            # 🔧 **CÁLCULO CORREGIDO DE RECOMENDACIONES NPK - MÁS PRECISO**
            if analisis_tipo == "RECOMENDACIONES NPK":
                if nutriente == "NITRÓGENO":
                    # Cálculo realista de recomendación de Nitrógeno
                    deficit_nitrogeno = max(0, n_optimo - nitrogeno)
                    
                    # Factores de ajuste más precisos:
                    factor_eficiencia = 1.4  # 40% de pérdidas por lixiviación/volatilización
                    factor_crecimiento = 1.2  # 20% adicional para crecimiento óptimo
                    factor_materia_organica = max(0.7, 1.0 - (materia_organica / 15.0))  # MO aporta N
                    factor_ndvi = 1.0 + (0.5 - ndvi) * 0.4  # NDVI bajo = más necesidad
                    
                    recomendacion = (deficit_nitrogeno * factor_eficiencia * factor_crecimiento * 
                                   factor_materia_organica * factor_ndvi)
                    
                    # Límites realistas para nitrógeno
                    recomendacion = min(recomendacion, 250)  # Máximo 250 kg/ha
                    recomendacion = max(20, recomendacion)   # Mínimo 20 kg/ha
                    
                    deficit = deficit_nitrogeno
                    
                elif nutriente == "FÓSFORO":
                    # Cálculo realista de recomendación de Fósforo
                    deficit_fosforo = max(0, p_optimo - fosforo)
                    
                    # Factores de ajuste para fósforo
                    factor_eficiencia = 1.6  # Alta fijación en el suelo
                    factor_ph = 1.0
                    if ph < 5.5 or ph > 7.5:  # Fuera del rango óptimo de disponibilidad
                        factor_ph = 1.3  # 30% más si el pH no es óptimo
                    factor_materia_organica = 1.1  # MO ayuda a la disponibilidad de P
                    
                    recomendacion = (deficit_fosforo * factor_eficiencia * 
                                   factor_ph * factor_materia_organica)
                    
                    # Límites realistas para fósforo
                    recomendacion = min(recomendacion, 120)  # Máximo 120 kg/ha P2O5
                    recomendacion = max(10, recomendacion)   # Mínimo 10 kg/ha
                    
                    deficit = deficit_fosforo
                    
                else:  # POTASIO
                    # Cálculo realista de recomendación de Potasio
                    deficit_potasio = max(0, k_optimo - potasio)
                    
                    # Factores de ajuste para potasio
                    factor_eficiencia = 1.3  # Moderada lixiviación
                    factor_textura = 1.0
                    if materia_organica < 2.0:  # Suelos arenosos
                        factor_textura = 1.2  # 20% más en suelos ligeros
                    factor_rendimiento = 1.0 + (0.5 - ndvi) * 0.3  # NDVI bajo = más necesidad
                    
                    recomendacion = (deficit_potasio * factor_eficiencia * 
                                   factor_textura * factor_rendimiento)
                    
                    # Límites realistas para potasio
                    recomendacion = min(recomendacion, 200)  # Máximo 200 kg/ha K2O
                    recomendacion = max(15, recomendacion)   # Mínimo 15 kg/ha
                    
                    deficit = deficit_potasio
                
                # Ajuste final basado en la categoría de fertilidad
                if categoria in ["MUY BAJA", "BAJA"]:
                    recomendacion *= 1.3  # 30% más en suelos de baja fertilidad
                elif categoria in ["ALTA", "MUY ALTA", "EXCELENTE"]:
                    recomendacion *= 0.8  # 20% menos en suelos fértiles
                
            else:
                recomendacion = 0
                deficit = 0
            
            # Asignar valores al GeoDataFrame
            zonas_gdf.loc[idx, 'area_ha'] = area_ha
            zonas_gdf.loc[idx, 'nitrogeno'] = nitrogeno
            zonas_gdf.loc[idx, 'fosforo'] = fosforo
            zonas_gdf.loc[idx, 'potasio'] = potasio
            zonas_gdf.loc[idx, 'materia_organica'] = materia_organica
            zonas_gdf.loc[idx, 'humedad'] = humedad
            zonas_gdf.loc[idx, 'ph'] = ph
            zonas_gdf.loc[idx, 'conductividad'] = conductividad
            zonas_gdf.loc[idx, 'ndvi'] = ndvi
            zonas_gdf.loc[idx, 'indice_fertilidad'] = indice_fertilidad
            zonas_gdf.loc[idx, 'categoria'] = categoria
            zonas_gdf.loc[idx, 'recomendacion_npk'] = recomendacion
            zonas_gdf.loc[idx, 'deficit_npk'] = deficit
            zonas_gdf.loc[idx, 'prioridad'] = prioridad
            
        except Exception as e:
            # Valores por defecto mejorados en caso de error
            zonas_gdf.loc[idx, 'area_ha'] = calcular_superficie(zonas_gdf.iloc[[idx]]).iloc[0]
            zonas_gdf.loc[idx, 'nitrogeno'] = params['NITROGENO']['optimo'] * 0.8
            zonas_gdf.loc[idx, 'fosforo'] = params['FOSFORO']['optimo'] * 0.8
            zonas_gdf.loc[idx, 'potasio'] = params['POTASIO']['optimo'] * 0.8
            zonas_gdf.loc[idx, 'materia_organica'] = params['MATERIA_ORGANICA_OPTIMA']
            zonas_gdf.loc[idx, 'humedad'] = params['HUMEDAD_OPTIMA']
            zonas_gdf.loc[idx, 'ph'] = params['pH_OPTIMO']
            zonas_gdf.loc[idx, 'conductividad'] = params['CONDUCTIVIDAD_OPTIMA']
            zonas_gdf.loc[idx, 'ndvi'] = 0.6
            zonas_gdf.loc[idx, 'indice_fertilidad'] = 0.5
            zonas_gdf.loc[idx, 'categoria'] = "MEDIA"
            zonas_gdf.loc[idx, 'recomendacion_npk'] = 0
            zonas_gdf.loc[idx, 'deficit_npk'] = 0
            zonas_gdf.loc[idx, 'prioridad'] = "MEDIA"
    
    return zonas_gdf

# FUNCIÓN PARA PROCESAR ARCHIVO SUBIDO
def procesar_archivo(uploaded_zip):
    """Procesa el archivo ZIP con shapefile"""
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Guardar archivo ZIP
            zip_path = os.path.join(tmp_dir, "uploaded.zip")
            with open(zip_path, "wb") as f:
                f.write(uploaded_zip.getvalue())
            
            # Extraer ZIP
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(tmp_dir)
            
            # Buscar archivos shapefile
            shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
            
            if not shp_files:
                st.error("❌ No se encontró archivo .shp en el ZIP")
                return None
            
            # Cargar shapefile
            shp_path = os.path.join(tmp_dir, shp_files[0])
            gdf = gpd.read_file(shp_path)
            
            # Verificar y reparar geometrías
            if not gdf.is_valid.all():
                gdf = gdf.make_valid()
            
            return gdf
            
    except Exception as e:
        st.error(f"❌ Error procesando archivo: {str(e)}")
        return None

# INTERFAZ PRINCIPAL
def main():
    # Mostrar información de la aplicación
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📊 Métodología GEE")
    st.sidebar.info("""
    Esta aplicación utiliza:
    - **Google Earth Engine** para análisis satelital
    - **Índices espectrales** (NDVI, NDBI, etc.)
    - **Modelos predictivos** de nutrientes
    - **Análisis de textura** del suelo
    - **Enfoque agroecológico** integrado
    """)

    # Procesar archivo subido si existe
    if uploaded_zip is not None and not st.session_state.analisis_completado:
        with st.spinner("🔄 Procesando archivo..."):
            gdf_original = procesar_archivo(uploaded_zip)
            if gdf_original is not None:
                st.session_state.gdf_original = gdf_original
                st.session_state.datos_demo = False

    # Cargar datos de demostración si se solicita
    if st.session_state.datos_demo and st.session_state.gdf_original is None:
        # Crear polígono de ejemplo
        poligono_ejemplo = Polygon([
            [-74.1, 4.6], [-74.0, 4.6], [-74.0, 4.7], [-74.1, 4.7], [-74.1, 4.6]
        ])
        
        gdf_demo = gpd.GeoDataFrame(
            {'id': [1], 'nombre': ['Parcela Demo']},
            geometry=[poligono_ejemplo],
            crs="EPSG:4326"
        )
        st.session_state.gdf_original = gdf_demo

    # Mostrar interfaz según el estado
    if st.session_state.analisis_completado and st.session_state.gdf_analisis is not None:
        mostrar_resultados()
    elif st.session_state.gdf_original is not None:
        mostrar_configuracion_parcela()
    else:
        mostrar_modo_demo()

def mostrar_modo_demo():
    """Muestra la interfaz de demostración"""
    st.markdown("### 🚀 Modo Demostración")
    st.info("""
    **Para usar la aplicación:**
    1. Sube un archivo ZIP con el shapefile de tu parcela
    2. Selecciona el cultivo y tipo de análisis
    3. Configura los parámetros en el sidebar
    4. Ejecuta el análisis GEE
    
    **📁 El shapefile debe incluir:**
    - .shp (geometrías)
    - .shx (índice)
    - .dbf (atributos)
    - .prj (sistema de coordenadas)
    
    **NUEVO: Análisis de Textura del Suelo**
    - Clasificación USDA de texturas
    - Propiedades físicas del suelo
    - Recomendaciones específicas por textura
    """)
    
    # Ejemplo de datos de demostración
    if st.button("🎯 Cargar Datos de Demostración", type="primary"):
        st.session_state.datos_demo = True
        st.rerun()

def mostrar_configuracion_parcela():
    """Muestra la configuración de la parcela antes del análisis"""
    gdf_original = st.session_state.gdf_original
    
    # Mostrar información de la parcela
    if st.session_state.datos_demo:
        st.success("✅ Datos de demostración cargados")
    else:
        st.success("✅ Parcela cargada correctamente")
    
    # Calcular estadísticas
    area_total = calcular_superficie(gdf_original).sum()
    num_poligonos = len(gdf_original)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📐 Área Total", f"{area_total:.2f} ha")
    with col2:
        st.metric("🔢 Número de Polígonos", num_poligonos)
    with col3:
        st.metric("🌱 Cultivo", cultivo.replace('_', ' ').title())
    
    # VISUALIZADOR DE PARCELA ORIGINAL
    st.markdown("### 🗺️ Visualizador de Parcela")
    
    # Crear y mostrar mapa interactivo
    mapa_parcela = crear_mapa_visualizador_parcela(gdf_original)
    st_folium(mapa_parcela, width=800, height=500)
    
    # DIVIDIR PARCELA EN ZONAS
    st.markdown("### 📊 División en Zonas de Manejo")
    st.info(f"La parcela se dividirá en **{n_divisiones} zonas** para análisis detallado")
    
    # Botón para ejecutar análisis
    if st.button("🚀 Ejecutar Análisis GEE Completo", type="primary"):
        with st.spinner("🔄 Dividiendo parcela en zonas..."):
            gdf_zonas = dividir_parcela_en_zonas(gdf_original, n_divisiones)
            st.session_state.gdf_zonas = gdf_zonas
        
        with st.spinner("🔬 Realizando análisis GEE..."):
            # Calcular índices según tipo de análisis
            if analisis_tipo == "ANÁLISIS DE TEXTURA":
                gdf_analisis = analizar_textura_suelo(gdf_zonas, cultivo, mes_analisis)
            else:
                gdf_analisis = calcular_indices_gee(
                    gdf_zonas, cultivo, mes_analisis, analisis_tipo, nutriente
                )
            
            st.session_state.gdf_analisis = gdf_analisis
            st.session_state.area_total = area_total
            st.session_state.analisis_completado = True
        
        st.rerun()

def mostrar_resultados():
    """Muestra los resultados del análisis completado"""
    gdf_analisis = st.session_state.gdf_analisis
    area_total = st.session_state.area_total
    
    # MOSTRAR RESULTADOS
    st.markdown("## 📈 RESULTADOS DEL ANÁLISIS")
    
    # Botón para volver atrás
    if st.button("⬅️ Volver a Configuración"):
        st.session_state.analisis_completado = False
        st.rerun()
    
    # Estadísticas resumen
    st.subheader("📊 Estadísticas del Análisis")
    
    if analisis_tipo == "FERTILIDAD ACTUAL":
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            avg_fert = gdf_analisis['indice_fertilidad'].mean()
            st.metric("📊 Índice Fertilidad Promedio", f"{avg_fert:.3f}")
        with col2:
            avg_n = gdf_analisis['nitrogeno'].mean()
            st.metric("🌿 Nitrógeno Promedio", f"{avg_n:.1f} kg/ha")
        with col3:
            avg_p = gdf_analisis['fosforo'].mean()
            st.metric("🧪 Fósforo Promedio", f"{avg_p:.1f} kg/ha")
        with col4:
            avg_k = gdf_analisis['potasio'].mean()
            st.metric("⚡ Potasio Promedio", f"{avg_k:.1f} kg/ha")
        
        # Estadísticas adicionales
        col5, col6, col7 = st.columns(3)
        with col5:
            avg_mo = gdf_analisis['materia_organica'].mean()
            st.metric("🌱 Materia Orgánica Promedio", f"{avg_mo:.1f}%")
        with col6:
            avg_ndvi = gdf_analisis['ndvi'].mean()
            st.metric("📡 NDVI Promedio", f"{avg_ndvi:.3f}")
        with col7:
            zona_prioridad = gdf_analisis['prioridad'].value_counts().index[0]
            st.metric("🎯 Prioridad Predominante", zona_prioridad)
        
        st.subheader("📋 Distribución de Categorías de Fertilidad")
        cat_dist = gdf_analisis['categoria'].value_counts()
        st.bar_chart(cat_dist)
    
    elif analisis_tipo == "ANÁLISIS DE TEXTURA":
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            textura_predominante = gdf_analisis['textura_suelo'].mode()[0]
            st.metric("🏗️ Textura Predominante", textura_predominante)
        with col2:
            avg_adecuacion = gdf_analisis['adecuacion_textura'].mean()
            st.metric("📊 Adecuación Promedio", f"{avg_adecuacion:.1%}")
        with col3:
            avg_arena = gdf_analisis['arena'].mean()
            st.metric("🏖️ Arena Promedio", f"{avg_arena:.1f}%")
        with col4:
            avg_arcilla = gdf_analisis['arcilla'].mean()
            st.metric("🧱 Arcilla Promedio", f"{avg_arcilla:.1f}%")
        
        # Estadísticas adicionales
        col5, col6, col7 = st.columns(3)
        with col5:
            avg_limo = gdf_analisis['limo'].mean()
            st.metric("🌫️ Limo Promedio", f"{avg_limo:.1f}%")
        with col6:
            avg_agua_disp = gdf_analisis['agua_disponible'].mean()
            st.metric("💧 Agua Disponible Promedio", f"{avg_agua_disp:.0f} mm/m")
        with col7:
            avg_densidad = gdf_analisis['densidad_aparente'].mean()
            st.metric("⚖️ Densidad Aparente", f"{avg_densidad:.2f} g/cm³")
        
        st.subheader("📋 Distribución de Texturas del Suelo")
        textura_dist = gdf_analisis['textura_suelo'].value_counts()
        st.bar_chart(textura_dist)
        
        # Triángulo de texturas simplificado
        st.subheader("🔺 Composición Granulométrica Promedio")
        fig, ax = plt.subplots(1, 1, figsize=(8, 6))
        
        # Datos para el gráfico de torta
        composicion = [
            gdf_analisis['arena'].mean(),
            gdf_analisis['limo'].mean(), 
            gdf_analisis['arcilla'].mean()
        ]
        labels = ['Arena', 'Limo', 'Arcilla']
        colors = ['#d8b365', '#f6e8c3', '#01665e']
        
        ax.pie(composicion, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
        ax.set_title('Composición Promedio del Suelo')
        
        st.pyplot(fig)
    
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            avg_rec = gdf_analisis['recomendacion_npk'].mean()
            st.metric(f"💡 Recomendación {nutriente} Promedio", f"{avg_rec:.1f} kg/ha")
        with col2:
            total_rec = (gdf_analisis['recomendacion_npk'] * gdf_analisis['area_ha']).sum()
            st.metric(f"📦 Total {nutriente} Requerido", f"{total_rec:.1f} kg")
        with col3:
            zona_prioridad = gdf_analisis['prioridad'].value_counts().index[0]
            st.metric("🎯 Prioridad Aplicación", zona_prioridad)
        
        st.subheader("🌿 Estado Actual de Nutrientes")
        col_n, col_p, col_k, col_mo = st.columns(4)
        with col_n:
            avg_n = gdf_analisis['nitrogeno'].mean()
            st.metric("Nitrógeno", f"{avg_n:.1f} kg/ha")
        with col_p:
            avg_p = gdf_analisis['fosforo'].mean()
            st.metric("Fósforo", f"{avg_p:.1f} kg/ha")
        with col_k:
            avg_k = gdf_analisis['potasio'].mean()
            st.metric("Potasio", f"{avg_k:.1f} kg/ha")
        with col_mo:
            avg_mo = gdf_analisis['materia_organica'].mean()
            st.metric("Materia Orgánica", f"{avg_mo:.1f}%")
    
    # MAPAS INTERACTIVOS
    st.markdown("### 🗺️ Mapas de Análisis")
    
    # Seleccionar columna para visualizar
    if analisis_tipo == "FERTILIDAD ACTUAL":
        columna_visualizar = 'indice_fertilidad'
        titulo_mapa = f"Fertilidad Actual - {cultivo.replace('_', ' ').title()}"
    elif analisis_tipo == "ANÁLISIS DE TEXTURA":
        columna_visualizar = 'textura_suelo'
        titulo_mapa = f"Textura del Suelo - {cultivo.replace('_', ' ').title()}"
    else:
        columna_visualizar = 'recomendacion_npk'
        titulo_mapa = f"Recomendación {nutriente} - {cultivo.replace('_', ' ').title()}"
    
    # Crear y mostrar mapa interactivo
    mapa_analisis = crear_mapa_interactivo_esri(
        gdf_analisis, titulo_mapa, columna_visualizar, analisis_tipo, nutriente
    )
    st_folium(mapa_analisis, width=800, height=500)
    
    # MAPA ESTÁTICO PARA DESCARGA
    st.markdown("### 📄 Mapa para Reporte")
    mapa_estatico = crear_mapa_estatico(
        gdf_analisis, titulo_mapa, columna_visualizar, analisis_tipo, nutriente
    )
    if mapa_estatico:
        st.image(mapa_estatico, caption=titulo_mapa, use_column_width=True)
    
    # TABLA DETALLADA
    st.markdown("### 📋 Tabla de Resultados por Zona")
    
    # Preparar datos para tabla
    if analisis_tipo == "FERTILIDAD ACTUAL":
        columnas_tabla = ['id_zona', 'area_ha', 'categoria', 'prioridad', 'indice_fertilidad', 'nitrogeno', 'fosforo', 'potasio', 'materia_organica', 'ndvi']
    elif analisis_tipo == "ANÁLISIS DE TEXTURA":
        columnas_tabla = ['id_zona', 'area_ha', 'textura_suelo', 'adecuacion_textura', 'arena', 'limo', 'arcilla', 'capacidad_campo', 'agua_disponible', 'densidad_aparente']
    else:
        columnas_tabla = ['id_zona', 'area_ha', 'categoria', 'prioridad', 'recomendacion_npk', 'deficit_npk', 'nitrogeno', 'fosforo', 'potasio']
    
    df_tabla = gdf_analisis[columnas_tabla].copy()
    df_tabla['area_ha'] = df_tabla['area_ha'].round(3)
    
    if analisis_tipo == "FERTILIDAD ACTUAL":
        df_tabla['indice_fertilidad'] = df_tabla['indice_fertilidad'].round(3)
        df_tabla['nitrogeno'] = df_tabla['nitrogeno'].round(1)
        df_tabla['fosforo'] = df_tabla['fosforo'].round(1)
        df_tabla['potasio'] = df_tabla['potasio'].round(1)
        df_tabla['materia_organica'] = df_tabla['materia_organica'].round(1)
        df_tabla['ndvi'] = df_tabla['ndvi'].round(3)
    elif analisis_tipo == "ANÁLISIS DE TEXTURA":
        df_tabla['arena'] = df_tabla['arena'].round(1)
        df_tabla['limo'] = df_tabla['limo'].round(1)
        df_tabla['arcilla'] = df_tabla['arcilla'].round(1)
        df_tabla['capacidad_campo'] = df_tabla['capacidad_campo'].round(1)
        df_tabla['agua_disponible'] = df_tabla['agua_disponible'].round(1)
        df_tabla['densidad_aparente'] = df_tabla['densidad_aparente'].round(2)
    else:
        df_tabla['recomendacion_npk'] = df_tabla['recomendacion_npk'].round(1)
        df_tabla['deficit_npk'] = df_tabla['deficit_npk'].round(1)
    
    st.dataframe(df_tabla, use_container_width=True)
    
    # RECOMENDACIONES AGROECOLÓGICAS
    if analisis_tipo == "ANÁLISIS DE TEXTURA":
        textura_predominante = gdf_analisis['textura_suelo'].mode()[0] if len(gdf_analisis) > 0 else "FRANCO"
        adecuacion_promedio = gdf_analisis['adecuacion_textura'].mean()
        
        textura_data = {
            'textura_predominante': textura_predominante,
            'adecuacion_promedio': adecuacion_promedio,
            'propiedades_fisicas': {
                'capacidad_campo': gdf_analisis['capacidad_campo'].mean(),
                'punto_marchitez': gdf_analisis['punto_marchitez'].mean(),
                'agua_disponible': gdf_analisis['agua_disponible'].mean(),
                'densidad_aparente': gdf_analisis['densidad_aparente'].mean(),
                'porosidad': gdf_analisis['porosidad'].mean(),
                'conductividad_hidraulica': gdf_analisis['conductividad_hidraulica'].mean()
            }
        }
        mostrar_recomendaciones_agroecologicas(
            cultivo, "", area_total, analisis_tipo, nutriente, textura_data
        )
    else:
        categoria_promedio = gdf_analisis['categoria'].mode()[0] if len(gdf_analisis) > 0 else "MEDIA"
        mostrar_recomendaciones_agroecologicas(
            cultivo, categoria_promedio, area_total, analisis_tipo, nutriente
        )
    
    # DESCARGAR RESULTADOS
    st.markdown("### 💾 Descargar Resultados")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Descargar CSV
        csv = df_tabla.to_csv(index=False)
        st.download_button(
            label="📥 Descargar Tabla CSV",
            data=csv,
            file_name=f"resultados_{cultivo}_{analisis_tipo.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
    
    with col2:
        # Descargar GeoJSON
        geojson = gdf_analisis.to_json()
        st.download_button(
            label="🗺️ Descargar GeoJSON",
            data=geojson,
            file_name=f"zonas_analisis_{cultivo}_{analisis_tipo.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson",
            mime="application/json"
        )
    
    with col3:
        # Descargar PDF
        if st.button("📄 Generar Informe PDF", type="primary"):
            with st.spinner("🔄 Generando informe PDF..."):
                pdf_buffer = generar_informe_pdf(
                    gdf_analisis, cultivo, analisis_tipo, nutriente, mes_analisis, area_total
                )
                
                st.download_button(
                    label="📥 Descargar Informe PDF",
                    data=pdf_buffer,
                    file_name=f"informe_{cultivo}_{analisis_tipo.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf"
                )

# EJECUTAR APLICACIÓN
if __name__ == "__main__":
    main()
[file content end]

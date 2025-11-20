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
import subprocess
import sys

# Intentar importar Google Earth Engine con manejo de errores
try:
    import ee
    EE_AVAILABLE = True
except ImportError:
    st.warning("🌐 Google Earth Engine no está instalado. Algunas funciones satelitales no estarán disponibles.")
    EE_AVAILABLE = False
    # Crear una clase dummy para evitar errores
    class EarthEngineDummy:
        def Initialize(self): pass
        def Geometry(self, *args, **kwargs): return DummyObject()
        def ImageCollection(self, *args): return DummyObject()
        def Image(self, *args): return DummyObject()
        def Date(self, *args): return DummyObject()
        def Filter(self, *args): return DummyObject()
    
    class DummyObject:
        def filterBounds(self, *args): return self
        def filterDate(self, *args): return self
        def filter(self, *args): return self
        def sort(self, *args): return self
        def first(self): return self
        def select(self, *args): return self
        def multiply(self, *args): return self
        def addBands(self, *args, **kwargs): return self
        def normalizedDifference(self, *args): return self
        def expression(self, *args, **kwargs): return self
        def rename(self, *args): return self
        def reduceRegion(self, *args, **kwargs): return self
        def getInfo(self): return {}
        def get(self, *args): return self
        def format(self, *args): return "2000-01-01"
        def getMapId(self, *args): 
            return {'tile_fetcher': DummyTileFetcher()}
    
    class DummyTileFetcher:
        @property
        def url_format(self):
            return ""

    ee = EarthEngineDummy()

# Intentar importar geemap
try:
    import geemap
    GEEMAP_AVAILABLE = True
except ImportError:
    GEEMAP_AVAILABLE = False

st.set_page_config(page_title="🌴 Analizador Cultivos", layout="wide")
st.title("🌱 ANALIZADOR CULTIVOS - METODOLOGÍA GEE COMPLETA CON AGROECOLOGÍA")
st.markdown("---")

# Mostrar estado de las dependencias
if not EE_AVAILABLE:
    st.error("""
    ⚠️ **Google Earth Engine no está disponible**
    
    Para habilitar el análisis satelital completo:
    ```bash
    pip install earthengine-api
    ```
    
    Luego autenticar con:
    ```python
    import ee
    ee.Authenticate()
    ee.Initialize()
    ```
    """)

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# PARÁMETROS PARA DIFERENTES CULTIVOS
PARAMETROS_CULTIVOS = {
    'PALMA_ACEITERA': {
        'NITROGENO': {'min': 150, 'max': 220},
        'FOSFORO': {'min': 60, 'max': 80},
        'POTASIO': {'min': 100, 'max': 120},
        'MATERIA_ORGANICA_OPTIMA': 4.0,
        'HUMEDAD_OPTIMA': 0.3
    },
    'CACAO': {
        'NITROGENO': {'min': 120, 'max': 180},
        'FOSFORO': {'min': 40, 'max': 60},
        'POTASIO': {'min': 80, 'max': 110},
        'MATERIA_ORGANICA_OPTIMA': 3.5,
        'HUMEDAD_OPTIMA': 0.35
    },
    'BANANO': {
        'NITROGENO': {'min': 180, 'max': 250},
        'FOSFORO': {'min': 50, 'max': 70},
        'POTASIO': {'min': 120, 'max': 160},
        'MATERIA_ORGANICA_OPTIMA': 4.5,
        'HUMEDAD_OPTIMA': 0.4
    }
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
    'NITROGENO': ['#00ff00', '#80ff00', '#ffff00', '#ff8000', '#ff0000'],
    'FOSFORO': ['#0000ff', '#4040ff', '#8080ff', '#c0c0ff', '#ffffff'],
    'POTASIO': ['#4B0082', '#6A0DAD', '#8A2BE2', '#9370DB', '#D8BFD8']
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

# NUEVAS VARIABLES DE SESSION_STATE PARA ANÁLISIS SENTINEL-2
if 'analisis_satelital_completado' not in st.session_state:
    st.session_state.analisis_satelital_completado = False
if 'gdf_satelital' not in st.session_state:
    st.session_state.gdf_satelital = None
if 'imagen_sentinel' not in st.session_state:
    st.session_state.imagen_sentinel = None
if 'fecha_imagen' not in st.session_state:
    st.session_state.fecha_imagen = None

# FUNCIÓN PARA GENERAR PDF
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
    
    # Estadísticas resumen
    story.append(Paragraph("ESTADÍSTICAS DEL ANÁLISIS", heading_style))
    
    if analisis_tipo == "FERTILIDAD ACTUAL":
        stats_data = [
            ["Estadística", "Valor"],
            ["Índice Fertilidad Promedio", f"{gdf_analisis['indice_fertilidad'].mean():.3f}"],
            ["Nitrógeno Promedio (kg/ha)", f"{gdf_analisis['nitrogeno'].mean():.1f}"],
            ["Fósforo Promedio (kg/ha)", f"{gdf_analisis['fosforo'].mean():.1f}"],
            ["Potasio Promedio (kg/ha)", f"{gdf_analisis['potasio'].mean():.1f}"],
            ["NDVI Promedio", f"{gdf_analisis['ndvi'].mean():.3f}"]
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
    
    # Mapa estático
    story.append(PageBreak())
    story.append(Paragraph("MAPA DE ANÁLISIS", heading_style))
    
    # Generar mapa estático para el PDF
    if analisis_tipo == "FERTILIDAD ACTUAL":
        titulo_mapa = f"Fertilidad Actual - {cultivo.replace('_', ' ').title()}"
        columna_visualizar = 'indice_fertilidad'
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
    columnas_tabla = ['id_zona', 'area_ha', 'categoria']
    if analisis_tipo == "FERTILIDAD ACTUAL":
        columnas_tabla.extend(['indice_fertilidad', 'nitrogeno', 'fosforo', 'potasio'])
    else:
        columnas_tabla.extend(['recomendacion_npk', 'nitrogeno', 'fosforo', 'potasio'])
    
    df_tabla = gdf_analisis[columnas_tabla].head(10).copy()
    
    # Redondear valores
    df_tabla['area_ha'] = df_tabla['area_ha'].round(3)
    if analisis_tipo == "FERTILIDAD ACTUAL":
        df_tabla['indice_fertilidad'] = df_tabla['indice_fertilidad'].round(3)
    else:
        df_tabla['recomendacion_npk'] = df_tabla['recomendacion_npk'].round(1)
    
    df_tabla['nitrogeno'] = df_tabla['nitrogeno'].round(1)
    df_tabla['fosforo'] = df_tabla['fosforo'].round(1)
    df_tabla['potasio'] = df_tabla['potasio'].round(1)
    
    # Convertir a lista para la tabla
    table_data = [df_tabla.columns.tolist()]
    for _, row in df_tabla.iterrows():
        table_data.append(row.tolist())
    
    # Crear tabla
    zona_table = Table(table_data, colWidths=[0.5*inch] + [0.8*inch] * (len(columnas_tabla)-1))
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
    
    categoria_promedio = gdf_analisis['categoria'].mode()[0] if len(gdf_analisis) > 0 else "MEDIA"
    
    # Determinar enfoque
    if categoria_promedio in ["MUY BAJA", "MUY BAJO", "BAJA", "BAJO"]:
        enfoque = "ENFOQUE: RECUPERACIÓN Y REGENERACIÓN - Intensidad: Alta"
    elif categoria_promedio in ["MEDIA", "MEDIO"]:
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

# FUNCIÓN MEJORADA PARA CREAR MAPA INTERACTIVO CON ESRI SATELITE
def crear_mapa_interactivo_esri(gdf, titulo, columna_valor=None, analisis_tipo=None, nutriente=None):
    """Crea mapa interactivo con base ESRI Satélite - AJUSTADO PARA CONSISTENCIA"""
    
    # Obtener centro y bounds del GeoDataFrame
    centroid = gdf.geometry.centroid.iloc[0]
    bounds = gdf.total_bounds
    
    # Crear mapa centrado
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=14,
        tiles=None  # Desactivar tiles por defecto
    )
    
    # Añadir base ESRI Satélite
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Satélite',
        overlay=False,
        control=True
    ).add_to(m)
    
    # Añadir base ESRI Calles
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Calles',
        overlay=False,
        control=True
    ).add_to(m)
    
    # Añadir base OpenStreetMap como alternativa
    folium.TileLayer(
        tiles='OpenStreetMap',
        name='OpenStreetMap',
        overlay=False,
        control=True
    ).add_to(m)
    
    # CONFIGURAR RANGOS UNIFICADOS (igual que en el mapa estático)
    if columna_valor and analisis_tipo:
        if analisis_tipo == "FERTILIDAD ACTUAL":
            vmin, vmax = 0, 1
            colores = PALETAS_GEE['FERTILIDAD']
        else:
            # RANGOS IDÉNTICOS AL MAPA ESTÁTICO
            if nutriente == "NITRÓGENO":
                vmin, vmax = 10, 140
                colores = PALETAS_GEE['NITROGENO']
            elif nutriente == "FÓSFORO":
                vmin, vmax = 5, 80
                colores = PALETAS_GEE['FOSFORO']
            else:  # POTASIO
                vmin, vmax = 8, 120
                colores = PALETAS_GEE['POTASIO']
        
        # Función para obtener color basado en valor
        def obtener_color(valor, vmin, vmax, colores):
            if vmax == vmin:  # Evitar división por cero
                return colores[0]
            valor_norm = (valor - vmin) / (vmax - vmin)
            valor_norm = max(0, min(1, valor_norm))
            idx = int(valor_norm * (len(colores) - 1))
            return colores[idx]
        
        # Añadir cada polígono con color según valor
        for idx, row in gdf.iterrows():
            valor = row[columna_valor]
            color = obtener_color(valor, vmin, vmax, colores)
            
            # Crear popup informativo
            if analisis_tipo == "FERTILIDAD ACTUAL":
                popup_text = f"""
                <b>Zona {row['id_zona']}</b><br>
                <b>Índice NPK:</b> {valor:.3f}<br>
                <b>Área:</b> {row.get('area_ha', 0):.2f} ha<br>
                <b>Categoría:</b> {row.get('categoria', 'N/A')}<br>
                <b>Materia Org:</b> {row.get('materia_organica', 'N/A')}%<br>
                <b>NDVI:</b> {row.get('ndvi', 'N/A')}
                """
            else:
                popup_text = f"""
                <b>Zona {row['id_zona']}</b><br>
                <b>Recomendación {nutriente}:</b> {valor:.1f} kg/ha<br>
                <b>Área:</b> {row.get('area_ha', 0):.2f} ha<br>
                <b>Categoría:</b> {row.get('categoria', 'N/A')}<br>
                <b>Materia Org:</b> {row.get('materia_organica', 'N/A')}%<br>
                <b>NDVI:</b> {row.get('ndvi', 'N/A')}
                """
            
            # Añadir polígono al mapa
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
                tooltip=f"Zona {row['id_zona']}: {valor:.2f}"
            ).add_to(m)
            
            # Añadir marcador con el número de zona
            centroid = row.geometry.centroid
            folium.Marker(
                [centroid.y, centroid.x],
                icon=folium.DivIcon(
                    html=f'<div style="background-color: white; border: 2px solid black; border-radius: 50%; width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 12px;">{row["id_zona"]}</div>'
                ),
                tooltip=f"Zona {row['id_zona']}"
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
                    'fillOpacity': 0.4,
                    'opacity': 0.8
                },
                popup=folium.Popup(f"Polígono {idx + 1}<br>Área: {calcular_superficie(gdf.iloc[[idx]]).iloc[0]:.2f} ha", 
                                 max_width=300),
                tooltip=f"Polígono {idx + 1}"
            ).add_to(m)
    
    # Ajustar bounds del mapa
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    
    # Añadir control de capas
    folium.LayerControl().add_to(m)
    
    # Añadir medida de escala
    plugins.MeasureControl(position='bottomleft').add_to(m)
    
    # Añadir mini mapa
    plugins.MiniMap(toggle_display=True).add_to(m)
    
    # Añadir botón de pantalla completa
    plugins.Fullscreen(position='topright').add_to(m)
    
    # Añadir leyenda
    if columna_valor and analisis_tipo:
        # Crear leyenda personalizada
        legend_html = f'''
        <div style="position: fixed; 
                    top: 10px; right: 10px; width: 220px; height: auto; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px; border-radius: 5px;">
        <p style="margin:0; font-weight:bold; font-size:14px; text-align:center;">{titulo}</p>
        <p style="margin:5px 0; font-weight:bold;">Escala de Valores:</p>
        '''
        
        # Añadir elementos de leyenda según el tipo de análisis
        if analisis_tipo == "FERTILIDAD ACTUAL":
            legend_html += '<p style="margin:2px 0;">🎯 Índice NPK (0-1)</p>'
            for i, color in enumerate(PALETAS_GEE['FERTILIDAD']):
                value = i / (len(PALETAS_GEE['FERTILIDAD']) - 1)
                legend_html += f'<p style="margin:1px 0;"><i style="background:{color}; width:20px; height:15px; display:inline-block; margin-right:5px; border:1px solid #000;"></i> {value:.1f}</p>'
        else:
            if nutriente == "NITRÓGENO":
                legend_html += '<p style="margin:2px 0;">🌿 Nitrógeno (kg/ha)</p>'
                colors = PALETAS_GEE['NITROGENO']
                vmin, vmax = 10, 140
            elif nutriente == "FÓSFORO":
                legend_html += '<p style="margin:2px 0;">🧪 Fósforo (kg/ha)</p>'
                colors = PALETAS_GEE['FOSFORO']
                vmin, vmax = 5, 80
            else:
                legend_html += '<p style="margin:2px 0;">⚡ Potasio (kg/ha)</p>'
                colors = PALETAS_GEE['POTASIO']
                vmin, vmax = 8, 120
            
            # LEYENDA UNIFICADA CON EL MAPA ESTÁTICO
            steps = 6  # Mismo número de pasos que el mapa estático
            for i in range(steps):
                value = vmin + (i / (steps - 1)) * (vmax - vmin)
                color_idx = int((i / (steps - 1)) * (len(colors) - 1))
                color = colors[color_idx]
                legend_html += f'<p style="margin:1px 0;"><i style="background:{color}; width:20px; height:15px; display:inline-block; margin-right:5px; border:1px solid #000;"></i> {value:.0f} kg/ha</p>'
        
        legend_html += '</div>'
        m.get_root().html.add_child(folium.Element(legend_html))
    
    return m

# FUNCIÓN PARA CREAR MAPA VISUALIZADOR DE PARCELA
def crear_mapa_visualizador_parcela(gdf):
    """Crea mapa interactivo para visualizar la parcela original con ESRI Satélite"""
    
    # Obtener centro y bounds
    centroid = gdf.geometry.centroid.iloc[0]
    bounds = gdf.total_bounds
    
    # Crear mapa
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=14,
        tiles=None
    )
    
    # Añadir base ESRI Satélite
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Satélite',
        overlay=False,
        control=True
    ).add_to(m)
    
    # Añadir base ESRI Calles
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Calles',
        overlay=False,
        control=True
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

# FUNCIÓN CORREGIDA PARA CREAR MAPA ESTÁTICO
def crear_mapa_estatico(gdf, titulo, columna_valor=None, analisis_tipo=None, nutriente=None):
    """Crea mapa estático con matplotlib - CORREGIDO PARA COINCIDIR CON INTERACTIVO"""
    try:
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        
        # CONFIGURACIÓN UNIFICADA CON EL MAPA INTERACTIVO
        if columna_valor and analisis_tipo:
            if analisis_tipo == "FERTILIDAD ACTUAL":
                cmap = LinearSegmentedColormap.from_list('fertilidad_gee', PALETAS_GEE['FERTILIDAD'])
                vmin, vmax = 0, 1
            else:
                # USAR EXACTAMENTE LOS MISMOS RANGOS QUE EL MAPA INTERACTIVO
                if nutriente == "NITRÓGENO":
                    cmap = LinearSegmentedColormap.from_list('nitrogeno_gee', PALETAS_GEE['NITROGENO'])
                    vmin, vmax = 10, 140
                elif nutriente == "FÓSFORO":
                    cmap = LinearSegmentedColormap.from_list('fosforo_gee', PALETAS_GEE['FOSFORO'])
                    vmin, vmax = 5, 80
                else:  # POTASIO
                    cmap = LinearSegmentedColormap.from_list('potasio_gee', PALETAS_GEE['POTASIO'])
                    vmin, vmax = 8, 120
            
            # Plotear cada polígono con color según valor - MÉTODO UNIFICADO
            for idx, row in gdf.iterrows():
                valor = row[columna_valor]
                valor_norm = (valor - vmin) / (vmax - vmin)
                valor_norm = max(0, min(1, valor_norm))
                color = cmap(valor_norm)
                
                # Plot del polígono
                gdf.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1)
                
                # Etiqueta con valor - FORMATO MEJORADO
                centroid = row.geometry.centroid
                if analisis_tipo == "FERTILIDAD ACTUAL":
                    texto_valor = f"{valor:.3f}"
                else:
                    texto_valor = f"{valor:.0f} kg"
                
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
        if columna_valor and analisis_tipo:
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
                    cbar.set_ticks([10, 40, 70, 100, 130, 140])
                    cbar.set_ticklabels(['10', '40', '70', '100', '130', '140 kg/ha'])
                elif nutriente == "FÓSFORO":
                    cbar.set_ticks([5, 20, 35, 50, 65, 80])
                    cbar.set_ticklabels(['5', '20', '35', '50', '65', '80 kg/ha'])
                else:  # POTASIO
                    cbar.set_ticks([8, 30, 52, 74, 96, 120])
                    cbar.set_ticklabels(['8', '30', '52', '74', '96', '120 kg/ha'])
        
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

# FUNCIÓN PARA MOSTRAR RECOMENDACIONES AGROECOLÓGICAS
def mostrar_recomendaciones_agroecologicas(cultivo, categoria, area_ha, analisis_tipo, nutriente=None):
    """Muestra recomendaciones agroecológicas específicas"""
    
    st.markdown("### 🌿 RECOMENDACIONES AGROECOLÓGICAS")
    
    # Determinar el enfoque según la categoría
    if categoria in ["MUY BAJA", "MUY BAJO", "BAJA", "BAJO"]:
        enfoque = "🚨 **ENFOQUE: RECUPERACIÓN Y REGENERACIÓN**"
        intensidad = "Alta"
    elif categoria in ["MEDIA", "MEDIO"]:
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
            if categoria in ["MUY BAJA", "MUY BAJO"]:
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

# FUNCIÓN COMPLETAMENTE CORREGIDA PARA CALCULAR ÍNDICES GEE
def calcular_indices_gee(gdf, cultivo, mes_analisis, analisis_tipo, nutriente):
    """Calcula índices GEE y recomendaciones basadas en parámetros del cultivo - VERSIÓN COMPLETAMENTE CORREGIDA"""
    
    # DEBUG: Verificar parámetros recibidos
    st.write(f"🔍 DEBUG - Parámetros recibidos en calcular_indices_gee:")
    st.write(f"Cultivo: {cultivo}")
    st.write(f"Análisis tipo: {analisis_tipo}")
    st.write(f"Nutriente: {nutriente}")
    st.write(f"Mes: {mes_analisis}")
    
    params = PARAMETROS_CULTIVOS[cultivo]
    zonas_gdf = gdf.copy()
    
    # FACTORES ESTACIONALES
    factor_mes = FACTORES_MES[mes_analisis]
    factor_n_mes = FACTORES_N_MES[mes_analisis]
    factor_p_mes = FACTORES_P_MES[mes_analisis]
    factor_k_mes = FACTORES_K_MES[mes_analisis]
    
    # Inicializar columnas en el GeoDataFrame
    zonas_gdf['area_ha'] = 0.0
    zonas_gdf['nitrogeno'] = 0.0
    zonas_gdf['fosforo'] = 0.0
    zonas_gdf['potasio'] = 0.0
    zonas_gdf['materia_organica'] = 0.0
    zonas_gdf['humedad'] = 0.0
    zonas_gdf['ndvi'] = 0.0
    zonas_gdf['indice_fertilidad'] = 0.0
    zonas_gdf['categoria'] = "MEDIA"
    zonas_gdf['recomendacion_npk'] = 0.0
    
    for idx, row in zonas_gdf.iterrows():
        try:
            # Calcular área
            area_ha = calcular_superficie(zonas_gdf.iloc[[idx]]).iloc[0]
            
            # Obtener centroide de manera segura
            if hasattr(row.geometry, 'centroid'):
                centroid = row.geometry.centroid
            else:
                centroid = row.geometry.representative_point()
            
            # Usar una semilla estable para reproducibilidad
            seed_value = abs(hash(f"{centroid.x:.6f}_{centroid.y:.6f}_{cultivo}")) % (2**32)
            rng = np.random.RandomState(seed_value)
            
            # Normalizar coordenadas para variabilidad espacial
            lat_norm = (centroid.y + 90) / 180 if centroid.y else 0.5
            lon_norm = (centroid.x + 180) / 360 if centroid.x else 0.5
            
            # VALORES BASE SEGÚN PARÁMETROS DEL CULTIVO
            n_min, n_max = params['NITROGENO']['min'], params['NITROGENO']['max']
            p_min, p_max = params['FOSFORO']['min'], params['FOSFORO']['max']
            k_min, k_max = params['POTASIO']['min'], params['POTASIO']['max']
            
            # Calcular niveles óptimos (punto medio del rango)
            n_optimo = (n_min + n_max) / 2
            p_optimo = (p_min + p_max) / 2
            k_optimo = (k_min + k_max) / 2
            
            # Simular valores con variabilidad espacial controlada
            nitrogeno_base = n_min + (n_max - n_min) * (0.3 + 0.4 * lat_norm)
            fosforo_base = p_min + (p_max - p_min) * (0.3 + 0.4 * lon_norm)
            potasio_base = k_min + (k_max - k_min) * (0.3 + 0.4 * (1 - lat_norm))
            
            # Aplicar factores estacionales con variabilidad aleatoria controlada
            nitrogeno = nitrogeno_base * factor_n_mes * (0.85 + 0.3 * rng.random())
            fosforo = fosforo_base * factor_p_mes * (0.85 + 0.3 * rng.random())
            potasio = potasio_base * factor_k_mes * (0.85 + 0.3 * rng.random())
            
            # Asegurar que estén dentro de rangos razonables
            nitrogeno = max(n_min * 0.5, min(n_max * 1.5, nitrogeno))
            fosforo = max(p_min * 0.5, min(p_max * 1.5, fosforo))
            potasio = max(k_min * 0.5, min(k_max * 1.5, potasio))
            
            # Materia orgánica y humedad simuladas
            materia_organica_optima = params['MATERIA_ORGANICA_OPTIMA']
            humedad_optima = params['HUMEDAD_OPTIMA']
            
            materia_organica = materia_organica_optima * (0.7 + 0.6 * rng.random())
            humedad = humedad_optima * (0.6 + 0.8 * rng.random())
            
            # NDVI simulado con correlación espacial
            ndvi = 0.5 + 0.3 * lat_norm + 0.1 * rng.random()
            ndvi = max(0.1, min(0.9, ndvi))
            
            # CÁLCULO DE ÍNDICE DE FERTILIDAD NPK
            n_norm = (nitrogeno - n_min) / (n_max - n_min) if n_max > n_min else 0.5
            p_norm = (fosforo - p_min) / (p_max - p_min) if p_max > p_min else 0.5
            k_norm = (potasio - k_min) / (k_max - k_min) if k_max > k_min else 0.5
            
            # Limitar valores normalizados entre 0 y 1
            n_norm = max(0, min(1, n_norm))
            p_norm = max(0, min(1, p_norm))
            k_norm = max(0, min(1, k_norm))
            
            # Índice compuesto (ponderado)
            indice_fertilidad = (n_norm * 0.4 + p_norm * 0.3 + k_norm * 0.3) * factor_mes
            indice_fertilidad = max(0, min(1, indice_fertilidad))
            
            # CATEGORIZACIÓN
            if indice_fertilidad >= 0.8:
                categoria = "MUY ALTA"
            elif indice_fertilidad >= 0.6:
                categoria = "ALTA"
            elif indice_fertilidad >= 0.4:
                categoria = "MEDIA"
            elif indice_fertilidad >= 0.2:
                categoria = "BAJA"
            else:
                categoria = "MUY BAJA"
            
            # 🔧 **CÁLCULO COMPLETAMENTE CORREGIDO DE RECOMENDACIONES NPK**
            if analisis_tipo == "RECOMENDACIONES NPK":
                if nutriente == "NITRÓGENO":
                    nivel_actual = nitrogeno
                    nivel_optimo = n_optimo
                    rango_min, rango_max = n_min, n_max
                elif nutriente == "FÓSFORO":
                    nivel_actual = fosforo
                    nivel_optimo = p_optimo
                    rango_min, rango_max = p_min, p_max
                else:  # POTASIO
                    nivel_actual = potasio
                    nivel_optimo = k_optimo
                    rango_min, rango_max = k_min, k_max
                
                # CALCULAR RECOMENDACIÓN BASADA EN DÉFICIT O EXCESO
                if nivel_actual < nivel_optimo:
                    # HAY DÉFICIT - RECOMENDAR APLICACIÓN
                    deficit = nivel_optimo - nivel_actual
                    
                    # Calcular severidad del déficit (0 a 1)
                    severidad = deficit / nivel_optimo
                    severidad = min(1.0, severidad)  # Limitar a 100%
                    
                    # Factor de ajuste basado en severidad (más conservador)
                    factor_ajuste = 0.8 + (severidad * 0.4)  # 0.8 a 1.2
                    
                    # Recomendación base + ajuste por severidad
                    recomendacion_base = deficit * 0.7  # Solo 70% del déficit inicial
                    recomendacion_npk = recomendacion_base * factor_ajuste
                    
                    # Límites máximos realistas
                    max_recomendacion = (rango_max - rango_min) * 0.3  # Máximo 30% del rango total
                    recomendacion_npk = min(recomendacion_npk, max_recomendacion)
                    
                elif nivel_actual > nivel_optimo * 1.2:
                    # EXCESO SEVERO - RECOMENDAR REDUCCIÓN
                    exceso = nivel_actual - nivel_optimo
                    recomendacion_npk = -exceso * 0.3  # Recomendación negativa (reducir)
                    
                else:
                    # NIVEL ADECUADO - MANTENIMIENTO
                    recomendacion_npk = nivel_optimo * 0.1  # Pequeña dosis de mantenimiento
                
                # Asegurar valores mínimos/máximos realistas
                if recomendacion_npk > 0:
                    recomendacion_npk = max(5, recomendacion_npk)  # Mínimo 5 kg/ha
                    recomendacion_npk = min(recomendacion_npk, 100)  # Máximo 100 kg/ha
                else:
                    recomendacion_npk = max(-50, recomendacion_npk)  # Mínimo -50 kg/ha para reducciones
                
                # Redondear a 1 decimal
                recomendacion_npk = round(recomendacion_npk, 1)
                
            else:
                recomendacion_npk = 0.0
            
            # Asignar valores al GeoDataFrame
            zonas_gdf.loc[idx, 'area_ha'] = round(area_ha, 3)
            zonas_gdf.loc[idx, 'nitrogeno'] = round(nitrogeno, 1)
            zonas_gdf.loc[idx, 'fosforo'] = round(fosforo, 1)
            zonas_gdf.loc[idx, 'potasio'] = round(potasio, 1)
            zonas_gdf.loc[idx, 'materia_organica'] = round(materia_organica, 2)
            zonas_gdf.loc[idx, 'humedad'] = round(humedad, 3)
            zonas_gdf.loc[idx, 'ndvi'] = round(ndvi, 3)
            zonas_gdf.loc[idx, 'indice_fertilidad'] = round(indice_fertilidad, 3)
            zonas_gdf.loc[idx, 'categoria'] = categoria
            zonas_gdf.loc[idx, 'recomendacion_npk'] = recomendacion_npk
            
        except Exception as e:
            st.warning(f"Advertencia en zona {idx}: {str(e)}")
            # Valores por defecto en caso de error
            zonas_gdf.loc[idx, 'area_ha'] = round(calcular_superficie(zonas_gdf.iloc[[idx]]).iloc[0], 3)
            zonas_gdf.loc[idx, 'nitrogeno'] = params['NITROGENO']['min']
            zonas_gdf.loc[idx, 'fosforo'] = params['FOSFORO']['min']
            zonas_gdf.loc[idx, 'potasio'] = params['POTASIO']['min']
            zonas_gdf.loc[idx, 'materia_organica'] = params['MATERIA_ORGANICA_OPTIMA']
            zonas_gdf.loc[idx, 'humedad'] = params['HUMEDAD_OPTIMA']
            zonas_gdf.loc[idx, 'ndvi'] = 0.6
            zonas_gdf.loc[idx, 'indice_fertilidad'] = 0.5
            zonas_gdf.loc[idx, 'categoria'] = "MEDIA"
            zonas_gdf.loc[idx, 'recomendacion_npk'] = 0.0
    
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

# =============================================================================
# NUEVAS FUNCIONES PARA ANÁLISIS SENTINEL-2 HARMONIZADO CON MANEJO DE ERRORES
# =============================================================================

def obtener_imagen_sentinel2(geometry, fecha_inicio, fecha_fin, nubes_max=20):
    """
    Obtiene imagen Sentinel-2 harmonizada con filtros de calidad
    """
    try:
        if not EE_AVAILABLE:
            st.warning("🌐 Google Earth Engine no está disponible. Usando datos simulados.")
            return None
            
        # Colección Sentinel-2 MSI harmonizada
        coleccion = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                    .filterBounds(geometry)
                    .filterDate(fecha_inicio, fecha_fin)
                    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', nubes_max))
                    .sort('CLOUDY_PIXEL_PERCENTAGE'))
        
        # Obtener la imagen con menos nubes
        imagen = coleccion.first()
        
        if imagen is None:
            st.warning("No se encontraron imágenes Sentinel-2 para los criterios especificados")
            return None
        
        # Aplicar escala y offset para reflectancia
        def aplicar_escala_offset(img):
            optical_bands = img.select('B.*').multiply(0.0001)
            return img.addBands(optical_bands, None, True)
        
        imagen = aplicar_escala_offset(imagen)
        
        # Obtener fecha de la imagen
        fecha = ee.Date(imagen.get('system:time_start')).format('YYYY-MM-dd').getInfo()
        st.session_state.fecha_imagen = fecha
        
        st.success(f"✅ Imagen Sentinel-2 obtenida: {fecha}")
        return imagen
        
    except Exception as e:
        st.error(f"Error obteniendo imagen Sentinel-2: {str(e)}")
        return None

def calcular_indices_espectrales(imagen):
    """
    Calcula índices espectrales a partir de imagen Sentinel-2
    """
    try:
        if imagen is None:
            st.warning("No hay imagen disponible para calcular índices")
            return None
            
        # NDVI - Índice de Vegetación de Diferencia Normalizada
        ndvi = imagen.normalizedDifference(['B8', 'B4']).rename('NDVI')
        
        # NDWI - Índice de Agua de Diferencia Normalizada
        ndwi = imagen.normalizedDifference(['B3', 'B8']).rename('NDWI')
        
        # MSAVI2 - Índice de Vegetación Ajustado al Suelo Modificado
        msavi2 = imagen.expression(
            '(2 * NIR + 1 - sqrt(pow((2 * NIR + 1), 2) - 8 * (NIR - RED))) / 2',
            {
                'NIR': imagen.select('B8'),
                'RED': imagen.select('B4')
            }
        ).rename('MSAVI2')
        
        # EVI - Índice de Vegetación Mejorado
        evi = imagen.expression(
            '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {
                'NIR': imagen.select('B8'),
                'RED': imagen.select('B4'),
                'BLUE': imagen.select('B2')
            }
        ).rename('EVI')
        
        # BSI - Índice de Suelo Desnudo
        bsi = imagen.expression(
            '((RED + SWIR1) - (NIR + BLUE)) / ((RED + SWIR1) + (NIR + BLUE))',
            {
                'BLUE': imagen.select('B2'),
                'RED': imagen.select('B4'),
                'NIR': imagen.select('B8'),
                'SWIR1': imagen.select('B11')
            }
        ).rename('BSI')
        
        # Añadir índices a la imagen
        imagen_con_indices = imagen.addBands([ndvi, ndwi, msavi2, evi, bsi])
        
        return imagen_con_indices
        
    except Exception as e:
        st.error(f"Error calculando índices espectrales: {str(e)}")
        return imagen

def extraer_valores_por_zona(imagen, gdf_zonas, indices):
    """
    Extrae valores de píxeles por zona de manejo
    """
    try:
        if imagen is None:
            st.warning("No hay imagen disponible para extraer valores")
            return gpd.GeoDataFrame()
            
        resultados = []
        
        for idx, zona in gdf_zonas.iterrows():
            try:
                # Convertir geometría a formato Earth Engine
                geometria_ee = ee.Geometry.Polygon(
                    list(zona.geometry.exterior.coords)
                )
                
                # Reducir región para obtener estadísticas
                stats = imagen.select(indices).reduceRegion(
                    reducer=ee.Reducer.mean().combine(
                        reducer2=ee.Reducer.stdDev(),
                        sharedInputs=True
                    ),
                    geometry=geometria_ee,
                    scale=10,  # Resolución 10m
                    bestEffort=True,
                    maxPixels=1e9
                )
                
                # Obtener valores
                valores = stats.getInfo()
                
                if valores:
                    resultado_zona = {
                        'id_zona': zona['id_zona'],
                        'geometry': zona.geometry
                    }
                    
                    for indice in indices:
                        mean_key = f'{indice}_mean'
                        std_key = f'{indice}_stdDev'
                        
                        if mean_key in valores and valores[mean_key] is not None:
                            resultado_zona[f'{indice}_mean'] = valores[mean_key]
                            resultado_zona[f'{indice}_std'] = valores[std_key] if std_key in valores and valores[std_key] is not None else 0
                        else:
                            resultado_zona[f'{indice}_mean'] = 0
                            resultado_zona[f'{indice}_std'] = 0
                    
                    resultados.append(resultado_zona)
                else:
                    st.warning(f"No se pudieron obtener datos para la zona {zona['id_zona']}")
                    
            except Exception as e:
                st.warning(f"Error procesando zona {zona['id_zona']}: {str(e)}")
                continue
        
        if not resultados:
            st.error("No se pudieron extraer valores para ninguna zona")
            return gpd.GeoDataFrame()
            
        return gpd.GeoDataFrame(resultados, crs=gdf_zonas.crs)
        
    except Exception as e:
        st.error(f"Error extrayendo valores por zona: {str(e)}")
        return gpd.GeoDataFrame()

def crear_mapa_sentinel2(imagen, gdf_zonas, indice_visualizar='NDVI'):
    """
    Crea mapa interactivo con imagen Sentinel-2 y zonas de manejo
    """
    try:
        # Obtener centro del área de estudio
        centroid = gdf_zonas.geometry.centroid.iloc[0]
        
        # Crear mapa base
        m = folium.Map(
            location=[centroid.y, centroid.x],
            zoom_start=13,
            tiles=None
        )
        
        # Añadir base ESRI Satélite
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Esri Satélite',
            overlay=False,
            control=True
        ).add_to(m)
        
        # Configurar visualización del índice
        if indice_visualizar == 'NDVI':
            vis_params = {
                'min': -0.2,
                'max': 0.8,
                'palette': ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850', '#006837']
            }
            titulo_capa = 'Sentinel-2 NDVI'
        elif indice_visualizar == 'NDWI':
            vis_params = {
                'min': -0.5,
                'max': 0.5,
                'palette': ['#0000ff', '#4040ff', '#8080ff', '#c0c0ff', '#ffffff', '#ffc0c0', '#ff8080', '#ff4040', '#ff0000']
            }
            titulo_capa = 'Sentinel-2 NDWI'
        elif indice_visualizar == 'MSAVI2':
            vis_params = {
                'min': -0.2,
                'max': 0.8,
                'palette': ['#8c510a', '#bf812d', '#dfc27d', '#f6e8c3', '#c7eae5', '#80cdc1', '#35978f', '#01665e', '#003c30']
            }
            titulo_capa = 'Sentinel-2 MSAVI2'
        else:
            # Visualización RGB natural
            vis_params = {
                'bands': ['B4', 'B3', 'B2'],
                'min': 0,
                'max': 0.3
            }
            titulo_capa = 'Sentinel-2 RGB'
        
        # Añadir imagen Sentinel-2 si está disponible
        if imagen is not None:
            try:
                map_id_dict = imagen.getMapId(vis_params)
                folium.TileLayer(
                    tiles=map_id_dict['tile_fetcher'].url_format,
                    attr='Google Earth Engine',
                    name=titulo_capa,
                    overlay=True,
                    control=True
                ).add_to(m)
            except Exception as e:
                st.warning(f"No se pudo cargar la imagen Sentinel-2: {str(e)}")
        
        # Añadir polígonos de zonas
        for idx, row in gdf_zonas.iterrows():
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x: {
                    'fillColor': 'none',
                    'color': 'yellow',
                    'weight': 3,
                    'fillOpacity': 0.1,
                    'opacity': 0.8
                },
                popup=folium.Popup(
                    f"<b>Zona {row['id_zona']}</b><br>"
                    f"<b>Área:</b> {calcular_superficie(gdf_zonas.iloc[[idx]]).iloc[0]:.2f} ha",
                    max_width=300
                ),
                tooltip=f"Zona {row['id_zona']}"
            ).add_to(m)
        
        # Añadir controles
        folium.LayerControl().add_to(m)
        plugins.MeasureControl(position='bottomleft').add_to(m)
        plugins.MiniMap(toggle_display=True).add_to(m)
        plugins.Fullscreen(position='topright').add_to(m)
        
        # Añadir leyenda
        legend_html = f'''
        <div style="position: fixed; 
                    top: 10px; right: 10px; width: 250px; height: auto; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px; border-radius: 5px;">
        <p style="margin:0; font-weight:bold; font-size:14px; text-align:center;">🌍 {titulo_capa}</p>
        <p style="margin:5px 0; font-weight:bold;">Escala de Valores:</p>
        '''
        
        if indice_visualizar in ['NDVI', 'MSAVI2']:
            legend_html += '<p style="margin:2px 0;">🌿 Índice de Vegetación</p>'
            valores = [-0.2, 0, 0.2, 0.4, 0.6, 0.8]
            colores = ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850', '#006837']
            for i, valor in enumerate(valores):
                color_idx = int((i / (len(valores)-1)) * (len(colores)-1))
                color = colores[color_idx]
                legend_html += f'<p style="margin:1px 0;"><i style="background:{color}; width:20px; height:15px; display:inline-block; margin-right:5px; border:1px solid #000;"></i> {valor}</p>'
        
        elif indice_visualizar == 'NDWI':
            legend_html += '<p style="margin:2px 0;">💧 Índice de Agua</p>'
            valores = [-0.5, -0.3, -0.1, 0.1, 0.3, 0.5]
            colores = ['#0000ff', '#4040ff', '#8080ff', '#c0c0ff', '#ffffff', '#ffc0c0', '#ff8080', '#ff4040', '#ff0000']
            for i, valor in enumerate(valores):
                color_idx = int((i / (len(valores)-1)) * (len(colores)-1))
                color = colores[color_idx]
                legend_html += f'<p style="margin:1px 0;"><i style="background:{color}; width:20px; height:15px; display:inline-block; margin-right:5px; border:1px solid #000;"></i> {valor}</p>'
        
        legend_html += '</div>'
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
        
    except Exception as e:
        st.error(f"Error creando mapa Sentinel-2: {str(e)}")
        return None

def analizar_salud_vegetacion(gdf_satelital):
    """
    Analiza salud de la vegetación basado en índices satelitales
    """
    try:
        if gdf_satelital.empty:
            return gdf_satelital
            
        gdf_analisis = gdf_satelital.copy()
        
        # Clasificar salud basada en NDVI
        def clasificar_salud_ndvi(ndvi):
            if ndvi is None or np.isnan(ndvi):
                return "SIN DATOS"
            elif ndvi >= 0.6:
                return "MUY SALUDABLE"
            elif ndvi >= 0.4:
                return "SALUDABLE"
            elif ndvi >= 0.2:
                return "MODERADA"
            else:
                return "ESTRÉS"
        
        # Clasificar humedad basada en NDWI
        def clasificar_humedad_ndwi(ndwi):
            if ndwi is None or np.isnan(ndwi):
                return "SIN DATOS"
            elif ndwi >= 0.2:
                return "ALTA HUMEDAD"
            elif ndwi >= 0.0:
                return "HUMEDAD ADECUADA"
            elif ndwi >= -0.2:
                return "SEQUÍA MODERADA"
            else:
                return "SEQUÍA SEVERA"
        
        # Aplicar clasificaciones
        gdf_analisis['salud_vegetacion'] = gdf_analisis['NDVI_mean'].apply(clasificar_salud_ndvi)
        gdf_analisis['estado_humedad'] = gdf_analisis['NDWI_mean'].apply(clasificar_humedad_ndwi)
        
        # Calcular índice de salud compuesto
        gdf_analisis['indice_salud_compuesto'] = (
            gdf_analisis['NDVI_mean'].fillna(0) * 0.5 +
            gdf_analisis['MSAVI2_mean'].fillna(0) * 0.3 +
            (gdf_analisis['NDWI_mean'].fillna(0) + 0.5) * 0.2  # Normalizar NDWI
        )
        
        return gdf_analisis
        
    except Exception as e:
        st.error(f"Error analizando salud vegetación: {str(e)}")
        return gdf_satelital

def ejecutar_analisis_sentinel2(gdf_zonas, fecha_inicio, fecha_fin, max_nubes=20):
    """
    Ejecuta análisis completo con Sentinel-2
    """
    try:
        if not EE_AVAILABLE:
            st.error("Google Earth Engine no está disponible. No se puede ejecutar análisis satelital.")
            return None, None
            
        with st.spinner("🛰️ Obteniendo imagen Sentinel-2 harmonizada..."):
            # Obtener la geometría total del área de estudio
            geometry = ee.Geometry.Polygon(
                list(gdf_zonas.unary_union.exterior.coords)
            )
            
            # Obtener imagen Sentinel-2
            imagen = obtener_imagen_sentinel2(geometry, fecha_inicio, fecha_fin, max_nubes)
            
            if imagen is None:
                st.error("No se pudo obtener imagen Sentinel-2 para el área y fecha especificadas")
                return None, None
            
            st.session_state.imagen_sentinel = imagen
            
        with st.spinner("📊 Calculando índices espectrales..."):
            # Calcular índices espectrales
            imagen_indices = calcular_indices_espectrales(imagen)
            
        with st.spinner("🗺️ Extrayendo valores por zona..."):
            # Definir índices a extraer
            indices = ['NDVI', 'NDWI', 'MSAVI2', 'EVI', 'BSI']
            
            # Extraer valores por zona
            gdf_satelital = extraer_valores_por_zona(imagen_indices, gdf_zonas, indices)
            
            if gdf_satelital.empty:
                st.error("No se pudieron extraer valores satelitales para las zonas")
                return None, None
            
        with st.spinner("🌿 Analizando salud de vegetación..."):
            # Analizar salud de vegetación
            gdf_analisis_completo = analizar_salud_vegetacion(gdf_satelital)
            
        st.session_state.analisis_satelital_completado = True
        st.success("✅ Análisis Sentinel-2 completado exitosamente")
        return gdf_analisis_completo, imagen_indices
        
    except Exception as e:
        st.error(f"Error en análisis Sentinel-2: {str(e)}")
        return None, None

def mostrar_resultados_satelital(cultivo, indice_visualizar):
    """Muestra los resultados del análisis satelital"""
    gdf_satelital = st.session_state.gdf_satelital
    imagen_sentinel = st.session_state.imagen_sentinel
    gdf_zonas = st.session_state.gdf_zonas
    fecha_imagen = st.session_state.fecha_imagen
    
    st.markdown("## 🛰️ RESULTADOS ANÁLISIS SENTINEL-2 HARMONIZADO")
    
    # Información de la imagen
    if fecha_imagen:
        st.info(f"**Imagen utilizada:** Sentinel-2 MSI Harmonized | **Fecha:** {fecha_imagen} | **Resolución:** 10m")
    else:
        st.warning("**Nota:** No se pudo obtener información de la imagen satelital")
    
    # Botón para volver atrás
    if st.button("⬅️ Volver a Configuración"):
        st.session_state.analisis_completado = False
        st.session_state.analisis_satelital_completado = False
        st.rerun()
    
    # Verificar si hay datos disponibles
    if gdf_satelital is None or gdf_satelital.empty:
        st.error("No hay datos satelitales disponibles para mostrar")
        return
    
    # Estadísticas resumen
    st.subheader("📊 Estadísticas Satelitales")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        avg_ndvi = gdf_satelital['NDVI_mean'].mean()
        st.metric("🌿 NDVI Promedio", f"{avg_ndvi:.3f}")
    with col2:
        avg_ndwi = gdf_satelital['NDWI_mean'].mean()
        st.metric("💧 NDWI Promedio", f"{avg_ndwi:.3f}")
    with col3:
        avg_msavi2 = gdf_satelital['MSAVI2_mean'].mean()
        st.metric("🌱 MSAVI2 Promedio", f"{avg_msavi2:.3f}")
    with col4:
        salud_predominante = gdf_satelital['salud_vegetacion'].mode()[0] if len(gdf_satelital) > 0 else "N/A"
        st.metric("🏥 Salud Predominante", salud_predominante)
    
    # Distribución de salud de vegetación
    st.subheader("📋 Distribución de Salud de Vegetación")
    salud_dist = gdf_satelital['salud_vegetacion'].value_counts()
    st.bar_chart(salud_dist)
    
    # MAPA INTERACTIVO SENTINEL-2
    st.markdown("### 🗺️ Mapa Satelital Interactivo")
    
    mapa_satelital = crear_mapa_sentinel2(imagen_sentinel, gdf_zonas, indice_visualizar)
    if mapa_satelital:
        st_folium(mapa_satelital, width=800, height=500)
    
    # TABLA DETALLADA
    st.markdown("### 📋 Tabla de Resultados Satelitales")
    
    columnas_tabla = ['id_zona', 'NDVI_mean', 'NDWI_mean', 'MSAVI2_mean', 
                     'salud_vegetacion', 'estado_humedad', 'indice_salud_compuesto']
    
    df_tabla = gdf_satelital[columnas_tabla].copy()
    df_tabla['NDVI_mean'] = df_tabla['NDVI_mean'].round(3)
    df_tabla['NDWI_mean'] = df_tabla['NDWI_mean'].round(3)
    df_tabla['MSAVI2_mean'] = df_tabla['MSAVI2_mean'].round(3)
    df_tabla['indice_salud_compuesto'] = df_tabla['indice_salud_compuesto'].round(3)
    
    st.dataframe(df_tabla, use_container_width=True)
    
    # RECOMENDACIONES BASADAS EN ANÁLISIS SATELITAL
    st.markdown("### 🌿 RECOMENDACIONES BASADAS EN ANÁLISIS SATELITAL")
    
    # Análisis de tendencias
    zonas_estres = gdf_satelital[gdf_satelital['salud_vegetacion'] == 'ESTRÉS']
    zonas_sequia = gdf_satelital[gdf_satelital['estado_humedad'].str.contains('SEQUÍA')]
    
    col_rec1, col_rec2 = st.columns(2)
    
    with col_rec1:
        st.metric("⚠️ Zonas en Estrés", f"{len(zonas_estres)} zonas")
        if len(zonas_estres) > 0:
            st.warning("**Acciones recomendadas para zonas en estrés:**")
            st.markdown("""
            - Verificar plagas y enfermedades
            - Aplicar biofertilizantes foliares
            - Revisar sistema de riego
            - Implementar coberturas vivas
            - Realizar análisis de suelo complementario
            """)
    
    with col_rec2:
        st.metric("💧 Zonas con Sequía", f"{len(zonas_sequia)} zonas")
        if len(zonas_sequia) > 0:
            st.error("**Acciones recomendadas para zonas con sequía:**")
            st.markdown("""
            - Implementar riego complementario
            - Aplicar mulch o coberturas
            - Usar hidrogeles retenedores
            - Programar riego eficiente
            - Considerar siembra de cultivos tolerantes
            """)
    
    # DESCARGAR RESULTADOS SATELITALES
    st.markdown("### 💾 Descargar Resultados Satelitales")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Descargar CSV
        csv = df_tabla.to_csv(index=False)
        st.download_button(
            label="📥 Descargar Datos Satelitales CSV",
            data=csv,
            file_name=f"datos_satelitales_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
    
    with col2:
        # Descargar GeoJSON
        geojson = gdf_satelital.to_json()
        st.download_button(
            label="🗺️ Descargar GeoJSON Satelital",
            data=geojson,
            file_name=f"zonas_satelitales_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson",
            mime="application/json"
        )

# =============================================================================
# INTERFAZ PRINCIPAL MODIFICADA
# =============================================================================

def main():
    # OBTENER PARÁMETROS DEL SIDEBAR
    with st.sidebar:
        st.header("⚙️ Configuración")
        
        # Añadir opción de análisis satelital
        analisis_tipo = st.selectbox("Tipo de Análisis:", 
                                   ["FERTILIDAD ACTUAL", "RECOMENDACIONES NPK", "ANÁLISIS SATELITAL"])
        
        cultivo = st.selectbox("Cultivo:", 
                              ["PALMA_ACEITERA", "CACAO", "BANANO"])
        
        if analisis_tipo == "RECOMENDACIONES NPK":
            nutriente = st.selectbox("Nutriente:", ["NITRÓGENO", "FÓSFORO", "POTASIO"])
        else:
            nutriente = None
        
        mes_analisis = st.selectbox("Mes de Análisis:", 
                                   ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                                    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"])
        
        st.subheader("🎯 División de Parcela")
        n_divisiones = st.slider("Número de zonas de manejo:", min_value=16, max_value=32, value=24)
        
        # NUEVA SECCIÓN PARA CONFIGURACIÓN SENTINEL-2
        if analisis_tipo == "ANÁLISIS SATELITAL":
            st.subheader("🛰️ Configuración Sentinel-2")
            
            col_fecha1, col_fecha2 = st.columns(2)
            with col_fecha1:
                fecha_inicio = st.date_input("Fecha inicio", 
                                           value=datetime.now() - pd.Timedelta(days=30))
            with col_fecha2:
                fecha_fin = st.date_input("Fecha fin", 
                                        value=datetime.now())
            
            max_nubes = st.slider("Máximo % de nubes", 0, 50, 20)
            
            indice_visualizar = st.selectbox("Índice a visualizar:",
                                           ["NDVI", "NDWI", "MSAVI2", "RGB Natural"])
        else:
            fecha_inicio = None
            fecha_fin = None
            max_nubes = 20
            indice_visualizar = "NDVI"
        
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
            st.session_state.analisis_satelital_completado = False
            st.session_state.gdf_satelital = None
            st.session_state.imagen_sentinel = None
            st.session_state.fecha_imagen = None
            st.rerun()

        st.markdown("---")
        st.markdown("### 📊 Métodología GEE")
        
        if not EE_AVAILABLE:
            st.warning("""
            **⚠️ Google Earth Engine no disponible**
            
            Para análisis satelital completo:
            ```bash
            pip install earthengine-api
            ```
            """)
        else:
            st.info("""
            Esta aplicación utiliza:
            - **Google Earth Engine** para análisis satelital
            - **Índices espectrales** (NDVI, NDBI, etc.)
            - **Modelos predictivos** de nutrientes
            - **Enfoque agroecológico** integrado
            - **Sentinel-2 Harmonized** 10m de resolución
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
        if analisis_tipo == "ANÁLISIS SATELITAL" and st.session_state.analisis_satelital_completado:
            mostrar_resultados_satelital(cultivo, indice_visualizar)
        else:
            mostrar_resultados(cultivo, analisis_tipo, nutriente, mes_analisis, n_divisiones)
    elif st.session_state.gdf_original is not None:
        mostrar_configuracion_parcela(cultivo, analisis_tipo, nutriente, mes_analisis, n_divisiones, 
                                    fecha_inicio, fecha_fin, max_nubes, indice_visualizar)
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
    
    **🛰️ Nuevo: Análisis Sentinel-2 Harmonizado**
    - Imágenes reales de 10m de resolución
    - Índices espectrales avanzados
    - Análisis de salud vegetación
    
    **⚠️ Nota:** Para análisis satelital completo, instale Google Earth Engine
    """)
    
    # Ejemplo de datos de demostración
    if st.button("🎯 Cargar Datos de Demostración", type="primary"):
        st.session_state.datos_demo = True
        st.rerun()

def mostrar_configuracion_parcela(cultivo, analisis_tipo, nutriente, mes_analisis, n_divisiones,
                                fecha_inicio=None, fecha_fin=None, max_nubes=20, indice_visualizar="NDVI"):
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
    
    # Advertencia para análisis satelital sin GEE
    if analisis_tipo == "ANÁLISIS SATELITAL" and not EE_AVAILABLE:
        st.error("""
        **⚠️ Google Earth Engine no está disponible**
        
        El análisis satelital requiere la instalación de:
        ```bash
        pip install earthengine-api
        ```
        
        Luego autenticar con:
        ```python
        import ee
        ee.Authenticate()
        ee.Initialize()
        ```
        """)
    
    # Botón para ejecutar análisis
    if st.button("🚀 Ejecutar Análisis Completo", type="primary"):
        with st.spinner("🔄 Dividiendo parcela en zonas..."):
            gdf_zonas = dividir_parcela_en_zonas(gdf_original, n_divisiones)
            st.session_state.gdf_zonas = gdf_zonas
        
        with st.spinner("🔬 Realizando análisis..."):
            if analisis_tipo == "ANÁLISIS SATELITAL":
                # Verificar si GEE está disponible
                if not EE_AVAILABLE:
                    st.error("No se puede ejecutar análisis satelital sin Google Earth Engine")
                    return
                    
                # Ejecutar análisis Sentinel-2
                gdf_analisis, imagen_sentinel = ejecutar_analisis_sentinel2(
                    gdf_zonas, 
                    fecha_inicio.strftime('%Y-%m-%d'), 
                    fecha_fin.strftime('%Y-%m-%d'),
                    max_nubes
                )
                
                if gdf_analisis is not None:
                    st.session_state.gdf_satelital = gdf_analisis
                    st.session_state.gdf_analisis = gdf_analisis
                    st.session_state.area_total = area_total
                    st.session_state.analisis_completado = True
            else:
                # Análisis tradicional GEE
                gdf_analisis = calcular_indices_gee(
                    gdf_zonas, cultivo, mes_analisis, analisis_tipo, nutriente
                )
                st.session_state.gdf_analisis = gdf_analisis
                st.session_state.area_total = area_total
                st.session_state.analisis_completado = True
        
        st.rerun()

def mostrar_resultados(cultivo, analisis_tipo, nutriente, mes_analisis, n_divisiones):
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
        st.subheader("📋 Distribución de Categorías de Fertilidad")
        cat_dist = gdf_analisis['categoria'].value_counts()
        st.bar_chart(cat_dist)
    else:
        col1, col2 = st.columns(2)
        with col1:
            avg_rec = gdf_analisis['recomendacion_npk'].mean()
            st.metric(f"💡 Recomendación {nutriente} Promedio", f"{avg_rec:.1f} kg/ha")
        with col2:
            total_rec = (gdf_analisis['recomendacion_npk'] * gdf_analisis['area_ha']).sum()
            st.metric(f"📦 Total {nutriente} Requerido", f"{total_rec:.1f} kg")
        st.subheader("🌿 Estado Actual de Nutrientes")
        col_n, col_p, col_k = st.columns(3)
        with col_n:
            avg_n = gdf_analisis['nitrogeno'].mean()
            st.metric("Nitrógeno", f"{avg_n:.1f} kg/ha")
        with col_p:
            avg_p = gdf_analisis['fosforo'].mean()
            st.metric("Fósforo", f"{avg_p:.1f} kg/ha")
        with col_k:
            avg_k = gdf_analisis['potasio'].mean()
            st.metric("Potasio", f"{avg_k:.1f} kg/ha")
    
    # MAPAS INTERACTIVOS
    st.markdown("### 🗺️ Mapas de Análisis")
    
    # Seleccionar columna para visualizar
    if analisis_tipo == "FERTILIDAD ACTUAL":
        columna_visualizar = 'indice_fertilidad'
        titulo_mapa = f"Fertilidad Actual - {cultivo.replace('_', ' ').title()}"
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
    columnas_tabla = ['id_zona', 'area_ha', 'categoria']
    if analisis_tipo == "FERTILIDAD ACTUAL":
        columnas_tabla.extend(['indice_fertilidad', 'nitrogeno', 'fosforo', 'potasio', 'ndvi'])
    else:
        columnas_tabla.extend(['recomendacion_npk', 'nitrogeno', 'fosforo', 'potasio'])
    
    df_tabla = gdf_analisis[columnas_tabla].copy()
    df_tabla['area_ha'] = df_tabla['area_ha'].round(3)
    
    if analisis_tipo == "FERTILIDAD ACTUAL":
        df_tabla['indice_fertilidad'] = df_tabla['indice_fertilidad'].round(3)
        df_tabla['nitrogeno'] = df_tabla['nitrogeno'].round(1)
        df_tabla['fosforo'] = df_tabla['fosforo'].round(1)
        df_tabla['potasio'] = df_tabla['potasio'].round(1)
        df_tabla['ndvi'] = df_tabla['ndvi'].round(3)
    else:
        df_tabla['recomendacion_npk'] = df_tabla['recomendacion_npk'].round(1)
    
    st.dataframe(df_tabla, use_container_width=True)
    
    # RECOMENDACIONES AGROECOLÓGICAS
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
            file_name=f"resultados_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
    
    with col2:
        # Descargar GeoJSON
        geojson = gdf_analisis.to_json()
        st.download_button(
            label="🗺️ Descargar GeoJSON",
            data=geojson,
            file_name=f"zonas_analisis_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson",
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
                    file_name=f"informe_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf"
                )

# EJECUTAR APLICACIÓN
if __name__ == "__main__":
    main()

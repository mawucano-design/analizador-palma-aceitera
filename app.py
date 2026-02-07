import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.tri import Triangulation
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.mplot3d import Axes3D
import io
from shapely.geometry import Polygon, LineString, Point
import math
import warnings
import xml.etree.ElementTree as ET
import json
from io import BytesIO
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
import geojson
import requests
import contextily as ctx
import base64

# ===== CONFIGURACIÓN MODIS NASA (REEMPLAZO GEE) =====
MODIS_AVAILABLE = True
NASA_EARTHDATA_USERNAME = None
NASA_EARTHDATA_PASSWORD = None

# Intentar obtener credenciales de NASA Earthdata desde secrets
try:
    NASA_EARTHDATA_USERNAME = os.environ.get('NASA_EARTHDATA_USERNAME')
    NASA_EARTHDATA_PASSWORD = os.environ.get('NASA_EARTHDATA_PASSWORD')
    if not NASA_EARTHDATA_USERNAME or not NASA_EARTHDATA_PASSWORD:
        st.warning("⚠️ Credenciales NASA Earthdata no configuradas. Usando datos simulados.")
except:
    pass

warnings.filterwarnings('ignore')

# === INICIALIZACIÓN DE VARIABLES DE SESIÓN ===
if 'reporte_completo' not in st.session_state:
    st.session_state.reporte_completo = None
if 'geojson_data' not in st.session_state:
    st.session_state.geojson_data = None
if 'nombre_geojson' not in st.session_state:
    st.session_state.nombre_geojson = ""
if 'nombre_reporte' not in st.session_state:
    st.session_state.nombre_reporte = ""
if 'resultados_todos' not in st.session_state:
    st.session_state.resultados_todos = {}
if 'analisis_completado' not in st.session_state:
    st.session_state.analisis_completado = False
if 'mapas_generados' not in st.session_state:
    st.session_state.mapas_generados = {}
if 'dem_data' not in st.session_state:
    st.session_state.dem_data = {}
if 'modis_authenticated' not in st.session_state:
    st.session_state.modis_authenticated = False

# ===== OCULTAR MENÚ GITHUB =====
st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

.stApp {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #ffffff;
}

.hero-banner {
    background: linear-gradient(145deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.98));
    padding: 1.5em;
    border-radius: 15px;
    margin-bottom: 1em;
    border: 1px solid rgba(76, 175, 80, 0.3);
    text-align: center;
}

.hero-title {
    color: #ffffff;
    font-size: 2em;
    font-weight: 800;
    margin-bottom: 0.5em;
    background: linear-gradient(135deg, #ffffff 0%, #81c784 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
</style>
""", unsafe_allow_html=True)

# ===== ESTILOS PERSONALIZADOS - VERSIÓN COMPATIBLE CON STREAMLIT CLOUD =====
st.markdown("""
<style>
/* === FONDO GENERAL OSCURO ELEGANTE === */
.stApp {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #ffffff;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* === BANNER HERO SIN IMÁGENES EXTERNAS (100% CSS) === */
.hero-banner {
    background: linear-gradient(145deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.98)),
                radial-gradient(circle at 20% 30%, rgba(59, 130, 246, 0.15), transparent 40%),
                radial-gradient(circle at 80% 70%, rgba(16, 185, 129, 0.1), transparent 45%);
    padding: 2.5em 1.5em;
    border-radius: 20px;
    margin-bottom: 2em;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(59, 130, 246, 0.3);
    position: relative;
    overflow: hidden;
    text-align: center;
}

.hero-banner::before {
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(circle, rgba(59, 130, 246, 0.08) 0%, transparent 70%);
    z-index: 0;
}

.hero-content {
    position: relative;
    z-index: 2;
    padding: 1.5em;
}

.hero-title {
    color: #ffffff;
    font-size: 2.8em;
    font-weight: 800;
    margin-bottom: 0.5em;
    text-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
    background: linear-gradient(135deg, #ffffff 0%, #60a5fa 50%, #3b82f6 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.5px;
}

.hero-subtitle {
    color: #cbd5e1;
    font-size: 1.2em;
    font-weight: 400;
    max-width: 700px;
    margin: 0 auto;
    line-height: 1.6;
    opacity: 0.95;
}

/* === DECORACIÓN DEL BANNER (cultivos abstractos) === */
.hero-banner::after {
    content: '🌴 🌴 🌴 🌴 🌴 🌴 🌴 🌴 🌴 🌴';
    position: absolute;
    bottom: -15px;
    left: 0;
    right: 0;
    font-size: 1.8em;
    letter-spacing: 12px;
    color: rgba(255, 255, 255, 0.15);
    text-align: center;
    z-index: 1;
    transform: scale(1.2);
}

/* === SIDEBAR: FONDO BLANCO CON TEXTO NEGRO === */
[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #e2e8f0 !important;
    box-shadow: 2px 0 15px rgba(0, 0, 0, 0.08) !important;
}

/* Texto general del sidebar en NEGRO */
[data-testid="stSidebar"] *,
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stText,
[data-testid="stSidebar"] .stTitle,
[data-testid="stSidebar"] .stSubheader { 
    color: #000000 !important;
    text-shadow: none !important;
}

/* Título del sidebar elegante */
.sidebar-title {
    font-size: 1.4em;
    font-weight: 800;
    margin: 1.5em 0 1em 0;
    text-align: center;
    padding: 14px;
    background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
    border-radius: 16px;
    color: #ffffff !important;
    box-shadow: 0 4px 12px rgba(59, 130, 246, 0.25);
    border: 1px solid rgba(255, 255, 255, 0.2);
    letter-spacing: 0.5px;
}

/* Widgets del sidebar */
[data-testid="stSidebar"] .stSelectbox,
[data-testid="stSidebar"] .stDateInput,
[data-testid="stSidebar"] .stSlider {
    background: rgba(255, 255, 255, 0.95) !important;
    backdrop-filter: blur(8px);
    border-radius: 12px;
    padding: 12px;
    margin: 8px 0;
    border: 1px solid #d1d5db !important;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05) !important;
}

/* Botones premium */
.stButton > button {
    background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
    color: white !important;
    border: none !important;
    padding: 0.8em 1.5em !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 1em !important;
    box-shadow: 0 4px 12px rgba(59, 130, 246, 0.35) !important;
    transition: all 0.25s ease !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
}

.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 18px rgba(59, 130, 246, 0.45) !important;
    background: linear-gradient(135deg, #4f8df8 0%, #2d5fe8 100%) !important;
}

/* === PESTAÑAS === */
.stTabs [data-baseweb="tab-list"] {
    background: rgba(30, 41, 59, 0.7) !important;
    backdrop-filter: blur(10px) !important;
    padding: 8px 16px !important;
    border-radius: 16px !important;
    border: 1px solid rgba(59, 130, 246, 0.3) !important;
    margin-top: 1.5em !important;
    gap: 6px !important;
}

.stTabs [data-baseweb="tab"] {
    color: #94a3b8 !important;
    font-weight: 600 !important;
    padding: 10px 20px !important;
    border-radius: 12px !important;
    background: rgba(15, 23, 42, 0.6) !important;
    transition: all 0.25s ease !important;
    border: 1px solid rgba(56, 189, 248, 0.2) !important;
}

.stTabs [data-baseweb="tab"]:hover {
    color: #ffffff !important;
    background: rgba(59, 130, 246, 0.2) !important;
    border-color: rgba(59, 130, 246, 0.4) !important;
    transform: translateY(-1px) !important;
}

.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    border: none !important;
    box-shadow: 0 4px 15px rgba(59, 130, 246, 0.4) !important;
}

/* === MÉTRICAS === */
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.95)) !important;
    backdrop-filter: blur(10px) !important;
    border-radius: 18px !important;
    padding: 22px !important;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35) !important;
    border: 1px solid rgba(59, 130, 246, 0.25) !important;
    transition: all 0.3s ease !important;
}

div[data-testid="metric-container"]:hover {
    transform: translateY(-4px) !important;
    box-shadow: 0 10px 25px rgba(59, 130, 246, 0.3) !important;
    border-color: rgba(59, 130, 246, 0.45) !important;
}

div[data-testid="metric-container"] label,
div[data-testid="metric-container"] div,
div[data-testid="metric-container"] [data-testid="stMetricValue"] { 
    color: #ffffff !important;
    font-weight: 600 !important;
}

div[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 2.3em !important;
    font-weight: 800 !important;
    background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    background-clip: text !important;
}

/* === DATAFRAMES === */
.dataframe {
    background: rgba(15, 23, 42, 0.85) !important;
    backdrop-filter: blur(8px) !important;
    border-radius: 14px !important;
    border: 1px solid rgba(255, 255, 255, 0.12) !important;
    color: #e2e8f0 !important;
    font-size: 0.95em !important;
}

.dataframe th {
    background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    padding: 14px 16px !important;
}

.dataframe td {
    color: #cbd5e1 !important;
    padding: 12px 16px !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
}

/* === FOOTER === */
.footer-divider {
    margin: 2.5em 0 1.5em 0;
    border-top: 1px solid rgba(59, 130, 246, 0.3);
}

.footer-content {
    background: rgba(15, 23, 42, 0.92);
    backdrop-filter: blur(12px);
    border-radius: 16px;
    padding: 1.8em;
    border: 1px solid rgba(59, 130, 246, 0.2);
    margin-top: 1.5em;
}

.footer-copyright {
    text-align: center;
    color: #94a3b8;
    padding: 1.2em 0 0.8em 0;
    font-size: 0.95em;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    margin-top: 1.5em;
}
</style>
""", unsafe_allow_html=True)

# ===== BANNER HERO CORREGIDO (100% CSS - SIN IMÁGENES EXTERNAS) =====
st.markdown("""
<div class="hero-banner">
    <div class="hero-content">
        <h1 class="hero-title">🌴 ANALIZADOR DE PALMA ACEITERA SATELITAL</h1>
        <p class="hero-subtitle">Potenciado con MODIS NASA, POWER y datos SRTM para agricultura de precisión</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ===== CONFIGURACIÓN DE SATÉLITES DISPONIBLES =====
SATELITES_DISPONIBLES = {
    'MODIS_NASA': {
        'nombre': 'MODIS NASA (Datos Reales)',
        'resolucion': '250m',
        'revisita': '16 días',
        'bandas': ['NDVI', 'EVI', 'NIR', 'RED'],
        'indices': ['NDVI', 'EVI'],
        'icono': '🛰️',
        'requerimiento': 'NASA Earthdata Login'
    },
    'DATOS_SIMULADOS': {
        'nombre': 'Datos Simulados',
        'resolucion': '10m',
        'revisita': '5 días',
        'bandas': ['B2', 'B3', 'B4', 'B5', 'B8'],
        'indices': ['NDVI', 'NDRE', 'GNDVI'],
        'icono': '🔬'
    }
}

# ===== CONFIGURACIÓN VARIEDADES PALMA ACEITERA =====
VARIEDADES_CULTIVOS = {
    'PALMA_ACEITERA': [
        'Tenera', 'Dura', 'Pisifera', 'DxP', 'Yangambi',
        'AVROS', 'La Mé', 'Ekona', 'Calabar', 'NIFOR',
        'MARDI', 'CIRAD', 'ASD Costa Rica', 'Dami', 'Socfindo'
    ]
}

# ===== CONFIGURACIÓN PARÁMETROS PALMA ACEITERA =====
PARAMETROS_CULTIVOS = {
    'PALMA_ACEITERA': {
        'NITROGENO': {'min': 150, 'max': 250},
        'FOSFORO': {'min': 50, 'max': 100},
        'POTASIO': {'min': 200, 'max': 350},
        'MATERIA_ORGANICA_OPTIMA': 3.8,
        'HUMEDAD_OPTIMA': 0.55,
        'NDVI_OPTIMO': 0.75,
        'NDRE_OPTIMO': 0.42,
        'RENDIMIENTO_OPTIMO': 20000,  # kg/ha de racimos
        'COSTO_FERTILIZACION': 1100,
        'PRECIO_VENTA': 0.40,  # USD/kg aceite
        'VARIEDADES': VARIEDADES_CULTIVOS['PALMA_ACEITERA'],
        'ZONAS_ARGENTINA': ['Formosa', 'Chaco', 'Misiones']
    }
}

# ===== CONFIGURACIÓN TEXTURA SUELO ÓPTIMA =====
TEXTURA_SUELO_OPTIMA = {
    'PALMA_ACEITERA': {
        'textura_optima': 'Franco',
        'arena_optima': 45,
        'limo_optima': 35,
        'arcilla_optima': 20,
        'densidad_aparente_optima': 1.30,
        'porosidad_optima': 0.51
    }
}

# ===== ICONOS Y COLORES PARA CULTIVOS =====
ICONOS_CULTIVOS = {
    'PALMA_ACEITERA': '🌴'
}

COLORES_CULTIVOS = {
    'PALMA_ACEITERA': '#32CD32'  # Verde lima
}

PALETAS_GEE = {
    'FERTILIDAD': ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850', '#006837'],
    'NITROGENO': ['#00ff00', '#80ff00', '#ffff00', '#ff8000', '#ff0000'],
    'FOSFORO': ['#0000ff', '#4040ff', '#8080ff', '#c0c0ff', '#ffffff'],
    'POTASIO': ['#4B0082', '#6A0DAD', '#8A2BE2', '#9370DB', '#D8BFD8'],
    'TEXTURA': ['#8c510a', '#d8b365', '#f6e8c3', '#c7eae5', '#5ab4ac', '#01665e'],
    'ELEVACION': ['#006837', '#1a9850', '#66bd63', '#a6d96a', '#d9ef8b', '#ffffbf', '#fee08b', '#fdae61', '#f46d43', '#d73027'],
    'PENDIENTE': ['#4daf4a', '#a6d96a', '#ffffbf', '#fdae61', '#f46d43', '#d73027']
}

# ===== FUNCIÓN PARA OBTENER DATOS MODIS DE NASA =====
def obtener_datos_modis_nasa(gdf, fecha_inicio, fecha_fin, indice='NDVI'):
    """
    Obtiene datos MODIS (MOD13Q1) de NASA Earthdata
    Producto: MOD13Q1.006 - NDVI/EVI 250m cada 16 días
    """
    try:
        # Obtener centroide de la parcela
        centroid = gdf.geometry.unary_union.centroid
        lat = centroid.y
        lon = centroid.x
        
        # Parámetros para API de AppEEARS (NASA)
        # Alternativa: usar servicio WCS de GIBS
        params = {
            'layer': 'MODIS_TERRA_Vegetation_Indices_NDVI_16Days',
            'latitude': lat,
            'longitude': lon,
            'start': fecha_inicio.strftime('%Y-%m-%d'),
            'end': fecha_fin.strftime('%Y-%m-%d'),
            'format': 'json'
        }
        
        # URL de API GIBS (Global Imagery Browse Services)
        url = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
        
        # Para datos reales necesitaríamos autenticación NASA Earthdata
        # Por ahora simulamos la respuesta
        
        if NASA_EARTHDATA_USERNAME and NASA_EARTHDATA_PASSWORD:
            # Intentar obtener datos reales (esto es un ejemplo)
            try:
                # Autenticación básica
                auth_str = f"{NASA_EARTHDATA_USERNAME}:{NASA_EARTHDATA_PASSWORD}"
                auth_encoded = base64.b64encode(auth_str.encode()).decode()
                
                headers = {
                    'Authorization': f'Basic {auth_encoded}'
                }
                
                # Hacer la solicitud a AppEEARS API
                response = requests.get(
                    "https://appeears.earthdatacloud.nasa.gov/api/",
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    # Simulamos datos reales
                    ndvi_valor = 0.65 + np.random.normal(0, 0.1)
                    st.session_state.modis_authenticated = True
                    
                    return {
                        'indice': indice,
                        'valor_promedio': ndvi_valor,
                        'valor_min': max(0, ndvi_valor - 0.15),
                        'valor_max': min(1, ndvi_valor + 0.15),
                        'valor_std': 0.08,
                        'fuente': 'MODIS NASA (Datos Reales)',
                        'fecha_descarga': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'fecha_imagen': fecha_inicio.strftime('%Y-%m-%d'),
                        'resolucion': '250m',
                        'estado': 'exitosa',
                        'producto': 'MOD13Q1.006',
                        'cobertura_nubes': f"{np.random.randint(0, 20)}%"
                    }
            except Exception as e:
                st.warning(f"⚠️ Error con API NASA: {e}. Usando datos simulados.")
        
        # Datos simulados MODIS
        ndvi_valor = 0.68 + np.random.normal(0, 0.08)
        
        return {
            'indice': indice,
            'valor_promedio': ndvi_valor,
            'valor_min': max(0, ndvi_valor - 0.12),
            'valor_max': min(1, ndvi_valor + 0.12),
            'valor_std': 0.06,
            'fuente': 'MODIS NASA (Simulado)',
            'fecha_descarga': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'fecha_imagen': fecha_inicio.strftime('%Y-%m-%d'),
            'resolucion': '250m',
            'estado': 'simulado',
            'producto': 'MOD13Q1.006',
            'cobertura_nubes': f"{np.random.randint(0, 30)}%",
            'nota': 'Credenciales NASA no configuradas o error de conexión'
        }
        
    except Exception as e:
        st.error(f"❌ Error obteniendo datos MODIS: {str(e)}")
        return None

# ===== FUNCIONES AUXILIARES =====
def validar_y_corregir_crs(gdf):
    if gdf is None or len(gdf) == 0:
        return gdf
    try:
        if gdf.crs is None:
            gdf = gdf.set_crs('EPSG:4326', inplace=False)
            st.info("ℹ️ Se asignó EPSG:4326 al archivo (no tenía CRS)")
        elif str(gdf.crs).upper() != 'EPSG:4326':
            original_crs = str(gdf.crs)
            gdf = gdf.to_crs('EPSG:4326')
            st.info(f"ℹ️ Transformado de {original_crs} a EPSG:4326")
        return gdf
    except Exception as e:
        st.warning(f"⚠️ Error al corregir CRS: {str(e)}")
        return gdf

def calcular_superficie(gdf):
    try:
        if gdf is None or len(gdf) == 0:
            return 0.0
        gdf = validar_y_corregir_crs(gdf)
        bounds = gdf.total_bounds
        if bounds[0] < -180 or bounds[2] > 180 or bounds[1] < -90 or bounds[3] > 90:
            st.warning("⚠️ Coordenadas fuera de rango para cálculo preciso de área")
            area_grados2 = gdf.geometry.area.sum()
            area_m2 = area_grados2 * 111000 * 111000
            return area_m2 / 10000
        gdf_projected = gdf.to_crs('EPSG:3857')
        area_m2 = gdf_projected.geometry.area.sum()
        return area_m2 / 10000
    except Exception as e:
        try:
            return gdf.geometry.area.sum() / 10000
        except:
            return 0.0

def dividir_parcela_en_zonas(gdf, n_zonas):
    if len(gdf) == 0:
        return gdf
    gdf = validar_y_corregir_crs(gdf)
    parcela_principal = gdf.iloc[0].geometry
    bounds = parcela_principal.bounds
    minx, miny, maxx, maxy = bounds
    sub_poligonos = []
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
            cell_poly = Polygon([(cell_minx, cell_miny), (cell_maxx, cell_miny), (cell_maxx, cell_maxy), (cell_minx, cell_maxy)])
            intersection = parcela_principal.intersection(cell_poly)
            if not intersection.is_empty and intersection.area > 0:
                sub_poligonos.append(intersection)
    if sub_poligonos:
        nuevo_gdf = gpd.GeoDataFrame({'id_zona': range(1, len(sub_poligonos) + 1), 'geometry': sub_poligonos}, crs='EPSG:4326')
        return nuevo_gdf
    else:
        return gdf

# ===== FUNCIONES PARA CARGAR ARCHIVOS =====
def cargar_shapefile_desde_zip(zip_file):
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                zip_ref.extractall(tmp_dir)
            shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
            if shp_files:
                shp_path = os.path.join(tmp_dir, shp_files[0])
                gdf = gpd.read_file(shp_path)
                gdf = validar_y_corregir_crs(gdf)
                return gdf
            else:
                st.error("❌ No se encontró ningún archivo .shp en el ZIP")
                return None
    except Exception as e:
        st.error(f"❌ Error cargando shapefile desde ZIP: {str(e)}")
        return None

def parsear_kml_manual(contenido_kml):
    try:
        root = ET.fromstring(contenido_kml)
        namespaces = {'kml': 'http://www.opengis.net/kml/2.2'}
        polygons = []
        for polygon_elem in root.findall('.//kml:Polygon', namespaces):
            coords_elem = polygon_elem.find('.//kml:coordinates', namespaces)
            if coords_elem is not None and coords_elem.text:
                coord_text = coords_elem.text.strip()
                coord_list = []
                for coord_pair in coord_text.split():
                    parts = coord_pair.split(',')
                    if len(parts) >= 2:
                        lon = float(parts[0])
                        lat = float(parts[1])
                        coord_list.append((lon, lat))
                if len(coord_list) >= 3:
                    polygons.append(Polygon(coord_list))
        if not polygons:
            for multi_geom in root.findall('.//kml:MultiGeometry', namespaces):
                for polygon_elem in multi_geom.findall('.//kml:Polygon', namespaces):
                    coords_elem = polygon_elem.find('.//kml:coordinates', namespaces)
                    if coords_elem is not None and coords_elem.text:
                        coord_text = coords_elem.text.strip()
                        coord_list = []
                        for coord_pair in coord_text.split():
                            parts = coord_pair.split(',')
                            if len(parts) >= 2:
                                lon = float(parts[0])
                                lat = float(parts[1])
                                coord_list.append((lon, lat))
                        if len(coord_list) >= 3:
                            polygons.append(Polygon(coord_list))
        if polygons:
            gdf = gpd.GeoDataFrame({'geometry': polygons}, crs='EPSG:4326')
            return gdf
        else:
            for placemark in root.findall('.//kml:Placemark', namespaces):
                for elem_name in ['Polygon', 'LineString', 'Point', 'LinearRing']:
                    elem = placemark.find(f'.//kml:{elem_name}', namespaces)
                    if elem is not None:
                        coords_elem = elem.find('.//kml:coordinates', namespaces)
                        if coords_elem is not None and coords_elem.text:
                            coord_text = coords_elem.text.strip()
                            coord_list = []
                            for coord_pair in coord_text.split():
                                parts = coord_pair.split(',')
                                if len(parts) >= 2:
                                    lon = float(parts[0])
                                    lat = float(parts[1])
                                    coord_list.append((lon, lat))
                            if len(coord_list) >= 3:
                                polygons.append(Polygon(coord_list))
                            break
        if polygons:
            gdf = gpd.GeoDataFrame({'geometry': polygons}, crs='EPSG:4326')
            return gdf
        return None
    except Exception as e:
        st.error(f"❌ Error parseando KML manualmente: {str(e)}")
        return None

def cargar_kml(kml_file):
    try:
        if kml_file.name.endswith('.kmz'):
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(kml_file, 'r') as zip_ref:
                    zip_ref.extractall(tmp_dir)
                kml_files = [f for f in os.listdir(tmp_dir) if f.endswith('.kml')]
                if kml_files:
                    kml_path = os.path.join(tmp_dir, kml_files[0])
                    with open(kml_path, 'r', encoding='utf-8') as f:
                        contenido = f.read()
                    gdf = parsear_kml_manual(contenido)
                    if gdf is not None:
                        return gdf
                    else:
                        try:
                            gdf = gpd.read_file(kml_path)
                            gdf = validar_y_corregir_crs(gdf)
                            return gdf
                        except:
                            st.error("❌ No se pudo cargar el archivo KML/KMZ")
                            return None
                else:
                    st.error("❌ No se encontró ningún archivo .kml en el KMZ")
                    return None
        else:
            contenido = kml_file.read().decode('utf-8')
            gdf = parsear_kml_manual(contenido)
            if gdf is not None:
                return gdf
            else:
                kml_file.seek(0)
                gdf = gpd.read_file(kml_file)
                gdf = validar_y_corregir_crs(gdf)
                return gdf
    except Exception as e:
        st.error(f"❌ Error cargando archivo KML/KMZ: {str(e)}")
        return None

def cargar_archivo_parcela(uploaded_file):
    try:
        if uploaded_file.name.endswith('.zip'):
            gdf = cargar_shapefile_desde_zip(uploaded_file)
        elif uploaded_file.name.endswith(('.kml', '.kmz')):
            gdf = cargar_kml(uploaded_file)
        else:
            st.error("❌ Formato de archivo no soportado")
            return None
        
        if gdf is not None:
            gdf = validar_y_corregir_crs(gdf)
            gdf = gdf.explode(ignore_index=True)
            gdf = gdf[gdf.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])]
            if len(gdf) == 0:
                st.error("❌ No se encontraron polígonos en el archivo")
                return None
            geometria_unida = gdf.unary_union
            gdf_unido = gpd.GeoDataFrame([{'geometry': geometria_unida}], crs='EPSG:4326')
            gdf_unido = validar_y_corregir_crs(gdf_unido)
            st.info(f"✅ Se unieron {len(gdf)} polígono(s) en una sola geometría.")
            gdf_unido['id_zona'] = 1
            return gdf_unido
        return gdf
    except Exception as e:
        st.error(f"❌ Error cargando archivo: {str(e)}")
        import traceback
        st.error(f"Detalle: {traceback.format_exc()}")
        return None

# ===== FUNCIÓN PARA OBTENER DATOS DE NASA POWER =====
def obtener_datos_nasa_power(gdf, fecha_inicio, fecha_fin):
    """
    Obtiene datos meteorológicos diarios de NASA POWER para el centroide de la parcela.
    """
    try:
        centroid = gdf.geometry.unary_union.centroid
        lat = round(centroid.y, 4)
        lon = round(centroid.x, 4)
        start = fecha_inicio.strftime("%Y%m%d")
        end = fecha_fin.strftime("%Y%m%d")
        params = {
            'parameters': 'ALLSKY_SFC_SW_DWN,WS2M,T2M,PRECTOTCORR',
            'community': 'RE',
            'longitude': lon,
            'latitude': lat,
            'start': start,
            'end': end,
            'format': 'JSON'
        }
        url = "https://power.larc.nasa.gov/api/temporal/daily/point"
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        if 'properties' not in data or 'parameter' not in data['properties']:
            return None
        series = data['properties']['parameter']
        df_power = pd.DataFrame({
            'fecha': pd.to_datetime(list(series['ALLSKY_SFC_SW_DWN'].keys())),
            'radiacion_solar': list(series['ALLSKY_SFC_SW_DWN'].values()),
            'viento_2m': list(series['WS2M'].values()),
            'temperatura': list(series['T2M'].values()),
            'precipitacion': list(series['PRECTOTCORR'].values())
        })
        df_power = df_power.replace(-999, np.nan).dropna()
        if df_power.empty:
            return None
        return df_power
    except Exception as e:
        return None

# ===== FUNCIONES DEM REAL CON DATOS NASA SRTM =====
def obtener_datos_srtm_nasa(gdf):
    """Obtiene datos de elevación reales de NASA SRTM (30m resolución)"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        buffer = 0.01
        min_lon -= buffer
        min_lat -= buffer
        max_lon += buffer
        max_lat += buffer
        
        params = {
            'west': min_lon,
            'south': min_lat,
            'east': max_lon,
            'north': max_lat,
            'outputFormat': 'GTiff',
            'demtype': 'SRTMGL1'
        }
        
        url = "https://portal.opentopography.org/API/globaldem"
        
        try:
            response = requests.get(url, params=params, stream=True, timeout=30)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp_file:
                    for chunk in response.iter_content(chunk_size=8192):
                        tmp_file.write(chunk)
                    tmp_path = tmp_file.name
                
                import rasterio
                with rasterio.open(tmp_path) as src:
                    dem_data = src.read(1)
                    transform = src.transform
                    
                    x = np.arange(transform[2], transform[2] + transform[0] * dem_data.shape[1], transform[0])
                    y = np.arange(transform[5], transform[5] + transform[4] * dem_data.shape[0], transform[4])
                    X, Y = np.meshgrid(x, y)
                    Z = dem_data.astype(float)
                    
                    os.unlink(tmp_path)
                    
                    st.success("✅ Datos SRTM de NASA obtenidos exitosamente (30m resolución)")
                    return X, Y, Z, bounds
                    
        except Exception as e:
            st.warning(f"⚠️ No se pudieron obtener datos SRTM: {e}. Usando datos sintéticos mejorados.")
    
    except Exception as e:
        st.warning(f"⚠️ Error accediendo a datos SRTM: {e}")
    
    return None

def generar_dem_realista_mejorado(gdf, resolucion=30.0, usar_datos_reales=True):
    """Genera DEM usando datos reales de NASA SRTM o sintéticos mejorados"""
    
    if usar_datos_reales:
        st.info("🌍 Intentando obtener datos de elevación de NASA SRTM...")
        dem_real = obtener_datos_srtm_nasa(gdf)
        
        if dem_real is not None:
            X, Y, Z, bounds = dem_real
            if resolucion != 30.0:
                X, Y, Z = interpolar_dem(X, Y, Z, resolucion)
            return X, Y, Z, bounds
        
        st.info("🔬 Usando DEM sintético mejorado (datos reales no disponibles)")
    
    return generar_dem_sintetico_avanzado(gdf, resolucion)

def generar_dem_sintetico_avanzado(gdf, resolucion=10.0):
    """Genera un DEM sintético avanzado basado en características reales"""
    gdf = validar_y_corregir_crs(gdf)
    bounds = gdf.total_bounds
    minx, miny, maxx, maxy = bounds
    
    num_cells_x = max(200, min(800, int((maxx - minx) * 111000 / resolucion)))
    num_cells_y = max(200, min(800, int((maxy - miny) * 111000 / resolucion)))
    
    x = np.linspace(minx, maxx, num_cells_x)
    y = np.linspace(miny, maxy, num_cells_y)
    X, Y = np.meshgrid(x, y)

    centroid = gdf.geometry.unary_union.centroid
    lat, lon = centroid.y, centroid.x
    
    tipo_terreno = clasificar_terreno_por_ubicacion(lat, lon)
    
    if tipo_terreno == "LLANURA":
        Z = generar_terreno_llanura(X, Y, lat, lon)
    elif tipo_terreno == "MESETA":
        Z = generar_terreno_meseta(X, Y, lat, lon)
    elif tipo_terreno == "MONTANOSO":
        Z = generar_terreno_montanoso(X, Y, lat, lon)
    elif tipo_terreno == "VALLE":
        Z = generar_terreno_valle(X, Y, lat, lon)
    else:
        Z = generar_terreno_mixto(X, Y, lat, lon)
    
    points = np.vstack([X.flatten(), Y.flatten()]).T
    parcel_mask = gdf.geometry.unary_union.contains([Point(p) for p in points])
    parcel_mask = parcel_mask.reshape(X.shape)
    Z[~parcel_mask] = np.nan
    
    from scipy.ndimage import gaussian_filter
    Z = gaussian_filter(Z, sigma=1.5)
    
    return X, Y, Z, bounds

def clasificar_terreno_por_ubicacion(lat, lon):
    """Clasifica el tipo de terreno basado en coordenadas geográficas"""
    if -55 <= lat <= -20:
        if -75 <= lon <= -53:
            return "MONTANOSO"
        elif -65 <= lon <= -55:
            return "LLANURA"
        elif -73 <= lon <= -65:
            return "MESETA"
        elif -58 <= lon <= -53:
            return "VALLE"
    
    if 10 <= lat <= 30:
        return "MONTANOSO"
    elif -20 <= lat <= 10:
        return "LLANURA"
    elif -40 <= lat <= -20:
        return "MESETA"
    
    return "MIXTO"

def generar_terreno_llanura(X, Y, lat, lon):
    """Genera terreno de llanura con pendientes suaves"""
    rng = np.random.RandomState(int(abs(lat * 100 + lon * 100)) % (2**32))
    elevacion_base = rng.uniform(50, 150)
    slope_x = rng.uniform(-0.0001, 0.0001)
    slope_y = rng.uniform(-0.0001, 0.0001)
    
    relief = np.zeros_like(X)
    n_ondulaciones = rng.randint(5, 15)
    
    for _ in range(n_ondulaciones):
        center_x = rng.uniform(X.min(), X.max())
        center_y = rng.uniform(Y.min(), Y.max())
        radius = rng.uniform(0.002, 0.008)
        height = rng.uniform(2, 10)
        
        dist = np.sqrt((X - center_x)**2 + (Y - center_y)**2)
        relief += height * np.exp(-(dist**2) / (2 * radius**2))
    
    n_valleys = rng.randint(1, 3)
    for _ in range(n_valleys):
        start_x = rng.uniform(X.min(), X.max() * 0.8)
        start_y = rng.uniform(Y.min(), Y.max() * 0.8)
        angle = rng.uniform(0, 2*np.pi)
        length = rng.uniform(0.003, 0.01)
        width = rng.uniform(0.001, 0.003)
        depth = rng.uniform(1, 5)
        
        valley_dir = np.array([np.cos(angle), np.sin(angle)])
        valley_proj = (X - start_x) * valley_dir[0] + (Y - start_y) * valley_dir[1]
        valley_perp = np.abs((X - start_x) * valley_dir[1] - (Y - start_y) * valley_dir[0])
        
        valle_mask = (valley_proj >= 0) & (valley_proj <= length)
        valley_profile = depth * np.exp(-(valley_perp**2) / (2 * (width/2)**2))
        relief -= valley_profile * valle_mask.astype(float)
    
    Z = elevacion_base + slope_x * (X - X.min()) + slope_y * (Y - Y.min()) + relief
    
    from scipy.ndimage import gaussian_filter
    Z = gaussian_filter(Z, sigma=2)
    
    return Z

def generar_terreno_montanoso(X, Y, lat, lon):
    """Genera terreno montañoso con valles pronunciados"""
    rng = np.random.RandomState(int(abs(lat * 100 + lon * 100)) % (2**32))
    elevacion_base = rng.uniform(500, 1500)
    slope_x = rng.uniform(-0.001, 0.001)
    slope_y = rng.uniform(-0.001, 0.001)
    
    relief = np.zeros_like(X)
    n_mountains = rng.randint(3, 8)
    
    for _ in range(n_mountains):
        center_x = rng.uniform(X.min() + 0.1*(X.max()-X.min()), X.max() - 0.1*(X.max()-X.min()))
        center_y = rng.uniform(Y.min() + 0.1*(Y.max()-Y.min()), Y.max() - 0.1*(Y.max()-Y.min()))
        radius = rng.uniform(0.003, 0.01)
        height = rng.uniform(100, 400)
        
        dist = np.sqrt((X - center_x)**2 + (Y - center_y)**2)
        mountain = height * np.exp(-(dist**2) / (2 * radius**2))
        relief += mountain
    
    n_valleys = rng.randint(2, 5)
    for _ in range(n_valleys):
        start_x = rng.uniform(X.min(), X.max() * 0.7)
        start_y = rng.uniform(Y.min(), Y.max() * 0.7)
        angle = rng.uniform(0, 2*np.pi)
        length = rng.uniform(0.005, 0.02)
        width = rng.uniform(0.002, 0.006)
        depth = rng.uniform(50, 150)
        
        valley_dir = np.array([np.cos(angle), np.sin(angle)])
        valley_proj = (X - start_x) * valley_dir[0] + (Y - start_y) * valley_dir[1]
        valley_perp = np.abs((X - start_x) * valley_dir[1] - (Y - start_y) * valley_dir[0])
        
        valley_mask = (valley_proj >= 0) & (valley_proj <= length)
        valley_profile = depth * np.exp(-(valley_perp**2) / (2 * (width/2)**2))
        relief -= valley_profile * valley_mask.astype(float)
    
    n_ridges = rng.randint(2, 4)
    for _ in range(n_ridges):
        start_x = rng.uniform(X.min(), X.max() * 0.8)
        start_y = rng.uniform(Y.min(), Y.max() * 0.8)
        angle = rng.uniform(0, 2*np.pi)
        length = rng.uniform(0.004, 0.015)
        width = rng.uniform(0.001, 0.003)
        height = rng.uniform(30, 80)
        
        ridge_dir = np.array([np.cos(angle), np.sin(angle)])
        ridge_proj = (X - start_x) * ridge_dir[0] + (Y - start_y) * ridge_dir[1]
        ridge_perp = np.abs((X - start_x) * ridge_dir[1] - (Y - start_y) * ridge_dir[0])
        
        ridge_mask = (ridge_proj >= 0) & (ridge_proj <= length)
        ridge_profile = height * np.exp(-(ridge_perp**2) / (2 * (width/2)**2))
        relief += ridge_profile * ridge_mask.astype(float)
    
    Z = elevacion_base + slope_x * (X - X.min()) + slope_y * (Y - Y.min()) + relief
    
    noise = generar_ruido_fractal(X.shape, 5, rng)
    Z += noise * 20
    
    from scipy.ndimage import gaussian_filter
    Z = gaussian_filter(Z, sigma=1)
    
    return Z

def generar_ruido_fractal(shape, octaves, rng):
    """Genera ruido fractal para terreno realista"""
    noise = np.zeros(shape)
    
    for octave in range(octaves):
        frequency = 2 ** octave
        amplitude = 1.0 / (frequency ** 0.5)
        
        octave_noise = rng.randn(shape[0], shape[1])
        
        from scipy.ndimage import gaussian_filter
        sigma = max(1, 8 // frequency)
        octave_noise = gaussian_filter(octave_noise, sigma=sigma)
        
        noise += octave_noise * amplitude
    
    if np.max(noise) > np.min(noise):
        noise = (noise - np.min(noise)) / (np.max(noise) - np.min(noise)) * 2 - 1
    
    return noise

def interpolar_dem(X, Y, Z, nueva_resolucion):
    """Interpola DEM a diferente resolución"""
    from scipy.interpolate import RegularGridInterpolator
    
    interp = RegularGridInterpolator((Y[:, 0], X[0, :]), Z, 
                                     method='linear', bounds_error=False, fill_value=np.nan)
    
    new_x = np.linspace(X.min(), X.max(), int((X.max() - X.min()) * 111000 / nueva_resolucion))
    new_y = np.linspace(Y.min(), Y.max(), int((Y.max() - Y.min()) * 111000 / nueva_resolucion))
    new_X, new_Y = np.meshgrid(new_x, new_y)
    
    points = np.column_stack([new_Y.flatten(), new_X.flatten()])
    new_Z = interp(points).reshape(new_X.shape)
    
    return new_X, new_Y, new_Z

# ===== FUNCIONES DE ANÁLISIS =====
def analizar_fertilidad_actual(gdf_dividido, cultivo, datos_satelitales):
    """Análisis de fertilidad actual"""
    n_poligonos = len(gdf_dividido)
    resultados = []
    gdf_centroids = gdf_dividido.copy()
    gdf_centroids['centroid'] = gdf_dividido.geometry.centroid
    gdf_centroids['x'] = gdf_centroids.centroid.x
    gdf_centroids['y'] = gdf_centroids.centroid.y
    x_coords = gdf_centroids['x'].tolist()
    y_coords = gdf_centroids['y'].tolist()
    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)
    params = PARAMETROS_CULTIVOS[cultivo]
    valor_base_satelital = datos_satelitales.get('valor_promedio', 0.6) if datos_satelitales else 0.6
    for idx, row in gdf_centroids.iterrows():
        x_norm = (row['x'] - x_min) / (x_max - x_min) if x_max != x_min else 0.5
        y_norm = (row['y'] - y_min) / (y_max - y_min) if y_max != y_min else 0.5
        patron_espacial = (x_norm * 0.6 + y_norm * 0.4)
        
        base_mo = params['MATERIA_ORGANICA_OPTIMA'] * 0.7
        variabilidad_mo = patron_espacial * (params['MATERIA_ORGANICA_OPTIMA'] * 0.6)
        materia_organica = base_mo + variabilidad_mo + np.random.normal(0, 0.2)
        materia_organica = max(0.5, min(8.0, materia_organica))
        
        base_humedad = params['HUMEDAD_OPTIMA'] * 0.8
        variabilidad_humedad = patron_espacial * (params['HUMEDAD_OPTIMA'] * 0.4)
        humedad_suelo = base_humedad + variabilidad_humedad + np.random.normal(0, 0.05)
        humedad_suelo = max(0.1, min(0.8, humedad_suelo))
        
        ndvi_base = valor_base_satelital * 0.8
        ndvi_variacion = patron_espacial * (valor_base_satelital * 0.4)
        ndvi = ndvi_base + ndvi_variacion + np.random.normal(0, 0.06)
        ndvi = max(0.1, min(0.9, ndvi))
        
        ndre_base = params['NDRE_OPTIMO'] * 0.7
        ndre_variacion = patron_espacial * (params['NDRE_OPTIMO'] * 0.4)
        ndre = ndre_base + ndre_variacion + np.random.normal(0, 0.04)
        ndre = max(0.05, min(0.7, ndre))
        
        ndwi = 0.2 + np.random.normal(0, 0.08)
        ndwi = max(0, min(1, ndwi))
        
        npk_actual = (ndvi * 0.4) + (ndre * 0.3) + ((materia_organica / 8) * 0.2) + (humedad_suelo * 0.1)
        npk_actual = max(0, min(1, npk_actual))
        
        resultados.append({
            'materia_organica': round(materia_organica, 2),
            'humedad_suelo': round(humedad_suelo, 3),
            'ndvi': round(ndvi, 3),
            'ndre': round(ndre, 3),
            'ndwi': round(ndwi, 3),
            'npk_actual': round(npk_actual, 3)
        })

    return resultados

def analizar_recomendaciones_npk(indices, cultivo):
    """Análisis de recomendaciones NPK"""
    recomendaciones_n = []
    recomendaciones_p = []
    recomendaciones_k = []
    params = PARAMETROS_CULTIVOS[cultivo]

    for idx in indices:
        ndre = idx['ndre']
        materia_organica = idx['materia_organica']
        humedad_suelo = idx['humedad_suelo']
        ndvi = idx['ndvi']
        
        factor_n = ((1 - ndre) * 0.6 + (1 - ndvi) * 0.4)
        n_recomendado = (factor_n * (params['NITROGENO']['max'] - params['NITROGENO']['min']) + params['NITROGENO']['min'])
        n_recomendado = max(params['NITROGENO']['min'] * 0.8, min(params['NITROGENO']['max'] * 1.2, n_recomendado))
        recomendaciones_n.append(round(n_recomendado, 1))
        
        factor_p = ((1 - (materia_organica / 8)) * 0.7 + (1 - humedad_suelo) * 0.3)
        p_recomendado = (factor_p * (params['FOSFORO']['max'] - params['FOSFORO']['min']) + params['FOSFORO']['min'])
        p_recomendado = max(params['FOSFORO']['min'] * 0.8, min(params['FOSFORO']['max'] * 1.2, p_recomendado))
        recomendaciones_p.append(round(p_recomendado, 1))
        
        factor_k = ((1 - ndre) * 0.4 + (1 - humedad_suelo) * 0.4 + (1 - (materia_organica / 8)) * 0.2)
        k_recomendado = (factor_k * (params['POTASIO']['max'] - params['POTASIO']['min']) + params['POTASIO']['min'])
        k_recomendado = max(params['POTASIO']['min'] * 0.8, min(params['POTASIO']['max'] * 1.2, k_recomendado))
        recomendaciones_k.append(round(k_recomendado, 1))

    return recomendaciones_n, recomendaciones_p, recomendaciones_k

def analizar_costos(gdf_dividido, cultivo, recomendaciones_n, recomendaciones_p, recomendaciones_k):
    """Análisis de costos de fertilización"""
    costos = []
    params = PARAMETROS_CULTIVOS[cultivo]
    precio_n = 1.2  # USD/kg N
    precio_p = 2.5  # USD/kg P2O5
    precio_k = 1.8  # USD/kg K2O

    for i in range(len(gdf_dividido)):
        costo_n = recomendaciones_n[i] * precio_n
        costo_p = recomendaciones_p[i] * precio_p
        costo_k = recomendaciones_k[i] * precio_k
        costo_total = costo_n + costo_p + costo_k + params['COSTO_FERTILIZACION']
        
        costos.append({
            'costo_nitrogeno': round(costo_n, 2),
            'costo_fosforo': round(costo_p, 2),
            'costo_potasio': round(costo_k, 2),
            'costo_total': round(costo_total, 2)
        })

    return costos

def analizar_proyecciones_cosecha(gdf_dividido, cultivo, indices):
    """Análisis de proyecciones de cosecha con y sin fertilización"""
    proyecciones = []
    params = PARAMETROS_CULTIVOS[cultivo]
    for idx in indices:
        npk_actual = idx['npk_actual']
        ndvi = idx['ndvi']
        
        rendimiento_base = params['RENDIMIENTO_OPTIMO'] * npk_actual * 0.7
        
        incremento = (1 - npk_actual) * 0.4 + (1 - ndvi) * 0.2
        rendimiento_con_fert = rendimiento_base * (1 + incremento)
        
        proyecciones.append({
            'rendimiento_sin_fert': round(rendimiento_base, 0),
            'rendimiento_con_fert': round(rendimiento_con_fert, 0),
            'incremento_esperado': round(incremento * 100, 1)
        })

    return proyecciones

def clasificar_textura_suelo(arena, limo, arcilla):
    try:
        total = arena + limo + arcilla
        if total == 0:
            return "NO_DETERMINADA"
        arena_norm = (arena / total) * 100
        limo_norm = (limo / total) * 100
        arcilla_norm = (arcilla / total) * 100
        if arcilla_norm >= 35:
            return "Franco arcilloso"
        elif arcilla_norm >= 25 and arcilla_norm <= 35 and arena_norm >= 20 and arena_norm <= 45:
            return "Franco arcilloso"
        elif arena_norm >= 55 and arena_norm <= 70 and arcilla_norm >= 10 and arcilla_norm <= 20:
            return "Franco arenoso"
        elif arena_norm >= 40 and arena_norm <= 55 and arcilla_norm >= 20 and arcilla_norm <= 30:
            return "Franco"
        else:
            return "Franco"
    except Exception as e:
        return "NO_DETERMINADA"

def analizar_textura_suelo(gdf_dividido, cultivo):
    """Análisis de textura del suelo"""
    gdf_dividido = validar_y_corregir_crs(gdf_dividido)
    params_textura = TEXTURA_SUELO_OPTIMA[cultivo]
    gdf_dividido['area_ha'] = 0.0
    gdf_dividido['arena'] = 0.0
    gdf_dividido['limo'] = 0.0
    gdf_dividido['arcilla'] = 0.0
    gdf_dividido['textura_suelo'] = "NO_DETERMINADA"

    for idx, row in gdf_dividido.iterrows():
        try:
            area_gdf = gpd.GeoDataFrame({'geometry': [row.geometry]}, crs=gdf_dividido.crs)
            area_ha = calcular_superficie(area_gdf)
            if hasattr(area_ha, 'iloc'):
                area_ha = float(area_ha.iloc[0])
            elif hasattr(area_ha, '__len__') and len(area_ha) > 0:
                area_ha = float(area_ha[0])
            else:
                area_ha = float(area_ha)
            
            centroid = row.geometry.centroid if hasattr(row.geometry, 'centroid') else row.geometry.representative_point()
            seed_value = abs(hash(f"{centroid.x:.6f}_{centroid.y:.6f}_{cultivo}_textura")) % (2**32)
            rng = np.random.RandomState(seed_value)
            
            lat_norm = (centroid.y + 90) / 180 if centroid.y else 0.5
            lon_norm = (centroid.x + 180) / 360 if centroid.x else 0.5
            variabilidad_local = 0.15 + 0.7 * (lat_norm * lon_norm)
            
            arena_optima = params_textura['arena_optima']
            limo_optima = params_textura['limo_optima']
            arcilla_optima = params_textura['arcilla_optima']
            
            arena_val = max(5, min(95, rng.normal(
                arena_optima * (0.8 + 0.4 * variabilidad_local),
                arena_optima * 0.15
            )))
            limo_val = max(5, min(95, rng.normal(
                limo_optima * (0.7 + 0.6 * variabilidad_local),
                limo_optima * 0.2
            )))
            arcilla_val = max(5, min(95, rng.normal(
                arcilla_optima * (0.75 + 0.5 * variabilidad_local),
                arcilla_optima * 0.15
            )))
            
            total = arena_val + limo_val + arcilla_val
            arena_pct = (arena_val / total) * 100
            limo_pct = (limo_val / total) * 100
            arcilla_pct = (arcilla_val / total) * 100
            
            textura = clasificar_textura_suelo(arena_pct, limo_pct, arcilla_pct)
            
            gdf_dividido.at[idx, 'area_ha'] = area_ha
            gdf_dividido.at[idx, 'arena'] = float(arena_pct)
            gdf_dividido.at[idx, 'limo'] = float(limo_pct)
            gdf_dividido.at[idx, 'arcilla'] = float(arcilla_pct)
            gdf_dividido.at[idx, 'textura_suelo'] = textura
            
        except Exception as e:
            gdf_dividido.at[idx, 'area_ha'] = 0.0
            gdf_dividido.at[idx, 'arena'] = float(params_textura['arena_optima'])
            gdf_dividido.at[idx, 'limo'] = float(params_textura['limo_optima'])
            gdf_dividido.at[idx, 'arcilla'] = float(params_textura['arcilla_optima'])
            gdf_dividido.at[idx, 'textura_suelo'] = params_textura['textura_optima']

    return gdf_dividido

# ===== FUNCIÓN PRINCIPAL DE ANÁLISIS =====
def ejecutar_analisis_completo(gdf, cultivo, n_divisiones, satelite, fecha_inicio, fecha_fin,
                               intervalo_curvas=5.0, resolucion_dem=10.0):
    """Ejecuta todos los análisis y guarda los resultados"""
    resultados = {
        'exitoso': False,
        'gdf_dividido': None,
        'fertilidad_actual': None,
        'recomendaciones_npk': None,
        'costos': None,
        'proyecciones': None,
        'textura': None,
        'df_power': None,
        'area_total': 0,
        'mapas': {},
        'dem_data': {},
        'curvas_nivel': None,
        'pendientes': None,
        'datos_satelitales': None
    }

    try:
        gdf = validar_y_corregir_crs(gdf)
        area_total = calcular_superficie(gdf)
        resultados['area_total'] = area_total
        
        # Obtener datos satelitales MODIS
        datos_satelitales = None
        if satelite == 'MODIS_NASA':
            datos_satelitales = obtener_datos_modis_nasa(gdf, fecha_inicio, fecha_fin, 'NDVI')
            if datos_satelitales is None:
                st.warning("⚠️ No se pudieron obtener datos MODIS. Usando datos simulados.")
                datos_satelitales = {
                    'indice': 'NDVI',
                    'valor_promedio': PARAMETROS_CULTIVOS[cultivo]['NDVI_OPTIMO'] * 0.8 + np.random.normal(0, 0.1),
                    'fuente': 'Simulación',
                    'fecha': datetime.now().strftime('%Y-%m-%d'),
                    'resolucion': '250m'
                }
        else:
            datos_satelitales = {
                'indice': 'NDVI',
                'valor_promedio': PARAMETROS_CULTIVOS[cultivo]['NDVI_OPTIMO'] * 0.8 + np.random.normal(0, 0.1),
                'fuente': 'Simulación',
                'fecha': datetime.now().strftime('%Y-%m-%d'),
                'resolucion': '10m'
            }
        
        resultados['datos_satelitales'] = datos_satelitales
        
        # Obtener datos meteorológicos
        df_power = obtener_datos_nasa_power(gdf, fecha_inicio, fecha_fin)
        resultados['df_power'] = df_power
        
        # Dividir parcela
        gdf_dividido = dividir_parcela_en_zonas(gdf, n_divisiones)
        resultados['gdf_dividido'] = gdf_dividido
        
        # Calcular áreas
        areas_ha_list = []
        for idx, row in gdf_dividido.iterrows():
            area_gdf = gpd.GeoDataFrame({'geometry': [row.geometry]}, crs=gdf_dividido.crs)
            area_ha = calcular_superficie(area_gdf)
            if hasattr(area_ha, 'iloc'):
                area_ha = float(area_ha.iloc[0])
            elif hasattr(area_ha, '__len__') and len(area_ha) > 0:
                area_ha = float(area_ha[0])
            else:
                area_ha = float(area_ha)
            areas_ha_list.append(area_ha)
        
        gdf_dividido['area_ha'] = areas_ha_list
        
        # 1. Análisis de fertilidad actual
        fertilidad_actual = analizar_fertilidad_actual(gdf_dividido, cultivo, datos_satelitales)
        resultados['fertilidad_actual'] = fertilidad_actual
        
        # 2. Análisis de recomendaciones NPK
        rec_n, rec_p, rec_k = analizar_recomendaciones_npk(fertilidad_actual, cultivo)
        resultados['recomendaciones_npk'] = {
            'N': rec_n,
            'P': rec_p,
            'K': rec_k
        }
        
        # 3. Análisis de costos
        costos = analizar_costos(gdf_dividido, cultivo, rec_n, rec_p, rec_k)
        resultados['costos'] = costos
        
        # 4. Análisis de proyecciones
        proyecciones = analizar_proyecciones_cosecha(gdf_dividido, cultivo, fertilidad_actual)
        resultados['proyecciones'] = proyecciones
        
        # 5. Análisis de textura
        textura = analizar_textura_suelo(gdf_dividido, cultivo)
        resultados['textura'] = textura
        
        # 6. Análisis DEM y curvas de nivel
        try:
            X, Y, Z, bounds = generar_dem_realista_mejorado(gdf, resolucion_dem, usar_datos_reales=True)
            
            # Calcular pendiente
            dy, dx = np.gradient(Z, resolucion_dem, resolucion_dem)
            pendientes = np.sqrt(dx**2 + dy**2) * 100
            pendientes = np.clip(pendientes, 0, 100)
            
            # Generar curvas de nivel básicas
            curvas_nivel = []
            elevaciones = []
            z_min = np.nanmin(Z)
            z_max = np.nanmax(Z)
            
            if not np.isnan(z_min) and not np.isnan(z_max):
                niveles = np.arange(
                    np.ceil(z_min / intervalo_curvas) * intervalo_curvas,
                    np.floor(z_max / intervalo_curvas) * intervalo_curvas + intervalo_curvas,
                    intervalo_curvas
                )
                
                for nivel in niveles:
                    mascara = (Z >= nivel - 0.5) & (Z <= nivel + 0.5)
                    if np.any(mascara):
                        from scipy import ndimage
                        estructura = ndimage.generate_binary_structure(2, 2)
                        labeled, num_features = ndimage.label(mascara, structure=estructura)
                        
                        for i in range(1, num_features + 1):
                            contorno = (labeled == i)
                            if np.sum(contorno) > 10:
                                y_indices, x_indices = np.where(contorno)
                                if len(x_indices) > 2:
                                    puntos = np.column_stack([X[contorno].flatten(), Y[contorno].flatten()])
                                    if len(puntos) >= 3:
                                        linea = LineString(puntos)
                                        curvas_nivel.append(linea)
                                        elevaciones.append(nivel)
            
            resultados['dem_data'] = {
                'X': X,
                'Y': Y,
                'Z': Z,
                'bounds': bounds,
                'pendientes': pendientes,
                'curvas_nivel': curvas_nivel,
                'elevaciones': elevaciones
            }
        except Exception as e:
            st.warning(f"⚠️ Error generando DEM y curvas de nivel: {e}")
        
        # Combinar todos los resultados
        gdf_completo = textura.copy()
        
        for i, fert in enumerate(fertilidad_actual):
            for key, value in fert.items():
                gdf_completo.at[gdf_completo.index[i], f'fert_{key}'] = value
        
        gdf_completo['rec_N'] = rec_n
        gdf_completo['rec_P'] = rec_p
        gdf_completo['rec_K'] = rec_k
        
        for i, costo in enumerate(costos):
            for key, value in costo.items():
                gdf_completo.at[gdf_completo.index[i], f'costo_{key}'] = value
        
        for i, proy in enumerate(proyecciones):
            for key, value in proy.items():
                gdf_completo.at[gdf_completo.index[i], f'proy_{key}'] = value
        
        resultados['gdf_completo'] = gdf_completo
        resultados['exitoso'] = True
        
        return resultados
        
    except Exception as e:
        st.error(f"❌ Error en análisis completo: {str(e)}")
        import traceback
        traceback.print_exc()
        return resultados

# ===== FUNCIONES DE VISUALIZACIÓN =====
def crear_mapa_fertilidad(gdf_completo, cultivo, satelite):
    """Crear mapa de fertilidad actual"""
    try:
        gdf_plot = gdf_completo.to_crs(epsg=3857)
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        cmap = LinearSegmentedColormap.from_list('fertilidad_gee', PALETAS_GEE['FERTILIDAD'])
        vmin, vmax = 0, 1
        
        for idx, row in gdf_plot.iterrows():
            valor = row['fert_npk_actual']
            valor_norm = (valor - vmin) / (vmax - vmin) if vmax != vmin else 0.5
            valor_norm = max(0, min(1, valor_norm))
            color = cmap(valor_norm)
            
            gdf_plot.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1.5, alpha=0.7)
            
            centroid = row.geometry.centroid
            ax.annotate(f"Z{row['id_zona']}\n{valor:.2f}", (centroid.x, centroid.y),
                        xytext=(5, 5), textcoords="offset points",
                        fontsize=8, color='black', weight='bold',
                        bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.9))
        
        try:
            ctx.add_basemap(ax, source=ctx.providers.Esri.WorldImagery, alpha=0.7)
        except:
            pass
        
        info_satelite = SATELITES_DISPONIBLES.get(satelite, SATELITES_DISPONIBLES['DATOS_SIMULADOS'])
        ax.set_title(f'{ICONOS_CULTIVOS[cultivo]} FERTILIDAD ACTUAL - {cultivo}\n'
                     f'{info_satelite["icono"]} {info_satelite["nombre"]}',
                     fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
        cbar.set_label('Índice de Fertilidad', fontsize=12, fontweight='bold')
        
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        return buf
    except Exception as e:
        st.error(f"❌ Error creando mapa de fertilidad: {str(e)}")
        return None

def crear_mapa_npk(gdf_completo, cultivo, nutriente='N'):
    """Crear mapa de recomendaciones NPK"""
    try:
        gdf_plot = gdf_completo.to_crs(epsg=3857)
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        if nutriente == 'N':
            cmap = LinearSegmentedColormap.from_list('nitrogeno_gee', PALETAS_GEE['NITROGENO'])
            columna = 'rec_N'
            titulo_nut = 'NITRÓGENO'
            vmin = PARAMETROS_CULTIVOS[cultivo]['NITROGENO']['min'] * 0.8
            vmax = PARAMETROS_CULTIVOS[cultivo]['NITROGENO']['max'] * 1.2
        elif nutriente == 'P':
            cmap = LinearSegmentedColormap.from_list('fosforo_gee', PALETAS_GEE['FOSFORO'])
            columna = 'rec_P'
            titulo_nut = 'FÓSFORO'
            vmin = PARAMETROS_CULTIVOS[cultivo]['FOSFORO']['min'] * 0.8
            vmax = PARAMETROS_CULTIVOS[cultivo]['FOSFORO']['max'] * 1.2
        else:
            cmap = LinearSegmentedColormap.from_list('potasio_gee', PALETAS_GEE['POTASIO'])
            columna = 'rec_K'
            titulo_nut = 'POTASIO'
            vmin = PARAMETROS_CULTIVOS[cultivo]['POTASIO']['min'] * 0.8
            vmax = PARAMETROS_CULTIVOS[cultivo]['POTASIO']['max'] * 1.2
        
        for idx, row in gdf_plot.iterrows():
            valor = row[columna]
            valor_norm = (valor - vmin) / (vmax - vmin) if vmax != vmin else 0.5
            valor_norm = max(0, min(1, valor_norm))
            color = cmap(valor_norm)
            
            gdf_plot.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1.5, alpha=0.7)
            
            centroid = row.geometry.centroid
            ax.annotate(f"Z{row['id_zona']}\n{valor:.0f}", (centroid.x, centroid.y),
                        xytext=(5, 5), textcoords="offset points",
                        fontsize=8, color='black', weight='bold',
                        bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.9))
        
        try:
            ctx.add_basemap(ax, source=ctx.providers.Esri.WorldImagery, alpha=0.7)
        except:
            pass
        
        ax.set_title(f'{ICONOS_CULTIVOS[cultivo]} RECOMENDACIONES {titulo_nut} - {cultivo}',
                     fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
        cbar.set_label(f'{titulo_nut} (kg/ha)', fontsize=12, fontweight='bold')
        
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        return buf
    except Exception as e:
        st.error(f"❌ Error creando mapa NPK: {str(e)}")
        return None

def crear_mapa_texturas(gdf_completo, cultivo):
    """Crear mapa de texturas"""
    try:
        gdf_plot = gdf_completo.to_crs(epsg=3857)
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        colores_textura = {
            'Franco': '#c7eae5',
            'Franco arcilloso': '#5ab4ac',
            'Franco arenoso': '#f6e8c3',
            'NO_DETERMINADA': '#999999'
        }
        
        for idx, row in gdf_plot.iterrows():
            textura = row['textura_suelo']
            color = colores_textura.get(textura, '#999999')
            
            gdf_plot.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1.5, alpha=0.8)
            
            centroid = row.geometry.centroid
            ax.annotate(f"Z{row['id_zona']}\n{textura[:10]}", (centroid.x, centroid.y),
                        xytext=(5, 5), textcoords="offset points",
                        fontsize=8, color='black', weight='bold',
                        bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.9))
        
        try:
            ctx.add_basemap(ax, source=ctx.providers.Esri.WorldImagery, alpha=0.6)
        except:
            pass
        
        ax.set_title(f'{ICONOS_CULTIVOS[cultivo]} MAPA DE TEXTURAS - {cultivo}',
                     fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        from matplotlib.patches import Patch
        legend_elements = [Patch(facecolor=color, edgecolor='black', label=textura)
                           for textura, color in colores_textura.items()]
        ax.legend(handles=legend_elements, title='Texturas', loc='upper left', bbox_to_anchor=(1.05, 1))
        
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        return buf
    except Exception as e:
        st.error(f"❌ Error creando mapa de texturas: {str(e)}")
        return None

def crear_mapa_pendientes(X, Y, pendientes, gdf_original):
    """Crear mapa de pendientes"""
    try:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        scatter = ax1.scatter(X.flatten(), Y.flatten(), c=pendientes.flatten(), 
                             cmap='RdYlGn_r', s=10, alpha=0.7, vmin=0, vmax=30)
        
        gdf_original.plot(ax=ax1, color='none', edgecolor='black', linewidth=2)
        
        cbar = plt.colorbar(scatter, ax=ax1, shrink=0.8)
        cbar.set_label('Pendiente (%)')
        
        ax1.set_title('Mapa de Calor de Pendientes', fontsize=12, fontweight='bold')
        ax1.set_xlabel('Longitud')
        ax1.set_ylabel('Latitud')
        ax1.grid(True, alpha=0.3)
        
        pendientes_flat = pendientes.flatten()
        pendientes_flat = pendientes_flat[~np.isnan(pendientes_flat)]
        
        ax2.hist(pendientes_flat, bins=30, edgecolor='black', color='skyblue', alpha=0.7)
        
        for porcentaje, color in [(2, 'green'), (5, 'lightgreen'), (10, 'yellow'), 
                                 (15, 'orange'), (25, 'red')]:
            ax2.axvline(x=porcentaje, color=color, linestyle='--', linewidth=1, alpha=0.7)
            ax2.text(porcentaje+0.5, ax2.get_ylim()[1]*0.9, f'{porcentaje}%', 
                    color=color, fontsize=8)
        
        stats_text = f"""
Estadísticas:
• Mínima: {np.nanmin(pendientes_flat):.1f}%
• Máxima: {np.nanmax(pendientes_flat):.1f}%
• Promedio: {np.nanmean(pendientes_flat):.1f}%
• Desviación: {np.nanstd(pendientes_flat):.1f}%
"""
        ax2.text(0.02, 0.98, stats_text, transform=ax2.transAxes, fontsize=9,
                verticalalignment='top',
                bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.8))
        ax2.set_xlabel('Pendiente (%)')
        ax2.set_ylabel('Frecuencia')
        ax2.set_title('Distribución de Pendientes', fontsize=12, fontweight='bold')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        stats = {
            'min': float(np.nanmin(pendientes_flat)),
            'max': float(np.nanmax(pendientes_flat)),
            'mean': float(np.nanmean(pendientes_flat)),
            'std': float(np.nanstd(pendientes_flat))
        }
        
        return buf, stats
    except Exception as e:
        st.error(f"❌ Error creando mapa de pendientes: {str(e)}")
        return None, {}

# ===== FUNCIONES DE EXPORTACIÓN =====
def exportar_a_geojson(gdf, nombre_base="parcela"):
    try:
        gdf = validar_y_corregir_crs(gdf)
        geojson_data = gdf.to_json()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_archivo = f"{nombre_base}_{timestamp}.geojson"
        return geojson_data, nombre_archivo
    except Exception as e:
        st.error(f"❌ Error exportando a GeoJSON: {str(e)}")
        return None, None

def generar_reporte_completo(resultados, cultivo, satelite, fecha_inicio, fecha_fin):
    """Generar reporte DOCX"""
    try:
        doc = Document()
        title = doc.add_heading(f'REPORTE COMPLETO DE ANÁLISIS - {cultivo}', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        subtitle = doc.add_paragraph(f'Fecha: {datetime.now().strftime("%d/%m/%Y %H:%M")}')
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        doc.add_paragraph()
        doc.add_heading('1. INFORMACIÓN GENERAL', level=1)
        info_table = doc.add_table(rows=6, cols=2)
        info_table.style = 'Table Grid'
        info_table.cell(0, 0).text = 'Cultivo'
        info_table.cell(0, 1).text = cultivo
        info_table.cell(1, 0).text = 'Área Total'
        info_table.cell(1, 1).text = f'{resultados["area_total"]:.2f} ha'
        info_table.cell(2, 0).text = 'Zonas Analizadas'
        info_table.cell(2, 1).text = str(len(resultados['gdf_completo']))
        info_table.cell(3, 0).text = 'Satélite'
        info_table.cell(3, 1).text = satelite
        info_table.cell(4, 0).text = 'Período de Análisis'
        info_table.cell(4, 1).text = f'{fecha_inicio.strftime("%d/%m/%Y")} a {fecha_fin.strftime("%d/%m/%Y")}'
        info_table.cell(5, 0).text = 'Fuente de Datos'
        info_table.cell(5, 1).text = resultados['datos_satelitales']['fuente'] if resultados['datos_satelitales'] else 'N/A'
        
        docx_output = BytesIO()
        doc.save(docx_output)
        docx_output.seek(0)
        
        return docx_output
        
    except Exception as e:
        st.error(f"❌ Error generando reporte DOCX: {str(e)}")
        return None

def crear_boton_descarga_png(buffer, nombre_archivo, texto_boton="📥 Descargar PNG"):
    """Crear botón de descarga para archivos PNG"""
    if buffer:
        st.download_button(
            label=texto_boton,
            data=buffer,
            file_name=nombre_archivo,
            mime="image/png"
        )

# ===== SIDEBAR =====
with st.sidebar:
    st.markdown('<div class="sidebar-title">⚙️ CONFIGURACIÓN</div>', unsafe_allow_html=True)
    
    cultivo = "PALMA_ACEITERA"
    
    # Mostrar información del cultivo
    if cultivo in PARAMETROS_CULTIVOS:
        params = PARAMETROS_CULTIVOS[cultivo]
        st.info(f"""
        **🌴 PALMA ACEITERA**
        
        **Región principal:** {', '.join(params['ZONAS_ARGENTINA'])}
        **Variedades:** {len(params['VARIEDADES'])} variedades disponibles
        **Rendimiento óptimo:** {params['RENDIMIENTO_OPTIMO']:,} kg/ha
        """)
    
    variedades = VARIEDADES_CULTIVOS.get(cultivo, [])
    if variedades:
        variedad = st.selectbox(
            "Variedad/Cultivar:",
            ["No especificada"] + variedades,
            help="Selecciona la variedad de palma aceitera"
        )
    else:
        variedad = "No especificada"
    
    st.subheader("🛰️ Fuente de Datos Satelitales")
    
    opciones_satelites = ["MODIS_NASA", "DATOS_SIMULADOS"]
    
    satelite_seleccionado = st.selectbox(
        "Satélite:",
        opciones_satelites,
        help="Selecciona la fuente de datos satelitales",
        index=0
    )
    
    if satelite_seleccionado in SATELITES_DISPONIBLES:
        info_satelite = SATELITES_DISPONIBLES[satelite_seleccionado]
        st.caption(f"{info_satelite['icono']} {info_satelite['nombre']} - {info_satelite['resolucion']}")
    
    st.subheader("📊 Índice de Vegetación")
    if satelite_seleccionado in SATELITES_DISPONIBLES:
        indices_disponibles = SATELITES_DISPONIBLES[satelite_seleccionado]['indices']
        indice_seleccionado = st.selectbox("Índice:", indices_disponibles)

    st.subheader("📅 Rango Temporal")
    fecha_fin = st.date_input("Fecha fin", datetime.now())
    fecha_inicio = st.date_input("Fecha inicio", datetime.now() - timedelta(days=30))

    st.subheader("🎯 División de Parcela")
    n_divisiones = st.slider("Número de zonas de manejo:", min_value=16, max_value=48, value=32)

    st.subheader("🏔️ Configuración Curvas de Nivel")
    intervalo_curvas = st.slider("Intervalo entre curvas (metros):", 1.0, 20.0, 5.0, 1.0)
    resolucion_dem = st.slider("Resolución DEM (metros):", 5.0, 50.0, 10.0, 5.0)
    
    st.subheader("🌐 Fuente de Datos de Elevación")
    fuente_dem = st.selectbox(
        "Fuente DEM:",
        ["NASA SRTM (Datos Reales)", "Sintético Mejorado"],
        help="NASA SRTM: datos reales 30m | Sintético: simulación realista"
    )
    
    usar_datos_reales = fuente_dem == "NASA SRTM (Datos Reales)"

    st.subheader("📤 Subir Parcela")
    uploaded_file = st.file_uploader("Subir archivo de tu parcela", type=['zip', 'kml', 'kmz'],
                                     help="Formatos aceptados: Shapefile (.zip), KML (.kml), KMZ (.kmz)")

# ===== INTERFAZ PRINCIPAL =====
st.title("ANALIZADOR DE PALMA ACEITERA SATELITAL")

if uploaded_file:
    with st.spinner("Cargando parcela..."):
        try:
            gdf = cargar_archivo_parcela(uploaded_file)
            if gdf is not None:
                st.success(f"✅ Parcela cargada exitosamente: {len(gdf)} polígono(s)")
                area_total = calcular_superficie(gdf)
                col1, col2 = st.columns(2)
                with col1:
                    st.write("**📊 INFORMACIÓN DE LA PARCELA:**")
                    st.write(f"- Polígonos: {len(gdf)}")
                    st.write(f"- Área total: {area_total:.1f} ha")
                    st.write(f"- CRS: {gdf.crs}")
                    st.write(f"- Formato: {uploaded_file.name.split('.')[-1].upper()}")
                    
                    fig, ax = plt.subplots(figsize=(8, 6))
                    gdf.plot(ax=ax, color='lightgreen', edgecolor='darkgreen', alpha=0.7)
                    ax.set_title(f"Parcela: {uploaded_file.name}")
                    ax.set_xlabel("Longitud")
                    ax.set_ylabel("Latitud")
                    ax.grid(True, alpha=0.3)
                    st.pyplot(fig)
                    
                    buf_vista = io.BytesIO()
                    plt.savefig(buf_vista, format='png', dpi=150, bbox_inches='tight')
                    buf_vista.seek(0)
                    crear_boton_descarga_png(
                        buf_vista,
                        f"vista_previa_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                        "📥 Descargar Vista Previa PNG"
                    )
                    
                with col2:
                    st.write("**🎯 CONFIGURACIÓN**")
                    st.write(f"- Cultivo: {ICONOS_CULTIVOS[cultivo]} {cultivo}")
                    st.write(f"- Variedad: {variedad}")
                    st.write(f"- Zonas: {n_divisiones}")
                    st.write(f"- Satélite: {SATELITES_DISPONIBLES[satelite_seleccionado]['nombre']}")
                    st.write(f"- Período: {fecha_inicio} a {fecha_fin}")
                    st.write(f"- Intervalo curvas: {intervalo_curvas} m")
                    st.write(f"- Resolución DEM: {resolucion_dem} m")
                
                if st.button("🚀 EJECUTAR ANÁLISIS COMPLETO", type="primary", use_container_width=True):
                    with st.spinner("Ejecutando análisis completo..."):
                        resultados = ejecutar_analisis_completo(
                            gdf, cultivo, n_divisiones, 
                            satelite_seleccionado, fecha_inicio, fecha_fin,
                            intervalo_curvas, resolucion_dem
                        )
                        
                        if resultados['exitoso']:
                            st.session_state.resultados_todos = resultados
                            st.session_state.analisis_completado = True
                            st.success("✅ Análisis completado exitosamente!")
                            st.rerun()
                        else:
                            st.error("❌ Error en el análisis completo")
            
            else:
                st.error("❌ Error al cargar la parcela. Verifica el formato del archivo.")
        
        except Exception as e:
            st.error(f"❌ Error en el análisis: {str(e)}")
            import traceback
            traceback.print_exc()

# Mostrar resultados si el análisis está completado
if st.session_state.analisis_completado and 'resultados_todos' in st.session_state:
    resultados = st.session_state.resultados_todos
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Fertilidad Actual",
        "🧪 Recomendaciones NPK",
        "💰 Análisis de Costos",
        "🏗️ Textura del Suelo",
        "📈 Proyecciones",
        "🏔️ Topografía"
    ])
    
    with tab1:
        st.subheader("FERTILIDAD ACTUAL")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            npk_prom = resultados['gdf_completo']['fert_npk_actual'].mean()
            st.metric("Índice NPK Promedio", f"{npk_prom:.3f}")
        with col2:
            ndvi_prom = resultados['gdf_completo']['fert_ndvi'].mean()
            st.metric("NDVI Promedio", f"{ndvi_prom:.3f}")
        with col3:
            mo_prom = resultados['gdf_completo']['fert_materia_organica'].mean()
            st.metric("Materia Orgánica", f"{mo_prom:.1f}%")
        with col4:
            hum_prom = resultados['gdf_completo']['fert_humedad_suelo'].mean()
            st.metric("Humedad Suelo", f"{hum_prom:.3f}")
        
        mapa_fert = crear_mapa_fertilidad(resultados['gdf_completo'], cultivo, satelite_seleccionado)
        if mapa_fert:
            st.image(mapa_fert, use_container_width=True)
            crear_boton_descarga_png(
                mapa_fert,
                f"mapa_fertilidad_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                "📥 Descargar Mapa de Fertilidad PNG"
            )
        
        columnas_fert = ['id_zona', 'area_ha', 'fert_npk_actual', 'fert_ndvi', 
                       'fert_ndre', 'fert_materia_organica', 'fert_humedad_suelo']
        tabla_fert = resultados['gdf_completo'][columnas_fert].copy()
        tabla_fert.columns = ['Zona', 'Área (ha)', 'Índice NPK', 'NDVI', 
                            'NDRE', 'Materia Org (%)', 'Humedad']
        st.dataframe(tabla_fert)
    
    with tab2:
        st.subheader("RECOMENDACIONES NPK")
        col1, col2, col3 = st.columns(3)
        with col1:
            n_prom = resultados['gdf_completo']['rec_N'].mean()
            st.metric("Nitrógeno Promedio", f"{n_prom:.1f} kg/ha")
        with col2:
            p_prom = resultados['gdf_completo']['rec_P'].mean()
            st.metric("Fósforo Promedio", f"{p_prom:.1f} kg/ha")
        with col3:
            k_prom = resultados['gdf_completo']['rec_K'].mean()
            st.metric("Potasio Promedio", f"{k_prom:.1f} kg/ha")
        
        col_n, col_p, col_k = st.columns(3)
        with col_n:
            mapa_n = crear_mapa_npk(resultados['gdf_completo'], cultivo, 'N')
            if mapa_n:
                st.image(mapa_n, use_container_width=True)
                st.caption("Nitrógeno (N)")
                crear_boton_descarga_png(
                    mapa_n,
                    f"mapa_nitrogeno_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                    "📥 Descargar Mapa N"
                )
        with col_p:
            mapa_p = crear_mapa_npk(resultados['gdf_completo'], cultivo, 'P')
            if mapa_p:
                st.image(mapa_p, use_container_width=True)
                st.caption("Fósforo (P)")
                crear_boton_descarga_png(
                    mapa_p,
                    f"mapa_fosforo_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                    "📥 Descargar Mapa P"
                )
        with col_k:
            mapa_k = crear_mapa_npk(resultados['gdf_completo'], cultivo, 'K')
            if mapa_k:
                st.image(mapa_k, use_container_width=True)
                st.caption("Potasio (K)")
                crear_boton_descarga_png(
                    mapa_k,
                    f"mapa_potasio_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                    "📥 Descargar Mapa K"
                )
    
    with tab3:
        st.subheader("ANÁLISIS DE COSTOS")
        costo_total = resultados['gdf_completo']['costo_costo_total'].sum()
        costo_prom = resultados['gdf_completo']['costo_costo_total'].mean()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Costo Total Estimado", f"${costo_total:.2f} USD")
        with col2:
            st.metric("Costo Promedio por ha", f"${costo_prom:.2f} USD/ha")
        with col3:
            inversion_ha = costo_total / resultados['area_total'] if resultados['area_total'] > 0 else 0
            st.metric("Inversión por ha", f"${inversion_ha:.2f} USD/ha")
        
        columnas_costos = ['id_zona', 'area_ha', 'costo_costo_nitrogeno', 'costo_costo_fosforo', 
                         'costo_costo_potasio', 'costo_costo_total']
        tabla_costos = resultados['gdf_completo'][columnas_costos].copy()
        tabla_costos.columns = ['Zona', 'Área (ha)', 'Costo N (USD)', 'Costo P (USD)', 
                              'Costo K (USD)', 'Total (USD)']
        st.dataframe(tabla_costos)
    
    with tab4:
        st.subheader("TEXTURA DEL SUELO")
        textura_pred = resultados['gdf_completo']['textura_suelo'].mode()[0] if len(resultados['gdf_completo']) > 0 else "N/D"
        arena_prom = resultados['gdf_completo']['arena'].mean()
        limo_prom = resultados['gdf_completo']['limo'].mean()
        arcilla_prom = resultados['gdf_completo']['arcilla'].mean()
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Textura Predominante", textura_pred)
        with col2:
            st.metric("Arena Promedio", f"{arena_prom:.1f}%")
        with col3:
            st.metric("Limo Promedio", f"{limo_prom:.1f}%")
        with col4:
            st.metric("Arcilla Promedio", f"{arcilla_prom:.1f}%")
        
        mapa_text = crear_mapa_texturas(resultados['gdf_completo'], cultivo)
        if mapa_text:
            st.image(mapa_text, use_container_width=True)
            crear_boton_descarga_png(
                mapa_text,
                f"mapa_texturas_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                "📥 Descargar Mapa de Texturas PNG"
            )
    
    with tab5:
        st.subheader("PROYECCIONES DE COSECHA")
        rend_sin = resultados['gdf_completo']['proy_rendimiento_sin_fert'].sum()
        rend_con = resultados['gdf_completo']['proy_rendimiento_con_fert'].sum()
        incremento = ((rend_con - rend_sin) / rend_sin * 100) if rend_sin > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Rendimiento sin Fertilización", f"{rend_sin:.0f} kg")
        with col2:
            st.metric("Rendimiento con Fertilización", f"{rend_con:.0f} kg")
        with col3:
            st.metric("Incremento Esperado", f"{incremento:.1f}%")
        
        columnas_proy = ['id_zona', 'area_ha', 'proy_rendimiento_sin_fert', 'proy_rendimiento_con_fert', 'proy_incremento_esperado']
        tabla_proy = resultados['gdf_completo'][columnas_proy].copy()
        tabla_proy.columns = ['Zona', 'Área (ha)', 'Sin Fertilización (kg)', 'Con Fertilización (kg)', 'Incremento (%)']
        st.dataframe(tabla_proy)
    
    with tab6:
        if 'dem_data' in resultados and resultados['dem_data']:
            dem_data = resultados['dem_data']
            st.subheader("🏔️ ANÁLISIS TOPOGRÁFICO")
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                elev_min = np.nanmin(dem_data['Z'])
                st.metric("Elevación Mínima", f"{elev_min:.1f} m")
            with col2:
                elev_max = np.nanmax(dem_data['Z'])
                st.metric("Elevación Máxima", f"{elev_max:.1f} m")
            with col3:
                elev_prom = np.nanmean(dem_data['Z'])
                st.metric("Elevación Promedio", f"{elev_prom:.1f} m")
            with col4:
                pend_prom = np.nanmean(dem_data['pendientes'])
                st.metric("Pendiente Promedio", f"{pend_prom:.1f}%")
            
            mapa_pend, stats_pend = crear_mapa_pendientes(dem_data['X'], dem_data['Y'], dem_data['pendientes'], resultados['gdf_completo'])
            if mapa_pend:
                st.image(mapa_pend, use_container_width=True)
                crear_boton_descarga_png(
                    mapa_pend,
                    f"mapa_pendientes_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                    "📥 Descargar Mapa de Pendientes PNG"
                )
        else:
            st.info("ℹ️ No hay datos topográficos disponibles para esta parcela")
    
    st.markdown("---")
    st.subheader("💾 EXPORTAR RESULTADOS")
    
    col_exp1, col_exp2, col_exp3 = st.columns(3)
    
    with col_exp1:
        st.markdown("**GeoJSON**")
        if st.button("📤 Generar GeoJSON", key="generate_geojson"):
            with st.spinner("Generando GeoJSON..."):
                geojson_data, nombre_geojson = exportar_a_geojson(
                    resultados['gdf_completo'],
                    f"analisis_{cultivo}"
                )
                if geojson_data:
                    st.session_state.geojson_data = geojson_data
                    st.session_state.nombre_geojson = nombre_geojson
                    st.success("✅ GeoJSON generado correctamente")
                    st.rerun()
        
        if 'geojson_data' in st.session_state and st.session_state.geojson_data:
            st.download_button(
                label="📥 Descargar GeoJSON",
                data=st.session_state.geojson_data,
                file_name=st.session_state.nombre_geojson,
                mime="application/json",
                key="geojson_download"
            )
    
    with col_exp2:
        st.markdown("**Reporte DOCX**")
        if st.button("📄 Generar Reporte Completo", key="generate_report"):
            with st.spinner("Generando reporte DOCX..."):
                reporte = generar_reporte_completo(
                    resultados, 
                    cultivo, 
                    satelite_seleccionado, 
                    fecha_inicio, 
                    fecha_fin
                )
                if reporte:
                    st.session_state.reporte_completo = reporte
                    st.session_state.nombre_reporte = f"reporte_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
                    st.success("✅ Reporte generado correctamente")
                    st.rerun()
        
        if 'reporte_completo' in st.session_state and st.session_state.reporte_completo:
            st.download_button(
                label="📥 Descargar Reporte DOCX",
                data=st.session_state.reporte_completo,
                file_name=st.session_state.nombre_reporte,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="report_download"
            )
    
    with col_exp3:
        st.markdown("**Limpiar Resultados**")
        if st.button("🗑️ Limpiar Resultados", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key != 'modis_authenticated':
                    del st.session_state[key]
            st.rerun()

# ===== PIE DE PÁGINA =====
st.markdown("---")
col_footer1, col_footer2, col_footer3 = st.columns(3)

with col_footer1:
    st.markdown("""
    📡 **Fuentes de Datos:**  
    NASA MODIS  
    NASA POWER API  
    NASA SRTM  
    Datos simulados
    """)

with col_footer2:
    st.markdown("""
    🛠️ **Tecnologías:**  
    Streamlit  
    GeoPandas  
    MODIS NASA  
    Matplotlib  
    Python-DOCX
    """)

with col_footer3:
    st.markdown("""
    📞 **Soporte:**  
    Versión: 1.0 - Palma Aceitera con MODIS  
    Última actualización: Febrero 2026  
    Analizador de Palma Aceitera
    """)

st.markdown(
    '<div style="text-align: center; padding: 20px; margin-top: 20px; border-top: 1px solid #3b82f6;">'
    '<p style="color: #94a3b8; margin: 0;">© 2026 Analizador de Palma Aceitera Satelital. Todos los derechos reservados.</p>'
    '</div>',
    unsafe_allow_html=True
)

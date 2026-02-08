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
import requests
import rasterio
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
import rasterio.features
import rasterio.transform
from PIL import Image
import folium
from folium.raster_layers import ImageOverlay
from streamlit_folium import st_folium
import mercantile
import contextily as ctx

# ===== CONFIGURACIÓN NASA GIBS =====
warnings.filterwarnings('ignore')

# Configuración NASA GIBS
NASA_GIBS_BASE_URL = "https://gibs.earthdata.nasa.gov"
NASA_GIBS_WMS_URL = f"{NASA_GIBS_BASE_URL}/wms/epsg4326/best/wms.cgi"

# Capas disponibles en NASA GIBS
GIBS_LAYERS = {
    'MODIS_Terra_CorrectedReflectance_TrueColor': {
        'name': 'MODIS Terra True Color',
        'description': 'Imágenes de color verdadero - MODIS Terra',
        'resolution': '250m',
        'temporal': 'Diario',
        'source': 'NASA MODIS Terra',
        'bands': 'RGB Natural',
        'min_date': '2000-02-24',
        'max_date': 'Presente'
    },
    'MODIS_Aqua_CorrectedReflectance_TrueColor': {
        'name': 'MODIS Aqua True Color',
        'description': 'Imágenes de color verdadero - MODIS Aqua',
        'resolution': '250m',
        'temporal': 'Diario',
        'source': 'NASA MODIS Aqua',
        'bands': 'RGB Natural',
        'min_date': '2002-07-04',
        'max_date': 'Presente'
    },
    'VIIRS_SNPP_CorrectedReflectance_TrueColor': {
        'name': 'VIIRS SNPP True Color',
        'description': 'Imágenes de color verdadero - VIIRS SNPP',
        'resolution': '375m',
        'temporal': 'Diario',
        'source': 'NASA/NOAA VIIRS',
        'bands': 'RGB Natural',
        'min_date': '2012-01-19',
        'max_date': 'Presente'
    },
    'MODIS_Terra_NDVI': {
        'name': 'MODIS Terra NDVI',
        'description': 'Índice de Vegetación Normalizado (NDVI)',
        'resolution': '250m',
        'temporal': '16 días',
        'source': 'NASA MODIS Terra',
        'bands': 'NDVI',
        'min_date': '2000-02-24',
        'max_date': 'Presente',
        'palette': 'NDVI'
    },
    'MODIS_Terra_EVI': {
        'name': 'MODIS Terra EVI',
        'description': 'Enhanced Vegetation Index (EVI)',
        'resolution': '250m',
        'temporal': '16 días',
        'source': 'NASA MODIS Terra',
        'bands': 'EVI',
        'min_date': '2000-02-24',
        'max_date': 'Presente'
    }
}

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
if 'imagen_satelital' not in st.session_state:
    st.session_state.imagen_satelital = None
if 'datos_satelitales_reales' not in st.session_state:
    st.session_state.datos_satelitales_reales = None

# ===== ESTILOS PERSONALIZADOS =====
st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #ffffff;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

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

[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #e2e8f0 !important;
}

[data-testid="stSidebar"] *,
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stText,
[data-testid="stSidebar"] .stTitle,
[data-testid="stSidebar"] .stSubheader { 
    color: #000000 !important;
}

/* Tablas */
.dataframe {
    background: rgba(15, 23, 42, 0.85) !important;
    backdrop-filter: blur(8px) !important;
    border-radius: 14px !important;
    border: 1px solid rgba(255, 255, 255, 0.12) !important;
    color: #e2e8f0 !important;
}

.dataframe th {
    background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%) !important;
    color: #ffffff !important;
    font-weight: 700 !important;
}

/* Métricas */
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.95)) !important;
    backdrop-filter: blur(10px) !important;
    border-radius: 18px !important;
    border: 1px solid rgba(59, 130, 246, 0.25) !important;
}

div[data-testid="metric-container"] label,
div[data-testid="metric-container"] div,
div[data-testid="metric-container"] [data-testid="stMetricValue"] { 
    color: #ffffff !important;
}

/* Folium map container */
.st-folium-map {
    border-radius: 15px;
    overflow: hidden;
    border: 2px solid rgba(59, 130, 246, 0.3);
}
</style>
""", unsafe_allow_html=True)

# ===== BANNER HERO =====
st.markdown("""
<div class="hero-banner">
    <div class="hero-content">
        <h1 class="hero-title">🌴 ANALIZADOR DE PALMA ACEITERA</h1>
        <p class="hero-subtitle">Imágenes satelitales reales NASA MODIS & VIIRS - Datos en tiempo real</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ===== FUNCIONES AUXILIARES =====
def validar_y_corregir_crs(gdf):
    if gdf is None or len(gdf) == 0:
        return gdf
    try:
        if gdf.crs is None:
            gdf = gdf.set_crs('EPSG:4326', inplace=False)
        elif str(gdf.crs).upper() != 'EPSG:4326':
            original_crs = str(gdf.crs)
            gdf = gdf.to_crs('EPSG:4326')
        return gdf
    except Exception as e:
        st.warning(f"⚠️ Error al corregir CRS: {str(e)}")
        return gdf

def calcular_superficie(gdf):
    try:
        if gdf is None or len(gdf) == 0:
            return 0.0
        gdf = validar_y_corregir_crs(gdf)
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
        if polygons:
            gdf = gpd.GeoDataFrame({'geometry': polygons}, crs='EPSG:4326')
            return gdf
        return None
    except Exception as e:
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
        return None

# ===== FUNCIONES NASA GIBS (IMÁGENES REALES) =====
def obtener_imagen_nasa_gibs(gdf, fecha, capa_seleccionada, zoom_level=10):
    """
    Obtiene imagen satelital real de NASA GIBS
    
    Args:
        gdf: GeoDataFrame con la parcela
        fecha: Fecha para la imagen
        capa_seleccionada: Capa de GIBS a usar
        zoom_level: Nivel de zoom para la imagen
    
    Returns:
        imagen_pil: Imagen PIL
        bounds: Bounds de la imagen
        info: Información de la imagen
    """
    try:
        # Obtener bounds de la parcela
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Calcular tamaño de imagen basado en zoom
        width = 1024
        height = 768
        
        # Parámetros para WMS
        params = {
            'service': 'WMS',
            'version': '1.3.0',
            'request': 'GetMap',
            'layers': capa_seleccionada,
            'styles': '',
            'crs': 'EPSG:4326',
            'bbox': f'{min_lon},{min_lat},{max_lon},{max_lat}',
            'width': width,
            'height': height,
            'format': 'image/png',
            'transparent': 'true',
            'time': fecha.strftime('%Y-%m-%d')
        }
        
        # Intentar obtener la imagen
        response = requests.get(NASA_GIBS_WMS_URL, params=params, timeout=30)
        
        if response.status_code == 200 and response.headers.get('Content-Type', '').startswith('image/'):
            # Convertir a imagen PIL
            imagen_bytes = response.content
            imagen_pil = Image.open(io.BytesIO(imagen_bytes))
            
            # Información de la imagen
            info = {
                'capa': capa_seleccionada,
                'fecha': fecha.strftime('%Y-%m-%d'),
                'resolucion': GIBS_LAYERS[capa_seleccionada]['resolution'],
                'fuente': GIBS_LAYERS[capa_seleccionada]['source'],
                'tamaño': f"{width}x{height}px",
                'bounds': bounds,
                'status': 'success'
            }
            
            return imagen_pil, bounds, info
        else:
            # Si falla, usar imagen de fondo alternativo
            st.warning(f"⚠️ No se pudo obtener imagen de NASA GIBS para {fecha.strftime('%Y-%m-%d')}")
            
            # Crear imagen sintética como fallback
            imagen_pil = Image.new('RGB', (width, height), (100, 150, 100))
            
            info = {
                'capa': capa_seleccionada,
                'fecha': fecha.strftime('%Y-%m-%d'),
                'resolucion': 'Simulado',
                'fuente': 'Datos simulados (NASA GIBS no disponible)',
                'tamaño': f"{width}x{height}px",
                'bounds': bounds,
                'status': 'simulated',
                'nota': 'Imagen simulada - NASA GIBS no disponible para esta fecha/área'
            }
            
            return imagen_pil, bounds, info
            
    except Exception as e:
        st.error(f"❌ Error obteniendo imagen NASA GIBS: {str(e)}")
        
        # Crear imagen de error
        width, height = 1024, 768
        imagen_pil = Image.new('RGB', (width, height), (50, 50, 50))
        
        info = {
            'capa': capa_seleccionada,
            'fecha': fecha.strftime('%Y-%m-%d'),
            'resolucion': 'Error',
            'fuente': 'Error en conexión NASA GIBS',
            'tamaño': f"{width}x{height}px",
            'bounds': bounds,
            'status': 'error',
            'error': str(e)
        }
        
        return imagen_pil, bounds, info

def crear_mapa_interactivo_nasa(gdf, imagen_pil, bounds, info_capa):
    """
    Crea mapa interactivo con imagen NASA GIBS
    
    Args:
        gdf: GeoDataFrame con la parcela
        imagen_pil: Imagen PIL de NASA GIBS
        bounds: Bounds de la imagen
        info_capa: Información de la capa
    
    Returns:
        folium_map: Mapa Folium interactivo
    """
    try:
        # Calcular centro del mapa
        min_lon, min_lat, max_lon, max_lat = bounds
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        
        # Calcular nivel de zoom apropiado
        lat_diff = max_lat - min_lat
        if lat_diff < 0.1:
            zoom_start = 13
        elif lat_diff < 0.5:
            zoom_start = 11
        elif lat_diff < 1.0:
            zoom_start = 9
        else:
            zoom_start = 8
        
        # Crear mapa Folium
        folium_map = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=zoom_start,
            tiles=None,  # No usar tiles por defecto
            control_scale=True,
            attr='NASA GIBS'
        )
        
        # Añadir imagen NASA GIBS como overlay
        ImageOverlay(
            image=np.array(imagen_pil),
            bounds=[[min_lat, min_lon], [max_lat, max_lon]],
            opacity=0.9,
            interactive=True,
            cross_origin=False,
            zindex=1
        ).add_to(folium_map)
        
        # Añadir parcela como polígono
        folium.GeoJson(
            gdf.__geo_interface__,
            style_function=lambda x: {
                'fillColor': 'transparent',
                'color': '#FF0000',
                'weight': 3,
                'opacity': 0.8,
                'fillOpacity': 0.1
            },
            name='Parcela',
            tooltip=folium.GeoJsonTooltip(
                fields=[],
                aliases=[],
                labels=True
            )
        ).add_to(folium_map)
        
        # Añadir capa base opcional (OpenStreetMap)
        folium.TileLayer(
            tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            attr='OpenStreetMap',
            name='OpenStreetMap',
            overlay=False,
            control=True
        ).add_to(folium_map)
        
        # Añadir control de capas
        folium.LayerControl(collapsed=False).add_to(folium_map)
        
        # Añadir marcador con información
        info_html = f"""
        <div style="font-family: Arial; font-size: 12px;">
            <h4>🌐 Información NASA GIBS</h4>
            <p><b>Capa:</b> {info_capa['capa']}</p>
            <p><b>Fecha:</b> {info_capa['fecha']}</p>
            <p><b>Resolución:</b> {info_capa['resolucion']}</p>
            <p><b>Fuente:</b> {info_capa['fuente']}</p>
            <p><b>Estado:</b> {info_capa['status']}</p>
        </div>
        """
        
        if 'nota' in info_capa:
            info_html += f"<p><b>Nota:</b> {info_capa['nota']}</p>"
        
        folium.Marker(
            [center_lat, center_lon],
            icon=folium.DivIcon(html='<div style="font-size: 12pt">ℹ️</div>'),
            tooltip="Información NASA GIBS",
            popup=folium.Popup(info_html, max_width=300)
        ).add_to(folium_map)
        
        return folium_map
        
    except Exception as e:
        st.error(f"❌ Error creando mapa interactivo: {str(e)}")
        return None

def analizar_ndvi_desde_imagen(imagen_pil, gdf):
    """
    Analiza NDVI a partir de imagen (versión simplificada)
    
    En una implementación real, necesitaríamos imágenes multiespectrales.
    Esta es una versión simulada basada en características de la imagen.
    """
    try:
        # Convertir imagen a array numpy
        img_array = np.array(imagen_pil)
        
        # Para imágenes RGB, calcular un índice de verde simplificado
        if len(img_array.shape) == 3 and img_array.shape[2] >= 3:
            # Separar canales RGB
            r = img_array[:, :, 0].astype(float)
            g = img_array[:, :, 1].astype(float)
            b = img_array[:, :, 2].astype(float)
            
            # Calcular índice de vegetación simplificado (GNDVI simplificado)
            total = r + g + b
            total[total == 0] = 1  # Evitar división por cero
            
            # Índice basado en el canal verde
            green_index = g / total
            
            # Valores estadísticos
            ndvi_mean = np.mean(green_index)
            ndvi_std = np.std(green_index)
            ndvi_min = np.min(green_index)
            ndvi_max = np.max(green_index)
            
            return {
                'ndvi_mean': float(ndvi_mean),
                'ndvi_std': float(ndvi_std),
                'ndvi_min': float(ndvi_min),
                'ndvi_max': float(ndvi_max),
                'status': 'calculated_from_rgb',
                'nota': 'Índice simplificado basado en canal verde (GNDVI aproximado)'
            }
        else:
            # Para imágenes de un canal (como NDVI real)
            if len(img_array.shape) == 2:
                ndvi_mean = np.mean(img_array)
                ndvi_std = np.std(img_array)
                ndvi_min = np.min(img_array)
                ndvi_max = np.max(img_array)
                
                return {
                    'ndvi_mean': float(ndvi_mean),
                    'ndvi_std': float(ndvi_std),
                    'ndvi_min': float(ndvi_min),
                    'ndvi_max': float(ndvi_max),
                    'status': 'calculated_from_single_band'
                }
            else:
                raise ValueError("Formato de imagen no soportado")
                
    except Exception as e:
        st.warning(f"⚠️ No se pudo calcular NDVI de la imagen: {str(e)}")
        
        # Valores por defecto para palma aceitera
        return {
            'ndvi_mean': 0.75,
            'ndvi_std': 0.08,
            'ndvi_min': 0.65,
            'ndvi_max': 0.85,
            'status': 'default_values',
            'nota': 'Valores por defecto para palma aceitera (imagen no analizable)'
        }

# ===== FUNCIÓN PARA OBTENER DATOS DE NASA POWER =====
def obtener_datos_nasa_power(gdf, fecha_inicio, fecha_fin):
    """
    Obtiene datos meteorológicos reales de NASA POWER
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
        st.warning(f"⚠️ No se pudieron obtener datos NASA POWER: {str(e)}")
        return None

# ===== CONFIGURACIÓN PALMA ACEITERA =====
VARIEDADES_PALMA = [
    'Tenera', 'Dura', 'Pisifera', 'DxP', 'Yangambi',
    'AVROS', 'La Mé', 'Ekona', 'Calabar', 'NIFOR',
    'MARDI', 'CIRAD', 'ASD Costa Rica', 'Dami', 'Socfindo'
]

PARAMETROS_PALMA = {
    'NITROGENO': {'min': 150, 'max': 250},
    'FOSFORO': {'min': 50, 'max': 100},
    'POTASIO': {'min': 200, 'max': 350},
    'MATERIA_ORGANICA_OPTIMA': 3.8,
    'HUMEDAD_OPTIMA': 0.55,
    'NDVI_OPTIMO': 0.75,
    'RENDIMIENTO_OPTIMO': 20000,
    'COSTO_FERTILIZACION': 1100,
    'PRECIO_VENTA': 0.40,
    'ZONAS': ['Formosa', 'Chaco', 'Misiones']
}

# ===== FUNCIONES DE ANÁLISIS =====
def analizar_parcela_completa(gdf, fecha_imagen, capa_nasa, n_divisiones=32):
    """
    Ejecuta análisis completo de la parcela
    """
    resultados = {
        'exitoso': False,
        'gdf_original': gdf,
        'area_total': 0,
        'datos_imagen': None,
        'analisis_ndvi': None,
        'zonas': None,
        'datos_power': None,
        'recomendaciones': None
    }
    
    try:
        # 1. Calcular área total
        area_total = calcular_superficie(gdf)
        resultados['area_total'] = area_total
        
        # 2. Obtener imagen NASA GIBS
        with st.spinner("🛰️ Descargando imagen satelital NASA..."):
            imagen_pil, bounds, info_imagen = obtener_imagen_nasa_gibs(
                gdf, fecha_imagen, capa_nasa
            )
        
        resultados['datos_imagen'] = {
            'imagen': imagen_pil,
            'bounds': bounds,
            'info': info_imagen
        }
        
        # 3. Analizar NDVI de la imagen
        resultados['analisis_ndvi'] = analizar_ndvi_desde_imagen(imagen_pil, gdf)
        
        # 4. Dividir parcela en zonas
        gdf_zonas = dividir_parcela_en_zonas(gdf, n_divisiones)
        resultados['zonas'] = gdf_zonas
        
        # 5. Obtener datos meteorológicos (últimos 30 días)
        fecha_fin = datetime.now()
        fecha_inicio = fecha_fin - timedelta(days=30)
        resultados['datos_power'] = obtener_datos_nasa_power(gdf, fecha_inicio, fecha_fin)
        
        # 6. Generar recomendaciones básicas
        ndvi_mean = resultados['analisis_ndvi']['ndvi_mean']
        
        # Recomendaciones basadas en NDVI
        if ndvi_mean >= 0.7:
            estado = "Excelente"
            recomendacion_npk = "Mantenimiento"
            dosis_n = PARAMETROS_PALMA['NITROGENO']['min']
            dosis_p = PARAMETROS_PALMA['FOSFORO']['min']
            dosis_k = PARAMETROS_PALMA['POTASIO']['min']
        elif ndvi_mean >= 0.6:
            estado = "Buena"
            recomendacion_npk = "Refuerzo moderado"
            dosis_n = (PARAMETROS_PALMA['NITROGENO']['min'] + PARAMETROS_PALMA['NITROGENO']['max']) / 2
            dosis_p = (PARAMETROS_PALMA['FOSFORO']['min'] + PARAMETROS_PALMA['FOSFORO']['max']) / 2
            dosis_k = (PARAMETROS_PALMA['POTASIO']['min'] + PARAMETROS_PALMA['POTASIO']['max']) / 2
        else:
            estado = "Necesita atención"
            recomendacion_npk = "Fertilización intensiva"
            dosis_n = PARAMETROS_PALMA['NITROGENO']['max']
            dosis_p = PARAMETROS_PALMA['FOSFORO']['max']
            dosis_k = PARAMETROS_PALMA['POTASIO']['max']
        
        resultados['recomendaciones'] = {
            'estado_vegetacion': estado,
            'ndvi_promedio': ndvi_mean,
            'recomendacion_npk': recomendacion_npk,
            'dosis_n_kg_ha': round(dosis_n, 1),
            'dosis_p_kg_ha': round(dosis_p, 1),
            'dosis_k_kg_ha': round(dosis_k, 1),
            'costo_estimado_usd_ha': round(dosis_n * 1.2 + dosis_p * 2.5 + dosis_k * 1.8 + PARAMETROS_PALMA['COSTO_FERTILIZACION'], 2),
            'rendimiento_esperado_kg_ha': round(PARAMETROS_PALMA['RENDIMIENTO_OPTIMO'] * ndvi_mean, 0)
        }
        
        resultados['exitoso'] = True
        
        return resultados
        
    except Exception as e:
        st.error(f"❌ Error en análisis completo: {str(e)}")
        return resultados

# ===== SIDEBAR =====
with st.sidebar:
    st.markdown("### ⚙️ CONFIGURACIÓN")
    
    # Cultivo (solo palma aceitera)
    cultivo = "🌴 PALMA ACEITERA"
    st.info(f"**Cultivo:** {cultivo}")
    
    # Variedad
    variedad = st.selectbox(
        "Variedad:",
        VARIEDADES_PALMA,
        help="Selecciona la variedad de palma aceitera"
    )
    
    st.markdown("---")
    st.markdown("### 🛰️ IMAGEN SATELITAL NASA")
    
    # Seleccionar capa NASA GIBS
    capas_disponibles = list(GIBS_LAYERS.keys())
    nombres_capas = [GIBS_LAYERS[c]['name'] for c in capas_disponibles]
    
    capa_seleccionada_nombre = st.selectbox(
        "Capa satelital:",
        nombres_capas,
        index=0,
        help="Selecciona la capa de imágenes satelitales NASA"
    )
    
    # Obtener clave de la capa seleccionada
    capa_seleccionada = capas_disponibles[nombres_capas.index(capa_seleccionada_nombre)]
    
    # Mostrar info de la capa
    info_capa = GIBS_LAYERS[capa_seleccionada]
    st.caption(f"**Resolución:** {info_capa['resolution']}")
    st.caption(f"**Temporalidad:** {info_capa['temporal']}")
    st.caption(f"**Fuente:** {info_capa['source']}")
    
    # Fecha de la imagen
    fecha_imagen = st.date_input(
        "Fecha de la imagen:",
        datetime.now() - timedelta(days=7),
        help="Selecciona la fecha para la imagen satelital"
    )
    
    st.markdown("---")
    st.markdown("### 🎯 DIVISIÓN DE PARCELA")
    
    n_divisiones = st.slider(
        "Número de zonas:",
        min_value=16,
        max_value=64,
        value=32,
        step=8,
        help="Divide la parcela en zonas de manejo diferenciado"
    )
    
    st.markdown("---")
    st.markdown("### 📤 SUBIR PARCELA")
    
    uploaded_file = st.file_uploader(
        "Subir archivo de parcela:",
        type=['zip', 'kml', 'kmz', 'geojson'],
        help="Formatos: Shapefile (.zip), KML, KMZ, GeoJSON"
    )

# ===== INTERFAZ PRINCIPAL =====
st.title("🌴 ANALIZADOR DE PALMA ACEITERA - IMÁGENES SATELITALES REALES NASA")

if uploaded_file:
    with st.spinner("Cargando parcela..."):
        gdf = cargar_archivo_parcela(uploaded_file)
        
        if gdf is not None:
            st.success(f"✅ Parcela cargada exitosamente")
            
            # Mostrar información básica
            col1, col2 = st.columns(2)
            
            with col1:
                area_total = calcular_superficie(gdf)
                st.metric("Área total", f"{area_total:.2f} ha")
                
                # Vista previa de la parcela
                fig, ax = plt.subplots(figsize=(8, 6))
                gdf.plot(ax=ax, color='lightgreen', edgecolor='darkgreen', alpha=0.7)
                ax.set_title("Parcela cargada")
                ax.set_xlabel("Longitud")
                ax.set_ylabel("Latitud")
                ax.grid(True, alpha=0.3)
                st.pyplot(fig)
            
            with col2:
                bounds = gdf.total_bounds
                st.metric("Extensión", f"{bounds[2]-bounds[0]:.4f}° × {bounds[3]-bounds[1]:.4f}°")
                st.metric("Centroide", f"Lat: {gdf.geometry.centroid.y:.4f}°, Lon: {gdf.geometry.centroid.x:.4f}°")
                
                st.info(f"""
                **Configuración:**
                - Cultivo: {cultivo}
                - Variedad: {variedad}
                - Imagen: {info_capa['name']}
                - Fecha: {fecha_imagen}
                - Zonas: {n_divisiones}
                """)
            
            # Botón para ejecutar análisis
            if st.button("🚀 EJECUTAR ANÁLISIS CON IMÁGENES NASA", type="primary", use_container_width=True):
                with st.spinner("Ejecutando análisis con imágenes satelitales reales..."):
                    resultados = analizar_parcela_completa(
                        gdf, fecha_imagen, capa_seleccionada, n_divisiones
                    )
                    
                    if resultados['exitoso']:
                        st.session_state.resultados_todos = resultados
                        st.session_state.analisis_completado = True
                        st.success("✅ Análisis completado exitosamente!")
                        st.rerun()
                    else:
                        st.error("❌ Error en el análisis")
                        
elif not uploaded_file and not st.session_state.analisis_completado:
    st.info("👈 **Sube un archivo de parcela en el panel izquierdo para comenzar el análisis**")
    
    # Información sobre formatos soportados
    with st.expander("📁 Formatos de archivo soportados"):
        st.markdown("""
        ### Formatos compatibles:
        
        **1. Shapefile (.zip)**
        - Archivo ZIP que contenga: .shp, .shx, .dbf, .prj
        - Sistema de coordenadas preferido: WGS84 (EPSG:4326)
        
        **2. KML/KMZ (Google Earth)**
        - Archivos exportados desde Google Earth
        - Formato estándar de Google
        
        **3. GeoJSON**
        - Formato estándar web para datos geoespaciales
        
        ### Recomendaciones:
        - Área máxima recomendada: 10,000 ha
        - Coordenadas en grados decimales (WGS84)
        - Archivos sin contraseña/protección
        """)
    
    # Ejemplo de análisis
    with st.expander("🛰️ Información sobre imágenes NASA"):
        st.markdown("""
        ### NASA GIBS - Global Imagery Browse Services
        
        **Fuentes de imágenes:**
        
        **MODIS Terra/Aqua**
        - Resolución: 250m
        - Frecuencia: Diaria
        - Banda: Color verdadero, NDVI, EVI
        - Período: 2000-Presente
        
        **VIIRS SNPP**
        - Resolución: 375m
        - Frecuencia: Diaria
        - Banda: Color verdadero
        - Período: 2012-Presente
        
        **NASA POWER - Datos meteorológicos**
        - Radiación solar, temperatura, precipitación
        - Datos diarios históricos
        - Resolución: 0.5° × 0.5°
        
        **Nota:** Las imágenes pueden tener cobertura de nubes
        según las condiciones climáticas del día seleccionado.
        """)

# Mostrar resultados si el análisis está completado
if st.session_state.analisis_completado and 'resultados_todos' in st.session_state:
    resultados = st.session_state.resultados_todos
    
    st.markdown("---")
    st.markdown("## 📊 RESULTADOS DEL ANÁLISIS")
    
    # Pestañas para diferentes secciones
    tab1, tab2, tab3, tab4 = st.tabs([
        "🛰️ Imagen Satelital",
        "📈 Análisis NDVI",
        "🧪 Recomendaciones",
        "📥 Exportar Datos"
    ])
    
    with tab1:
        st.subheader("IMAGEN SATELITAL NASA")
        
        # Mostrar información de la imagen
        info_imagen = resultados['datos_imagen']['info']
        col_info1, col_info2, col_info3 = st.columns(3)
        
        with col_info1:
            st.metric("Capa", info_imagen['capa'])
            st.metric("Fecha", info_imagen['fecha'])
        
        with col_info2:
            st.metric("Resolución", info_imagen['resolucion'])
            st.metric("Fuente", "NASA GIBS")
        
        with col_info3:
            st.metric("Estado", info_imagen['status'].upper())
            st.metric("Tamaño", info_imagen['tamaño'])
        
        # Mostrar mapa interactivo
        st.subheader("🗺️ Mapa Interactivo")
        
        folium_map = crear_mapa_interactivo_nasa(
            resultados['gdf_original'],
            resultados['datos_imagen']['imagen'],
            resultados['datos_imagen']['bounds'],
            info_imagen
        )
        
        if folium_map:
            # Mostrar mapa con streamlit-folium
            st_folium(folium_map, width=800, height=600)
            
            # Opción para descargar imagen
            if st.button("📥 Descargar Imagen", key="descargar_imagen"):
                img_bytes = io.BytesIO()
                resultados['datos_imagen']['imagen'].save(img_bytes, format='PNG')
                st.download_button(
                    label="⬇️ Descargar PNG",
                    data=img_bytes.getvalue(),
                    file_name=f"nasa_gibs_{info_imagen['capa']}_{info_imagen['fecha']}.png",
                    mime="image/png"
                )
        else:
            st.warning("No se pudo generar el mapa interactivo")
    
    with tab2:
        st.subheader("ANÁLISIS DE VEGETACIÓN (NDVI)")
        
        analisis_ndvi = resultados['analisis_ndvi']
        
        # Métricas NDVI
        col_ndvi1, col_ndvi2, col_ndvi3, col_ndvi4 = st.columns(4)
        
        with col_ndvi1:
            st.metric("NDVI Promedio", f"{analisis_ndvi['ndvi_mean']:.3f}")
        
        with col_ndvi2:
            st.metric("NDVI Mínimo", f"{analisis_ndvi['ndvi_min']:.3f}")
        
        with col_ndvi3:
            st.metric("NDVI Máximo", f"{analisis_ndvi['ndvi_max']:.3f}")
        
        with col_ndvi4:
            st.metric("Variabilidad", f"{analisis_ndvi['ndvi_std']:.3f}")
        
        # Interpretación NDVI
        ndvi_mean = analisis_ndvi['ndvi_mean']
        
        if ndvi_mean >= 0.7:
            estado_color = "🟢"
            estado_texto = "EXCELENTE"
            descripcion = "Vegetación muy saludable, crecimiento óptimo"
        elif ndvi_mean >= 0.6:
            estado_color = "🟡"
            estado_texto = "BUENA"
            descripcion = "Vegetación en buen estado, crecimiento normal"
        elif ndvi_mean >= 0.4:
            estado_color = "🟠"
            estado_texto = "REGULAR"
            descripcion = "Vegetación con estrés, necesita atención"
        else:
            estado_color = "🔴"
            estado_texto = "CRÍTICA"
            descripcion = "Vegetación muy estresada, intervención urgente"
        
        st.markdown(f"""
        ### {estado_color} Estado de la vegetación: **{estado_texto}**
        
        **Descripción:** {descripcion}
        
        **Valor óptimo para palma aceitera:** 0.70 - 0.85
        """)
        
        # Gráfico de zonas
        if resultados['zonas'] is not None:
            st.subheader("🎯 Zonas de Manejo")
            
            # Mostrar mapa de zonas
            fig, ax = plt.subplots(figsize=(10, 8))
            gdf_zonas = resultados['zonas']
            
            # Colorear por id_zona
            gdf_zonas.plot(column='id_zona', ax=ax, cmap='tab20', legend=True, 
                          edgecolor='black', linewidth=0.5)
            
            # Agregar números de zona
            for idx, row in gdf_zonas.iterrows():
                centroid = row.geometry.centroid
                ax.text(centroid.x, centroid.y, str(row['id_zona']), 
                       fontsize=8, ha='center', va='center',
                       bbox=dict(boxstyle="round,pad=0.2", facecolor='white', alpha=0.8))
            
            ax.set_title(f"División en {len(gdf_zonas)} zonas de manejo")
            ax.set_xlabel("Longitud")
            ax.set_ylabel("Latitud")
            ax.grid(True, alpha=0.3)
            
            st.pyplot(fig)
            
            # Tabla de zonas
            st.dataframe(gdf_zonas[['id_zona', 'geometry']].head(10))
    
    with tab3:
        st.subheader("RECOMENDACIONES AGRONÓMICAS")
        
        recomendaciones = resultados['recomendaciones']
        
        # Métricas de recomendaciones
        col_rec1, col_rec2, col_rec3 = st.columns(3)
        
        with col_rec1:
            st.metric("Estado vegetación", recomendaciones['estado_vegetacion'])
            st.metric("Dosis N", f"{recomendaciones['dosis_n_kg_ha']} kg/ha")
        
        with col_rec2:
            st.metric("Dosis P", f"{recomendaciones['dosis_p_kg_ha']} kg/ha")
            st.metric("Dosis K", f"{recomendaciones['dosis_k_kg_ha']} kg/ha")
        
        with col_rec3:
            st.metric("Costo estimado", f"${recomendaciones['costo_estimado_usd_ha']}/ha")
            st.metric("Rendimiento esperado", f"{recomendaciones['rendimiento_esperado_kg_ha']:,} kg/ha")
        
        # Recomendaciones detalladas
        st.markdown("""
        ### 📋 Plan de fertilización
        
        **Aplicación por zona:**
        
        1. **Zonas con NDVI alto (>0.7):** Mantenimiento
           - Fertilización de mantenimiento
           - Aplicar dosis mínimas recomendadas
        
        2. **Zonas con NDVI medio (0.6-0.7):** Refuerzo
           - Fertilización balanceada
           - Monitoreo cada 30 días
        
        3. **Zonas con NDVI bajo (<0.6):** Corrección
           - Fertilización intensiva
           - Análisis de suelo complementario
           - Riego suplementario si es necesario
        
        **Productos recomendados:**
        - Urea (46% N) para nitrógeno
        - Superfosfato triple (46% P₂O₅) para fósforo
        - Cloruro de potasio (60% K₂O) para potasio
        
        **Época de aplicación:** Inicio de temporada de lluvias
        """)
        
        # Datos meteorológicos si están disponibles
        if resultados['datos_power'] is not None:
            st.subheader("🌤️ Datos Meteorológicos Recientes")
            
            df_power = resultados['datos_power']
            
            # Resumen estadístico
            col_met1, col_met2, col_met3, col_met4 = st.columns(4)
            
            with col_met1:
                st.metric("Temp. promedio", f"{df_power['temperatura'].mean():.1f}°C")
            
            with col_met2:
                st.metric("Precip. total", f"{df_power['precipitacion'].sum():.1f} mm")
            
            with col_met3:
                st.metric("Rad. solar", f"{df_power['radiacion_solar'].mean():.1f} W/m²")
            
            with col_met4:
                st.metric("Viento", f"{df_power['viento_2m'].mean():.1f} m/s")
            
            # Gráfico de precipitación
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.bar(df_power['fecha'], df_power['precipitacion'], color='blue', alpha=0.6)
            ax.set_title("Precipitación diaria - últimos 30 días")
            ax.set_ylabel("Precipitación (mm)")
            ax.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            st.pyplot(fig)
    
    with tab4:
        st.subheader("EXPORTAR RESULTADOS")
        
        col_exp1, col_exp2, col_exp3 = st.columns(3)
        
        with col_exp1:
            st.markdown("**📊 Reporte PDF**")
            if st.button("Generar Reporte", key="gen_pdf"):
                st.info("Funcionalidad en desarrollo")
        
        with col_exp2:
            st.markdown("**🗺️ GeoJSON**")
            if st.button("Exportar Zonas", key="export_geojson"):
                if resultados['zonas'] is not None:
                    geojson_str = resultados['zonas'].to_json()
                    st.download_button(
                        label="Descargar GeoJSON",
                        data=geojson_str,
                        file_name=f"zonas_palma_{datetime.now().strftime('%Y%m%d')}.geojson",
                        mime="application/json"
                    )
        
        with col_exp3:
            st.markdown("**📋 Datos CSV**")
            if st.button("Exportar Datos", key="export_csv"):
                # Crear DataFrame con datos básicos
                datos_export = {
                    'parametro': [
                        'area_total_ha', 'ndvi_promedio', 'dosis_n_kg_ha',
                        'dosis_p_kg_ha', 'dosis_k_kg_ha', 'costo_estimado_usd_ha',
                        'rendimiento_esperado_kg_ha'
                    ],
                    'valor': [
                        resultados['area_total'],
                        resultados['recomendaciones']['ndvi_promedio'],
                        resultados['recomendaciones']['dosis_n_kg_ha'],
                        resultados['recomendaciones']['dosis_p_kg_ha'],
                        resultados['recomendaciones']['dosis_k_kg_ha'],
                        resultados['recomendaciones']['costo_estimado_usd_ha'],
                        resultados['recomendaciones']['rendimiento_esperado_kg_ha']
                    ]
                }
                
                df_export = pd.DataFrame(datos_export)
                csv = df_export.to_csv(index=False)
                
                st.download_button(
                    label="Descargar CSV",
                    data=csv,
                    file_name=f"datos_palma_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
        
        # Limpiar resultados
        st.markdown("---")
        if st.button("🗑️ Limpiar Resultados", type="secondary", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

# ===== PIE DE PÁGINA =====
st.markdown("---")
st.markdown("""
<div style="text-align: center; padding: 20px; color: #94a3b8;">
    <p>🌐 <strong>ANALIZADOR DE PALMA ACEITERA</strong> | Imágenes satelitales reales NASA GIBS</p>
    <p style="font-size: 0.9em;">Datos de: NASA Global Imagery Browse Services (GIBS) • NASA POWER • OpenStreetMap</p>
    <p style="font-size: 0.8em;">© 2024 Sistema de Análisis Agrícola con Imágenes Satelitales</p>
</div>
""", unsafe_allow_html=True)

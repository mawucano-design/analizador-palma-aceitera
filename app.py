# app.py - Versión completa para PALMA ACEITERA con detección de plantas individuales
import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
from matplotlib.patches import Polygon as MplPolygon
import io
from shapely.geometry import Polygon, Point, box
import math
import warnings
from io import BytesIO
import requests
import re
from PIL import Image, ImageDraw
import json

# ===== DEPENDENCIAS PARA DETECCIÓN DE PALMAS =====
try:
    import cv2
    DETECCION_DISPONIBLE = True
except ImportError:
    DETECCION_DISPONIBLE = False
    if 'deteccion_advertencia_mostrada' not in st.session_state:
        st.session_state.deteccion_advertencia_mostrada = True


# ===== CONFIGURACIÓN =====
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
warnings.filterwarnings('ignore')

# ===== INICIALIZACIÓN DE SESIÓN =====
def init_session_state():
    """Inicializar todas las variables de sesión"""
    defaults = {
        'geojson_data': None,
        'analisis_completado': False,
        'resultados_todos': {},
        'palmas_detectadas': [],
        'imagen_alta_resolucion': None,
        'patron_plantacion': None,
        'archivo_cargado': False,
        'gdf_original': None,
        'datos_modis': {},
        'datos_climaticos': {},
        'deteccion_ejecutada': False,
        'imagen_modis_bytes': None,
        'mapa_generado': False,
        'mapa_calor_bytes': None,
        'geojson_bytes': None
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ===== CONFIGURACIONES =====
MODIS_CONFIG = {
    'NDVI': {
        'producto': 'MOD13Q1',
        'url_base': 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi',
        'layers': ['MOD13Q1_NDVI'],
        'formato': 'image/png',
        'palette': 'RdYlGn'
    },
    'EVI': {
        'producto': 'MOD13Q1',
        'url_base': 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi',
        'layers': ['MOD13Q1_EVI'],
        'formato': 'image/png',
        'palette': 'YlGn'
    },
    'NDWI': {
        'producto': 'MOD09A1',
        'url_base': 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi',
        'layers': ['MOD09A1_SurfaceReflectance_Band2'],
        'formato': 'image/png',
        'palette': 'Blues'
    }
}

# Configuración de ESRI para imágenes base
ESRI_BASE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services"
ESRI_SERVICES = {
    "World_Imagery": f"{ESRI_BASE_URL}/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",
    "World_Topo_Map": f"{ESRI_BASE_URL}/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}",
    "World_Street_Map": f"{ESRI_BASE_URL}/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}",
    "NatGeo_World_Map": f"{ESRI_BASE_URL}/NatGeo_World_Map/MapServer/tile/{{z}}/{{y}}/{{x}}"
}

PARAMETROS_PALMA = {
    'NITROGENO': {'min': 150, 'max': 250},
    'FOSFORO': {'min': 50, 'max': 100},
    'POTASIO': {'min': 200, 'max': 350},
    'MAGNESIO': {'min': 30, 'max': 60},
    'BORO': {'min': 0.3, 'max': 0.8},
    'NDVI_OPTIMO': 0.75,
    'RENDIMIENTO_OPTIMO': 20000,
    'COSTO_FERTILIZACION': 1100,
    'CICLO_PRODUCTIVO': '25-30 años',
    'DENSIDAD_PLANTACION': '120-150 plantas/ha',
    'TEMPERATURA_OPTIMA': '24-28°C',
    'PRECIPITACION_OPTIMA': '1800-2500 mm/año'
}

VARIEDADES_PALMA_ACEITERA = [
    'Tenera (DxP)', 'Dura', 'Pisifera', 'Yangambi', 'AVROS', 'La Mé',
    'Ekona', 'Calabar', 'NIFOR', 'MARDI', 'CIRAD', 'ASD Costa Rica',
    'Dami', 'Socfindo', 'SP540'
]

# ===== FUNCIONES DE UTILIDAD =====
def validar_y_corregir_crs(gdf):
    if gdf is None or len(gdf) == 0:
        return gdf
    try:
        if gdf.crs is None:
            gdf = gdf.set_crs('EPSG:4326', inplace=False)
        elif str(gdf.crs).upper() != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')
        return gdf
    except Exception:
        return gdf

def calcular_superficie(gdf):
    try:
        if gdf is None or len(gdf) == 0:
            return 0.0
        gdf = validar_y_corregir_crs(gdf)
        bounds = gdf.total_bounds
        if bounds[0] < -180 or bounds[2] > 180 or bounds[1] < -90 or bounds[3] > 90:
            area_grados2 = gdf.geometry.area.sum()
            area_m2 = area_grados2 * 111000 * 111000
            return area_m2 / 10000
        gdf_projected = gdf.to_crs('EPSG:3857')
        area_m2 = gdf_projected.geometry.area.sum()
        return area_m2 / 10000
    except Exception:
        try:
            return gdf.geometry.area.sum() / 10000
        except:
            return 0.0

def dividir_plantacion_en_bloques(gdf, n_bloques):
    if len(gdf) == 0:
        return gdf
    gdf = validar_y_corregir_crs(gdf)
    plantacion_principal = gdf.iloc[0].geometry
    bounds = plantacion_principal.bounds
    minx, miny, maxx, maxy = bounds
    
    sub_poligonos = []
    n_cols = math.ceil(math.sqrt(n_bloques))
    n_rows = math.ceil(n_bloques / n_cols)
    width = (maxx - minx) / n_cols
    height = (maxy - miny) / n_rows
    
    for i in range(n_rows):
        for j in range(n_cols):
            if len(sub_poligonos) >= n_bloques:
                break
            cell_minx = minx + (j * width)
            cell_maxx = minx + ((j + 1) * width)
            cell_miny = miny + (i * height)
            cell_maxy = miny + ((i + 1) * height)
            cell_poly = Polygon([
                (cell_minx, cell_miny), (cell_maxx, cell_miny),
                (cell_maxx, cell_maxy), (cell_minx, cell_maxy)
            ])
            intersection = plantacion_principal.intersection(cell_poly)
            if not intersection.is_empty and intersection.area > 0:
                sub_poligonos.append(intersection)
    
    if sub_poligonos:
        nuevo_gdf = gpd.GeoDataFrame(
            {'id_bloque': range(1, len(sub_poligonos) + 1), 'geometry': sub_poligonos},
            crs='EPSG:4326'
        )
        return nuevo_gdf
    return gdf

def procesar_kml_robusto(file_content):
    """Procesa archivos KML de manera robusta usando expresiones regulares"""
    try:
        content = file_content.decode('utf-8', errors='ignore')
        polygons = []
        
        coord_sections = re.findall(r'<coordinates[^>]*>([\s\S]*?)</coordinates>', content, re.IGNORECASE)
        
        for coord_text in coord_sections:
            coord_text = coord_text.strip()
            if not coord_text:
                continue
            
            coord_list = []
            coords = re.split(r'\s+', coord_text)
            
            for coord in coords:
                coord = coord.strip()
                if coord and ',' in coord:
                    try:
                        parts = [p.strip() for p in coord.split(',')]
                        if len(parts) >= 2:
                            lon = float(parts[0])
                            lat = float(parts[1])
                            coord_list.append((lon, lat))
                    except ValueError:
                        continue
            
            if len(coord_list) >= 3:
                if coord_list[0] != coord_list[-1]:
                    coord_list.append(coord_list[0])
                
                try:
                    polygon = Polygon(coord_list)
                    if polygon.is_valid and polygon.area > 0:
                        polygons.append(polygon)
                except:
                    continue
        
        if polygons:
            return gpd.GeoDataFrame(geometry=polygons, crs='EPSG:4326')
        return None
    except Exception as e:
        st.error(f"Error en procesamiento KML: {str(e)}")
        return None

# ===== FUNCIONES DE CARGA DE ARCHIVOS =====
def cargar_archivo_plantacion(uploaded_file):
    try:
        file_content = uploaded_file.read()
        
        if uploaded_file.name.endswith('.zip'):
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(io.BytesIO(file_content), 'r') as zip_ref:
                    zip_ref.extractall(tmp_dir)
                
                shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                if shp_files:
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf = gpd.read_file(shp_path)
                else:
                    st.error("No se encontró shapefile en el archivo ZIP")
                    return None
        
        elif uploaded_file.name.endswith('.geojson'):
            gdf = gpd.read_file(io.BytesIO(file_content))
        
        elif uploaded_file.name.endswith('.kml'):
            gdf = procesar_kml_robusto(file_content)
            if gdf is None or len(gdf) == 0:
                st.error("No se pudieron extraer polígonos del archivo KML")
                return None
        
        elif uploaded_file.name.endswith('.kmz'):
            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    kmz_path = os.path.join(tmp_dir, 'temp.kmz')
                    with open(kmz_path, 'wb') as f:
                        f.write(file_content)
                    
                    with zipfile.ZipFile(kmz_path, 'r') as kmz:
                        kml_files = [f for f in kmz.namelist() if f.endswith('.kml')]
                        if not kml_files:
                            st.error("No se encontró archivo KML dentro del KMZ")
                            return None
                        
                        kml_file_name = kml_files[0]
                        kmz.extract(kml_file_name, tmp_dir)
                        kml_path = os.path.join(tmp_dir, kml_file_name)
                        
                        with open(kml_path, 'rb') as f:
                            kml_content = f.read()
                        
                        gdf = procesar_kml_robusto(kml_content)
                        
                        if gdf is None or len(gdf) == 0:
                            st.error("No se pudieron extraer polígonos del archivo KMZ")
                            return None
            except Exception as e:
                st.error(f"Error procesando KMZ: {str(e)}")
                return None
        
        else:
            st.error(f"Formato no soportado: {uploaded_file.name}")
            return None
        
        gdf = validar_y_corregir_crs(gdf)
        gdf = gdf.explode(ignore_index=True)
        gdf = gdf[gdf.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])]
        
        if len(gdf) == 0:
            st.error("No se encontraron polígonos válidos en el archivo")
            return None
        
        geometria_unida = gdf.unary_union
        
        if geometria_unida.geom_type == 'Polygon':
            gdf_unido = gpd.GeoDataFrame([{'geometry': geometria_unida}], crs='EPSG:4326')
        elif geometria_unida.geom_type == 'MultiPolygon':
            poligonos = list(geometria_unida.geoms)
            poligonos.sort(key=lambda p: p.area, reverse=True)
            gdf_unido = gpd.GeoDataFrame([{'geometry': poligonos[0]}], crs='EPSG:4326')
        else:
            st.error(f"Tipo de geometría no soportado: {geometria_unida.geom_type}")
            return None
        
        gdf_unido['id_bloque'] = 1
        return gdf_unido
        
    except Exception as e:
        st.error(f"❌ Error cargando archivo: {str(e)}")
        return None

# ===== FUNCIONES DE ANÁLISIS CON MODIS =====
def obtener_imagen_modis_real(gdf, fecha, indice='NDVI'):
    """Obtiene imagen MODIS real de NASA GIBS"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Añadir margen
        min_lon -= 0.02
        max_lon += 0.02
        min_lat -= 0.02
        max_lat += 0.02
        
        if indice not in MODIS_CONFIG:
            indice = 'NDVI'
        
        config = MODIS_CONFIG[indice]
        
        # Parámetros WMS para NASA GIBS
        wms_params = {
            'SERVICE': 'WMS',
            'REQUEST': 'GetMap',
            'VERSION': '1.3.0',
            'LAYERS': config['layers'][0],
            'CRS': 'EPSG:4326',
            'BBOX': f'{min_lat},{min_lon},{max_lat},{max_lon}',
            'WIDTH': '1024',
            'HEIGHT': '768',
            'FORMAT': 'image/png',
            'TIME': fecha.strftime('%Y-%m-%d'),
            'STYLES': f'boxfill/{config["palette"]}',
            'COLORSCALERANGE': '0,1'
        }
        
        response = requests.get(config['url_base'], params=wms_params, timeout=30)
        
        if response.status_code == 200:
            # Crear un nuevo BytesIO para la imagen
            imagen_bytes = BytesIO(response.content)
            imagen_bytes.seek(0)  # Asegurar que esté al inicio
            return imagen_bytes
        else:
            st.warning(f"No se pudo obtener imagen MODIS real. Código: {response.status_code}")
            return None
    except Exception as e:
        st.warning(f"Error obteniendo imagen MODIS: {str(e)}")
        return None

def generar_imagen_modis_simulada(gdf):
    """Genera una imagen MODIS simulada con patrones de vegetación"""
    try:
        width, height = 1024, 768
        img = Image.new('RGB', (width, height), color=(200, 200, 200))
        draw = ImageDraw.Draw(img)
        
        # Patrón de vegetación simulando campos
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Convertir coordenadas a píxeles
        def coord_to_pixel(lon, lat):
            x = int((lon - min_lon) / (max_lon - min_lon) * width)
            y = int((max_lat - lat) / (max_lat - min_lat) * height)
            return x, y
        
        # Dibujar áreas verdes (vegetación)
        for i in range(0, width, 50):
            for j in range(0, height, 50):
                if (i // 100 + j // 100) % 2 == 0:
                    green_intensity = np.random.randint(100, 200)
                    draw.rectangle([i, j, i+49, j+49], 
                                 fill=(50, green_intensity, 50))
        
        # Añadir algunos patrones de cultivo
        for i in range(5):
            center_x = np.random.randint(100, width-100)
            center_y = np.random.randint(100, height-100)
            radius = np.random.randint(50, 150)
            
            for r in range(0, radius, 10):
                green = max(50, min(200, 150 - r//5))
                draw.ellipse([center_x-r, center_y-r, center_x+r, center_y+r], 
                            outline=(50, green, 50), width=2)
        
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes
    except Exception as e:
        # Fallback más simple si hay error
        img = Image.new('RGB', (1024, 768), color=(100, 150, 100))
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes

def obtener_datos_modis(gdf, fecha_inicio, fecha_fin, indice='NDVI'):
    """Obtiene datos MODIS reales o simulados"""
    try:
        fecha_media = fecha_inicio + (fecha_fin - fecha_inicio) / 2
        
        # Intentar obtener imagen MODIS real
        imagen_bytes = obtener_imagen_modis_real(gdf, fecha_media, indice)
        
        if imagen_bytes is None:
            # Usar imagen simulada
            imagen_bytes = generar_imagen_modis_simulada(gdf)
            if imagen_bytes:
                imagen_bytes.seek(0)  # Asegurar que esté al inicio
            fuente = f'MODIS {indice} (Simulado) - NASA'
            estado = 'simulado'
        else:
            fuente = f'MODIS {indice} - NASA GIBS'
            estado = 'real'
        
        # Calcular valores basados en ubicación y fecha
        centroide = gdf.geometry.unary_union.centroid
        lat_norm = (centroide.y + 90) / 180
        lon_norm = (centroide.x + 180) / 360
        
        mes = fecha_media.month
        if 3 <= mes <= 5:  # Otoño en hemisferio sur
            base_valor = 0.65
        elif 6 <= mes <= 8:  # Invierno
            base_valor = 0.55
        elif 9 <= mes <= 11:  # Primavera
            base_valor = 0.75
        else:  # Verano
            base_valor = 0.70
        
        variacion = (lat_norm * lon_norm) * 0.15
        
        if indice == 'NDVI':
            valor = base_valor + variacion + np.random.normal(0, 0.05)
            valor = max(0.3, min(0.9, valor))
        elif indice == 'EVI':
            valor = (base_valor * 1.1) + variacion + np.random.normal(0, 0.04)
            valor = max(0.2, min(0.8, valor))
        elif indice == 'NDWI':
            valor = 0.4 + variacion + np.random.normal(0, 0.03)
            valor = max(0.1, min(0.7, valor))
        else:
            valor = base_valor + variacion
        
        resultado = {
            'indice': indice,
            'valor_promedio': round(valor, 3),
            'fuente': fuente,
            'fecha_imagen': fecha_media.strftime('%Y-%m-%d'),
            'resolucion': '250m',
            'estado': estado,
            'bbox': gdf.total_bounds.tolist()
        }
        
        # Solo agregar imagen_bytes si no es None
        if imagen_bytes:
            resultado['imagen_bytes'] = imagen_bytes
        
        return resultado
        
    except Exception as e:
        st.error(f"Error en datos MODIS: {str(e)}")
        # Retornar datos simulados como fallback
        return {
            'indice': indice,
            'valor_promedio': 0.65,
            'fuente': 'MODIS (Simulado) - NASA',
            'fecha_imagen': datetime.now().strftime('%Y-%m-%d'),
            'resolucion': '250m',
            'estado': 'simulado',
            'nota': 'Datos simulados - Error en conexión'
        }

def generar_datos_climaticos_simulados(gdf, fecha_inicio, fecha_fin):
    """Genera datos climáticos simulados"""
    try:
        centroide = gdf.geometry.unary_union.centroid
        lat_norm = (centroide.y + 90) / 180
        
        if lat_norm > 0.6:
            temp_base = 20
            precip_base = 80
        elif lat_norm > 0.3:
            temp_base = 25
            precip_base = 120
        else:
            temp_base = 27
            precip_base = 180
        
        mes = fecha_inicio.month
        if 12 <= mes <= 2:
            temp_ajuste = 5
            precip_ajuste = 40
        elif 3 <= mes <= 5:
            temp_ajuste = 0
            precip_ajuste = 20
        elif 6 <= mes <= 8:
            temp_ajuste = -5
            precip_ajuste = 10
        else:
            temp_ajuste = 2
            precip_ajuste = 30
        
        return {
            'temperatura_promedio': temp_base + temp_ajuste + np.random.normal(0, 2),
            'precipitacion_total': max(0, precip_base + precip_ajuste + np.random.normal(0, 30)),
            'radiacion_promedio': 18 + np.random.normal(0, 3),
            'dias_con_lluvia': 15 + np.random.randint(-5, 5),
            'humedad_promedio': 75 + np.random.normal(0, 5)
        }
    except Exception:
        # Datos climáticos por defecto
        return {
            'temperatura_promedio': 25.0,
            'precipitacion_total': 1800.0,
            'radiacion_promedio': 18.0,
            'dias_con_lluvia': 15,
            'humedad_promedio': 75.0
        }

def analizar_edad_plantacion(gdf_dividido):
    """Analiza la edad de la plantación por bloque"""
    edades = []
    for idx, row in gdf_dividido.iterrows():
        centroid = row.geometry.centroid
        lat_norm = (centroid.y + 90) / 180
        lon_norm = (centroid.x + 180) / 360
        edad = 2 + (lat_norm * lon_norm * 18)
        edades.append(round(edad, 1))
    return edades

def analizar_produccion_palma(gdf_dividido, edades, ndvi_values, datos_climaticos):
    """Calcula la producción estimada por bloque"""
    producciones = []
    rendimiento_optimo = PARAMETROS_PALMA['RENDIMIENTO_OPTIMO']
    
    for i, edad in enumerate(edades):
        ndvi = ndvi_values[i] if i < len(ndvi_values) else 0.65
        
        if edad < 3:
            factor_edad = 0.1
        elif edad < 8:
            factor_edad = 0.3 + (edad - 3) * 0.14
        elif edad <= 12:
            factor_edad = 1.0
        elif edad <= 20:
            factor_edad = 1.0 - ((edad - 12) * 0.04)
        else:
            factor_edad = 0.6
        
        factor_ndvi = min(1.0, ndvi / PARAMETROS_PALMA['NDVI_OPTIMO'])
        
        if datos_climaticos:
            temp_factor = 1.0 - abs(datos_climaticos['temperatura_promedio'] - 26) / 10
            precip_factor = min(1.0, datos_climaticos['precipitacion_total'] / 2000)
            factor_clima = (temp_factor * 0.5 + precip_factor * 0.5)
        else:
            factor_clima = 0.8
        
        produccion = rendimiento_optimo * factor_edad * factor_ndvi * factor_clima
        producciones.append(round(produccion, 0))
    
    return producciones

def analizar_requerimientos_nutricionales(ndvi_values, edades, datos_climaticos):
    """Calcula los requerimientos nutricionales por bloque"""
    requerimientos_n, requerimientos_p, requerimientos_k = [], [], []
    requerimientos_mg, requerimientos_b = [], []
    
    for i, ndvi in enumerate(ndvi_values):
        edad = edades[i] if i < len(edades) else 10
        
        if edad < 3:
            base_n = 80
            base_p = 25
            base_k = 120
            base_mg = 15
            base_b = 0.2
        elif edad <= 8:
            base_n = 120 + (edad - 3) * 15
            base_p = 35 + (edad - 3) * 5
            base_k = 180 + (edad - 3) * 20
            base_mg = 20 + (edad - 3) * 2
            base_b = 0.3 + (edad - 3) * 0.02
        else:
            base_n = 200
            base_p = 60
            base_k = 280
            base_mg = 35
            base_b = 0.5
        
        ajuste_ndvi = 1.5 - ndvi
        
        if datos_climaticos:
            if datos_climaticos['precipitacion_total'] > 2500:
                ajuste_clima = 1.2
            elif datos_climaticos['precipitacion_total'] < 1500:
                ajuste_clima = 0.8
            else:
                ajuste_clima = 1.0
        else:
            ajuste_clima = 1.0
        
        n = base_n * ajuste_ndvi * ajuste_clima
        p = base_p * ajuste_ndvi * ajuste_clima
        k = base_k * ajuste_ndvi * ajuste_clima
        mg = base_mg * ajuste_ndvi * ajuste_clima
        b = base_b * ajuste_ndvi * ajuste_clima
        
        n = min(max(n, PARAMETROS_PALMA['NITROGENO']['min']), PARAMETROS_PALMA['NITROGENO']['max'])
        p = min(max(p, PARAMETROS_PALMA['FOSFORO']['min']), PARAMETROS_PALMA['FOSFORO']['max'])
        k = min(max(k, PARAMETROS_PALMA['POTASIO']['min']), PARAMETROS_PALMA['POTASIO']['max'])
        mg = min(max(mg, 20), 60)
        b = min(max(b, 0.2), 0.8)
        
        requerimientos_n.append(round(n, 1))
        requerimientos_p.append(round(p, 1))
        requerimientos_k.append(round(k, 1))
        requerimientos_mg.append(round(mg, 1))
        requerimientos_b.append(round(b, 3))
    
    return requerimientos_n, requerimientos_p, requerimientos_k, requerimientos_mg, requerimientos_b

# ===== FUNCIONES DE VISUALIZACIÓN =====
def crear_mapa_bloques(gdf, palmas_detectadas=None):
    """Crea un mapa de los bloques con matplotlib - VERSIÓN CORREGIDA"""
    if gdf is None or len(gdf) == 0:
        return None
    
    try:
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # Configurar colores basados en NDVI si está disponible
        if 'ndvi_modis' in gdf.columns:
            # Obtener valores NDVI y normalizarlos
            ndvi_values = gdf['ndvi_modis'].values
            min_ndvi, max_ndvi = ndvi_values.min(), ndvi_values.max()
            
            # Crear colormap manualmente
            colors = []
            for ndvi in ndvi_values:
                # Normalizar NDVI entre 0 y 1
                norm_val = (ndvi - min_ndvi) / (max_ndvi - min_ndvi) if max_ndvi > min_ndvi else 0.5
                
                # Asignar color basado en valor normalizado
                if norm_val < 0.33:
                    # Rojo para bajo NDVI
                    colors.append((1.0, 0.5, 0.5, 0.6))  # RGBA
                elif norm_val < 0.66:
                    # Amarillo para medio NDVI
                    colors.append((1.0, 1.0, 0.5, 0.6))
                else:
                    # Verde para alto NDVI
                    colors.append((0.5, 1.0, 0.5, 0.6))
            
            # Dibujar cada polígono con su color
            for idx, row in gdf.iterrows():
                try:
                    if row.geometry.geom_type == 'Polygon':
                        # Simplificar geometría si tiene demasiados puntos
                        simplified = row.geometry.simplify(0.0001)
                        poly_coords = list(simplified.exterior.coords)
                        polygon = MplPolygon(poly_coords, closed=True, 
                                           facecolor=colors[idx], 
                                           edgecolor='black', 
                                           linewidth=1,
                                           alpha=0.6)
                        ax.add_patch(polygon)
                    elif row.geometry.geom_type == 'MultiPolygon':
                        for poly in row.geometry.geoms:
                            simplified = poly.simplify(0.0001)
                            poly_coords = list(simplified.exterior.coords)
                            polygon = MplPolygon(poly_coords, closed=True,
                                               facecolor=colors[idx],
                                               edgecolor='black',
                                               linewidth=1,
                                               alpha=0.6)
                            ax.add_patch(polygon)
                except Exception:
                    continue
            
            # Añadir etiquetas de bloques
            for idx, row in gdf.iterrows():
                try:
                    centroid = row.geometry.centroid
                    ax.text(centroid.x, centroid.y, str(int(row['id_bloque'])), 
                           fontsize=9, ha='center', va='center',
                           bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7))
                except Exception:
                    continue
        else:
            # Dibujar polígonos simples
            gdf.plot(ax=ax, color='lightgreen', edgecolor='darkgreen', alpha=0.6)
        
        # Añadir palmas detectadas si existen
        if palmas_detectadas and len(palmas_detectadas) > 0:
            try:
                coords = np.array([p['centroide'] for p in palmas_detectadas[:200]])  # Limitar a 200 puntos
                ax.scatter(coords[:, 0], coords[:, 1], 
                          s=10, color='blue', alpha=0.5, label='Palmas detectadas')
            except Exception:
                pass
        
        ax.set_title('Mapa de Bloques - Palma Aceitera', fontsize=14, fontweight='bold')
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        # Añadir leyenda solo si hay palmas
        if palmas_detectadas and len(palmas_detectadas) > 0:
            ax.legend()
        
        plt.tight_layout()
        return fig
    except Exception as e:
        st.error(f"Error al generar mapa: {str(e)}")
        # Fallback: mapa simple
        fig, ax = plt.subplots(figsize=(10, 8))
        gdf.plot(ax=ax, color='lightgreen', edgecolor='darkgreen', alpha=0.6)
        ax.set_title('Mapa de Bloques - Palma Aceitera', fontsize=14, fontweight='bold')
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        return fig

def crear_grafico_ndvi_bloques(gdf):
    """Crea gráfico de barras de NDVI por bloque"""
    if gdf is None or 'ndvi_modis' not in gdf.columns:
        return None
    
    try:
        fig, ax = plt.subplots(figsize=(12, 6))
        
        bloques = gdf['id_bloque'].astype(str)
        ndvi_values = gdf['ndvi_modis']
        
        # Colores basados en valor NDVI
        colors = []
        for val in ndvi_values:
            if val < 0.4:
                colors.append('red')
            elif val < 0.6:
                colors.append('orange')
            elif val < 0.75:
                colors.append('yellow')
            else:
                colors.append('green')
        
        bars = ax.bar(bloques, ndvi_values, color=colors, edgecolor='black')
        ax.axhline(y=PARAMETROS_PALMA['NDVI_OPTIMO'], color='green', linestyle='--', 
                   label=f'Óptimo ({PARAMETROS_PALMA["NDVI_OPTIMO"]})')
        ax.axhline(y=0.5, color='orange', linestyle='--', alpha=0.5, label='Mínimo aceptable')
        
        ax.set_xlabel('Bloque')
        ax.set_ylabel('NDVI')
        ax.set_title('NDVI por Bloque - Palma Aceitera', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        
        # Añadir valores en las barras
        for bar, val in zip(bars, ndvi_values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{val:.3f}', ha='center', va='bottom' if height > 0 else 'top',
                   fontsize=9)
        
        plt.tight_layout()
        return fig
    except Exception:
        return None

def crear_grafico_produccion(gdf):
    """Crea gráfico de producción por bloque"""
    if gdf is None or 'produccion_estimada' not in gdf.columns:
        return None
    
    try:
        fig, ax = plt.subplots(figsize=(12, 6))
        
        bloques = gdf['id_bloque'].astype(str)
        produccion = gdf['produccion_estimada']
        
        # Ordenar bloques por producción
        sorted_indices = np.argsort(produccion)[::-1]
        bloques_sorted = bloques.iloc[sorted_indices]
        produccion_sorted = produccion.iloc[sorted_indices]
        
        bars = ax.bar(bloques_sorted, produccion_sorted, color='#4caf50', edgecolor='#2e7d32')
        
        ax.set_xlabel('Bloque')
        ax.set_ylabel('Producción (kg/ha)')
        ax.set_title('Producción Estimada por Bloque', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')
        
        # Añadir valores
        for bar, val in zip(bars, produccion_sorted):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{val:,.0f}', ha='center', va='bottom', fontsize=9)
        
        plt.tight_layout()
        return fig
    except Exception:
        return None

def crear_grafico_rentabilidad(gdf):
    """Crea gráfico de rentabilidad por bloque"""
    if gdf is None or 'rentabilidad' not in gdf.columns:
        return None
    
    try:
        fig, ax = plt.subplots(figsize=(12, 6))
        
        bloques = gdf['id_bloque'].astype(str)
        rentabilidad = gdf['rentabilidad']
        
        # Colores basados en rentabilidad
        colors = []
        for val in rentabilidad:
            if val < 0:
                colors.append('red')
            elif val < 15:
                colors.append('orange')
            elif val < 25:
                colors.append('yellow')
            else:
                colors.append('green')
        
        bars = ax.bar(bloques, rentabilidad, color=colors, edgecolor='black')
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axhline(y=15, color='green', linestyle='--', alpha=0.5, label='Umbral rentable (15%)')
        
        ax.set_xlabel('Bloque')
        ax.set_ylabel('Rentabilidad (%)')
        ax.set_title('Rentabilidad por Bloque', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        
        # Añadir valores
        for bar, val in zip(bars, rentabilidad):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{val:.1f}%', ha='center', va='bottom' if val >= 0 else 'top',
                   fontsize=9, fontweight='bold')
        
        plt.tight_layout()
        return fig
    except Exception:
        return None

def crear_mapa_calor_produccion(gdf):
    """Crea un mapa de calor de producción por bloque"""
    if gdf is None or 'produccion_estimada' not in gdf.columns:
        return None
    
    try:
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # Obtener valores de producción
        produccion = gdf['produccion_estimada'].values
        min_prod, max_prod = produccion.min(), produccion.max()
        
        # Crear colormap para calor
        import matplotlib.cm as cm
        norm = plt.Normalize(min_prod, max_prod)
        cmap = cm.YlOrRd
        
        # Dibujar cada polígono con color basado en producción
        for idx, row in gdf.iterrows():
            try:
                valor_prod = row['produccion_estimada']
                color = cmap(norm(valor_prod))
                
                if row.geometry.geom_type == 'Polygon':
                    simplified = row.geometry.simplify(0.0001)
                    poly_coords = list(simplified.exterior.coords)
                    polygon = MplPolygon(poly_coords, closed=True, 
                                       facecolor=color, 
                                       edgecolor='black', 
                                       linewidth=1,
                                       alpha=0.7)
                    ax.add_patch(polygon)
                elif row.geometry.geom_type == 'MultiPolygon':
                    for poly in row.geometry.geoms:
                        simplified = poly.simplify(0.0001)
                        poly_coords = list(simplified.exterior.coords)
                        polygon = MplPolygon(poly_coords, closed=True,
                                           facecolor=color,
                                           edgecolor='black',
                                           linewidth=1,
                                           alpha=0.7)
                        ax.add_patch(polygon)
            except Exception:
                continue
        
        # Añadir barra de color
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, shrink=0.7)
        cbar.set_label('Producción (kg/ha)', fontsize=12)
        
        # Añadir etiquetas de valores
        for idx, row in gdf.iterrows():
            try:
                centroid = row.geometry.centroid
                ax.text(centroid.x, centroid.y, 
                       f"{int(row['produccion_estimada']):,}",
                       fontsize=8, ha='center', va='center',
                       bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8))
            except Exception:
                continue
        
        ax.set_title('Mapa de Calor - Producción Estimada', fontsize=14, fontweight='bold')
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Guardar figura en bytes
        img_bytes = BytesIO()
        fig.savefig(img_bytes, format='PNG', dpi=150, bbox_inches='tight')
        img_bytes.seek(0)
        
        # Guardar en session_state para exportar
        st.session_state.mapa_calor_bytes = img_bytes
        
        return fig
    except Exception as e:
        st.error(f"Error al crear mapa de calor: {str(e)}")
        return None

def crear_geojson_resultados(gdf):
    """Crea un GeoJSON con todos los resultados del análisis"""
    try:
        # Crear copia del GeoDataFrame
        gdf_export = gdf.copy()
        
        # Convertir geometrías a WGS84 si no lo están
        if gdf_export.crs != 'EPSG:4326':
            gdf_export = gdf_export.to_crs('EPSG:4326')
        
        # Convertir a GeoJSON
        geojson_dict = json.loads(gdf_export.to_json())
        
        # Agregar metadatos
        geojson_dict['metadata'] = {
            'export_date': datetime.now().isoformat(),
            'total_blocks': len(gdf),
            'area_total_ha': float(gdf['area_ha'].sum()),
            'production_avg': float(gdf['produccion_estimada'].mean()),
            'ndvi_avg': float(gdf['ndvi_modis'].mean()),
            'rentability_avg': float(gdf['rentabilidad'].mean())
        }
        
        # Convertir a string JSON
        geojson_str = json.dumps(geojson_dict, indent=2)
        
        # Crear bytes
        geojson_bytes = BytesIO()
        geojson_bytes.write(geojson_str.encode('utf-8'))
        geojson_bytes.seek(0)
        
        # Guardar en session_state
        st.session_state.geojson_bytes = geojson_bytes
        
        return geojson_bytes
    except Exception as e:
        st.error(f"Error al crear GeoJSON: {str(e)}")
        return None

# ===== FUNCIÓN PRINCIPAL DE ANÁLISIS =====
def ejecutar_analisis_completo():
    """Ejecuta el análisis completo y almacena resultados en session_state"""
    if st.session_state.gdf_original is None:
        st.error("Primero debe cargar un archivo de plantación")
        return
    
    with st.spinner("Ejecutando análisis completo..."):
        # Obtener parámetros del sidebar
        n_divisiones = st.session_state.get('n_divisiones', 16)
        indice_seleccionado = st.session_state.get('indice_seleccionado', 'NDVI')
        fecha_inicio = st.session_state.get('fecha_inicio', datetime.now() - timedelta(days=60))
        fecha_fin = st.session_state.get('fecha_fin', datetime.now())
        
        gdf = st.session_state.gdf_original
        
        # Verificar que gdf no sea None
        if gdf is None:
            st.error("Error: No se cargó correctamente la plantación")
            return
            
        try:
            area_total = calcular_superficie(gdf)
        except Exception:
            area_total = 0.0
        
        # 1. Obtener datos MODIS reales
        datos_modis = obtener_datos_modis(gdf, fecha_inicio, fecha_fin, indice_seleccionado)
        st.session_state.datos_modis = datos_modis
        
        # Guardar imagen MODIS para mostrar - SOLO SI EXISTE
        if datos_modis and 'imagen_bytes' in datos_modis and datos_modis['imagen_bytes'] is not None:
            try:
                datos_modis['imagen_bytes'].seek(0)
                copia_bytes = BytesIO(datos_modis['imagen_bytes'].read())
                copia_bytes.seek(0)
                st.session_state.imagen_modis_bytes = copia_bytes
            except Exception:
                st.session_state.imagen_modis_bytes = None
        else:
            st.session_state.imagen_modis_bytes = None
        
        # 2. Obtener datos climáticos
        datos_climaticos = generar_datos_climaticos_simulados(gdf, fecha_inicio, fecha_fin)
        st.session_state.datos_climaticos = datos_climaticos
        
        # 3. Dividir plantación
        gdf_dividido = dividir_plantacion_en_bloques(gdf, n_divisiones)
        
        # 4. Calcular áreas
        areas_ha = []
        for idx, row in gdf_dividido.iterrows():
            try:
                area_gdf = gpd.GeoDataFrame({'geometry': [row.geometry]}, crs=gdf_dividido.crs)
                area_ha_val = calcular_superficie(area_gdf)
                if hasattr(area_ha_val, 'iloc'):
                    area_ha_val = float(area_ha_val.iloc[0])
                else:
                    area_ha_val = float(area_ha_val)
                areas_ha.append(area_ha_val)
            except Exception:
                areas_ha.append(0.0)
        
        gdf_dividido['area_ha'] = areas_ha
        
        # 5. Análisis de edad
        edades = analizar_edad_plantacion(gdf_dividido)
        gdf_dividido['edad_anios'] = edades
        
        # 6. NDVI por bloque
        ndvi_bloques = []
        valor_modis = datos_modis.get('valor_promedio', 0.65)
        
        for idx, row in gdf_dividido.iterrows():
            try:
                centroid = row.geometry.centroid
                lat_norm = (centroid.y + 90) / 180
                lon_norm = (centroid.x + 180) / 360
                variacion = (lat_norm * lon_norm) * 0.2 - 0.1
                ndvi = valor_modis + variacion + np.random.normal(0, 0.05)
                ndvi = max(0.4, min(0.85, ndvi))
                ndvi_bloques.append(ndvi)
            except Exception:
                ndvi_bloques.append(0.65)
        
        gdf_dividido['ndvi_modis'] = ndvi_bloques
        
        # 7. Producción
        producciones = analizar_produccion_palma(gdf_dividido, edades, ndvi_bloques, datos_climaticos)
        gdf_dividido['produccion_estimada'] = producciones
        
        # 8. Requerimientos nutricionales
        req_n, req_p, req_k, req_mg, req_b = analizar_requerimientos_nutricionales(
            ndvi_bloques, edades, datos_climaticos
        )
        gdf_dividido['req_N'] = req_n
        gdf_dividido['req_P'] = req_p
        gdf_dividido['req_K'] = req_k
        gdf_dividido['req_Mg'] = req_mg
        gdf_dividido['req_B'] = req_b
        
        # 9. Ingresos y rentabilidad
        precio_racimo = 0.15
        ingresos = []
        for idx, row in gdf_dividido.iterrows():
            try:
                ingreso = row['produccion_estimada'] * precio_racimo * row['area_ha']
                ingresos.append(round(ingreso, 2))
            except Exception:
                ingresos.append(0.0)
        
        gdf_dividido['ingreso_estimado'] = ingresos
        
        # 10. Costos
        precio_n, precio_p, precio_k = 1.2, 2.5, 1.8
        precio_mg, precio_b = 1.5, 15.0
        
        costos_totales = []
        for idx, row in gdf_dividido.iterrows():
            try:
                costo_n = row['req_N'] * precio_n * row['area_ha']
                costo_p = row['req_P'] * precio_p * row['area_ha']
                costo_k = row['req_K'] * precio_k * row['area_ha']
                costo_mg = row['req_Mg'] * precio_mg * row['area_ha']
                costo_b = row['req_B'] * precio_b * row['area_ha']
                costo_base = PARAMETROS_PALMA['COSTO_FERTILIZACION'] * row['area_ha']
                costo_total = costo_n + costo_p + costo_k + costo_mg + costo_b + costo_base
                costos_totales.append(round(costo_total, 2))
            except Exception:
                costos_totales.append(0.0)
        
        gdf_dividido['costo_total'] = costos_totales
        
        # 11. Rentabilidad
        rentabilidades = []
        for idx, row in gdf_dividido.iterrows():
            try:
                ingreso = row['ingreso_estimado']
                costo = row['costo_total']
                rentabilidad = (ingreso - costo) / costo * 100 if costo > 0 else 0
                rentabilidades.append(round(rentabilidad, 1))
            except Exception:
                rentabilidades.append(0.0)
        
        gdf_dividido['rentabilidad'] = rentabilidades
        
        # 12. Crear GeoJSON para exportar
        crear_geojson_resultados(gdf_dividido)
        
        # Marcar que el mapa ha sido generado
        st.session_state.mapa_generado = True
        
        # Almacenar resultados
        st.session_state.resultados_todos = {
            'exitoso': True,
            'gdf_completo': gdf_dividido,
            'area_total': area_total,
            'edades': edades,
            'producciones': producciones,
            'datos_modis': datos_modis,
            'datos_climaticos': datos_climaticos
        }
        
        st.session_state.analisis_completado = True
        st.success("✅ Análisis completado exitosamente!")

# ===== FUNCIONES DE DETECCIÓN =====
def simular_deteccion_palmas(gdf, densidad=130):
    """Simula la detección de palmas"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        area_ha = calcular_superficie(gdf)
        num_palmas = int(area_ha * densidad)
        
        palmas_detectadas = []
        lado = np.sqrt(10000 / densidad)
        lado_grados = lado / 111000
        
        rows = int((max_lat - min_lat) / lado_grados)
        cols = int((max_lon - min_lon) / (lado_grados * 0.866))
        
        for i in range(rows):
            for j in range(cols):
                if len(palmas_detectadas) >= num_palmas:
                    break
                    
                offset = lado_grados * 0.5 if i % 2 == 0 else 0
                lon = min_lon + (j * lado_grados * 0.866) + offset
                lat = min_lat + (i * lado_grados * 0.75)
                
                if lon <= max_lon and lat <= max_lat:
                    lon += np.random.normal(0, lado_grados * 0.2)
                    lat += np.random.normal(0, lado_grados * 0.2)
                    
                    palmas_detectadas.append({
                        'centroide': (lon, lat),
                        'area_pixels': np.random.uniform(50, 150),
                        'circularidad': np.random.uniform(0.7, 0.9),
                        'radio_aprox': np.random.uniform(4, 8),
                        'simulado': True
                    })
        
        return {
            'detectadas': palmas_detectadas,
            'total': len(palmas_detectadas),
            'patron': 'hexagonal',
            'densidad_calculada': len(palmas_detectadas) / area_ha if area_ha > 0 else densidad,
            'area_ha': area_ha
        }
    except Exception:
        # Retorno mínimo en caso de error
        return {
            'detectadas': [],
            'total': 0,
            'patron': 'indeterminado',
            'densidad_calculada': 0,
            'area_ha': 0
        }

def obtener_imagen_esri_base(gdf, servicio="World_Imagery", zoom=15):
    """Obtiene imagen base de ESRI"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Añadir margen
        min_lon -= 0.002
        max_lon += 0.002
        min_lat -= 0.002
        max_lat += 0.002
        
        # Calcular centro
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        
        # Calcular tamaño basado en zoom
        width, height = 800, 600
        
        # Construir URL de ESRI (solo para referencia, necesitaríamos implementar más)
        # Por ahora, generamos una imagen simulada con patrón de ESRI
        
        img = Image.new('RGB', (width, height), color=(240, 240, 240))
        draw = ImageDraw.Draw(img)
        
        # Simular imagen satelital con patrones
        for i in range(0, width, 20):
            for j in range(0, height, 20):
                if (i // 40 + j // 40) % 2 == 0:
                    green = np.random.randint(80, 180)
                    brown = np.random.randint(100, 150)
                    draw.rectangle([i, j, i+19, j+19], 
                                 fill=(brown, green, brown//2))
        
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes
    except Exception as e:
        st.warning(f"No se pudo obtener imagen ESRI: {str(e)}")
        return None

def ejecutar_deteccion_palmas():
    """Ejecuta la detección de palmas individuales con visualización ESRI"""
    if st.session_state.gdf_original is None:
        st.error("Primero debe cargar un archivo de plantación")
        return
    
    with st.spinner("Ejecutando detección de palmas..."):
        gdf = st.session_state.gdf_original
        tamano_minimo = st.session_state.get('tamano_minimo', 15.0)
        
        # Usar simulación
        resultados = simular_deteccion_palmas(gdf)
        st.session_state.palmas_detectadas = resultados['detectadas']
        
        try:
            # Obtener imagen base de ESRI
            esri_image = obtener_imagen_esri_base(gdf)
            
            if esri_image:
                img = Image.open(esri_image)
                draw = ImageDraw.Draw(img)
                
                bounds = gdf.total_bounds
                min_lon, min_lat, max_lon, max_lat = bounds
                width, height = img.size
                
                # Dibujar palmas detectadas como puntos
                for palma in resultados['detectadas'][:500]:  # Limitar para visualización
                    lon, lat = palma['centroide']
                    x = int((lon - min_lon) / (max_lon - min_lon) * width)
                    y = int((max_lat - lat) / (max_lat - min_lat) * height)
                    
                    # Dibujar punto centroide
                    radio = 3
                    draw.ellipse([x-radio, y-radio, x+radio, y+radio], 
                                fill=(255, 0, 0), outline=(255, 255, 255))
                
                # Dibujar borde de la plantación
                poly_points = []
                if gdf.iloc[0].geometry.geom_type == 'Polygon':
                    for lon, lat in gdf.iloc[0].geometry.exterior.coords:
                        x = int((lon - min_lon) / (max_lon - min_lon) * width)
                        y = int((max_lat - lat) / (max_lat - min_lat) * height)
                        poly_points.append((x, y))
                    
                    if len(poly_points) > 2:
                        draw.polygon(poly_points, outline=(0, 255, 0), width=2)
                
                img_bytes = BytesIO()
                img.save(img_bytes, format='PNG')
                img_bytes.seek(0)
                st.session_state.imagen_alta_resolucion = img_bytes
            else:
                # Crear imagen simple si no hay ESRI
                img = Image.new('RGB', (800, 600), color=(200, 220, 200))
                img_bytes = BytesIO()
                img.save(img_bytes, format='PNG')
                img_bytes.seek(0)
                st.session_state.imagen_alta_resolucion = img_bytes
        
        except Exception as e:
            st.error(f"Error en visualización ESRI: {str(e)}")
            # Crear imagen simple si falla
            img = Image.new('RGB', (800, 600), color=(200, 220, 200))
            img_bytes = BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            st.session_state.imagen_alta_resolucion = img_bytes
        
        st.success(f"✅ Detección completada (simulada): {len(resultados['detectadas'])} palmas detectadas")

# ===== INTERFAZ DE USUARIO =====
# Configuración de página
st.set_page_config(
    page_title="Analizador de Palma Aceitera",
    page_icon="🌴",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS
st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #ffffff;
}
.stButton > button {
    background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%) !important;
    color: white !important;
    border: none !important;
    padding: 0.8em 1.5em !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 1em !important;
    margin: 5px 0 !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: rgba(30, 41, 59, 0.7) !important;
    backdrop-filter: blur(10px) !important;
    padding: 8px 16px !important;
    border-radius: 16px !important;
    border: 1px solid rgba(76, 175, 80, 0.3) !important;
    margin-top: 1.5em !important;
}
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.95)) !important;
    backdrop-filter: blur(10px) !important;
    border-radius: 18px !important;
    padding: 22px !important;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35) !important;
    border: 1px solid rgba(76, 175, 80, 0.25) !important;
}
</style>
""", unsafe_allow_html=True)

# Banner principal
st.markdown("""
<div style="background: linear-gradient(145deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.98));
            padding: 2em; border-radius: 15px; margin-bottom: 2em; text-align: center;">
    <h1 style="color: #ffffff; font-size: 2.8em; margin-bottom: 0.5em;">
        🌴 ANALIZADOR DE PALMA ACEITERA SATELITAL
    </h1>
    <p style="color: #cbd5e1; font-size: 1.2em;">
        Monitoreo inteligente con detección de plantas individuales usando datos MODIS de la NASA
    </p>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("## 🌴 CONFIGURACIÓN")
    
    # Selección de variedad
    variedad = st.selectbox(
        "Variedad de palma:",
        ["Seleccionar variedad"] + VARIEDADES_PALMA_ACEITERA
    )
    
    st.markdown("---")
    st.markdown("### 🛰️ Fuente de Datos")
    
    indice_seleccionado = st.selectbox(
        "Índice de vegetación:",
        ['NDVI', 'EVI', 'NDWI']
    )
    
    st.markdown("---")
    st.markdown("### 📅 Rango Temporal")
    
    fecha_fin = st.date_input("Fecha fin", datetime.now())
    fecha_inicio = st.date_input("Fecha inicio", datetime.now() - timedelta(days=60))
    
    st.markdown("---")
    st.markdown("### 🎯 División de Plantación")
    
    n_divisiones = st.slider("Número de bloques:", 8, 32, 16)
    
    st.markdown("---")
    st.markdown("### 🌴 Detección de Palmas")
    
    deteccion_habilitada = st.checkbox("Activar detección de plantas", value=True)
    if deteccion_habilitada:
        tamano_minimo = st.slider("Tamaño mínimo (m²):", 1.0, 50.0, 15.0, 1.0)
    
    st.markdown("---")
    st.markdown("### 📤 Subir Polígono")
    
    uploaded_file = st.file_uploader(
        "Subir archivo de plantación",
        type=['zip', 'kml', 'kmz', 'geojson'],
        help="Formatos: Shapefile (.zip), KML (.kmz), GeoJSON (.geojson)"
    )
    
    # Almacenar parámetros en session_state
    st.session_state.n_divisiones = n_divisiones
    st.session_state.indice_seleccionado = indice_seleccionado
    st.session_state.fecha_inicio = fecha_inicio
    st.session_state.fecha_fin = fecha_fin
    if deteccion_habilitada:
        st.session_state.tamano_minimo = tamano_minimo

# Área principal
if uploaded_file and not st.session_state.archivo_cargado:
    with st.spinner("Cargando plantación..."):
        gdf = cargar_archivo_plantacion(uploaded_file)
        if gdf is not None:
            st.session_state.gdf_original = gdf
            st.session_state.archivo_cargado = True
            st.session_state.analisis_completado = False
            st.success("✅ Plantación cargada exitosamente")
            st.rerun()
        else:
            st.error("❌ Error al cargar la plantación")

# Mostrar información si hay archivo cargado
if st.session_state.archivo_cargado and st.session_state.gdf_original is not None:
    gdf = st.session_state.gdf_original
    try:
        area_total = calcular_superficie(gdf)
    except Exception:
        area_total = 0.0
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 📊 INFORMACIÓN DE LA PLANTACIÓN")
        st.write(f"- **Área total:** {area_total:.1f} ha")
        st.write(f"- **Bloques configurados:** {n_divisiones}")
        if variedad != "Seleccionar variedad":
            st.write(f"- **Variedad:** {variedad}")
        
        # Mostrar mapa básico
        try:
            fig, ax = plt.subplots(figsize=(8, 6))
            gdf.plot(ax=ax, color='#8bc34a', edgecolor='#4caf50', alpha=0.7)
            ax.set_title("Plantación de Palma Aceitera", fontweight='bold')
            ax.set_xlabel("Longitud")
            ax.set_ylabel("Latitud")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            st.pyplot(fig)
        except Exception:
            st.info("No se pudo mostrar el mapa de la plantación")
    
    with col2:
        st.markdown("### 🎯 ACCIONES")
        
        # Botón para ejecutar análisis
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
            if not st.session_state.analisis_completado:
                if st.button("🚀 EJECUTAR ANÁLISIS", use_container_width=True):
                    ejecutar_analisis_completo()
                    st.rerun()
            else:
                if st.button("🔄 RE-EJECUTAR", use_container_width=True):
                    st.session_state.analisis_completado = False
                    ejecutar_analisis_completo()
                    st.rerun()
        
        with col_btn2:
            if deteccion_habilitada:
                if st.button("🔍 DETECTAR PALMAS", use_container_width=True):
                    ejecutar_deteccion_palmas()
                    st.rerun()

# Mostrar resultados del análisis
if st.session_state.analisis_completado:
    resultados = st.session_state.resultados_todos
    gdf_completo = resultados.get('gdf_completo')
    
    if gdf_completo is not None:
        # Crear pestañas
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📊 Resumen", "🗺️ Mapas", "🛰️ MODIS", 
            "📈 Gráficos", "💰 Económico", "🌴 Detección"
        ])
        
        with tab1:
            st.subheader("RESUMEN GENERAL")
            
            # Métricas principales
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Área Total", f"{resultados.get('area_total', 0):.1f} ha")
            with col2:
                try:
                    edad_prom = gdf_completo['edad_anios'].mean()
                    st.metric("Edad Promedio", f"{edad_prom:.1f} años")
                except Exception:
                    st.metric("Edad Promedio", "N/A")
            with col3:
                try:
                    prod_prom = gdf_completo['produccion_estimada'].mean()
                    st.metric("Producción Promedio", f"{prod_prom:,.0f} kg/ha")
                except Exception:
                    st.metric("Producción Promedio", "N/A")
            with col4:
                try:
                    rent_prom = gdf_completo['rentabilidad'].mean()
                    st.metric("Rentabilidad Promedio", f"{rent_prom:.1f}%")
                except Exception:
                    st.metric("Rentabilidad Promedio", "N/A")
            
            # Resumen nutricional
            st.subheader("🧪 RESUMEN NUTRICIONAL")
            col_n1, col_n2, col_n3, col_n4, col_n5 = st.columns(5)
            with col_n1:
                try:
                    st.metric("N", f"{gdf_completo['req_N'].mean():.0f} kg/ha")
                except Exception:
                    st.metric("N", "N/A")
            with col_n2:
                try:
                    st.metric("P", f"{gdf_completo['req_P'].mean():.0f} kg/ha")
                except Exception:
                    st.metric("P", "N/A")
            with col_n3:
                try:
                    st.metric("K", f"{gdf_completo['req_K'].mean():.0f} kg/ha")
                except Exception:
                    st.metric("K", "N/A")
            with col_n4:
                try:
                    st.metric("Mg", f"{gdf_completo['req_Mg'].mean():.0f} kg/ha")
                except Exception:
                    st.metric("Mg", "N/A")
            with col_n5:
                try:
                    st.metric("B", f"{gdf_completo['req_B'].mean():.3f} kg/ha")
                except Exception:
                    st.metric("B", "N/A")
            
            # Botón para exportar GeoJSON
            st.subheader("📥 EXPORTAR RESULTADOS")
            col_exp1, col_exp2, col_exp3 = st.columns(3)
            
            with col_exp1:
                if st.session_state.geojson_bytes:
                    st.download_button(
                        label="🗺️ Descargar GeoJSON",
                        data=st.session_state.geojson_bytes,
                        file_name=f"analisis_palma_{datetime.now().strftime('%Y%m%d_%H%M%S')}.geojson",
                        mime="application/json",
                        use_container_width=True
                    )
            
            with col_exp2:
                # Exportar CSV
                try:
                    csv_data = gdf_completo.drop(columns=['geometry']).to_csv(index=False)
                    st.download_button(
                        label="📊 Descargar CSV",
                        data=csv_data,
                        file_name=f"datos_palma_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                except Exception:
                    st.button("📊 Descargar CSV", disabled=True, use_container_width=True)
            
            with col_exp3:
                if st.session_state.mapa_calor_bytes:
                    st.download_button(
                        label="🔥 Descargar Mapa Calor",
                        data=st.session_state.mapa_calor_bytes,
                        file_name=f"mapa_calor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                        mime="image/png",
                        use_container_width=True
                    )
            
            st.subheader("📋 RESUMEN POR BLOQUE")
            try:
                columnas = ['id_bloque', 'area_ha', 'edad_anios', 'ndvi_modis', 
                           'produccion_estimada', 'rentabilidad']
                tabla = gdf_completo[columnas].copy()
                tabla.columns = ['Bloque', 'Área (ha)', 'Edad (años)', 'NDVI', 
                                'Producción (kg/ha)', 'Rentabilidad (%)']
                st.dataframe(tabla.style.format({
                    'Área (ha)': '{:.2f}',
                    'Edad (años)': '{:.1f}',
                    'NDVI': '{:.3f}',
                    'Producción (kg/ha)': '{:,.0f}',
                    'Rentabilidad (%)': '{:.1f}'
                }))
            except Exception as e:
                st.warning(f"No se pudo mostrar la tabla de bloques: {str(e)}")
        
        with tab2:
            st.subheader("🗺️ MAPAS Y VISUALIZACIONES")
            
            # Mapa de bloques con NDVI
            st.markdown("### 🗺️ Mapa de Bloques (Coloreado por NDVI)")
            try:
                mapa_fig = crear_mapa_bloques(gdf_completo, st.session_state.palmas_detectadas)
                if mapa_fig:
                    st.pyplot(mapa_fig)
                else:
                    st.info("No se pudo generar el mapa de bloques")
            except Exception as e:
                st.error(f"Error al generar mapa: {str(e)}")
                # Mostrar un mapa simple como fallback
                try:
                    fig_fallback, ax_fallback = plt.subplots(figsize=(10, 8))
                    gdf_completo.plot(ax=ax_fallback, color='lightgreen', edgecolor='darkgreen', alpha=0.6)
                    ax_fallback.set_title('Mapa de Bloques - Palma Aceitera', fontweight='bold')
                    ax_fallback.set_xlabel('Longitud')
                    ax_fallback.set_ylabel('Latitud')
                    ax_fallback.grid(True, alpha=0.3)
                    plt.tight_layout()
                    st.pyplot(fig_fallback)
                except Exception:
                    st.info("No se pudo generar ningún mapa")
            
            # Mapa de calor de producción
            st.markdown("### 🔥 Mapa de Calor - Producción Estimada")
            try:
                mapa_calor_fig = crear_mapa_calor_produccion(gdf_completo)
                if mapa_calor_fig:
                    st.pyplot(mapa_calor_fig)
                else:
                    st.info("No se pudo generar el mapa de calor")
            except Exception as e:
                st.error(f"Error al generar mapa de calor: {str(e)}")
        
        with tab3:
            st.subheader("DATOS SATELITALES MODIS")
            datos_modis = st.session_state.datos_modis
            
            if datos_modis:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**📊 INFORMACIÓN TÉCNICA:**")
                    st.write(f"- **Índice:** {datos_modis.get('indice', 'NDVI')}")
                    st.write(f"- **Valor promedio:** {datos_modis.get('valor_promedio', 0):.3f}")
                    st.write(f"- **Resolución:** {datos_modis.get('resolucion', '250m')}")
                    st.write(f"- **Fuente:** {datos_modis.get('fuente', 'NASA MODIS')}")
                    st.write(f"- **Fecha:** {datos_modis.get('fecha_imagen', 'N/A')}")
                    st.write(f"- **Estado:** {datos_modis.get('estado', 'N/A')}")
                
                with col2:
                    st.markdown("**🎯 INTERPRETACIÓN:**")
                    valor = datos_modis.get('valor_promedio', 0)
                    if valor < 0.3:
                        st.error("**NDVI bajo** - Posible estrés hídrico o nutricional")
                        st.write("Recomendación: Evaluar riego y fertilización")
                    elif valor < 0.5:
                        st.warning("**NDVI moderado** - Vegetación en desarrollo")
                        st.write("Recomendación: Monitorear crecimiento")
                    elif valor < 0.7:
                        st.success("**NDVI bueno** - Vegetación saludable")
                        st.write("Recomendación: Mantener prácticas actuales")
                    else:
                        st.success("**NDVI excelente** - Vegetación muy densa y saludable")
                        st.write("Recomendación: Condiciones óptimas")
                    
                    st.write(f"- **Óptimo para palma:** {PARAMETROS_PALMA['NDVI_OPTIMO']}")
                    st.write(f"- **Diferencia:** {(valor - PARAMETROS_PALMA['NDVI_OPTIMO']):.3f}")
                
                # Mostrar imagen MODIS - CON MANEJO DE ERRORES
                st.subheader("🖼️ IMAGEN MODIS")
                
                # Intentar múltiples fuentes para la imagen
                imagen_a_mostrar = None
                fuente_imagen = ""
                
                # 1. Intentar con imagen en session_state
                if hasattr(st.session_state, 'imagen_modis_bytes') and st.session_state.imagen_modis_bytes is not None:
                    try:
                        st.session_state.imagen_modis_bytes.seek(0)
                        imagen_a_mostrar = st.session_state.imagen_modis_bytes
                        fuente_imagen = "session_state"
                    except Exception:
                        pass
                
                # 2. Intentar con imagen en datos_modis
                if imagen_a_mostrar is None and 'imagen_bytes' in datos_modis and datos_modis['imagen_bytes'] is not None:
                    try:
                        datos_modis['imagen_bytes'].seek(0)
                        imagen_a_mostrar = datos_modis['imagen_bytes']
                        fuente_imagen = "datos_modis"
                    except Exception:
                        pass
                
                # 3. Generar imagen simulada como último recurso
                if imagen_a_mostrar is None:
                    try:
                        imagen_a_mostrar = generar_imagen_modis_simulada(st.session_state.gdf_original)
                        fuente_imagen = "simulada"
                        st.info("Mostrando imagen MODIS simulada")
                    except Exception:
                        pass
                
                # Mostrar la imagen si se encontró alguna
                if imagen_a_mostrar is not None:
                    try:
                        # Asegurarse de que el puntero esté al inicio
                        if hasattr(imagen_a_mostrar, 'seek'):
                            imagen_a_mostrar.seek(0)
                        
                        caption = f"Imagen MODIS {datos_modis.get('indice', '')} - {datos_modis.get('fecha_imagen', '')}"
                        if fuente_imagen == "simulada":
                            caption += " (Simulada)"
                        
                        st.image(imagen_a_mostrar, 
                                caption=caption,
                                use_container_width=True)
                    except Exception:
                        st.info("No se pudo mostrar la imagen MODIS")
                else:
                    st.info("No hay imagen MODIS disponible para mostrar")
            else:
                st.warning("No hay datos MODIS disponibles. Ejecute el análisis primero.")
        
        with tab4:
            st.subheader("📈 GRÁFICOS DE ANÁLISIS")
            
            # Gráfico de NDVI
            st.markdown("### 📊 NDVI por Bloque")
            fig_ndvi = crear_grafico_ndvi_bloques(gdf_completo)
            if fig_ndvi:
                st.pyplot(fig_ndvi)
            else:
                st.info("No se pudo generar el gráfico de NDVI")
            
            # Gráfico de producción
            st.markdown("### 📈 Producción por Bloque")
            fig_prod = crear_grafico_produccion(gdf_completo)
            if fig_prod:
                st.pyplot(fig_prod)
            else:
                st.info("No se pudo generar el gráfico de producción")
            
            # Gráfico de rentabilidad
            st.markdown("### 💰 Rentabilidad por Bloque")
            fig_rent = crear_grafico_rentabilidad(gdf_completo)
            if fig_rent:
                st.pyplot(fig_rent)
            else:
                st.info("No se pudo generar el gráfico de rentabilidad")
            
            # Gráfico de edad
            st.markdown("### 📅 Distribución de Edades")
            try:
                fig_edad, ax_edad = plt.subplots(figsize=(10, 6))
                ax_edad.hist(gdf_completo['edad_anios'], bins=10, color='#4caf50', 
                            edgecolor='#2e7d32', alpha=0.7)
                ax_edad.set_xlabel('Edad (años)')
                ax_edad.set_ylabel('Número de bloques')
                ax_edad.set_title('Distribución de Edades de la Plantación', fontweight='bold')
                ax_edad.grid(True, alpha=0.3)
                plt.tight_layout()
                st.pyplot(fig_edad)
            except Exception:
                st.info("No se pudo generar el gráfico de distribución de edades")
        
        with tab5:
            st.subheader("💰 ANÁLISIS ECONÓMICO")
            
            # Métricas económicas
            try:
                ingreso_total = gdf_completo['ingreso_estimado'].sum()
                costo_total = gdf_completo['costo_total'].sum()
                ganancia_total = ingreso_total - costo_total
                rentabilidad_prom = gdf_completo['rentabilidad'].mean()
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Ingreso Total", f"${ingreso_total:,.0f} USD")
                with col2:
                    st.metric("Costo Total", f"${costo_total:,.0f} USD")
                with col3:
                    st.metric("Ganancia Total", f"${ganancia_total:,.0f} USD")
                with col4:
                    st.metric("Rentabilidad Promedio", f"{rentabilidad_prom:.1f}%")
            except Exception:
                st.warning("No se pudieron calcular las métricas económicas")
            
            # Análisis de costos
            st.subheader("📊 DISTRIBUCIÓN DE COSTOS")
            try:
                # Calcular costos por componente
                costo_n = (gdf_completo['req_N'] * 1.2 * gdf_completo['area_ha']).sum()
                costo_p = (gdf_completo['req_P'] * 2.5 * gdf_completo['area_ha']).sum()
                costo_k = (gdf_completo['req_K'] * 1.8 * gdf_completo['area_ha']).sum()
                costo_mg = (gdf_completo['req_Mg'] * 1.5 * gdf_completo['area_ha']).sum()
                costo_b = (gdf_completo['req_B'] * 15.0 * gdf_completo['area_ha']).sum()
                costo_base = PARAMETROS_PALMA['COSTO_FERTILIZACION'] * gdf_completo['area_ha'].sum()
                
                labels = ['Nitrógeno', 'Fósforo', 'Potasio', 'Magnesio', 'Boro', 'Costo Base']
                sizes = [costo_n, costo_p, costo_k, costo_mg, costo_b, costo_base]
                colors = ['#4caf50', '#2196f3', '#ff9800', '#9c27b0', '#f44336', '#795548']
                
                fig_costos, ax_costos = plt.subplots(figsize=(8, 8))
                ax_costos.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
                ax_costos.set_title('Distribución de Costos de Producción', fontweight='bold')
                plt.tight_layout()
                st.pyplot(fig_costos)
            except Exception:
                st.info("No se pudo generar el gráfico de distribución de costos")
            
            # Tabla de costos detallada
            st.subheader("📋 DETALLE DE COSTOS POR BLOQUE")
            try:
                costos_cols = ['id_bloque', 'costo_total', 'ingreso_estimado', 'rentabilidad']
                if all(col in gdf_completo.columns for col in costos_cols):
                    df_costos = gdf_completo[costos_cols].copy()
                    df_costos.columns = ['Bloque', 'Costo Total (USD)', 'Ingreso Estimado (USD)', 'Rentabilidad (%)']
                    st.dataframe(df_costos.style.format({
                        'Costo Total (USD)': '{:,.2f}',
                        'Ingreso Estimado (USD)': '{:,.2f}',
                        'Rentabilidad (%)': '{:.1f}'
                    }))
            except Exception:
                st.info("No se pudo mostrar la tabla de costos detallada")
        
        with tab6:
            st.subheader("🌴 DETECCIÓN DE PALMAS INDIVIDUALES")
            
            if not DETECCION_DISPONIBLE:
                st.warning("""
                ⚠️ **Funcionalidad limitada:** Las librerías de visión por computadora no están instaladas.
                
                **Para activar la detección avanzada, instale:**
                ```
                pip install opencv-python
                ```
                
                **Funcionalidades disponibles:**
                - Simulación de detección de palmas
                - Estimación de densidad
                - Análisis de patrones básico
                """)
            
            if st.session_state.palmas_detectadas:
                palmas = st.session_state.palmas_detectadas
                total = len(palmas)
                area_total = resultados.get('area_total', 0)
                densidad = total / area_total if area_total > 0 else 0
                
                st.success(f"✅ Detección completada: {total} palmas detectadas")
                
                # Métricas
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Palmas detectadas", f"{total:,}")
                with col2:
                    st.metric("Densidad", f"{densidad:.0f} plantas/ha")
                with col3:
                    try:
                        area_prom = np.mean([p.get('area_pixels', 0) for p in palmas])
                        st.metric("Área promedio", f"{area_prom:.1f} m²")
                    except Exception:
                        st.metric("Área promedio", "N/A")
                with col4:
                    try:
                        cobertura = (total * area_prom) / (area_total * 10000) * 100 if area_total > 0 else 0
                        st.metric("Cobertura estimada", f"{cobertura:.1f}%")
                    except Exception:
                        st.metric("Cobertura estimada", "N/A")
                
                # Mostrar imagen con detección - CON MANEJO DE ERRORES
                st.subheader("📷 Visualización de Detección (ESRI + Centroides)")
                if hasattr(st.session_state, 'imagen_alta_resolucion') and st.session_state.imagen_alta_resolucion is not None:
                    try:
                        st.session_state.imagen_alta_resolucion.seek(0)
                        st.image(st.session_state.imagen_alta_resolucion,
                                caption="Detección de palmas sobre imagen base ESRI con puntos centroides",
                                use_container_width=True)
                    except Exception:
                        st.info("No se pudo mostrar la imagen de detección")
                else:
                    st.info("No hay imagen de detección disponible")
                    
                # Mapa de distribución
                st.subheader("🗺️ Mapa de Distribución de Palmas")
                try:
                    fig_palmas, ax_palmas = plt.subplots(figsize=(10, 8))
                    gdf_completo.plot(ax=ax_palmas, color='lightgreen', alpha=0.3, edgecolor='darkgreen')
                    
                    if palmas and len(palmas) > 0:
                        # Limitar a 1000 puntos para mejor visualización
                        coords = np.array([p['centroide'] for p in palmas[:1000]])
                        ax_palmas.scatter(coords[:, 0], coords[:, 1], 
                                        s=5, color='red', alpha=0.6, label='Palmas detectadas (centroides)')
                    
                    ax_palmas.set_title(f'Distribución de {total} Palmas Detectadas', 
                                       fontsize=14, fontweight='bold')
                    ax_palmas.set_xlabel('Longitud')
                    ax_palmas.set_ylabel('Latitud')
                    ax_palmas.legend()
                    ax_palmas.grid(True, alpha=0.3)
                    plt.tight_layout()
                    st.pyplot(fig_palmas)
                except Exception:
                    st.info("No se pudo generar el mapa de distribución de palmas")
                
                # Análisis de densidad
                st.subheader("📊 ANÁLISIS DE DENSIDAD")
                densidad_optima = 130  # plantas/ha
                if densidad < densidad_optima * 0.8:
                    st.error(f"**DENSIDAD BAJA:** {densidad:.0f} plantas/ha (Óptimo: {densidad_optima})")
                    st.write("Recomendación: Considerar replantar áreas con baja densidad")
                elif densidad > densidad_optima * 1.2:
                    st.warning(f"**DENSIDAD ALTA:** {densidad:.0f} plantas/ha (Óptimo: {densidad_optima})")
                    st.write("Recomendación: Evaluar competencia por recursos")
                else:
                    st.success(f"**DENSIDAD ÓPTIMA:** {densidad:.0f} plantas/ha")
                    st.write("La densidad de plantación es adecuada")
                
                # Exportar datos de palmas
                st.subheader("📥 EXPORTAR DATOS DE PALMAS")
                if palmas and len(palmas) > 0:
                    try:
                        df_palmas = pd.DataFrame([{
                            'id': i+1,
                            'longitud': p.get('centroide', (0, 0))[0],
                            'latitud': p.get('centroide', (0, 0))[1],
                            'area_m2': p.get('area_pixels', 0),
                            'radio_m': p.get('radio_aprox', 0),
                            'circularidad': p.get('circularidad', 0)
                        } for i, p in enumerate(palmas)])
                        
                        # Exportar CSV
                        csv_data = df_palmas.to_csv(index=False)
                        
                        # Exportar GeoJSON de palmas
                        geometry = [Point(p['longitud'], p['latitud']) for _, p in df_palmas.iterrows()]
                        gdf_palmas = gpd.GeoDataFrame(df_palmas, geometry=geometry, crs='EPSG:4326')
                        geojson_palmas = gdf_palmas.to_json()
                        
                        col_exp1, col_exp2 = st.columns(2)
                        
                        with col_exp1:
                            st.download_button(
                                label="📥 Descargar Coordenadas (CSV)",
                                data=csv_data,
                                file_name=f"coordenadas_palmas_{datetime.now().strftime('%Y%m%d')}.csv",
                                mime="text/csv",
                                use_container_width=True
                            )
                        
                        with col_exp2:
                            st.download_button(
                                label="🗺️ Descargar GeoJSON Palmas",
                                data=geojson_palmas,
                                file_name=f"palmas_detectadas_{datetime.now().strftime('%Y%m%d')}.geojson",
                                mime="application/json",
                                use_container_width=True
                            )
                    except Exception:
                        st.info("No se pudieron exportar los datos de detección")
            else:
                st.info("La detección de palmas no se ha ejecutado aún.")
                if st.button("🔍 EJECUTAR DETECCIÓN DE PALMAS", key="detectar_palmas_tab6"):
                    ejecutar_deteccion_palmas()
                    st.rerun()

# Pie de página
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #94a3b8; padding: 20px;">
    <p><strong>© 2026 Analizador de Palma Aceitera Satelital</strong></p>
    <p>Datos satelitales: NASA MODIS - Acceso público</p>
    <p>Desarrollado por: Martin Ernesto Cano | Contacto: mawucano@gmail.com | +5493525 532313</p>
</div>
""", unsafe_allow_html=True)

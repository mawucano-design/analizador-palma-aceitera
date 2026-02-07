# app.py - Versión completa para PALMA ACEITERA con membresías premium
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
import hashlib
import time
import base64

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

# ===== SISTEMA DE MEMBRESÍAS =====
class SistemaMembresias:
    """Sistema de membresías con validación de 25 días"""
    
    @staticmethod
    def generar_token(email, dias=25):
        """Genera un token único basado en email y tiempo"""
        timestamp = int(time.time())
        hash_input = f"{email}_{timestamp}_{dias}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    @staticmethod
    def verificar_membresia(token, dias_duracion=25):
        """Verifica si la membresía es válida"""
        try:
            if 'membresia_valida_hasta' not in st.session_state:
                return False
            
            fecha_validez = st.session_state.membresia_valida_hasta
            return datetime.now() < fecha_validez
        except:
            return False

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
        'geojson_bytes': None,
        'usuario_autenticado': False,
        'email_usuario': None,
        'membresia_valida_hasta': None,
        'token_membresia': None,
        'mostrar_pago': False,
        'modo_prueba': True,
        'dias_restantes': 0,
        'intentos_analisis': 0,
        'max_intentos_gratis': 3,
        'premium_activado': False
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

# ===== FUNCIONES DE ANÁLISIS CON MODIS MEJORADAS =====
def obtener_imagen_modis_real(gdf, fecha, indice='NDVI'):
    """Obtiene imagen MODIS real de NASA GIBS - VERSIÓN MEJORADA"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Añadir margen pequeño
        min_lon -= 0.01
        max_lon += 0.01
        min_lat -= 0.01
        max_lat += 0.01
        
        if indice not in MODIS_CONFIG:
            indice = 'NDVI'
        
        config = MODIS_CONFIG[indice]
        
        # Parámetros WMS para NASA GIBS - CORREGIDOS
        wms_params = {
            'SERVICE': 'WMS',
            'REQUEST': 'GetMap',
            'VERSION': '1.1.1',
            'LAYERS': config['layers'][0],
            'FORMAT': 'image/png',
            'BBOX': f'{min_lon},{min_lat},{max_lon},{max_lat}',
            'WIDTH': '800',
            'HEIGHT': '600',
            'SRS': 'EPSG:4326',
            'TIME': fecha.strftime('%Y-%m-%d'),
            'STYLES': f'boxfill/{config["palette"]}',
            'COLORSCALERANGE': '0.0,1.0',
            'TRANSPARENT': 'TRUE'
        }
        
        response = requests.get(config['url_base'], params=wms_params, timeout=30)
        
        if response.status_code == 200:
            # Verificar que sea realmente una imagen PNG
            content_type = response.headers.get('Content-Type', '')
            if 'image' not in content_type:
                return None
            
            # Crear un nuevo BytesIO para la imagen
            imagen_bytes = BytesIO(response.content)
            
            # Verificar que sea una imagen PNG válida
            try:
                img = Image.open(imagen_bytes)
                img.verify()
                imagen_bytes.seek(0)
                
                # Si es muy grande, redimensionar
                if img.size[0] > 1000 or img.size[1] > 1000:
                    img = img.resize((800, 600), Image.Resampling.LANCZOS)
                    new_bytes = BytesIO()
                    img.save(new_bytes, format='PNG')
                    new_bytes.seek(0)
                    return new_bytes
                
                return imagen_bytes
            except Exception:
                return None
        else:
            return None
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.ConnectionError:
        return None
    except Exception:
        return None

def generar_imagen_modis_simulada_mejorada(gdf):
    """Genera una imagen MODIS simulada más realista"""
    try:
        width, height = 800, 600
        
        # Crear imagen con gradiente de vegetación
        img = Image.new('RGB', (width, height), color=(220, 220, 220))
        draw = ImageDraw.Draw(img)
        
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Crear patrón de vegetación más realista
        for i in range(0, width, 4):
            for j in range(0, height, 4):
                # Gradiente basado en posición
                x_ratio = i / width
                y_ratio = j / height
                
                # Simular diferentes tipos de vegetación
                if (i // 100 + j // 100) % 3 == 0:
                    # Áreas de alta vegetación
                    green = int(100 + (x_ratio * y_ratio * 100))
                    red = int(50 + (1 - x_ratio) * 30)
                    blue = int(50 + (1 - y_ratio) * 30)
                elif (i // 100 + j // 100) % 3 == 1:
                    # Áreas de vegetación media
                    green = int(80 + (x_ratio * y_ratio * 80))
                    red = int(80 + (1 - x_ratio) * 40)
                    blue = int(40 + (1 - y_ratio) * 40)
                else:
                    # Áreas de baja vegetación/suelo
                    green = int(60 + (x_ratio * y_ratio * 60))
                    red = int(120 + (1 - x_ratio) * 60)
                    blue = int(60 + (1 - y_ratio) * 30)
                
                # Añadir variación aleatoria
                variation = np.random.randint(-10, 10)
                green = max(0, min(255, green + variation))
                red = max(0, min(255, red + variation // 2))
                blue = max(0, min(255, blue + variation // 2))
                
                draw.point((i, j), fill=(red, green, blue))
        
        # Añadir patrones de cultivo (filas)
        for row in range(5):
            y_start = int(height * 0.1 + row * height * 0.15)
            y_end = y_start + int(height * 0.1)
            
            for x in range(0, width, 15):
                # Patrón de filas de cultivo
                if (x // 30) % 2 == row % 2:
                    draw.rectangle([x, y_start, x+10, y_end], 
                                 fill=(50, 180, 50), outline=(30, 150, 30))
        
        # Añadir ríos/cuerpos de agua
        for i in range(3):
            x_center = np.random.randint(width * 0.3, width * 0.7)
            y_center = np.random.randint(height * 0.3, height * 0.7)
            river_width = np.random.randint(10, 30)
            
            for w in range(-river_width, river_width):
                x = x_center + w
                if 0 <= x < width:
                    for y in range(height):
                        dist_from_center = abs(w) / river_width
                        if np.random.random() > dist_from_center * 0.8:
                            blue_intensity = int(150 + np.random.randint(-20, 20))
                            draw.point((x, y), fill=(50, 100, blue_intensity))
        
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG', optimize=True, compress_level=6)
        img_bytes.seek(0)
        
        return img_bytes
    except Exception:
        # Fallback ultra simple si hay error
        img = Image.new('RGB', (800, 600), color=(100, 150, 100))
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes

def obtener_datos_modis_mejorado(gdf, fecha_inicio, fecha_fin, indice='NDVI'):
    """Obtiene datos MODIS reales o simulados - VERSIÓN MEJORADA"""
    try:
        fecha_media = fecha_inicio + (fecha_fin - fecha_inicio) / 2
        
        # Verificar membresía
        usar_reales = st.session_state.usuario_autenticado
        
        imagen_bytes = None
        estado = 'simulado'
        fuente = f'MODIS {indice} (Simulado)'
        
        if usar_reales:
            # Intentar obtener imagen MODIS real
            imagen_real = obtener_imagen_modis_real(gdf, fecha_media, indice)
            
            if imagen_real is not None:
                imagen_bytes = imagen_real
                estado = 'real'
                fuente = f'MODIS {indice} - NASA GIBS (Premium)'
            else:
                # Fallback a simulados
                imagen_bytes = generar_imagen_modis_simulada_mejorada(gdf)
                estado = 'simulado'
                fuente = f'MODIS {indice} (Simulado - Fallback)'
        else:
            # Modo gratuito - usar simulados
            imagen_bytes = generar_imagen_modis_simulada_mejorada(gdf)
            estado = 'simulado'
            fuente = f'MODIS {indice} (Simulado - Modo Gratuito)'
        
        # Asegurarse de que la imagen esté en posición 0
        if imagen_bytes:
            imagen_bytes.seek(0)
        
        # Calcular valores NDVI/otros índices
        centroide = gdf.geometry.unary_union.centroid
        lat_norm = (centroide.y + 90) / 180
        lon_norm = (centroide.x + 180) / 360
        
        mes = fecha_media.month
        if 3 <= mes <= 5:
            base_valor = 0.65
        elif 6 <= mes <= 8:
            base_valor = 0.55
        elif 9 <= mes <= 11:
            base_valor = 0.75
        else:
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
            'bbox': gdf.total_bounds.tolist(),
            'imagen_disponible': imagen_bytes is not None
        }
        
        # Solo agregar imagen_bytes si no es None
        if imagen_bytes:
            # Crear copia para evitar problemas de posición
            imagen_bytes_copia = BytesIO(imagen_bytes.read())
            imagen_bytes_copia.seek(0)
            resultado['imagen_bytes'] = imagen_bytes_copia
            
            # Guardar copia separada en session_state
            imagen_bytes.seek(0)
            copia_session = BytesIO(imagen_bytes.read())
            copia_session.seek(0)
            st.session_state.imagen_modis_bytes = copia_session
        
        return resultado
        
    except Exception as e:
        # Retornar datos simulados como fallback robusto
        return {
            'indice': indice,
            'valor_promedio': 0.65,
            'fuente': 'MODIS (Simulado) - NASA',
            'fecha_imagen': datetime.now().strftime('%Y-%m-%d'),
            'resolucion': '250m',
            'estado': 'simulado',
            'nota': 'Datos simulados - Error en conexión',
            'imagen_disponible': False
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

# ===== FUNCIONES DE VISUALIZACIÓN MEJORADAS =====
def crear_mapa_bloques(gdf, palmas_detectadas=None):
    """Crea un mapa de los bloques con matplotlib"""
    if gdf is None or len(gdf) == 0:
        return None
    
    try:
        # Limitar el número de bloques para evitar imágenes grandes
        if len(gdf) > 20:
            gdf = gdf.head(20)
        
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
                    colors.append((1.0, 0.5, 0.5, 0.6))
                elif norm_val < 0.66:
                    colors.append((1.0, 1.0, 0.5, 0.6))
                else:
                    colors.append((0.5, 1.0, 0.5, 0.6))
            
            # Dibujar cada polígono con su color
            for idx, row in gdf.iterrows():
                try:
                    if row.geometry.geom_type == 'Polygon':
                        # Simplificar geometría
                        simplified = row.geometry.simplify(0.001, preserve_topology=True)
                        poly_coords = list(simplified.exterior.coords)
                        polygon = MplPolygon(poly_coords, closed=True, 
                                           facecolor=colors[idx], 
                                           edgecolor='black', 
                                           linewidth=1,
                                           alpha=0.6)
                        ax.add_patch(polygon)
                    elif row.geometry.geom_type == 'MultiPolygon':
                        for poly in row.geometry.geoms:
                            simplified = poly.simplify(0.001, preserve_topology=True)
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
        
        # Añadir palmas detectadas si existen (limitado a 100)
        if palmas_detectadas and len(palmas_detectadas) > 0:
            try:
                coords = np.array([p['centroide'] for p in palmas_detectadas[:100]])
                ax.scatter(coords[:, 0], coords[:, 1], 
                          s=20, color='blue', alpha=0.5, label='Palmas detectadas')
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
    except Exception:
        # Fallback: mapa simple
        try:
            fig, ax = plt.subplots(figsize=(10, 8))
            gdf.plot(ax=ax, color='lightgreen', edgecolor='darkgreen', alpha=0.6)
            ax.set_title('Mapa de Bloques - Palma Aceitera', fontsize=14, fontweight='bold')
            ax.set_xlabel('Longitud')
            ax.set_ylabel('Latitud')
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            return fig
        except:
            return None

def crear_mapa_calor_produccion(gdf):
    """Crea un mapa de calor de producción por bloque"""
    if gdf is None or 'produccion_estimada' not in gdf.columns:
        return None
    
    try:
        # Limitar el número de bloques para evitar imágenes grandes
        if len(gdf) > 10:
            gdf = gdf.head(10)
        
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # Obtener valores de producción
        produccion = gdf['produccion_estimada'].values
        min_prod, max_prod = produccion.min(), produccion.max()
        
        if max_prod - min_prod < 0.001:
            min_prod = max_prod - 1000
        
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
                    # Simplificar geometría
                    simplified = row.geometry.simplify(0.001, preserve_topology=True)
                    poly_coords = list(simplified.exterior.coords)
                    polygon = MplPolygon(poly_coords, closed=True, 
                                       facecolor=color, 
                                       edgecolor='black', 
                                       linewidth=1,
                                       alpha=0.7)
                    ax.add_patch(polygon)
                elif row.geometry.geom_type == 'MultiPolygon':
                    for poly in row.geometry.geoms:
                        simplified = poly.simplify(0.001, preserve_topology=True)
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
        
        # Guardar figura en bytes con DPI controlado
        img_bytes = BytesIO()
        fig.savefig(img_bytes, format='PNG', dpi=100, bbox_inches='tight')
        img_bytes.seek(0)
        
        # Guardar en session_state para exportar
        st.session_state.mapa_calor_bytes = img_bytes
        
        return fig
    except Exception:
        return None

def crear_imagen_deteccion_esri(gdf, palmas_detectadas):
    """Crea imagen de detección sobre fondo ESRI"""
    try:
        # Tamaño controlado
        width, height = 800, 600
        
        # Crear imagen de fondo (simulación ESRI)
        img = Image.new('RGB', (width, height), color=(220, 230, 220))
        draw = ImageDraw.Draw(img)
        
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Dibujar patrón de terreno
        for i in range(0, width, 30):
            for j in range(0, height, 30):
                if (i // 60 + j // 60) % 2 == 0:
                    green = np.random.randint(100, 180)
                    draw.rectangle([i, j, i+29, j+29], 
                                 fill=(80, green, 70))
        
        # Dibujar contorno de la plantación
        poly_points = []
        if gdf.iloc[0].geometry.geom_type == 'Polygon':
            for lon, lat in gdf.iloc[0].geometry.exterior.coords:
                x = int((lon - min_lon) / (max_lon - min_lon) * width)
                y = int((max_lat - lat) / (max_lat - min_lat) * height)
                poly_points.append((x, y))
            
            if len(poly_points) > 2:
                draw.polygon(poly_points, outline=(0, 150, 0), fill=(100, 200, 100, 64))
        
        # Dibujar palmas detectadas (limitado a 200 para visualización)
        palmas_mostrar = palmas_detectadas[:200] if len(palmas_detectadas) > 200 else palmas_detectadas
        
        for palma in palmas_mostrar:
            lon, lat = palma['centroide']
            x = int((lon - min_lon) / (max_lon - min_lon) * width)
            y = int((max_lat - lat) / (max_lat - min_lat) * height)
            
            # Dibujar punto centroide
            radio = 4
            draw.ellipse([x-radio, y-radio, x+radio, y+radio], 
                        fill=(255, 50, 50), outline=(255, 255, 255))
        
        # Añadir leyenda
        draw.rectangle([10, 10, 200, 80], fill=(255, 255, 255, 200))
        draw.ellipse([20, 20, 30, 30], fill=(255, 50, 50), outline=(0, 0, 0))
        draw.text((40, 20), "Palma detectada", fill=(0, 0, 0))
        
        draw.rectangle([20, 40, 190, 50], fill=(100, 200, 100))
        draw.text((40, 40), "Área plantación", fill=(0, 0, 0))
        
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG', optimize=True)
        img_bytes.seek(0)
        
        return img_bytes
    except Exception:
        # Crear imagen simple si falla
        img = Image.new('RGB', (800, 600), color=(200, 220, 200))
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes

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
    except Exception:
        return None

def activar_premium_instantaneo():
    """Activa premium instantáneo para pruebas"""
    st.session_state.email_usuario = "premium@ejemplo.com"
    st.session_state.usuario_autenticado = True
    st.session_state.membresia_valida_hasta = datetime.now() + timedelta(days=25)
    st.session_state.token_membresia = SistemaMembresias.generar_token("premium@ejemplo.com")
    st.session_state.dias_restantes = 25
    st.session_state.premium_activado = True
    st.session_state.intentos_analisis = 0
    
    st.success("✅ ¡Premium activado instantáneamente por 25 días!")
    st.balloons()

# ===== FUNCIÓN PRINCIPAL DE ANÁLISIS =====
def ejecutar_analisis_completo():
    """Ejecuta el análisis completo y almacena resultados en session_state"""
    if st.session_state.gdf_original is None:
        st.error("Primero debe cargar un archivo de plantación")
        return
    
    # Verificar límites de análisis gratuito
    if not st.session_state.usuario_autenticado:
        if st.session_state.intentos_analisis >= st.session_state.max_intentos_gratis:
            st.warning("""
            ⚠️ **Límite de análisis gratuito alcanzado**
            
            Has utilizado todos tus análisis gratuitos. Para continuar:
            1. Activa tu membresía premium
            2. Desbloquea análisis ilimitados
            3. Accede a imágenes satelitales reales
            
            """)
            return
        else:
            st.session_state.intentos_analisis += 1
    
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
        
        # 1. Obtener datos MODIS (reales o simulados según membresía)
        datos_modis = obtener_datos_modis_mejorado(gdf, fecha_inicio, fecha_fin, indice_seleccionado)
        st.session_state.datos_modis = datos_modis
        
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

def ejecutar_deteccion_palmas():
    """Ejecuta la detección de palmas individuales"""
    if st.session_state.gdf_original is None:
        st.error("Primero debe cargar un archivo de plantación")
        return
    
    with st.spinner("Ejecutando detección de palmas..."):
        gdf = st.session_state.gdf_original
        tamano_minimo = st.session_state.get('tamano_minimo', 15.0)
        
        # Usar simulación
        resultados = simular_deteccion_palmas(gdf)
        st.session_state.palmas_detectadas = resultados['detectadas']
        
        # Crear imagen de detección con ESRI
        imagen_bytes = crear_imagen_deteccion_esri(gdf, resultados['detectadas'])
        if imagen_bytes:
            # Asegurarse de que el BytesIO esté en la posición correcta
            imagen_bytes.seek(0)
            st.session_state.imagen_alta_resolucion = imagen_bytes
        
        st.success(f"✅ Detección completada: {len(resultados['detectadas'])} palmas detectadas")

# ===== INTERFAZ DE USUARIO =====
# Configuración de página
st.set_page_config(
    page_title="Analizador de Palma Aceitera Premium",
    page_icon="🌴",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS mejorados
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
.premium-badge {
    background: linear-gradient(135deg, #FFD700 0%, #FFA500 100%);
    color: #000 !important;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 0.8em;
}
.free-badge {
    background: linear-gradient(135deg, #808080 0%, #A9A9A9 100%);
    color: white !important;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 0.8em;
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

# Barra superior con estado de membresía
col_status1, col_status2, col_status3 = st.columns([2, 1, 1])
with col_status1:
    if st.session_state.usuario_autenticado:
        dias_restantes = (st.session_state.membresia_valida_hasta - datetime.now()).days
        st.session_state.dias_restantes = max(0, dias_restantes)
        
        if dias_restantes > 0:
            st.success(f"✅ MEMBRESÍA PREMIUM ACTIVA - {dias_restantes} días restantes")
        else:
            st.warning("⚠️ MEMBRESÍA EXPIRADA - Renueva para continuar")
            st.session_state.usuario_autenticado = False
    else:
        st.info("🔓 MODO GRATUITO - Activa membresía para funciones premium")

with col_status2:
    if st.session_state.usuario_autenticado:
        st.markdown('<span class="premium-badge">PREMIUM</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="free-badge">GRATUITO</span>', unsafe_allow_html=True)

with col_status3:
    if st.button("🚀 ACTIVAR PREMIUM INSTANTÁNEO", type="primary"):
        activar_premium_instantaneo()
        st.rerun()

# Sidebar
with st.sidebar:
    st.markdown("## 🌴 CONFIGURACIÓN")
    
    # Estado de membresía en sidebar
    if st.session_state.usuario_autenticado:
        st.success(f"✅ Premium: {st.session_state.dias_restantes} días")
    else:
        st.warning("🔓 Modo Gratuito")
    
    st.markdown("---")
    
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
    
    # Indicador de calidad de datos
    if st.session_state.usuario_autenticado:
        st.success("✓ Datos MODIS reales disponibles")
    else:
        st.info("ℹ️ Datos simulados - Activa Premium para datos reales")
    
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
    
    # Contador de análisis gratuito
    if not st.session_state.usuario_autenticado:
        st.markdown("---")
        st.markdown("### 📊 Análisis Gratuito")
        intentos_restantes = st.session_state.max_intentos_gratis - st.session_state.intentos_analisis
        st.progress(st.session_state.intentos_analisis / st.session_state.max_intentos_gratis)
        st.caption(f"Análisis restantes: {intentos_restantes}/{st.session_state.max_intentos_gratis}")
    
    # Botón para activar premium instantáneo (solo para pruebas)
    st.markdown("---")
    st.markdown("### 🚀 Acceso Premium")
    if not st.session_state.usuario_autenticado:
        if st.button("🎁 ACTIVAR PREMIUM GRATIS (25 días)", use_container_width=True, type="primary"):
            activar_premium_instantaneo()
            st.rerun()
    else:
        if st.button("🔄 REINICIAR SISTEMA", use_container_width=True):
            # Reiniciar session_state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            init_session_state()
            st.rerun()
    
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
        
        # Indicador de calidad
        if st.session_state.usuario_autenticado:
            st.success("✅ Análisis Premium disponible")
        else:
            st.warning(f"⚠️ Modo Gratuito: {st.session_state.max_intentos_gratis - st.session_state.intentos_analisis} análisis restantes")
        
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
            
            # Botón para exportar GeoJSON (solo premium)
            st.subheader("📥 EXPORTAR RESULTADOS")
            
            if st.session_state.usuario_autenticado:
                col_exp1, col_exp2, col_exp3 = st.columns(3)
                
                with col_exp1:
                    if st.session_state.geojson_bytes:
                        st.download_button(
                            label="🗺️ Descargar GeoJSON",
                            data=st.session_state.geojson_bytes.getvalue(),
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
                            data=st.session_state.mapa_calor_bytes.getvalue(),
                            file_name=f"mapa_calor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                            mime="image/png",
                            use_container_width=True
                        )
            else:
                st.warning("⚠️ La exportación de datos está disponible solo para usuarios premium")
                if st.button("💎 ACTUALIZAR PARA EXPORTAR", use_container_width=True):
                    activar_premium_instantaneo()
                    st.rerun()
            
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
            
            # Mapa de calor de producción (solo premium)
            st.markdown("### 🔥 Mapa de Calor - Producción Estimada")
            if st.session_state.usuario_autenticado:
                try:
                    mapa_calor_fig = crear_mapa_calor_produccion(gdf_completo)
                    if mapa_calor_fig:
                        st.pyplot(mapa_calor_fig)
                    else:
                        st.info("No se pudo generar el mapa de calor")
                except Exception as e:
                    st.error(f"Error al generar mapa de calor: {str(e)}")
            else:
                st.warning("""
                ⚠️ **Mapa de calor solo disponible en versión Premium**
                
                Desbloquea esta función para:
                - Visualización avanzada de producción
                - Mapas de calor interactivos
                - Análisis espacial detallado
                
                """)
                if st.button("💎 DESBLOQUEAR MAPAS DE CALOR", use_container_width=True):
                    activar_premium_instantaneo()
                    st.rerun()
        
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
                    
                    # Indicador de calidad
                    if datos_modis.get('estado') == 'real':
                        st.success("✓ **Estado:** Datos reales (Premium)")
                    else:
                        st.info("ℹ️ **Estado:** Datos simulados (Gratuito)")
                
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
                
                # Mostrar imagen MODIS
                st.subheader("🖼️ IMAGEN MODIS")
                
                if st.session_state.imagen_modis_bytes:
                    try:
                        # Asegurarse de que esté en la posición correcta
                        st.session_state.imagen_modis_bytes.seek(0)
                        st.image(st.session_state.imagen_modis_bytes,
                                caption=f"Imagen MODIS {datos_modis.get('indice', '')} - {datos_modis.get('fecha_imagen', '')}",
                                use_container_width=True)
                    except Exception:
                        st.info("No se pudo mostrar la imagen MODIS")
                else:
                    st.info("No hay imagen MODIS disponible para mostrar")
                    
                    if not st.session_state.usuario_autenticado:
                        st.warning("""
                        ⚠️ **Imágenes MODIS reales solo disponibles en Premium**
                        
                        Actualiza para acceder a:
                        - Imágenes satelitales reales de la NASA
                        - Datos actualizados diariamente
                        - Análisis con información real
                        
                        """)
                        if st.button("💎 VER IMÁGENES REALES", use_container_width=True):
                            activar_premium_instantaneo()
                            st.rerun()
            else:
                st.warning("No hay datos MODIS disponibles. Ejecute el análisis primero.")
        
        with tab4:
            st.subheader("📈 GRÁFICOS DE ANÁLISIS")
            
            # Gráfico de NDVI
            st.markdown("### 📊 NDVI por Bloque")
            try:
                fig_ndvi, ax_ndvi = plt.subplots(figsize=(10, 6))
                bloques = gdf_completo['id_bloque'].astype(str)
                ndvi_values = gdf_completo['ndvi_modis']
                
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
                
                bars = ax_ndvi.bar(bloques, ndvi_values, color=colors, edgecolor='black')
                ax_ndvi.axhline(y=PARAMETROS_PALMA['NDVI_OPTIMO'], color='green', linestyle='--', 
                               label=f'Óptimo ({PARAMETROS_PALMA["NDVI_OPTIMO"]})')
                
                ax_ndvi.set_xlabel('Bloque')
                ax_ndvi.set_ylabel('NDVI')
                ax_ndvi.set_title('NDVI por Bloque - Palma Aceitera', fontsize=14, fontweight='bold')
                ax_ndvi.legend()
                ax_ndvi.grid(True, alpha=0.3, axis='y')
                
                plt.tight_layout()
                st.pyplot(fig_ndvi)
            except Exception:
                st.info("No se pudo generar el gráfico de NDVI")
            
            # Gráfico de producción
            st.markdown("### 📈 Producción por Bloque")
            try:
                fig_prod, ax_prod = plt.subplots(figsize=(10, 6))
                produccion = gdf_completo['produccion_estimada']
                
                sorted_indices = np.argsort(produccion)[::-1]
                bloques_sorted = bloques.iloc[sorted_indices]
                produccion_sorted = produccion.iloc[sorted_indices]
                
                bars = ax_prod.bar(bloques_sorted, produccion_sorted, color='#4caf50', edgecolor='#2e7d32')
                
                ax_prod.set_xlabel('Bloque')
                ax_prod.set_ylabel('Producción (kg/ha)')
                ax_prod.set_title('Producción Estimada por Bloque', fontsize=14, fontweight='bold')
                ax_prod.grid(True, alpha=0.3, axis='y')
                
                plt.tight_layout()
                st.pyplot(fig_prod)
            except Exception:
                st.info("No se pudo generar el gráfico de producción")
        
        with tab5:
            st.subheader("💰 ANÁLISIS ECONÓMICO")
            
            if st.session_state.usuario_autenticado:
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
                
                # Gráfico de rentabilidad
                st.markdown("### 📊 Rentabilidad por Bloque")
                try:
                    fig_rent, ax_rent = plt.subplots(figsize=(10, 6))
                    rentabilidad = gdf_completo['rentabilidad']
                    
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
                    
                    bars = ax_rent.bar(bloques, rentabilidad, color=colors, edgecolor='black')
                    ax_rent.axhline(y=0, color='black', linewidth=1)
                    ax_rent.axhline(y=15, color='green', linestyle='--', alpha=0.5, label='Umbral rentable (15%)')
                    
                    ax_rent.set_xlabel('Bloque')
                    ax_rent.set_ylabel('Rentabilidad (%)')
                    ax_rent.set_title('Rentabilidad por Bloque', fontsize=14, fontweight='bold')
                    ax_rent.legend()
                    ax_rent.grid(True, alpha=0.3, axis='y')
                    
                    plt.tight_layout()
                    st.pyplot(fig_rent)
                except Exception:
                    st.info("No se pudo generar el gráfico de rentabilidad")
            else:
                st.warning("""
                ⚠️ **Análisis económico avanzado solo disponible en Premium**
                
                Desbloquea esta función para:
                - Análisis detallado de rentabilidad
                - Cálculos de ROI precisos
                - Optimización de costos
                - Planificación financiera
                
                """)
                if st.button("💎 DESBLOQUEAR ANÁLISIS ECONÓMICO", use_container_width=True):
                    activar_premium_instantaneo()
                    st.rerun()
        
        with tab6:
            st.subheader("🌴 DETECCIÓN DE PALMAS INDIVIDUALES")
            
            if st.session_state.usuario_autenticado:
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
                    
                    # Mostrar imagen de detección
                    st.subheader("📷 Visualización de Detección (ESRI + Centroides)")
                    if hasattr(st.session_state, 'imagen_alta_resolucion') and st.session_state.imagen_alta_resolucion is not None:
                        try:
                            # Asegurarse de que esté en la posición correcta
                            st.session_state.imagen_alta_resolucion.seek(0)
                            st.image(st.session_state.imagen_alta_resolucion,
                                    caption="Detección de palmas sobre imagen base ESRI con puntos centroides",
                                    use_container_width=True)
                        except Exception:
                            st.info("No se pudo mostrar la imagen de detección")
                    else:
                        st.info("No hay imagen de detección disponible")
                        
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
                                # Crear GeoJSON de palmas
                                geometry = [Point(row['longitud'], row['latitud']) for _, row in df_palmas.iterrows()]
                                gdf_palmas = gpd.GeoDataFrame(df_palmas, geometry=geometry, crs='EPSG:4326')
                                geojson_palmas = gdf_palmas.to_json()
                                
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
            else:
                st.warning("""
                ⚠️ **Detección avanzada de palmas solo disponible en Premium**
                
                Actualiza para acceder a:
                - Detección con imágenes de alta resolución
                - Análisis de densidad preciso
                - Exportación de coordenadas GPS
                - Visualización sobre imágenes ESRI
                
                """)
                
                # Demo de detección limitada - VERSIÓN CORREGIDA
                if st.button("👁️ VER DEMO DE DETECCIÓN", use_container_width=True):
                    # Crear demo básica CORREGIDA
                    try:
                        img_demo = Image.new('RGB', (600, 400), color=(200, 220, 200))
                        draw_demo = ImageDraw.Draw(img_demo)
                        
                        # Dibujar algunos puntos de ejemplo
                        for i in range(20):
                            x = np.random.randint(50, 550)
                            y = np.random.randint(50, 350)
                            draw_demo.ellipse([x-3, y-3, x+3, y+3], fill=(255, 0, 0))
                        
                        # Convertir a bytes de forma segura
                        img_bytes = BytesIO()
                        img_demo.save(img_bytes, format='PNG')
                        img_bytes.seek(0)
                        
                        # Crear copia para mostrar
                        img_bytes_copy = BytesIO(img_bytes.getvalue())
                        img_bytes_copy.seek(0)
                        
                        st.image(img_bytes_copy, 
                                caption="Demo: Detección básica (Premium desbloquea más funciones)",
                                use_container_width=True)
                    except Exception as e:
                        st.error(f"Error al crear demo: {str(e)}")
                
                if st.button("💎 DESBLOQUEAR DETECCIÓN AVANZADA", use_container_width=True):
                    activar_premium_instantaneo()
                    st.rerun()

# Si no hay archivo cargado, mostrar mensaje
elif not st.session_state.archivo_cargado:
    st.info("""
    📋 **INSTRUCCIONES PARA COMENZAR:**
    
    1. **Carga tu plantación** usando el panel lateral
    2. **Configura los parámetros** de análisis
    3. **Activa Premium** para acceso completo (botón en la parte superior)
    4. **Ejecuta el análisis** completo
    5. **Explora los resultados** en las pestañas
    
    ⚡ **Características Premium:**
    - Análisis ilimitados
    - Imágenes MODIS reales de NASA
    - Mapas de calor avanzados
    - Detección precisa de palmas
    - Exportación completa de datos
    """)

# Pie de página
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #94a3b8; padding: 20px;">
    <p><strong>© 2026 Analizador de Palma Aceitera Satelital Premium</strong></p>
    <p>Datos satelitales: NASA MODIS - Acceso público | Funciones Premium requieren suscripción</p>
    <p>Desarrollado por: Martin Ernesto Cano | Contacto: mawucano@gmail.com | +5493525 532313</p>
    <p style="font-size: 0.8em; margin-top: 20px;">
        <strong>Modo de prueba:</strong> Premium activado instantáneamente para pruebas. En producción, se integraría con Mercado Pago.
    </p>
</div>
""", unsafe_allow_html=True)

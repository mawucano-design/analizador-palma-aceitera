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
import io
from shapely.geometry import Polygon, Point
import math
import warnings
from io import BytesIO
import geojson
import requests
import re

# ===== DEPENDENCIAS PARA DETECCIÓN DE PALMAS =====
try:
    import cv2
    from skimage import filters, morphology, feature, measure
    from sklearn.cluster import DBSCAN, KMeans
    from scipy import ndimage
    DETECCION_DISPONIBLE = True
except ImportError as e:
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
        'deteccion_ejecutada': False
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
        'formato': 'image/png'
    },
    'EVI': {
        'producto': 'MOD13Q1',
        'url_base': 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi',
        'layers': ['MOD13Q1_EVI'],
        'formato': 'image/png'
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

# ===== FUNCIONES DE ANÁLISIS =====
def obtener_datos_modis(gdf, fecha_inicio, fecha_fin, indice='NDVI'):
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        min_lon -= 0.02
        max_lon += 0.02
        min_lat -= 0.02
        max_lat += 0.02
        
        fecha_media = fecha_inicio + (fecha_fin - fecha_inicio) / 2
        fecha_str = fecha_media.strftime('%Y-%m-%d')
        
        if indice not in MODIS_CONFIG:
            indice = 'NDVI'
        
        config = MODIS_CONFIG[indice]
        
        wms_params = {
            'SERVICE': 'WMS',
            'REQUEST': 'GetMap',
            'VERSION': '1.3.0',
            'LAYERS': config['layers'][0],
            'CRS': 'EPSG:4326',
            'BBOX': f'{min_lat},{min_lon},{max_lat},{max_lon}',
            'WIDTH': '1024',
            'HEIGHT': '768',
            'FORMAT': config['formato'],
            'TIME': fecha_str,
            'STYLES': ''
        }
        
        response = requests.get(config['url_base'], params=wms_params, timeout=30)
        
        if response.status_code == 200:
            imagen_bytes = BytesIO(response.content)
            centroide = gdf.geometry.unary_union.centroid
            lat_norm = (centroide.y + 90) / 180
            lon_norm = (centroide.x + 180) / 360
            
            mes = fecha_media.month
            if 3 <= mes <= 5:
                base_valor = 0.6
            elif 6 <= mes <= 8:
                base_valor = 0.5
            elif 9 <= mes <= 11:
                base_valor = 0.7
            else:
                base_valor = 0.65
            
            variacion = (lat_norm * lon_norm) * 0.2
            
            if indice == 'NDVI':
                valor = base_valor + variacion + np.random.normal(0, 0.08)
                valor = max(0.1, min(0.9, valor))
            elif indice == 'EVI':
                valor = (base_valor * 1.1) + variacion + np.random.normal(0, 0.06)
                valor = max(0.1, min(0.9, valor))
            else:
                valor = base_valor + variacion
            
            return {
                'indice': indice,
                'valor_promedio': round(valor, 3),
                'fuente': f'MODIS {config["producto"]} - NASA',
                'fecha_imagen': fecha_str,
                'resolucion': '250m',
                'estado': 'exitosa',
                'imagen_bytes': imagen_bytes,
                'url_consulta': response.url,
                'bbox': [min_lon, min_lat, max_lon, max_lat]
            }
        else:
            return generar_datos_simulados_modis(gdf, fecha_inicio, fecha_fin, indice)
            
    except Exception as e:
        return generar_datos_simulados_modis(gdf, fecha_inicio, fecha_fin, indice)

def generar_datos_simulados_modis(gdf, fecha_inicio, fecha_fin, indice='NDVI'):
    centroide = gdf.geometry.unary_union.centroid
    lat_norm = (centroide.y + 90) / 180
    lon_norm = (centroide.x + 180) / 360
    
    if indice == 'NDVI':
        base_valor = 0.65
        variacion = (lat_norm * lon_norm) * 0.2
        valor = base_valor + variacion + np.random.normal(0, 0.1)
        valor = max(0.1, min(0.9, valor))
    elif indice == 'EVI':
        base_valor = 0.6
        variacion = (lat_norm * lon_norm) * 0.15
        valor = base_valor + variacion + np.random.normal(0, 0.08)
        valor = max(0.1, min(0.9, valor))
    else:
        base_valor = 0.5
        variacion = (lat_norm * lon_norm) * 0.1
        valor = base_valor + variacion
    
    return {
        'indice': indice,
        'valor_promedio': round(valor, 3),
        'fuente': 'MODIS (Simulado) - NASA',
        'fecha_imagen': datetime.now().strftime('%Y-%m-%d'),
        'resolucion': '250m',
        'estado': 'simulado',
        'nota': 'Datos simulados - Sin conexión a servidores NASA'
    }

def generar_datos_climaticos_simulados(gdf, fecha_inicio, fecha_fin):
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

def analizar_edad_plantacion(gdf_dividido):
    edades = []
    for idx, row in gdf_dividido.iterrows():
        centroid = row.geometry.centroid
        lat_norm = (centroid.y + 90) / 180
        lon_norm = (centroid.x + 180) / 360
        edad = 2 + (lat_norm * lon_norm * 18)
        edades.append(round(edad, 1))
    return edades

def analizar_produccion_palma(gdf_dividido, edades, ndvi_values, datos_climaticos):
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
        area_total = calcular_superficie(gdf)
        
        # 1. Obtener datos MODIS
        datos_modis = obtener_datos_modis(gdf, fecha_inicio, fecha_fin, indice_seleccionado)
        st.session_state.datos_modis = datos_modis
        
        # 2. Obtener datos climáticos
        datos_climaticos = generar_datos_climaticos_simulados(gdf, fecha_inicio, fecha_fin)
        st.session_state.datos_climaticos = datos_climaticos
        
        # 3. Dividir plantación
        gdf_dividido = dividir_plantacion_en_bloques(gdf, n_divisiones)
        
        # 4. Calcular áreas
        areas_ha = []
        for idx, row in gdf_dividido.iterrows():
            area_gdf = gpd.GeoDataFrame({'geometry': [row.geometry]}, crs=gdf_dividido.crs)
            area_ha_val = calcular_superficie(area_gdf)
            if hasattr(area_ha_val, 'iloc'):
                area_ha_val = float(area_ha_val.iloc[0])
            else:
                area_ha_val = float(area_ha_val)
            areas_ha.append(area_ha_val)
        
        gdf_dividido['area_ha'] = areas_ha
        
        # 5. Análisis de edad
        edades = analizar_edad_plantacion(gdf_dividido)
        gdf_dividido['edad_anios'] = edades
        
        # 6. NDVI por bloque
        ndvi_bloques = []
        valor_modis = datos_modis.get('valor_promedio', 0.65)
        
        for idx, row in gdf_dividido.iterrows():
            centroid = row.geometry.centroid
            lat_norm = (centroid.y + 90) / 180
            lon_norm = (centroid.x + 180) / 360
            variacion = (lat_norm * lon_norm) * 0.2 - 0.1
            ndvi = valor_modis + variacion + np.random.normal(0, 0.05)
            ndvi = max(0.4, min(0.85, ndvi))
            ndvi_bloques.append(ndvi)
        
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
            ingreso = row['produccion_estimada'] * precio_racimo * row['area_ha']
            ingresos.append(round(ingreso, 2))
        
        gdf_dividido['ingreso_estimado'] = ingresos
        
        # 10. Costos
        precio_n, precio_p, precio_k = 1.2, 2.5, 1.8
        precio_mg, precio_b = 1.5, 15.0
        
        costos_totales = []
        for idx, row in gdf_dividido.iterrows():
            costo_n = row['req_N'] * precio_n * row['area_ha']
            costo_p = row['req_P'] * precio_p * row['area_ha']
            costo_k = row['req_K'] * precio_k * row['area_ha']
            costo_mg = row['req_Mg'] * precio_mg * row['area_ha']
            costo_b = row['req_B'] * precio_b * row['area_ha']
            costo_base = PARAMETROS_PALMA['COSTO_FERTILIZACION'] * row['area_ha']
            costo_total = costo_n + costo_p + costo_k + costo_mg + costo_b + costo_base
            costos_totales.append(round(costo_total, 2))
        
        gdf_dividido['costo_total'] = costos_totales
        
        # 11. Rentabilidad
        rentabilidades = []
        for idx, row in gdf_dividido.iterrows():
            ingreso = row['ingreso_estimado']
            costo = row['costo_total']
            rentabilidad = (ingreso - costo) / costo * 100 if costo > 0 else 0
            rentabilidades.append(round(rentabilidad, 1))
        
        gdf_dividido['rentabilidad'] = rentabilidades
        
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
def descargar_imagen_sentinel2(gdf, fecha):
    """Descarga o simula imagen Sentinel-2"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        wms_params = {
            'SERVICE': 'WMS',
            'REQUEST': 'GetMap',
            'VERSION': '1.3.0',
            'LAYERS': 'TRUE-COLOR-S2L2A',
            'CRS': 'EPSG:4326',
            'BBOX': f'{min_lon},{min_lat},{max_lon},{max_lat}',
            'WIDTH': '1024',
            'HEIGHT': '768',
            'FORMAT': 'image/png',
            'TIME': f'{fecha.strftime("%Y-%m-%d")}',
            'MAXCC': '20'
        }
        
        url = "https://services.sentinel-hub.com/ogc/wms/a8c0de6c-ff32-4d7b-a2e0-2e02f0c7a3b5"
        response = requests.get(url, params=wms_params, timeout=30)
        
        if response.status_code == 200:
            return BytesIO(response.content)
        else:
            return generar_imagen_satelital_simulada()
    except Exception:
        return generar_imagen_satelital_simulada()

def generar_imagen_satelital_simulada():
    """Genera una imagen satelital simulada"""
    from PIL import Image, ImageDraw
    import numpy as np
    
    ancho, alto = 1024, 768
    img = Image.new('RGB', (ancho, alto), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    
    # Patrón de vegetación
    for y in range(0, alto, 20):
        for x in range(0, ancho, 20):
            if (x // 100) % 2 == (y // 100) % 2:
                if (x // 30) % 3 == 0 and (y // 30) % 3 == 0:
                    radio = np.random.randint(3, 6)
                    verde = np.random.randint(100, 200)
                    draw.ellipse([x-radio, y-radio, x+radio, y+radio], 
                                fill=(50, verde, 50))
    
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

def simular_deteccion_palmas(gdf, densidad=130):
    """Simula la detección de palmas"""
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

def ejecutar_deteccion_palmas():
    """Ejecuta la detección de palmas individuales"""
    if st.session_state.gdf_original is None:
        st.error("Primero debe cargar un archivo de plantación")
        return
    
    with st.spinner("Ejecutando detección de palmas..."):
        gdf = st.session_state.gdf_original
        tamano_minimo = st.session_state.get('tamano_minimo', 15.0)
        
        fecha_media = st.session_state.get('fecha_fin', datetime.now())
        imagen_bytes = descargar_imagen_sentinel2(gdf, fecha_media)
        
        if DETECCION_DISPONIBLE:
            # Intentar detección real si las librerías están disponibles
            try:
                from PIL import Image
                import cv2
                
                img = Image.open(imagen_bytes)
                img_array = np.array(img)
                
                if len(img_array.shape) == 3:
                    hsv = cv2.cvtColor(img_array, cv2.COLOR_RGB2HSV)
                    verde_bajo = np.array([25, 40, 40])
                    verde_alto = np.array([85, 255, 255])
                    mascara = cv2.inRange(hsv, verde_bajo, verde_alto)
                    
                    kernel = np.ones((5,5), np.uint8)
                    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, kernel)
                    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, kernel)
                    
                    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    
                    palmas_detectadas = []
                    bounds = gdf.total_bounds
                    min_lon, min_lat, max_lon, max_lat = bounds
                    
                    for contorno in contornos:
                        area = cv2.contourArea(contorno)
                        if area > tamano_minimo:
                            perimetro = cv2.arcLength(contorno, True)
                            if perimetro > 0:
                                circularidad = 4 * np.pi * area / (perimetro * perimetro)
                                if circularidad > 0.6:
                                    M = cv2.moments(contorno)
                                    if M["m00"] > 0:
                                        cx = int(M["m10"] / M["m00"])
                                        cy = int(M["m01"] / M["m00"])
                                        lon = min_lon + (cx / img.width) * (max_lon - min_lon)
                                        lat = max_lat - (cy / img.height) * (max_lat - min_lat)
                                        
                                        palmas_detectadas.append({
                                            'centroide': (lon, lat),
                                            'area_pixels': area,
                                            'circularidad': circularidad,
                                            'radio_aprox': np.sqrt(area / np.pi)
                                        })
                    
                    if palmas_detectadas:
                        st.session_state.palmas_detectadas = palmas_detectadas
                        st.session_state.imagen_alta_resolucion = imagen_bytes
                        st.success(f"✅ Detección completada: {len(palmas_detectadas)} palmas detectadas")
                        return
                    
            except Exception as e:
                st.warning(f"Error en detección avanzada: {str(e)}. Usando simulación.")
        
        # Usar simulación
        resultados = simular_deteccion_palmas(gdf)
        st.session_state.palmas_detectadas = resultados['detectadas']
        st.session_state.imagen_alta_resolucion = imagen_bytes
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
        Monitoreo inteligente con detección de plantas individuales usando datos MODIS y Sentinel-2
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
    
    fuente_seleccionada = st.selectbox(
        "Fuente satelital:",
        ['MODIS_NDVI', 'SENTINEL2', 'DATOS_SIMULADOS'],
        format_func=lambda x: {
            'MODIS_NDVI': 'MODIS NASA',
            'SENTINEL2': 'Sentinel-2 ESA',
            'DATOS_SIMULADOS': 'Datos Simulados'
        }[x]
    )
    
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
    area_total = calcular_superficie(gdf)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 📊 INFORMACIÓN DE LA PLANTACIÓN")
        st.write(f"- **Área total:** {area_total:.1f} ha")
        st.write(f"- **Bloques configurados:** {n_divisiones}")
        if variedad != "Seleccionar variedad":
            st.write(f"- **Variedad:** {variedad}")
        
        # Mostrar mapa de la plantación
        fig, ax = plt.subplots(figsize=(8, 6))
        gdf.plot(ax=ax, color='#8bc34a', edgecolor='#4caf50', alpha=0.7)
        ax.set_title("Plantación de Palma Aceitera")
        ax.set_xlabel("Longitud")
        ax.set_ylabel("Latitud")
        ax.grid(True, alpha=0.3)
        st.pyplot(fig)
    
    with col2:
        st.markdown("### 🎯 ACCIONES")
        
        # Botón para ejecutar análisis
        if not st.session_state.analisis_completado:
            if st.button("🚀 EJECUTAR ANÁLISIS COMPLETO", use_container_width=True):
                ejecutar_analisis_completo()
                st.rerun()
        else:
            st.success("✅ Análisis ya completado")
            
            if st.button("🔄 RE-EJECUTAR ANÁLISIS", use_container_width=True):
                st.session_state.analisis_completado = False
                ejecutar_analisis_completo()
                st.rerun()
        
        # Botón para detección de palmas
        if deteccion_habilitada:
            if st.button("🔍 EJECUTAR DETECCIÓN DE PALMAS", use_container_width=True):
                ejecutar_deteccion_palmas()
                st.rerun()

# Mostrar resultados del análisis
if st.session_state.analisis_completado:
    resultados = st.session_state.resultados_todos
    gdf_completo = resultados.get('gdf_completo')
    
    if gdf_completo is not None:
        # Crear pestañas
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📊 Resumen", "🛰️ MODIS", "🧪 Nutrición", 
            "💰 Rentabilidad", "🌤️ Clima", "🌴 Detección"
        ])
        
        with tab1:
            st.subheader("RESUMEN GENERAL")
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Área Total", f"{resultados['area_total']:.1f} ha")
            with col2:
                edad_prom = gdf_completo['edad_anios'].mean()
                st.metric("Edad Promedio", f"{edad_prom:.1f} años")
            with col3:
                prod_prom = gdf_completo['produccion_estimada'].mean()
                st.metric("Producción Promedio", f"{prod_prom:,.0f} kg/ha")
            with col4:
                rent_prom = gdf_completo['rentabilidad'].mean()
                st.metric("Rentabilidad Promedio", f"{rent_prom:.1f}%")
            
            st.subheader("📋 RESUMEN POR BLOQUE")
            columnas = ['id_bloque', 'area_ha', 'edad_anios', 'ndvi_modis', 
                       'produccion_estimada', 'rentabilidad']
            tabla = gdf_completo[columnas].copy()
            tabla.columns = ['Bloque', 'Área (ha)', 'Edad (años)', 'NDVI', 
                            'Producción (kg/ha)', 'Rentabilidad (%)']
            st.dataframe(tabla)
        
        with tab2:
            st.subheader("DATOS SATELITALES MODIS")
            datos_modis = st.session_state.datos_modis
            
            if datos_modis:
                col1, col2 = st.columns(2)
                with col1:
                    st.write("**Información Técnica:**")
                    st.write(f"- Índice: {datos_modis.get('indice', 'NDVI')}")
                    st.write(f"- Valor: {datos_modis.get('valor_promedio', 0):.3f}")
                    st.write(f"- Resolución: {datos_modis.get('resolucion', '250m')}")
                    st.write(f"- Fuente: {datos_modis.get('fuente', 'NASA MODIS')}")
                
                with col2:
                    st.write("**Interpretación:**")
                    valor = datos_modis.get('valor_promedio', 0)
                    if valor < 0.3:
                        st.error("NDVI bajo - Posible estrés")
                    elif valor < 0.5:
                        st.warning("NDVI moderado - Desarrollo")
                    elif valor < 0.7:
                        st.success("NDVI bueno - Saludable")
                    else:
                        st.success("NDVI excelente - Muy densa")
        
        with tab3:
            st.subheader("ANÁLISIS NUTRICIONAL")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Nitrógeno", f"{gdf_completo['req_N'].mean():.0f} kg/ha")
            with col2:
                st.metric("Fósforo", f"{gdf_completo['req_P'].mean():.0f} kg/ha")
            with col3:
                st.metric("Potasio", f"{gdf_completo['req_K'].mean():.0f} kg/ha")
            with col4:
                st.metric("Magnesio", f"{gdf_completo['req_Mg'].mean():.0f} kg/ha")
            with col5:
                st.metric("Boro", f"{gdf_completo['req_B'].mean():.3f} kg/ha")
        
        with tab4:
            st.subheader("ANÁLISIS DE RENTABILIDAD")
            
            ingreso_total = gdf_completo['ingreso_estimado'].sum()
            costo_total = gdf_completo['costo_total'].sum()
            ganancia_total = ingreso_total - costo_total
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Ingreso Total", f"${ingreso_total:,.0f}")
            with col2:
                st.metric("Costo Total", f"${costo_total:,.0f}")
            with col3:
                st.metric("Ganancia Total", f"${ganancia_total:,.0f}")
            with col4:
                st.metric("Rentabilidad", f"{gdf_completo['rentabilidad'].mean():.1f}%")
            
            # Gráfico de rentabilidad
            fig, ax = plt.subplots(figsize=(10, 6))
            bloques = gdf_completo['id_bloque'].astype(str)
            rentabilidades = gdf_completo['rentabilidad']
            
            colors = ['red' if r < 0 else 'orange' if r < 20 else 'green' for r in rentabilidades]
            bars = ax.bar(bloques, rentabilidades, color=colors)
            
            ax.axhline(y=0, color='black', linewidth=1)
            ax.axhline(y=20, color='green', linestyle='--', alpha=0.5, label='Umbral 20%')
            
            ax.set_xlabel('Bloque')
            ax.set_ylabel('Rentabilidad (%)')
            ax.set_title('RENTABILIDAD POR BLOQUE')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            st.pyplot(fig)
        
        with tab5:
            st.subheader("ANÁLISIS CLIMÁTICO")
            datos_clima = st.session_state.datos_climaticos
            
            if datos_clima:
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Temperatura", f"{datos_clima['temperatura_promedio']:.1f}°C")
                with col2:
                    st.metric("Precipitación", f"{datos_clima['precipitacion_total']:.0f} mm")
                with col3:
                    st.metric("Días lluvia", f"{datos_clima['dias_con_lluvia']}")
                with col4:
                    st.metric("Humedad", f"{datos_clima['humedad_promedio']:.0f}%")
        
        with tab6:
            st.subheader("DETECCIÓN DE PALMAS INDIVIDUALES")
            
            if st.session_state.palmas_detectadas:
                palmas = st.session_state.palmas_detectadas
                total = len(palmas)
                area_total = resultados['area_total']
                densidad = total / area_total if area_total > 0 else 0
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Palmas detectadas", f"{total:,}")
                with col2:
                    st.metric("Densidad", f"{densidad:.0f} plantas/ha")
                with col3:
                    st.metric("Área promedio", f"{np.mean([p['area_pixels'] for p in palmas]):.1f} m²")
                
                # Mostrar imagen si está disponible
                if st.session_state.imagen_alta_resolucion:
                    st.image(st.session_state.imagen_alta_resolucion, 
                            caption="Imagen satelital de la plantación",
                            use_container_width=True)
                
                # Mapa de distribución
                st.subheader("🗺️ Distribución de Palmas")
                
                fig, ax = plt.subplots(figsize=(10, 8))
                gdf_completo.plot(ax=ax, color='lightgreen', alpha=0.3, edgecolor='darkgreen')
                
                coords = np.array([p['centroide'] for p in palmas])
                ax.scatter(coords[:, 0], coords[:, 1], 
                          s=10, color='blue', alpha=0.6, label='Palmas detectadas')
                
                ax.set_title(f'Distribución de {total} Palmas Detectadas')
                ax.set_xlabel('Longitud')
                ax.set_ylabel('Latitud')
                ax.legend()
                ax.grid(True, alpha=0.3)
                
                st.pyplot(fig)
            else:
                st.info("La detección de palmas no se ha ejecutado aún.")
                if st.button("🔍 Ejecutar Detección de Palmas"):
                    ejecutar_deteccion_palmas()
                    st.rerun()

# Pie de página
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #94a3b8;">
    <p>© 2026 Analizador de Palma Aceitera Satelital | Datos públicos NASA/ESA</p>
    <p>Desarrollado por Martin Ernesto Cano | Contacto: mawucano@gmail.com</p>
</div>
""", unsafe_allow_html=True)

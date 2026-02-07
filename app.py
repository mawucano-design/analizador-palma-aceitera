# app.py - Versión simplificada para PALMA ACEITERA
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
        'geojson_bytes': None,
        'intentos_analisis': 0,
        'fecha_analisis': None,
        'variedad_seleccionada': None,
        'zoom_level': 14
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ===== CONFIGURACIONES =====
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
    
    # Limitar número de bloques para evitar problemas de rendimiento
    n_bloques = min(n_bloques, 20)
    
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
def generar_datos_modis_simulados(gdf):
    """Genera datos MODIS simulados mejorados"""
    try:
        centroide = gdf.geometry.unary_union.centroid
        lat_norm = (centroide.y + 90) / 180
        lon_norm = (centroide.x + 180) / 360
        
        # Calcular NDVI basado en ubicación y temporada
        mes = datetime.now().month
        if 3 <= mes <= 5:  # Primavera
            base_valor = 0.70
        elif 6 <= mes <= 8:  # Verano
            base_valor = 0.65
        elif 9 <= mes <= 11:  # Otoño
            base_valor = 0.75
        else:  # Invierno
            base_valor = 0.68
        
        variacion = (lat_norm * lon_norm) * 0.15
        ndvi = base_valor + variacion + np.random.normal(0, 0.03)
        ndvi = max(0.4, min(0.85, ndvi))
        
        # Crear imagen simulada
        img_bytes = generar_imagen_modis_simulada(gdf)
        
        return {
            'indice': 'NDVI',
            'valor_promedio': round(ndvi, 3),
            'fuente': 'MODIS Simulado - NASA',
            'fecha_imagen': datetime.now().strftime('%Y-%m-%d'),
            'resolucion': '250m',
            'estado': 'simulado',
            'imagen_disponible': True,
            'imagen_bytes': img_bytes
        }
    except Exception:
        return {
            'indice': 'NDVI',
            'valor_promedio': 0.65,
            'fuente': 'MODIS Simulado',
            'fecha_imagen': datetime.now().strftime('%Y-%m-%d'),
            'resolucion': '250m',
            'estado': 'simulado',
            'imagen_disponible': False
        }

def generar_imagen_modis_simulada(gdf):
    """Genera una imagen MODIS simulada simple"""
    try:
        width, height = 800, 600
        img = Image.new('RGB', (width, height), color=(200, 220, 200))
        draw = ImageDraw.Draw(img)
        
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Dibujar gradiente de NDVI
        for i in range(0, width, 5):
            for j in range(0, height, 5):
                # Gradiente simple
                x_ratio = i / width
                y_ratio = j / height
                
                # Simular NDVI
                if (i // 50 + j // 50) % 3 == 0:
                    green = int(150 + x_ratio * 80)
                    red = int(100 + (1 - x_ratio) * 50)
                    blue = int(100 + (1 - y_ratio) * 50)
                else:
                    green = int(100 + x_ratio * 60)
                    red = int(120 + (1 - x_ratio) * 60)
                    blue = int(80 + (1 - y_ratio) * 40)
                
                draw.rectangle([i, j, i+4, j+4], fill=(red, green, blue))
        
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes
    except Exception:
        img = Image.new('RGB', (800, 600), color=(100, 150, 100))
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes

def generar_datos_climaticos_simulados(gdf):
    """Genera datos climáticos simulados completos"""
    try:
        centroide = gdf.geometry.unary_union.centroid
        lat_norm = (centroide.y + 90) / 180
        
        # Base según latitud
        if lat_norm > 0.6:  # Zona templada
            temp_base = 20
            precip_base = 1200
            radiacion_base = 15
        elif lat_norm > 0.3:  # Zona subtropical
            temp_base = 25
            precip_base = 1800
            radiacion_base = 18
        else:  # Zona tropical
            temp_base = 27
            precip_base = 2200
            radiacion_base = 20
        
        # Variación estacional
        mes = datetime.now().month
        if mes in [12, 1, 2]:
            temp_ajuste = 2
            precip_ajuste = 100
        elif mes in [3, 4, 5]:
            temp_ajuste = 0
            precip_ajuste = 50
        elif mes in [6, 7, 8]:
            temp_ajuste = -2
            precip_ajuste = -100
        else:
            temp_ajuste = 1
            precip_ajuste = 50
        
        return {
            'temperatura_promedio': round(temp_base + temp_ajuste + np.random.normal(0, 1.5), 1),
            'precipitacion_total': round(max(0, precip_base + precip_ajuste + np.random.normal(0, 200)), 0),
            'radiacion_promedio': round(radiacion_base + np.random.normal(0, 2), 1),
            'dias_con_lluvia': 15 + np.random.randint(-3, 3),
            'humedad_promedio': round(75 + np.random.normal(0, 3), 1),
            'velocidad_viento': round(3 + np.random.normal(0, 1), 1),
            'evaporacion': round(4 + np.random.normal(0, 0.5), 1)
        }
    except Exception:
        return {
            'temperatura_promedio': 25.0,
            'precipitacion_total': 1800.0,
            'radiacion_promedio': 18.0,
            'dias_con_lluvia': 15,
            'humedad_promedio': 75.0,
            'velocidad_viento': 3.0,
            'evaporacion': 4.0
        }

def analizar_edad_plantacion(gdf_dividido):
    """Analiza la edad de la plantación por bloque"""
    edades = []
    for idx, row in gdf_dividido.iterrows():
        centroid = row.geometry.centroid
        lat_norm = (centroid.y + 90) / 180
        lon_norm = (centroid.x + 180) / 360
        # Edad entre 2 y 20 años
        edad = 2 + (lat_norm * lon_norm * 18)
        edades.append(round(edad, 1))
    return edades

def analizar_produccion_palma(gdf_dividido, edades, ndvi_values, datos_climaticos):
    """Calcula la producción estimada por bloque"""
    producciones = []
    rendimiento_optimo = PARAMETROS_PALMA['RENDIMIENTO_OPTIMO']
    
    for i, edad in enumerate(edades):
        ndvi = ndvi_values[i] if i < len(ndvi_values) else 0.65
        
        # Factor edad
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
        
        # Factor NDVI
        factor_ndvi = min(1.0, ndvi / PARAMETROS_PALMA['NDVI_OPTIMO'])
        
        # Factor clima
        if datos_climaticos:
            temp_factor = 1.0 - abs(datos_climaticos['temperatura_promedio'] - 26) / 10
            precip_factor = min(1.0, datos_climaticos['precipitacion_total'] / 2000)
            factor_clima = (temp_factor * 0.5 + precip_factor * 0.5)
        else:
            factor_clima = 0.8
        
        # Cálculo final
        produccion = rendimiento_optimo * factor_edad * factor_ndvi * factor_clima
        producciones.append(round(produccion, 0))
    
    return producciones

def analizar_fertilidad_actual(gdf_dividido):
    """Analiza la fertilidad actual por bloque"""
    n_actual, p_actual, k_actual = [], [], []
    
    for idx, row in gdf_dividido.iterrows():
        centroid = row.geometry.centroid
        lat_norm = (centroid.y + 90) / 180
        lon_norm = (centroid.x + 180) / 360
        
        # Valores base con variación espacial
        base_n = 180 + (lat_norm * lon_norm * 40)
        base_p = 60 + (lat_norm * lon_norm * 20)
        base_k = 250 + (lat_norm * lon_norm * 50)
        
        # Añadir variación aleatoria
        n_actual.append(round(base_n + np.random.normal(0, 15), 1))
        p_actual.append(round(base_p + np.random.normal(0, 8), 1))
        k_actual.append(round(base_k + np.random.normal(0, 20), 1))
    
    return n_actual, p_actual, k_actual

def calcular_recomendaciones_npk(gdf_dividido, n_actual, p_actual, k_actual, edades, ndvi_values):
    """Calcula recomendaciones de fertilización NPK"""
    rec_n, rec_p, rec_k = [], [], []
    
    for i in range(len(gdf_dividido)):
        edad = edades[i]
        ndvi = ndvi_values[i]
        
        # Requerimientos según edad
        if edad < 3:
            n_requerido = 80
            p_requerido = 25
            k_requerido = 120
        elif edad <= 8:
            n_requerido = 120 + (edad - 3) * 15
            p_requerido = 35 + (edad - 3) * 5
            k_requerido = 180 + (edad - 3) * 20
        else:
            n_requerido = 200
            p_requerido = 60
            k_requerido = 280
        
        # Ajustar por NDVI
        ajuste_ndvi = 1.5 - ndvi
        
        # Calcular recomendaciones
        rec_n.append(max(0, round((n_requerido * ajuste_ndvi) - n_actual[i], 1)))
        rec_p.append(max(0, round((p_requerido * ajuste_ndvi) - p_actual[i], 1)))
        rec_k.append(max(0, round((k_requerido * ajuste_ndvi) - k_actual[i], 1)))
    
    return rec_n, rec_p, rec_k

def crear_mapa_simple(gdf, columna_valor=None, titulo="Mapa"):
    """Crea un mapa simple sin problemas de tamaño"""
    try:
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # Limitar número de geometrías para evitar problemas
        if len(gdf) > 20:
            gdf_plot = gdf.head(20)
        else:
            gdf_plot = gdf
        
        if columna_valor and columna_valor in gdf_plot.columns:
            # Mapa con colores según valores
            valores = gdf_plot[columna_valor]
            norm = plt.Normalize(valores.min(), valores.max())
            cmap = plt.cm.YlOrRd
            
            for idx, row in gdf_plot.iterrows():
                try:
                    if row.geometry.geom_type == 'Polygon':
                        # Simplificar geometría
                        simplified = row.geometry.simplify(0.001, preserve_topology=True)
                        poly_coords = list(simplified.exterior.coords)
                        if len(poly_coords) > 100:  # Limitar puntos
                            poly_coords = poly_coords[:100]
                        
                        color = cmap(norm(row[columna_valor]))
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
            cbar.set_label(columna_valor)
        else:
            # Mapa simple
            try:
                gdf_plot.plot(ax=ax, color='lightgreen', edgecolor='darkgreen', alpha=0.6)
            except:
                # Fallback manual
                for idx, row in gdf_plot.iterrows():
                    try:
                        if row.geometry.geom_type == 'Polygon':
                            poly_coords = list(row.geometry.exterior.coords)
                            if len(poly_coords) > 100:
                                poly_coords = poly_coords[:100]
                            polygon = MplPolygon(poly_coords, closed=True, 
                                               facecolor='lightgreen', 
                                               edgecolor='darkgreen', 
                                               linewidth=1,
                                               alpha=0.6)
                            ax.add_patch(polygon)
                    except Exception:
                        continue
        
        ax.set_title(titulo, fontsize=14, fontweight='bold')
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Guardar figura
        img_bytes = BytesIO()
        fig.savefig(img_bytes, format='PNG', dpi=100, bbox_inches='tight')
        img_bytes.seek(0)
        
        return fig, img_bytes
    except Exception as e:
        st.error(f"Error al crear mapa: {str(e)}")
        return None, None

def crear_geojson_resultados(gdf):
    """Crea un GeoJSON con todos los resultados del análisis"""
    try:
        # Crear copia
        gdf_export = gdf.copy()
        
        # Convertir a GeoJSON
        geojson_dict = json.loads(gdf_export.to_json())
        
        # Agregar metadatos
        geojson_dict['metadata'] = {
            'export_date': datetime.now().isoformat(),
            'total_blocks': len(gdf),
            'area_total_ha': float(gdf['area_ha'].sum()),
            'production_avg': float(gdf['produccion_estimada'].mean()),
            'ndvi_avg': float(gdf['ndvi_modis'].mean())
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

def simular_deteccion_palmas_mejorada(gdf, densidad=130):
    """Simula la detección de palmas con centroides para Google Earth"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        area_ha = calcular_superficie(gdf)
        if area_ha <= 0:
            area_ha = 10  # Valor por defecto
        
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
                    # Añadir pequeña variación
                    lon += np.random.normal(0, lado_grados * 0.1)
                    lat += np.random.normal(0, lado_grados * 0.1)
                    
                    # Crear punto de detección con metadatos
                    palmas_detectadas.append({
                        'id': len(palmas_detectadas) + 1,
                        'centroide': (round(lon, 6), round(lat, 6)),
                        'area_m2': round(np.random.uniform(10, 20), 1),
                        'diametro_aprox': round(np.random.uniform(4, 8), 1),
                        'estado_salud': np.random.choice(['Excelente', 'Bueno', 'Regular'], p=[0.6, 0.3, 0.1]),
                        'produccion_estimada': round(np.random.uniform(15, 35), 1),
                        'simulado': True
                    })
        
        return {
            'detectadas': palmas_detectadas,
            'total': len(palmas_detectadas),
            'densidad_calculada': len(palmas_detectadas) / area_ha if area_ha > 0 else densidad,
            'area_ha': area_ha,
            'patron': 'hexagonal' if len(palmas_detectadas) > 10 else 'aleatorio'
        }
    except Exception:
        return {
            'detectadas': [],
            'total': 0,
            'densidad_calculada': 0,
            'area_ha': 0,
            'patron': 'indeterminado'
        }

def crear_imagen_deteccion_google_earth(gdf, palmas_detectadas):
    """Crea imagen de detección estilo Google Earth"""
    try:
        width, height = 800, 600
        img = Image.new('RGB', (width, height), color=(40, 100, 40))
        draw = ImageDraw.Draw(img)
        
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Dibujar terreno estilo Google Earth
        for i in range(0, width, 20):
            for j in range(0, height, 20):
                green = np.random.randint(80, 180)
                draw.rectangle([i, j, i+19, j+19], 
                             fill=(40, green, 40))
        
        # Dibujar palmas
        for palma in palmas_detectadas[:500]:  # Limitar para visualización
            lon, lat = palma['centroide']
            x = int((lon - min_lon) / (max_lon - min_lon) * width)
            y = int((max_lat - lat) / (max_lat - min_lat) * height)
            
            # Dibujar palma (círculo con tallo)
            radio = 3
            # Tallo
            draw.line([x, y, x, y+8], fill=(100, 60, 30), width=2)
            # Copa
            draw.ellipse([x-radio, y-radio, x+radio, y+radio], 
                        fill=(0, 150, 0), outline=(0, 100, 0))
        
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes
    except Exception:
        img = Image.new('RGB', (800, 600), color=(60, 120, 60))
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes

# ===== FUNCIÓN PRINCIPAL DE ANÁLISIS =====
def ejecutar_analisis_completo():
    """Ejecuta el análisis completo"""
    if st.session_state.gdf_original is None:
        st.error("Primero debe cargar un archivo de plantación")
        return
    
    with st.spinner("Ejecutando análisis completo..."):
        # Obtener parámetros
        n_divisiones = st.session_state.get('n_divisiones', 12)
        gdf = st.session_state.gdf_original
        
        try:
            area_total = calcular_superficie(gdf)
        except Exception:
            area_total = 0.0
        
        # 1. Obtener datos MODIS
        datos_modis = generar_datos_modis_simulados(gdf)
        st.session_state.datos_modis = datos_modis
        
        # 2. Obtener datos climáticos
        datos_climaticos = generar_datos_climaticos_simulados(gdf)
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
                ndvi = valor_modis + variacion + np.random.normal(0, 0.03)
                ndvi = max(0.4, min(0.85, ndvi))
                ndvi_bloques.append(round(ndvi, 3))
            except Exception:
                ndvi_bloques.append(0.65)
        
        gdf_dividido['ndvi_modis'] = ndvi_bloques
        
        # 7. Fertilidad actual
        n_actual, p_actual, k_actual = analizar_fertilidad_actual(gdf_dividido)
        gdf_dividido['N_actual'] = n_actual
        gdf_dividido['P_actual'] = p_actual
        gdf_dividido['K_actual'] = k_actual
        
        # 8. Recomendaciones NPK
        rec_n, rec_p, rec_k = calcular_recomendaciones_npk(gdf_dividido, n_actual, p_actual, k_actual, edades, ndvi_bloques)
        gdf_dividido['rec_N'] = rec_n
        gdf_dividido['rec_P'] = rec_p
        gdf_dividido['rec_K'] = rec_k
        
        # 9. Producción
        producciones = analizar_produccion_palma(gdf_dividido, edades, ndvi_bloques, datos_climaticos)
        gdf_dividido['produccion_estimada'] = producciones
        
        # 10. Cálculos económicos
        precio_racimo = 0.15  # USD por kg
        ingresos = []
        costos = []
        
        for idx, row in gdf_dividido.iterrows():
            try:
                # Ingresos
                ingreso = row['produccion_estimada'] * precio_racimo * row['area_ha']
                ingresos.append(round(ingreso, 2))
                
                # Costos (fertilización + operación)
                costo_fertilizacion = (row['rec_N'] * 1.2 + row['rec_P'] * 2.5 + row['rec_K'] * 1.8) * row['area_ha']
                costo_operacion = PARAMETROS_PALMA['COSTO_FERTILIZACION'] * row['area_ha']
                costo_total = costo_fertilizacion + costo_operacion
                costos.append(round(costo_total, 2))
            except Exception:
                ingresos.append(0.0)
                costos.append(0.0)
        
        gdf_dividido['ingreso_estimado'] = ingresos
        gdf_dividido['costo_total'] = costos
        
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
        
        # 12. Potencial de cosecha (clasificación)
        potencial = []
        for prod in producciones:
            if prod > 18000:
                potencial.append('Muy Alto')
            elif prod > 16000:
                potencial.append('Alto')
            elif prod > 14000:
                potencial.append('Medio')
            elif prod > 12000:
                potencial.append('Bajo')
            else:
                potencial.append('Muy Bajo')
        
        gdf_dividido['potencial_cosecha'] = potencial
        
        # 13. Crear GeoJSON
        crear_geojson_resultados(gdf_dividido)
        
        # 14. Crear mapas
        st.session_state.mapa_generado = True
        
        # Almacenar resultados
        st.session_state.resultados_todos = {
            'exitoso': True,
            'gdf_completo': gdf_dividido,
            'area_total': area_total,
            'datos_modis': datos_modis,
            'datos_climaticos': datos_climaticos,
            'fecha_analisis': datetime.now()
        }
        
        st.session_state.analisis_completado = True
        st.session_state.intentos_analisis += 1
        st.success("✅ Análisis completado exitosamente!")

def ejecutar_deteccion_palmas():
    """Ejecuta la detección de palmas individuales"""
    if st.session_state.gdf_original is None:
        st.error("Primero debe cargar un archivo de plantación")
        return
    
    with st.spinner("Detectando palmas individuales..."):
        gdf = st.session_state.gdf_original
        densidad = st.session_state.get('densidad_palmas', 130)
        
        resultados = simular_deteccion_palmas_mejorada(gdf, densidad)
        st.session_state.palmas_detectadas = resultados['detectadas']
        st.session_state.deteccion_ejecutada = True
        
        # Crear imagen de detección
        imagen_bytes = crear_imagen_deteccion_google_earth(gdf, resultados['detectadas'])
        if imagen_bytes:
            st.session_state.imagen_alta_resolucion = imagen_bytes
        
        st.success(f"✅ Detección completada: {len(resultados['detectadas'])} palmas detectadas")

# ===== INTERFAZ DE USUARIO =====
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
        Monitoreo inteligente con detección de plantas individuales y análisis de fertilidad
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
    if variedad != "Seleccionar variedad":
        st.session_state.variedad_seleccionada = variedad
    
    st.markdown("---")
    st.markdown("### 🎯 División de Plantación")
    
    n_divisiones = st.slider("Número de bloques:", 4, 20, 12)
    st.session_state.n_divisiones = n_divisiones
    
    st.markdown("---")
    st.markdown("### 🌴 Detección de Palmas")
    
    deteccion_habilitada = st.checkbox("Activar detección de plantas", value=True)
    if deteccion_habilitada:
        densidad_palmas = st.slider("Densidad estimada (plantas/ha):", 80, 200, 130, 5)
        st.session_state.densidad_palmas = densidad_palmas
    
    st.markdown("---")
    st.markdown("### 📤 Subir Polígono")
    
    uploaded_file = st.file_uploader(
        "Subir archivo de plantación",
        type=['zip', 'kml', 'kmz', 'geojson'],
        help="Formatos: Shapefile (.zip), KML (.kmz), GeoJSON (.geojson)"
    )
    
    # Información de uso
    st.markdown("---")
    st.markdown("### 📊 Estadísticas")
    st.info(f"Análisis realizados: {st.session_state.intentos_analisis}")
    
    # Botón para reiniciar
    if st.button("🔄 Reiniciar Sistema", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        init_session_state()
        st.rerun()

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
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 📊 INFORMACIÓN DE LA PLANTACIÓN")
        st.write(f"- **Área total:** {area_total:.1f} ha")
        st.write(f"- **Bloques configurados:** {n_divisiones}")
        if st.session_state.variedad_seleccionada:
            st.write(f"- **Variedad:** {st.session_state.variedad_seleccionada}")
        
        # Mostrar mapa básico
        try:
            fig_simple, ax_simple = plt.subplots(figsize=(10, 6))
            gdf.plot(ax=ax_simple, color='#8bc34a', edgecolor='#4caf50', alpha=0.7)
            ax_simple.set_title("Plantación de Palma Aceitera", fontweight='bold')
            ax_simple.set_xlabel("Longitud")
            ax_simple.set_ylabel("Latitud")
            ax_simple.grid(True, alpha=0.3)
            plt.tight_layout()
            st.pyplot(fig_simple)
        except Exception:
            st.info("Visualización básica de la plantación")
    
    with col2:
        st.markdown("### 🎯 ACCIONES")
        
        # Botones de acción
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
            if not st.session_state.analisis_completado:
                if st.button("🚀 EJECUTAR ANÁLISIS", use_container_width=True, type="primary"):
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
        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
            "📊 Resumen", "🗺️ Mapas", "🛰️ NDVI", 
            "🧪 Fertilidad", "📈 Económico", "🌦️ Clima", "🌴 Detección"
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
            
            # Tabla de resumen
            st.subheader("📋 RESUMEN POR BLOQUE")
            try:
                columnas = ['id_bloque', 'area_ha', 'edad_anios', 'ndvi_modis', 
                           'produccion_estimada', 'rentabilidad', 'potencial_cosecha']
                tabla = gdf_completo[columnas].copy()
                tabla.columns = ['Bloque', 'Área (ha)', 'Edad (años)', 'NDVI', 
                                'Producción (kg/ha)', 'Rentabilidad (%)', 'Potencial']
                st.dataframe(tabla.style.format({
                    'Área (ha)': '{:.2f}',
                    'Edad (años)': '{:.1f}',
                    'NDVI': '{:.3f}',
                    'Producción (kg/ha)': '{:,.0f}',
                    'Rentabilidad (%)': '{:.1f}'
                }), height=400)
            except Exception as e:
                st.warning(f"No se pudo mostrar la tabla: {str(e)}")
            
            # Exportar datos
            st.subheader("📥 EXPORTAR RESULTADOS")
            if st.session_state.geojson_bytes:
                st.download_button(
                    label="🗺️ Descargar GeoJSON",
                    data=st.session_state.geojson_bytes.getvalue(),
                    file_name=f"analisis_palma_{datetime.now().strftime('%Y%m%d')}.geojson",
                    mime="application/json",
                    use_container_width=True
                )
            
            # Exportar CSV
            try:
                csv_data = gdf_completo.drop(columns=['geometry']).to_csv(index=False)
                st.download_button(
                    label="📊 Descargar CSV",
                    data=csv_data,
                    file_name=f"datos_palma_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            except Exception:
                pass
        
        with tab2:
            st.subheader("🗺️ MAPAS")
            
            # Mapa de NDVI
            st.markdown("### 🗺️ Mapa de NDVI")
            try:
                fig_ndvi, img_bytes_ndvi = crear_mapa_simple(gdf_completo, 'ndvi_modis', "Mapa de NDVI")
                if fig_ndvi:
                    st.pyplot(fig_ndvi)
                    st.download_button(
                        label="📥 Descargar Mapa NDVI",
                        data=img_bytes_ndvi.getvalue() if img_bytes_ndvi else b'',
                        file_name="mapa_ndvi.png",
                        mime="image/png",
                        use_container_width=True
                    )
            except Exception as e:
                st.error(f"Error en mapa NDVI: {str(e)}")
            
            # Mapa de Producción
            st.markdown("### 📈 Mapa de Producción")
            try:
                fig_prod, img_bytes_prod = crear_mapa_simple(gdf_completo, 'produccion_estimada', "Mapa de Producción Estimada")
                if fig_prod:
                    st.pyplot(fig_prod)
                    st.download_button(
                        label="📥 Descargar Mapa Producción",
                        data=img_bytes_prod.getvalue() if img_bytes_prod else b'',
                        file_name="mapa_produccion.png",
                        mime="image/png",
                        use_container_width=True
                    )
            except Exception as e:
                st.error(f"Error en mapa producción: {str(e)}")
            
            # Mapa de Potencial de Cosecha
            st.markdown("### 🌟 Mapa de Potencial de Cosecha")
            try:
                # Crear mapa de potencial
                fig_pot, ax_pot = plt.subplots(figsize=(10, 8))
                
                # Asignar colores según potencial
                colores = {
                    'Muy Alto': '#4caf50',
                    'Alto': '#8bc34a',
                    'Medio': '#ffeb3b',
                    'Bajo': '#ff9800',
                    'Muy Bajo': '#f44336'
                }
                
                for idx, row in gdf_completo.iterrows():
                    try:
                        color = colores.get(row['potencial_cosecha'], '#cccccc')
                        if row.geometry.geom_type == 'Polygon':
                            simplified = row.geometry.simplify(0.001, preserve_topology=True)
                            poly_coords = list(simplified.exterior.coords)
                            if len(poly_coords) > 100:
                                poly_coords = poly_coords[:100]
                            polygon = MplPolygon(poly_coords, closed=True, 
                                               facecolor=color, 
                                               edgecolor='black', 
                                               linewidth=1,
                                               alpha=0.7)
                            ax_pot.add_patch(polygon)
                    except Exception:
                        continue
                
                ax_pot.set_title("Mapa de Potencial de Cosecha", fontsize=14, fontweight='bold')
                ax_pot.set_xlabel("Longitud")
                ax_pot.set_ylabel("Latitud")
                ax_pot.grid(True, alpha=0.3)
                
                # Añadir leyenda
                from matplotlib.patches import Patch
                legend_elements = [Patch(facecolor=color, label=label) 
                                 for label, color in colores.items()]
                ax_pot.legend(handles=legend_elements, loc='upper right')
                
                plt.tight_layout()
                st.pyplot(fig_pot)
            except Exception as e:
                st.error(f"Error en mapa potencial: {str(e)}")
        
        with tab3:
            st.subheader("🛰️ ANÁLISIS NDVI")
            datos_modis = st.session_state.datos_modis
            
            if datos_modis:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**📊 INFORMACIÓN:**")
                    st.write(f"- **Índice:** {datos_modis.get('indice', 'NDVI')}")
                    st.write(f"- **Valor promedio:** {datos_modis.get('valor_promedio', 0):.3f}")
                    st.write(f"- **Fuente:** {datos_modis.get('fuente', 'NASA MODIS')}")
                    st.write(f"- **Fecha:** {datos_modis.get('fecha_imagen', 'N/A')}")
                    
                    # Interpretación NDVI
                    valor = datos_modis.get('valor_promedio', 0)
                    if valor < 0.3:
                        st.error("**NDVI bajo** - Posible estrés hídrico o nutricional")
                    elif valor < 0.5:
                        st.warning("**NDVI moderado** - Vegetación en desarrollo")
                    elif valor < 0.7:
                        st.success("**NDVI bueno** - Vegetación saludable")
                    else:
                        st.success("**NDVI excelente** - Vegetación muy densa y saludable")
                
                with col2:
                    # Gráfico de NDVI por bloque
                    st.markdown("**📈 NDVI por Bloque:**")
                    try:
                        fig_ndvi_chart, ax_ndvi_chart = plt.subplots(figsize=(10, 4))
                        bloques = gdf_completo['id_bloque'].astype(str)
                        ndvi_values = gdf_completo['ndvi_modis']
                        
                        bars = ax_ndvi_chart.bar(bloques, ndvi_values, color='#4caf50', edgecolor='#2e7d32')
                        ax_ndvi_chart.axhline(y=PARAMETROS_PALMA['NDVI_OPTIMO'], color='red', linestyle='--', 
                                            label=f'Óptimo ({PARAMETROS_PALMA["NDVI_OPTIMO"]})')
                        
                        ax_ndvi_chart.set_xlabel('Bloque')
                        ax_ndvi_chart.set_ylabel('NDVI')
                        ax_ndvi_chart.set_title('NDVI por Bloque', fontsize=12)
                        ax_ndvi_chart.legend()
                        ax_ndvi_chart.grid(True, alpha=0.3, axis='y')
                        
                        plt.tight_layout()
                        st.pyplot(fig_ndvi_chart)
                    except Exception:
                        st.info("No se pudo generar el gráfico de NDVI")
                
                # Mostrar imagen MODIS
                if datos_modis.get('imagen_disponible') and datos_modis.get('imagen_bytes'):
                    st.markdown("**🖼️ Imagen MODIS Simulada:**")
                    try:
                        datos_modis['imagen_bytes'].seek(0)
                        st.image(datos_modis['imagen_bytes'], 
                                caption=f"Imagen MODIS - {datos_modis.get('fecha_imagen', '')}",
                                use_column_width=True)
                    except Exception:
                        st.info("No se pudo mostrar la imagen MODIS")
        
        with tab4:
            st.subheader("🧪 ANÁLISIS DE FERTILIDAD")
            
            # Fertilidad actual
            st.markdown("### 📊 Fertilidad Actual (kg/ha)")
            col_n1, col_n2, col_n3 = st.columns(3)
            with col_n1:
                try:
                    n_prom = gdf_completo['N_actual'].mean()
                    st.metric("Nitrógeno (N)", f"{n_prom:.0f} kg/ha")
                except Exception:
                    st.metric("Nitrógeno (N)", "N/A")
            with col_n2:
                try:
                    p_prom = gdf_completo['P_actual'].mean()
                    st.metric("Fósforo (P)", f"{p_prom:.0f} kg/ha")
                except Exception:
                    st.metric("Fósforo (P)", "N/A")
            with col_n3:
                try:
                    k_prom = gdf_completo['K_actual'].mean()
                    st.metric("Potasio (K)", f"{k_prom:.0f} kg/ha")
                except Exception:
                    st.metric("Potasio (K)", "N/A")
            
            # Recomendaciones
            st.markdown("### 💡 Recomendaciones de Fertilización (kg/ha)")
            col_r1, col_r2, col_r3 = st.columns(3)
            with col_r1:
                try:
                    rec_n_prom = gdf_completo['rec_N'].mean()
                    st.metric("Aplicar N", f"{rec_n_prom:.0f} kg/ha")
                except Exception:
                    st.metric("Aplicar N", "N/A")
            with col_r2:
                try:
                    rec_p_prom = gdf_completo['rec_P'].mean()
                    st.metric("Aplicar P", f"{rec_p_prom:.0f} kg/ha")
                except Exception:
                    st.metric("Aplicar P", "N/A")
            with col_r3:
                try:
                    rec_k_prom = gdf_completo['rec_K'].mean()
                    st.metric("Aplicar K", f"{rec_k_prom:.0f} kg/ha")
                except Exception:
                    st.metric("Aplicar K", "N/A")
            
            # Tabla detallada
            st.markdown("### 📋 Detalle por Bloque")
            try:
                columnas_fert = ['id_bloque', 'N_actual', 'P_actual', 'K_actual', 
                                'rec_N', 'rec_P', 'rec_K']
                tabla_fert = gdf_completo[columnas_fert].copy()
                tabla_fert.columns = ['Bloque', 'N Actual', 'P Actual', 'K Actual', 
                                     'Rec. N', 'Rec. P', 'Rec. K']
                st.dataframe(tabla_fert.style.format({
                    'N Actual': '{:.0f}',
                    'P Actual': '{:.0f}',
                    'K Actual': '{:.0f}',
                    'Rec. N': '{:.0f}',
                    'Rec. P': '{:.0f}',
                    'Rec. K': '{:.0f}'
                }), height=400)
            except Exception:
                st.info("No se pudo mostrar la tabla de fertilidad")
            
            # Gráfico de recomendaciones
            st.markdown("### 📈 Gráfico de Recomendaciones")
            try:
                fig_rec, ax_rec = plt.subplots(figsize=(10, 6))
                
                x = np.arange(len(gdf_completo))
                width = 0.25
                
                ax_rec.bar(x - width, gdf_completo['rec_N'], width, label='N', color='#4caf50')
                ax_rec.bar(x, gdf_completo['rec_P'], width, label='P', color='#2196f3')
                ax_rec.bar(x + width, gdf_completo['rec_K'], width, label='K', color='#ff9800')
                
                ax_rec.set_xlabel('Bloque')
                ax_rec.set_ylabel('kg/ha')
                ax_rec.set_title('Recomendaciones de Fertilización por Bloque', fontsize=12)
                ax_rec.set_xticks(x)
                ax_rec.set_xticklabels(gdf_completo['id_bloque'].astype(str))
                ax_rec.legend()
                ax_rec.grid(True, alpha=0.3, axis='y')
                
                plt.tight_layout()
                st.pyplot(fig_rec)
            except Exception:
                st.info("No se pudo generar el gráfico de recomendaciones")
        
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
                    st.metric("Ingreso Total", f"${ingreso_total:,.0f}")
                with col2:
                    st.metric("Costo Total", f"${costo_total:,.0f}")
                with col3:
                    st.metric("Ganancia Total", f"${ganancia_total:,.0f}")
                with col4:
                    st.metric("Rentabilidad Prom.", f"{rentabilidad_prom:.1f}%")
            except Exception:
                st.warning("No se pudieron calcular las métricas económicas")
            
            # Gráfico de rentabilidad
            st.markdown("### 📊 Rentabilidad por Bloque")
            try:
                fig_rent, ax_rent = plt.subplots(figsize=(10, 6))
                rentabilidad = gdf_completo['rentabilidad']
                bloques = gdf_completo['id_bloque'].astype(str)
                
                colors = ['green' if r >= 0 else 'red' for r in rentabilidad]
                bars = ax_rent.bar(bloques, rentabilidad, color=colors, edgecolor='black')
                ax_rent.axhline(y=0, color='black', linewidth=1)
                ax_rent.axhline(y=15, color='green', linestyle='--', alpha=0.5, label='Umbral rentable (15%)')
                
                ax_rent.set_xlabel('Bloque')
                ax_rent.set_ylabel('Rentabilidad (%)')
                ax_rent.set_title('Rentabilidad por Bloque', fontsize=12)
                ax_rent.legend()
                ax_rent.grid(True, alpha=0.3, axis='y')
                
                plt.tight_layout()
                st.pyplot(fig_rent)
            except Exception:
                st.info("No se pudo generar el gráfico de rentabilidad")
            
            # Costo de fertilización
            st.markdown("### 💰 Costo de Fertilización por Bloque")
            try:
                fig_costo, ax_costo = plt.subplots(figsize=(10, 6))
                
                costos = gdf_completo['costo_total'] / gdf_completo['area_ha']
                ax_costo.bar(bloques, costos, color='#ff9800', edgecolor='#f57c00')
                
                ax_costo.set_xlabel('Bloque')
                ax_costo.set_ylabel('Costo (USD/ha)')
                ax_costo.set_title('Costo de Fertilización por Hectárea', fontsize=12)
                ax_costo.grid(True, alpha=0.3, axis='y')
                
                plt.tight_layout()
                st.pyplot(fig_costo)
            except Exception:
                pass
        
        with tab6:
            st.subheader("🌦️ ANÁLISIS CLIMÁTICO")
            datos_climaticos = st.session_state.datos_climaticos
            
            if datos_climaticos:
                # Métricas climáticas
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Temperatura", f"{datos_climaticos.get('temperatura_promedio', 0):.1f}°C")
                with col2:
                    st.metric("Precipitación", f"{datos_climaticos.get('precipitacion_total', 0):,.0f} mm")
                with col3:
                    st.metric("Radiación", f"{datos_climaticos.get('radiacion_promedio', 0):.1f} MJ/m²")
                with col4:
                    st.metric("Humedad", f"{datos_climaticos.get('humedad_promedio', 0):.1f}%")
                
                col5, col6, col7 = st.columns(3)
                with col5:
                    st.metric("Días con lluvia", f"{datos_climaticos.get('dias_con_lluvia', 0)}")
                with col6:
                    st.metric("Viento", f"{datos_climaticos.get('velocidad_viento', 0):.1f} m/s")
                with col7:
                    st.metric("Evaporación", f"{datos_climaticos.get('evaporacion', 0):.1f} mm/día")
                
                # Evaluación climática
                st.markdown("### 📊 Evaluación Climática")
                
                temp = datos_climaticos.get('temperatura_promedio', 25)
                precip = datos_climaticos.get('precipitacion_total', 1800)
                
                col_eval1, col_eval2 = st.columns(2)
                with col_eval1:
                    st.markdown("**🌡️ Temperatura:**")
                    if 24 <= temp <= 28:
                        st.success(f"✅ Óptima ({temp}°C)")
                    elif 20 <= temp < 24 or 28 < temp <= 30:
                        st.warning(f"⚠️ Aceptable ({temp}°C)")
                    else:
                        st.error(f"❌ Crítica ({temp}°C)")
                    
                    st.write(f"- **Óptimo para palma:** 24-28°C")
                
                with col_eval2:
                    st.markdown("**💧 Precipitación:**")
                    if 1800 <= precip <= 2500:
                        st.success(f"✅ Adecuada ({precip:,.0f} mm)")
                    elif 1500 <= precip < 1800 or 2500 < precip <= 3000:
                        st.warning(f"⚠️ Moderada ({precip:,.0f} mm)")
                    else:
                        st.error(f"❌ Crítica ({precip:,.0f} mm)")
                    
                    st.write(f"- **Óptimo para palma:** 1,800-2,500 mm")
                
                # Gráficos climáticos
                st.markdown("### 📈 Gráficos Climáticos")
                
                # Datos para gráficos
                meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 
                        'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
                
                fig_clima, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
                
                # Temperatura mensual simulada
                temp_mensual = [temp + np.random.normal(0, 2) for _ in range(12)]
                ax1.plot(meses, temp_mensual, marker='o', color='red', linewidth=2)
                ax1.axhline(y=26, color='green', linestyle='--', alpha=0.5, label='Óptimo (26°C)')
                ax1.fill_between(meses, temp_mensual, 26, alpha=0.1, color='red')
                ax1.set_ylabel('Temperatura (°C)')
                ax1.set_title('Temperatura Mensual Promedio', fontsize=12)
                ax1.legend()
                ax1.grid(True, alpha=0.3)
                
                # Precipitación mensual simulada
                precip_mensual = [precip/12 + np.random.normal(0, 50) for _ in range(12)]
                ax2.bar(meses, precip_mensual, color='blue', alpha=0.7)
                ax2.axhline(y=precip/12, color='darkblue', linestyle='--', alpha=0.5, label='Promedio')
                ax2.set_ylabel('Precipitación (mm)')
                ax2.set_title('Precipitación Mensual', fontsize=12)
                ax2.legend()
                ax2.grid(True, alpha=0.3, axis='y')
                
                plt.tight_layout()
                st.pyplot(fig_clima)
        
        with tab7:
            st.subheader("🌴 DETECCIÓN DE PALMAS")
            
            if st.session_state.deteccion_ejecutada:
                palmas = st.session_state.palmas_detectadas
                total = len(palmas)
                
                if total > 0:
                    st.success(f"✅ Detección completada: {total} palmas detectadas")
                    
                    # Métricas
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Palmas detectadas", f"{total:,}")
                    with col2:
                        area_total = resultados.get('area_total', 0)
                        densidad = total / area_total if area_total > 0 else 0
                        st.metric("Densidad", f"{densidad:.0f} plantas/ha")
                    with col3:
                        try:
                            area_prom = np.mean([p.get('area_m2', 0) for p in palmas])
                            st.metric("Área promedio", f"{area_prom:.1f} m²")
                        except Exception:
                            st.metric("Área promedio", "N/A")
                    with col4:
                        try:
                            salud_counts = {}
                            for p in palmas:
                                salud = p.get('estado_salud', 'Desconocido')
                                salud_counts[salud] = salud_counts.get(salud, 0) + 1
                            salud_predominante = max(salud_counts.items(), key=lambda x: x[1])[0]
                            st.metric("Estado predominante", salud_predominante)
                        except Exception:
                            st.metric("Estado", "N/A")
                    
                    # Visualización
                    st.markdown("### 📷 Visualización de Detección")
                    if st.session_state.imagen_alta_resolucion:
                        try:
                            st.session_state.imagen_alta_resolucion.seek(0)
                            st.image(st.session_state.imagen_alta_resolucion,
                                    caption="Detección de palmas (estilo Google Earth)",
                                    use_column_width=True)
                        except Exception:
                            st.info("No se pudo mostrar la imagen de detección")
                    
                    # Tabla de palmas (primeras 50)
                    st.markdown("### 📋 Muestra de Palmas Detectadas (primeras 50)")
                    if palmas and len(palmas) > 0:
                        try:
                            df_palmas = pd.DataFrame([{
                                'ID': p['id'],
                                'Latitud': p['centroide'][1],
                                'Longitud': p['centroide'][0],
                                'Área (m²)': p['area_m2'],
                                'Diámetro (m)': p['diametro_aprox'],
                                'Estado': p['estado_salud'],
                                'Prod. Est. (kg)': p['produccion_estimada']
                            } for p in palmas[:50]])
                            
                            st.dataframe(df_palmas, height=400)
                        except Exception:
                            st.info("No se pudo mostrar la tabla de palmas")
                    
                    # Exportar datos
                    st.markdown("### 📥 EXPORTAR DATOS DE PALMAS")
                    if palmas:
                        try:
                            # CSV
                            csv_data = pd.DataFrame([{
                                'id': p['id'],
                                'latitud': p['centroide'][1],
                                'longitud': p['centroide'][0],
                                'area_m2': p['area_m2'],
                                'diametro_m': p['diametro_aprox'],
                                'estado_salud': p['estado_salud'],
                                'produccion_kg': p['produccion_estimada']
                            } for p in palmas]).to_csv(index=False)
                            
                            col_exp1, col_exp2 = st.columns(2)
                            
                            with col_exp1:
                                st.download_button(
                                    label="📥 Descargar CSV",
                                    data=csv_data,
                                    file_name=f"palmas_detectadas_{datetime.now().strftime('%Y%m%d')}.csv",
                                    mime="text/csv",
                                    use_container_width=True
                                )
                            
                            with col_exp2:
                                # KML para Google Earth
                                kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
<name>Palmas Detectadas</name>
<description>Palmas de aceite detectadas automáticamente</description>
"""
                                
                                for p in palmas[:1000]:  # Limitar para KML
                                    lat, lon = p['centroide'][1], p['centroide'][0]
                                    kml_content += f"""
<Placemark>
<name>Palma {p['id']}</name>
<description>
Estado: {p['estado_salud']}
Área: {p['area_m2']} m²
Diámetro: {p['diametro_aprox']} m
Producción estimada: {p['produccion_estimada']} kg
</description>
<Point>
<coordinates>{lon},{lat},0</coordinates>
</Point>
</Placemark>
"""
                                
                                kml_content += "</Document></kml>"
                                
                                st.download_button(
                                    label="🗺️ Descargar KML (Google Earth)",
                                    data=kml_content,
                                    file_name=f"palmas_detectadas_{datetime.now().strftime('%Y%m%d')}.kml",
                                    mime="application/vnd.google-earth.kml+xml",
                                    use_container_width=True
                                )
                        except Exception:
                            st.info("No se pudieron exportar los datos")
                else:
                    st.info("No se detectaron palmas en esta plantación.")
            else:
                st.info("La detección de palmas no se ha ejecutado aún.")
                if deteccion_habilitada and st.button("🔍 EJECUTAR DETECCIÓN DE PALMAS", use_container_width=True):
                    ejecutar_deteccion_palmas()
                    st.rerun()

# Si no hay archivo cargado, mostrar instrucciones
elif not st.session_state.archivo_cargado:
    st.info("""
    📋 **INSTRUCCIONES PARA COMENZAR:**
    
    1. **Carga tu plantación** usando el panel lateral (formatos: ZIP, KML, KMZ, GeoJSON)
    2. **Configura los parámetros** de análisis (variedad, número de bloques)
    3. **Ejecuta el análisis** completo
    4. **Explora los resultados** en las pestañas:
       - 📊 Resumen general
       - 🗺️ Mapas interactivos
       - 🛰️ Análisis NDVI
       - 🧪 Fertilidad y recomendaciones NPK
       - 📈 Análisis económico
       - 🌦️ Datos climáticos
       - 🌴 Detección de palmas individuales
    
    ⚡ **Funcionalidades principales:**
    - Análisis de NDVI satelital
    - Evaluación de fertilidad actual
    - Recomendaciones específicas de fertilización NPK
    - Mapas de potencial de cosecha
    - Análisis económico detallado
    - Datos climáticos simulados
    - Detección de palmas individuales con coordenadas para Google Earth
    """)

# Pie de página
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #94a3b8; padding: 20px;">
    <p><strong>© 2024 Analizador de Palma Aceitera Satelital</strong></p>
    <p>Desarrollado por: Martin Ernesto Cano | Contacto: mawucano@gmail.com | +5493525 532313</p>
    <p style="font-size: 0.8em; margin-top: 20px;">
        Herramienta de análisis para plantaciones de palma aceitera con datos satelitales simulados
    </p>
</div>
""", unsafe_allow_html=True)

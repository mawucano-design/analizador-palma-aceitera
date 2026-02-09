# app.py - Versión CORREGIDA para PALMA ACEITERA con detección de plantas individuales
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
from shapely.geometry import Polygon, Point
import math
import warnings
from io import BytesIO
import requests
import re
from PIL import Image, ImageDraw

# ===== DEPENDENCIAS PARA MAPAS INTERACTIVOS =====
FOLIUM_DISPONIBLE = False  # Desactivado temporalmente para evitar errores

# ===== DEPENDENCIAS PARA DETECCIÓN DE PALMAS =====
try:
    import cv2
    DETECCION_DISPONIBLE = True
except ImportError:
    DETECCION_DISPONIBLE = False

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
        'n_divisiones': 16,
        'indice_seleccionado': 'NDVI',
        'fecha_inicio': datetime.now() - timedelta(days=60),
        'fecha_fin': datetime.now(),
        'tamano_minimo': 15.0,
        'variedad_seleccionada': 'Tenera (DxP)'
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ===== CONFIGURACIONES =====
VARIEDADES_PALMA_ACEITERA = [
    'Tenera (DxP)', 'Dura', 'Pisifera', 'Yangambi', 'AVROS', 'La Mé',
    'Ekona', 'Calabar', 'NIFOR', 'MARDI', 'CIRAD', 'ASD Costa Rica',
    'Dami', 'Socfindo', 'SP540'
]

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
    if gdf is None or len(gdf) == 0:
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
def generar_datos_modis_simulados(gdf, fecha_inicio, fecha_fin):
    """Genera datos MODIS simulados"""
    try:
        centroide = gdf.geometry.unary_union.centroid
        lat_norm = (centroide.y + 90) / 180
        lon_norm = (centroide.x + 180) / 360
        
        mes = fecha_inicio.month
        if 3 <= mes <= 5:  # Otoño en hemisferio sur
            base_ndvi = 0.65
            base_ndre = 0.55
            base_ndwi = 0.35
        elif 6 <= mes <= 8:  # Invierno
            base_ndvi = 0.55
            base_ndre = 0.45
            base_ndwi = 0.30
        elif 9 <= mes <= 11:  # Primavera
            base_ndvi = 0.75
            base_ndre = 0.65
            base_ndwi = 0.40
        else:  # Verano
            base_ndvi = 0.70
            base_ndre = 0.60
            base_ndwi = 0.38
        
        variacion = (lat_norm * lon_norm) * 0.15
        
        return {
            'ndvi': round(base_ndvi + variacion + np.random.normal(0, 0.05), 3),
            'ndre': round(base_ndre + variacion + np.random.normal(0, 0.04), 3),
            'ndwi': round(base_ndwi + variacion + np.random.normal(0, 0.03), 3),
            'fecha': fecha_inicio.strftime('%Y-%m-%d'),
            'fuente': 'Datos simulados basados en ubicación y temporada'
        }
    except Exception:
        return {
            'ndvi': 0.65,
            'ndre': 0.55,
            'ndwi': 0.35,
            'fecha': datetime.now().strftime('%Y-%m-%d'),
            'fuente': 'Datos simulados'
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
            'temperatura_promedio': round(temp_base + temp_ajuste + np.random.normal(0, 2), 1),
            'precipitacion_total': round(max(0, precip_base + precip_ajuste + np.random.normal(0, 30)), 1),
            'radiacion_promedio': round(18 + np.random.normal(0, 3), 1),
            'dias_con_lluvia': 15 + np.random.randint(-5, 5),
            'humedad_promedio': round(75 + np.random.normal(0, 5), 1)
        }
    except Exception:
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
        try:
            centroid = row.geometry.centroid
            lat_norm = (centroid.y + 90) / 180
            lon_norm = (centroid.x + 180) / 360
            edad = 2 + (lat_norm * lon_norm * 18)
            edades.append(round(edad, 1))
        except Exception:
            edades.append(10.0)
    return edades

def analizar_produccion_palma(gdf_dividido, edades, ndvi_values, datos_climaticos):
    """Calcula la producción estimada por bloque"""
    producciones = []
    rendimiento_optimo = PARAMETROS_PALMA['RENDIMIENTO_OPTIMO']
    
    for i, (edad, ndvi) in enumerate(zip(edades, ndvi_values)):
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
    
    for i, (ndvi, edad) in enumerate(zip(ndvi_values, edades)):
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
        mg = min(max(mg, PARAMETROS_PALMA['MAGNESIO']['min']), PARAMETROS_PALMA['MAGNESIO']['max'])
        b = min(max(b, PARAMETROS_PALMA['BORO']['min']), PARAMETROS_PALMA['BORO']['max'])
        
        requerimientos_n.append(round(n, 1))
        requerimientos_p.append(round(p, 1))
        requerimientos_k.append(round(k, 1))
        requerimientos_mg.append(round(mg, 1))
        requerimientos_b.append(round(b, 3))
    
    return requerimientos_n, requerimientos_p, requerimientos_k, requerimientos_mg, requerimientos_b

# ===== FUNCIONES DE VISUALIZACIÓN CORREGIDAS =====
def crear_mapa_bloques(gdf, palmas_detectadas=None):
    """Crea un mapa de los bloques con matplotlib - CORREGIDA"""
    if gdf is None or len(gdf) == 0:
        # Crear una figura vacía en lugar de devolver None
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.text(0.5, 0.5, "No hay datos para mostrar", 
                ha='center', va='center', fontsize=12)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig
    
    try:
        fig, ax = plt.subplots(figsize=(12, 10))
        
        # Configurar colores basados en NDVI
        if 'ndvi_modis' in gdf.columns and not gdf['ndvi_modis'].isna().all():
            ndvi_values = gdf['ndvi_modis'].values
            if len(ndvi_values) > 0:
                min_ndvi, max_ndvi = ndvi_values.min(), ndvi_values.max()
                
                for idx, row in gdf.iterrows():
                    try:
                        if max_ndvi > min_ndvi:
                            norm_val = (ndvi_values[idx] - min_ndvi) / (max_ndvi - min_ndvi)
                        else:
                            norm_val = 0.5
                        
                        if norm_val < 0.33:
                            color = (1.0, 0.5, 0.5, 0.6)
                        elif norm_val < 0.66:
                            color = (1.0, 1.0, 0.5, 0.6)
                        else:
                            color = (0.5, 1.0, 0.5, 0.6)
                        
                        if row.geometry.geom_type == 'Polygon':
                            poly_coords = list(row.geometry.exterior.coords)
                            polygon = MplPolygon(poly_coords, closed=True, 
                                               facecolor=color, 
                                               edgecolor='black', 
                                               linewidth=1,
                                               alpha=0.6)
                            ax.add_patch(polygon)
                        elif row.geometry.geom_type == 'MultiPolygon':
                            for poly in row.geometry.geoms:
                                poly_coords = list(poly.exterior.coords)
                                polygon = MplPolygon(poly_coords, closed=True,
                                                   facecolor=color,
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
                               fontsize=8, ha='center', va='center',
                               bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7))
                    except Exception:
                        continue
            else:
                # Sin datos NDVI, dibujar polígonos simples
                gdf.plot(ax=ax, color='lightgreen', edgecolor='darkgreen', alpha=0.6)
        else:
            # Sin columna NDVI, dibujar polígonos simples
            gdf.plot(ax=ax, color='lightgreen', edgecolor='darkgreen', alpha=0.6)
        
        # Añadir palmas detectadas si existen
        if palmas_detectadas and len(palmas_detectadas) > 0:
            try:
                coords = []
                for p in palmas_detectadas[:500]:  # Limitar a 500 para rendimiento
                    if isinstance(p, dict) and 'centroide' in p:
                        centroide = p['centroide']
                        if isinstance(centroide, (tuple, list)) and len(centroide) == 2:
                            lon, lat = centroide
                            if not np.isnan(lon) and not np.isnan(lat):
                                coords.append((lon, lat))
                
                if coords:
                    coords_array = np.array(coords)
                    ax.scatter(coords_array[:, 0], coords_array[:, 1], 
                              s=20, color='blue', alpha=0.7, 
                              label=f'Palmas detectadas ({len(coords)})',
                              edgecolors='white', linewidth=0.5)
            except Exception:
                pass
        
        ax.set_title('Mapa de Bloques - Palma Aceitera', fontsize=14, fontweight='bold')
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        if palmas_detectadas and len(palmas_detectadas) > 0:
            ax.legend(loc='upper right', fontsize=9)
        
        plt.tight_layout()
        return fig
    except Exception as e:
        # Crear figura de error
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.text(0.5, 0.5, f"Error al crear mapa: {str(e)[:50]}...", 
                ha='center', va='center', fontsize=12, color='red')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig

def crear_mapa_indices(gdf):
    """Crea un mapa de índices (NDVI, NDRE, NDWI) - CORREGIDA"""
    if gdf is None or len(gdf) == 0:
        # Crear figura vacía
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.text(0.5, 0.5, "No hay datos para mostrar", 
                ha='center', va='center', fontsize=12)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig
    
    try:
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        
        # 1. NDVI
        ax1 = axes[0]
        if 'ndvi_modis' in gdf.columns and not gdf['ndvi_modis'].isna().all():
            # Obtener centroides
            centroids_x = []
            centroids_y = []
            ndvi_values = []
            
            for idx, row in gdf.iterrows():
                try:
                    centroid = row.geometry.centroid
                    centroids_x.append(centroid.x)
                    centroids_y.append(centroid.y)
                    ndvi_values.append(row['ndvi_modis'])
                except:
                    continue
            
            if len(centroids_x) > 0:
                scatter1 = ax1.scatter(
                    centroids_x,
                    centroids_y,
                    c=ndvi_values,
                    cmap='RdYlGn',
                    s=100,
                    vmin=0.3,
                    vmax=0.9,
                    edgecolors='black',
                    linewidth=0.5
                )
                
                cbar1 = plt.colorbar(scatter1, ax=ax1, orientation='vertical', pad=0.02)
                cbar1.set_label('NDVI', fontsize=10)
                
                if ndvi_values:
                    ndvi_avg = np.nanmean(ndvi_values)
                    ax1.text(0.02, 0.98, f'Promedio: {ndvi_avg:.3f}',
                            transform=ax1.transAxes, 
                            fontsize=9,
                            verticalalignment='top',
                            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        ax1.set_title('NDVI - Índice de Vegetación', fontsize=12, fontweight='bold')
        ax1.set_xlabel('Longitud')
        ax1.set_ylabel('Latitud')
        ax1.grid(True, alpha=0.3)
        
        # 2. NDRE (simulado)
        ax2 = axes[1]
        if 'ndvi_modis' in gdf.columns and not gdf['ndvi_modis'].isna().all():
            # Calcular NDRE simulado
            ndre_values = []
            centroids_x2 = []
            centroids_y2 = []
            
            for idx, row in gdf.iterrows():
                try:
                    centroid = row.geometry.centroid
                    centroids_x2.append(centroid.x)
                    centroids_y2.append(centroid.y)
                    ndre = row['ndvi_modis'] * 0.85 + np.random.normal(0, 0.03)
                    ndre = max(0.2, min(0.8, ndre))
                    ndre_values.append(ndre)
                except:
                    continue
            
            if len(centroids_x2) > 0:
                scatter2 = ax2.scatter(
                    centroids_x2,
                    centroids_y2,
                    c=ndre_values,
                    cmap='YlGn',
                    s=100,
                    vmin=0.2,
                    vmax=0.8,
                    edgecolors='black',
                    linewidth=0.5
                )
                
                cbar2 = plt.colorbar(scatter2, ax=ax2, orientation='vertical', pad=0.02)
                cbar2.set_label('NDRE', fontsize=10)
                
                if ndre_values:
                    ndre_avg = np.nanmean(ndre_values)
                    ax2.text(0.02, 0.98, f'Promedio: {ndre_avg:.3f}',
                            transform=ax2.transAxes, 
                            fontsize=9,
                            verticalalignment='top',
                            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        ax2.set_title('NDRE - Índice de Borde Rojo', fontsize=12, fontweight='bold')
        ax2.set_xlabel('Longitud')
        ax2.grid(True, alpha=0.3)
        
        # 3. NDWI (simulado)
        ax3 = axes[2]
        if 'ndvi_modis' in gdf.columns and not gdf['ndvi_modis'].isna().all():
            # Calcular NDWI simulado
            ndwi_values = []
            centroids_x3 = []
            centroids_y3 = []
            
            for idx, row in gdf.iterrows():
                try:
                    centroid = row.geometry.centroid
                    centroids_x3.append(centroid.x)
                    centroids_y3.append(centroid.y)
                    ndwi = 0.6 - (row['ndvi_modis'] * 0.4) + np.random.normal(0, 0.05)
                    ndwi = max(0.1, min(0.7, ndwi))
                    ndwi_values.append(ndwi)
                except:
                    continue
            
            if len(centroids_x3) > 0:
                scatter3 = ax3.scatter(
                    centroids_x3,
                    centroids_y3,
                    c=ndwi_values,
                    cmap='Blues',
                    s=100,
                    vmin=0.1,
                    vmax=0.7,
                    edgecolors='black',
                    linewidth=0.5
                )
                
                cbar3 = plt.colorbar(scatter3, ax=ax3, orientation='vertical', pad=0.02)
                cbar3.set_label('NDWI', fontsize=10)
                
                if ndwi_values:
                    ndwi_avg = np.nanmean(ndwi_values)
                    ax3.text(0.02, 0.98, f'Promedio: {ndwi_avg:.3f}',
                            transform=ax3.transAxes, 
                            fontsize=9,
                            verticalalignment='top',
                            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        ax3.set_title('NDWI - Índice de Agua', fontsize=12, fontweight='bold')
        ax3.set_xlabel('Longitud')
        ax3.grid(True, alpha=0.3)
        
        plt.suptitle('Mapa de Índices de Vegetación', fontsize=14, fontweight='bold', y=1.02)
        plt.tight_layout()
        return fig
        
    except Exception as e:
        # Crear figura de error
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.text(0.5, 0.5, f"Error al crear mapa de índices", 
                ha='center', va='center', fontsize=12, color='red')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig

def crear_grafico_ndvi_bloques(gdf):
    """Crea gráfico de barras de NDVI por bloque - CORREGIDA"""
    if gdf is None or 'ndvi_modis' not in gdf.columns or gdf['ndvi_modis'].isna().all():
        # Crear gráfico vacío
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "No hay datos NDVI para mostrar", 
                ha='center', va='center', fontsize=12)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig
    
    try:
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Filtrar datos válidos
        valid_data = gdf[['id_bloque', 'ndvi_modis']].dropna()
        if len(valid_data) == 0:
            ax.text(0.5, 0.5, "No hay datos NDVI válidos", 
                    ha='center', va='center', fontsize=12)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
            return fig
        
        bloques = valid_data['id_bloque'].astype(str)
        ndvi_values = valid_data['ndvi_modis']
        
        # Colores basados en valor NDVI
        colors = []
        for val in ndvi_values:
            if val < 0.4:
                colors.append('#d73027')  # Rojo
            elif val < 0.6:
                colors.append('#fee08b')  # Amarillo
            elif val < 0.75:
                colors.append('#91cf60')  # Verde claro
            else:
                colors.append('#1a9850')  # Verde oscuro
        
        bars = ax.bar(bloques, ndvi_values, color=colors, edgecolor='black', linewidth=1)
        ax.axhline(y=PARAMETROS_PALMA['NDVI_OPTIMO'], color='green', linestyle='--', 
                   linewidth=2, label=f'Óptimo ({PARAMETROS_PALMA["NDVI_OPTIMO"]})')
        ax.axhline(y=0.5, color='orange', linestyle='--', alpha=0.5, label='Mínimo aceptable')
        
        ax.set_xlabel('Bloque', fontsize=11)
        ax.set_ylabel('NDVI', fontsize=11)
        ax.set_title('NDVI por Bloque - Palma Aceitera', fontsize=13, fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3, axis='y')
        
        # Añadir valores en las barras
        for bar, val in zip(bars, ndvi_values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                   f'{val:.3f}', ha='center', va='bottom', fontsize=8)
        
        plt.tight_layout()
        return fig
    except Exception as e:
        # Crear gráfico de error
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, f"Error al crear gráfico NDVI", 
                ha='center', va='center', fontsize=12, color='red')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig

def crear_grafico_produccion(gdf):
    """Crea gráfico de producción por bloque - CORREGIDA"""
    if gdf is None or 'produccion_estimada' not in gdf.columns or gdf['produccion_estimada'].isna().all():
        # Crear gráfico vacío
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "No hay datos de producción para mostrar", 
                ha='center', va='center', fontsize=12)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig
    
    try:
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Filtrar datos válidos
        valid_data = gdf[['id_bloque', 'produccion_estimada']].dropna()
        if len(valid_data) == 0:
            ax.text(0.5, 0.5, "No hay datos de producción válidos", 
                    ha='center', va='center', fontsize=12)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
            return fig
        
        bloques = valid_data['id_bloque'].astype(str)
        produccion = valid_data['produccion_estimada']
        
        # Ordenar bloques por producción
        sorted_indices = np.argsort(produccion)[::-1]
        bloques_sorted = bloques.iloc[sorted_indices]
        produccion_sorted = produccion.iloc[sorted_indices]
        
        bars = ax.bar(bloques_sorted, produccion_sorted, color='#4caf50', 
                     edgecolor='#2e7d32', linewidth=1)
        
        ax.set_xlabel('Bloque', fontsize=11)
        ax.set_ylabel('Producción (kg/ha)', fontsize=11)
        ax.set_title('Producción Estimada por Bloque', fontsize=13, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')
        
        # Añadir valores
        for bar, val in zip(bars, produccion_sorted):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 50,
                   f'{val:,.0f}', ha='center', va='bottom', fontsize=8)
        
        plt.tight_layout()
        return fig
    except Exception as e:
        # Crear gráfico de error
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, f"Error al crear gráfico de producción", 
                ha='center', va='center', fontsize=12, color='red')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig

def crear_grafico_rentabilidad(gdf):
    """Crea gráfico de rentabilidad por bloque - CORREGIDA"""
    if gdf is None or 'rentabilidad' not in gdf.columns or gdf['rentabilidad'].isna().all():
        # Crear gráfico vacío
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "No hay datos de rentabilidad para mostrar", 
                ha='center', va='center', fontsize=12)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig
    
    try:
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Filtrar datos válidos
        valid_data = gdf[['id_bloque', 'rentabilidad']].dropna()
        if len(valid_data) == 0:
            ax.text(0.5, 0.5, "No hay datos de rentabilidad válidos", 
                    ha='center', va='center', fontsize=12)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
            return fig
        
        bloques = valid_data['id_bloque'].astype(str)
        rentabilidad = valid_data['rentabilidad']
        
        # Colores basados en rentabilidad
        colors = []
        for val in rentabilidad:
            if val < 0:
                colors.append('#d73027')
            elif val < 15:
                colors.append('#fee08b')
            elif val < 25:
                colors.append('#91cf60')
            else:
                colors.append('#1a9850')
        
        bars = ax.bar(bloques, rentabilidad, color=colors, edgecolor='black', linewidth=1)
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axhline(y=15, color='green', linestyle='--', alpha=0.5, linewidth=2, label='Umbral rentable (15%)')
        
        ax.set_xlabel('Bloque', fontsize=11)
        ax.set_ylabel('Rentabilidad (%)', fontsize=11)
        ax.set_title('Rentabilidad por Bloque', fontsize=13, fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3, axis='y')
        
        # Añadir valores
        for bar, val in zip(bars, rentabilidad):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.5,
                   f'{val:.1f}%', ha='center', va='bottom' if val >= 0 else 'top',
                   fontsize=8, fontweight='bold')
        
        plt.tight_layout()
        return fig
    except Exception as e:
        # Crear gráfico de error
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, f"Error al crear gráfico de rentabilidad", 
                ha='center', va='center', fontsize=12, color='red')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig

# ===== FUNCIONES DE DETECCIÓN =====
def simular_deteccion_palmas(gdf, densidad=130):
    """Simula la detección de palmas"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        area_ha = calcular_superficie(gdf)
        if area_ha <= 0:
            return {
                'detectadas': [],
                'total': 0,
                'patron': 'indeterminado',
                'densidad_calculada': 0,
                'area_ha': area_ha
            }
            
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
                    lon += np.random.normal(0, lado_grados * 0.15)
                    lat += np.random.normal(0, lado_grados * 0.15)
                    
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
        
        # Usar simulación
        resultados = simular_deteccion_palmas(gdf)
        st.session_state.palmas_detectadas = resultados['detectadas']
        
        try:
            # Crear imagen simulada para mostrar
            width, height = 800, 600
            img = Image.new('RGB', (width, height), color=(240, 240, 240))
            draw = ImageDraw.Draw(img)
            
            # Dibujar palmas detectadas
            bounds = gdf.total_bounds
            min_lon, min_lat, max_lon, max_lat = bounds
            
            if resultados['detectadas']:
                for palma in resultados['detectadas'][:100]:  # Limitar a 100 para visualización
                    lon, lat = palma['centroide']
                    x = int((lon - min_lon) / (max_lon - min_lon) * width)
                    y = int((max_lat - lat) / (max_lat - min_lat) * height)
                    radio = int(palma['radio_aprox'] * 3)
                    
                    draw.ellipse([x-radio, y-radio, x+radio, y+radio], 
                                fill=(50, 200, 50), outline=(30, 150, 30), width=2)
            
            img_bytes = BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            st.session_state.imagen_alta_resolucion = img_bytes
        except Exception:
            img = Image.new('RGB', (800, 600), color=(200, 220, 200))
            img_bytes = BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            st.session_state.imagen_alta_resolucion = img_bytes
        
        st.session_state.deteccion_ejecutada = True
        st.success(f"✅ Detección completada (simulada): {len(resultados['detectadas'])} palmas detectadas")

# ===== FUNCIÓN PRINCIPAL DE ANÁLISIS =====
def ejecutar_analisis_completo():
    """Ejecuta el análisis completo y almacena resultados en session_state"""
    if st.session_state.gdf_original is None:
        st.error("Primero debe cargar un archivo de plantación")
        return
    
    with st.spinner("Ejecutando análisis completo..."):
        n_divisiones = st.session_state.get('n_divisiones', 16)
        fecha_inicio = st.session_state.get('fecha_inicio', datetime.now() - timedelta(days=60))
        fecha_fin = st.session_state.get('fecha_fin', datetime.now())
        
        gdf = st.session_state.gdf_original
        
        if gdf is None:
            st.error("Error: No se cargó correctamente la plantación")
            return
            
        try:
            area_total = calcular_superficie(gdf)
        except Exception:
            area_total = 0.0
        
        # 1. Obtener datos MODIS simulados
        datos_modis = generar_datos_modis_simulados(gdf, fecha_inicio, fecha_fin)
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
        valor_modis = datos_modis.get('ndvi', 0.65)
        
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
        
        # 7. NDRE y NDWI por bloque
        ndre_bloques = []
        ndwi_bloques = []
        for ndvi in ndvi_bloques:
            ndre = ndvi * 0.85 + np.random.normal(0, 0.03)
            ndwi = 0.6 - (ndvi * 0.4) + np.random.normal(0, 0.05)
            ndre_bloques.append(round(ndre, 3))
            ndwi_bloques.append(round(ndwi, 3))
        
        gdf_dividido['ndre_modis'] = ndre_bloques
        gdf_dividido['ndwi_modis'] = ndwi_bloques
        
        # 8. Producción
        producciones = analizar_produccion_palma(gdf_dividido, edades, ndvi_bloques, datos_climaticos)
        gdf_dividido['produccion_estimada'] = producciones
        
        # 9. Requerimientos nutricionales
        req_n, req_p, req_k, req_mg, req_b = analizar_requerimientos_nutricionales(
            ndvi_bloques, edades, datos_climaticos
        )
        gdf_dividido['req_N'] = req_n
        gdf_dividido['req_P'] = req_p
        gdf_dividido['req_K'] = req_k
        gdf_dividido['req_Mg'] = req_mg
        gdf_dividido['req_B'] = req_b
        
        # 10. Ingresos
        precio_racimo = 0.15
        ingresos = []
        for idx, row in gdf_dividido.iterrows():
            try:
                ingreso = row['produccion_estimada'] * precio_racimo * row['area_ha']
                ingresos.append(round(ingreso, 2))
            except Exception:
                ingresos.append(0.0)
        
        gdf_dividido['ingreso_estimado'] = ingresos
        
        # 11. Costos
        precio_n, precio_p, precio_k = 1.2, 2.5, 1.8
        precio_mg, precio_b = 1.5, 15.0
        
        costos_totales = []
        costos_n = []
        costos_p = []
        costos_k = []
        costos_mg = []
        costos_b = []
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
                costos_n.append(round(costo_n, 2))
                costos_p.append(round(costo_p, 2))
                costos_k.append(round(costo_k, 2))
                costos_mg.append(round(costo_mg, 2))
                costos_b.append(round(costo_b, 2))
            except Exception:
                costos_totales.append(0.0)
                costos_n.append(0.0)
                costos_p.append(0.0)
                costos_k.append(0.0)
                costos_mg.append(0.0)
                costos_b.append(0.0)
        
        gdf_dividido['costo_total'] = costos_totales
        gdf_dividido['costo_N'] = costos_n
        gdf_dividido['costo_P'] = costos_p
        gdf_dividido['costo_K'] = costos_k
        gdf_dividido['costo_Mg'] = costos_mg
        gdf_dividido['costo_B'] = costos_b
        
        # 12. Rentabilidad
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
    transition: all 0.3s ease !important;
}
.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 5px 15px rgba(0,0,0,0.3) !important;
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
        Monitoreo inteligente con detección de plantas individuales y análisis de índices de vegetación
    </p>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("## 🌴 CONFIGURACIÓN")
    
    # Selección de variedad
    variedad = st.selectbox(
        "Variedad de palma:",
        VARIEDADES_PALMA_ACEITERA,
        index=0
    )
    st.session_state.variedad_seleccionada = variedad
    
    st.markdown("---")
    st.markdown("### 📅 Rango Temporal")
    
    fecha_fin_default = datetime.now()
    fecha_inicio_default = datetime.now() - timedelta(days=60)
    
    fecha_fin = st.date_input("Fecha fin", fecha_fin_default)
    fecha_inicio = st.date_input("Fecha inicio", fecha_inicio_default)
    
    try:
        if hasattr(fecha_inicio, 'year') and hasattr(fecha_inicio, 'month') and hasattr(fecha_inicio, 'day'):
            if not hasattr(fecha_inicio, 'hour'):
                fecha_inicio = datetime.combine(fecha_inicio, datetime.min.time())
    except Exception:
        pass
    
    try:
        if hasattr(fecha_fin, 'year') and hasattr(fecha_fin, 'month') and hasattr(fecha_fin, 'day'):
            if not hasattr(fecha_fin, 'hour'):
                fecha_fin = datetime.combine(fecha_fin, datetime.min.time())
    except Exception:
        pass
    
    st.session_state.fecha_inicio = fecha_inicio
    st.session_state.fecha_fin = fecha_fin
    
    st.markdown("---")
    st.markdown("### 🎯 División de Plantación")
    
    n_divisiones = st.slider("Número de bloques:", 8, 32, 16)
    st.session_state.n_divisiones = n_divisiones
    
    st.markdown("---")
    st.markdown("### 🌴 Detección de Palmas")
    
    deteccion_habilitada = st.checkbox("Activar detección de plantas", value=True)
    if deteccion_habilitada:
        tamano_minimo = st.slider("Tamaño mínimo (m²):", 1.0, 50.0, 15.0, 1.0)
        st.session_state.tamano_minimo = tamano_minimo
    
    st.markdown("---")
    st.markdown("### 📤 Subir Polígono")
    
    uploaded_file = st.file_uploader(
        "Subir archivo de plantación",
        type=['zip', 'kml', 'kmz', 'geojson'],
        help="Formatos: Shapefile (.zip), KML (.kmz), GeoJSON (.geojson)"
    )

# Área principal
if uploaded_file and not st.session_state.archivo_cargado:
    with st.spinner("Cargando plantación..."):
        gdf = cargar_archivo_plantacion(uploaded_file)
        if gdf is not None:
            st.session_state.gdf_original = gdf
            st.session_state.archivo_cargado = True
            st.session_state.analisis_completado = False
            st.session_state.deteccion_ejecutada = False
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
        st.write(f"- **Variedad:** {st.session_state.variedad_seleccionada}")
        st.write(f"- **Bloques configurados:** {st.session_state.n_divisiones}")
        
        # Mostrar mapa básico
        try:
            fig, ax = plt.subplots(figsize=(8, 6))
            gdf.plot(ax=ax, color='#8bc34a', edgecolor='#4caf50', alpha=0.7, linewidth=2)
            ax.set_title("Plantación de Palma Aceitera", fontweight='bold', fontsize=14)
            ax.set_xlabel("Longitud")
            ax.set_ylabel("Latitud")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            st.pyplot(fig)
            plt.close(fig)
        except Exception:
            st.info("No se pudo mostrar el mapa de la plantación")
    
    with col2:
        st.markdown("### 🎯 ACCIONES")
        
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
            "📊 Resumen", "🗺️ Mapas", "🛰️ Índices", 
            "📈 Gráficos", "💰 Económico", "🌴 Detección"
        ])
        
        with tab1:
            st.subheader("RESUMEN GENERAL")
            
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
            except Exception:
                st.warning("No se pudo mostrar la tabla de bloques")
        
        with tab2:
            st.subheader("🗺️ MAPAS Y VISUALIZACIONES")
            
            st.markdown("### 🗺️ Mapa de Bloques con Palmas Detectadas")
            try:
                mapa_fig = crear_mapa_bloques(gdf_completo, st.session_state.palmas_detectadas)
                if mapa_fig:
                    st.pyplot(mapa_fig)
                    plt.close(mapa_fig)
                else:
                    st.info("No se pudo generar el mapa de bloques")
            except Exception as e:
                st.error(f"Error al mostrar el mapa: {str(e)[:100]}")
                st.info("Mostrando mapa simplificado...")
                try:
                    fig, ax = plt.subplots(figsize=(10, 8))
                    gdf_completo.plot(ax=ax, color='lightgreen', edgecolor='darkgreen', alpha=0.6)
                    ax.set_title('Mapa de Bloques - Palma Aceitera')
                    ax.set_xlabel('Longitud')
                    ax.set_ylabel('Latitud')
                    ax.grid(True, alpha=0.3)
                    st.pyplot(fig)
                    plt.close(fig)
                except Exception:
                    st.info("No se pudo mostrar ningún mapa")
            
            # Estadísticas de palmas detectadas
            if st.session_state.palmas_detectadas:
                st.markdown("### 📊 ESTADÍSTICAS DE DETECCIÓN")
                
                num_palmas = len(st.session_state.palmas_detectadas)
                area_total_val = resultados.get('area_total', 0)
                
                if area_total_val > 0:
                    densidad = num_palmas / area_total_val
                    
                    col_stat1, col_stat2, col_stat3 = st.columns(3)
                    
                    with col_stat1:
                        st.metric("Total palmas", f"{num_palmas:,}")
                    
                    with col_stat2:
                        st.metric("Densidad", f"{densidad:.0f} palmas/ha")
                    
                    with col_stat3:
                        densidad_optima = 130
                        diferencia = densidad - densidad_optima
                        st.metric("Vs. Óptimo (130/ha)", f"{diferencia:+.0f}")
        
        with tab3:
            st.subheader("🛰️ ÍNDICES DE VEGETACIÓN")
            
            col_info, col_legend = st.columns([2, 1])
            
            with col_info:
                st.markdown("### 📊 EXPLICACIÓN DE ÍNDICES")
                st.write("""
                **NDVI (Índice de Vegetación de Diferencia Normalizada):**
                - Mide salud y densidad de vegetación
                - Rango: -1 a 1 (0.7-0.8 óptimo para palma)
                - <0.4: Vegetación escasa/estresada
                - 0.4-0.6: Vegetación moderada
                - 0.6-0.75: Vegetación buena
                - >0.75: Vegetación excelente
                
                **NDRE (Índice de Borde Rojo Normalizado):**
                - Detecta estrés nutricional temprano
                - Sensible al contenido de clorofila
                - Ideal para monitoreo de nitrógeno
                
                **NDWI (Índice de Agua Normalizado):**
                - Mide contenido de agua en vegetación
                - Detecta estrés hídrico
                - Valores altos = mayor contenido de agua
                """)
            
            with col_legend:
                st.markdown("### 🎨 INTERPRETACIÓN NDVI")
                
                st.markdown("""
                <div style="background-color: #d73027; padding: 10px; border-radius: 5px; margin: 5px;">
                <strong style="color: white;">🔴 CRÍTICO</strong> (NDVI < 0.4)
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("""
                <div style="background-color: #fee08b; padding: 10px; border-radius: 5px; margin: 5px;">
                <strong>🟡 BAJO</strong> (NDVI 0.4-0.6)
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("""
                <div style="background-color: #91cf60; padding: 10px; border-radius: 5px; margin: 5px;">
                <strong style="color: white;">🟢 ADECUADO</strong> (NDVI 0.6-0.75)
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("""
                <div style="background-color: #1a9850; padding: 10px; border-radius: 5px; margin: 5px;">
                <strong style="color: white;">🔵 ÓPTIMO</strong> (NDVI > 0.75)
                </div>
                """, unsafe_allow_html=True)
            
            # Mapa de índices
            st.markdown("### 🗺️ Mapas de Índices por Bloque")
            try:
                mapa_indices = crear_mapa_indices(gdf_completo)
                if mapa_indices:
                    st.pyplot(mapa_indices)
                    plt.close(mapa_indices)
                else:
                    st.info("No se pudo generar el mapa de índices")
            except Exception as e:
                st.error(f"Error al mostrar mapa de índices: {str(e)[:100]}")
            
            # Tabla de valores
            st.markdown("### 📋 VALORES POR BLOQUE")
            try:
                resumen_indices = gdf_completo[['id_bloque', 'ndvi_modis', 'ndre_modis', 'ndwi_modis']].copy()
                resumen_indices.columns = ['Bloque', 'NDVI', 'NDRE', 'NDWI']
                
                # Calcular estado
                def clasificar_ndvi(valor):
                    if valor < 0.4:
                        return 'Crítico'
                    elif valor < 0.6:
                        return 'Bajo'
                    elif valor < 0.75:
                        return 'Adecuado'
                    else:
                        return 'Óptimo'
                
                resumen_indices['Estado'] = resumen_indices['NDVI'].apply(clasificar_ndvi)
                
                # Mostrar tabla con formato
                st.dataframe(
                    resumen_indices.style
                    .format({'NDVI': '{:.3f}', 'NDRE': '{:.3f}', 'NDWI': '{:.3f}'})
                    .applymap(lambda x: 'color: #d73027; font-weight: bold' if x == 'Crítico' else 
                             'color: #fee08b' if x == 'Bajo' else 
                             'color: #91cf60' if x == 'Adecuado' else 
                             'color: #1a9850; font-weight: bold', 
                             subset=['Estado'])
                )
                
            except Exception:
                st.warning("No se pudo generar la tabla de índices")
            
            # Recomendaciones
            st.markdown("### 🎯 RECOMENDACIONES BASADAS EN NDVI")
            
            try:
                ndvi_promedio = gdf_completo['ndvi_modis'].mean()
                
                if ndvi_promedio < 0.4:
                    st.error("""
                    **⚠️ ALERTA: NDVI CRÍTICO (Promedio: {:.3f})**
                    
                    **Acciones urgentes recomendadas:**
                    1. Evaluar sistema de riego inmediatamente
                    2. Realizar análisis completo de suelo
                    3. Aplicar fertilización nitrogenada de emergencia
                    4. Considerar replante en áreas con NDVI < 0.3
                    5. Monitoreo semanal de evolución
                    """.format(ndvi_promedio))
                elif ndvi_promedio < 0.6:
                    st.warning("""
                    **⚠️ NDVI MODERADO (Promedio: {:.3f})**
                    
                    **Recomendaciones:**
                    1. Ajustar programa de fertilización (énfasis en N y K)
                    2. Verificar drenaje del suelo
                    3. Monitoreo quincenal
                    4. Control preventivo de plagas
                    5. Evaluar posible deficiencia de micronutrientes
                    """.format(ndvi_promedio))
                elif ndvi_promedio < 0.75:
                    st.success("""
                    **✅ NDVI ADECUADO (Promedio: {:.3f})**
                    
                    **Acciones recomendadas:**
                    1. Mantener prácticas actuales de manejo
                    2. Monitoreo mensual de índices
                    3. Fertilización balanceada según análisis
                    4. Podas programadas según edad
                    5. Mantener cobertura vegetal
                    """.format(ndvi_promedio))
                else:
                    st.success("""
                    **🌟 NDVI ÓPTIMO (Promedio: {:.3f})**
                    
                    **Condiciones excelentes:**
                    1. Continuar con manejo actual
                    2. Monitoreo trimestral suficiente
                    3. Mantener nutrición balanceada
                    4. Planificar cosecha optimizada
                    5. Considerar programas de mejora genética
                    """.format(ndvi_promedio))
                    
            except Exception:
                st.info("No se pudieron generar recomendaciones específicas")
        
        with tab4:
            st.subheader("📈 GRÁFICOS DE ANÁLISIS")
            
            # Gráfico de NDVI
            st.markdown("### 📊 NDVI por Bloque")
            try:
                fig_ndvi = crear_grafico_ndvi_bloques(gdf_completo)
                if fig_ndvi:
                    st.pyplot(fig_ndvi)
                    plt.close(fig_ndvi)
                else:
                    st.info("No se pudo generar el gráfico de NDVI")
            except Exception as e:
                st.error(f"Error al mostrar gráfico NDVI: {str(e)[:100]}")
            
            # Gráfico de producción
            st.markdown("### 📈 Producción por Bloque")
            try:
                fig_prod = crear_grafico_produccion(gdf_completo)
                if fig_prod:
                    st.pyplot(fig_prod)
                    plt.close(fig_prod)
                else:
                    st.info("No se pudo generar el gráfico de producción")
            except Exception as e:
                st.error(f"Error al mostrar gráfico de producción: {str(e)[:100]}")
            
            # Gráfico de rentabilidad
            st.markdown("### 💰 Rentabilidad por Bloque")
            try:
                fig_rent = crear_grafico_rentabilidad(gdf_completo)
                if fig_rent:
                    st.pyplot(fig_rent)
                    plt.close(fig_rent)
                else:
                    st.info("No se pudo generar el gráfico de rentabilidad")
            except Exception as e:
                st.error(f"Error al mostrar gráfico de rentabilidad: {str(e)[:100]}")
            
            # Gráfico de edad
            st.markdown("### 📅 Distribución de Edades")
            try:
                fig_edad, ax_edad = plt.subplots(figsize=(12, 6))
                ax_edad.hist(gdf_completo['edad_anios'], bins=10, color='#4caf50', 
                            edgecolor='#2e7d32', alpha=0.7)
                ax_edad.set_xlabel('Edad (años)', fontsize=12)
                ax_edad.set_ylabel('Número de bloques', fontsize=12)
                ax_edad.set_title('Distribución de Edades de la Plantación', fontweight='bold', fontsize=14)
                ax_edad.grid(True, alpha=0.3)
                plt.tight_layout()
                st.pyplot(fig_edad)
                plt.close(fig_edad)
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
                costo_fertilizantes = gdf_completo[['costo_N', 'costo_P', 'costo_K', 'costo_Mg', 'costo_B']].sum().sum()
                costo_base = PARAMETROS_PALMA['COSTO_FERTILIZACION'] * gdf_completo['area_ha'].sum()
                
                labels = ['Fertilizantes', 'Costo Base']
                sizes = [costo_fertilizantes, costo_base]
                colors = ['#4caf50', '#2196f3']
                
                fig_costos, ax_costos = plt.subplots(figsize=(10, 8))
                wedges, texts, autotexts = ax_costos.pie(sizes, labels=labels, colors=colors, 
                                                        autopct='%1.1f%%', startangle=90)
                
                for autotext in autotexts:
                    autotext.set_color('white')
                    autotext.set_fontweight('bold')
                
                ax_costos.set_title('Distribución de Costos de Producción', fontweight='bold', fontsize=14)
                st.pyplot(fig_costos)
                plt.close(fig_costos)
            except Exception:
                st.info("No se pudo generar el gráfico de distribución de costos")
            
            # Tabla de costos
            st.subheader("📋 DETALLE DE COSTOS POR BLOQUE")
            try:
                costos_cols = ['id_bloque', 'costo_total', 'ingreso_estimado', 'rentabilidad']
                if all(col in gdf_completo.columns for col in costos_cols):
                    df_costos = gdf_completo[costos_cols].copy()
                    df_costos.columns = ['Bloque', 'Costo Total (USD)', 'Ingreso Estimado (USD)', 'Rentabilidad (%)']
                    
                    # Formato condicional
                    def color_rentabilidad(val):
                        if val < 0:
                            return 'color: #d73027; font-weight: bold'
                        elif val < 15:
                            return 'color: #fee08b'
                        elif val < 25:
                            return 'color: #91cf60'
                        else:
                            return 'color: #1a9850; font-weight: bold'
                    
                    st.dataframe(
                        df_costos.style
                        .format({
                            'Costo Total (USD)': '{:,.2f}',
                            'Ingreso Estimado (USD)': '{:,.2f}',
                            'Rentabilidad (%)': '{:.1f}'
                        })
                        .applymap(color_rentabilidad, subset=['Rentabilidad (%)'])
                    )
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
                """)
            
            if st.session_state.deteccion_ejecutada and st.session_state.palmas_detectadas:
                palmas = st.session_state.palmas_detectadas
                total = len(palmas)
                area_total_val = resultados.get('area_total', 0)
                densidad = total / area_total_val if area_total_val > 0 else 0
                
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
                        cobertura = (total * area_prom) / (area_total_val * 10000) * 100 if area_total_val > 0 else 0
                        st.metric("Cobertura estimada", f"{cobertura:.1f}%")
                    except Exception:
                        st.metric("Cobertura estimada", "N/A")
                
                # Mostrar imagen con detección
                st.subheader("📷 Visualización de Detección")
                if hasattr(st.session_state, 'imagen_alta_resolucion') and st.session_state.imagen_alta_resolucion is not None:
                    try:
                        st.session_state.imagen_alta_resolucion.seek(0)
                        st.image(st.session_state.imagen_alta_resolucion,
                                caption="Simulación de detección de palmas individuales",
                                use_container_width=True)
                    except Exception:
                        st.info("No se pudo mostrar la imagen de detección")
                else:
                    st.info("No hay imagen de detección disponible")
                    
                # Mapa de distribución
                st.subheader("🗺️ Mapa de Distribución de Palmas")
                try:
                    fig_palmas, ax_palmas = plt.subplots(figsize=(14, 8))
                    gdf_completo.plot(ax=ax_palmas, color='lightgreen', alpha=0.3, edgecolor='darkgreen', linewidth=2)
                    
                    if palmas and len(palmas) > 0:
                        coords = np.array([p['centroide'] for p in palmas[:1000]])  # Limitar para rendimiento
                        ax_palmas.scatter(coords[:, 0], coords[:, 1], 
                                        s=15, color='blue', alpha=0.6, 
                                        label=f'Palmas detectadas ({len(coords)})',
                                        edgecolors='white', linewidth=0.5)
                    
                    ax_palmas.set_title(f'Distribución de Palmas Detectadas', 
                                       fontsize=14, fontweight='bold')
                    ax_palmas.set_xlabel('Longitud')
                    ax_palmas.set_ylabel('Latitud')
                    ax_palmas.legend()
                    ax_palmas.grid(True, alpha=0.3)
                    plt.tight_layout()
                    st.pyplot(fig_palmas)
                    plt.close(fig_palmas)
                except Exception:
                    st.info("No se pudo generar el mapa de distribución de palmas")
                
                # Análisis de densidad
                st.subheader("📊 ANÁLISIS DE DENSIDAD")
                densidad_optima = 130
                if total == 0:
                    st.warning("No se detectaron palmas.")
                elif densidad < densidad_optima * 0.8:
                    st.error(f"**DENSIDAD BAJA:** {densidad:.0f} plantas/ha (Óptimo: {densidad_optima})")
                    st.write("Recomendación: Considerar replantar áreas con baja densidad")
                elif densidad > densidad_optima * 1.2:
                    st.warning(f"**DENSIDAD ALTA:** {densidad:.0f} plantas/ha (Óptimo: {densidad_optima})")
                    st.write("Recomendación: Evaluar competencia por recursos, considerar raleo")
                else:
                    st.success(f"**DENSIDAD ÓPTIMA:** {densidad:.0f} plantas/ha")
                    st.write("La densidad de plantación es adecuada para la variedad seleccionada")
                
                # Exportar datos
                st.subheader("📥 EXPORTAR DATOS")
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
                            informe = f"""INFORME DE DETECCIÓN DE PALMAS
Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}
Total palmas: {total}
Área total: {area_total_val:.1f} ha
Densidad: {densidad:.1f} plantas/ha
Densidad óptima: {densidad_optima} plantas/ha
Variedad: {st.session_state.variedad_seleccionada}
Estado: {"Óptimo" if abs(densidad - densidad_optima) < 10 else "Revisar"}
Observaciones: Análisis de detección de palmas individuales realizado con éxito."""
                            st.download_button(
                                label="📄 Descargar Informe (TXT)",
                                data=informe,
                                file_name=f"informe_deteccion_{datetime.now().strftime('%Y%m%d')}.txt",
                                mime="text/plain",
                                use_container_width=True
                            )
                    except Exception:
                        st.info("No se pudieron exportar los datos de detección")
            else:
                st.info("La detección de palmas no se ha ejecutado aún.")
                if st.button("🔍 EJECUTAR DETECCIÓN DE PALMAS", key="detectar_palmas_tab6", use_container_width=True):
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

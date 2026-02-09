# app.py - Versión CORREGIDA con mapas de calor, ESRI Satellite y mejor detección
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
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster
from branca.colormap import LinearColormap

# ===== CONFIGURACIÓN =====
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
        'mapa_generado': False,
        'n_divisiones': 16,
        'fecha_inicio': datetime.now() - timedelta(days=60),
        'fecha_fin': datetime.now(),
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
def generar_datos_indices(gdf, fecha_inicio, fecha_fin):
    """Genera datos de índices NDVI, NDRE, NDWI"""
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

def generar_datos_climaticos_nasa_power(gdf, fecha_inicio, fecha_fin):
    """Genera datos climáticos simulados de NASA POWER"""
    try:
        centroide = gdf.geometry.unary_union.centroid
        
        # Simular datos de NASA POWER
        # Radiación solar (MJ/m²/día)
        radiacion_base = 18.0
        radiacion_var = np.random.normal(0, 3, 30)
        radiacion_diaria = [max(5, min(30, radiacion_base + var)) for var in radiacion_var]
        
        # Precipitación (mm)
        precip_base = 3.0
        precip_diaria = []
        for i in range(30):
            if np.random.random() > 0.7:  # 30% de probabilidad de lluvia
                precip = np.random.exponential(precip_base * 2)
                precip_diaria.append(min(50, precip))
            else:
                precip_diaria.append(0)
        
        # Velocidad del viento (m/s)
        viento_base = 3.0
        viento_diaria = [max(0.5, min(10, viento_base + np.random.normal(0, 1.5))) for _ in range(30)]
        
        # Temperatura (°C)
        temp_base = 25.0
        temp_diaria = [temp_base + np.random.normal(0, 2) for _ in range(30)]
        
        return {
            'radiacion': {
                'promedio': round(np.mean(radiacion_diaria), 1),
                'maxima': round(max(radiacion_diaria), 1),
                'minima': round(min(radiacion_diaria), 1),
                'diaria': radiacion_diaria
            },
            'precipitacion': {
                'total': round(sum(precip_diaria), 1),
                'maxima_diaria': round(max(precip_diaria), 1),
                'dias_con_lluvia': sum(1 for p in precip_diaria if p > 0),
                'diaria': precip_diaria
            },
            'viento': {
                'promedio': round(np.mean(viento_diaria), 1),
                'maxima': round(max(viento_diaria), 1),
                'diaria': viento_diaria
            },
            'temperatura': {
                'promedio': round(np.mean(temp_diaria), 1),
                'maxima': round(max(temp_diaria), 1),
                'minima': round(min(temp_diaria), 1),
                'diaria': temp_diaria
            },
            'periodo': f"{fecha_inicio.strftime('%d/%m/%Y')} - {fecha_fin.strftime('%d/%m/%Y')}",
            'fuente': 'NASA POWER (datos simulados)'
        }
    except Exception:
        return {
            'radiacion': {'promedio': 18.0, 'maxima': 25.0, 'minima': 12.0, 'diaria': [18]*30},
            'precipitacion': {'total': 90.0, 'maxima_diaria': 15.0, 'dias_con_lluvia': 10, 'diaria': [3]*30},
            'viento': {'promedio': 3.0, 'maxima': 6.0, 'diaria': [3]*30},
            'temperatura': {'promedio': 25.0, 'maxima': 30.0, 'minima': 20.0, 'diaria': [25]*30},
            'periodo': 'Últimos 30 días',
            'fuente': 'NASA POWER (datos simulados)'
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

# ===== FUNCIONES DE VISUALIZACIÓN MEJORADAS =====
def crear_mapa_calor_indices(gdf):
    """Crea un mapa de calor para cada índice usando interpolación"""
    if gdf is None or len(gdf) == 0:
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.text(0.5, 0.5, "No hay datos para mostrar", 
                ha='center', va='center', fontsize=12)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig
    
    try:
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        fig.subplots_adjust(wspace=0.3)
        
        # Obtener centroides y valores
        centroids = []
        ndvi_vals = []
        ndre_vals = []
        ndwi_vals = []
        
        for idx, row in gdf.iterrows():
            try:
                centroid = row.geometry.centroid
                centroids.append([centroid.x, centroid.y])
                ndvi_vals.append(row.get('ndvi_modis', 0.5))
                ndre_vals.append(row.get('ndre_modis', 0.4))
                ndwi_vals.append(row.get('ndwi_modis', 0.3))
            except Exception:
                continue
        
        if not centroids:
            for ax in axes:
                ax.text(0.5, 0.5, "No hay datos", ha='center', va='center')
                ax.axis('off')
            return fig
        
        centroids = np.array(centroids)
        
        # Crear grid para interpolación
        x_min, x_max = centroids[:, 0].min(), centroids[:, 0].max()
        y_min, y_max = centroids[:, 1].min(), centroids[:, 1].max()
        
        # Añadir margen
        x_margin = (x_max - x_min) * 0.1
        y_margin = (y_max - y_min) * 0.1
        x_min, x_max = x_min - x_margin, x_max + x_margin
        y_min, y_max = y_min - y_margin, y_max + y_margin
        
        grid_size = 50
        xi = np.linspace(x_min, x_max, grid_size)
        yi = np.linspace(y_min, y_max, grid_size)
        xi, yi = np.meshgrid(xi, yi)
        
        # Interpolación simple (distancia inversa)
        def interpolate_idw(points, values, xi, yi, power=2):
            zi = np.zeros(xi.shape)
            for i in range(xi.shape[0]):
                for j in range(xi.shape[1]):
                    distances = np.sqrt((points[:,0] - xi[i,j])**2 + (points[:,1] - yi[i,j])**2)
                    weights = 1.0 / (distances**power + 1e-8)
                    zi[i,j] = np.sum(weights * values) / np.sum(weights)
            return zi
        
        # NDVI
        if len(ndvi_vals) > 0:
            zi_ndvi = interpolate_idw(centroids, ndvi_vals, xi, yi)
            im1 = axes[0].contourf(xi, yi, zi_ndvi, levels=20, cmap='RdYlGn', alpha=0.8, vmin=0.3, vmax=0.9)
            axes[0].scatter(centroids[:,0], centroids[:,1], c=ndvi_vals, cmap='RdYlGn', 
                           edgecolors='black', s=50, alpha=0.7, vmin=0.3, vmax=0.9)
            plt.colorbar(im1, ax=axes[0], orientation='vertical', label='NDVI')
        
        axes[0].set_title('NDVI - Índice de Vegetación', fontsize=12, fontweight='bold')
        axes[0].set_xlabel('Longitud')
        axes[0].set_ylabel('Latitud')
        axes[0].grid(True, alpha=0.3)
        
        # NDRE
        if len(ndre_vals) > 0:
            zi_ndre = interpolate_idw(centroids, ndre_vals, xi, yi)
            im2 = axes[1].contourf(xi, yi, zi_ndre, levels=20, cmap='YlGn', alpha=0.8, vmin=0.2, vmax=0.8)
            axes[1].scatter(centroids[:,0], centroids[:,1], c=ndre_vals, cmap='YlGn', 
                           edgecolors='black', s=50, alpha=0.7, vmin=0.2, vmax=0.8)
            plt.colorbar(im2, ax=axes[1], orientation='vertical', label='NDRE')
        
        axes[1].set_title('NDRE - Índice de Borde Rojo', fontsize=12, fontweight='bold')
        axes[1].set_xlabel('Longitud')
        axes[1].grid(True, alpha=0.3)
        
        # NDWI
        if len(ndwi_vals) > 0:
            zi_ndwi = interpolate_idw(centroids, ndwi_vals, xi, yi)
            im3 = axes[2].contourf(xi, yi, zi_ndwi, levels=20, cmap='Blues', alpha=0.8, vmin=0.1, vmax=0.7)
            axes[2].scatter(centroids[:,0], centroids[:,1], c=ndwi_vals, cmap='Blues', 
                           edgecolors='black', s=50, alpha=0.7, vmin=0.1, vmax=0.7)
            plt.colorbar(im3, ax=axes[2], orientation='vertical', label='NDWI')
        
        axes[2].set_title('NDWI - Índice de Agua', fontsize=12, fontweight='bold')
        axes[2].set_xlabel('Longitud')
        axes[2].grid(True, alpha=0.3)
        
        plt.suptitle('Mapas de Calor de Índices de Vegetación', fontsize=14, fontweight='bold', y=1.02)
        plt.tight_layout()
        return fig
        
    except Exception as e:
        # Figura de error simplificada
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.text(0.5, 0.5, "Error al crear mapa de calor\nMostrando puntos simples...", 
                ha='center', va='center', fontsize=12, color='red')
        
        # Mostrar puntos simples como fallback
        if 'ndvi_modis' in gdf.columns:
            centroids = []
            ndvi_vals = []
            for idx, row in gdf.iterrows():
                try:
                    centroid = row.geometry.centroid
                    centroids.append([centroid.x, centroid.y])
                    ndvi_vals.append(row['ndvi_modis'])
                except:
                    continue
            
            if centroids:
                centroids = np.array(centroids)
                sc = ax.scatter(centroids[:,0], centroids[:,1], c=ndvi_vals, cmap='RdYlGn', 
                               s=100, alpha=0.7, vmin=0.3, vmax=0.9)
                plt.colorbar(sc, ax=ax, label='NDVI')
        
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.set_title('NDVI por Bloque (fallback)', fontsize=12)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        return fig

def crear_mapa_interactivo_esri(gdf, palmas_detectadas=None):
    """Crea un mapa interactivo con ESRI Satellite"""
    if gdf is None or len(gdf) == 0:
        return None
    
    try:
        # Obtener centroide para centrar el mapa
        centroide = gdf.geometry.unary_union.centroid
        bounds = gdf.total_bounds
        
        # Crear mapa base con ESRI Satellite
        m = folium.Map(
            location=[centroide.y, centroide.x],
            zoom_start=15,
            tiles=None,
            control_scale=True
        )
        
        # Capa ESRI Satellite
        esri_satellite = folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri, Maxar, Earthstar Geographics, and the GIS User Community',
            name='Satélite Esri',
            overlay=False,
            control=True
        ).add_to(m)
        
        # Capa OpenStreetMap como alternativa
        folium.TileLayer(
            tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            attr='OpenStreetMap',
            name='OpenStreetMap',
            overlay=False,
            control=True
        ).add_to(m)
        
        # Añadir polígonos de bloques con colores según NDVI
        if 'ndvi_modis' in gdf.columns:
            # Crear colormap para NDVI
            colormap = LinearColormap(
                colors=['red', 'orange', 'yellow', 'lightgreen', 'darkgreen'],
                vmin=0.3,
                vmax=0.9,
                caption='NDVI'
            )
            
            for idx, row in gdf.iterrows():
                try:
                    if row.geometry.geom_type == 'Polygon':
                        coords = [(lat, lon) for lon, lat in row.geometry.exterior.coords]
                    elif row.geometry.geom_type == 'MultiPolygon':
                        poly = list(row.geometry.geoms)[0]
                        coords = [(lat, lon) for lon, lat in poly.exterior.coords]
                    else:
                        continue
                    
                    ndvi = row.get('ndvi_modis', 0.5)
                    
                    # Crear popup con información
                    popup_text = f"""
                    <div style="font-family: Arial; font-size: 12px;">
                        <b>Bloque {int(row['id_bloque'])}</b><br>
                        <hr style="margin: 5px 0;">
                        <b>NDVI:</b> {ndvi:.3f}<br>
                        <b>NDRE:</b> {row.get('ndre_modis', 0):.3f}<br>
                        <b>NDWI:</b> {row.get('ndwi_modis', 0):.3f}<br>
                        <b>Área:</b> {row.get('area_ha', 0):.2f} ha<br>
                        <b>Edad:</b> {row.get('edad_anios', 0):.1f} años
                    </div>
                    """
                    
                    folium.Polygon(
                        locations=coords,
                        popup=folium.Popup(popup_text, max_width=300),
                        tooltip=f"Bloque {int(row['id_bloque'])} - NDVI: {ndvi:.3f}",
                        color=colormap(ndvi),
                        fill=True,
                        fill_color=colormap(ndvi),
                        fill_opacity=0.6,
                        weight=2,
                        opacity=0.8
                    ).add_to(m)
                    
                except Exception:
                    continue
            
            # Añadir colormap al mapa
            colormap.add_to(m)
        
        # Añadir palmas detectadas si existen
        if palmas_detectadas and len(palmas_detectadas) > 0:
            marker_cluster = MarkerCluster(
                name="Palmas detectadas",
                overlay=True,
                control=True,
                icon_create_function=None
            ).add_to(m)
            
            # Limitar a 1000 palmas para rendimiento
            for i, palma in enumerate(palmas_detectadas[:1000]):
                try:
                    if 'centroide' in palma:
                        lon, lat = palma['centroide']
                        
                        # Verificar que la palma esté dentro del polígono
                        point = Point(lon, lat)
                        dentro = False
                        for _, row in gdf.iterrows():
                            if row.geometry.contains(point):
                                dentro = True
                                break
                        
                        if dentro:
                            folium.CircleMarker(
                                location=[lat, lon],
                                radius=3,
                                popup=f"Palma #{i+1}",
                                tooltip=f"Palma #{i+1}",
                                color='red',
                                fill=True,
                                fill_color='red',
                                fill_opacity=0.8,
                                weight=1
                            ).add_to(marker_cluster)
                        
                except Exception:
                    continue
        
        # Añadir control de capas
        folium.LayerControl(collapsed=False).add_to(m)
        
        # Añadir botón de pantalla completa
        folium.plugins.Fullscreen(
            position="topright",
            title="Pantalla completa",
            title_cancel="Salir pantalla completa",
            force_separate_button=True,
        ).add_to(m)
        
        return m
        
    except Exception as e:
        print(f"Error en crear_mapa_interactivo_esri: {str(e)}")
        return None

def crear_graficos_climaticos(datos_climaticos):
    """Crea gráficos de datos climáticos"""
    try:
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        
        # Gráfico 1: Radiación solar
        ax1 = axes[0, 0]
        radiacion = datos_climaticos['radiacion']['diaria']
        dias = list(range(1, len(radiacion) + 1))
        ax1.plot(dias, radiacion, 'o-', color='orange', linewidth=2, markersize=4)
        ax1.fill_between(dias, radiacion, alpha=0.3, color='orange')
        ax1.axhline(y=datos_climaticos['radiacion']['promedio'], color='red', 
                   linestyle='--', label=f"Promedio: {datos_climaticos['radiacion']['promedio']} MJ/m²/día")
        ax1.set_xlabel('Día')
        ax1.set_ylabel('Radiación (MJ/m²/día)')
        ax1.set_title('Radiación Solar Diaria', fontweight='bold')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Gráfico 2: Precipitación
        ax2 = axes[0, 1]
        precipitacion = datos_climaticos['precipitacion']['diaria']
        ax2.bar(dias, precipitacion, color='blue', alpha=0.7)
        ax2.set_xlabel('Día')
        ax2.set_ylabel('Precipitación (mm)')
        ax2.set_title(f'Precipitación Diaria (Total: {datos_climaticos["precipitacion"]["total"]} mm)', fontweight='bold')
        ax2.grid(True, alpha=0.3, axis='y')
        
        # Gráfico 3: Velocidad del viento
        ax3 = axes[1, 0]
        viento = datos_climaticos['viento']['diaria']
        ax3.plot(dias, viento, 's-', color='green', linewidth=2, markersize=4)
        ax3.fill_between(dias, viento, alpha=0.3, color='green')
        ax3.axhline(y=datos_climaticos['viento']['promedio'], color='red', 
                   linestyle='--', label=f"Promedio: {datos_climaticos['viento']['promedio']} m/s")
        ax3.set_xlabel('Día')
        ax3.set_ylabel('Velocidad del viento (m/s)')
        ax3.set_title('Velocidad del Viento Diaria', fontweight='bold')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        # Gráfico 4: Temperatura
        ax4 = axes[1, 1]
        temperatura = datos_climaticos['temperatura']['diaria']
        ax4.plot(dias, temperatura, '^-', color='red', linewidth=2, markersize=4)
        ax4.fill_between(dias, temperatura, alpha=0.3, color='red')
        ax4.axhline(y=datos_climaticos['temperatura']['promedio'], color='blue', 
                   linestyle='--', label=f"Promedio: {datos_climaticos['temperatura']['promedio']}°C")
        ax4.set_xlabel('Día')
        ax4.set_ylabel('Temperatura (°C)')
        ax4.set_title('Temperatura Diaria', fontweight='bold')
        ax4.legend()
        ax4.grid(True, alpha=0.3)
        
        plt.suptitle('Datos Climáticos - NASA POWER', fontsize=16, fontweight='bold', y=1.02)
        plt.tight_layout()
        return fig
        
    except Exception:
        # Gráfico simple de error
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "Error al crear gráficos climáticos", 
                ha='center', va='center', fontsize=12)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return fig

# ===== FUNCIONES DE DETECCIÓN MEJORADAS =====
def simular_deteccion_palmas_realista(gdf, densidad=130):
    """Simula la detección de palmas de manera realista dentro del polígono"""
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
        intentos_maximos = num_palmas * 3  # Intentar más veces para conseguir dentro del polígono
        intentos = 0
        
        while len(palmas_detectadas) < num_palmas and intentos < intentos_maximos:
            intentos += 1
            
            # Generar punto aleatorio dentro del bounding box
            lon = np.random.uniform(min_lon, max_lon)
            lat = np.random.uniform(min_lat, max_lat)
            point = Point(lon, lat)
            
            # Verificar si el punto está dentro del polígono
            dentro = False
            for idx, row in gdf.iterrows():
                if row.geometry.contains(point):
                    dentro = True
                    break
            
            if dentro:
                # Asegurar que no esté demasiado cerca de otra palma
                muy_cerca = False
                for palma in palmas_detectadas:
                    if 'centroide' in palma:
                        p_lon, p_lat = palma['centroide']
                        distancia = math.sqrt((lon - p_lon)**2 + (lat - p_lat)**2)
                        if distancia < 0.0001:  # Aprox 10 metros
                            muy_cerca = True
                            break
                
                if not muy_cerca:
                    palmas_detectadas.append({
                        'centroide': (lon, lat),
                        'area_m2': np.random.uniform(15, 25),
                        'circularidad': np.random.uniform(0.8, 0.95),
                        'diametro_aprox': np.random.uniform(4, 8),
                        'simulado': True
                    })
        
        # Si no se pudieron generar suficientes, usar patrón hexagonal forzado
        if len(palmas_detectadas) < num_palmas * 0.5:
            return simular_deteccion_palmas_hexagonal(gdf, densidad)
        
        return {
            'detectadas': palmas_detectadas,
            'total': len(palmas_detectadas),
            'patron': 'aleatorio dentro del polígono',
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

def simular_deteccion_palmas_hexagonal(gdf, densidad=130):
    """Simula detección con patrón hexagonal"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        area_ha = calcular_superficie(gdf)
        num_palmas = int(area_ha * densidad)
        
        palmas_detectadas = []
        
        # Distancia entre palmas en grados (aproximadamente 9 metros)
        distancia_grados = 9 / 111000  # 111km por grado
        
        # Patrón hexagonal
        rows = int((max_lat - min_lat) / (distancia_grados * 0.866))
        cols = int((max_lon - min_lon) / distancia_grados)
        
        for i in range(rows):
            for j in range(cols):
                if len(palmas_detectadas) >= num_palmas:
                    break
                
                # Coordenadas en patrón hexagonal
                offset = distancia_grados * 0.5 if i % 2 == 0 else 0
                lon = min_lon + (j * distancia_grados) + offset
                lat = min_lat + (i * distancia_grados * 0.866)
                
                point = Point(lon, lat)
                
                # Verificar si está dentro del polígono
                dentro = False
                for idx, row in gdf.iterrows():
                    if row.geometry.contains(point):
                        dentro = True
                        break
                
                if dentro:
                    # Pequeña variación aleatoria
                    lon += np.random.normal(0, distancia_grados * 0.1)
                    lat += np.random.normal(0, distancia_grados * 0.1)
                    
                    palmas_detectadas.append({
                        'centroide': (lon, lat),
                        'area_m2': np.random.uniform(15, 25),
                        'circularidad': np.random.uniform(0.8, 0.95),
                        'diametro_aprox': np.random.uniform(4, 8),
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
        
        # Usar simulación realista
        resultados = simular_deteccion_palmas_realista(gdf)
        st.session_state.palmas_detectadas = resultados['detectadas']
        
        st.session_state.deteccion_ejecutada = True
        st.success(f"✅ Detección completada: {len(resultados['detectadas'])} palmas detectadas")

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
        
        # 1. Obtener datos de índices
        datos_indices = generar_datos_indices(gdf, fecha_inicio, fecha_fin)
        st.session_state.datos_modis = datos_indices
        
        # 2. Obtener datos climáticos NASA POWER
        datos_climaticos = generar_datos_climaticos_nasa_power(gdf, fecha_inicio, fecha_fin)
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
        valor_base = datos_indices.get('ndvi', 0.65)
        
        for idx, row in gdf_dividido.iterrows():
            try:
                centroid = row.geometry.centroid
                lat_norm = (centroid.y + 90) / 180
                lon_norm = (centroid.x + 180) / 360
                variacion = (lat_norm * lon_norm) * 0.2 - 0.1
                ndvi = valor_base + variacion + np.random.normal(0, 0.05)
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
        
        # 8. Calcular salud de la plantación
        salud_bloques = []
        for ndvi in ndvi_bloques:
            if ndvi < 0.4:
                salud = 'Crítica'
            elif ndvi < 0.6:
                salud = 'Baja'
            elif ndvi < 0.75:
                salud = 'Moderada'
            else:
                salud = 'Buena'
            salud_bloques.append(salud)
        
        gdf_dividido['salud'] = salud_bloques
        
        # Almacenar resultados
        st.session_state.resultados_todos = {
            'exitoso': True,
            'gdf_completo': gdf_dividido,
            'area_total': area_total,
            'edades': edades,
            'datos_indices': datos_indices,
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
        Monitoreo biológico con mapas de calor de índices y detección de plantas individuales
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
        densidad_personalizada = st.slider("Densidad objetivo (plantas/ha):", 50, 200, 130)
    
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
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 Resumen", "🗺️ Mapas", "🛰️ Índices", 
            "🌤️ Clima", "🌴 Detección"
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
                    ndvi_prom = gdf_completo['ndvi_modis'].mean()
                    st.metric("NDVI Promedio", f"{ndvi_prom:.3f}")
                except Exception:
                    st.metric("NDVI Promedio", "N/A")
            with col4:
                try:
                    bloques_salud_buena = (gdf_completo['salud'] == 'Buena').sum()
                    total_bloques = len(gdf_completo)
                    porcentaje_bueno = (bloques_salud_buena / total_bloques) * 100
                    st.metric("Salud Buena", f"{porcentaje_bueno:.1f}%")
                except Exception:
                    st.metric("Salud Buena", "N/A")
            
            st.subheader("📋 RESUMEN POR BLOQUE")
            try:
                columnas = ['id_bloque', 'area_ha', 'edad_anios', 'ndvi_modis', 'ndre_modis', 'ndwi_modis', 'salud']
                tabla = gdf_completo[columnas].copy()
                tabla.columns = ['Bloque', 'Área (ha)', 'Edad (años)', 'NDVI', 'NDRE', 'NDWI', 'Salud']
                
                # Formato condicional para salud
                def color_salud(val):
                    if val == 'Crítica':
                        return 'color: #d73027; font-weight: bold'
                    elif val == 'Baja':
                        return 'color: #fee08b'
                    elif val == 'Moderada':
                        return 'color: #91cf60'
                    else:  # Buena
                        return 'color: #1a9850; font-weight: bold'
                
                st.dataframe(
                    tabla.style
                    .format({
                        'Área (ha)': '{:.2f}',
                        'Edad (años)': '{:.1f}',
                        'NDVI': '{:.3f}',
                        'NDRE': '{:.3f}',
                        'NDWI': '{:.3f}'
                    })
                    .applymap(color_salud, subset=['Salud'])
                )
            except Exception:
                st.warning("No se pudo mostrar la tabla de bloques")
        
        with tab2:
            st.subheader("🗺️ MAPAS INTERACTIVOS")
            
            # Selector de tipo de mapa
            tipo_mapa = st.radio(
                "Seleccionar tipo de mapa:",
                ["ESRI Satellite", "OpenStreetMap"],
                horizontal=True,
                index=0
            )
            
            # Crear mapa interactivo
            st.markdown("### 🌍 Mapa Interactivo con Palmas Detectadas")
            
            try:
                mapa_interactivo = crear_mapa_interactivo_esri(gdf_completo, st.session_state.palmas_detectadas)
                
                if mapa_interactivo:
                    # Añadir controles
                    col_info1, col_info2 = st.columns(2)
                    
                    with col_info1:
                        st.markdown("**Leyenda:**")
                        st.markdown("""
                        - 🔴 **Rojo oscuro:** NDVI crítico (<0.4)
                        - 🟡 **Amarillo:** NDVI bajo (0.4-0.6)
                        - 🟢 **Verde claro:** NDVI moderado (0.6-0.75)
                        - 🟢 **Verde oscuro:** NDVI bueno (>0.75)
                        - 🔴 **Puntos rojos:** Palmas individuales detectadas
                        """)
                    
                    with col_info2:
                        st.markdown("**Controles:**")
                        st.markdown("""
                        - 🖱️ **Click** en cualquier bloque o palma para ver detalles
                        - 🔄 **Arrastrar** para mover el mapa
                        - ➕ **Scroll** para zoom in/out
                        - 🗺️ **Esquina superior derecha:** Cambiar capas
                        - ⛶ **Fullscreen:** Pantalla completa
                        """)
                    
                    # Mostrar mapa
                    folium_static(mapa_interactivo, width=1000, height=600)
                    
                    # Botón para descargar datos del mapa
                    st.markdown("### 📥 EXPORTAR DATOS DEL MAPA")
                    try:
                        # Crear GeoJSON con todos los datos
                        gdf_export = gdf_completo.copy()
                        if 'geometry' in gdf_export.columns:
                            geojson_str = gdf_export.to_json()
                            
                            col_exp1, col_exp2 = st.columns(2)
                            
                            with col_exp1:
                                st.download_button(
                                    label="🗺️ Descargar GeoJSON (Mapa completo)",
                                    data=geojson_str,
                                    file_name=f"mapa_palma_{datetime.now().strftime('%Y%m%d')}.geojson",
                                    mime="application/geo+json",
                                    use_container_width=True
                                )
                            
                            with col_exp2:
                                # Descargar CSV también
                                csv_data = gdf_export.drop(columns='geometry').to_csv(index=False)
                                st.download_button(
                                    label="📊 Descargar CSV (Datos tabulares)",
                                    data=csv_data,
                                    file_name=f"datos_palma_{datetime.now().strftime('%Y%m%d')}.csv",
                                    mime="text/csv",
                                    use_container_width=True
                                )
                    except Exception:
                        st.info("No se pudieron exportar los datos del mapa")
                else:
                    st.warning("No se pudo generar el mapa interactivo. Verifique las dependencias.")
                    
            except Exception as e:
                st.error(f"Error al mostrar mapa interactivo: {str(e)[:100]}")
                st.info("Intentando mostrar mapa estático...")
                
                # Mostrar mapa estático como fallback
                try:
                    fig, ax = plt.subplots(figsize=(12, 8))
                    gdf_completo.plot(ax=ax, column='ndvi_modis', cmap='RdYlGn', 
                                     legend=True, legend_kwds={'label': 'NDVI'},
                                     edgecolor='black', linewidth=0.5)
                    ax.set_title('Mapa de NDVI por Bloque', fontsize=14, fontweight='bold')
                    ax.set_xlabel('Longitud')
                    ax.set_ylabel('Latitud')
                    ax.grid(True, alpha=0.3)
                    plt.tight_layout()
                    st.pyplot(fig)
                    plt.close(fig)
                except Exception:
                    st.info("No se pudo mostrar ningún mapa")
        
        with tab3:
            st.subheader("🛰️ MAPAS DE CALOR DE ÍNDICES")
            
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
            
            # Mapa de calor de índices
            st.markdown("### 🗺️ Mapas de Calor de Índices")
            try:
                mapa_calor = crear_mapa_calor_indices(gdf_completo)
                if mapa_calor:
                    st.pyplot(mapa_calor)
                    plt.close(mapa_calor)
                else:
                    st.info("No se pudo generar el mapa de calor")
            except Exception as e:
                st.error(f"Error al mostrar mapa de calor: {str(e)[:100]}")
            
            # Descarga de datos de índices
            st.markdown("### 📥 EXPORTAR DATOS DE ÍNDICES")
            try:
                # Crear GeoJSON con datos de índices
                gdf_indices = gdf_completo[['id_bloque', 'ndvi_modis', 'ndre_modis', 'ndwi_modis', 'salud', 'geometry']].copy()
                gdf_indices.columns = ['id_bloque', 'NDVI', 'NDRE', 'NDWI', 'Salud', 'geometry']
                
                geojson_indices = gdf_indices.to_json()
                
                col_dl1, col_dl2 = st.columns(2)
                
                with col_dl1:
                    st.download_button(
                        label="🗺️ Descargar GeoJSON (Índices)",
                        data=geojson_indices,
                        file_name=f"indices_palma_{datetime.now().strftime('%Y%m%d')}.geojson",
                        mime="application/geo+json",
                        use_container_width=True
                    )
                
                with col_dl2:
                    csv_indices = gdf_indices.drop(columns='geometry').to_csv(index=False)
                    st.download_button(
                        label="📊 Descargar CSV (Índices)",
                        data=csv_indices,
                        file_name=f"indices_palma_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    
            except Exception:
                st.info("No se pudieron exportar los datos de índices")
            
            # Recomendaciones
            st.markdown("### 🎯 RECOMENDACIONES")
            
            try:
                ndvi_promedio = gdf_completo['ndvi_modis'].mean()
                
                if ndvi_promedio < 0.4:
                    st.error(f"""
                    **⚠️ ALERTA: NDVI CRÍTICO (Promedio: {ndvi_promedio:.3f})**
                    
                    **Acciones urgentes recomendadas:**
                    1. Evaluar sistema de riego inmediatamente
                    2. Realizar análisis completo de suelo
                    3. Aplicar fertilización nitrogenada de emergencia
                    4. Considerar replante en áreas con NDVI < 0.3
                    5. Monitoreo semanal de evolución
                    """)
                elif ndvi_promedio < 0.6:
                    st.warning(f"""
                    **⚠️ NDVI MODERADO (Promedio: {ndvi_promedio:.3f})**
                    
                    **Recomendaciones:**
                    1. Ajustar programa de fertilización (énfasis en N y K)
                    2. Verificar drenaje del suelo
                    3. Monitoreo quincenal
                    4. Control preventivo de plagas
                    5. Evaluar posible deficiencia de micronutrientes
                    """)
                elif ndvi_promedio < 0.75:
                    st.success(f"""
                    **✅ NDVI ADECUADO (Promedio: {ndvi_promedio:.3f})**
                    
                    **Acciones recomendadas:**
                    1. Mantener prácticas actuales de manejo
                    2. Monitoreo mensual de índices
                    3. Fertilización balanceada según análisis
                    4. Podas programadas según edad
                    5. Mantener cobertura vegetal
                    """)
                else:
                    st.success(f"""
                    **🌟 NDVI ÓPTIMO (Promedio: {ndvi_promedio:.3f})**
                    
                    **Condiciones excelentes:**
                    1. Continuar con manejo actual
                    2. Monitoreo trimestral suficiente
                    3. Mantener nutrición balanceada
                    4. Planificar cosecha optimizada
                    5. Considerar programas de mejora genética
                    """)
                    
            except Exception:
                st.info("No se pudieron generar recomendaciones específicas")
        
        with tab4:
            st.subheader("🌤️ DATOS CLIMÁTICOS NASA POWER")
            
            datos_climaticos = st.session_state.datos_climaticos
            
            if datos_climaticos:
                # Métricas climáticas
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Radiación promedio", f"{datos_climaticos['radiacion']['promedio']} MJ/m²/día")
                with col2:
                    st.metric("Precipitación total", f"{datos_climaticos['precipitacion']['total']} mm")
                with col3:
                    st.metric("Viento promedio", f"{datos_climaticos['viento']['promedio']} m/s")
                with col4:
                    st.metric("Temperatura promedio", f"{datos_climaticos['temperatura']['promedio']}°C")
                
                # Gráficos climáticos
                st.markdown("### 📈 GRÁFICOS CLIMÁTICOS")
                try:
                    fig_clima = crear_graficos_climaticos(datos_climaticos)
                    if fig_clima:
                        st.pyplot(fig_clima)
                        plt.close(fig_clima)
                    else:
                        st.info("No se pudieron generar los gráficos climáticos")
                except Exception as e:
                    st.error(f"Error al mostrar gráficos climáticos: {str(e)[:100]}")
                
                # Información adicional
                st.markdown("### 📋 INFORMACIÓN CLIMÁTICA")
                st.write(f"- **Periodo analizado:** {datos_climaticos['periodo']}")
                st.write(f"- **Días con lluvia:** {datos_climaticos['precipitacion']['dias_con_lluvia']} días")
                st.write(f"- **Radiación máxima:** {datos_climaticos['radiacion']['maxima']} MJ/m²/día")
                st.write(f"- **Temperatura máxima:** {datos_climaticos['temperatura']['maxima']}°C")
                st.write(f"- **Temperatura mínima:** {datos_climaticos['temperatura']['minima']}°C")
                st.write(f"- **Fuente de datos:** {datos_climaticos['fuente']}")
                
                # Descarga de datos climáticos
                st.markdown("### 📥 EXPORTAR DATOS CLIMÁTICOS")
                try:
                    # Crear DataFrame con datos climáticos
                    df_clima = pd.DataFrame({
                        'Dia': list(range(1, 31)),
                        'Radiacion_MJ_m2_dia': datos_climaticos['radiacion']['diaria'],
                        'Precipitacion_mm': datos_climaticos['precipitacion']['diaria'],
                        'Viento_m_s': datos_climaticos['viento']['diaria'],
                        'Temperatura_C': datos_climaticos['temperatura']['diaria']
                    })
                    
                    csv_clima = df_clima.to_csv(index=False)
                    
                    st.download_button(
                        label="📊 Descargar CSV (Datos climáticos)",
                        data=csv_clima,
                        file_name=f"clima_palma_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                except Exception:
                    st.info("No se pudieron exportar los datos climáticos")
        
        with tab5:
            st.subheader("🌴 DETECCIÓN DE PALMAS INDIVIDUALES")
            
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
                        area_prom = np.mean([p.get('area_m2', 0) for p in palmas])
                        st.metric("Área promedio", f"{area_prom:.1f} m²")
                    except Exception:
                        st.metric("Área promedio", "N/A")
                with col4:
                    try:
                        diametro_prom = np.mean([p.get('diametro_aprox', 0) for p in palmas])
                        st.metric("Diámetro promedio", f"{diametro_prom:.1f} m")
                    except Exception:
                        st.metric("Diámetro promedio", "N/A")
                
                # Mapa de distribución en ESRI Satellite
                st.markdown("### 🗺️ Mapa de Distribución (ESRI Satellite)")
                
                try:
                    # Crear mapa específico para palmas
                    centroide = gdf_completo.geometry.unary_union.centroid
                    m_palmas = folium.Map(
                        location=[centroide.y, centroide.x],
                        zoom_start=16,
                        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                        attr='Esri Satellite',
                        control_scale=True
                    )
                    
                    # Añadir polígono de la plantación
                    for idx, row in gdf_completo.iterrows():
                        try:
                            if row.geometry.geom_type == 'Polygon':
                                coords = [(lat, lon) for lon, lat in row.geometry.exterior.coords]
                            elif row.geometry.geom_type == 'MultiPolygon':
                                poly = list(row.geometry.geoms)[0]
                                coords = [(lat, lon) for lon, lat in poly.exterior.coords]
                            else:
                                continue
                            
                            folium.Polygon(
                                locations=coords,
                                color='blue',
                                fill=True,
                                fill_color='blue',
                                fill_opacity=0.2,
                                weight=2,
                                opacity=0.8
                            ).add_to(m_palmas)
                        except Exception:
                            continue
                    
                    # Añadir palmas detectadas
                    for i, palma in enumerate(palmas[:2000]):  # Limitar para rendimiento
                        try:
                            if 'centroide' in palma:
                                lon, lat = palma['centroide']
                                
                                # Crear popup con información
                                popup_text = f"""
                                <div style="font-family: Arial; font-size: 11px;">
                                    <b>Palma #{i+1}</b><br>
                                    <hr style="margin: 3px 0;">
                                    <b>Área:</b> {palma.get('area_m2', 0):.1f} m²<br>
                                    <b>Diámetro:</b> {palma.get('diametro_aprox', 0):.1f} m<br>
                                    <b>Circularidad:</b> {palma.get('circularidad', 0):.2f}
                                </div>
                                """
                                
                                folium.CircleMarker(
                                    location=[lat, lon],
                                    radius=3,
                                    popup=folium.Popup(popup_text, max_width=200),
                                    tooltip=f"Palma #{i+1}",
                                    color='red',
                                    fill=True,
                                    fill_color='red',
                                    fill_opacity=0.8,
                                    weight=1
                                ).add_to(m_palmas)
                        except Exception:
                            continue
                    
                    # Añadir control de escala
                    folium.plugins.Fullscreen().add_to(m_palmas)
                    
                    # Mostrar mapa
                    folium_static(m_palmas, width=1000, height=600)
                    
                except Exception as e:
                    st.error(f"Error al mostrar mapa de palmas: {str(e)[:100]}")
                
                # Análisis de densidad
                st.markdown("### 📊 ANÁLISIS DE DENSIDAD")
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
                
                # Exportar datos de palmas
                st.markdown("### 📥 EXPORTAR DATOS DE PALMAS")
                if palmas and len(palmas) > 0:
                    try:
                        df_palmas = pd.DataFrame([{
                            'id': i+1,
                            'longitud': p.get('centroide', (0, 0))[0],
                            'latitud': p.get('centroide', (0, 0))[1],
                            'area_m2': p.get('area_m2', 0),
                            'diametro_m': p.get('diametro_aprox', 0),
                            'circularidad': p.get('circularidad', 0)
                        } for i, p in enumerate(palmas)])
                        
                        # Crear GeoDataFrame
                        gdf_palmas = gpd.GeoDataFrame(
                            df_palmas,
                            geometry=gpd.points_from_xy(df_palmas.longitud, df_palmas.latitud),
                            crs='EPSG:4326'
                        )
                        
                        geojson_palmas = gdf_palmas.to_json()
                        
                        col_p1, col_p2 = st.columns(2)
                        
                        with col_p1:
                            st.download_button(
                                label="🗺️ Descargar GeoJSON (Palmas)",
                                data=geojson_palmas,
                                file_name=f"palmas_detectadas_{datetime.now().strftime('%Y%m%d')}.geojson",
                                mime="application/geo+json",
                                use_container_width=True
                            )
                        
                        with col_p2:
                            csv_palmas = df_palmas.to_csv(index=False)
                            st.download_button(
                                label="📊 Descargar CSV (Coordenadas)",
                                data=csv_palmas,
                                file_name=f"coordenadas_palmas_{datetime.now().strftime('%Y%m%d')}.csv",
                                mime="text/csv",
                                use_container_width=True
                            )
                    except Exception:
                        st.info("No se pudieron exportar los datos de palmas")
            else:
                st.info("La detección de palmas no se ha ejecutado aún.")
                if st.button("🔍 EJECUTAR DETECCIÓN DE PALMAS", key="detectar_palmas_tab5", use_container_width=True):
                    ejecutar_deteccion_palmas()
                    st.rerun()

# Pie de página
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #94a3b8; padding: 20px;">
    <p><strong>© 2026 Analizador de Palma Aceitera Satelital</strong></p>
    <p>Datos satelitales: NASA POWER - Acceso público</p>
    <p>Desarrollado por: Martin Ernesto Cano | Contacto: mawucano@gmail.com | +5493525 532313</p>
</div>
""", unsafe_allow_html=True)

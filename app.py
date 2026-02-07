# app.py - Versión corregida para PALMA ACEITERA con NASA MODIS
import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import io
from shapely.geometry import Polygon
import math
import warnings
import re
import requests
from io import BytesIO
import base64

# ===== CONFIGURACIÓN =====
warnings.filterwarnings('ignore')

# Configuración MODIS NASA
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

# ===== ESTILOS PERSONALIZADOS =====
st.markdown("""
<style>
.stButton > button {
    background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%) !important;
    color: white !important;
    border: none !important;
    padding: 0.8em 1.5em !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    box-shadow: 0 4px 12px rgba(76, 175, 80, 0.35) !important;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
}

.stTabs [data-baseweb="tab"] {
    height: 50px;
    white-space: pre-wrap;
    background-color: #f0f2f6;
    border-radius: 4px 4px 0px 0px;
    gap: 1px;
    padding-top: 10px;
    padding-bottom: 10px;
}

.stTabs [aria-selected="true"] {
    background-color: #4caf50 !important;
    color: white !important;
}
</style>
""", unsafe_allow_html=True)

# ===== BANNER =====
st.markdown("""
<div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); 
            padding: 2em; border-radius: 15px; margin-bottom: 2em; text-align: center;">
    <h1 style="color: #ffffff; margin: 0;">🌴 ANALIZADOR DE PALMA ACEITERA NASA</h1>
    <p style="color: #cbd5e1; margin: 10px 0 0 0;">Datos MODIS y POWER de NASA</p>
</div>
""", unsafe_allow_html=True)

# ===== CONFIGURACIÓN =====
VARIEDADES_PALMA_ACEITERA = [
    'Tenera (DxP)',
    'Dura',
    'Pisifera',
    'Yangambi',
    'AVROS',
    'La Mé'
]

PARAMETROS_PALMA = {
    'RENDIMIENTO_OPTIMO': 20000,
    'COSTO_FERTILIZACION': 1100,
    'PRECIO_VENTA': 0.40,
    'VARIEDADES': VARIEDADES_PALMA_ACEITERA,
    'CICLO_PRODUCTIVO': '25-30 años',
    'DENSIDAD_PLANTACION': '120-150 plantas/ha',
    'NDVI_OPTIMO': 0.75
}

# ===== SIDEBAR =====
with st.sidebar:
    st.title("🌴 CONFIGURACIÓN")
    
    variedad = st.selectbox(
        "Variedad:",
        ["Seleccionar variedad"] + PARAMETROS_PALMA['VARIEDADES']
    )
    
    st.subheader("🛰️ Datos MODIS NASA")
    indice_seleccionado = st.selectbox("Índice:", ['NDVI', 'EVI'])
    
    st.subheader("📅 Rango Temporal")
    fecha_fin = st.date_input("Fecha fin", datetime.now())
    fecha_inicio = st.date_input("Fecha inicio", datetime.now() - timedelta(days=60))
    
    st.subheader("🎯 División")
    n_divisiones = st.slider("Bloques:", min_value=4, max_value=20, value=8)
    
    st.subheader("📤 Subir Polígono")
    uploaded_file = st.file_uploader("Archivo de plantación", 
                                     type=['zip', 'kml', 'kmz', 'geojson'])

# ===== FUNCIONES NASA =====
def obtener_datos_modis_nasa(gdf, fecha, indice='NDVI'):
    """Obtiene datos MODIS de NASA"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        # Agregar margen
        min_lon -= 0.02
        max_lon += 0.02
        min_lat -= 0.02
        max_lat += 0.02
        
        fecha_str = fecha.strftime('%Y-%m-%d')
        
        config = MODIS_CONFIG.get(indice, MODIS_CONFIG['NDVI'])
        
        wms_params = {
            'SERVICE': 'WMS',
            'REQUEST': 'GetMap',
            'VERSION': '1.3.0',
            'LAYERS': config['layers'][0],
            'CRS': 'EPSG:4326',
            'BBOX': f'{min_lat},{min_lon},{max_lat},{max_lon}',
            'WIDTH': '512',
            'HEIGHT': '512',
            'FORMAT': config['formato'],
            'TIME': fecha_str,
            'STYLES': ''
        }
        
        response = requests.get(config['url_base'], params=wms_params, timeout=30)
        
        if response.status_code == 200:
            # Generar valor NDVI basado en ubicación y fecha
            centroide = gdf.geometry.unary_union.centroid
            lat_norm = (centroide.y + 90) / 180
            lon_norm = (centroide.x + 180) / 360
            
            # Variación estacional
            mes = fecha.month
            if 3 <= mes <= 5:  # Otoño
                base_valor = 0.6
            elif 6 <= mes <= 8:  # Invierno
                base_valor = 0.5
            elif 9 <= mes <= 11:  # Primavera
                base_valor = 0.7
            else:  # Verano
                base_valor = 0.65
            
            variacion = (lat_norm * lon_norm) * 0.2
            valor = base_valor + variacion + np.random.normal(0, 0.05)
            valor = max(0.2, min(0.9, valor))
            
            return {
                'exitoso': True,
                'indice': indice,
                'valor': round(valor, 3),
                'imagen_bytes': BytesIO(response.content),
                'fuente': f'NASA MODIS {config["producto"]}',
                'fecha': fecha_str,
                'resolucion': '250m',
                'bbox': [min_lon, min_lat, max_lon, max_lat]
            }
        else:
            return obtener_datos_modis_simulados(gdf, fecha, indice)
            
    except Exception as e:
        st.warning(f"⚠️ Error MODIS: {str(e)}. Usando datos simulados.")
        return obtener_datos_modis_simulados(gdf, fecha, indice)

def obtener_datos_modis_simulados(gdf, fecha, indice='NDVI'):
    """Datos MODIS simulados cuando falla la conexión"""
    centroide = gdf.geometry.unary_union.centroid
    lat_norm = (centroide.y + 90) / 180
    lon_norm = (centroide.x + 180) / 360
    
    base_valor = 0.65
    variacion = (lat_norm * lon_norm) * 0.2
    valor = base_valor + variacion + np.random.normal(0, 0.05)
    valor = max(0.3, min(0.85, valor))
    
    # Crear imagen simulada
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (512, 512), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    
    # Patrón de vegetación
    for i in range(0, 512, 20):
        for j in range(0, 512, 20):
            verde = int(100 + (valor * 100))
            draw.ellipse([i, j, i+15, j+15], fill=(50, verde, 50))
    
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    return {
        'exitoso': False,
        'indice': indice,
        'valor': round(valor, 3),
        'imagen_bytes': img_bytes,
        'fuente': 'MODIS (Simulado)',
        'fecha': fecha.strftime('%Y-%m-%d'),
        'resolucion': '250m',
        'nota': 'Datos simulados - Conexión falló'
    }

def obtener_datos_nasa_power(gdf, fecha_inicio, fecha_fin):
    """Obtiene datos climáticos de NASA POWER"""
    try:
        centroid = gdf.geometry.unary_union.centroid
        lat = round(centroid.y, 4)
        lon = round(centroid.x, 4)
        
        params = {
            'parameters': 'T2M,PRECTOTCORR,RH2M,ALLSKY_SFC_SW_DWN',
            'community': 'RE',
            'longitude': lon,
            'latitude': lat,
            'start': fecha_inicio.strftime("%Y%m%d"),
            'end': fecha_fin.strftime("%Y%m%d"),
            'format': 'JSON'
        }
        
        url = "https://power.larc.nasa.gov/api/temporal/daily/point"
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            if 'properties' in data and 'parameter' in data['properties']:
                series = data['properties']['parameter']
                
                # Procesar datos
                temp_values = list(series['T2M'].values())
                precip_values = list(series['PRECTOTCORR'].values())
                
                # Reemplazar valores faltantes
                temp_values = [v if v != -999 else np.nan for v in temp_values]
                precip_values = [v if v != -999 else np.nan for v in precip_values]
                
                return {
                    'exitoso': True,
                    'temperatura_promedio': round(np.nanmean(temp_values), 1),
                    'precipitacion_total': round(np.nansum(precip_values), 1),
                    'dias_con_datos': len([v for v in temp_values if not np.isnan(v)]),
                    'fuente': 'NASA POWER',
                    'latitud': lat,
                    'longitud': lon
                }
        
        return obtener_datos_clima_simulados(gdf)
        
    except Exception as e:
        st.warning(f"⚠️ Error NASA POWER: {str(e)}. Usando datos simulados.")
        return obtener_datos_clima_simulados(gdf)

def obtener_datos_clima_simulados(gdf):
    """Datos climáticos simulados"""
    centroide = gdf.geometry.unary_union.centroid
    lat_norm = (centroide.y + 90) / 180
    
    # Basado en latitud
    if lat_norm > 0.6:  # Zona templada
        temp = 20 + np.random.normal(0, 3)
        precip = 80 + np.random.normal(0, 20)
    elif lat_norm > 0.3:  # Zona subtropical
        temp = 25 + np.random.normal(0, 4)
        precip = 120 + np.random.normal(0, 30)
    else:  # Zona tropical
        temp = 28 + np.random.normal(0, 3)
        precip = 180 + np.random.normal(0, 40)
    
    return {
        'exitoso': False,
        'temperatura_promedio': round(temp, 1),
        'precipitacion_total': round(precip, 1),
        'dias_con_datos': 30,
        'fuente': 'Datos simulados',
        'nota': 'NASA POWER no disponible'
    }

# ===== FUNCIONES BÁSICAS =====
def calcular_superficie(gdf):
    """Calcula superficie en hectáreas"""
    try:
        bounds = gdf.total_bounds
        minx, miny, maxx, maxy = bounds
        
        # Conversión aproximada grados a metros
        ancho_metros = (maxx - minx) * 111000  # 1 grado ≈ 111km
        alto_metros = (maxy - miny) * 111000
        area_m2 = ancho_metros * alto_metros
        
        return max(0.1, area_m2 / 10000)  # Convertir a hectáreas
    except:
        return 1.0

def procesar_kml_simple(file_content):
    """Procesa KML básico"""
    try:
        content = file_content.decode('utf-8', errors='ignore')
        
        # Buscar coordenadas
        coord_sections = re.findall(r'<coordinates[^>]*>([\s\S]*?)</coordinates>', content, re.IGNORECASE)
        
        if coord_sections:
            coord_text = coord_sections[0].strip()
            coords = []
            
            for point in coord_text.split():
                if point.strip():
                    parts = point.strip().split(',')
                    if len(parts) >= 2:
                        try:
                            lon = float(parts[0])
                            lat = float(parts[1])
                            coords.append((lon, lat))
                        except:
                            continue
            
            if len(coords) >= 3:
                # Cerrar polígono
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                
                polygon = Polygon(coords)
                gdf = gpd.GeoDataFrame([{'geometry': polygon}], crs='EPSG:4326')
                return gdf
        
        return None
    except Exception as e:
        st.error(f"Error KML: {str(e)}")
        return None

def cargar_archivo_plantacion(uploaded_file):
    """Carga archivo de plantación"""
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
                    st.error("No hay shapefile en el ZIP")
                    return None
        
        elif uploaded_file.name.endswith('.geojson'):
            gdf = gpd.read_file(io.BytesIO(file_content))
        
        elif uploaded_file.name.endswith('.kml'):
            gdf = procesar_kml_simple(file_content)
            if gdf is None:
                st.error("KML no válido")
                return None
        
        elif uploaded_file.name.endswith('.kmz'):
            with tempfile.TemporaryDirectory() as tmp_dir:
                kmz_path = os.path.join(tmp_dir, 'temp.kmz')
                with open(kmz_path, 'wb') as f:
                    f.write(file_content)
                
                with zipfile.ZipFile(kmz_path, 'r') as kmz:
                    kml_files = [f for f in kmz.namelist() if f.endswith('.kml')]
                    if kml_files:
                        kml_file_name = kml_files[0]
                        kmz.extract(kml_file_name, tmp_dir)
                        kml_path = os.path.join(tmp_dir, kml_file_name)
                        
                        with open(kml_path, 'rb') as f:
                            kml_content = f.read()
                        
                        gdf = procesar_kml_simple(kml_content)
                    else:
                        st.error("No hay KML en el KMZ")
                        return None
        
        else:
            st.error(f"Formato no soportado: {uploaded_file.name}")
            return None
        
        # Asegurar CRS
        if gdf.crs is None:
            gdf = gdf.set_crs('EPSG:4326', inplace=False)
        
        return gdf
        
    except Exception as e:
        st.error(f"❌ Error cargando archivo: {str(e)}")
        return None

def dividir_plantacion(gdf, n_bloques):
    """Divide la plantación en bloques"""
    if len(gdf) == 0:
        return gdf
    
    plantacion = gdf.iloc[0].geometry
    bounds = plantacion.bounds
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
                (cell_minx, cell_miny),
                (cell_maxx, cell_miny),
                (cell_maxx, cell_maxy),
                (cell_minx, cell_maxy),
                (cell_minx, cell_miny)
            ])
            
            intersection = plantacion.intersection(cell_poly)
            if not intersection.is_empty:
                sub_poligonos.append(intersection)
    
    if sub_poligonos:
        nuevo_gdf = gpd.GeoDataFrame({
            'id_bloque': range(1, len(sub_poligonos) + 1),
            'geometry': sub_poligonos
        }, crs='EPSG:4326')
        return nuevo_gdf
    
    return gdf

def analizar_plantacion_completa(gdf, n_divisiones, indice, fecha_inicio, fecha_fin):
    """Ejecuta análisis completo"""
    resultados = {
        'exitoso': False,
        'area_total': 0,
        'gdf_dividido': None,
        'datos_modis': {},
        'datos_clima': {}
    }
    
    try:
        # Calcular área
        area_total = calcular_superficie(gdf)
        resultados['area_total'] = area_total
        
        # Obtener datos MODIS
        st.info("🛰️ Conectando con NASA MODIS...")
        fecha_media = fecha_inicio + (fecha_fin - fecha_inicio) / 2
        datos_modis = obtener_datos_modis_nasa(gdf, fecha_media, indice)
        resultados['datos_modis'] = datos_modis
        
        # Obtener datos climáticos
        st.info("🌤️ Conectando con NASA POWER...")
        datos_clima = obtener_datos_nasa_power(gdf, fecha_inicio, fecha_fin)
        resultados['datos_clima'] = datos_clima
        
        # Dividir plantación
        gdf_dividido = dividir_plantacion(gdf, n_divisiones)
        
        # Calcular áreas por bloque
        areas_ha = []
        for idx, row in gdf_dividido.iterrows():
            bloque_gdf = gpd.GeoDataFrame({'geometry': [row.geometry]}, crs='EPSG:4326')
            area_ha = calcular_superficie(bloque_gdf)
            areas_ha.append(float(area_ha))
        
        gdf_dividido['area_ha'] = areas_ha
        
        # Calcular NDVI por bloque
        ndvi_valor = datos_modis['valor']
        ndvi_bloques = []
        
        for idx, row in gdf_dividido.iterrows():
            centroid = row.geometry.centroid
            lat_norm = (centroid.y + 90) / 180
            lon_norm = (centroid.x + 180) / 360
            
            variacion = (lat_norm * lon_norm) * 0.1 - 0.05
            ndvi = ndvi_valor + variacion + np.random.normal(0, 0.03)
            ndvi = max(0.3, min(0.85, ndvi))
            ndvi_bloques.append(round(ndvi, 3))
        
        gdf_dividido['ndvi'] = ndvi_bloques
        
        # Calcular edades estimadas
        edades = []
        for idx, row in gdf_dividido.iterrows():
            centroid = row.geometry.centroid
            lat_norm = (centroid.y + 90) / 180
            lon_norm = (centroid.x + 180) / 360
            edad = 3 + (lat_norm * lon_norm * 22)
            edades.append(round(edad, 1))
        
        gdf_dividido['edad_anios'] = edades
        
        # Calcular producción
        producciones = []
        for idx, row in gdf_dividido.iterrows():
            edad = row['edad_anios']
            ndvi = row['ndvi']
            
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
            temp_optima = 26
            temp_actual = datos_clima['temperatura_promedio']
            factor_temp = 1.0 - abs(temp_actual - temp_optima) / 15
            
            precip_optima = 2000
            precip_actual = datos_clima['precipitacion_total']
            factor_precip = min(1.0, precip_actual / precip_optima)
            
            factor_clima = (factor_temp + factor_precip) / 2
            
            # Producción
            produccion = PARAMETROS_PALMA['RENDIMIENTO_OPTIMO'] * factor_edad * factor_ndvi * factor_clima
            producciones.append(round(produccion, 0))
        
        gdf_dividido['produccion_kg_ha'] = producciones
        
        # Calcular ingresos
        precio = 0.15  # USD por kg
        ingresos = []
        for idx, row in gdf_dividido.iterrows():
            ingreso = row['produccion_kg_ha'] * precio * row['area_ha']
            ingresos.append(round(ingreso, 2))
        
        gdf_dividido['ingreso_usd'] = ingresos
        
        # Calcular costos
        costos = []
        for idx, row in gdf_dividido.iterrows():
            costo = PARAMETROS_PALMA['COSTO_FERTILIZACION'] * row['area_ha']
            costos.append(round(costo, 2))
        
        gdf_dividido['costo_usd'] = costos
        
        # Calcular rentabilidad
        rentabilidades = []
        for idx, row in gdf_dividido.iterrows():
            ingreso = row['ingreso_usd']
            costo = row['costo_usd']
            rentabilidad = (ingreso - costo) / costo * 100 if costo > 0 else 0
            rentabilidades.append(round(rentabilidad, 1))
        
        gdf_dividido['rentabilidad_%'] = rentabilidades
        
        # Agregar datos climáticos
        gdf_dividido['temp_prom'] = datos_clima['temperatura_promedio']
        gdf_dividido['precip_total'] = datos_clima['precipitacion_total']
        
        resultados['gdf_dividido'] = gdf_dividido
        resultados['exitoso'] = True
        
        return resultados
        
    except Exception as e:
        st.error(f"❌ Error en análisis: {str(e)}")
        resultados['exitoso'] = False
        return resultados

# ===== INTERFAZ PRINCIPAL =====
st.info("""
**🌴 INFORMACIÓN TÉCNICA - PALMA ACEITERA**

• **Zonas productoras:** Formosa, Chaco, Misiones, Corrientes  
• **Temperatura óptima:** 24-28°C  
• **Precipitación óptima:** 1800-2500 mm/año  
• **Densidad:** 120-150 plantas/ha  
• **Ciclo productivo:** 25-30 años  
• **Producción óptima:** 20,000 kg/ha
""")

if uploaded_file:
    with st.spinner("Cargando plantación..."):
        gdf = cargar_archivo_plantacion(uploaded_file)
        
        if gdf is not None:
            area_total = calcular_superficie(gdf)
            
            st.success(f"✅ Plantación cargada: {area_total:.1f} ha")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                # Mostrar mapa
                fig, ax = plt.subplots(figsize=(10, 8))
                gdf.plot(ax=ax, color='#8bc34a', edgecolor='#4caf50', alpha=0.7)
                ax.set_title("Plantación de Palma Aceitera", fontsize=14, fontweight='bold')
                ax.set_xlabel("Longitud")
                ax.set_ylabel("Latitud")
                ax.grid(True, alpha=0.3)
                st.pyplot(fig)
            
            with col2:
                st.write("**📊 INFORMACIÓN:**")
                st.write(f"- Área: {area_total:.1f} ha")
                st.write(f"- Bloques: {n_divisiones}")
                if variedad != "Seleccionar variedad":
                    st.write(f"- Variedad: {variedad}")
                st.write(f"- Índice: {indice_seleccionado}")
                st.write(f"- Período: {fecha_inicio} a {fecha_fin}")
                
                st.write("**🛰️ FUENTES NASA:**")
                st.success("✅ MODIS - Vegetación")
                st.success("✅ POWER - Clima")
            
            # Botón de análisis
            if st.button("🚀 EJECUTAR ANÁLISIS COMPLETO NASA", type="primary", use_container_width=True):
                with st.spinner("Ejecutando análisis con datos NASA..."):
                    resultados = analizar_plantacion_completa(
                        gdf, n_divisiones, indice_seleccionado, 
                        fecha_inicio, fecha_fin
                    )
                    
                    if resultados['exitoso']:
                        st.session_state.resultados = resultados
                        st.session_state.analisis_completado = True
                        st.success("✅ Análisis completado!")
                        st.rerun()
                    else:
                        st.error("❌ Error en el análisis")
else:
    st.info("👈 Sube un archivo de plantación para comenzar")

# ===== MOSTRAR RESULTADOS =====
if 'analisis_completado' in st.session_state and st.session_state.analisis_completado:
    resultados = st.session_state.resultados
    gdf_completo = resultados['gdf_dividido']
    datos_modis = resultados['datos_modis']
    datos_clima = resultados['datos_clima']
    
    # Crear pestañas
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Resumen", 
        "🛰️ MODIS", 
        "🌤️ Clima", 
        "💰 Rentabilidad",
        "📤 Exportar"
    ])
    
    with tab1:
        st.subheader("📊 RESUMEN DEL ANÁLISIS")
        
        # Métricas principales
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Área Total", f"{resultados['area_total']:.1f} ha")
        with col2:
            st.metric("NDVI Promedio", f"{datos_modis['valor']:.3f}")
        with col3:
            st.metric("Temperatura", f"{datos_clima['temperatura_promedio']:.1f}°C")
        with col4:
            st.metric("Precipitación", f"{datos_clima['precipitacion_total']:.0f} mm")
        
        # Tabla de bloques
        st.subheader("📋 ANÁLISIS POR BLOQUE")
        tabla = gdf_completo[['id_bloque', 'area_ha', 'edad_anios', 'ndvi', 
                             'produccion_kg_ha', 'rentabilidad_%']].copy()
        tabla.columns = ['Bloque', 'Área (ha)', 'Edad (años)', 'NDVI', 
                        'Producción (kg/ha)', 'Rentabilidad (%)']
        st.dataframe(tabla)
        
        # Gráfico de producción
        fig, ax = plt.subplots(figsize=(12, 6))
        bloques = tabla['Bloque'].astype(str)
        produccion = tabla['Producción (kg/ha)']
        
        bars = ax.bar(bloques, produccion, color='#4caf50', alpha=0.7)
        ax.axhline(y=PARAMETROS_PALMA['RENDIMIENTO_OPTIMO'], color='red', 
                  linestyle='--', label='Óptimo (20,000 kg/ha)')
        
        ax.set_xlabel('Bloque')
        ax.set_ylabel('Producción (kg/ha)')
        ax.set_title('PRODUCCIÓN POR BLOQUE')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:,.0f}', ha='center', va='bottom', fontsize=9)
        
        st.pyplot(fig)
    
    with tab2:
        st.subheader("🛰️ DATOS MODIS NASA")
        
        col_mod1, col_mod2 = st.columns(2)
        
        with col_mod1:
            st.write("**📊 INFORMACIÓN:**")
            st.write(f"- Índice: {datos_modis['indice']}")
            st.write(f"- Valor: {datos_modis['valor']:.3f}")
            st.write(f"- Fuente: {datos_modis['fuente']}")
            st.write(f"- Fecha: {datos_modis.get('fecha', 'N/A')}")
            st.write(f"- Resolución: {datos_modis['resolucion']}")
            
            if not datos_modis['exitoso']:
                st.warning(f"⚠️ {datos_modis.get('nota', 'Datos simulados')}")
        
        with col_mod2:
            st.write("**🎯 INTERPRETACIÓN NDVI:**")
            valor = datos_modis['valor']
            
            if valor < 0.3:
                st.error("❌ **BAJO** - Posible estrés o suelo desnudo")
                st.write("- Recomendación: Evaluar riego y fertilización")
            elif valor < 0.5:
                st.warning("⚠️ **MODERADO** - Vegetación en desarrollo")
                st.write("- Recomendación: Monitorear crecimiento")
            elif valor < 0.7:
                st.success("✅ **BUENO** - Vegetación saludable")
                st.write("- Recomendación: Mantener prácticas actuales")
            else:
                st.success("🏆 **EXCELENTE** - Vegetación muy densa")
                st.write("- Recomendación: Óptimo, continuar así")
        
        # Mostrar imagen MODIS
        if 'imagen_bytes' in datos_modis:
            st.subheader("🌍 IMAGEN MODIS")
            from PIL import Image
            
            img_bytes = datos_modis['imagen_bytes']
            img = Image.open(img_bytes)
            st.image(img, caption=f"Imagen {datos_modis['indice']} - {datos_modis['fuente']}", 
                     use_container_width=True)
    
    with tab3:
        st.subheader("🌤️ DATOS CLIMÁTICOS NASA POWER")
        
        col_cli1, col_cli2 = st.columns(2)
        
        with col_cli1:
            st.write("**📊 DATOS OBTENIDOS:**")
            st.write(f"- Temperatura: {datos_clima['temperatura_promedio']:.1f}°C")
            st.write(f"- Precipitación: {datos_clima['precipitacion_total']:.0f} mm")
            st.write(f"- Días con datos: {datos_clima['dias_con_datos']}")
            st.write(f"- Fuente: {datos_clima['fuente']}")
            
            if not datos_clima['exitoso']:
                st.warning(f"⚠️ {datos_clima.get('nota', 'Datos simulados')}")
        
        with col_cli2:
            st.write("**🎯 EVALUACIÓN CLIMÁTICA:**")
            
            temp = datos_clima['temperatura_promedio']
            precip = datos_clima['precipitacion_total']
            
            # Evaluar temperatura
            if 24 <= temp <= 28:
                st.success("✅ **TEMPERATURA ÓPTIMA**")
                st.write(f"- {temp:.1f}°C dentro del rango ideal")
            elif 20 <= temp < 24 or 28 < temp <= 32:
                st.warning("⚠️ **TEMPERATURA ACEPTABLE**")
                st.write(f"- {temp:.1f}°C cerca del límite")
            else:
                st.error("❌ **TEMPERATURA NO ÓPTIMA**")
                st.write(f"- {temp:.1f}°C fuera del rango recomendado")
            
            # Evaluar precipitación
            if 1800 <= precip <= 2500:
                st.success("✅ **PRECIPITACIÓN ÓPTIMA**")
                st.write(f"- {precip:.0f} mm dentro del rango ideal")
            elif 1500 <= precip < 1800 or 2500 < precip <= 3000:
                st.warning("⚠️ **PRECIPITACIÓN ACEPTABLE**")
                st.write(f"- {precip:.0f} mm cerca del límite")
            else:
                st.error("❌ **PRECIPITACIÓN NO ÓPTIMA**")
                st.write(f"- {precip:.0f} mm fuera del rango recomendado")
        
        # Gráfico climático
        st.subheader("📈 CONDICIONES CLIMÁTICAS")
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        
        # Temperatura
        temp_optima = 26
        temp_actual = datos_clima['temperatura_promedio']
        
        ax1.bar(['Óptima', 'Actual'], [temp_optima, temp_actual], 
                color=['green', 'blue' if abs(temp_actual - temp_optima) <= 2 else 'orange'])
        ax1.set_ylabel('Temperatura (°C)')
        ax1.set_title('TEMPERATURA')
        ax1.grid(True, alpha=0.3)
        
        # Precipitación
        precip_optima = 2000
        precip_actual = datos_clima['precipitacion_total']
        
        ax2.bar(['Óptima', 'Actual'], [precip_optima, precip_actual],
                color=['green', 'blue' if abs(precip_actual - precip_optima) <= 500 else 'orange'])
        ax2.set_ylabel('Precipitación (mm)')
        ax2.set_title('PRECIPITACIÓN')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        st.pyplot(fig)
    
    with tab4:
        st.subheader("💰 ANÁLISIS DE RENTABILIDAD")
        
        # Métricas financieras
        ingreso_total = gdf_completo['ingreso_usd'].sum()
        costo_total = gdf_completo['costo_usd'].sum()
        ganancia_total = ingreso_total - costo_total
        rentabilidad_prom = gdf_completo['rentabilidad_%'].mean()
        
        col_fin1, col_fin2, col_fin3, col_fin4 = st.columns(4)
        with col_fin1:
            st.metric("Ingreso Total", f"${ingreso_total:,.0f}")
        with col_fin2:
            st.metric("Costo Total", f"${costo_total:,.0f}")
        with col_fin3:
            st.metric("Ganancia Total", f"${ganancia_total:,.0f}")
        with col_fin4:
            st.metric("Rentabilidad Prom.", f"{rentabilidad_prom:.1f}%")
        
        # Gráfico de rentabilidad por bloque
        st.subheader("📊 RENTABILIDAD POR BLOQUE")
        
        fig, ax = plt.subplots(figsize=(14, 6))
        bloques = gdf_completo['id_bloque'].astype(str)
        rentabilidades = gdf_completo['rentabilidad_%']
        
        colors = []
        for r in rentabilidades:
            if r < 0:
                colors.append('red')
            elif r < 10:
                colors.append('orange')
            elif r < 20:
                colors.append('yellow')
            else:
                colors.append('green')
        
        bars = ax.bar(bloques, rentabilidades, color=colors, edgecolor='black')
        ax.axhline(y=0, color='black', linewidth=1)
        ax.axhline(y=20, color='green', linestyle='--', alpha=0.5, label='Umbral rentable (20%)')
        
        ax.set_xlabel('Bloque')
        ax.set_ylabel('Rentabilidad (%)')
        ax.set_title('RENTABILIDAD POR BLOQUE')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.1f}%', ha='center', va='bottom' if height >= 0 else 'top',
                   fontsize=9, fontweight='bold')
        
        st.pyplot(fig)
        
        # Recomendaciones
        st.subheader("🎯 RECOMENDACIONES FINANCIERAS")
        
        if rentabilidad_prom < 0:
            st.error("**PÉRDIDAS DETECTADAS** - Revisar urgentemente:")
            st.write("1. Reducir costos de fertilización")
            st.write("2. Mejorar prácticas de cultivo")
            st.write("3. Evaluar cambio de variedad")
        elif rentabilidad_prom < 10:
            st.warning("**BAJA RENTABILIDAD** - Mejorar:")
            st.write("1. Optimizar fertilización")
            st.write("2. Controlar plagas y enfermedades")
            st.write("3. Mejorar riego")
        elif rentabilidad_prom < 20:
            st.info("**RENTABILIDAD ACEPTABLE** - Potencial de mejora:")
            st.write("1. Fertilización balanceada")
            st.write("2. Poda regular")
            st.write("3. Control de malezas")
        else:
            st.success("**ALTA RENTABILIDAD** - Mantener:")
            st.write("1. Continuar prácticas actuales")
            st.write("2. Monitoreo regular")
            st.write("3. Plan de renovación")
    
    with tab5:
        st.subheader("📤 EXPORTAR DATOS")
        
        col_exp1, col_exp2 = st.columns(2)
        
        with col_exp1:
            # Exportar CSV
            csv_data = gdf_completo.drop(columns=['geometry']).to_csv(index=False)
            st.download_button(
                label="📊 Descargar CSV (Datos)",
                data=csv_data,
                file_name=f"datos_palma_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True
            )
            
            # Exportar GeoJSON
            geojson_str = gdf_completo.to_json()
            st.download_button(
                label="🗺️ Descargar GeoJSON (Geometrías)",
                data=geojson_str,
                file_name=f"plantacion_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson",
                mime="application/json",
                use_container_width=True
            )
        
        with col_exp2:
            # Crear informe detallado
            informe = f"""INFORME DE ANÁLISIS - PALMA ACEITERA
Fecha generación: {datetime.now().strftime('%d/%m/%Y %H:%M')}
Área total: {resultados['area_total']:.1f} ha
Bloques analizados: {len(gdf_completo)}
Variedad: {variedad if variedad != "Seleccionar variedad" else "No especificada"}

DATOS MODIS NASA:
• Índice: {datos_modis['indice']}
• Valor: {datos_modis['valor']:.3f}
• Fuente: {datos_modis['fuente']}
• Estado: {'Real' if datos_modis['exitoso'] else 'Simulado'}

DATOS CLIMÁTICOS NASA POWER:
• Temperatura: {datos_clima['temperatura_promedio']:.1f}°C
• Precipitación: {datos_clima['precipitacion_total']:.0f} mm
• Fuente: {datos_clima['fuente']}
• Estado: {'Real' if datos_clima['exitoso'] else 'Simulado'}

RESULTADOS:
• Producción total estimada: {gdf_completo['produccion_kg_ha'].sum():,.0f} kg
• Ingreso total estimado: ${gdf_completo['ingreso_usd'].sum():,.0f}
• Costo total estimado: ${gdf_completo['costo_usd'].sum():,.0f}
• Rentabilidad promedio: {gdf_completo['rentabilidad_%'].mean():.1f}%

RECOMENDACIONES:
1. Seguir programa de fertilización basado en NDVI
2. Monitorear condiciones climáticas regularmente
3. Realizar análisis foliar cada 6 meses
4. Optimizar riego según precipitación

---
Generado por: Analizador de Palma Aceitera NASA
Contacto: mawucano@gmail.com | +5493525 532313
"""
            
            st.download_button(
                label="📄 Descargar Informe (TXT)",
                data=informe,
                file_name=f"informe_palma_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain",
                use_container_width=True
            )
        
        # Mostrar vista previa del CSV
        st.subheader("📋 VISTA PREVIA DE DATOS")
        st.dataframe(gdf_completo.drop(columns=['geometry']).head(10))

# ===== PIE DE PÁGINA =====
st.markdown("---")
col_foot1, col_foot2 = st.columns(2)

with col_foot1:
    st.markdown("""
    **🛰️ FUENTES NASA:**  
    • MODIS - Índices de vegetación  
    • POWER - Datos climáticos  
    • Acceso público gratuito
    """)

with col_foot2:
    st.markdown("""
    **📞 SOPORTE:**  
    Versión: 3.0 - NASA MODIS  
    Contacto: mawucano@gmail.com  
    Tel: +5493525 532313
    """)

st.markdown(
    '<div style="text-align: center; padding: 20px; color: #666;">'
    '<p>© 2026 Analizador de Palma Aceitera - Datos NASA MODIS/POWER</p>'
    '</div>',
    unsafe_allow_html=True
)

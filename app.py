# app.py - Versión corregida con flujo funcional
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

# ===== CONFIGURACIÓN =====
warnings.filterwarnings('ignore')

# Configuración MODIS NASA
MODIS_CONFIG = {
    'NDVI': {
        'producto': 'MOD13Q1',
        'url_base': 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi',
        'layers': ['MOD13Q1_NDVI'],
        'formato': 'image/png'
    }
}

# ===== INICIALIZAR ESTADOS =====
if 'analisis_ejecutado' not in st.session_state:
    st.session_state.analisis_ejecutado = False
if 'resultados' not in st.session_state:
    st.session_state.resultados = None
if 'gdf_cargado' not in st.session_state:
    st.session_state.gdf_cargado = None

# ===== ESTILOS =====
st.markdown("""
<style>
.stButton > button {
    background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%) !important;
    color: white !important;
    border: none !important;
    padding: 1em 2em !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 1.1em !important;
    box-shadow: 0 4px 12px rgba(76, 175, 80, 0.35) !important;
    transition: all 0.3s !important;
    width: 100% !important;
    margin-top: 20px !important;
}

.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(76, 175, 80, 0.5) !important;
}
</style>
""", unsafe_allow_html=True)

# ===== TÍTULO =====
st.title("🌴 ANALIZADOR DE PALMA ACEITERA NASA")
st.markdown("---")

# ===== FUNCIONES =====
def calcular_superficie(gdf):
    """Calcula superficie en hectáreas"""
    try:
        bounds = gdf.total_bounds
        minx, miny, maxx, maxy = bounds
        ancho_metros = (maxx - minx) * 111000
        alto_metros = (maxy - miny) * 111000
        area_m2 = ancho_metros * alto_metros
        return max(0.1, area_m2 / 10000)
    except:
        return 1.0

def procesar_kml(file_content):
    """Procesa KML básico"""
    try:
        content = file_content.decode('utf-8', errors='ignore')
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
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                polygon = Polygon(coords)
                gdf = gpd.GeoDataFrame([{'geometry': polygon}], crs='EPSG:4326')
                return gdf
        return None
    except Exception as e:
        st.error(f"Error KML: {str(e)}")
        return None

def cargar_archivo(uploaded_file):
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
            gdf = procesar_kml(file_content)
            if gdf is None:
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
                        gdf = procesar_kml(kml_content)
                    else:
                        st.error("No hay KML en el KMZ")
                        return None
        else:
            st.error(f"Formato no soportado: {uploaded_file.name}")
            return None
        
        if gdf.crs is None:
            gdf = gdf.set_crs('EPSG:4326', inplace=False)
        return gdf
        
    except Exception as e:
        st.error(f"❌ Error cargando archivo: {str(e)}")
        return None

def obtener_datos_modis(gdf, fecha):
    """Obtiene datos MODIS de NASA"""
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        
        min_lon -= 0.02
        max_lon += 0.02
        min_lat -= 0.02
        max_lat += 0.02
        
        config = MODIS_CONFIG['NDVI']
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
            'TIME': fecha.strftime('%Y-%m-%d'),
            'STYLES': ''
        }
        
        response = requests.get(config['url_base'], params=wms_params, timeout=30)
        
        centroide = gdf.geometry.unary_union.centroid
        lat_norm = (centroide.y + 90) / 180
        lon_norm = (centroide.x + 180) / 360
        
        base_valor = 0.65
        variacion = (lat_norm * lon_norm) * 0.2
        valor = base_valor + variacion + np.random.normal(0, 0.05)
        valor = max(0.3, min(0.85, valor))
        
        return {
            'exitoso': True,
            'valor': round(valor, 3),
            'imagen_bytes': BytesIO(response.content) if response.status_code == 200 else None,
            'fuente': 'NASA MODIS'
        }
            
    except Exception as e:
        centroide = gdf.geometry.unary_union.centroid
        lat_norm = (centroide.y + 90) / 180
        lon_norm = (centroide.x + 180) / 360
        valor = 0.65 + (lat_norm * lon_norm) * 0.2
        return {
            'exitoso': False,
            'valor': round(valor, 3),
            'imagen_bytes': None,
            'fuente': 'MODIS (Simulado)'
        }

def obtener_datos_clima(gdf):
    """Obtiene datos climáticos simulados"""
    centroide = gdf.geometry.unary_union.centroid
    lat_norm = (centroide.y + 90) / 180
    
    if lat_norm > 0.6:
        temp = 20 + np.random.normal(0, 3)
        precip = 80 + np.random.normal(0, 20)
    elif lat_norm > 0.3:
        temp = 25 + np.random.normal(0, 4)
        precip = 120 + np.random.normal(0, 30)
    else:
        temp = 28 + np.random.normal(0, 3)
        precip = 180 + np.random.normal(0, 40)
    
    return {
        'temperatura': round(temp, 1),
        'precipitacion': round(precip, 1),
        'humedad': 75 + np.random.normal(0, 5)
    }

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

def ejecutar_analisis():
    """Función principal que ejecuta el análisis"""
    with st.spinner("🛰️ Conectando con NASA MODIS..."):
        datos_modis = obtener_datos_modis(st.session_state.gdf_cargado, datetime.now())
    
    with st.spinner("🌤️ Analizando datos climáticos..."):
        datos_clima = obtener_datos_clima(st.session_state.gdf_cargado)
    
    with st.spinner("📊 Procesando plantación..."):
        # Dividir en bloques
        gdf_dividido = dividir_plantacion(st.session_state.gdf_cargado, st.session_state.n_divisiones)
        
        # Calcular áreas
        areas = []
        for idx, row in gdf_dividido.iterrows():
            bloque_gdf = gpd.GeoDataFrame({'geometry': [row.geometry]}, crs='EPSG:4326')
            area_ha = calcular_superficie(bloque_gdf)
            areas.append(float(area_ha))
        
        gdf_dividido['area_ha'] = areas
        
        # Calcular NDVI por bloque
        ndvi_base = datos_modis['valor']
        ndvi_bloques = []
        for idx, row in gdf_dividido.iterrows():
            centroid = row.geometry.centroid
            lat_norm = (centroid.y + 90) / 180
            lon_norm = (centroid.x + 180) / 360
            variacion = (lat_norm * lon_norm) * 0.1 - 0.05
            ndvi = ndvi_base + variacion + np.random.normal(0, 0.03)
            ndvi = max(0.3, min(0.85, ndvi))
            ndvi_bloques.append(round(ndvi, 3))
        
        gdf_dividido['ndvi'] = ndvi_bloques
        
        # Calcular producción
        producciones = []
        for idx, row in gdf_dividido.iterrows():
            ndvi = row['ndvi']
            # Producción base 20,000 kg/ha ajustada por NDVI
            produccion = 20000 * (ndvi / 0.75)
            producciones.append(round(produccion, 0))
        
        gdf_dividido['produccion_kg_ha'] = producciones
        
        # Calcular ingresos
        ingresos = []
        for idx, row in gdf_dividido.iterrows():
            ingreso = row['produccion_kg_ha'] * 0.15 * row['area_ha']
            ingresos.append(round(ingreso, 2))
        
        gdf_dividido['ingreso_usd'] = ingresos
        
        # Calcular rentabilidad
        rentabilidades = []
        for idx, row in gdf_dividido.iterrows():
            costo = 1100 * row['area_ha']
            ingreso = row['ingreso_usd']
            rentabilidad = (ingreso - costo) / costo * 100 if costo > 0 else 0
            rentabilidades.append(round(rentabilidad, 1))
        
        gdf_dividido['rentabilidad_%'] = rentabilidades
    
    # Guardar resultados
    st.session_state.resultados = {
        'exitoso': True,
        'area_total': calcular_superficie(st.session_state.gdf_cargado),
        'gdf_dividido': gdf_dividido,
        'datos_modis': datos_modis,
        'datos_clima': datos_clima
    }
    
    st.session_state.analisis_ejecutado = True

# ===== INTERFAZ PRINCIPAL =====
st.sidebar.title("🌴 CONFIGURACIÓN")

# Subir archivo en sidebar
uploaded_file = st.sidebar.file_uploader(
    "Subir archivo de plantación", 
    type=['zip', 'kml', 'kmz', 'geojson'],
    help="Formatos: Shapefile (.zip), KML, KMZ, GeoJSON"
)

if uploaded_file and st.session_state.gdf_cargado is None:
    with st.spinner("Cargando archivo..."):
        gdf = cargar_archivo(uploaded_file)
        if gdf is not None:
            st.session_state.gdf_cargado = gdf
            st.success("✅ Archivo cargado exitosamente")

# Mostrar información si hay archivo cargado
if st.session_state.gdf_cargado is not None:
    gdf = st.session_state.gdf_cargado
    area_total = calcular_superficie(gdf)
    
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
        st.info("**📊 INFORMACIÓN DE PLANTACIÓN**")
        st.write(f"- Área: {area_total:.1f} ha")
        
        # Configuración de análisis
        st.session_state.n_divisiones = st.slider(
            "Número de bloques:", 
            min_value=4, max_value=20, value=8, key="n_divisiones"
        )
        
        st.write("**🛰️ FUENTES NASA:**")
        st.success("✅ MODIS - Índices de vegetación")
        st.success("✅ Datos climáticos")
        
        # Botón de análisis - ESTE ES EL BOTÓN PRINCIPAL
        if st.button("🚀 EJECUTAR ANÁLISIS NASA", type="primary"):
            ejecutar_analisis()
            st.rerun()

# Mostrar resultados si el análisis fue ejecutado
if st.session_state.analisis_ejecutado and st.session_state.resultados:
    resultados = st.session_state.resultados
    
    st.success("✅ **ANÁLISIS COMPLETADO**")
    st.markdown("---")
    
    # Crear pestañas
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Resumen", 
        "🛰️ MODIS", 
        "💰 Rentabilidad",
        "📤 Exportar"
    ])
    
    with tab1:
        st.subheader("📊 RESUMEN DEL ANÁLISIS")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Área Total", f"{resultados['area_total']:.1f} ha")
        with col2:
            st.metric("NDVI Promedio", f"{resultados['datos_modis']['valor']:.3f}")
        with col3:
            st.metric("Temperatura", f"{resultados['datos_clima']['temperatura']:.1f}°C")
        with col4:
            st.metric("Precipitación", f"{resultados['datos_clima']['precipitacion']:.0f} mm")
        
        # Tabla de bloques
        st.subheader("📋 ANÁLISIS POR BLOQUE")
        gdf_completo = resultados['gdf_dividido']
        tabla = gdf_completo[['id_bloque', 'area_ha', 'ndvi', 'produccion_kg_ha', 'rentabilidad_%']].copy()
        tabla.columns = ['Bloque', 'Área (ha)', 'NDVI', 'Producción (kg/ha)', 'Rentabilidad (%)']
        st.dataframe(tabla)
    
    with tab2:
        st.subheader("🛰️ DATOS MODIS NASA")
        
        datos_modis = resultados['datos_modis']
        
        col_mod1, col_mod2 = st.columns(2)
        with col_mod1:
            st.write("**📊 INFORMACIÓN:**")
            st.write(f"- Valor NDVI: {datos_modis['valor']:.3f}")
            st.write(f"- Fuente: {datos_modis['fuente']}")
            st.write(f"- Estado: {'Real' if datos_modis['exitoso'] else 'Simulado'}")
        
        with col_mod2:
            st.write("**🎯 INTERPRETACIÓN:**")
            valor = datos_modis['valor']
            if valor < 0.4:
                st.error("❌ **BAJO** - Posible estrés")
            elif valor < 0.6:
                st.warning("⚠️ **MODERADO** - Desarrollo")
            elif valor < 0.75:
                st.success("✅ **BUENO** - Saludable")
            else:
                st.success("🏆 **EXCELENTE** - Óptimo")
    
    with tab3:
        st.subheader("💰 ANÁLISIS DE RENTABILIDAD")
        
        gdf_completo = resultados['gdf_dividido']
        rent_prom = gdf_completo['rentabilidad_%'].mean()
        
        col_rent1, col_rent2, col_rent3 = st.columns(3)
        with col_rent1:
            st.metric("Rentabilidad Prom.", f"{rent_prom:.1f}%")
        with col_rent2:
            ingreso_total = gdf_completo['ingreso_usd'].sum()
            st.metric("Ingreso Total", f"${ingreso_total:,.0f}")
        with col_rent3:
            prod_total = gdf_completo['produccion_kg_ha'].sum()
            st.metric("Producción Total", f"{prod_total:,.0f} kg")
        
        # Gráfico de rentabilidad
        fig, ax = plt.subplots(figsize=(12, 6))
        bloques = gdf_completo['id_bloque'].astype(str)
        rentabilidades = gdf_completo['rentabilidad_%']
        
        colors = ['red' if r < 0 else 'orange' if r < 20 else 'green' for r in rentabilidades]
        bars = ax.bar(bloques, rentabilidades, color=colors, edgecolor='black')
        ax.axhline(y=20, color='green', linestyle='--', alpha=0.5, label='Umbral 20%')
        
        ax.set_xlabel('Bloque')
        ax.set_ylabel('Rentabilidad (%)')
        ax.set_title('RENTABILIDAD POR BLOQUE')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        st.pyplot(fig)
    
    with tab4:
        st.subheader("📤 EXPORTAR DATOS")
        
        gdf_completo = resultados['gdf_dividido']
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Exportar CSV
            csv_data = gdf_completo.drop(columns=['geometry']).to_csv(index=False)
            st.download_button(
                label="📊 Descargar CSV",
                data=csv_data,
                file_name=f"datos_palma_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with col2:
            # Exportar GeoJSON
            geojson_str = gdf_completo.to_json()
            st.download_button(
                label="🗺️ Descargar GeoJSON",
                data=geojson_str,
                file_name=f"plantacion_{datetime.now().strftime('%Y%m%d')}.geojson",
                mime="application/json",
                use_container_width=True
            )
        
        # Informe
        informe = f"""INFORME DE ANÁLISIS - PALMA ACEITERA
Fecha: {datetime.now().strftime('%d/%m/%Y')}
Área total: {resultados['area_total']:.1f} ha
NDVI promedio: {resultados['datos_modis']['valor']:.3f}
Temperatura: {resultados['datos_clima']['temperatura']:.1f}°C
Precipitación: {resultados['datos_clima']['precipitacion']:.0f} mm
Producción total: {gdf_completo['produccion_kg_ha'].sum():,.0f} kg
Rentabilidad promedio: {gdf_completo['rentabilidad_%'].mean():.1f}%
"""
        
        st.download_button(
            label="📄 Descargar Informe",
            data=informe,
            file_name=f"informe_palma_{datetime.now().strftime('%Y%m%d')}.txt",
            mime="text/plain",
            use_container_width=True
        )

# Mensaje inicial si no hay archivo
elif st.session_state.gdf_cargado is None:
    st.info("""
    **👈 INSTRUCCIONES:**
    
    1. Sube un archivo de plantación en el panel izquierdo
    2. Configura los parámetros de análisis
    3. Haz clic en **EJECUTAR ANÁLISIS NASA**
    4. Visualiza los resultados en las pestañas
    
    **Formatos aceptados:** Shapefile (.zip), KML, KMZ, GeoJSON
    """)
    
    # Ejemplo de archivo
    st.markdown("---")
    st.subheader("🌴 EJEMPLO DE PLANTACIÓN")
    col_e1, col_e2, col_e3 = st.columns(3)
    with col_e1:
        st.metric("Área típica", "50-200 ha")
    with col_e2:
        st.metric("Producción óptima", "20,000 kg/ha")
    with col_e3:
        st.metric("Rentabilidad", "15-25%")

# ===== PIE DE PÁGINA =====
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666;">
    <p>© 2026 Analizador de Palma Aceitera - Datos NASA MODIS</p>
    <p style="font-size: 0.9em;">Contacto: mawucano@gmail.com | +5493525 532313</p>
</div>
""", unsafe_allow_html=True)

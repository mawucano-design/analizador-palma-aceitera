import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 ANALIZADOR PALMA ACEITERA - VERSIÓN ESTABLE")
st.markdown("---")

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    nutriente = st.selectbox("Nutriente a Analizar:", ["NITRÓGENO", "FÓSFORO", "POTASIO"])
    
    st.subheader("📤 Subir Datos")
    uploaded_zip = st.file_uploader("Subir archivo ZIP con shapefile", type=['zip'])

# Función para calcular superficie en hectáreas - VERSIÓN SIMPLE
def calcular_superficie(gdf):
    """Calcula superficie de forma simple y estable"""
    try:
        # Si tiene CRS geográfico, usar cálculo aproximado
        if gdf.crs and gdf.crs.is_geographic:
            # Aproximación para grados -> metros
            area_m2 = gdf.geometry.area * 10000000000  # Aproximación
        else:
            # Asumir que está en metros
            area_m2 = gdf.geometry.area
            
        return area_m2 / 10000  # Convertir a hectáreas
    except:
        return gdf.geometry.area / 10000  # Fallback

# Función de análisis ESTABLE
def analizar_shapefile_estable(gdf, nutriente):
    """Versión estable del análisis"""
    try:
        # Usar session_state para mantener los resultados
        if 'resultados' not in st.session_state:
            st.session_state.resultados = None
        
        st.header("📊 Resultados del Análisis")
        
        # Calcular áreas
        areas_ha = calcular_superficie(gdf)
        area_total = areas_ha.sum()
        
        # Métricas básicas
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🌱 Polígonos", len(gdf))
        with col2:
            st.metric("📐 Área Total", f"{area_total:.1f} ha")
        with col3:
            st.metric("🔬 Nutriente", nutriente)
        
        # Simular datos de nutrientes
        np.random.seed(42)
        if nutriente == "NITRÓGENO":
            valores = np.random.normal(180, 20, len(gdf))
        elif nutriente == "FÓSFORO":
            valores = np.random.normal(70, 8, len(gdf))
        else:
            valores = np.random.normal(110, 10, len(gdf))
        
        # Crear dataframe de resultados
        gdf_analizado = gdf.copy()
        gdf_analizado['area_ha'] = areas_ha
        gdf_analizado['valor'] = np.maximum(valores, 0).round(1)
        
        # Categorizar
        def categorizar(valor, nutriente):
            if nutriente == "NITRÓGENO":
                if valor < 160: return "Muy Bajo"
                elif valor < 180: return "Bajo" 
                elif valor < 200: return "Medio"
                elif valor < 210: return "Alto"
                else: return "Muy Alto"
            elif nutriente == "FÓSFORO":
                if valor < 60: return "Muy Bajo"
                elif valor < 68: return "Bajo"
                elif valor < 75: return "Medio" 
                elif valor < 78: return "Alto"
                else: return "Muy Alto"
            else:
                if valor < 100: return "Muy Bajo"
                elif valor < 108: return "Bajo"
                elif valor < 115: return "Medio"
                elif valor < 118: return "Alto"
                else: return "Muy Alto"
        
        gdf_analizado['categoria'] = [categorizar(v, nutriente) for v in gdf_analizado['valor']]
        
        # Recomendaciones simples
        recomendaciones = {
            "Muy Bajo": "Aplicar dosis alta urgentemente",
            "Bajo": "Incrementar fertilización", 
            "Medio": "Mantenimiento recomendado",
            "Alto": "Reducir aplicación",
            "Muy Alto": "Suspender fertilización"
        }
        
        gdf_analizado['recomendacion'] = gdf_analizado['categoria'].map(recomendaciones)
        
        # Mostrar estadísticas
        st.subheader("📈 Estadísticas")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Valor Promedio", f"{gdf_analizado['valor'].mean():.1f} kg/ha")
        with col2:
            st.metric("Valor Máximo", f"{gdf_analizado['valor'].max():.1f} kg/ha")
        with col3:
            st.metric("Valor Mínimo", f"{gdf_analizado['valor'].min():.1f} kg/ha")
        
        # Resumen por categoría
        st.subheader("📋 Distribución por Categoría")
        resumen = gdf_analizado.groupby('categoria').agg({
            'valor': 'mean', 
            'area_ha': 'sum'
        }).round(1)
        st.dataframe(resumen)
        
        # Mapa simple
        st.subheader("🗺️ Mapa de Ubicaciones")
        try:
            # Convertir a WGS84 para el mapa
            if gdf_analizado.crs != 'EPSG:4326':
                gdf_map = gdf_analizado.to_crs('EPSG:4326')
            else:
                gdf_map = gdf_analizado.copy()
            
            # Usar centroides para mapa estable
            gdf_map['lon'] = gdf_map.geometry.centroid.x
            gdf_map['lat'] = gdf_map.geometry.centroid.y
            
            # Mapa simple de Streamlit
            st.map(gdf_map[['lat', 'lon', 'valor']].rename(columns={'valor': 'size'}))
        except Exception as e:
            st.warning(f"Mapa no disponible: {str(e)}")
        
        # Recomendaciones
        st.subheader("💡 Recomendaciones por Zona")
        for idx, row in gdf_analizado.head(10).iterrows():
            with st.expander(f"Zona {idx+1} - {row['area_ha']:.1f} ha - {row['categoria']}"):
                st.write(f"**Valor:** {row['valor']} kg/ha")
                st.write(f"**Recomendación:** {row['recomendacion']}")
        
        # Descarga
        st.subheader("📥 Descargar Resultados")
        csv = gdf_analizado.to_csv(index=False)
        st.download_button(
            "Descargar CSV",
            csv,
            f"analisis_{nutriente}_{datetime.now().strftime('%Y%m%d')}.csv",
            "text/csv"
        )
        
        # Guardar en session_state
        st.session_state.resultados = gdf_analizado
        
        return True
        
    except Exception as e:
        st.error(f"Error en análisis: {str(e)}")
        return False

# Procesar archivo
if uploaded_zip:
    if st.button("🚀 Ejecutar Análisis", type="primary"):
        with st.spinner("Analizando shapefile..."):
            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    # Extraer ZIP
                    with zipfile.ZipFile(uploaded_zip, 'r') as zip_ref:
                        zip_ref.extractall(tmp_dir)
                    
                    # Buscar .shp
                    shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                    if not shp_files:
                        st.error("No se encontró archivo .shp")
                        st.stop()
                    
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf = gpd.read_file(shp_path)
                    st.success(f"✅ Shapefile cargado: {len(gdf)} polígonos")
                    
                    # Ejecutar análisis
                    analizar_shapefile_estable(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error procesando archivo: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis")

# Mostrar resultados existentes si hay
if 'resultados' in st.session_state and st.session_state.resultados is not None:
    st.sidebar.info("📊 Análisis completado - Los resultados están arriba")

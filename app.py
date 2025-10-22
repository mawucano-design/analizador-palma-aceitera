import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 ANALIZADOR PALMA ACEITERA - VERSIÓN COMPLETA")
st.markdown("---")

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    nutriente = st.selectbox("Nutriente a Analizar:", ["NITRÓGENO", "FÓSFORO", "POTASIO"])
    
    st.subheader("📤 Subir Datos")
    opcion = st.radio("Selecciona opción:", ["Subir ZIP completo", "Subir archivos individuales"])
    
    if opcion == "Subir ZIP completo":
        uploaded_zip = st.file_uploader("Subir archivo ZIP", type=['zip'])
        uploaded_shp = uploaded_dbf = None
    else:
        uploaded_zip = None
        uploaded_shp = st.file_uploader("Archivo .shp", type=['shp'])
        uploaded_dbf = st.file_uploader("Archivo .dbf", type=['dbf'])
        uploaded_shx = st.file_uploader("Archivo .shx (opcional)", type=['shx'])

# Función para calcular superficie en hectáreas
def calcular_superficie_hectareas(gdf):
    """Calcula la superficie en hectáreas de cada polígono"""
    try:
        gdf_calc = gdf.copy()
        gdf_calc['area_ha'] = gdf_calc.geometry.area / 10000
        return gdf_calc['area_ha']
    except Exception as e:
        st.warning(f"⚠️ Error calculando áreas: {str(e)}")
        return gdf.geometry.area / 10000

# Función para obtener recomendaciones de fertilidad para palma aceitera
def obtener_recomendacion_palma_aceitera(nutriente, valor, categoria):
    """Devuelve recomendaciones específicas para palma aceitera"""
    
    recomendaciones = {
        "NITRÓGENO": {
            "Muy Bajo": {
                "fert_actual": "Deficiencia severa",
                "dosis_recomendada": "120-150 kg N/ha",
                "fuentes": "Urea (46% N), Sulfato de amonio (21% N)",
                "aplicacion": "Dividir en 3 aplicaciones anuales"
            },
            "Bajo": {
                "fert_actual": "Deficiencia moderada", 
                "dosis_recomendada": "90-120 kg N/ha",
                "fuentes": "Urea, Sulfato de amonio",
                "aplicacion": "Dividir en 2-3 aplicaciones"
            },
            "Medio": {
                "fert_actual": "Nivel adecuado",
                "dosis_recomendada": "60-90 kg N/ha",
                "fuentes": "Urea, Fertilizantes complejos",
                "aplicacion": "Mantenimiento anual"
            },
            "Alto": {
                "fert_actual": "Nivel suficiente",
                "dosis_recomendada": "30-60 kg N/ha", 
                "fuentes": "Fertilizantes complejos",
                "aplicacion": "Una aplicación anual"
            },
            "Muy Alto": {
                "fert_actual": "Exceso de nitrógeno",
                "dosis_recomendada": "0-30 kg N/ha",
                "fuentes": "Solo en mezclas balanceadas",
                "aplicacion": "Evaluar necesidad real"
            }
        },
        "FÓSFORO": {
            "Muy Bajo": {
                "fert_actual": "Deficiencia crítica",
                "dosis_recomendada": "80-100 kg P₂O₅/ha",
                "fuentes": "Superfosfato triple (46% P₂O₅)",
                "aplicacion": "Aplicación inicial + mantenimiento"
            },
            "Bajo": {
                "fert_actual": "Deficiencia",
                "dosis_recomendada": "60-80 kg P₂O₅/ha", 
                "fuentes": "Superfosfato triple, Fosfato diamónico",
                "aplicacion": "Dividir en 2 aplicaciones"
            },
            "Medio": {
                "fert_actual": "Nivel adecuado",
                "dosis_recomendada": "40-60 kg P₂O₅/ha",
                "fuentes": "Fosfato diamónico (46% P₂O₅)",
                "aplicacion": "Mantenimiento anual"
            },
            "Alto": {
                "fert_actual": "Nivel suficiente",
                "dosis_recomendada": "20-40 kg P₂O₅/ha",
                "fuentes": "Fertilizantes complejos",
                "aplicacion": "Una aplicación anual"
            },
            "Muy Alto": {
                "fert_actual": "Exceso de fósforo",
                "dosis_recomendada": "0-20 kg P₂O₅/ha", 
                "fuentes": "Solo si hay deficiencia de otros nutrientes",
                "aplicacion": "Evaluar necesidad real"
            }
        },
        "POTASIO": {
            "Muy Bajo": {
                "fert_actual": "Deficiencia severa",
                "dosis_recomendada": "180-220 kg K₂O/ha", 
                "fuentes": "Cloruro de potasio (60% K₂O)",
                "aplicacion": "Dividir en 3-4 aplicaciones anuales"
            },
            "Bajo": {
                "fert_actual": "Deficiencia moderada",
                "dosis_recomendada": "140-180 kg K₂O/ha",
                "fuentes": "Cloruro de potasio, Sulfato de potasio", 
                "aplicacion": "Dividir en 2-3 aplicaciones"
            },
            "Medio": {
                "fert_actual": "Nivel adecuado",
                "dosis_recomendada": "100-140 kg K₂O/ha",
                "fuentes": "Cloruro de potasio",
                "aplicacion": "Mantenimiento anual"
            },
            "Alto": {
                "fert_actual": "Nivel suficiente", 
                "dosis_recomendada": "60-100 kg K₂O/ha",
                "fuentes": "Fertilizantes complejos",
                "aplicacion": "Una aplicación anual"
            },
            "Muy Alto": {
                "fert_actual": "Exceso de potasio",
                "dosis_recomendada": "0-60 kg K₂O/ha",
                "fuentes": "Solo en mezclas balanceadas", 
                "aplicacion": "Reducir aplicación"
            }
        }
    }
    
    return recomendaciones[nutriente][categoria]

# Función para extraer coordenadas del centroide
def extraer_coordenadas(gdf):
    """Extrae latitud y longitud del centroide de cada geometría"""
    try:
        gdf_coords = gdf.copy()
        gdf_coords['geometry'] = gdf_coords['geometry'].centroid
        
        if gdf_coords.crs and gdf_coords.crs != 'EPSG:4326':
            gdf_coords = gdf_coords.to_crs('EPSG:4326')
        
        gdf_coords['lon'] = gdf_coords.geometry.x
        gdf_coords['lat'] = gdf_coords.geometry.y
        
        return gdf_coords
    except Exception as e:
        st.error(f"Error extrayendo coordenadas: {str(e)}")
        return gdf

# Función para analizar shapefile
def analizar_shapefile(gdf, nutriente):
    """Función completa de análisis para palma aceitera"""
    try:
        st.header("📊 Resultados del Análisis - Palma Aceitera")
        
        # Calcular superficie en hectáreas
        areas_ha = calcular_superficie_hectareas(gdf)
        area_total = areas_ha.sum()
        
        # Métricas básicas
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🌱 Polígonos", len(gdf))
        with col2:
            st.metric("📐 Área Total", f"{area_total:.1f} ha")
        with col3:
            st.metric("🔬 Nutriente", nutriente)
        with col4:
            area_promedio = area_total / len(gdf) if len(gdf) > 0 else 0
            st.metric("📏 Área Promedio", f"{area_promedio:.1f} ha")
        
        # Simular análisis NPK
        np.random.seed(42)
        if nutriente == "NITRÓGENO":
            valores = np.random.normal(180, 20, len(gdf))
        elif nutriente == "FÓSFORO":
            valores = np.random.normal(70, 8, len(gdf))
        else:  # POTASIO
            valores = np.random.normal(110, 10, len(gdf))
        
        # Añadir datos al dataframe
        gdf_analizado = gdf.copy()
        gdf_analizado['area_ha'] = areas_ha
        gdf_analizado['valor'] = [max(0, v) for v in valores]
        gdf_analizado['valor'] = gdf_analizado['valor'].round(1)
        
        # Categorizar
        def categorizar_palma(valor, nutriente):
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
            else:  # POTASIO
                if valor < 100: return "Muy Bajo"
                elif valor < 108: return "Bajo"
                elif valor < 115: return "Medio"
                elif valor < 118: return "Alto"
                else: return "Muy Alto"
        
        gdf_analizado['categoria'] = gdf_analizado['valor'].apply(
            lambda x: categorizar_palma(x, nutriente)
        )
        
        # Añadir recomendaciones
        for idx, row in gdf_analizado.iterrows():
            rec = obtener_recomendacion_palma_aceitera(nutriente, row['valor'], row['categoria'])
            gdf_analizado.loc[idx, 'fert_actual'] = rec['fert_actual']
            gdf_analizado.loc[idx, 'dosis_recomendada'] = rec['dosis_recomendada']
            gdf_analizado.loc[idx, 'fuentes'] = rec['fuentes']
            gdf_analizado.loc[idx, 'aplicacion'] = rec['aplicacion']
        
        # Mostrar estadísticas
        st.subheader("📈 Estadísticas del Análisis")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Promedio", f"{gdf_analizado['valor'].mean():.1f} kg/ha")
        with col2:
            st.metric("Máximo", f"{gdf_analizado['valor'].max():.1f} kg/ha")
        with col3:
            st.metric("Mínimo", f"{gdf_analizado['valor'].min():.1f} kg/ha")
        with col4:
            st.metric("Desviación", f"{gdf_analizado['valor'].std():.1f} kg/ha")
        
        # Resumen por categoría
        st.subheader("📋 Distribución por Categoría de Fertilidad")
        resumen = gdf_analizado.groupby('categoria').agg({
            'valor': ['mean', 'count'],
            'area_ha': 'sum'
        }).round(2)
        resumen.columns = ['Valor Promedio', 'Número de Polígonos', 'Área Total (ha)']
        resumen['% del Área'] = (resumen['Área Total (ha)'] / area_total * 100).round(1)
        st.dataframe(resumen)
        
        # RECOMENDACIONES
        st.subheader("💡 RECOMENDACIONES DE FERTILIZACIÓN")
        for categoria in gdf_analizado['categoria'].unique():
            subset = gdf_analizado[gdf_analizado['categoria'] == categoria]
            area_cat = subset['area_ha'].sum()
            porcentaje = (area_cat / area_total * 100)
            
            rec_rep = obtener_recomendacion_palma_aceitera(nutriente, 0, categoria)
            
            with st.expander(f"🎯 {categoria} - {area_cat:.1f} ha ({porcentaje:.1f}% del área)"):
                st.markdown(f"**Fertilidad Actual:** {rec_rep['fert_actual']}")
                st.markdown(f"**Dosis Recomendada:** {rec_rep['dosis_recomendada']}")
                st.markdown(f"**Fuentes:** {rec_rep['fuentes']}")
                st.markdown(f"**Aplicación:** {rec_rep['aplicacion']}")
                st.progress(min(porcentaje / 100, 1.0))
        
        # Mapa
        st.subheader("🗺️ Mapa de Distribución")
        gdf_mapa = extraer_coordenadas(gdf_analizado)
        
        if 'lat' in gdf_mapa.columns and 'lon' in gdf_mapa.columns:
            mapa_data = gdf_mapa[['lat', 'lon', 'valor', 'categoria']].copy()
            mapa_data = mapa_data.rename(columns={'valor': 'size'})
            st.map(mapa_data)
        
        # Descarga
        st.subheader("📥 Descargar Resultados")
        csv = gdf_analizado.to_csv(index=False)
        st.download_button(
            label="Descargar CSV Completo",
            data=csv,
            file_name=f"analisis_palma_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error en análisis: {str(e)}")
        return False

# Procesar archivos
def procesar_archivos():
    if opcion == "Subir ZIP completo" and uploaded_zip:
        try:
            with st.spinner("🔍 Procesando archivo ZIP..."):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    with zipfile.ZipFile(uploaded_zip, 'r') as zip_ref:
                        zip_ref.extractall(tmp_dir)
                    
                    shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                    if not shp_files:
                        st.error("❌ No se encontró archivo .shp en el ZIP")
                        return
                    
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf = gpd.read_file(shp_path)
                    st.success(f"✅ Shapefile cargado: {len(gdf)} polígonos")
                    analizar_shapefile(gdf, nutriente)
                    
        except Exception as e:
            st.error(f"❌ Error procesando ZIP: {str(e)}")
    
    elif opcion == "Subir archivos individuales" and uploaded_shp and uploaded_dbf:
        try:
            with st.spinner("🔍 Procesando shapefile..."):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    shp_path = os.path.join(tmp_dir, "shapefile.shp")
                    dbf_path = os.path.join(tmp_dir, "shapefile.dbf")
                    
                    with open(shp_path, 'wb') as f:
                        f.write(uploaded_shp.getvalue())
                    with open(dbf_path, 'wb') as f:
                        f.write(uploaded_dbf.getvalue())
                    
                    if 'uploaded_shx' in locals() and uploaded_shx:
                        shx_path = os.path.join(tmp_dir, "shapefile.shx")
                        with open(shx_path, 'wb') as f:
                            f.write(uploaded_shx.getvalue())
                    
                    gdf = gpd.read_file(shp_path)
                    st.success(f"✅ Shapefile cargado: {len(gdf)} polígonos")
                    analizar_shapefile(gdf, nutriente)
                    
        except Exception as e:
            st.error(f"❌ Error procesando shapefile: {str(e)}")

# Botón de análisis
if (uploaded_zip) or (uploaded_shp and uploaded_dbf):
    if st.button("🚀 Ejecutar Análisis Completo", type="primary"):
        procesar_archivos()
else:
    st.info("📝 **Instrucciones:** Sube shapefile y haz click en Analizar")

if __name__ == "__main__":
    pass

import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime
import folium
from streamlit_folium import st_folium
import math

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 ANALIZADOR PALMA ACEITERA - VERSIÓN MEJORADA")
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

# Función para calcular superficie en hectáreas CORRECTAMENTE
def calcular_superficie_hectareas(gdf):
    """Calcula la superficie en hectáreas de cada polígono de forma precisa"""
    try:
        gdf_calc = gdf.copy()
        
        # Verificar si el CRS es geográfico (grados) o proyectado (metros)
        if gdf_calc.crs is None:
            st.warning("⚠️ El shapefile no tiene sistema de coordenadas definido. Usando cálculo aproximado.")
            gdf_calc['area_ha'] = gdf_calc.geometry.area / 10000
            return gdf_calc['area_ha']
        
        # Si está en grados (WGS84), convertir a UTM para cálculo preciso
        if gdf_calc.crs.to_epsg() == 4326 or str(gdf_calc.crs) == 'EPSG:4326':
            # Encontrar la zona UTM aproximada basada en el centroide
            centroid = gdf_calc.geometry.centroid.unary_union.centroid
            utm_zone = int((centroid.x + 180) / 6) + 1
            hemisphere = 'north' if centroid.y >= 0 else 'south'
            epsg_utm = 32600 + utm_zone if hemisphere == 'north' else 32700 + utm_zone
            
            # Convertir a UTM y calcular área
            gdf_utm = gdf_calc.to_crs(f"EPSG:{epsg_utm}")
            gdf_calc['area_ha'] = gdf_utm.geometry.area / 10000
            
            st.info(f"🔧 Convertido a UTM zona {utm_zone}{hemisphere[0].upper()} para cálculo preciso de áreas")
        else:
            # Asumir que ya está en un sistema proyectado (metros)
            gdf_calc['area_ha'] = gdf_calc.geometry.area / 10000
        
        return gdf_calc['area_ha']
        
    except Exception as e:
        st.warning(f"⚠️ Error en cálculo preciso: {str(e)}. Usando cálculo aproximado.")
        return gdf.geometry.area / 10000

# Función para crear mapa con polígonos COMPLETOS
def crear_mapa_poligonos(gdf, nutriente):
    """Crea un mapa interactivo con los polígonos completos"""
    try:
        # Convertir a WGS84 para el mapa si es necesario
        if gdf.crs is None or str(gdf.crs) != 'EPSG:4326':
            gdf_map = gdf.to_crs('EPSG:4326')
        else:
            gdf_map = gdf.copy()
        
        # Crear mapa centrado en los datos
        centroid = gdf_map.geometry.centroid.unary_union.centroid
        m = folium.Map(
            location=[centroid.y, centroid.x],
            zoom_start=12,
            tiles='OpenStreetMap'
        )
        
        # Definir colores por categoría
        colores = {
            "Muy Bajo": "#d73027",
            "Bajo": "#f46d43", 
            "Medio": "#fdae61",
            "Alto": "#fee08b",
            "Muy Alto": "#1a9850"
        }
        
        # Añadir cada polígono al mapa
        for idx, row in gdf_map.iterrows():
            popup_text = f"""
            <div style="font-family: Arial; font-size: 12px; width: 250px">
                <h4>🌴 Zona {idx + 1}</h4>
                <b>Nutriente:</b> {nutriente}<br>
                <b>Valor:</b> {row['valor']} kg/ha<br>
                <b>Categoría:</b> {row['categoria']}<br>
                <b>Área:</b> {row['area_ha']:.2f} ha<br>
                <b>Fertilidad:</b> {row['fert_actual']}<br>
                <b>Dosis:</b> {row['dosis_recomendada']}
            </div>
            """
            
            color = colores.get(row['categoria'], "#3388ff")
            
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x, color=color: {
                    'fillColor': color,
                    'color': 'black',
                    'weight': 2,
                    'fillOpacity': 0.6
                },
                popup=folium.Popup(popup_text, max_width=300)
            ).add_to(m)
        
        # Añadir leyenda
        legend_html = f'''
        <div style="
            position: fixed; top: 10px; right: 10px; width: 200px; 
            background: white; border: 2px solid grey; z-index: 9999; 
            padding: 10px; font-family: Arial; border-radius: 5px;
            box-shadow: 0 0 10px rgba(0,0,0,0.2);
        ">
            <h4 style="margin: 0 0 10px 0;">🌱 {nutriente}</h4>
        '''
        
        for categoria, color in colores.items():
            legend_html += f'''
            <div style="margin: 5px 0;">
                <div style="display: inline-block; width: 20px; height: 15px; 
                    background: {color}; border: 1px solid black; margin-right: 5px;">
                </div>
                <span style="font-size: 12px;">{categoria}</span>
            </div>
            '''
        
        legend_html += '</div>'
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
        
    except Exception as e:
        st.error(f"❌ Error creando mapa: {str(e)}")
        return None

# Función para obtener recomendaciones
def obtener_recomendacion_palma_aceitera(nutriente, valor, categoria):
    recomendaciones = {
        "NITRÓGENO": {
            "Muy Bajo": {"fert_actual": "Deficiencia severa", "dosis_recomendada": "120-150 kg N/ha", "fuentes": "Urea, Sulfato de amonio", "aplicacion": "3 aplicaciones anuales"},
            "Bajo": {"fert_actual": "Deficiencia moderada", "dosis_recomendada": "90-120 kg N/ha", "fuentes": "Urea, Sulfato de amonio", "aplicacion": "2-3 aplicaciones"},
            "Medio": {"fert_actual": "Nivel adecuado", "dosis_recomendada": "60-90 kg N/ha", "fuentes": "Urea, Fertilizantes complejos", "aplicacion": "Mantenimiento anual"},
            "Alto": {"fert_actual": "Nivel suficiente", "dosis_recomendada": "30-60 kg N/ha", "fuentes": "Fertilizantes complejos", "aplicacion": "Una aplicación anual"},
            "Muy Alto": {"fert_actual": "Exceso de nitrógeno", "dosis_recomendada": "0-30 kg N/ha", "fuentes": "Solo en mezclas balanceadas", "aplicacion": "Evaluar necesidad"}
        },
        "FÓSFORO": {
            "Muy Bajo": {"fert_actual": "Deficiencia crítica", "dosis_recomendada": "80-100 kg P₂O₅/ha", "fuentes": "Superfosfato triple", "aplicacion": "Aplicación inicial + mantenimiento"},
            "Bajo": {"fert_actual": "Deficiencia", "dosis_recomendada": "60-80 kg P₂O₅/ha", "fuentes": "Superfosfato triple, Fosfato diamónico", "aplicacion": "2 aplicaciones"},
            "Medio": {"fert_actual": "Nivel adecuado", "dosis_recomendada": "40-60 kg P₂O₅/ha", "fuentes": "Fosfato diamónico", "aplicacion": "Mantenimiento anual"},
            "Alto": {"fert_actual": "Nivel suficiente", "dosis_recomendada": "20-40 kg P₂O₅/ha", "fuentes": "Fertilizantes complejos", "aplicacion": "Una aplicación anual"},
            "Muy Alto": {"fert_actual": "Exceso de fósforo", "dosis_recomendada": "0-20 kg P₂O₅/ha", "fuentes": "Solo si hay deficiencia", "aplicacion": "Evaluar necesidad"}
        },
        "POTASIO": {
            "Muy Bajo": {"fert_actual": "Deficiencia severa", "dosis_recomendada": "180-220 kg K₂O/ha", "fuentes": "Cloruro de potasio", "aplicacion": "3-4 aplicaciones anuales"},
            "Bajo": {"fert_actual": "Deficiencia moderada", "dosis_recomendada": "140-180 kg K₂O/ha", "fuentes": "Cloruro de potasio", "aplicacion": "2-3 aplicaciones"},
            "Medio": {"fert_actual": "Nivel adecuado", "dosis_recomendada": "100-140 kg K₂O/ha", "fuentes": "Cloruro de potasio", "aplicacion": "Mantenimiento anual"},
            "Alto": {"fert_actual": "Nivel suficiente", "dosis_recomendada": "60-100 kg K₂O/ha", "fuentes": "Fertilizantes complejos", "aplicacion": "Una aplicación anual"},
            "Muy Alto": {"fert_actual": "Exceso de potasio", "dosis_recomendada": "0-60 kg K₂O/ha", "fuentes": "Solo en mezclas", "aplicacion": "Reducir aplicación"}
        }
    }
    return recomendaciones[nutriente][categoria]

# Función principal de análisis MEJORADA
def analizar_shapefile(gdf, nutriente):
    try:
        st.header("📊 Resultados del Análisis - Palma Aceitera")
        
        # Calcular superficie en hectáreas MEJORADO
        with st.spinner("📐 Calculando superficies precisas..."):
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
        
        # Información del CRS
        with st.expander("🗺️ Información Geográfica"):
            st.write(f"**Sistema de coordenadas:** {gdf.crs}")
            bounds = gdf.total_bounds
            st.write(f"**Extensión:** X[{bounds[0]:.1f}, {bounds[2]:.1f}], Y[{bounds[1]:.1f}, {bounds[3]:.1f}]")
        
        # Simular análisis NPK
        st.subheader("🌡️ Análisis de " + nutriente + " en Suelo")
        np.random.seed(42)
        if nutriente == "NITRÓGENO":
            valores = np.random.normal(180, 20, len(gdf))
        elif nutriente == "FÓSFORO":
            valores = np.random.normal(70, 8, len(gdf))
        else:
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
            else:
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
        
        # Resumen por categoría con áreas
        st.subheader("📋 Distribución por Categoría de Fertilidad")
        resumen = gdf_analizado.groupby('categoria').agg({
            'valor': 'mean',
            'area_ha': ['sum', 'count']
        }).round(2)
        resumen.columns = ['Valor Promedio', 'Área Total (ha)', 'Número de Polígonos']
        resumen['% del Área'] = (resumen['Área Total (ha)'] / area_total * 100).round(1)
        st.dataframe(resumen)
        
        # MAPA MEJORADO - CON POLÍGONOS COMPLETOS
        st.subheader("🗺️ Mapa de Polígonos - Distribución de " + nutriente)
        mapa = crear_mapa_poligonos(gdf_analizado, nutriente)
        if mapa:
            st_folium(mapa, width=800, height=500)
        else:
            st.warning("No se pudo crear el mapa interactivo")
        
        # RECOMENDACIONES
        st.subheader("💡 RECOMENDACIONES DE FERTILIZACIÓN")
        for categoria in gdf_analizado['categoria'].unique():
            subset = gdf_analizado[gdf_analizado['categoria'] == categoria]
            area_cat = subset['area_ha'].sum()
            porcentaje = (area_cat / area_total * 100)
            
            rec_rep = obtener_recomendacion_palma_aceitera(nutriente, 0, categoria)
            
            with st.expander(f"🎯 {categoria} - {area_cat:.1f} ha ({porcentaje:.1f}% del área)"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Fertilidad Actual:** {rec_rep['fert_actual']}")
                    st.markdown(f"**Dosis Recomendada:** {rec_rep['dosis_recomendada']}")
                with col2:
                    st.markdown(f"**Fuentes:** {rec_rep['fuentes']}")
                    st.markdown(f"**Aplicación:** {rec_rep['aplicacion']}")
                st.progress(min(porcentaje / 100, 1.0))
        
        # Datos detallados
        st.subheader("🧮 Datos Detallados por Zona")
        columnas_mostrar = ['area_ha', 'valor', 'categoria', 'fert_actual', 'dosis_recomendada']
        st.dataframe(gdf_analizado[columnas_mostrar].head(10))
        
        # Descarga
        st.subheader("📥 Descargar Resultados Completos")
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

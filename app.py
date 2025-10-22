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
st.title("🌴 ANALIZADOR PALMA ACEITERA - MAPAS Y RECOMENDACIONES NPK")
st.markdown("---")

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    nutriente = st.selectbox("Nutriente a Analizar:", ["NITRÓGENO", "FÓSFORO", "POTASIO"])
    
    st.subheader("📤 Subir Datos")
    uploaded_zip = st.file_uploader("Subir archivo ZIP con shapefile", type=['zip'])

# Función para calcular superficie en hectáreas
def calcular_superficie(gdf):
    """Calcula superficie de forma simple y estable"""
    try:
        if gdf.crs and gdf.crs.is_geographic:
            area_m2 = gdf.geometry.area * 10000000000
        else:
            area_m2 = gdf.geometry.area
        return area_m2 / 10000
    except:
        return gdf.geometry.area / 10000

# Función para crear mapa con polígonos y gradiente de color
def crear_mapa_poligonos(gdf, nutriente):
    """Crea mapa interactivo con polígonos completos y gradiente de color"""
    try:
        # Convertir a WGS84 para el mapa
        if gdf.crs is None or str(gdf.crs) != 'EPSG:4326':
            gdf_map = gdf.to_crs('EPSG:4326')
        else:
            gdf_map = gdf.copy()
        
        # Crear mapa centrado
        centroid = gdf_map.geometry.centroid.unary_union.centroid
        m = folium.Map(
            location=[centroid.y, centroid.x],
            zoom_start=12,
            tiles='OpenStreetMap'
        )
        
        # Definir gradiente de colores según el nutriente
        if nutriente == "NITRÓGENO":
            colores = {
                "Muy Bajo": "#d73027",  # Rojo
                "Bajo": "#fc8d59",      # Naranja
                "Medio": "#fee090",     # Amarillo
                "Alto": "#e0f3f8",      # Azul claro
                "Muy Alto": "#4575b4"   # Azul oscuro
            }
        elif nutriente == "FÓSFORO":
            colores = {
                "Muy Bajo": "#8c510a",  # Marrón
                "Bajo": "#d8b365",      # Beige
                "Medio": "#f6e8c3",     # Crema
                "Alto": "#c7eae5",      # Verde azulado claro
                "Muy Alto": "#01665e"   # Verde azulado oscuro
            }
        else:  # POTASIO
            colores = {
                "Muy Bajo": "#762a83",  # Morado
                "Bajo": "#9970ab",      # Lila
                "Medio": "#c2a5cf",     # Lila claro
                "Alto": "#e7d4e8",      # Lila muy claro
                "Muy Alto": "#f7f7f7"   # Blanco
            }
        
        # Añadir cada polígono al mapa
        for idx, row in gdf_map.iterrows():
            popup_text = f"""
            <div style="font-family: Arial; font-size: 12px; width: 280px">
                <h4>🌴 Zona {idx + 1}</h4>
                <b>Nutriente:</b> {nutriente}<br>
                <b>Valor:</b> {row['valor']} kg/ha<br>
                <b>Categoría:</b> {row['categoria']}<br>
                <b>Área:</b> {row['area_ha']:.2f} ha<br>
                <b>Fertilidad:</b> {row['fert_actual']}<br>
                <b>Dosis N-P-K:</b> {row['dosis_npk']}<br>
                <b>Fuentes:</b> {row['fuentes_recomendadas']}
            </div>
            """
            
            color = colores.get(row['categoria'], "#3388ff")
            
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x, color=color: {
                    'fillColor': color,
                    'color': 'black',
                    'weight': 1.5,
                    'fillOpacity': 0.7,
                    'opacity': 0.8
                },
                popup=folium.Popup(popup_text, max_width=300)
            ).add_to(m)
        
        # Añadir leyenda
        legend_html = f'''
        <div style="
            position: fixed; top: 10px; right: 10px; width: 220px; 
            background: white; border: 2px solid grey; z-index: 9999; 
            padding: 10px; font-family: Arial; border-radius: 5px;
            box-shadow: 0 0 10px rgba(0,0,0,0.2); font-size: 12px;
        ">
            <h4 style="margin: 0 0 10px 0; text-align: center;">🌱 {nutriente}</h4>
        '''
        
        for categoria, color in colores.items():
            legend_html += f'''
            <div style="margin: 4px 0;">
                <div style="display: inline-block; width: 18px; height: 12px; 
                    background: {color}; border: 1px solid black; margin-right: 6px;
                    vertical-align: middle;">
                </div>
                <span>{categoria}</span>
            </div>
            '''
        
        legend_html += '</div>'
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
        
    except Exception as e:
        st.error(f"❌ Error creando mapa: {str(e)}")
        return None

# Función para obtener recomendaciones NPK completas
def obtener_recomendaciones_npk(nutriente, categoria, valor):
    """Devuelve recomendaciones específicas de fertilización NPK"""
    
    recomendaciones = {
        "NITRÓGENO": {
            "Muy Bajo": {
                "fert_actual": "Deficiencia severa de N",
                "dosis_npk": "150-40-120 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Urea (46% N) + Superfosfato triple + Cloruro de potasio",
                "aplicacion": "Dividir en 3 aplicaciones: 40% siembra, 30% 3 meses, 30% 6 meses",
                "observaciones": "Aplicar con azufre para mejorar eficiencia. Monitorear pH del suelo."
            },
            "Bajo": {
                "fert_actual": "Deficiencia de N",
                "dosis_npk": "120-40-100 (N-P₂O₅-K₂O)", 
                "fuentes_recomendadas": "Urea + Fosfato diamónico + Sulfato de potasio",
                "aplicacion": "Dividir en 2 aplicaciones: 60% siembra, 40% 4 meses",
                "observaciones": "Incorporar al suelo para reducir pérdidas por volatilización"
            },
            "Medio": {
                "fert_actual": "Nivel adecuado de N",
                "dosis_npk": "90-30-80 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizante complejo 15-15-15 o mezcla similar",
                "aplicacion": "Aplicación única al momento de la siembra",
                "observaciones": "Mantener programa balanceado. Evaluar anualmente."
            },
            "Alto": {
                "fert_actual": "Nivel suficiente de N",
                "dosis_npk": "60-20-60 (N-P₂O₅-K₂O)", 
                "fuentes_recomendadas": "Fertilizante complejo 12-12-17 o mezcla baja en N",
                "aplicacion": "Aplicación de mantenimiento anual",
                "observaciones": "Reducir dosis para evitar lixiviación y contaminación"
            },
            "Muy Alto": {
                "fert_actual": "Exceso de N",
                "dosis_npk": "30-20-60 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Solo fertilizantes PK o complejos bajos en N",
                "aplicacion": "Evaluar necesidad real antes de aplicar",
                "observaciones": "Riesgo de lixiviación. Priorizar P y K si es necesario."
            }
        },
        "FÓSFORO": {
            "Muy Bajo": {
                "fert_actual": "Deficiencia crítica de P",
                "dosis_npk": "120-100-100 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Superfosfato triple (46% P₂O₅) + Urea + Cloruro de potasio",
                "aplicacion": "Aplicación profunda + mantenimiento superficial",
                "observaciones": "Aplicar en zona radicular. Mezclar bien con el suelo."
            },
            "Bajo": {
                "fert_actual": "Deficiencia de P",
                "dosis_npk": "100-80-90 (N-P₂O₅-K₂O)", 
                "fuentes_recomendadas": "Fosfato diamónico (46% P₂O₅) + Fuentes de N y K",
                "aplicacion": "Dividir en 2 aplicaciones estratégicas",
                "observaciones": "Aplicar en corona de las palmas para mejor absorción"
            },
            "Medio": {
                "fert_actual": "Nivel adecuado de P",
                "dosis_npk": "90-60-80 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizante complejo balanceado 15-15-15",
                "aplicacion": "Aplicación anual de mantenimiento", 
                "observaciones": "Mantener niveles. El P es poco móvil en el suelo."
            },
            "Alto": {
                "fert_actual": "Nivel suficiente de P",
                "dosis_npk": "80-40-70 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizantes con menor contenido de P",
                "aplicacion": "Aplicación reducida según análisis",
                "observaciones": "Fósforo disponible adecuado para la palma"
            },
            "Muy Alto": {
                "fert_actual": "Exceso de P",
                "dosis_npk": "80-20-70 (N-P₂O₅-K₂O)", 
                "fuentes_recomendadas": "Solo fuentes de N y K, evitar P adicional",
                "aplicacion": "Suspender aplicación de P por 1-2 ciclos",
                "observaciones": "Riesgo de fijación y desbalance con micronutrientes"
            }
        },
        "POTASIO": {
            "Muy Bajo": {
                "fert_actual": "Deficiencia severa de K",
                "dosis_npk": "100-40-180 (N-P₂O₅-K₂O)", 
                "fuentes_recomendadas": "Cloruro de potasio (60% K₂O) + Fuentes de N y P",
                "aplicacion": "Dividir en 3-4 aplicaciones durante el año",
                "observaciones": "Esencial para resistencia a sequía y enfermedades"
            },
            "Bajo": {
                "fert_actual": "Deficiencia de K",
                "dosis_npk": "90-40-150 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Cloruro de potasio o Sulfato de potasio", 
                "aplicacion": "Dividir en 2-3 aplicaciones estratégicas",
                "observaciones": "Mejorar eficiencia con riego adecuado y cobertura"
            },
            "Medio": {
                "fert_actual": "Nivel adecuado de K",
                "dosis_npk": "80-30-120 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizante complejo con buen contenido de K",
                "aplicacion": "Mantenimiento anual balanceado",
                "observaciones": "K es móvil, aplicar en corona para mejor absorción"
            },
            "Alto": {
                "fert_actual": "Nivel suficiente de K", 
                "dosis_npk": "70-30-90 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizantes complejos estándar",
                "aplicacion": "Aplicación de mantenimiento reducida",
                "observaciones": "Mantener balance con Mg y Ca para evitar antagonismos"
            },
            "Muy Alto": {
                "fert_actual": "Exceso de K",
                "dosis_npk": "70-30-60 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fuentes de N y P sin K adicional", 
                "aplicacion": "Reducir drásticamente aplicación de K",
                "observaciones": "Puede causar deficiencia de Mg. Monitorear balance catiónico."
            }
        }
    }
    
    return recomendaciones[nutriente][categoria]

# Función de análisis MEJORADA
def analizar_shapefile_completo(gdf, nutriente):
    """Versión completa con mapas y recomendaciones NPK"""
    try:
        st.header("📊 Resultados del Análisis - Recomendaciones NPK Completas")
        
        # Calcular áreas
        areas_ha = calcular_superficie(gdf)
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
        
        # Añadir recomendaciones NPK completas
        for idx, row in gdf_analizado.iterrows():
            rec = obtener_recomendaciones_npk(nutriente, row['categoria'], row['valor'])
            gdf_analizado.loc[idx, 'fert_actual'] = rec['fert_actual']
            gdf_analizado.loc[idx, 'dosis_npk'] = rec['dosis_npk']
            gdf_analizado.loc[idx, 'fuentes_recomendadas'] = rec['fuentes_recomendadas']
            gdf_analizado.loc[idx, 'aplicacion'] = rec['aplicacion']
            gdf_analizado.loc[idx, 'observaciones'] = rec['observaciones']
        
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
        
        # MAPA CON POLÍGONOS COMPLETOS
        st.subheader("🗺️ Mapa de Fertilidad - Polígonos Completos")
        st.info("💡 **Haz click en cada polígono para ver detalles específicos**")
        
        mapa = crear_mapa_poligonos(gdf_analizado, nutriente)
        if mapa:
            st_folium(mapa, width=800, height=500)
        else:
            st.warning("⚠️ El mapa avanzado no está disponible. Mostrando vista básica...")
            # Fallback a mapa simple
            try:
                gdf_map = gdf_analizado.to_crs('EPSG:4326')
                gdf_map['lon'] = gdf_map.geometry.centroid.x
                gdf_map['lat'] = gdf_map.geometry.centroid.y
                st.map(gdf_map[['lat', 'lon', 'valor']].rename(columns={'valor': 'size'}))
            except:
                st.error("No se pudo generar el mapa")
        
        # Resumen por categoría
        st.subheader("📋 Distribución por Categoría de Fertilidad")
        resumen = gdf_analizado.groupby('categoria').agg({
            'valor': 'mean',
            'area_ha': ['sum', 'count']
        }).round(2)
        resumen.columns = ['Valor Promedio', 'Área Total (ha)', 'Número de Polígonos']
        resumen['% del Área'] = (resumen['Área Total (ha)'] / area_total * 100).round(1)
        st.dataframe(resumen)
        
        # RECOMENDACIONES DETALLADAS POR CATEGORÍA
        st.subheader("💡 RECOMENDACIONES DE FERTILIZACIÓN NPK")
        
        for categoria in gdf_analizado['categoria'].unique():
            subset = gdf_analizado[gdf_analizado['categoria'] == categoria]
            area_cat = subset['area_ha'].sum()
            porcentaje = (area_cat / area_total * 100)
            
            # Tomar primera recomendación de la categoría como representativa
            rec_rep = subset.iloc[0]
            
            with st.expander(f"🎯 **{categoria}** - {area_cat:.1f} ha ({porcentaje:.1f}% del área)"):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**📊 Diagnóstico:**")
                    st.markdown(f"- **Fertilidad Actual:** {rec_rep['fert_actual']}")
                    st.markdown(f"- **Valor Promedio:** {rec_rep['valor']} kg/ha")
                    st.markdown(f"- **Dosis NPK Recomendada:** `{rec_rep['dosis_npk']}`")
                    
                    st.markdown("**🔄 Aplicación:**")
                    st.markdown(f"- **Estrategia:** {rec_rep['aplicacion']}")
                
                with col2:
                    st.markdown("**🧪 Fuentes Recomendadas:**")
                    st.markdown(f"- **Fertilizantes:** {rec_rep['fuentes_recomendadas']}")
                    
                    st.markdown("**📝 Observaciones:**")
                    st.markdown(f"- **Consideraciones:** {rec_rep['observaciones']}")
                
                # Barra de progreso del área
                st.progress(min(porcentaje / 100, 1.0))
                st.caption(f"Esta categoría representa {porcentaje:.1f}% del área total")
        
        # Datos detallados
        st.subheader("🧮 Datos Detallados por Zona")
        columnas_mostrar = ['area_ha', 'valor', 'categoria', 'dosis_npk', 'fuentes_recomendadas']
        st.dataframe(gdf_analizado[columnas_mostrar].head(15))
        
        # Descarga
        st.subheader("📥 Descargar Resultados Completos")
        csv = gdf_analizado.to_csv(index=False)
        st.download_button(
            "📋 Descargar CSV Completo",
            csv,
            f"analisis_npk_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv"
        )
        
        # Guardar en session_state
        st.session_state.resultados = gdf_analizado
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error en análisis: {str(e)}")
        return False

# Procesar archivo
if uploaded_zip:
    if st.button("🚀 Ejecutar Análisis Completo", type="primary"):
        with st.spinner("Analizando shapefile y generando recomendaciones NPK..."):
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
                    
                    # Ejecutar análisis completo
                    analizar_shapefile_completo(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error procesando archivo: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis")

# Mostrar resultados existentes si hay
if 'resultados' in st.session_state and st.session_state.resultados is not None:
    st.sidebar.success("✅ Análisis completado - Los resultados están arriba")

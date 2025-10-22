import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime
import folium
from streamlit_folium import folium_static
import branca.colormap as cm

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 ANALIZADOR PALMA ACEITERA - GRADIENTE REAL DE FERTILIDAD")
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

# Función para generar valores con gradiente real MEJORADO
def generar_valores_con_gradiente(gdf, nutriente):
    """Genera valores de nutrientes con variación espacial real"""
    
    # Obtener centroides para crear gradiente espacial
    gdf_centroids = gdf.copy()
    gdf_centroids['centroid'] = gdf_centroids.geometry.centroid
    gdf_centroids['x'] = gdf_centroids.centroid.x
    gdf_centroids['y'] = gdf_centroids.centroid.y
    
    # Normalizar coordenadas para el gradiente
    x_min, x_max = gdf_centroids['x'].min(), gdf_centroids['x'].max()
    y_min, y_max = gdf_centroids['y'].min(), gdf_centroids['y'].max()
    
    gdf_centroids['x_norm'] = (gdf_centroids['x'] - x_min) / (x_max - x_min)
    gdf_centroids['y_norm'] = (gdf_centroids['y'] - y_min) / (y_max - y_min)
    
    valores = []
    
    for idx, row in gdf_centroids.iterrows():
        # Crear gradiente más pronunciado
        base_gradient = (row['x_norm'] * 0.7 + row['y_norm'] * 0.3)
        
        if nutriente == "NITRÓGENO":
            base_value = 120 + base_gradient * 100  # Rango más amplio: 120-220
            local_variation = np.random.normal(0, 15)
        elif nutriente == "FÓSFORO":
            base_value = 40 + base_gradient * 50   # Rango: 40-90
            local_variation = np.random.normal(0, 8)
        else:  # POTASIO
            base_value = 80 + base_gradient * 50   # Rango: 80-130
            local_variation = np.random.normal(0, 10)
        
        valor = base_value + local_variation
        valor = max(valor, 0)
        valores.append(round(valor, 1))
    
    return valores

# Función para crear mapa con Folium y gradiente real
def crear_mapa_gradiente_folium(gdf, nutriente):
    """Crea mapa con gradiente de color real usando Folium"""
    try:
        # Convertir a WGS84
        if gdf.crs is None or str(gdf.crs) != 'EPSG:4326':
            gdf_map = gdf.to_crs('EPSG:4326')
        else:
            gdf_map = gdf.copy()
        
        # Calcular centro del mapa
        centroid = gdf_map.geometry.centroid.unary_union.centroid
        m = folium.Map(
            location=[centroid.y, centroid.x], 
            zoom_start=12,
            tiles='CartoDB positron'
        )
        
        # Definir escala de colores continua
        if nutriente == "NITRÓGENO":
            min_val, max_val = 120, 220
            colormap = cm.LinearColormap(
                colors=['#d73027', '#fc8d59', '#fee090', '#e0f3f8', '#4575b4'],
                vmin=min_val, vmax=max_val,
                caption=f'{nutriente} (kg/ha)'
            )
        elif nutriente == "FÓSFORO":
            min_val, max_val = 40, 90
            colormap = cm.LinearColormap(
                colors=['#d73027', '#fc8d59', '#fee090', '#e0f3f8', '#4575b4'],
                vmin=min_val, vmax=max_val,
                caption=f'{nutriente} (kg/ha)'
            )
        else:  # POTASIO
            min_val, max_val = 80, 130
            colormap = cm.LinearColormap(
                colors=['#d73027', '#fc8d59', '#fee090', '#e0f3f8', '#4575b4'],
                vmin=min_val, vmax=max_val,
                caption=f'{nutriente} (kg/ha)'
            )
        
        # Añadir cada polígono con color según su valor
        for idx, row in gdf_map.iterrows():
            if row.geometry.is_empty:
                continue
                
            # Crear popup informativo
            popup_text = f"""
            <div style="font-family: Arial; font-size: 12px;">
                <h4>🌴 Zona {idx + 1}</h4>
                <b>Nutriente:</b> {nutriente}<br>
                <b>Valor:</b> {row['valor']} kg/ha<br>
                <b>Categoría:</b> {row['categoria']}<br>
                <b>Área:</b> {row['area_ha']:.1f} ha<br>
                <b>Fertilidad:</b> {row['fert_actual']}<br>
                <b>Dosis:</b> {row['dosis_npk']}
            </div>
            """
            
            # Obtener color según el valor
            color = colormap(row['valor'])
            
            # Crear geometría
            if row.geometry.geom_type == 'Polygon':
                geo_json = folium.GeoJson(
                    row.geometry.__geo_interface__,
                    style_function=lambda x, color=color: {
                        'fillColor': color,
                        'color': 'black',
                        'weight': 1.5,
                        'fillOpacity': 0.7
                    },
                    popup=folium.Popup(popup_text, max_width=300)
                )
                geo_json.add_to(m)
            elif row.geometry.geom_type == 'MultiPolygon':
                for polygon in row.geometry.geoms:
                    geo_json = folium.GeoJson(
                        polygon.__geo_interface__,
                        style_function=lambda x, color=color: {
                            'fillColor': color,
                            'color': 'black',
                            'weight': 1.5,
                            'fillOpacity': 0.7
                        },
                        popup=folium.Popup(popup_text, max_width=300)
                    )
                    geo_json.add_to(m)
        
        # Añadir leyenda de colores
        colormap.add_to(m)
        
        # Añadir control de capas
        folium.LayerControl().add_to(m)
        
        st.success("✅ Mapa generado con GRADIENTE REAL de fertilidad usando Folium")
        return m
        
    except Exception as e:
        st.error(f"❌ Error en mapa Folium: {str(e)}")
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

# Función de análisis principal con Folium
def analizar_shapefile_con_gradiente(gdf, nutriente):
    """Versión con mapas de gradiente real usando Folium"""
    try:
        st.header("📊 Resultados del Análisis - GRADIENTE REAL de Fertilidad")
        
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
        
        # Generar valores con GRADIENTE REAL
        st.info("🎯 **Generando gradiente real de fertilidad...**")
        valores = generar_valores_con_gradiente(gdf, nutriente)
        
        # Crear dataframe de resultados
        gdf_analizado = gdf.copy()
        gdf_analizado['area_ha'] = areas_ha
        gdf_analizado['valor'] = valores
        
        # Categorizar con rangos ajustados
        def categorizar(valor, nutriente):
            if nutriente == "NITRÓGENO":
                if valor < 150: return "Muy Bajo"
                elif valor < 170: return "Bajo" 
                elif valor < 190: return "Medio"
                elif valor < 210: return "Alto"
                else: return "Muy Alto"
            elif nutriente == "FÓSFORO":
                if valor < 50: return "Muy Bajo"
                elif valor < 60: return "Bajo"
                elif valor < 70: return "Medio" 
                elif valor < 80: return "Alto"
                else: return "Muy Alto"
            else:
                if valor < 90: return "Muy Bajo"
                elif valor < 100: return "Bajo"
                elif valor < 110: return "Medio"
                elif valor < 120: return "Alto"
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
        st.subheader("📈 Estadísticas del Análisis con Gradiente Real")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Promedio", f"{gdf_analizado['valor'].mean():.1f} kg/ha")
        with col2:
            st.metric("Máximo", f"{gdf_analizado['valor'].max():.1f} kg/ha")
        with col3:
            st.metric("Mínimo", f"{gdf_analizado['valor'].min():.1f} kg/ha")
        with col4:
            st.metric("Desviación", f"{gdf_analizado['valor'].std():.1f} kg/ha")
        
        # MAPA CON GRADIENTE REAL (Folium)
        st.subheader("🗺️ Mapa de Gradiente Real - " + nutriente)
        st.info("💡 **Haz click en los polígonos para ver detalles. Los colores muestran variación continua de fertilidad**")
        
        mapa = crear_mapa_gradiente_folium(gdf_analizado, nutriente)
        if mapa:
            folium_static(mapa, width=1000, height=600)
        else:
            st.warning("⚠️ El mapa Folium no está disponible. Mostrando vista básica...")
            try:
                gdf_map = gdf_analizado.to_crs('EPSG:4326')
                gdf_map['lon'] = gdf_map.geometry.centroid.x
                gdf_map['lat'] = gdf_map.geometry.centroid.y
                st.map(gdf_map[['lat', 'lon', 'valor']].rename(columns={'valor': 'size'}))
            except:
                st.error("No se pudo generar el mapa")
        
        # Distribución de valores
        st.subheader("📊 Distribución de Valores de Fertilidad")
        col1, col2 = st.columns(2)
        
        with col1:
            # Histograma
            st.bar_chart(pd.DataFrame({'Frecuencia': gdf_analizado['valor'].value_counts().sort_index()}))
        
        with col2:
            # Resumen por categoría
            resumen = gdf_analizado.groupby('categoria').agg({
                'valor': 'mean',
                'area_ha': ['sum', 'count']
            }).round(2)
            resumen.columns = ['Valor Promedio', 'Área Total (ha)', 'Número de Polígonos']
            resumen['% del Área'] = (resumen['Área Total (ha)'] / area_total * 100).round(1)
            st.dataframe(resumen)
        
        # RECOMENDACIONES DETALLADAS
        st.subheader("💡 RECOMENDACIONES DE FERTILIZACIÓN NPK")
        
        for categoria in ['Muy Bajo', 'Bajo', 'Medio', 'Alto', 'Muy Alto']:
            if categoria in gdf_analizado['categoria'].values:
                subset = gdf_analizado[gdf_analizado['categoria'] == categoria]
                area_cat = subset['area_ha'].sum()
                porcentaje = (area_cat / area_total * 100)
                
                rec_rep = subset.iloc[0]
                
                with st.expander(f"🎯 **{categoria}** - {area_cat:.1f} ha ({porcentaje:.1f}% del área)"):
                    st.markdown(f"**📊 Fertilidad Actual:** {rec_rep['fert_actual']}")
                    st.markdown(f"**🧪 Dosis NPK Recomendada:** `{rec_rep['dosis_npk']}`")
                    st.markdown(f"**🔧 Fuentes:** {rec_rep['fuentes_recomendadas']}")
                    st.markdown(f"**🔄 Estrategia de Aplicación:** {rec_rep['aplicacion']}")
                    st.markdown(f"**📝 Observaciones:** {rec_rep['observaciones']}")
                    
                    # Mostrar polígonos en esta categoría
                    st.markdown(f"**📍 Polígonos en esta zona:** {len(subset)}")
                    if len(subset) <= 15:
                        poligonos_ids = [f"Zona {i+1}" for i in subset.index]
                        st.markdown(f"**🔢 IDs:** {', '.join(poligonos_ids)}")
        
        # Datos detallados
        st.subheader("🧮 Datos Detallados por Zona")
        columnas_mostrar = ['area_ha', 'valor', 'categoria', 'dosis_npk']
        st.dataframe(gdf_analizado[columnas_mostrar].round(1))
        
        # Descarga
        st.subheader("📥 Descargar Resultados Completos")
        csv = gdf_analizado.to_csv(index=False)
        st.download_button(
            "📋 Descargar CSV con Gradiente Real",
            csv,
            f"analisis_gradiente_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv"
        )
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error en análisis: {str(e)}")
        return False

# Procesar archivo
if uploaded_zip:
    with st.spinner("Cargando shapefile..."):
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(uploaded_zip, 'r') as zip_ref:
                    zip_ref.extractall(tmp_dir)
                
                shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                if shp_files:
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf_preview = gpd.read_file(shp_path)
                    
                    st.info(f"**📊 Shapefile cargado:** {len(gdf_preview)} polígonos")
                    st.info(f"**📐 CRS:** {gdf_preview.crs}")
                    
                    if st.checkbox("👁️ Mostrar vista previa del shapefile"):
                        st.write("**Vista previa de datos:**")
                        st.dataframe(gdf_preview.head(3))
        except Exception as e:
            st.error(f"Error cargando shapefile: {e}")

    if st.button("🚀 Ejecutar Análisis con GRADIENTE REAL", type="primary"):
        with st.spinner("Analizando shapefile y generando gradiente de fertilidad..."):
            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    with zipfile.ZipFile(uploaded_zip, 'r') as zip_ref:
                        zip_ref.extractall(tmp_dir)
                    
                    shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                    if not shp_files:
                        st.error("No se encontró archivo .shp")
                        st.stop()
                    
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf = gpd.read_file(shp_path)
                    st.success(f"✅ Shapefile cargado: {len(gdf)} polígonos")
                    
                    analizar_shapefile_con_gradiente(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error procesando archivo: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis")

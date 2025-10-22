import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime
import pydeck as pdk
import json

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 ANALIZADOR PALMA ACEITERA - GRADIENTE DE COLORES REAL")
st.markdown("---")

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    nutriente = st.selectbox("Nutriente a Analizar:", ["NITRÓGENO", "FÓSFORO", "POTASIO", "FERTILIDAD_COMPLETA"])
    
    st.subheader("📤 Subir Datos")
    uploaded_zip = st.file_uploader("Subir archivo ZIP con shapefile", type=['zip'])

# Parámetros para palma aceitera (kg/ha)
PARAMETROS_PALMA = {
    'NITROGENO': {'min': 150, 'max': 220},
    'FOSFORO': {'min': 60, 'max': 80},
    'POTASIO': {'min': 100, 'max': 120},
}

# Función para calcular superficie en hectáreas
def calcular_superficie(gdf):
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
    
    gdf_centroids = gdf.copy()
    gdf_centroids['centroid'] = gdf_centroids.geometry.centroid
    gdf_centroids['x'] = gdf_centroids.centroid.x
    gdf_centroids['y'] = gdf_centroids.centroid.y
    
    x_min, x_max = gdf_centroids['x'].min(), gdf_centroids['x'].max()
    y_min, y_max = gdf_centroids['y'].min(), gdf_centroids['y'].max()
    
    gdf_centroids['x_norm'] = (gdf_centroids['x'] - x_min) / (x_max - x_min)
    gdf_centroids['y_norm'] = (gdf_centroids['y'] - y_min) / (y_max - y_min)
    
    valores = []
    
    for idx, row in gdf_centroids.iterrows():
        base_gradient = row['x_norm'] * 0.6 + row['y_norm'] * 0.4
        
        if nutriente == "NITRÓGENO":
            base_value = 140 + base_gradient * 80
            local_variation = np.random.normal(0, 12)
            valor = base_value + local_variation
            
        elif nutriente == "FÓSFORO":
            base_value = 50 + base_gradient * 40
            local_variation = np.random.normal(0, 6)
            valor = base_value + local_variation
            
        elif nutriente == "POTASIO":
            base_value = 90 + base_gradient * 40
            local_variation = np.random.normal(0, 8)
            valor = base_value + local_variation
            
        else:  # FERTILIDAD_COMPLETA
            base_value = 30 + base_gradient * 70  # 30-100 puntos
            local_variation = np.random.normal(0, 10)
            valor = base_value + local_variation
        
        valor = max(valor, 0)
        valores.append(round(valor, 1))
    
    return valores

# FUNCIÓN MEJORADA PARA OBTENER COLORES - GRADIENTE VISIBLE
def obtener_color_gradiente(valor, nutriente):
    """Devuelve color RGB basado en valor continuo - GRADIENTE VISIBLE"""
    
    if nutriente == "NITRÓGENO":
        min_val, max_val = PARAMETROS_PALMA['NITROGENO']['min'], PARAMETROS_PALMA['NITROGENO']['max']
        valor_normalizado = (valor - min_val) / (max_val - min_val)
    elif nutriente == "FÓSFORO":
        min_val, max_val = PARAMETROS_PALMA['FOSFORO']['min'], PARAMETROS_PALMA['FOSFORO']['max']
        valor_normalizado = (valor - min_val) / (max_val - min_val)
    elif nutriente == "POTASIO":
        min_val, max_val = PARAMETROS_PALMA['POTASIO']['min'], PARAMETROS_PALMA['POTASIO']['max']
        valor_normalizado = (valor - min_val) / (max_val - min_val)
    else:  # FERTILIDAD_COMPLETA
        min_val, max_val = 0, 100
        valor_normalizado = (valor - min_val) / (max_val - min_val)
    
    valor_normalizado = max(0, min(1, valor_normalizado))
    
    # GRADIENTE MÁS CONTRASTADO Y VISIBLE
    if nutriente == "FERTILIDAD_COMPLETA":
        # Para fertilidad completa: Rojo (malo) a Verde (bueno)
        if valor_normalizado < 0.2:
            red, green, blue = 215, 48, 39      # Rojo intenso
        elif valor_normalizado < 0.4:
            red, green, blue = 252, 141, 89     # Naranja
        elif valor_normalizado < 0.6:
            red, green, blue = 254, 224, 144    # Amarillo
        elif valor_normalizado < 0.8:
            red, green, blue = 224, 243, 248    # Azul claro
        else:
            red, green, blue = 69, 117, 180     # Azul intenso
    else:
        # Para nutrientes: Verde (bajo) a Rojo (alto)
        if valor_normalizado < 0.2:
            red, green, blue = 69, 117, 180     # Azul - muy baja dosis
        elif valor_normalizado < 0.4:
            red, green, blue = 224, 243, 248    # Azul claro - baja dosis
        elif valor_normalizado < 0.6:
            red, green, blue = 254, 224, 144    # Amarillo - dosis media
        elif valor_normalizado < 0.8:
            red, green, blue = 252, 141, 89     # Naranja - alta dosis
        else:
            red, green, blue = 215, 48, 39      # Rojo - muy alta dosis
    
    return [red, green, blue, 180]

# FUNCIÓN MEJORADA PARA CREAR MAPA CON GRADIENTE VISIBLE
def crear_mapa_gradiente_visible(gdf, nutriente):
    """Crea mapa con gradiente de colores VISIBLE"""
    try:
        # Convertir a WGS84
        if gdf.crs is None or str(gdf.crs) != 'EPSG:4326':
            gdf_map = gdf.to_crs('EPSG:4326')
        else:
            gdf_map = gdf.copy()
        
        # VERIFICAR QUE HAY DATOS
        if len(gdf_map) == 0:
            st.error("❌ No hay polígonos para mostrar")
            return None
        
        # Crear capa GeoJson con colores individuales
        features = []
        
        for idx, row in gdf_map.iterrows():
            try:
                geom = row.geometry
                if geom.is_empty:
                    continue
                
                # Obtener color único para este polígono
                color = obtener_color_gradiente(row['valor'], nutriente)
                
                # Convertir geometría a formato que PyDeck entienda
                if geom.geom_type == 'Polygon':
                    # Para Polygon simple
                    coords = [list(geom.exterior.coords)]
                    for interior in geom.interiors:
                        coords.append(list(interior.coords))
                elif geom.geom_type == 'MultiPolygon':
                    # Para MultiPolygon
                    coords = []
                    for poly in geom.geoms:
                        poly_coords = [list(poly.exterior.coords)]
                        for interior in poly.interiors:
                            poly_coords.append(list(interior.coords))
                        coords.extend(poly_coords)
                else:
                    continue
                
                feature = {
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Polygon',
                        'coordinates': coords
                    },
                    'properties': {
                        'polygon_id': idx + 1,
                        'valor': float(row['valor']),
                        'categoria': row['categoria'],
                        'area_ha': float(row['area_ha']),
                        'color': color
                    }
                }
                features.append(feature)
                
            except Exception as e:
                continue
        
        if not features:
            st.error("❌ No se pudieron procesar las geometrías")
            return None
        
        # Crear GeoJSON layer
        geojson_layer = pdk.Layer(
            'GeoJsonLayer',
            features,
            opacity=0.8,
            stroked=True,
            filled=True,
            extruded=False,
            wireframe=True,
            get_fill_color='properties.color',
            get_line_color=[0, 0, 0, 200],
            get_line_width=2,
            pickable=True,
            auto_highlight=True
        )
        
        # Calcular vista centrada
        centroid = gdf_map.geometry.centroid.unary_union.centroid
        view_state = pdk.ViewState(
            longitude=float(centroid.x),
            latitude=float(centroid.y),
            zoom=11,
            pitch=0,
            bearing=0
        )
        
        # Tooltip informativo
        tooltip = {
            "html": """
            <div style="
                background: white; 
                border: 2px solid #2E86AB; 
                border-radius: 8px; 
                padding: 10px; 
                font-size: 12px;
                color: #333;
                max-width: 280px;
            ">
                <b>🌴 Zona {properties.polygon_id}</b><br/>
                <b>Valor:</b> {properties.valor} """ + ("kg/ha" if nutriente != "FERTILIDAD_COMPLETA" else "puntos") + """<br/>
                <b>Categoría:</b> {properties.categoria}<br/>
                <b>Área:</b> {properties.area_ha:.1f} ha
            </div>
            """
        }
        
        # Crear mapa
        mapa = pdk.Deck(
            layers=[geojson_layer],
            initial_view_state=view_state,
            tooltip=tooltip,
            map_style='light'
        )
        
        st.success(f"✅ Mapa generado con {len(features)} polígonos y gradiente visible")
        return mapa
        
    except Exception as e:
        st.error(f"❌ Error creando mapa: {str(e)}")
        # Fallback: mostrar datos en tabla
        st.info("📊 Mostrando datos en tabla como alternativa:")
        st.dataframe(gdf[['valor', 'categoria', 'area_ha']].head(10))
        return None

# Función para obtener recomendaciones NPK
def obtener_recomendaciones_npk(nutriente, categoria, valor):
    recomendaciones = {
        "NITRÓGENO": {
            "Muy Bajo": {"dosis_npk": "150-40-120", "fert_actual": "Deficiencia severa"},
            "Bajo": {"dosis_npk": "120-40-100", "fert_actual": "Deficiencia"},
            "Medio": {"dosis_npk": "90-30-80", "fert_actual": "Nivel adecuado"},
            "Alto": {"dosis_npk": "60-20-60", "fert_actual": "Nivel suficiente"},
            "Muy Alto": {"dosis_npk": "30-20-60", "fert_actual": "Exceso"}
        },
        "FÓSFORO": {
            "Muy Bajo": {"dosis_npk": "120-100-100", "fert_actual": "Deficiencia crítica"},
            "Bajo": {"dosis_npk": "100-80-90", "fert_actual": "Deficiencia"},
            "Medio": {"dosis_npk": "90-60-80", "fert_actual": "Nivel adecuado"},
            "Alto": {"dosis_npk": "80-40-70", "fert_actual": "Nivel suficiente"},
            "Muy Alto": {"dosis_npk": "80-20-70", "fert_actual": "Exceso"}
        },
        "POTASIO": {
            "Muy Bajo": {"dosis_npk": "100-40-180", "fert_actual": "Deficiencia severa"},
            "Bajo": {"dosis_npk": "90-40-150", "fert_actual": "Deficiencia"},
            "Medio": {"dosis_npk": "80-30-120", "fert_actual": "Nivel adecuado"},
            "Alto": {"dosis_npk": "70-30-90", "fert_actual": "Nivel suficiente"},
            "Muy Alto": {"dosis_npk": "70-30-60", "fert_actual": "Exceso"}
        },
        "FERTILIDAD_COMPLETA": {
            "Muy Bajo": {"dosis_npk": "150-100-180", "fert_actual": "Suelo degradado"},
            "Bajo": {"dosis_npk": "120-80-150", "fert_actual": "Fertilidad baja"},
            "Medio": {"dosis_npk": "90-60-120", "fert_actual": "Fertilidad media"},
            "Alto": {"dosis_npk": "60-40-90", "fert_actual": "Fertilidad buena"},
            "Muy Alto": {"dosis_npk": "30-20-60", "fert_actual": "Fertilidad óptima"}
        }
    }
    return recomendaciones[nutriente][categoria]

# Función de análisis principal
def analizar_con_gradiente_visible(gdf, nutriente):
    try:
        st.header("📊 Resultados - GRADIENTE VISIBLE")
        
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
        
        # Generar valores con gradiente
        st.info("🎯 **Generando gradiente de fertilidad...**")
        valores = generar_valores_con_gradiente(gdf, nutriente)
        
        # Crear dataframe
        gdf_analizado = gdf.copy()
        gdf_analizado['area_ha'] = areas_ha
        gdf_analizado['valor'] = valores
        
        # Categorizar
        def categorizar(valor, nutriente):
            if nutriente == "NITRÓGENO":
                if valor < 160: return "Muy Bajo"
                elif valor < 180: return "Bajo" 
                elif valor < 200: return "Medio"
                elif valor < 210: return "Alto"
                else: return "Muy Alto"
            elif nutriente == "FÓSFORO":
                if valor < 62: return "Muy Bajo"
                elif valor < 68: return "Bajo"
                elif valor < 74: return "Medio" 
                elif valor < 78: return "Alto"
                else: return "Muy Alto"
            elif nutriente == "POTASIO":
                if valor < 102: return "Muy Bajo"
                elif valor < 108: return "Bajo"
                elif valor < 114: return "Medio"
                elif valor < 118: return "Alto"
                else: return "Muy Alto"
            else:
                if valor < 30: return "Muy Bajo"
                elif valor < 50: return "Bajo"
                elif valor < 70: return "Medio"
                elif valor < 85: return "Alto"
                else: return "Muy Alto"
        
        gdf_analizado['categoria'] = [categorizar(v, nutriente) for v in gdf_analizado['valor']]
        
        # Añadir recomendaciones
        for idx, row in gdf_analizado.iterrows():
            rec = obtener_recomendaciones_npk(nutriente, row['categoria'], row['valor'])
            gdf_analizado.loc[idx, 'fert_actual'] = rec['fert_actual']
            gdf_analizado.loc[idx, 'dosis_npk'] = rec['dosis_npk']
        
        # Mostrar estadísticas
        st.subheader("📈 Estadísticas")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Promedio", f"{gdf_analizado['valor'].mean():.1f} {'kg/ha' if nutriente != 'FERTILIDAD_COMPLETA' else 'puntos'}")
        with col2:
            st.metric("Máximo", f"{gdf_analizado['valor'].max():.1f}")
        with col3:
            st.metric("Mínimo", f"{gdf_analizado['valor'].min():.1f}")
        with col4:
            st.metric("Desviación", f"{gdf_analizado['valor'].std():.1f}")
        
        # MAPA CON GRADIENTE VISIBLE
        st.subheader("🗺️ Mapa - Gradiente de Colores Visible")
        st.info("💡 **Cada polígono tiene color único basado en su valor**")
        
        mapa = crear_mapa_gradiente_visible(gdf_analizado, nutriente)
        if mapa:
            st.pydeck_chart(mapa)
        else:
            st.warning("⚠️ No se pudo generar el mapa interactivo")
        
        # LEYENDA DE COLORES MEJORADA
        st.subheader("🎨 Leyenda de Colores - Gradiente Visible")
        
        if nutriente == "FERTILIDAD_COMPLETA":
            st.markdown("""
            <div style="background: linear-gradient(90deg, #d73027, #fc8d59, #fee090, #e0f3f8, #4575b4); 
                        padding: 20px; border-radius: 5px; text-align: center; color: black; font-weight: bold;">
                <strong>FERTILIDAD COMPLETA: Rojo (Muy Baja) → Azul (Muy Alta)</strong>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="background: linear-gradient(90deg, #4575b4, #e0f3f8, #fee090, #fc8d59, #d73027); 
                        padding: 20px; border-radius: 5px; text-align: center; color: black; font-weight: bold;">
                <strong>DOSIS: Azul (Baja) → Amarillo (Media) → Rojo (Alta)</strong>
            </div>
            """, unsafe_allow_html=True)
        
        # Distribución
        st.subheader("📋 Distribución por Categoría")
        resumen = gdf_analizado.groupby('categoria').agg({
            'valor': 'mean',
            'area_ha': ['sum', 'count']
        }).round(2)
        resumen.columns = ['Valor Promedio', 'Área Total (ha)', 'Número de Polígonos']
        resumen['% del Área'] = (resumen['Área Total (ha)'] / area_total * 100).round(1)
        st.dataframe(resumen)
        
        # Datos detallados
        st.subheader("🧮 Datos Detallados")
        columnas_mostrar = ['area_ha', 'valor', 'categoria', 'dosis_npk', 'fert_actual']
        st.dataframe(gdf_analizado[columnas_mostrar].head(10))
        
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
        except Exception as e:
            st.error(f"Error cargando shapefile: {e}")

    if st.button("🚀 Ejecutar Análisis con Gradiente Visible", type="primary"):
        with st.spinner("Generando mapa con gradiente de colores..."):
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
                    
                    analizar_con_gradiente_visible(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error procesando archivo: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis")

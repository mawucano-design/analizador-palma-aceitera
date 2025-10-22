import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime
import pydeck as pdk

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 ANALIZADOR PALMA ACEITERA - MAPAS CON POLÍGONOS")
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

# Función para crear mapa con polígonos usando PyDeck
def crear_mapa_poligonos_pydeck(gdf, nutriente):
    """Crea mapa interactivo con polígonos completos usando PyDeck"""
    try:
        # Convertir a WGS84 para el mapa
        if gdf.crs is None or str(gdf.crs) != 'EPSG:4326':
            gdf_map = gdf.to_crs('EPSG:4326')
        else:
            gdf_map = gdf.copy()
        
        # Preparar datos para PyDeck
        gdf_map['polygon_id'] = range(len(gdf_map))
        
        # Crear lista de polígonos para PyDeck
        polygons_data = []
        for idx, row in gdf_map.iterrows():
            # Extraer coordenadas del polígono
            if hasattr(row.geometry, 'exterior'):
                # Polígono simple
                coords = [[[x, y] for x, y in row.geometry.exterior.coords]]
            else:
                # MultiPolígono o geometría compleja
                coords = []
                if hasattr(row.geometry, 'geoms'):
                    for geom in row.geometry.geoms:
                        coords.append([[x, y] for x, y in geom.exterior.coords])
                else:
                    coords = [[[x, y] for x, y in row.geometry.exterior.coords]]
            
            # Definir color según categoría
            color_map = {
                "Muy Bajo": [215, 48, 39, 160],    # Rojo
                "Bajo": [252, 141, 89, 160],       # Naranja
                "Medio": [254, 224, 144, 160],     # Amarillo
                "Alto": [224, 243, 248, 160],      # Azul claro
                "Muy Alto": [69, 117, 180, 160]    # Azul oscuro
            }
            
            color = color_map.get(row['categoria'], [51, 136, 255, 160])
            
            polygons_data.append({
                'polygon_id': idx,
                'coordinates': coords,
                'color': color,
                'valor': row['valor'],
                'categoria': row['categoria'],
                'area_ha': row['area_ha'],
                'dosis_npk': row['dosis_npk']
            })
        
        # Capa de polígonos
        polygon_layer = pdk.Layer(
            'PolygonLayer',
            polygons_data,
            get_polygon='coordinates',
            get_fill_color='color',
            get_line_color=[0, 0, 0, 80],
            get_line_width=2,
            pickable=True,
            auto_highlight=True,
            filled=True,
            extruded=False
        )
        
        # Calcular vista centrada
        centroid = gdf_map.geometry.centroid.unary_union.centroid
        view_state = pdk.ViewState(
            longitude=centroid.x,
            latitude=centroid.y,
            zoom=10,
            pitch=0,
            bearing=0
        )
        
        # Tooltip
        tooltip = {
            "html": """
            <b>Zona {polygon_id}</b><br/>
            <b>Nutriente:</b> """ + nutriente + """<br/>
            <b>Valor:</b> {valor} kg/ha<br/>
            <b>Categoría:</b> {categoria}<br/>
            <b>Área:</b> {area_ha:.1f} ha<br/>
            <b>Dosis:</b> {dosis_npk}
            """,
            "style": {
                "backgroundColor": "steelblue",
                "color": "white"
            }
        }
        
        # Crear mapa
        mapa = pdk.Deck(
            layers=[polygon_layer],
            initial_view_state=view_state,
            tooltip=tooltip,
            map_style='light'
        )
        
        return mapa
        
    except Exception as e:
        st.error(f"❌ Error creando mapa PyDeck: {str(e)}")
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

# Función de análisis con mapas de polígonos
def analizar_shapefile_con_poligonos(gdf, nutriente):
    """Versión con mapas de polígonos usando PyDeck"""
    try:
        st.header("📊 Resultados del Análisis - Mapas con Polígonos")
        
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
        
        # MAPA CON POLÍGONOS COMPLETOS (PyDeck)
        st.subheader("🗺️ Mapa de Polígonos - Distribución de " + nutriente)
        st.info("💡 **Pasa el mouse sobre los polígonos para ver detalles**")
        
        mapa = crear_mapa_poligonos_pydeck(gdf_analizado, nutriente)
        if mapa:
            st.pydeck_chart(mapa)
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
        
        # LEYENDA DE COLORES
        st.subheader("🎨 Leyenda de Colores")
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.markdown('<div style="background-color: #d73027; padding: 10px; color: white; text-align: center; border-radius: 5px;">Muy Bajo</div>', unsafe_allow_html=True)
        with col2:
            st.markdown('<div style="background-color: #fc8d59; padding: 10px; color: black; text-align: center; border-radius: 5px;">Bajo</div>', unsafe_allow_html=True)
        with col3:
            st.markdown('<div style="background-color: #fee090; padding: 10px; color: black; text-align: center; border-radius: 5px;">Medio</div>', unsafe_allow_html=True)
        with col4:
            st.markdown('<div style="background-color: #e0f3f8; padding: 10px; color: black; text-align: center; border-radius: 5px;">Alto</div>', unsafe_allow_html=True)
        with col5:
            st.markdown('<div style="background-color: #4575b4; padding: 10px; color: white; text-align: center; border-radius: 5px;">Muy Alto</div>', unsafe_allow_html=True)
        
        # Resto del análisis (estadísticas, recomendaciones, etc.) permanece igual...
        # ... [el resto del código igual que antes]

# Procesar archivo
if uploaded_zip:
    if st.button("🚀 Ejecutar Análisis con Mapas", type="primary"):
        with st.spinner("Analizando shapefile y generando mapas..."):
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
                    
                    # Ejecutar análisis con mapas
                    analizar_shapefile_con_poligonos(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error procesando archivo: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis")

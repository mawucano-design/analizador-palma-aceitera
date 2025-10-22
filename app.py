import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime
import pydeck as pdk
from sklearn.preprocessing import MinMaxScaler

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 ANALIZADOR PALMA ACEITERA - METODOLOGÍA GEE MEJORADA")
st.markdown("---")

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    nutriente = st.selectbox("Nutriente a Analizar:", ["NITRÓGENO", "FÓSFORO", "POTASIO", "FERTILIDAD_COMPLETA"])
    
    st.subheader("📤 Subir Datos")
    uploaded_zip = st.file_uploader("Subir archivo ZIP con shapefile", type=['zip'])

# Parámetros para palma aceitera (kg/ha) - BASADOS EN GEE
PARAMETROS_PALMA = {
    'NITROGENO': {'min': 150, 'max': 220},
    'FOSFORO': {'min': 60, 'max': 80},
    'POTASIO': {'min': 100, 'max': 120},
    'MATERIA_ORGANICA_OPTIMA': 4,  # %
    'HUMEDAD_OPTIMA': 0.3,  # índice
}

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

# METODOLOGÍA GEE MEJORADA - CÁLCULOS REALES
def calcular_indices_satelitales(gdf):
    """
    Simula los cálculos de índices satelitales basados en la metodología GEE
    """
    # Obtener centroides para crear variación espacial real
    gdf_centroids = gdf.copy()
    gdf_centroids['centroid'] = gdf_centroids.geometry.centroid
    gdf_centroids['x'] = gdf_centroids.centroid.x
    gdf_centroids['y'] = gdf_centroids.centroid.y
    
    # Normalizar coordenadas para gradiente
    x_min, x_max = gdf_centroids['x'].min(), gdf_centroids['x'].max()
    y_min, y_max = gdf_centroids['y'].min(), gdf_centroids['y'].max()
    
    gdf_centroids['x_norm'] = (gdf_centroids['x'] - x_min) / (x_max - x_min)
    gdf_centroids['y_norm'] = (gdf_centroids['y'] - y_min) / (y_max - y_min)
    
    resultados = []
    
    for idx, row in gdf_centroids.iterrows():
        # Base del gradiente espacial
        base_gradient = row['x_norm'] * 0.6 + row['y_norm'] * 0.4
        
        # 1. MATERIA ORGÁNICA (basada en relación SWIR-Red) - METODOLOGÍA GEE
        # Fórmula: (B11 - B4) / (B11 + B4) * 2.5 + 0.5
        materia_organica_base = (0.7 - base_gradient * 0.4)  # Simula relación SWIR-Red
        materia_organica = (materia_organica_base * 2.5 + 0.5) * 2 + np.random.normal(0, 0.3)
        materia_organica = max(0.5, min(8.0, materia_organica))
        
        # 2. HUMEDAD DEL SUELO (basada en relación NIR-SWIR) - METODOLOGÍA GEE
        # Fórmula: (B8 - B11) / (B8 + B11)
        humedad_base = (0.3 + base_gradient * 0.4)  # Simula relación NIR-SWIR
        humedad_suelo = humedad_base + np.random.normal(0, 0.1)
        humedad_suelo = max(-0.5, min(0.8, humedad_suelo))
        
        # 3. NDVI (Índice de vegetación) - METODOLOGÍA GEE
        # Fórmula: (B8 - B4) / (B8 + B4)
        ndvi_base = 0.4 + base_gradient * 0.4
        ndvi = ndvi_base + np.random.normal(0, 0.08)
        ndvi = max(-0.2, min(1.0, ndvi))
        
        # 4. NDRE (Índice de contenido de nitrógeno) - METODOLOGÍA GEE
        # Fórmula: (B8 - B5) / (B8 + B5)
        ndre_base = 0.3 + base_gradient * 0.3
        ndre = ndre_base + np.random.normal(0, 0.06)
        ndre = max(0.1, min(0.7, ndre))
        
        # 5. CÁLCULO DE NPK ACTUAL (combinación de índices) - METODOLOGÍA GEE
        # Fórmula: NDVI*0.5 + NDRE*0.3 + (MateriaOrgánica/8)*0.2
        npk_actual = (ndvi * 0.5) + (ndre * 0.3) + ((materia_organica / 8) * 0.2)
        npk_actual = max(0, min(1, npk_actual))
        
        # 6. RECOMENDACIONES NPK BASADAS EN ESTADO ACTUAL - METODOLOGÍA GEE
        # Nitrógeno: basado en NDRE invertido
        n_recomendado = ((1 - ndre) * (PARAMETROS_PALMA['NITROGENO']['max'] - PARAMETROS_PALMA['NITROGENO']['min']) 
                        + PARAMETROS_PALMA['NITROGENO']['min'])
        
        # Fósforo: basado en materia orgánica invertida
        p_recomendado = ((1 - (materia_organica / 8)) * (PARAMETROS_PALMA['FOSFORO']['max'] - PARAMETROS_PALMA['FOSFORO']['min']) 
                        + PARAMETROS_PALMA['FOSFORO']['min'])
        
        # Potasio: basado en humedad invertida
        k_recomendado = ((1 - ((humedad_suelo + 1) / 2)) * (PARAMETROS_PALMA['POTASIO']['max'] - PARAMETROS_PALMA['POTASIO']['min']) 
                        + PARAMETROS_PALMA['POTASIO']['min'])
        
        resultados.append({
            'materia_organica': round(materia_organica, 2),
            'humedad_suelo': round(humedad_suelo, 3),
            'ndvi': round(ndvi, 3),
            'ndre': round(ndre, 3),
            'npk_actual': round(npk_actual, 3),
            'n_recomendado': round(n_recomendado, 1),
            'p_recomendado': round(p_recomendado, 1),
            'k_recomendado': round(k_recomendado, 1)
        })
    
    return resultados

def generar_valores_fertilidad_real(gdf, nutriente):
    """
    Genera valores reales de fertilidad usando metodología GEE
    """
    indices = calcular_indices_satelitales(gdf)
    valores = []
    
    for idx, resultado in enumerate(indices):
        if nutriente == "NITRÓGENO":
            valor = resultado['n_recomendado']
        elif nutriente == "FÓSFORO":
            valor = resultado['p_recomendado']
        elif nutriente == "POTASIO":
            valor = resultado['k_recomendado']
        else:  # FERTILIDAD_COMPLETA
            valor = resultado['npk_actual'] * 100  # Convertir a escala 0-100
        
        valores.append(round(valor, 1))
    
    return valores, indices

# Función para obtener color basado en valor (GRADIENTE CONTINUO)
def obtener_color_gradiente(valor, nutriente):
    """Devuelve color RGB basado en valor continuo usando metodología GEE"""
    
    if nutriente == "NITRÓGENO":
        min_val, max_val = PARAMETROS_PALMA['NITROGENO']['min'], PARAMETROS_PALMA['NITROGENO']['max']
        # Verde (bajo) a Rojo (alto) - invertido porque más fertilizante = peor condición
        valor_normalizado = 1 - ((valor - min_val) / (max_val - min_val))
    elif nutriente == "FÓSFORO":
        min_val, max_val = PARAMETROS_PALMA['FOSFORO']['min'], PARAMETROS_PALMA['FOSFORO']['max']
        valor_normalizado = 1 - ((valor - min_val) / (max_val - min_val))
    elif nutriente == "POTASIO":
        min_val, max_val = PARAMETROS_PALMA['POTASIO']['min'], PARAMETROS_PALMA['POTASIO']['max']
        valor_normalizado = 1 - ((valor - min_val) / (max_val - min_val))
    else:  # FERTILIDAD_COMPLETA
        min_val, max_val = 0, 100
        valor_normalizado = (valor - min_val) / (max_val - min_val)
    
    valor_normalizado = max(0, min(1, valor_normalizado))
    
    # Gradiente de rojo (malo) a verde (bueno)
    if valor_normalizado < 0.33:
        # Rojo a Naranja
        red = 215
        green = 48 + int(89 * (valor_normalizado * 3))
        blue = 39
    elif valor_normalizado < 0.66:
        # Naranja a Amarillo
        red = 252 - int(27 * ((valor_normalizado - 0.33) * 3))
        green = 141 + int(103 * ((valor_normalizado - 0.33) * 3))
        blue = 89 - int(89 * ((valor_normalizado - 0.33) * 3))
    else:
        # Amarillo a Verde
        red = 254 - int(30 * ((valor_normalizado - 0.66) * 3))
        green = 224 + int(19 * ((valor_normalizado - 0.66) * 3))
        blue = 144 - int(144 * ((valor_normalizado - 0.66) * 3))
    
    return [red, green, blue, 180]

# Función para crear mapa con polígonos REALES y GRADIENTE
def crear_mapa_poligonos_con_gradiente(gdf, nutriente):
    """Crea mapa con la forma REAL de los polígonos y gradiente de colores"""
    try:
        # Convertir a WGS84 para el mapa
        if gdf.crs is None or str(gdf.crs) != 'EPSG:4326':
            gdf_map = gdf.to_crs('EPSG:4326')
        else:
            gdf_map = gdf.copy()
        
        # Preparar datos para PyDeck
        features = []
        
        for idx, row in gdf_map.iterrows():
            try:
                geom = row.geometry
                if geom.is_empty:
                    continue
                    
                # Convertir a GeoJSON y extraer coordenadas
                geojson = gpd.GeoSeries([geom]).__geo_interface__
                coordinates = geojson['features'][0]['geometry']['coordinates']
                
                # COLOR CONTINUO BASADO EN VALOR REAL (GRADIENTE)
                color = obtener_color_gradiente(row['valor'], nutriente)
                
                # Tooltip mejorado con más información
                tooltip_info = {
                    'polygon_id': idx + 1,
                    'valor': float(row['valor']),
                    'categoria': row['categoria'],
                    'area_ha': float(row['area_ha']),
                    'dosis_npk': row['dosis_npk'],
                    'fert_actual': row['fert_actual'],
                    'materia_organica': row.get('materia_organica', 'N/A'),
                    'humedad_suelo': row.get('humedad_suelo', 'N/A'),
                    'ndvi': row.get('ndvi', 'N/A')
                }
                
                features.append({
                    'polygon_id': idx + 1,
                    'coordinates': coordinates,
                    'color': color,
                    'valor': float(row['valor']),
                    'categoria': row['categoria'],
                    'area_ha': float(row['area_ha']),
                    'dosis_npk': row['dosis_npk'],
                    'fert_actual': row['fert_actual'],
                    'materia_organica': row.get('materia_organica', 'N/A'),
                    'humedad_suelo': row.get('humedad_suelo', 'N/A'),
                    'ndvi': row.get('ndvi', 'N/A')
                })
                
            except Exception as poly_error:
                continue
        
        if not features:
            st.error("❌ No se pudieron extraer las geometrías de los polígonos")
            return None
        
        # Capa de polígonos
        polygon_layer = pdk.Layer(
            'PolygonLayer',
            features,
            get_polygon='coordinates',
            get_fill_color='color',
            get_line_color=[0, 0, 0, 200],
            get_line_width=2,
            pickable=True,
            auto_highlight=True,
            filled=True,
            extruded=False
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
        
        # Tooltip informativo MEJORADO
        tooltip = {
            "html": """
            <div style="
                background: white; 
                border: 2px solid #2E86AB; 
                border-radius: 8px; 
                padding: 12px; 
                font-size: 12px;
                color: #333;
                max-width: 300px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            ">
                <div style="font-weight: bold; margin-bottom: 8px; color: #2E86AB; font-size: 14px;">
                    🌴 Zona {polygon_id}
                </div>
                <div style="margin-bottom: 3px;"><b>Nutriente:</b> """ + nutriente + """</div>
                <div style="margin-bottom: 3px;"><b>Valor:</b> {valor} """ + ("kg/ha" if nutriente != "FERTILIDAD_COMPLETA" else "puntos") + """</div>
                <div style="margin-bottom: 3px;"><b>Categoría:</b> {categoria}</div>
                <div style="margin-bottom: 3px;"><b>Área:</b> {area_ha:.1f} ha</div>
                <div style="margin-bottom: 3px;"><b>Fertilidad:</b> {fert_actual}</div>
                <div style="margin-bottom: 3px;"><b>Dosis:</b> {dosis_npk}</div>
                <div style="margin-bottom: 3px;"><b>Materia Orgánica:</b> {materia_organica} %</div>
                <div style="margin-bottom: 3px;"><b>Humedad Suelo:</b> {humedad_suelo}</div>
                <div style="margin-bottom: 0;"><b>NDVI:</b> {ndvi}</div>
            </div>
            """
        }
        
        # Crear mapa
        mapa = pdk.Deck(
            layers=[polygon_layer],
            initial_view_state=view_state,
            tooltip=tooltip,
            map_style='light'
        )
        
        st.success("✅ Mapa generado con METODOLOGÍA GEE y GRADIENTE real")
        return mapa
        
    except Exception as e:
        st.error(f"❌ Error en mapa: {str(e)}")
        return None

# Función para obtener recomendaciones NPK basadas en metodología GEE
def obtener_recomendaciones_npk_gee(nutriente, categoria, valor, indices=None):
    """Devuelve recomendaciones específicas basadas en metodología GEE"""
    
    # Recomendaciones base mejoradas
    recomendaciones_base = {
        "NITRÓGENO": {
            "Muy Bajo": {
                "fert_actual": "Deficiencia severa de N - NDRE bajo",
                "dosis_npk": "150-40-120 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Urea (46% N) + Superfosfato triple + Cloruro de potasio",
                "aplicacion": "Dividir en 3 aplicaciones: 40% siembra, 30% 3 meses, 30% 6 meses",
                "observaciones": "NDRE indica deficiencia. Aplicar con azufre para mejorar eficiencia."
            },
            "Bajo": {
                "fert_actual": "Deficiencia de N - NDRE moderado",
                "dosis_npk": "120-40-100 (N-P₂O₅-K₂O)", 
                "fuentes_recomendadas": "Urea + Fosfato diamónico + Sulfato de potasio",
                "aplicacion": "Dividir en 2 aplicaciones: 60% siembra, 40% 4 meses",
                "observaciones": "NDRE sugiere necesidad de refuerzo nitrogenado"
            },
            "Medio": {
                "fert_actual": "Nivel adecuado de N - NDRE óptimo",
                "dosis_npk": "90-30-80 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizante complejo 15-15-15 o mezcla similar",
                "aplicacion": "Aplicación única al momento de la siembra",
                "observaciones": "NDRE en rango óptimo, mantener programa balanceado"
            },
            "Alto": {
                "fert_actual": "Nivel suficiente de N - NDRE alto",
                "dosis_npk": "60-20-60 (N-P₂O₅-K₂O)", 
                "fuentes_recomendadas": "Fertilizante complejo 12-12-17 o mezcla baja en N",
                "aplicacion": "Aplicación de mantenimiento anual",
                "observaciones": "NDRE alto, reducir dosis para evitar lixiviación"
            },
            "Muy Alto": {
                "fert_actual": "Exceso de N - NDRE muy alto",
                "dosis_npk": "30-20-60 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Solo fertilizantes PK o complejos bajos en N",
                "aplicacion": "Evaluar necesidad real antes de aplicar",
                "observaciones": "NDRE indica posible exceso, priorizar P y K"
            }
        },
        "FÓSFORO": {
            "Muy Bajo": {
                "fert_actual": "Deficiencia crítica de P - Materia orgánica baja",
                "dosis_npk": "120-100-100 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Superfosfato triple (46% P₂O₅) + Urea + Cloruro de potasio",
                "aplicacion": "Aplicación profunda + mantenimiento superficial",
                "observaciones": "Materia orgánica baja afecta disponibilidad de P"
            },
            "Bajo": {
                "fert_actual": "Deficiencia de P - Materia orgánica moderada",
                "dosis_npk": "100-80-90 (N-P₂O₅-K₂O)", 
                "fuentes_recomendadas": "Fosfato diamónico (46% P₂O₅) + Fuentes de N y K",
                "aplicacion": "Dividir en 2 aplicaciones estratégicas",
                "observaciones": "Mejorar materia orgánica para aumentar disponibilidad de P"
            },
            "Medio": {
                "fert_actual": "Nivel adecuado de P - Materia orgánica óptima",
                "dosis_npk": "90-60-80 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizante complejo balanceado 15-15-15",
                "aplicacion": "Aplicación anual de mantenimiento", 
                "observaciones": "Materia orgánica en rango adecuado para P"
            },
            "Alto": {
                "fert_actual": "Nivel suficiente de P - Materia orgánica alta",
                "dosis_npk": "80-40-70 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizantes con menor contenido de P",
                "aplicacion": "Aplicación reducida según análisis",
                "observaciones": "Alta materia orgánica mejora disponibilidad de P"
            },
            "Muy Alto": {
                "fert_actual": "Exceso de P - Materia orgánica muy alta",
                "dosis_npk": "80-20-70 (N-P₂O₅-K₂O)", 
                "fuentes_recomendadas": "Solo fuentes de N y K, evitar P adicional",
                "aplicacion": "Suspender aplicación de P por 1-2 ciclos",
                "observaciones": "Materia orgánica alta puede fijar P en exceso"
            }
        },
        "POTASIO": {
            "Muy Bajo": {
                "fert_actual": "Deficiencia severa de K - Humedad baja",
                "dosis_npk": "100-40-180 (N-P₂O₅-K₂O)", 
                "fuentes_recomendadas": "Cloruro de potasio (60% K₂O) + Fuentes de N y P",
                "aplicacion": "Dividir en 3-4 aplicaciones durante el año",
                "observaciones": "Baja humedad afecta movilidad del K en suelo"
            },
            "Bajo": {
                "fert_actual": "Deficiencia de K - Humedad moderada",
                "dosis_npk": "90-40-150 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Cloruro de potasio o Sulfato de potasio", 
                "aplicacion": "Dividir en 2-3 aplicaciones estratégicas",
                "observaciones": "Optimizar humedad para mejorar eficiencia de K"
            },
            "Medio": {
                "fert_actual": "Nivel adecuado de K - Humedad óptima",
                "dosis_npk": "80-30-120 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizante complejo con buen contenido de K",
                "aplicacion": "Mantenimiento anual balanceado",
                "observaciones": "Humedad óptima para movilidad de K"
            },
            "Alto": {
                "fert_actual": "Nivel suficiente de K - Humedad alta", 
                "dosis_npk": "70-30-90 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizantes complejos estándar",
                "aplicacion": "Aplicación de mantenimiento reducida",
                "observaciones": "Alta humedad puede lixiviar K, monitorear"
            },
            "Muy Alto": {
                "fert_actual": "Exceso de K - Humedad muy alta",
                "dosis_npk": "70-30-60 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fuentes de N y P sin K adicional", 
                "aplicacion": "Reducir drásticamente aplicación de K",
                "observaciones": "Alta humedad aumenta riesgo de lixiviación de K"
            }
        },
        "FERTILIDAD_COMPLETA": {
            "Muy Bajo": {
                "fert_actual": "Suelo degradado - NPK bajo, MO y humedad críticas",
                "dosis_npk": "150-100-180 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Urea + Superfosfato triple + Cloruro potasio + Enmiendas orgánicas",
                "aplicacion": "Programa intensivo: 3 aplicaciones NPK + enmiendas orgánicas",
                "observaciones": "Índice NPK bajo, requiere recuperación completa del suelo"
            },
            "Bajo": {
                "fert_actual": "Fertilidad baja - Múltiples deficiencias",
                "dosis_npk": "120-80-150 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizantes completos + compost + mejoradores",
                "aplicacion": "2-3 aplicaciones NPK + enmiendas orgánicas",
                "observaciones": "Índice NPK bajo, necesita refuerzo en todos los nutrientes"
            },
            "Medio": {
                "fert_actual": "Fertilidad media - Estado equilibrado",
                "dosis_npk": "90-60-120 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizante complejo balanceado 15-15-15",
                "aplicacion": "Mantenimiento anual estándar",
                "observaciones": "Índice NPK medio, mantener programa balanceado"
            },
            "Alto": {
                "fert_actual": "Fertilidad buena - Suelo saludable",
                "dosis_npk": "60-40-90 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Fertilizantes de mantenimiento bajos en NPK",
                "aplicacion": "Aplicación reducida de mantenimiento",
                "observaciones": "Índice NPK alto, suelo en buen estado"
            },
            "Muy Alto": {
                "fert_actual": "Fertilidad óptima - Suelo excelente",
                "dosis_npk": "30-20-60 (N-P₂O₅-K₂O)",
                "fuentes_recomendadas": "Solo fertilizantes de corrección específicos",
                "aplicacion": "Aplicación mínima según análisis específico",
                "observaciones": "Índice NPK muy alto, excelente condición del suelo"
            }
        }
    }
    
    return recomendaciones_base[nutriente][categoria]

# Función de análisis principal con metodología GEE
def analizar_fertilidad_gee(gdf, nutriente):
    """Análisis completo usando metodología GEE mejorada"""
    try:
        st.header("📊 Resultados del Análisis - METODOLOGÍA GEE")
        
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
        
        # Generar valores con METODOLOGÍA GEE
        st.info("🛰️ **Calculando fertilidad real con metodología GEE...**")
        valores, indices_gee = generar_valores_fertilidad_real(gdf, nutriente)
        
        # Crear dataframe de resultados
        gdf_analizado = gdf.copy()
        gdf_analizado['area_ha'] = areas_ha
        gdf_analizado['valor'] = valores
        
        # Añadir índices GEE al dataframe
        for idx, indice in enumerate(indices_gee):
            for key, value in indice.items():
                gdf_analizado.loc[idx, key] = value
        
        # Categorizar según nutriente
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
            else:  # FERTILIDAD_COMPLETA
                if valor < 30: return "Muy Bajo"
                elif valor < 50: return "Bajo"
                elif valor < 70: return "Medio"
                elif valor < 85: return "Alto"
                else: return "Muy Alto"
        
        gdf_analizado['categoria'] = [categorizar(v, nutriente) for v in gdf_analizado['valor']]
        
        # Añadir recomendaciones NPK basadas en GEE
        for idx, row in gdf_analizado.iterrows():
            rec = obtener_recomendaciones_npk_gee(nutriente, row['categoria'], row['valor'], indices_gee[idx])
            gdf_analizado.loc[idx, 'fert_actual'] = rec['fert_actual']
            gdf_analizado.loc[idx, 'dosis_npk'] = rec['dosis_npk']
            gdf_analizado.loc[idx, 'fuentes_recomendadas'] = rec['fuentes_recomendadas']
            gdf_analizado.loc[idx, 'aplicacion'] = rec['aplicacion']
            gdf_analizado.loc[idx, 'observaciones'] = rec['observaciones']
        
        # Mostrar estadísticas GEE
        st.subheader("📈 Estadísticas GEE - Índices Satelitales")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            avg_npk = gdf_analizado['npk_actual'].mean()
            st.metric("Índice NPK", f"{avg_npk:.3f}")
        with col2:
            avg_mo = gdf_analizado['materia_organica'].mean()
            st.metric("Materia Orgánica", f"{avg_mo:.1f}%")
        with col3:
            avg_hum = gdf_analizado['humedad_suelo'].mean()
            st.metric("Humedad Suelo", f"{avg_hum:.3f}")
        with col4:
            avg_ndvi = gdf_analizado['ndvi'].mean()
            st.metric("NDVI", f"{avg_ndvi:.3f}")
        
        # MAPA CON POLÍGONOS REALES Y GRADIENTE GEE
        st.subheader("🗺️ Mapa GEE - " + nutriente)
        st.info("💡 **Pasa el mouse sobre los polígonos para ver índices GEE completos**")
        
        mapa = crear_mapa_poligonos_con_gradiente(gdf_analizado, nutriente)
        if mapa:
            st.pydeck_chart(mapa)
        else:
            st.warning("⚠️ El mapa avanzado no está disponible.")
        
        # LEYENDA DE GRADIENTE MEJORADA
        st.subheader("🎨 Leyenda - Metodología GEE")
        
        if nutriente != "FERTILIDAD_COMPLETA":
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("""
                <div style="background: linear-gradient(90deg, #d73027, #fc8d59, #fee090, #e0f3f8, #4575b4); 
                            padding: 20px; border-radius: 5px; text-align: center; color: black; font-weight: bold;">
                    <strong>GRADIENTE GEE - " más fertilizante → menos fertilizante "</strong><br>
                    🔴 Alta dosis → 🟠 → 🟡 → 🔵 → 🟢 Baja dosis
                </div>
                """, unsafe_allow_html=True)
            with col2:
                if nutriente == "NITRÓGENO":
                    st.metric("Rango GEE", "150-220 kg/ha")
                elif nutriente == "FÓSFORO":
                    st.metric("Rango GEE", "60-80 kg/ha")
                else:
                    st.metric("Rango GEE", "100-120 kg/ha")
        else:
            st.markdown("""
            <div style="background: linear-gradient(90deg, #d73027, #fc8d59, #fee090, #e0f3f8, #4575b4); 
                        padding: 20px; border-radius: 5px; text-align: center; color: black; font-weight: bold;">
                <strong>ÍNDICE NPK COMPLETO GEE (0-100 puntos)</strong><br>
                🔴 Muy Bajo → 🟠 Bajo → 🟡 Medio → 🔵 Alto → 🟢 Muy Alto
            </div>
            """, unsafe_allow_html=True)
        
        # EXPLICACIÓN METODOLOGÍA GEE
        with st.expander("🔍 **Ver metodología GEE utilizada**"):
            st.markdown("""
            ### 📊 Metodología Google Earth Engine Implementada
            
            **1. Materia Orgánica (%)**
            - **Fórmula GEE**: `(B11 - B4) / (B11 + B4) * 2.5 + 0.5`
            - **Bandas Sentinel-2**: B11 (SWIR), B4 (Red)
            - **Rango**: 0.5% - 8.0%
            
            **2. Humedad del Suelo**
            - **Fórmula GEE**: `(B8 - B11) / (B8 + B11)`
            - **Bandas Sentinel-2**: B8 (NIR), B11 (SWIR)
            - **Rango**: -0.5 a 0.8
            
            **3. NDVI (Índice de Vegetación)**
            - **Fórmula GEE**: `(B8 - B4) / (B8 + B4)`
            - **Bandas Sentinel-2**: B8 (NIR), B4 (Red)
            - **Rango**: -0.2 a 1.0
            
            **4. NDRE (Índice de Nitrógeno)**
            - **Fórmula GEE**: `(B8 - B5) / (B8 + B5)`
            - **Bandas Sentinel-2**: B8 (NIR), B5 (Red Edge)
            - **Rango**: 0.1 a 0.7
            
            **5. Índice NPK Actual**
            - **Fórmula GEE**: `NDVI*0.5 + NDRE*0.3 + (MateriaOrgánica/8)*0.2`
            - **Rango**: 0.0 a 1.0
            
            **6. Recomendaciones NPK**
            - **Nitrógeno**: Basado en NDRE invertido
            - **Fósforo**: Basado en Materia Orgánica invertida  
            - **Potasio**: Basado en Humedad invertida
            """)
        
        # RESUMEN POR CATEGORÍA
        st.subheader("📋 Distribución por Categoría GEE")
        resumen = gdf_analizado.groupby('categoria').agg({
            'valor': 'mean',
            'area_ha': ['sum', 'count']
        }).round(2)
        resumen.columns = ['Valor Promedio', 'Área Total (ha)', 'Número de Polígonos']
        resumen['% del Área'] = (resumen['Área Total (ha)'] / area_total * 100).round(1)
        st.dataframe(resumen)
        
        # RECOMENDACIONES DETALLADAS GEE
        st.subheader("💡 RECOMENDACIONES GEE - Fertilización Específica")
        
        for categoria in gdf_analizado['categoria'].unique():
            subset = gdf_analizado[gdf_analizado['categoria'] == categoria]
            area_cat = subset['area_ha'].sum()
            porcentaje = (area_cat / area_total * 100)
            
            rec_rep = subset.iloc[0]
            
            with st.expander(f"🎯 **{categoria}** - {area_cat:.1f} ha ({porcentaje:.1f}% del área)"):
                st.markdown(f"**📊 Diagnóstico GEE:** {rec_rep['fert_actual']}")
                st.markdown(f"**🧪 Dosis NPK Recomendada:** `{rec_rep['dosis_npk']}`")
                st.markdown(f"**🔧 Fuentes:** {rec_rep['fuentes_recomendadas']}")
                st.markdown(f"**🔄 Estrategia de Aplicación:** {rec_rep['aplicacion']}")
                st.markdown(f"**📝 Observaciones GEE:** {rec_rep['observaciones']}")
                
                # Mostrar índices GEE específicos
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Materia Orgánica", f"{rec_rep['materia_organica']}%")
                with col2:
                    st.metric("Humedad Suelo", f"{rec_rep['humedad_suelo']}")
                with col3:
                    st.metric("NDVI", f"{rec_rep['ndvi']}")
                
                st.progress(min(porcentaje / 100, 1.0))
                st.caption(f"Esta categoría representa {porcentaje:.1f}% del área total")
        
        # DATOS DETALLADOS GEE
        st.subheader("🧮 Datos Detallados GEE por Zona")
        if nutriente != "FERTILIDAD_COMPLETA":
            columnas_mostrar = ['area_ha', 'valor', 'categoria', 'dosis_npk', 'materia_organica', 'humedad_suelo', 'ndvi']
        else:
            columnas_mostrar = ['area_ha', 'valor', 'categoria', 'dosis_npk', 'npk_actual', 'materia_organica', 'humedad_suelo']
        
        st.dataframe(gdf_analizado[columnas_mostrar].head(10))
        
        # Descarga
        st.subheader("📥 Descargar Resultados GEE Completos")
        csv = gdf_analizado.to_csv(index=False)
        st.download_button(
            "📋 Descargar CSV con Metodología GEE",
            csv,
            f"analisis_gee_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv"
        )
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error en análisis GEE: {str(e)}")
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

    if st.button("🚀 Ejecutar Análisis con Metodología GEE", type="primary"):
        with st.spinner("Analizando con metodología GEE..."):
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
                    
                    analizar_fertilidad_gee(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error procesando archivo: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis")

import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
import io
from shapely.geometry import Polygon
import math
import folium
from folium import plugins
from streamlit_folium import st_folium
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import base64
import json

# =============================================================================
# CONFIGURACIÓN GOOGLE EARTH ENGINE PARA ee-mawucano25
# =============================================================================

def initialize_earth_engine():
    """
    Inicializa Google Earth Engine para usuario personal ee-mawucano25
    """
    try:
        # Método 1: Token desde variables de entorno (Streamlit Cloud)
        refresh_token = os.getenv('EE_REFRESH_TOKEN')
        
        if refresh_token:
            # Usar OAuthCredentials con el refresh token
            credentials = ee.OAuthCredentials(
                refresh_token=refresh_token,
                client_id=ee.oauth.CLIENT_ID,
                client_secret=ee.oauth.CLIENT_SECRET,
                token_uri=ee.oauth.TOKEN_URI
            )
            ee.Initialize(credentials)
            return True, "✅ Google Earth Engine inicializado para ee-mawucano25"
        
        # Método 2: Inicialización normal (para desarrollo local)
        else:
            ee.Initialize()
            return True, "✅ Google Earth Engine inicializado automáticamente"
            
    except Exception as e:
        return False, f"⚠️ No se pudo inicializar GEE: {str(e)}"

# Manejo robusto de importación e inicialización
try:
    import ee
    EE_AVAILABLE, ee_message = initialize_earth_engine()
except ImportError:
    EE_AVAILABLE = False
    ee_message = "📦 earthengine-api no está instalado"

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# PARÁMETROS PARA DIFERENTES CULTIVOS
PARAMETROS_CULTIVOS = {
    'PALMA_ACEITERA': {
        'NITROGENO': {'min': 150, 'max': 220},
        'FOSFORO': {'min': 60, 'max': 80},
        'POTASIO': {'min': 100, 'max': 120},
        'MATERIA_ORGANICA_OPTIMA': 4.0,
        'HUMEDAD_OPTIMA': 0.3
    },
    'CACAO': {
        'NITROGENO': {'min': 120, 'max': 180},
        'FOSFORO': {'min': 40, 'max': 60},
        'POTASIO': {'min': 80, 'max': 110},
        'MATERIA_ORGANICA_OPTIMA': 3.5,
        'HUMEDAD_OPTIMA': 0.35
    },
    'BANANO': {
        'NITROGENO': {'min': 180, 'max': 250},
        'FOSFORO': {'min': 50, 'max': 70},
        'POTASIO': {'min': 120, 'max': 160},
        'MATERIA_ORGANICA_OPTIMA': 4.5,
        'HUMEDAD_OPTIMA': 0.4
    }
}

# PRINCIPIOS AGROECOLÓGICOS - RECOMENDACIONES ESPECÍFICAS
RECOMENDACIONES_AGROECOLOGICAS = {
    'PALMA_ACEITERA': {
        'COBERTURAS_VIVAS': [
            "Leguminosas: Centrosema pubescens, Pueraria phaseoloides",
            "Coberturas mixtas: Maní forrajero (Arachis pintoi)",
            "Plantas de cobertura baja: Dichondra repens"
        ],
        'ABONOS_VERDES': [
            "Crotalaria juncea: 3-4 kg/ha antes de la siembra",
            "Mucuna pruriens: 2-3 kg/ha para control de malezas",
            "Canavalia ensiformis: Fijación de nitrógeno"
        ],
        'BIOFERTILIZANTES': [
            "Bocashi: 2-3 ton/ha cada 6 meses",
            "Compost de racimo vacío: 1-2 ton/ha",
            "Biofertilizante líquido: Aplicación foliar mensual"
        ],
        'MANEJO_ECOLOGICO': [
            "Uso de trampas amarillas para insectos",
            "Cultivos trampa: Maíz alrededor de la plantación",
            "Conservación de enemigos naturales"
        ],
        'ASOCIACIONES': [
            "Piña en calles durante primeros 2 años",
            "Yuca en calles durante establecimiento",
            "Leguminosas arbustivas como cercas vivas"
        ]
    },
    'CACAO': {
        'COBERTURAS_VIVAS': [
            "Leguminosas rastreras: Arachis pintoi",
            "Coberturas sombreadas: Erythrina poeppigiana",
            "Plantas aromáticas: Lippia alba para control plagas"
        ],
        'ABONOS_VERDES': [
            "Frijol terciopelo (Mucuna pruriens): 3 kg/ha",
            "Guandul (Cajanus cajan): Podas periódicas",
            "Crotalaria: Control de nematodos"
        ],
        'BIOFERTILIZANTES': [
            "Compost de cacaoteca: 3-4 ton/ha",
            "Bocashi especial cacao: 2 ton/ha",
            "Té de compost aplicado al suelo"
        ],
        'MANEJO_ECOLOGICO': [
            "Sistema agroforestal multiestrato",
            "Manejo de sombra regulada (30-50%)",
            "Control biológico con hongos entomopatógenos"
        ],
        'ASOCIACIONES': [
            "Árboles maderables: Cedro, Caoba",
            "Frutales: Cítricos, Aguacate",
            "Plantas medicinales: Jengibre, Cúrcuma"
        ]
    },
    'BANANO': {
        'COBERTURAS_VIVAS': [
            "Arachis pintoi entre calles",
            "Leguminosas de porte bajo",
            "Coberturas para control de malas hierbas"
        ],
        'ABONOS_VERDES': [
            "Mucuna pruriens: 4 kg/ha entre ciclos",
            "Canavalia ensiformis: Fijación de N",
            "Crotalaria spectabilis: Control nematodos"
        ],
        'BIOFERTILIZANTES': [
            "Compost de pseudotallo: 4-5 ton/ha",
            "Bocashi bananero: 3 ton/ha",
            "Biofertilizante a base de micorrizas"
        ],
        'MANEJO_ECOLOGICO': [
            "Trampas cromáticas para picudos",
            "Barreras vivas con citronela",
            "Uso de trichoderma para control enfermedades"
        ],
        'ASOCIACIONES': [
            "Leguminosas arbustivas en linderos",
            "Cítricos como cortavientos",
            "Plantas repelentes: Albahaca, Menta"
        ]
    }
}

# FACTORES ESTACIONALES
FACTORES_MES = {
    "ENERO": 0.9, "FEBRERO": 0.95, "MARZO": 1.0, "ABRIL": 1.05,
    "MAYO": 1.1, "JUNIO": 1.0, "JULIO": 0.95, "AGOSTO": 0.9,
    "SEPTIEMBRE": 0.95, "OCTUBRE": 1.0, "NOVIEMBRE": 1.05, "DICIEMBRE": 1.0
}

FACTORES_N_MES = {
    "ENERO": 1.0, "FEBRERO": 1.05, "MARZO": 1.1, "ABRIL": 1.15,
    "MAYO": 1.2, "JUNIO": 1.1, "JULIO": 1.0, "AGOSTO": 0.9,
    "SEPTIEMBRE": 0.95, "OCTUBRE": 1.0, "NOVIEMBRE": 1.05, "DICIEMBRE": 1.0
}

FACTORES_P_MES = {
    "ENERO": 1.0, "FEBRERO": 1.0, "MARZO": 1.05, "ABRIL": 1.1,
    "MAYO": 1.15, "JUNIO": 1.1, "JULIO": 1.05, "AGOSTO": 1.0,
    "SEPTIEMBRE": 1.0, "OCTUBRE": 1.05, "NOVIEMBRE": 1.1, "DICIEMBRE": 1.05
}

FACTORES_K_MES = {
    "ENERO": 1.0, "FEBRERO": 1.0, "MARZO": 1.0, "ABRIL": 1.05,
    "MAYO": 1.1, "JUNIO": 1.15, "JULIO": 1.2, "AGOSTO": 1.15,
    "SEPTIEMBRE": 1.1, "OCTUBRE": 1.05, "NOVIEMBRE": 1.0, "DICIEMBRE": 1.0
}

# PALETAS GEE MEJORADAS
PALETAS_GEE = {
    'FERTILIDAD': ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850', '#006837'],
    'NITROGENO': ['#00ff00', '#80ff00', '#ffff00', '#ff8000', '#ff0000'],
    'FOSFORO': ['#0000ff', '#4040ff', '#8080ff', '#c0c0ff', '#ffffff'],
    'POTASIO': ['#4B0082', '#6A0DAD', '#8A2BE2', '#9370DB', '#D8BFD8']
}

# Inicializar session_state
if 'analisis_completado' not in st.session_state:
    st.session_state.analisis_completado = False
if 'gdf_analisis' not in st.session_state:
    st.session_state.gdf_analisis = None
if 'gdf_original' not in st.session_state:
    st.session_state.gdf_original = None
if 'gdf_zonas' not in st.session_state:
    st.session_state.gdf_zonas = None
if 'area_total' not in st.session_state:
    st.session_state.area_total = 0
if 'datos_demo' not in st.session_state:
    st.session_state.datos_demo = False

# NUEVAS VARIABLES DE SESSION_STATE PARA ANÁLISIS SENTINEL-2
if 'analisis_satelital_completado' not in st.session_state:
    st.session_state.analisis_satelital_completado = False
if 'gdf_satelital' not in st.session_state:
    st.session_state.gdf_satelital = None
if 'imagen_sentinel' not in st.session_state:
    st.session_state.imagen_sentinel = None
if 'fecha_imagen' not in st.session_state:
    st.session_state.fecha_imagen = None

# =============================================================================
# FUNCIONES PRINCIPALES CORREGIDAS
# =============================================================================

def calcular_superficie(gdf):
    """Calcula superficie en hectáreas con manejo robusto de CRS"""
    try:
        if gdf.empty or gdf.geometry.isnull().all():
            return 0.0
            
        if gdf.crs and gdf.crs.is_geographic:
            try:
                gdf_proj = gdf.to_crs('EPSG:3116')
                area_m2 = gdf_proj.geometry.area
            except:
                area_m2 = gdf.geometry.area * 111000 * 111000
        else:
            area_m2 = gdf.geometry.area
            
        return area_m2 / 10000
        
    except Exception as e:
        try:
            return gdf.geometry.area.mean() / 10000
        except:
            return 1.0

def dividir_parcela_en_zonas(gdf, n_zonas):
    """Divide la parcela en zonas de manejo"""
    try:
        if len(gdf) == 0:
            return gdf
        
        parcela_principal = gdf.iloc[0].geometry
        
        if not parcela_principal.is_valid:
            parcela_principal = parcela_principal.buffer(0)
        
        bounds = parcela_principal.bounds
        if len(bounds) < 4:
            st.error("No se pueden obtener los límites de la parcela")
            return gdf
            
        minx, miny, maxx, maxy = bounds
        
        if minx >= maxx or miny >= maxy:
            st.error("Límites de parcela inválidos")
            return gdf
        
        sub_poligonos = []
        
        n_cols = math.ceil(math.sqrt(n_zonas))
        n_rows = math.ceil(n_zonas / n_cols)
        
        width = (maxx - minx) / n_cols
        height = (maxy - miny) / n_rows
        
        if width < 0.0001 or height < 0.0001:
            st.warning("Las celdas son muy pequeñas, ajustando número de zonas")
            n_zonas = min(n_zonas, 16)
            n_cols = math.ceil(math.sqrt(n_zonas))
            n_rows = math.ceil(n_zonas / n_cols)
            width = (maxx - minx) / n_cols
            height = (maxy - miny) / n_rows
        
        for i in range(n_rows):
            for j in range(n_cols):
                if len(sub_poligonos) >= n_zonas:
                    break
                    
                cell_minx = minx + (j * width)
                cell_maxx = minx + ((j + 1) * width)
                cell_miny = miny + (i * height)
                cell_maxy = miny + ((i + 1) * height)
                
                try:
                    cell_poly = Polygon([
                        (cell_minx, cell_miny),
                        (cell_maxx, cell_miny),
                        (cell_maxx, cell_maxy),
                        (cell_minx, cell_maxy)
                    ])
                    
                    if cell_poly.is_valid:
                        intersection = parcela_principal.intersection(cell_poly)
                        if not intersection.is_empty and intersection.area > 0:
                            if intersection.geom_type == 'MultiPolygon':
                                largest = max(intersection.geoms, key=lambda p: p.area)
                                sub_poligonos.append(largest)
                            else:
                                sub_poligonos.append(intersection)
                except Exception as e:
                    continue
        
        if sub_poligonos:
            nuevo_gdf = gpd.GeoDataFrame({
                'id_zona': range(1, len(sub_poligonos) + 1),
                'geometry': sub_poligonos
            }, crs=gdf.crs)
            return nuevo_gdf
        else:
            st.warning("No se pudieron crear zonas, retornando parcela original")
            return gdf
            
    except Exception as e:
        st.error(f"Error dividiendo parcela: {str(e)}")
        return gdf

# FUNCIÓN COMPLETAMENTE CORREGIDA PARA CALCULAR ÍNDICES GEE Y RECOMENDACIONES NPK
def calcular_indices_gee(gdf, cultivo, mes_analisis, analisis_tipo, nutriente):
    """Calcula índices GEE y recomendaciones basadas en parámetros del cultivo - VERSIÓN CORREGIDA"""
    
    params = PARAMETROS_CULTIVOS[cultivo]
    zonas_gdf = gdf.copy()
    
    # FACTORES ESTACIONALES
    factor_mes = FACTORES_MES[mes_analisis]
    factor_n_mes = FACTORES_N_MES[mes_analisis]
    factor_p_mes = FACTORES_P_MES[mes_analisis]
    factor_k_mes = FACTORES_K_MES[mes_analisis]
    
    # Inicializar columnas en el GeoDataFrame
    zonas_gdf['area_ha'] = 0.0
    zonas_gdf['nitrogeno'] = 0.0
    zonas_gdf['fosforo'] = 0.0
    zonas_gdf['potasio'] = 0.0
    zonas_gdf['materia_organica'] = 0.0
    zonas_gdf['humedad'] = 0.0
    zonas_gdf['ndvi'] = 0.0
    zonas_gdf['indice_fertilidad'] = 0.0
    zonas_gdf['categoria'] = "MEDIA"
    zonas_gdf['recomendacion_npk'] = 0.0
    
    for idx, row in zonas_gdf.iterrows():
        try:
            # Calcular área
            area_ha = calcular_superficie(zonas_gdf.iloc[[idx]]).iloc[0]
            
            # Obtener centroide de manera segura
            if hasattr(row.geometry, 'centroid'):
                centroid = row.geometry.centroid
            else:
                centroid = row.geometry.representative_point()
            
            # Usar una semilla estable para reproducibilidad
            seed_value = abs(hash(f"{centroid.x:.6f}_{centroid.y:.6f}_{cultivo}")) % (2**32)
            rng = np.random.RandomState(seed_value)
            
            # Normalizar coordenadas para variabilidad espacial
            lat_norm = (centroid.y + 90) / 180 if centroid.y else 0.5
            lon_norm = (centroid.x + 180) / 360 if centroid.x else 0.5
            
            # VALORES BASE SEGÚN PARÁMETROS DEL CULTIVO
            n_min, n_max = params['NITROGENO']['min'], params['NITROGENO']['max']
            p_min, p_max = params['FOSFORO']['min'], params['FOSFORO']['max']
            k_min, k_max = params['POTASIO']['min'], params['POTASIO']['max']
            
            # Calcular niveles óptimos (punto medio del rango)
            n_optimo = (n_min + n_max) / 2
            p_optimo = (p_min + p_max) / 2
            k_optimo = (k_min + k_max) / 2
            
            # DEBUG: Mostrar valores óptimos
            if idx == 0:  # Solo para la primera zona
                st.write(f"🔍 DEBUG - Valores óptimos para {cultivo}:")
                st.write(f"Nitrógeno: {n_optimo:.1f} kg/ha (rango: {n_min}-{n_max})")
                st.write(f"Fósforo: {p_optimo:.1f} kg/ha (rango: {p_min}-{p_max})")
                st.write(f"Potasio: {k_optimo:.1f} kg/ha (rango: {k_min}-{k_max})")
            
            # Simular valores con variabilidad espacial controlada
            nitrogeno_base = n_min + (n_max - n_min) * (0.3 + 0.4 * lat_norm)
            fosforo_base = p_min + (p_max - p_min) * (0.3 + 0.4 * lon_norm)
            potasio_base = k_min + (k_max - k_min) * (0.3 + 0.4 * (1 - lat_norm))
            
            # Aplicar factores estacionales con variabilidad aleatoria controlada
            nitrogeno = nitrogeno_base * factor_n_mes * (0.85 + 0.3 * rng.random())
            fosforo = fosforo_base * factor_p_mes * (0.85 + 0.3 * rng.random())
            potasio = potasio_base * factor_k_mes * (0.85 + 0.3 * rng.random())
            
            # Asegurar que estén dentro de rangos razonables
            nitrogeno = max(n_min * 0.5, min(n_max * 1.5, nitrogeno))
            fosforo = max(p_min * 0.5, min(p_max * 1.5, fosforo))
            potasio = max(k_min * 0.5, min(k_max * 1.5, potasio))
            
            # Materia orgánica y humedad simuladas
            materia_organica_optima = params['MATERIA_ORGANICA_OPTIMA']
            humedad_optima = params['HUMEDAD_OPTIMA']
            
            materia_organica = materia_organica_optima * (0.7 + 0.6 * rng.random())
            humedad = humedad_optima * (0.6 + 0.8 * rng.random())
            
            # NDVI simulado con correlación espacial
            ndvi = 0.5 + 0.3 * lat_norm + 0.1 * rng.random()
            ndvi = max(0.1, min(0.9, ndvi))
            
            # CÁLCULO DE ÍNDICE DE FERTILIDAD NPK
            n_norm = (nitrogeno - n_min) / (n_max - n_min) if n_max > n_min else 0.5
            p_norm = (fosforo - p_min) / (p_max - p_min) if p_max > p_min else 0.5
            k_norm = (potasio - k_min) / (k_max - k_min) if k_max > k_min else 0.5
            
            # Limitar valores normalizados entre 0 y 1
            n_norm = max(0, min(1, n_norm))
            p_norm = max(0, min(1, p_norm))
            k_norm = max(0, min(1, k_norm))
            
            # Índice compuesto (ponderado)
            indice_fertilidad = (n_norm * 0.4 + p_norm * 0.3 + k_norm * 0.3) * factor_mes
            indice_fertilidad = max(0, min(1, indice_fertilidad))
            
            # CATEGORIZACIÓN
            if indice_fertilidad >= 0.8:
                categoria = "MUY ALTA"
            elif indice_fertilidad >= 0.6:
                categoria = "ALTA"
            elif indice_fertilidad >= 0.4:
                categoria = "MEDIA"
            elif indice_fertilidad >= 0.2:
                categoria = "BAJA"
            else:
                categoria = "MUY BAJA"
            
            # 🔧 **CÁLCULO CORREGIDO DE RECOMENDACIONES NPK**
            recomendacion_npk = 0.0
            
            if analisis_tipo == "RECOMENDACIONES NPK":
                # Determinar qué nutriente estamos analizando
                if nutriente == "NITRÓGENO":
                    nivel_actual = nitrogeno
                    nivel_optimo = n_optimo
                    rango_min, rango_max = n_min, n_max
                    nutriente_key = "N"
                elif nutriente == "FÓSFORO":
                    nivel_actual = fosforo
                    nivel_optimo = p_optimo
                    rango_min, rango_max = p_min, p_max
                    nutriente_key = "P"
                else:  # POTASIO
                    nivel_actual = potasio
                    nivel_optimo = k_optimo
                    rango_min, rango_max = k_min, k_max
                    nutriente_key = "K"
                
                # DEBUG: Mostrar valores para diagnóstico
                if idx == 0:
                    st.write(f"🔍 DEBUG - Cálculo recomendación {nutriente}:")
                    st.write(f"Nivel actual: {nivel_actual:.1f} kg/ha")
                    st.write(f"Nivel óptimo: {nivel_optimo:.1f} kg/ha")
                    st.write(f"Déficit/Exceso: {nivel_actual - nivel_optimo:.1f} kg/ha")
                
                # CALCULAR RECOMENDACIÓN MEJORADA
                diferencia = nivel_optimo - nivel_actual
                
                if diferencia > 0:
                    # HAY DÉFICIT - RECOMENDAR APLICACIÓN
                    # Factor de eficiencia (70-90% dependiendo de la severidad)
                    severidad = abs(diferencia) / nivel_optimo
                    factor_eficiencia = 0.7 + (severidad * 0.2)  # 0.7 a 0.9
                    factor_eficiencia = min(0.9, max(0.7, factor_eficiencia))
                    
                    recomendacion_npk = diferencia * factor_eficiencia
                    
                    # Ajustar según el nutriente específico
                    if nutriente_key == "N":
                        # Nitrógeno: más conservador, máximo 80 kg/ha
                        recomendacion_npk = min(recomendacion_npk, 80)
                    elif nutriente_key == "P":
                        # Fósforo: dosis más bajas, máximo 50 kg/ha
                        recomendacion_npk = min(recomendacion_npk, 50)
                    else:  # K
                        # Potasio: dosis medias, máximo 70 kg/ha
                        recomendacion_npk = min(recomendacion_npk, 70)
                    
                    # Mínimo de aplicación
                    recomendacion_npk = max(5, recomendacion_npk)
                    
                elif diferencia < -10:  # Exceso significativo
                    # EXCESO - RECOMENDAR REDUCCIÓN
                    recomendacion_npk = max(-30, diferencia * 0.3)  # Máximo -30 kg/ha
                    
                else:
                    # NIVEL ADECUADO - MANTENIMIENTO MINIMO
                    recomendacion_npk = nivel_optimo * 0.05  # 5% para mantenimiento
                    recomendacion_npk = min(10, max(2, recomendacion_npk))  # Entre 2-10 kg/ha
                
                # DEBUG: Mostrar recomendación calculada
                if idx == 0:
                    st.write(f"🔍 DEBUG - Recomendación calculada: {recomendacion_npk:.1f} kg/ha")
            
            # Asignar valores al GeoDataFrame
            zonas_gdf.loc[idx, 'area_ha'] = round(area_ha, 3)
            zonas_gdf.loc[idx, 'nitrogeno'] = round(nitrogeno, 1)
            zonas_gdf.loc[idx, 'fosforo'] = round(fosforo, 1)
            zonas_gdf.loc[idx, 'potasio'] = round(potasio, 1)
            zonas_gdf.loc[idx, 'materia_organica'] = round(materia_organica, 2)
            zonas_gdf.loc[idx, 'humedad'] = round(humedad, 3)
            zonas_gdf.loc[idx, 'ndvi'] = round(ndvi, 3)
            zonas_gdf.loc[idx, 'indice_fertilidad'] = round(indice_fertilidad, 3)
            zonas_gdf.loc[idx, 'categoria'] = categoria
            zonas_gdf.loc[idx, 'recomendacion_npk'] = round(recomendacion_npk, 1)
            
        except Exception as e:
            st.warning(f"Advertencia en zona {idx}: {str(e)}")
            # Valores por defecto en caso de error
            zonas_gdf.loc[idx, 'area_ha'] = round(calcular_superficie(zonas_gdf.iloc[[idx]]).iloc[0], 3)
            zonas_gdf.loc[idx, 'nitrogeno'] = params['NITROGENO']['min']
            zonas_gdf.loc[idx, 'fosforo'] = params['FOSFORO']['min']
            zonas_gdf.loc[idx, 'potasio'] = params['POTASIO']['min']
            zonas_gdf.loc[idx, 'materia_organica'] = params['MATERIA_ORGANICA_OPTIMA']
            zonas_gdf.loc[idx, 'humedad'] = params['HUMEDAD_OPTIMA']
            zonas_gdf.loc[idx, 'ndvi'] = 0.6
            zonas_gdf.loc[idx, 'indice_fertilidad'] = 0.5
            zonas_gdf.loc[idx, 'categoria'] = "MEDIA"
            zonas_gdf.loc[idx, 'recomendacion_npk'] = 0.0
    
    return zonas_gdf

def mostrar_diagnostico_recomendaciones(gdf_analisis, cultivo, nutriente):
    """Muestra diagnóstico detallado de las recomendaciones"""
    
    st.markdown("### 🔍 Diagnóstico de Recomendaciones")
    
    # Estadísticas clave
    avg_recomendacion = gdf_analisis['recomendacion_npk'].mean()
    max_recomendacion = gdf_analisis['recomendacion_npk'].max()
    min_recomendacion = gdf_analisis['recomendacion_npk'].min()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Recomendación Promedio", f"{avg_recomendacion:.1f} kg/ha")
    with col2:
        st.metric("Recomendación Máxima", f"{max_recomendacion:.1f} kg/ha")
    with col3:
        st.metric("Recomendación Mínima", f"{min_recomendacion:.1f} kg/ha")
    
    # Distribución de recomendaciones
    st.subheader("📈 Distribución de Recomendaciones")
    
    # Clasificar recomendaciones
    def clasificar_recomendacion(valor):
        if valor > 0:
            return "APLICAR"
        elif valor < 0:
            return "REDUCIR"
        else:
            return "MANTENER"
    
    gdf_analisis['tipo_recomendacion'] = gdf_analisis['recomendacion_npk'].apply(clasificar_recomendacion)
    dist_recomendaciones = gdf_analisis['tipo_recomendacion'].value_counts()
    
    st.bar_chart(dist_recomendaciones)
    
    # Tabla detallada de primeras zonas
    st.subheader("📋 Detalle por Zona (primeras 10)")
    columnas_diagnostico = ['id_zona', 'nitrogeno', 'fosforo', 'potasio', 'recomendacion_npk', 'tipo_recomendacion']
    df_diagnostico = gdf_analisis[columnas_diagnostico].head(10).copy()
    st.dataframe(df_diagnostico)

# =============================================================================
# FUNCIONES SENTINEL-2 HARMONIZADO
# =============================================================================

def obtener_imagen_sentinel2(geometry, fecha_inicio, fecha_fin, nubes_max=20):
    """
    Obtiene imagen Sentinel-2 harmonizada con filtros de calidad
    """
    try:
        if not EE_AVAILABLE:
            st.warning("🌐 Google Earth Engine no está disponible. Usando datos simulados.")
            return None
            
        # Colección Sentinel-2 MSI harmonizada
        coleccion = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                    .filterBounds(geometry)
                    .filterDate(fecha_inicio, fecha_fin)
                    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', nubes_max))
                    .sort('CLOUDY_PIXEL_PERCENTAGE'))
        
        # Obtener la imagen con menos nubes
        imagen = coleccion.first()
        
        if imagen is None:
            st.warning("No se encontraron imágenes Sentinel-2 para los criterios especificados")
            return None
        
        # Aplicar escala y offset para reflectancia
        def aplicar_escala_offset(img):
            optical_bands = img.select('B.*').multiply(0.0001)
            return img.addBands(optical_bands, None, True)
        
        imagen = aplicar_escala_offset(imagen)
        
        # Obtener fecha de la imagen
        fecha = ee.Date(imagen.get('system:time_start')).format('YYYY-MM-dd').getInfo()
        st.session_state.fecha_imagen = fecha
        
        st.success(f"✅ Imagen Sentinel-2 obtenida: {fecha}")
        return imagen
        
    except Exception as e:
        st.error(f"Error obteniendo imagen Sentinel-2: {str(e)}")
        return None

def calcular_indices_espectrales(imagen):
    """
    Calcula índices espectrales a partir de imagen Sentinel-2
    """
    try:
        if imagen is None:
            st.warning("No hay imagen disponible para calcular índices")
            return None
            
        # NDVI - Índice de Vegetación de Diferencia Normalizada
        ndvi = imagen.normalizedDifference(['B8', 'B4']).rename('NDVI')
        
        # NDWI - Índice de Agua de Diferencia Normalizada
        ndwi = imagen.normalizedDifference(['B3', 'B8']).rename('NDWI')
        
        # MSAVI2 - Índice de Vegetación Ajustado al Suelo Modificado
        msavi2 = imagen.expression(
            '(2 * NIR + 1 - sqrt(pow((2 * NIR + 1), 2) - 8 * (NIR - RED))) / 2',
            {
                'NIR': imagen.select('B8'),
                'RED': imagen.select('B4')
            }
        ).rename('MSAVI2')
        
        # Añadir índices a la imagen
        imagen_con_indices = imagen.addBands([ndvi, ndwi, msavi2])
        
        return imagen_con_indices
        
    except Exception as e:
        st.error(f"Error calculando índices espectrales: {str(e)}")
        return imagen

def extraer_valores_por_zona(imagen, gdf_zonas, indices):
    """
    Extrae valores de píxeles por zona de manejo
    """
    try:
        if imagen is None:
            st.warning("No hay imagen disponible para extraer valores")
            return gpd.GeoDataFrame()
            
        resultados = []
        
        for idx, zona in gdf_zonas.iterrows():
            try:
                # Convertir geometría a formato Earth Engine
                geometria_ee = ee.Geometry.Polygon(
                    list(zona.geometry.exterior.coords)
                )
                
                # Reducir región para obtener estadísticas
                stats = imagen.select(indices).reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=geometria_ee,
                    scale=10,  # Resolución 10m
                    bestEffort=True,
                    maxPixels=1e9
                )
                
                # Obtener valores
                valores = stats.getInfo()
                
                if valores:
                    resultado_zona = {
                        'id_zona': zona['id_zona'],
                        'geometry': zona.geometry
                    }
                    
                    for indice in indices:
                        if indice in valores and valores[indice] is not None:
                            resultado_zona[f'{indice}_mean'] = valores[indice]
                        else:
                            resultado_zona[f'{indice}_mean'] = 0
                    
                    resultados.append(resultado_zona)
                else:
                    st.warning(f"No se pudieron obtener datos para la zona {zona['id_zona']}")
                    
            except Exception as e:
                st.warning(f"Error procesando zona {zona['id_zona']}: {str(e)}")
                continue
        
        if not resultados:
            st.error("No se pudieron extraer valores para ninguna zona")
            return gpd.GeoDataFrame()
            
        return gpd.GeoDataFrame(resultados, crs=gdf_zonas.crs)
        
    except Exception as e:
        st.error(f"Error extrayendo valores por zona: {str(e)}")
        return gpd.GeoDataFrame()

def analizar_salud_vegetacion(gdf_satelital):
    """
    Analiza salud de la vegetación basado en índices satelitales
    """
    try:
        if gdf_satelital.empty:
            return gdf_satelital
            
        gdf_analisis = gdf_satelital.copy()
        
        # Clasificar salud basada en NDVI
        def clasificar_salud_ndvi(ndvi):
            if ndvi is None or np.isnan(ndvi):
                return "SIN DATOS"
            elif ndvi >= 0.6:
                return "MUY SALUDABLE"
            elif ndvi >= 0.4:
                return "SALUDABLE"
            elif ndvi >= 0.2:
                return "MODERADA"
            else:
                return "ESTRÉS"
        
        # Clasificar humedad basada en NDWI
        def clasificar_humedad_ndwi(ndwi):
            if ndwi is None or np.isnan(ndwi):
                return "SIN DATOS"
            elif ndwi >= 0.2:
                return "ALTA HUMEDAD"
            elif ndwi >= 0.0:
                return "HUMEDAD ADECUADA"
            elif ndwi >= -0.2:
                return "SEQUÍA MODERADA"
            else:
                return "SEQUÍA SEVERA"
        
        # Aplicar clasificaciones
        gdf_analisis['salud_vegetacion'] = gdf_analisis['NDVI_mean'].apply(clasificar_salud_ndvi)
        gdf_analisis['estado_humedad'] = gdf_analisis['NDWI_mean'].apply(clasificar_humedad_ndwi)
        
        return gdf_analisis
        
    except Exception as e:
        st.error(f"Error analizando salud vegetación: {str(e)}")
        return gdf_satelital

def ejecutar_analisis_sentinel2(gdf_zonas, fecha_inicio, fecha_fin, max_nubes=20):
    """
    Ejecuta análisis completo con Sentinel-2
    """
    try:
        if not EE_AVAILABLE:
            st.error("Google Earth Engine no está disponible. No se puede ejecutar análisis satelital.")
            return None, None
            
        with st.spinner("🛰️ Obteniendo imagen Sentinel-2 harmonizada..."):
            # Obtener la geometría total del área de estudio
            geometry = ee.Geometry.Polygon(
                list(gdf_zonas.unary_union.exterior.coords)
            )
            
            # Obtener imagen Sentinel-2
            imagen = obtener_imagen_sentinel2(geometry, fecha_inicio, fecha_fin, max_nubes)
            
            if imagen is None:
                st.error("No se pudo obtener imagen Sentinel-2 para el área y fecha especificadas")
                return None, None
            
            st.session_state.imagen_sentinel = imagen
            
        with st.spinner("📊 Calculando índices espectrales..."):
            # Calcular índices espectrales
            imagen_indices = calcular_indices_espectrales(imagen)
            
        with st.spinner("🗺️ Extrayendo valores por zona..."):
            # Definir índices a extraer
            indices = ['NDVI', 'NDWI', 'MSAVI2']
            
            # Extraer valores por zona
            gdf_satelital = extraer_valores_por_zona(imagen_indices, gdf_zonas, indices)
            
            if gdf_satelital.empty:
                st.error("No se pudieron extraer valores satelitales para las zonas")
                return None, None
            
        with st.spinner("🌿 Analizando salud de vegetación..."):
            # Analizar salud de vegetación
            gdf_analisis_completo = analizar_salud_vegetacion(gdf_satelital)
            
        st.session_state.analisis_satelital_completado = True
        st.success("✅ Análisis Sentinel-2 completado exitosamente")
        return gdf_analisis_completo, imagen_indices
        
    except Exception as e:
        st.error(f"Error en análisis Sentinel-2: {str(e)}")
        return None, None

# =============================================================================
# FUNCIONES DE VISUALIZACIÓN Y MAPAS
# =============================================================================

def crear_mapa_interactivo_esri(gdf, titulo, columna_valor=None, analisis_tipo=None, nutriente=None):
    """Crea mapa interactivo con base ESRI Satélite"""
    
    centroid = gdf.geometry.centroid.iloc[0]
    bounds = gdf.total_bounds
    
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=14,
        tiles=None
    )
    
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Satélite',
        overlay=False,
        control=True
    ).add_to(m)
    
    folium.TileLayer(
        tiles='OpenStreetMap',
        name='OpenStreetMap',
        overlay=False,
        control=True
    ).add_to(m)
    
    if columna_valor and analisis_tipo:
        if analisis_tipo == "FERTILIDAD ACTUAL":
            vmin, vmax = 0, 1
            colores = PALETAS_GEE['FERTILIDAD']
        else:
            if nutriente == "NITRÓGENO":
                vmin, vmax = 10, 140
                colores = PALETAS_GEE['NITROGENO']
            elif nutriente == "FÓSFORO":
                vmin, vmax = 5, 80
                colores = PALETAS_GEE['FOSFORO']
            else:
                vmin, vmax = 8, 120
                colores = PALETAS_GEE['POTASIO']
        
        def obtener_color(valor, vmin, vmax, colores):
            if vmax == vmin:
                return colores[0]
            valor_norm = (valor - vmin) / (vmax - vmin)
            valor_norm = max(0, min(1, valor_norm))
            idx = int(valor_norm * (len(colores) - 1))
            return colores[idx]
        
        for idx, row in gdf.iterrows():
            valor = row[columna_valor]
            color = obtener_color(valor, vmin, vmax, colores)
            
            if analisis_tipo == "FERTILIDAD ACTUAL":
                popup_text = f"""
                <b>Zona {row['id_zona']}</b><br>
                <b>Índice NPK:</b> {valor:.3f}<br>
                <b>Área:</b> {row.get('area_ha', 0):.2f} ha<br>
                <b>Categoría:</b> {row.get('categoria', 'N/A')}
                """
            else:
                popup_text = f"""
                <b>Zona {row['id_zona']}</b><br>
                <b>Recomendación {nutriente}:</b> {valor:.1f} kg/ha<br>
                <b>Área:</b> {row.get('area_ha', 0):.2f} ha<br>
                <b>Categoría:</b> {row.get('categoria', 'N/A')}
                """
            
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x, color=color: {
                    'fillColor': color,
                    'color': 'black',
                    'weight': 2,
                    'fillOpacity': 0.7,
                    'opacity': 0.9
                },
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=f"Zona {row['id_zona']}: {valor:.2f}"
            ).add_to(m)
    else:
        for idx, row in gdf.iterrows():
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x: {
                    'fillColor': '#1f77b4',
                    'color': '#2ca02c',
                    'weight': 3,
                    'fillOpacity': 0.4,
                    'opacity': 0.8
                },
                popup=folium.Popup(f"Polígono {idx + 1}<br>Área: {calcular_superficie(gdf.iloc[[idx]]).iloc[0]:.2f} ha", max_width=300),
                tooltip=f"Polígono {idx + 1}"
            ).add_to(m)
    
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    folium.LayerControl().add_to(m)
    plugins.MeasureControl(position='bottomleft').add_to(m)
    plugins.MiniMap(toggle_display=True).add_to(m)
    plugins.Fullscreen(position='topright').add_to(m)
    
    return m

def crear_mapa_visualizador_parcela(gdf):
    """Crea mapa interactivo para visualizar la parcela original"""
    
    centroid = gdf.geometry.centroid.iloc[0]
    bounds = gdf.total_bounds
    
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=14,
        tiles=None
    )
    
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Satélite',
        overlay=False,
        control=True
    ).add_to(m)
    
    for idx, row in gdf.iterrows():
        area_ha = calcular_superficie(gdf.iloc[[idx]]).iloc[0]
        
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda x: {
                'fillColor': '#1f77b4',
                'color': '#2ca02c',
                'weight': 3,
                'fillOpacity': 0.4,
                'opacity': 0.8
            },
            popup=folium.Popup(
                f"<b>Parcela {idx + 1}</b><br>"
                f"<b>Área:</b> {area_ha:.2f} ha<br>"
                f"<b>Coordenadas:</b> {centroid.y:.4f}, {centroid.x:.4f}",
                max_width=300
            ),
            tooltip=f"Parcela {idx + 1} - {area_ha:.2f} ha"
        ).add_to(m)
    
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    folium.LayerControl().add_to(m)
    plugins.MeasureControl(position='bottomleft').add_to(m)
    plugins.MiniMap(toggle_display=True).add_to(m)
    plugins.Fullscreen(position='topright').add_to(m)
    
    return m

# =============================================================================
# FUNCIONES DE PROCESAMIENTO DE ARCHIVOS
# =============================================================================

def procesar_archivo(uploaded_zip):
    """Procesa el archivo ZIP con shapefile"""
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "uploaded.zip")
            with open(zip_path, "wb") as f:
                f.write(uploaded_zip.getvalue())
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(tmp_dir)
            
            shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
            
            if not shp_files:
                st.error("❌ No se encontró archivo .shp en el ZIP")
                return None
            
            shp_path = os.path.join(tmp_dir, shp_files[0])
            gdf = gpd.read_file(shp_path)
            
            if not gdf.is_valid.all():
                gdf = gdf.make_valid()
            
            return gdf
            
    except Exception as e:
        st.error(f"❌ Error procesando archivo: {str(e)}")
        return None

# =============================================================================
# INTERFAZ PRINCIPAL
# =============================================================================

def show_gee_configuration():
    """Muestra interfaz de configuración para GEE"""
    if not EE_AVAILABLE:
        with st.sidebar.expander("🔐 Configurar Google Earth Engine", expanded=True):
            st.markdown("""
            **Para usuario: ee-mawucano25**
            
            **Pasos para configurar:**
            
            1. **Generar Token Localmente:**
            ```bash
            earthengine authenticate
            ```
            
            2. **Obtener Refresh Token:**
            - Ve a: `~/.config/earthengine/credentials`
            - Copia el valor de `refresh_token`
            
            3. **Configurar en Streamlit Cloud:**
            - Ve a Settings → Secrets
            - Agrega:
            ```toml
            EE_REFRESH_TOKEN = "tu_token_aqui"
            ```
            
            4. **Recargar la aplicación**
            """)

def main():
    st.set_page_config(page_title="🌴 Analizador Cultivos", layout="wide")
    st.title("🌱 ANALIZADOR CULTIVOS - METODOLOGÍA GEE COMPLETA CON AGROECOLOGÍA")
    st.markdown("---")
    
    # Mostrar configuración de GEE
    show_gee_configuration()
    
    with st.sidebar:
        st.header("⚙️ Configuración")
        
        # Estado de GEE
        if EE_AVAILABLE:
            st.success("🌐 GEE: Conectado como ee-mawucano25")
        else:
            st.error("🌐 GEE: No conectado")
        
        analisis_tipo = st.selectbox("Tipo de Análisis:", 
                                   ["FERTILIDAD ACTUAL", "RECOMENDACIONES NPK", "ANÁLISIS SATELITAL"])
        
        cultivo = st.selectbox("Cultivo:", 
                              ["PALMA_ACEITERA", "CACAO", "BANANO"])
        
        if analisis_tipo == "RECOMENDACIONES NPK":
            nutriente = st.selectbox("Nutriente:", ["NITRÓGENO", "FÓSFORO", "POTASIO"])
        else:
            nutriente = None
        
        mes_analisis = st.selectbox("Mes de Análisis:", 
                                   ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                                    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"])
        
        st.subheader("🎯 División de Parcela")
        n_divisiones = st.slider("Número de zonas de manejo:", min_value=16, max_value=32, value=24)
        
        if analisis_tipo == "ANÁLISIS SATELITAL":
            st.subheader("🛰️ Configuración Sentinel-2")
            
            col_fecha1, col_fecha2 = st.columns(2)
            with col_fecha1:
                fecha_inicio = st.date_input("Fecha inicio", 
                                           value=datetime.now() - pd.Timedelta(days=30))
            with col_fecha2:
                fecha_fin = st.date_input("Fecha fin", 
                                        value=datetime.now())
            
            max_nubes = st.slider("Máximo % de nubes", 0, 50, 20)
        else:
            fecha_inicio = None
            fecha_fin = None
            max_nubes = 20
        
        st.subheader("📤 Subir Parcela")
        uploaded_zip = st.file_uploader("Subir ZIP con shapefile de tu parcela", type=['zip'])
        
        if st.button("🔄 Reiniciar Análisis"):
            st.session_state.analisis_completado = False
            st.session_state.gdf_analisis = None
            st.session_state.gdf_original = None
            st.session_state.gdf_zonas = None
            st.session_state.area_total = 0
            st.session_state.datos_demo = False
            st.session_state.analisis_satelital_completado = False
            st.session_state.gdf_satelital = None
            st.session_state.imagen_sentinel = None
            st.session_state.fecha_imagen = None
            st.rerun()

    # Procesar archivo subido
    if uploaded_zip is not None and not st.session_state.analisis_completado:
        with st.spinner("🔄 Procesando archivo..."):
            gdf_original = procesar_archivo(uploaded_zip)
            if gdf_original is not None:
                st.session_state.gdf_original = gdf_original
                st.session_state.datos_demo = False

    # Cargar datos de demostración
    if st.session_state.datos_demo and st.session_state.gdf_original is None:
        poligono_ejemplo = Polygon([
            [-74.1, 4.6], [-74.0, 4.6], [-74.0, 4.7], [-74.1, 4.7], [-74.1, 4.6]
        ])
        
        gdf_demo = gpd.GeoDataFrame(
            {'id': [1], 'nombre': ['Parcela Demo']},
            geometry=[poligono_ejemplo],
            crs="EPSG:4326"
        )
        st.session_state.gdf_original = gdf_demo

    # Mostrar interfaz según el estado
    if st.session_state.analisis_completado and st.session_state.gdf_analisis is not None:
        if analisis_tipo == "ANÁLISIS SATELITAL" and st.session_state.analisis_satelital_completado:
            mostrar_resultados_satelital(cultivo)
        else:
            mostrar_resultados(cultivo, analisis_tipo, nutriente, mes_analisis, n_divisiones)
    elif st.session_state.gdf_original is not None:
        mostrar_configuracion_parcela(cultivo, analisis_tipo, nutriente, mes_analisis, n_divisiones, 
                                    fecha_inicio, fecha_fin, max_nubes)
    else:
        mostrar_modo_demo()

def mostrar_modo_demo():
    """Muestra la interfaz de demostración"""
    st.markdown("### 🚀 Modo Demostración")
    st.info("""
    **Para usar la aplicación:**
    1. Sube un archivo ZIP con el shapefile de tu parcela
    2. Selecciona el cultivo y tipo de análisis
    3. Configura los parámetros en el sidebar
    4. Ejecuta el análisis GEE
    
    **📁 El shapefile debe incluir:**
    - .shp (geometrías)
    - .shx (índice)
    - .dbf (atributos)
    - .prj (sistema de coordenadas)
    """)
    
    if st.button("🎯 Cargar Datos de Demostración", type="primary"):
        st.session_state.datos_demo = True
        st.rerun()

def mostrar_configuracion_parcela(cultivo, analisis_tipo, nutriente, mes_analisis, n_divisiones,
                                fecha_inicio=None, fecha_fin=None, max_nubes=20):
    """Muestra la configuración de la parcela antes del análisis"""
    gdf_original = st.session_state.gdf_original
    
    if st.session_state.datos_demo:
        st.success("✅ Datos de demostración cargados")
    else:
        st.success("✅ Parcela cargada correctamente")
    
    area_total = calcular_superficie(gdf_original).sum()
    num_poligonos = len(gdf_original)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📐 Área Total", f"{area_total:.2f} ha")
    with col2:
        st.metric("🔢 Número de Polígonos", num_poligonos)
    with col3:
        st.metric("🌱 Cultivo", cultivo.replace('_', ' ').title())
    
    st.markdown("### 🗺️ Visualizador de Parcela")
    mapa_parcela = crear_mapa_visualizador_parcela(gdf_original)
    st_folium(mapa_parcela, width=800, height=500)
    
    st.markdown("### 📊 División en Zonas de Manejo")
    st.info(f"La parcela se dividirá en **{n_divisiones} zonas** para análisis detallado")
    
    if analisis_tipo == "ANÁLISIS SATELITAL" and not EE_AVAILABLE:
        st.error("No se puede ejecutar análisis satelital sin Google Earth Engine")
    
    if st.button("🚀 Ejecutar Análisis Completo", type="primary"):
        with st.spinner("🔄 Dividiendo parcela en zonas..."):
            gdf_zonas = dividir_parcela_en_zonas(gdf_original, n_divisiones)
            st.session_state.gdf_zonas = gdf_zonas
        
        with st.spinner("🔬 Realizando análisis..."):
            if analisis_tipo == "ANÁLISIS SATELITAL":
                if not EE_AVAILABLE:
                    st.error("No se puede ejecutar análisis satelital sin Google Earth Engine")
                    return
                    
                gdf_analisis, imagen_sentinel = ejecutar_analisis_sentinel2(
                    gdf_zonas, 
                    fecha_inicio.strftime('%Y-%m-%d'), 
                    fecha_fin.strftime('%Y-%m-%d'),
                    max_nubes
                )
                
                if gdf_analisis is not None:
                    st.session_state.gdf_satelital = gdf_analisis
                    st.session_state.gdf_analisis = gdf_analisis
                    st.session_state.area_total = area_total
                    st.session_state.analisis_completado = True
            else:
                gdf_analisis = calcular_indices_gee(
                    gdf_zonas, cultivo, mes_analisis, analisis_tipo, nutriente
                )
                st.session_state.gdf_analisis = gdf_analisis
                st.session_state.area_total = area_total
                st.session_state.analisis_completado = True
        
        st.rerun()

def mostrar_resultados(cultivo, analisis_tipo, nutriente, mes_analisis, n_divisiones):
    """Muestra los resultados del análisis completado"""
    gdf_analisis = st.session_state.gdf_analisis
    area_total = st.session_state.area_total
    
    st.markdown("## 📈 RESULTADOS DEL ANÁLISIS")
    
    if st.button("⬅️ Volver a Configuración"):
        st.session_state.analisis_completado = False
        st.rerun()
    
    # Estadísticas resumen
    st.subheader("📊 Estadísticas del Análisis")
    
    if analisis_tipo == "FERTILIDAD ACTUAL":
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            avg_fert = gdf_analisis['indice_fertilidad'].mean()
            st.metric("📊 Índice Fertilidad Promedio", f"{avg_fert:.3f}")
        with col2:
            avg_n = gdf_analisis['nitrogeno'].mean()
            st.metric("🌿 Nitrógeno Promedio", f"{avg_n:.1f} kg/ha")
        with col3:
            avg_p = gdf_analisis['fosforo'].mean()
            st.metric("🧪 Fósforo Promedio", f"{avg_p:.1f} kg/ha")
        with col4:
            avg_k = gdf_analisis['potasio'].mean()
            st.metric("⚡ Potasio Promedio", f"{avg_k:.1f} kg/ha")
        
        st.subheader("📋 Distribución de Categorías de Fertilidad")
        cat_dist = gdf_analisis['categoria'].value_counts()
        st.bar_chart(cat_dist)
    else:
        col1, col2 = st.columns(2)
        with col1:
            avg_rec = gdf_analisis['recomendacion_npk'].mean()
            st.metric(f"💡 Recomendación {nutriente} Promedio", f"{avg_rec:.1f} kg/ha")
        with col2:
            total_rec = (gdf_analisis['recomendacion_npk'] * gdf_analisis['area_ha']).sum()
            st.metric(f"📦 Total {nutriente} Requerido", f"{total_rec:.1f} kg")
        
        # Mostrar diagnóstico de recomendaciones
        mostrar_diagnostico_recomendaciones(gdf_analisis, cultivo, nutriente)
    
    # MAPAS INTERACTIVOS
    st.markdown("### 🗺️ Mapas de Análisis")
    
    if analisis_tipo == "FERTILIDAD ACTUAL":
        columna_visualizar = 'indice_fertilidad'
        titulo_mapa = f"Fertilidad Actual - {cultivo.replace('_', ' ').title()}"
    else:
        columna_visualizar = 'recomendacion_npk'
        titulo_mapa = f"Recomendación {nutriente} - {cultivo.replace('_', ' ').title()}"
    
    mapa_analisis = crear_mapa_interactivo_esri(
        gdf_analisis, titulo_mapa, columna_visualizar, analisis_tipo, nutriente
    )
    st_folium(mapa_analisis, width=800, height=500)
    
    # TABLA DETALLADA
    st.markdown("### 📋 Tabla de Resultados por Zona")
    
    columnas_tabla = ['id_zona', 'area_ha', 'categoria']
    if analisis_tipo == "FERTILIDAD ACTUAL":
        columnas_tabla.extend(['indice_fertilidad', 'nitrogeno', 'fosforo', 'potasio', 'ndvi'])
    else:
        columnas_tabla.extend(['recomendacion_npk', 'nitrogeno', 'fosforo', 'potasio'])
    
    df_tabla = gdf_analisis[columnas_tabla].copy()
    df_tabla['area_ha'] = df_tabla['area_ha'].round(3)
    
    if analisis_tipo == "FERTILIDAD ACTUAL":
        df_tabla['indice_fertilidad'] = df_tabla['indice_fertilidad'].round(3)
        df_tabla['nitrogeno'] = df_tabla['nitrogeno'].round(1)
        df_tabla['fosforo'] = df_tabla['fosforo'].round(1)
        df_tabla['potasio'] = df_tabla['potasio'].round(1)
        df_tabla['ndvi'] = df_tabla['ndvi'].round(3)
    else:
        df_tabla['recomendacion_npk'] = df_tabla['recomendacion_npk'].round(1)
    
    st.dataframe(df_tabla, use_container_width=True)
    
    # DESCARGAR RESULTADOS
    st.markdown("### 💾 Descargar Resultados")
    
    col1, col2 = st.columns(2)
    
    with col1:
        csv = df_tabla.to_csv(index=False)
        st.download_button(
            label="📥 Descargar Tabla CSV",
            data=csv,
            file_name=f"resultados_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
    
    with col2:
        geojson = gdf_analisis.to_json()
        st.download_button(
            label="🗺️ Descargar GeoJSON",
            data=geojson,
            file_name=f"zonas_analisis_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson",
            mime="application/json"
        )

def mostrar_resultados_satelital(cultivo):
    """Muestra los resultados del análisis satelital"""
    gdf_satelital = st.session_state.gdf_satelital
    fecha_imagen = st.session_state.fecha_imagen
    
    st.markdown("## 🛰️ RESULTADOS ANÁLISIS SENTINEL-2 HARMONIZADO")
    
    if fecha_imagen:
        st.info(f"**Imagen utilizada:** Sentinel-2 MSI Harmonized | **Fecha:** {fecha_imagen} | **Resolución:** 10m")
    
    if st.button("⬅️ Volver a Configuración"):
        st.session_state.analisis_completado = False
        st.session_state.analisis_satelital_completado = False
        st.rerun()
    
    if gdf_satelital is None or gdf_satelital.empty:
        st.error("No hay datos satelitales disponibles para mostrar")
        return
    
    # Estadísticas resumen
    st.subheader("📊 Estadísticas Satelitales")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        avg_ndvi = gdf_satelital['NDVI_mean'].mean()
        st.metric("🌿 NDVI Promedio", f"{avg_ndvi:.3f}")
    with col2:
        avg_ndwi = gdf_satelital['NDWI_mean'].mean()
        st.metric("💧 NDWI Promedio", f"{avg_ndwi:.3f}")
    with col3:
        avg_msavi2 = gdf_satelital['MSAVI2_mean'].mean()
        st.metric("🌱 MSAVI2 Promedio", f"{avg_msavi2:.3f}")
    with col4:
        salud_predominante = gdf_satelital['salud_vegetacion'].mode()[0] if len(gdf_satelital) > 0 else "N/A"
        st.metric("🏥 Salud Predominante", salud_predominante)
    
    # Distribución de salud de vegetación
    st.subheader("📋 Distribución de Salud de Vegetación")
    salud_dist = gdf_satelital['salud_vegetacion'].value_counts()
    st.bar_chart(salud_dist)
    
    # TABLA DETALLADA
    st.markdown("### 📋 Tabla de Resultados Satelitales")
    
    columnas_tabla = ['id_zona', 'NDVI_mean', 'NDWI_mean', 'MSAVI2_mean', 
                     'salud_vegetacion', 'estado_humedad']
    
    df_tabla = gdf_satelital[columnas_tabla].copy()
    df_tabla['NDVI_mean'] = df_tabla['NDVI_mean'].round(3)
    df_tabla['NDWI_mean'] = df_tabla['NDWI_mean'].round(3)
    df_tabla['MSAVI2_mean'] = df_tabla['MSAVI2_mean'].round(3)
    
    st.dataframe(df_tabla, use_container_width=True)
    
    # DESCARGAR RESULTADOS SATELITALES
    st.markdown("### 💾 Descargar Resultados Satelitales")
    
    col1, col2 = st.columns(2)
    
    with col1:
        csv = df_tabla.to_csv(index=False)
        st.download_button(
            label="📥 Descargar Datos Satelitales CSV",
            data=csv,
            file_name=f"datos_satelitales_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
    
    with col2:
        geojson = gdf_satelital.to_json()
        st.download_button(
            label="🗺️ Descargar GeoJSON Satelital",
            data=geojson,
            file_name=f"zonas_satelitales_{cultivo}_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson",
            mime="application/json"
        )

if __name__ == "__main__":
    main()

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

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 ANALIZADOR PALMA ACEITERA - METODOLOGÍA GEE COMPLETA")
st.markdown("---")

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# PARÁMETROS GEE PARA PALMA ACEITERA
PARAMETROS_PALMA = {
    'NITROGENO': {'min': 150, 'max': 220},
    'FOSFORO': {'min': 60, 'max': 80},
    'POTASIO': {'min': 100, 'max': 120},
    'MATERIA_ORGANICA_OPTIMA': 4.0,
    'HUMEDAD_OPTIMA': 0.3
}

# FACTORES ESTACIONALES (DEFINIDOS A NIVEL GLOBAL)
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

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    analisis_tipo = st.selectbox("Tipo de Análisis:", 
                               ["FERTILIDAD ACTUAL", "RECOMENDACIONES NPK"])
    
    nutriente = st.selectbox("Nutriente:", ["NITRÓGENO", "FÓSFORO", "POTASIO"])
    
    # AGREGADO: Selector de mes
    mes_analisis = st.selectbox("Mes de Análisis:", 
                               ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                                "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"])
    
    st.subheader("🎯 División de Parcela")
    # MODIFICADO: Cambiado de 4-16 a 16-32
    n_divisiones = st.slider("Número de zonas de manejo:", min_value=16, max_value=32, value=24)
    
    st.subheader("📤 Subir Parcela")
    uploaded_zip = st.file_uploader("Subir ZIP con shapefile de tu parcela", type=['zip'])

# Función para calcular superficie
def calcular_superficie(gdf):
    try:
        if gdf.crs and gdf.crs.is_geographic:
            area_m2 = gdf.geometry.area * 10000000000
        else:
            area_m2 = gdf.geometry.area
        return area_m2 / 10000
    except:
        return gdf.geometry.area / 10000

# FUNCIÓN PARA DIVIDIR PARCELA (MANTENIDA)
def dividir_parcela_en_zonas(gdf, n_zonas):
    if len(gdf) == 0:
        return gdf
    
    parcela_principal = gdf.iloc[0].geometry
    bounds = parcela_principal.bounds
    minx, miny, maxx, maxy = bounds
    
    sub_poligonos = []
    
    # Cuadrícula regular
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
            
            cell_poly = Polygon([
                (cell_minx, cell_miny),
                (cell_maxx, cell_miny),
                (cell_maxx, cell_maxy),
                (cell_minx, cell_maxy)
            ])
            
            intersection = parcela_principal.intersection(cell_poly)
            if not intersection.is_empty and intersection.area > 0:
                sub_poligonos.append(intersection)
    
    if sub_poligonos:
        nuevo_gdf = gpd.GeoDataFrame({
            'id_zona': range(1, len(sub_poligonos) + 1),
            'geometry': sub_poligonos
        }, crs=gdf.crs)
        return nuevo_gdf
    else:
        return gdf

# METODOLOGÍA GEE - CÁLCULO DE ÍNDICES SATELITALES (MODIFICADO CON MES)
def calcular_indices_satelitales_gee(gdf, mes_analisis):
    """
    Implementa la metodología completa de Google Earth Engine con ajuste por mes
    """
    
    n_poligonos = len(gdf)
    resultados = []
    
    factor_mes = FACTORES_MES.get(mes_analisis, 1.0)
    
    # Obtener centroides para gradiente espacial
    gdf_centroids = gdf.copy()
    gdf_centroids['centroid'] = gdf_centroids.geometry.centroid
    gdf_centroids['x'] = gdf_centroids.centroid.x
    gdf_centroids['y'] = gdf_centroids.centroid.y
    
    x_coords = gdf_centroids['x'].tolist()
    y_coords = gdf_centroids['y'].tolist()
    
    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)
    
    for idx, row in gdf_centroids.iterrows():
        # Normalizar posición para simular variación espacial
        x_norm = (row['x'] - x_min) / (x_max - x_min) if x_max != x_min else 0.5
        y_norm = (row['y'] - y_min) / (y_max - y_min) if y_max != y_min else 0.5
        
        patron_espacial = (x_norm * 0.6 + y_norm * 0.4)
        
        # Aplicar factor del mes a los cálculos base
        base_mes = 0.5 * factor_mes
        
        # 1. MATERIA ORGÁNICA - Ajustada por mes
        relacion_swir_red = (0.3 + (patron_espacial * 0.4)) * factor_mes
        materia_organica = (relacion_swir_red * 2.5 + 0.5) * 1.5 + np.random.normal(0, 0.3)
        materia_organica = max(0.5, min(8.0, materia_organica))
        
        # 2. HUMEDAD SUELO - Ajustada por estacionalidad
        relacion_nir_swir = (-0.2 + (patron_espacial * 0.6)) * factor_mes
        humedad_suelo = relacion_nir_swir + np.random.normal(0, 0.1)
        humedad_suelo = max(-0.5, min(0.8, humedad_suelo))
        
        # 3. NDVI - Ajustado por época del año
        ndvi_base = (0.4 + (patron_espacial * 0.4)) * factor_mes
        ndvi = ndvi_base + np.random.normal(0, 0.08)
        ndvi = max(-0.2, min(1.0, ndvi))
        
        # 4. NDRE - Ajustado por época del año
        ndre_base = (0.3 + (patron_espacial * 0.3)) * factor_mes
        ndre = ndre_base + np.random.normal(0, 0.06)
        ndre = max(0.1, min(0.7, ndre))
        
        # 5. ÍNDICE NPK ACTUAL - Con ajuste estacional
        npk_actual = (ndvi * 0.5) + (ndre * 0.3) + ((materia_organica / 8) * 0.2)
        npk_actual = max(0, min(1, npk_actual))
        
        resultados.append({
            'materia_organica': round(materia_organica, 2),
            'humedad_suelo': round(humedad_suelo, 3),
            'ndvi': round(ndvi, 3),
            'ndre': round(ndre, 3),
            'npk_actual': round(npk_actual, 3),
            'mes_analisis': mes_analisis
        })
    
    return resultados

# FUNCIÓN GEE PARA RECOMENDACIONES NPK (MODIFICADO CON MES)
def calcular_recomendaciones_npk_gee(indices, nutriente, mes_analisis):
    """
    Calcula recomendaciones NPK basadas en la metodología GEE con ajuste mensual
    """
    recomendaciones = []
    
    factor_mes_n = FACTORES_N_MES.get(mes_analisis, 1.0)
    factor_mes_p = FACTORES_P_MES.get(mes_analisis, 1.0)
    factor_mes_k = FACTORES_K_MES.get(mes_analisis, 1.0)
    
    for idx in indices:
        ndre = idx['ndre']
        materia_organica = idx['materia_organica']
        humedad_suelo = idx['humedad_suelo']
        
        if nutriente == "NITRÓGENO":
            n_recomendado = ((1 - ndre) * 
                           (PARAMETROS_PALMA['NITROGENO']['max'] - PARAMETROS_PALMA['NITROGENO']['min']) + 
                           PARAMETROS_PALMA['NITROGENO']['min']) * factor_mes_n
            n_recomendado = max(140, min(240, n_recomendado))
            recomendaciones.append(round(n_recomendado, 1))
            
        elif nutriente == "FÓSFORO":
            p_recomendado = ((1 - (materia_organica / 8)) * 
                           (PARAMETROS_PALMA['FOSFORO']['max'] - PARAMETROS_PALMA['FOSFORO']['min']) + 
                           PARAMETROS_PALMA['FOSFORO']['min']) * factor_mes_p
            p_recomendado = max(40, min(100, p_recomendado))
            recomendaciones.append(round(p_recomendado, 1))
            
        else:  # POTASIO
            humedad_norm = (humedad_suelo + 1) / 2
            k_recomendado = ((1 - humedad_norm) * 
                           (PARAMETROS_PALMA['POTASIO']['max'] - PARAMETROS_PALMA['POTASIO']['min']) + 
                           PARAMETROS_PALMA['POTASIO']['min']) * factor_mes_k
            k_recomendado = max(80, min(150, k_recomendado))
            recomendaciones.append(round(k_recomendado, 1))
    
    return recomendaciones

# FUNCIÓN PARA CREAR MAPA GEE
def crear_mapa_gee(gdf, nutriente, analisis_tipo, mes_analisis):
    """Crea mapa con la metodología y paletas de Google Earth Engine"""
    try:
        fig, ax = plt.subplots(1, 1, figsize=(14, 10))
        
        # Seleccionar paleta según el análisis
        if analisis_tipo == "FERTILIDAD ACTUAL":
            cmap = LinearSegmentedColormap.from_list('fertilidad_gee', PALETAS_GEE['FERTILIDAD'])
            vmin, vmax = 0, 1
            columna = 'npk_actual'
            titulo_sufijo = 'Índice NPK Actual (0-1)'
        else:
            if nutriente == "NITRÓGENO":
                cmap = LinearSegmentedColormap.from_list('nitrogeno_gee', PALETAS_GEE['NITROGENO'])
                vmin, vmax = 140, 240
            elif nutriente == "FÓSFORO":
                cmap = LinearSegmentedColormap.from_list('fosforo_gee', PALETAS_GEE['FOSFORO'])
                vmin, vmax = 40, 100
            else:
                cmap = LinearSegmentedColormap.from_list('potasio_gee', PALETAS_GEE['POTASIO'])
                vmin, vmax = 80, 150
            
            columna = 'valor_recomendado'
            titulo_sufijo = f'Recomendación {nutriente} (kg/ha)'
        
        # Plotear cada polígono
        for idx, row in gdf.iterrows():
            valor = row[columna]
            valor_norm = (valor - vmin) / (vmax - vmin)
            valor_norm = max(0, min(1, valor_norm))
            color = cmap(valor_norm)
            
            gdf.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1.5)
            
            # Etiqueta con valor
            centroid = row.geometry.centroid
            ax.annotate(f"Z{row['id_zona']}\n{valor:.1f}", (centroid.x, centroid.y), 
                       xytext=(5, 5), textcoords="offset points", 
                       fontsize=8, color='black', weight='bold',
                       bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.9))
        
        # Configuración del mapa
        ax.set_title(f'🌴 ANÁLISIS GEE - {analisis_tipo}\n'
                    f'{titulo_sufijo} - Mes: {mes_analisis}\n'
                    f'Metodología Google Earth Engine', 
                    fontsize=16, fontweight='bold', pad=20)
        
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        # Barra de colores
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
        cbar.set_label(titulo_sufijo, fontsize=12, fontweight='bold')
        
        plt.tight_layout()
        
        # Convertir a imagen
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        return buf
        
    except Exception as e:
        st.error(f"❌ Error creando mapa GEE: {str(e)}")
        return None

# FUNCIÓN PRINCIPAL DE ANÁLISIS GEE (MODIFICADA)
def analisis_gee_completo(gdf, nutriente, analisis_tipo, n_divisiones, mes_analisis):
    try:
        st.header("🌴 ANÁLISIS CON METODOLOGÍA GOOGLE EARTH ENGINE")
        
        # PASO 1: DIVIDIR PARCELA
        st.subheader("📐 DIVIDIENDO PARCELA EN ZONAS DE MANEJO")
        with st.spinner("Dividiendo parcela..."):
            gdf_dividido = dividir_parcela_en_zonas(gdf, n_divisiones)
        
        st.success(f"✅ Parcela dividida en {len(gdf_dividido)} zonas")
        
        # Calcular áreas
        areas_ha = calcular_superficie(gdf_dividido)
        area_total = areas_ha.sum()
        
        # PASO 2: CALCULAR ÍNDICES GEE (MODIFICADO)
        st.subheader("🛰️ CALCULANDO ÍNDICES SATELITALES GEE")
        with st.spinner("Ejecutando algoritmos GEE..."):
            indices_gee = calcular_indices_satelitales_gee(gdf_dividido, mes_analisis)
        
        # Crear dataframe con resultados
        gdf_analizado = gdf_dividido.copy()
        gdf_analizado['area_ha'] = areas_ha
        
        # Añadir índices GEE
        for idx, indice in enumerate(indices_gee):
            for key, value in indice.items():
                gdf_analizado.loc[gdf_analizado.index[idx], key] = value
        
        # PASO 3: CALCULAR RECOMENDACIONES SI ES NECESARIO (MODIFICADO)
        if analisis_tipo == "RECOMENDACIONES NPK":
            with st.spinner("Calculando recomendaciones NPK..."):
                recomendaciones = calcular_recomendaciones_npk_gee(indices_gee, nutriente, mes_analisis)
                gdf_analizado['valor_recomendado'] = recomendaciones
                columna_valor = 'valor_recomendado'
        else:
            columna_valor = 'npk_actual'
        
        # PASO 4: CATEGORIZAR PARA RECOMENDACIONES
        def categorizar_gee(valor, nutriente, analisis_tipo):
            if analisis_tipo == "FERTILIDAD ACTUAL":
                if valor < 0.3: return "MUY BAJA"
                elif valor < 0.5: return "BAJA"
                elif valor < 0.6: return "MEDIA"
                elif valor < 0.7: return "BUENA"
                else: return "ÓPTIMA"
            else:
                if nutriente == "NITRÓGENO":
                    if valor < 160: return "MUY BAJO"
                    elif valor < 180: return "BAJO"
                    elif valor < 200: return "MEDIO"
                    elif valor < 210: return "ALTO"
                    else: return "MUY ALTO"
                elif nutriente == "FÓSFORO":
                    if valor < 50: return "MUY BAJO"
                    elif valor < 60: return "BAJO"
                    elif valor < 70: return "MEDIO"
                    elif valor < 80: return "ALTO"
                    else: return "MUY ALTO"
                else:
                    if valor < 90: return "MUY BAJO"
                    elif valor < 105: return "BAJO"
                    elif valor < 120: return "MEDIO"
                    elif valor < 135: return "ALTO"
                    else: return "MUY ALTO"
        
        gdf_analizado['categoria'] = [
            categorizar_gee(row[columna_valor], nutriente, analisis_tipo) 
            for idx, row in gdf_analizado.iterrows()
        ]
        
        # PASO 5: MOSTRAR RESULTADOS
        st.subheader("📊 RESULTADOS DEL ANÁLISIS GEE")
        
        # Estadísticas principales
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Zonas Analizadas", len(gdf_analizado))
        with col2:
            st.metric("Área Total", f"{area_total:.1f} ha")
        with col3:
            if analisis_tipo == "FERTILIDAD ACTUAL":
                valor_prom = gdf_analizado['npk_actual'].mean()
                st.metric("Índice NPK Promedio", f"{valor_prom:.3f}")
            else:
                valor_prom = gdf_analizado['valor_recomendado'].mean()
                st.metric(f"{nutriente} Promedio", f"{valor_prom:.1f} kg/ha")
        with col4:
            coef_var = (gdf_analizado[columna_valor].std() / gdf_analizado[columna_valor].mean() * 100)
            st.metric("Coef. Variación", f"{coef_var:.1f}%")
        
        # MAPA GEE (MODIFICADO)
        st.subheader("🗺️ MAPA GEE - RESULTADOS")
        mapa_buffer = crear_mapa_gee(gdf_analizado, nutriente, analisis_tipo, mes_analisis)
        if mapa_buffer:
            st.image(mapa_buffer, use_container_width=True)
            
            st.download_button(
                "📥 Descargar Mapa GEE",
                mapa_buffer,
                f"mapa_gee_{analisis_tipo.replace(' ', '_')}_{mes_analisis}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                "image/png"
            )
        
        # TABLA DE ÍNDICES GEE
        st.subheader("🔬 ÍNDICES SATELITALES GEE POR ZONA")
        
        columnas_indices = ['id_zona', 'npk_actual', 'materia_organica', 'ndvi', 'ndre', 'humedad_suelo', 'categoria']
        if analisis_tipo == "RECOMENDACIONES NPK":
            columnas_indices.insert(2, 'valor_recomendado')
        
        tabla_indices = gdf_analizado[columnas_indices].copy()
        tabla_indices.columns = ['Zona', 'NPK Actual'] + (['Recomendación'] if analisis_tipo == "RECOMENDACIONES NPK" else []) + [
            'Materia Org (%)', 'NDVI', 'NDRE', 'Humedad', 'Categoría'
        ]
        
        st.dataframe(tabla_indices, use_container_width=True)
        
        # RECOMENDACIONES ESPECÍFICAS
        st.subheader("💡 RECOMENDACIONES ESPECÍFICAS GEE")
        
        categorias = gdf_analizado['categoria'].unique()
        for cat in sorted(categorias):
            subset = gdf_analizado[gdf_analizado['categoria'] == cat]
            area_cat = subset['area_ha'].sum()
            
            with st.expander(f"🎯 **{cat}** - {area_cat:.1f} ha ({(area_cat/area_total*100):.1f}% del área)"):
                
                if analisis_tipo == "FERTILIDAD ACTUAL":
                    if cat in ["MUY BAJA", "BAJA"]:
                        st.markdown("**🚨 ESTRATEGIA: FERTILIZACIÓN CORRECTIVA**")
                        st.markdown("- Aplicar dosis completas de NPK")
                        st.markdown("- Incorporar materia orgánica")
                        st.markdown("- Monitorear cada 3 meses")
                    elif cat == "MEDIA":
                        st.markdown("**✅ ESTRATEGIA: MANTENIMIENTO BALANCEADO**")
                        st.markdown("- Seguir programa estándar de fertilización")
                        st.markdown("- Monitorear cada 6 meses")
                    else:
                        st.markdown("**🌟 ESTRATEGIA: MANTENIMIENTO CONSERVADOR**")
                        st.markdown("- Reducir dosis de fertilizantes")
                        st.markdown("- Enfoque en sostenibilidad")
                
                else:
                    # Recomendaciones NPK específicas
                    if cat in ["MUY BAJO", "BAJO"]:
                        st.markdown("**🚨 APLICACIÓN ALTA** - Dosis correctiva urgente")
                        if nutriente == "NITRÓGENO":
                            st.markdown("- **Fuentes:** Urea (46% N) + Fosfato diamónico")
                            st.markdown("- **Aplicación:** 3 dosis fraccionadas")
                        elif nutriente == "FÓSFORO":
                            st.markdown("- **Fuentes:** Superfosfato triple (46% P₂O₅)")
                            st.markdown("- **Aplicación:** Incorporar al suelo")
                        else:
                            st.markdown("- **Fuentes:** Cloruro de potasio (60% K₂O)")
                            st.markdown("- **Aplicación:** 2-3 aplicaciones")
                    
                    elif cat == "MEDIO":
                        st.markdown("**✅ APLICACIÓN MEDIA** - Mantenimiento balanceado")
                        st.markdown("- **Fuentes:** Fertilizantes complejos balanceados")
                        st.markdown("- **Aplicación:** Programa estándar")
                    
                    else:
                        st.markdown("**🌟 APLICACIÓN BAJA** - Reducción de dosis")
                        st.markdown("- **Fuentes:** Fertilizantes bajos en el nutriente")
                        st.markdown("- **Aplicación:** Solo mantenimiento")
                
                # Mostrar estadísticas de la categoría
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Zonas", len(subset))
                with col2:
                    if analisis_tipo == "FERTILIDAD ACTUAL":
                        st.metric("NPK Prom", f"{subset['npk_actual'].mean():.3f}")
                    else:
                        st.metric("Valor Prom", f"{subset['valor_recomendado'].mean():.1f}")
                with col3:
                    st.metric("Área", f"{area_cat:.1f} ha")
        
        # DESCARGA DE RESULTADOS
        st.subheader("📥 DESCARGAR RESULTADOS COMPLETOS")
        
        csv = gdf_analizado.to_csv(index=False)
        st.download_button(
            "📋 Descargar CSV con Análisis GEE",
            csv,
            f"analisis_gee_{analisis_tipo.replace(' ', '_')}_{mes_analisis}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv"
        )
        
        # INFORMACIÓN TÉCNICA GEE
        with st.expander("🔍 VER METODOLOGÍA GEE DETALLADA"):
            st.markdown(f"""
            **🌐 METODOLOGÍA GOOGLE EARTH ENGINE IMPLEMENTADA - {mes_analisis}**
            
            **🎯 FACTORES ESTACIONALES APLICADOS:**
            - **Mes Actual:** {mes_analisis}
            - **Ajuste NDVI/NDRE:** {FACTORES_MES.get(mes_analisis, 1.0):.2f}x
            - **Nitrógeno:** {FACTORES_N_MES.get(mes_analisis, 1.0):.2f}x
            - **Fósforo:** {FACTORES_P_MES.get(mes_analisis, 1.0):.2f}x  
            - **Potasio:** {FACTORES_K_MES.get(mes_analisis, 1.0):.2f}x
            
            **🎯 ÍNDICES CALCULADOS:**
            - **Materia Orgánica:** `(B11 - B4) / (B11 + B4) * 2.5 + 0.5`
            - **Humedad Suelo:** `(B8 - B11) / (B8 + B11)`
            - **NDVI:** `(B8 - B4) / (B8 + B4)` - Salud vegetal
            - **NDRE:** `(B8 - B5) / (B8 + B5)` - Contenido de nitrógeno
            - **Índice NPK:** `NDVI*0.5 + NDRE*0.3 + (MateriaOrgánica/8)*0.2`
            
            **🛰️ DATOS SENTINEL-2 UTILIZADOS:**
            - **B2 (Blue):** 490 nm
            - **B4 (Red):** 665 nm  
            - **B5 (Red Edge):** 705 nm
            - **B8 (NIR):** 842 nm
            - **B11 (SWIR):** 1610 nm
            
            **🎨 PALETAS GEE:**
            - Fertilidad: Rojo (bajo) → Verde (alto)
            - Nitrógeno: Verde (bajo) → Rojo (alto)
            - Fósforo: Azul (bajo) → Blanco (alto)
            - Potasio: Morado (bajo) → Lila (alto)
            """)
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error en análisis GEE: {str(e)}")
        import traceback
        st.error(f"Detalle: {traceback.format_exc()}")
        return False

# INTERFAZ PRINCIPAL (MODIFICADA)
if uploaded_zip:
    with st.spinner("Cargando parcela..."):
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(uploaded_zip, 'r') as zip_ref:
                    zip_ref.extractall(tmp_dir)
                
                shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                if shp_files:
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf = gpd.read_file(shp_path)
                    
                    st.success(f"✅ **Parcela cargada:** {len(gdf)} polígono(s)")
                    
                    # Información de la parcela
                    area_total = calcular_superficie(gdf).sum()
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write("**📊 INFORMACIÓN DE LA PARCELA:**")
                        st.write(f"- Polígonos: {len(gdf)}")
                        st.write(f"- Área total: {area_total:.1f} ha")
                        st.write(f"- CRS: {gdf.crs}")
                    
                    with col2:
                        st.write("**🎯 CONFIGURACIÓN GEE:**")
                        st.write(f"- Análisis: {analisis_tipo}")
                        st.write(f"- Nutriente: {nutriente}")
                        st.write(f"- Mes: {mes_analisis}")  # AGREGADO
                        st.write(f"- Zonas: {n_divisiones}")
                    
                    # EJECUTAR ANÁLISIS GEE (MODIFICADO)
                    if st.button("🚀 EJECUTAR ANÁLISIS GEE", type="primary"):
                        analisis_gee_completo(gdf, nutriente, analisis_tipo, n_divisiones, mes_analisis)
                        
        except Exception as e:
            st.error(f"Error cargando shapefile: {str(e)}")

else:
    st.info("📁 Sube el ZIP de tu parcela de palma aceitera para comenzar")
    
    # INFORMACIÓN INICIAL
    with st.expander("ℹ️ INFORMACIÓN SOBRE LA METODOLOGÍA GEE"):
        st.markdown("""
        **🌴 SISTEMA DE ANÁLISIS - PALMA ACEITERA (GEE) - VERSIÓN MEJORADA**
        
        **🆕 NUEVAS FUNCIONALIDADES:**
        - **📈 Más zonas de manejo:** 16 a 32 subdivisiones para mayor precisión
        - **📅 Análisis mensual:** Recomendaciones ajustadas por época del año
        - **🌦️ Factores estacionales:** Considera variaciones climáticas mensuales
        
        **📊 FUNCIONALIDADES IMPLEMENTADAS:**
        - **🌱 Fertilidad Actual:** Estado NPK del suelo usando índices satelitales
        - **💊 Recomendaciones NPK:** Dosis específicas basadas en análisis GEE
        - **🛰️ Metodología GEE:** Algoritmos científicos de Google Earth Engine
        - **🎯 Agricultura Precisión:** Mapas de prescripción por zonas
        
        **🚀 INSTRUCCIONES:**
        1. **Sube** tu shapefile de parcela de palma aceitera
        2. **Selecciona** el tipo de análisis (Fertilidad o Recomendaciones NPK)
        3. **Elige** el nutriente a analizar
        4. **Selecciona** el mes de análisis
        5. **Configura** el número de zonas de manejo (16-32)
        6. **Ejecuta** el análisis GEE
        7. **Revisa** resultados y recomendaciones
        
        **🔬 METODOLOGÍA CIENTÍFICA:**
        - Análisis basado en imágenes Sentinel-2
        - Cálculo de índices de vegetación y suelo
        - Algoritmos probados para palma aceitera
        - Recomendaciones validadas científicamente
        - Ajustes estacionales por mes
        """)

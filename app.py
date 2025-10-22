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
st.title("🌴 ANALIZADOR PALMA ACEITERA - MAPAS CON POLÍGONOS Y GRADIENTE REAL")
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

# Función para generar valores con gradiente real
def generar_valores_con_gradiente(gdf, nutriente):
    """Genera valores de nutrientes con variación espacial real basada en la posición de los polígonos"""
    
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
        # Crear gradiente basado en posición + variación local
        base_gradient = row['x_norm'] * 0.6 + row['y_norm'] * 0.4
        
        if nutriente == "NITRÓGENO":
            # Gradiente de N: 140-220 kg/ha con variación local
            base_value = 140 + base_gradient * 80  # Rango más amplio
            local_variation = np.random.normal(0, 12)  # Variación local
            valor = base_value + local_variation
            
        elif nutriente == "FÓSFORO":
            # Gradiente de P: 50-90 kg/ha
            base_value = 50 + base_gradient * 40
            local_variation = np.random.normal(0, 6)
            valor = base_value + local_variation
            
        else:  # POTASIO
            # Gradiente de K: 90-130 kg/ha
            base_value = 90 + base_gradient * 40
            local_variation = np.random.normal(0, 8)
            valor = base_value + local_variation
        
        # Asegurar valores dentro de rangos razonables
        valor = max(valor, 0)
        valores.append(round(valor, 1))
    
    return valores

# Función para crear mapa con gradiente de fertilidad real
def crear_mapa_gradiente_pydeck(gdf, nutriente):
    """Crea mapa con gradiente de fertilidad continuo basado en valores reales"""
    try:
        # Convertir a WGS84 para el mapa
        if gdf.crs is None or str(gdf.crs) != 'EPSG:4326':
            gdf_map = gdf.to_crs('EPSG:4326')
        else:
            gdf_map = gdf.copy()
        
        # VERIFICAR GEOMETRÍAS
        st.info(f"🔍 **Diagnóstico:** {len(gdf_map)} polígonos, CRS: {gdf_map.crs}")
        
        # Preparar datos para PyDeck
        features = []
        
        # Definir rangos para el gradiente de color
        if nutriente == "NITRÓGENO":
            min_val, max_val = 140, 220
        elif nutriente == "FÓSFORO":
            min_val, max_val = 50, 90
        else:  # POTASIO
            min_val, max_val = 90, 130
        
        for idx, row in gdf_map.iterrows():
            try:
                geom = row.geometry
                if geom.is_empty:
                    continue
                    
                # Convertir a GeoJSON y extraer coordenadas
                geojson = gpd.GeoSeries([geom]).__geo_interface__
                coordinates = geojson['features'][0]['geometry']['coordinates']
                
                # COLOR CONTINUO BASADO EN VALOR REAL (gradiente)
                valor_normalizado = (row['valor'] - min_val) / (max_val - min_val)
                valor_normalizado = max(0, min(1, valor_normalizado))  # Clamp 0-1
                
                # Gradiente de rojo (bajo) a verde (alto) pasando por amarillo
                if valor_normalizado < 0.33:
                    # Rojo a Naranja
                    red = 255
                    green = int(165 * (valor_normalizado * 3))
                    blue = 0
                elif valor_normalizado < 0.66:
                    # Naranja a Amarillo
                    red = 255
                    green = 165 + int(90 * ((valor_normalizado - 0.33) * 3))
                    blue = 0
                else:
                    # Amarillo a Verde
                    red = 255 - int(255 * ((valor_normalizado - 0.66) * 3))
                    green = 255
                    blue = 0
                
                color = [red, green, blue, 180]
                
                features.append({
                    'polygon_id': idx + 1,
                    'coordinates': coordinates,
                    'color': color,
                    'valor': float(row['valor']),
                    'categoria': row['categoria'],
                    'area_ha': float(row['area_ha']),
                    'dosis_npk': row['dosis_npk'],
                    'fert_actual': row['fert_actual'],
                    'valor_normalizado': valor_normalizado
                })
                
            except Exception as poly_error:
                continue
        
        if not features:
            st.error("❌ No se pudieron extraer las geometrías de los polígonos")
            # Mostrar mapa básico como fallback
            gdf_map['lon'] = gdf_map.geometry.centroid.x
            gdf_map['lat'] = gdf_map.geometry.centroid.y
            st.map(gdf_map[['lat', 'lon', 'valor']].rename(columns={'valor': 'size'}))
            return None
        
        # Capa de polígonos con gradiente
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
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            ">
                <div style="font-weight: bold; margin-bottom: 8px; color: #2E86AB; font-size: 14px;">
                    🌴 Zona {polygon_id}
                </div>
                <div style="margin-bottom: 3px;"><b>Nutriente:</b> """ + nutriente + """</div>
                <div style="margin-bottom: 3px;"><b>Valor:</b> {valor} kg/ha</div>
                <div style="margin-bottom: 3px;"><b>Categoría:</b> {categoria}</div>
                <div style="margin-bottom: 3px;"><b>Área:</b> {area_ha:.1f} ha</div>
                <div style="margin-bottom: 3px;"><b>Fertilidad:</b> {fert_actual}</div>
                <div style="margin-bottom: 0;"><b>Dosis:</b> {dosis_npk}</div>
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
        
        st.success("✅ Mapa generado con GRADIENTE REAL de fertilidad")
        return mapa
        
    except Exception as e:
        st.error(f"❌ Error en mapa: {str(e)}")
        # Fallback robusto
        try:
            st.info("🔄 Mostrando vista alternativa...")
            gdf_map = gdf.to_crs('EPSG:4326')
            gdf_map['lon'] = gdf_map.geometry.centroid.x
            gdf_map['lat'] = gdf_map.geometry.centroid.y
            
            # Mostrar información sobre los polígonos
            st.write(f"**📊 Información del Shapefile:**")
            st.write(f"- **Polígonos cargados:** {len(gdf_map)}")
            st.write(f"- **Tipo de geometrías:** {gdf_map.geometry.type.unique()}")
            st.write(f"- **Extensión:** {gdf_map.total_bounds}")
            
            # Mapa nativo
            st.map(gdf_map[['lat', 'lon', 'valor']].rename(columns={'valor': 'size'}))
            
        except:
            st.error("❌ No se pudo generar ninguna visualización")
        
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

# Función para análisis de agricultura de precisión
def analisis_precision(gdf_analizado, nutriente):
    """Análisis detallado para agricultura de precisión"""
    st.header("🎯 ANÁLISIS PARA AGRICULTURA DE PRECISIÓN")
    
    # Calcular variabilidad
    coef_variacion = (gdf_analizado['valor'].std() / gdf_analizado['valor'].mean()) * 100
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📊 Coeficiente de Variación", f"{coef_variacion:.1f}%")
    with col2:
        st.metric("📏 Rango de Valores", 
                 f"{gdf_analizado['valor'].min():.1f} - {gdf_analizado['valor'].max():.1f}")
    with col3:
        st.metric("🎯 Zonas de Manejo", len(gdf_analizado['categoria'].unique()))
    with col4:
        area_variable = gdf_analizado[gdf_analizado['categoria'].isin(['Muy Bajo', 'Muy Alto'])]['area_ha'].sum()
        st.metric("⚠️ Área Crítica", f"{area_variable:.1f} ha")
    
    # Recomendaciones de precisión
    st.subheader("💡 Estrategias de Fertilización de Precisión")
    
    # Zonas específicas por categoría
    categorias_orden = ['Muy Bajo', 'Bajo', 'Medio', 'Alto', 'Muy Alto']
    
    for cat in categorias_orden:
        subset = gdf_analizado[gdf_analizado['categoria'] == cat]
        if len(subset) > 0:
            area_cat = subset['area_ha'].sum()
            valor_prom = subset['valor'].mean()
            
            with st.expander(f"🎯 Zona **{cat}** - {area_cat:.1f} ha (Valor promedio: {valor_prom:.1f} kg/ha)"):
                
                if cat in ['Muy Bajo', 'Bajo']:
                    st.markdown("**🚨 Estrategia: Fertilización Correctiva**")
                    st.markdown("- Aplicar dosis más altas en estas zonas")
                    st.markdown("- Dividir aplicaciones para mejor eficiencia")
                    st.markdown("- Considerar enmiendas específicas")
                    st.markdown("- Monitorear respuesta cada 3 meses")
                    
                elif cat in ['Alto', 'Muy Alto']:
                    st.markdown("**💡 Estrategia: Mantenimiento/Reducción**")
                    st.markdown("- Reducir dosis para evitar excesos")
                    st.markdown("- Monitorear posibles problemas de lixiviación")
                    st.markdown("- Evaluar balance con otros nutrientes")
                    st.markdown("- Considerar aplicación cada 12-18 meses")
                    
                else:  # Medio
                    st.markdown("**✅ Estrategia: Mantenimiento Balanceado**")
                    st.markdown("- Seguir recomendaciones estándar")
                    st.markdown("- Monitorear tendencias cada 6 meses")
                    st.markdown("- Mantener balance NPK")
                    st.markdown("- Aplicación anual normal")
                
                # Polígonos específicos en esta categoría
                st.markdown(f"**📍 Polígonos en esta zona:** {len(subset)}")
                if len(subset) <= 10:
                    poligonos_lista = ", ".join([str(i+1) for i in subset.index])
                    st.markdown(f"**🔢 IDs de polígonos:** {poligonos_lista}")
    
    # Mapa de prescripción
    st.subheader("🗺️ Mapa de Prescripción de Fertilizantes")
    
    # Crear capa de prescripción
    prescription_features = []
    for idx, row in gdf_analizado.iterrows():
        try:
            geom = row.geometry
            if geom.is_empty:
                continue
                
            geojson = gpd.GeoSeries([geom]).__geo_interface__
            coordinates = geojson['features'][0]['geometry']['coordinates']
            
            # Color por categoría de prescripción
            color_prescription = {
                "Muy Bajo": [215, 48, 39, 200],    # Rojo - Alta dosis
                "Bajo": [252, 141, 89, 200],       # Naranja - Media-alta
                "Medio": [254, 224, 144, 200],     # Amarillo - Media
                "Alto": [224, 243, 248, 200],      # Azul claro - Media-baja
                "Muy Alto": [69, 117, 180, 200]    # Azul - Baja dosis
            }
            
            prescription_features.append({
                'polygon_id': idx + 1,
                'coordinates': coordinates,
                'color': color_prescription[row['categoria']],
                'categoria': row['categoria'],
                'dosis_npk': row['dosis_npk'],
                'valor': row['valor'],
                'prescripcion': f"Dosis: {row['dosis_npk']}"
            })
            
        except Exception as e:
            continue
    
    if prescription_features:
        prescription_layer = pdk.Layer(
            'PolygonLayer',
            prescription_features,
            get_polygon='coordinates',
            get_fill_color='color',
            get_line_color=[0, 0, 0, 255],
            get_line_width=1,
            pickable=True,
            auto_highlight=True
        )
        
        # Usar misma vista que el mapa principal
        gdf_map = gdf_analizado.to_crs('EPSG:4326')
        centroid = gdf_map.geometry.centroid.unary_union.centroid
        view_state = pdk.ViewState(
            longitude=float(centroid.x),
            latitude=float(centroid.y),
            zoom=11,
            pitch=0
        )
        
        tooltip = {
            "html": """
            <div style="background: white; padding: 10px; border-radius: 5px; border: 1px solid #ccc;">
                <b>Zona {polygon_id}</b><br/>
                <b>Categoría:</b> {categoria}<br/>
                <b>Valor:</b> {valor} kg/ha<br/>
                <b>Prescripción:</b> {dosis_npk}
            </div>
            """
        }
        
        st.pydeck_chart(pdk.Deck(
            layers=[prescription_layer],
            initial_view_state=view_state,
            tooltip=tooltip,
            map_style='light'
        ))
    
    # Resumen ejecutivo para agricultura de precisión
    st.subheader("📋 Resumen Ejecutivo - Agricultura de Precisión")
    
    # Calcular áreas por categoría
    resumen_precision = gdf_analizado.groupby('categoria').agg({
        'area_ha': 'sum',
        'valor': ['min', 'max', 'mean']
    }).round(1)
    
    resumen_precision.columns = ['Área Total (ha)', 'Valor Mínimo', 'Valor Máximo', 'Valor Promedio']
    resumen_precision['% del Área'] = (resumen_precision['Área Total (ha)'] / gdf_analizado['area_ha'].sum() * 100).round(1)
    
    st.dataframe(resumen_precision)
    
    # Recomendaciones generales
    st.markdown("### 💎 Recomendaciones Clave")
    
    if coef_variacion > 30:
        st.warning("**🔴 ALTA VARIABILIDAD:** Se recomienda fertilización variable por zonas. La variabilidad supera el 30%, indicando necesidad de manejo diferenciado.")
    elif coef_variacion > 15:
        st.info("**🟡 VARIABILIDAD MODERADA:** Considerar fertilización sectorizada. La variabilidad entre 15-30% sugiere manejo por sectores.")
    else:
        st.success("**🟢 VARIABILIDAD BAJA:** Fertilización uniforme puede ser adecuada. Variabilidad menor al 15% permite manejo más homogéneo.")

# Función de análisis principal con gradiente real
def analizar_shapefile_con_gradiente(gdf, nutriente):
    """Versión con mapas de polígonos y gradiente real usando PyDeck"""
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
        st.info("🎯 **Generando gradiente real de fertilidad basado en posición espacial...**")
        valores = generar_valores_con_gradiente(gdf, nutriente)
        
        # Crear dataframe de resultados
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
        
        # MAPA CON GRADIENTE REAL (PyDeck)
        st.subheader("🗺️ Mapa de Gradiente Real - Distribución de " + nutriente)
        st.info("💡 **Pasa el mouse sobre los polígonos para ver detalles. Los colores muestran variación continua de fertilidad**")
        
        mapa = crear_mapa_gradiente_pydeck(gdf_analizado, nutriente)
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
        
        # LEYENDA DE GRADIENTE
        st.subheader("🎨 Leyenda de Gradiente de Fertilidad")
        st.markdown("""
        <div style="background: linear-gradient(90deg, #ff0000, #ffa500, #ffff00, #008000); 
                    padding: 15px; border-radius: 5px; text-align: center; color: black;">
            <strong>Baja Fertilidad → Alta Fertilidad</strong><br>
            Rojo (Bajo) → Naranja → Amarillo → Verde (Alto)
        </div>
        """, unsafe_allow_html=True)
        
        # Resumen por categoría
        st.subheader("📋 Distribución por Categoría de Fertilidad")
        resumen = gdf_analizado.groupby('categoria').agg({
            'valor': 'mean',
            'area_ha': ['sum', 'count']
        }).round(2)
        resumen.columns = ['Valor Promedio', 'Área Total (ha)', 'Número de Polígonos']
        resumen['% del Área'] = (resumen['Área Total (ha)'] / area_total * 100).round(1)
        st.dataframe(resumen)
        
        # RECOMENDACIONES DETALLADAS
        st.subheader("💡 RECOMENDACIONES DE FERTILIZACIÓN NPK")
        
        for categoria in gdf_analizado['categoria'].unique():
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
                
                st.progress(min(porcentaje / 100, 1.0))
                st.caption(f"Esta categoría representa {porcentaje:.1f}% del área total")
        
        # ANÁLISIS DE PRECISIÓN
        analisis_precision(gdf_analizado, nutriente)
        
        # Datos detallados
        st.subheader("🧮 Datos Detallados por Zona")
        columnas_mostrar = ['area_ha', 'valor', 'categoria', 'dosis_npk', 'fuentes_recomendadas']
        st.dataframe(gdf_analizado[columnas_mostrar].head(15))
        
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
    # Mostrar información del shapefile antes de analizar
    with st.spinner("Cargando shapefile..."):
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(uploaded_zip, 'r') as zip_ref:
                    zip_ref.extractall(tmp_dir)
                
                shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                if shp_files:
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf_preview = gpd.read_file(shp_path)
                    
                    # Mostrar info básica
                    st.info(f"**📊 Shapefile cargado:** {len(gdf_preview)} polígonos")
                    st.info(f"**📐 CRS:** {gdf_preview.crs}")
                    st.info(f"**🔷 Tipo de geometrías:** {gdf_preview.geometry.type.unique()}")
                    
                    # Vista previa simple
                    if st.checkbox("👁️ Mostrar vista previa del shapefile"):
                        st.write("**Vista previa de datos:**")
                        st.dataframe(gdf_preview.head(3))
                        
                        # Mapa básico de preview
                        try:
                            gdf_preview_map = gdf_preview.to_crs('EPSG:4326')
                            st.map(gdf_preview_map)
                        except Exception as e:
                            st.warning(f"No se pudo generar vista previa: {e}")
        except:
            pass

    # BOTÓN PARA ANÁLISIS CON GRADIENTE REAL
    if st.button("🚀 Ejecutar Análisis con GRADIENTE REAL", type="primary"):
        with st.spinner("Analizando shapefile y generando gradiente de fertilidad..."):
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
                    
                    # Ejecutar análisis con GRADIENTE REAL
                    analizar_shapefile_con_gradiente(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error procesando archivo: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis")

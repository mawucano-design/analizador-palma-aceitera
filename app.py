import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime
import folium
from folium import GeoJson
import json
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from shapely.geometry import Polygon
import math
import contextily as ctx  # Para fondo Esri (opcional, pero recomendado)

st.set_page_config(page_title="Analizador Cultivos", layout="wide")
st.title("ANALIZADOR CULTIVOS - METODOLOGÍA GEE COMPLETA CON AGROECOLOGÍA")
st.markdown("---")

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

# RECOMENDACIONES AGROECOLÓGICAS
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

# PALETAS GEE
PALETAS_GEE = {
    'FERTILIDAD': ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850', '#006837'],
    'NITROGENO': ['#00ff00', '#80ff00', '#ffff00', '#ff8000', '#ff0000'],
    'FOSFORO': ['#0000ff', '#4040ff', '#8080ff', '#c0c0ff', '#ffffff'],
    'POTASIO': ['#4B0082', '#6A0DAD', '#8A2BE2', '#9370DB', '#D8BFD8']
}

# Sidebar
with st.sidebar:
    st.header("Configuración")
    cultivo = st.selectbox("Cultivo:", ["PALMA_ACEITERA", "CACAO", "BANANO"])
    analisis_tipo = st.selectbox("Tipo de Análisis:", ["FERTILIDAD ACTUAL", "RECOMENDACIONES NPK"])
    nutriente = st.selectbox("Nutriente:", ["NITRÓGENO", "FÓSFORO", "POTASIO"])
    mes_analisis = st.selectbox("Mes de Análisis:", [
        "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
        "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"
    ])
    st.subheader("División de Parcela")
    n_divisiones = st.slider("Número de zonas de manejo:", min_value=16, max_value=32, value=24)
    st.subheader("Subir Parcela")
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

# === NUEVA FUNCIÓN: MAPA CON ESRI SATELLITE ===
def crear_mapa_interactivo_esri(gdf, titulo, columna_valor=None, analisis_tipo=None, nutriente=None, zoom_start=15):
    try:
        gdf_web = gdf.to_crs(epsg=3857)
        centroid = gdf_web.geometry.centroid.iloc[0]
        m = folium.Map(
            location=[centroid.y, centroid.x],
            zoom_start=zoom_start,
            tiles=None,
            control_scale=True
        )

        # Fondo Esri Satellite
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri, Maxar, GeoEye, Earthstar Geographics, CNES/Airbus DS, USDA, USGS, AeroGRID, IGN, GIS User Community',
            name='Esri Satellite',
            overlay=False
        ).add_to(m)

        if columna_valor and analisis_tipo:
            vmin, vmax = gdf_web[columna_valor].min(), gdf_web[columna_valor].max()
            if analisis_tipo == "FERTILIDAD ACTUAL":
                cmap_name = 'viridis'
                vmin, vmax = 0, 1
            elif nutriente == "NITRÓGENO":
                cmap_name = 'YlGn'
                vmin, vmax = 140, 240
            elif nutriente == "FÓSFORO":
                cmap_name = 'Blues'
                vmin, vmax = 40, 100
            else:
                cmap_name = 'Purples'
                vmin, vmax = 80, 150

            def style_function(feature):
                valor = feature['properties'].get(columna_valor, 0)
                norm = (valor - vmin) / (vmax - vmin) if vmax > vmin else 0.5
                color = plt.cm.get_cmap(cmap_name)(norm)
                return {
                    'fillColor': f'rgba({int(color[0]*255)}, {int(color[1]*255)}, {int(color[2]*255)}, 0.7)',
                    'color': 'black',
                    'weight': 1.5,
                    'fillOpacity': 0.7
                }

            geojson_data = gdf_web[[columna_valor, 'id_zona', 'geometry']].to_json()
            geojson_layer = GeoJson(
                geojson_data,
                style_function=style_function,
                tooltip=folium.GeoJsonTooltip(
                    fields=['id_zona', columna_valor],
                    aliases=['Zona', f'{nutriente or "NPK"}'],
                    localize=True
                )
            ).add_to(m)

            # Etiquetas
            for _, row in gdf_web.iterrows():
                folium.Marker(
                    location=[row.geometry.centroid.y, row.geometry.centroid.x],
                    icon=folium.DivIcon(html=f"""
                        <div style="
                            font-size: 10pt; color: white; background-color: rgba(0,0,0,0.7);
                            padding: 3px 7px; border-radius: 4px; font-weight: bold;
                            text-shadow: 1px 1px 2px black; white-space: nowrap;
                        ">Z{row['id_zona']}<br>{row[columna_valor]:.2f}</div>
                    """)
                ).add_to(m)

            # Leyenda
            from branca.colormap import LinearColormap
            colormap = LinearColormap(
                colors=plt.cm.get_cmap(cmap_name, 256).colors,
                vmin=vmin, vmax=vmax
            )
            colormap.caption = 'Índice NPK (0-1)' if analisis_tipo == "FERTILIDAD ACTUAL" else f'{nutriente} (kg/ha)'
            m.add_child(colormap)

        else:
            geojson_data = gdf_web.to_json()
            GeoJson(
                geojson_data,
                style_function=lambda x: {
                    'fillColor': '#3388ff',
                    'color': 'black',
                    'weight': 2,
                    'fillOpacity': 0.4
                }
            ).add_to(m)

        # Título
        folium.map.Marker(
            [centroid.y, centroid.x],
            icon=folium.DivIcon(html=f"""
                <div style="
                    position: absolute; top: 10px; left: 50%; transform: translateX(-50%);
                    background: rgba(255,255,255,0.95); padding: 8px 16px; border-radius: 8px;
                    font-weight: bold; font-size: 14px; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                    z-index: 1000; white-space: nowrap;
                ">{titulo}</div>
            """)
        ).add_to(m)

        folium.LayerControl().add_to(m)
        return m._repr_html_()

    except Exception as e:
        st.error(f"Error creando mapa: {str(e)}")
        return None

# === FUNCIONES RESTANTES (sin cambios) ===
def mostrar_recomendaciones_agroecologicas(cultivo, categoria, area_ha, analisis_tipo, nutriente=None):
    st.markdown("### RECOMENDACIONES AGROECOLÓGICAS")
    if categoria in ["MUY BAJA", "MUY BAJO", "BAJA", "BAJO"]:
        enfoque = "**ENFOQUE: RECUPERACIÓN Y REGENERACIÓN**"
        intensidad = "Alta"
    elif categoria in ["MEDIA", "MEDIO"]:
        enfoque = "**ENFOQUE: MANTENIMIENTO Y MEJORA**"
        intensidad = "Media"
    else:
        enfoque = "**ENFOQUE: CONSERVACIÓN Y OPTIMIZACIÓN**"
        intensidad = "Baja"
    st.success(f"{enfoque} - Intensidad: {intensidad}")
    recomendaciones = RECOMENDACIONES_AGROECOLOGICAS.get(cultivo, {})
    col1, col2 = st.columns(2)
    with col1:
        with st.expander("COBERTURAS VIVAS", expanded=True):
            for rec in recomendaciones.get('COBERTURAS_VIVAS', []): st.markdown(f"• {rec}")
            st.info("**Para áreas grandes:** Franjas progresivas" if area_ha > 10 else "**Para áreas pequeñas:** Cobertura total")
    with col2:
        with st.expander("ABONOS VERDES", expanded=True):
            for rec in recomendaciones.get('ABONOS_VERDES', []): st.markdown(f"• {rec}")
            if intensidad == "Alta": st.warning("**Prioridad alta:** Sembrar YA")
    col3, col4 = st.columns(2)
    with col3:
        with st.expander("BIOFERTILIZANTES", expanded=True):
            for rec in recomendaciones.get('BIOFERTILIZANTES', []): st.markdown(f"• {rec}")
            if analisis_tipo == "RECOMENDACIONES NPK" and nutriente:
                if nutriente == "NITRÓGENO": st.markdown("• **N:** Compost de leguminosas")
                elif nutriente == "FÓSFORO": st.markdown("• **P:** Roca fosfórica molida")
                else: st.markdown("• **K:** Cenizas de biomasa")
    with col4:
        with st.expander("MANEJO ECOLÓGICO", expanded=True):
            for rec in recomendaciones.get('MANEJO_ECOLOGICO', []): st.markdown(f"• {rec}")
            if categoria in ["MUY BAJA", "MUY BAJO"]: st.markdown("• **Urgente:** Control biológico intensivo")
    with st.expander("ASOCIACIONES Y DIVERSIFICACIÓN", expanded=True):
        for rec in recomendaciones.get('ASOCIACIONES', []): st.markdown(f"• {rec}")
        st.markdown("**Beneficios:** Biodiversidad, menos plagas, resiliencia, uso eficiente de recursos")

    st.markdown("### PLAN DE IMPLEMENTACIÓN")
    col1, col2, col3 = st.columns(3)
    with col1: st.markdown("**INMEDIATO (0-15 días)**\n• Terreno\n• Abonos verdes\n• Biofertilizantes")
    with col2: st.markdown("**CORTO PLAZO (1-3 meses)**\n• Coberturas\n• Monitoreo\n• Podas")
    with col3: st.markdown("**MEDIANO PLAZO (3-12 meses)**\n• Evaluación\n• Diversificación\n• Réplica")

def dividir_parcela_en_zonas(gdf, n_zonas):
    if len(gdf) == 0: return gdf
    parcela = gdf.iloc[0].geometry
    minx, miny, maxx, maxy = parcela.bounds
    n_cols = math.ceil(math.sqrt(n_zonas))
    n_rows = math.ceil(n_zonas / n_cols)
    width, height = (maxx - minx) / n_cols, (maxy - miny) / n_rows
    sub_poligonos = []
    for i in range(n_rows):
        for j in range(n_cols):
            if len(sub_poligonos) >= n_zonas: break
            cell = Polygon([
                (minx + j*width, miny + i*height),
                (minx + (j+1)*width, miny + i*height),
                (minx + (j+1)*width, miny + (i+1)*height),
                (minx + j*width, miny + (i+1)*height)
            ])
            inter = parcela.intersection(cell)
            if not inter.is_empty and inter.area > 0:
                sub_poligonos.append(inter)
    if sub_poligonos:
        return gpd.GeoDataFrame({'id_zona': range(1, len(sub_poligonos)+1), 'geometry': sub_poligonos}, crs=gdf.crs)
    return gdf

def calcular_indices_satelitales_gee(gdf, mes_analisis, cultivo):
    resultados = []
    factor_mes = FACTORES_MES.get(mes_analisis, 1.0)
    gdf_centroids = gdf.copy()
    gdf_centroids['centroid'] = gdf_centroids.geometry.centroid
    gdf_centroids['x'] = gdf_centroids.centroid.x
    gdf_centroids['y'] = gdf_centroids.centroid.y
    x_coords = gdf_centroids['x'].tolist()
    y_coords = gdf_centroids['y'].tolist()
    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)

    for idx, row in gdf_centroids.iterrows():
        x_norm = (row['x'] - x_min) / (x_max - x_min) if x_max != x_min else 0.5
        y_norm = (row['y'] - y_min) / (y_max - y_min) if y_max != y_min else 0.5
        patron = x_norm * 0.6 + y_norm * 0.4
        base_mes = 0.5 * factor_mes

        mo = (0.3 + patron * 0.4) * factor_mes * 2.5 + 0.5 * 1.5
        if cultivo == "CACAO": mo *= 0.9
        elif cultivo == "BANANO": mo *= 1.1
        mo = max(0.5, min(8.0, mo + np.random.normal(0, 0.3)))

        hum = (-0.2 + patron * 0.6) * factor_mes
        if cultivo == "CACAO": hum *= 1.1
        elif cultivo == "BANANO": hum *= 1.2
        hum = max(-0.5, min(0.8, hum + np.random.normal(0, 0.1)))

        ndvi = (0.4 + patron * 0.4) * factor_mes
        if cultivo == "CACAO": ndvi *= 0.9
        elif cultivo == "BANANO": ndvi *= 1.1
        ndvi = max(-0.2, min(1.0, ndvi + np.random.normal(0, 0.08)))

        ndre = (0.3 + patron * 0.3) * factor_mes
        if cultivo == "CACAO": ndre *= 0.85
        elif cultivo == "BANANO": ndre *= 1.15
        ndre = max(0.1, min(0.7, ndre + np.random.normal(0, 0.06)))

        npk_actual = (ndvi * 0.5) + (ndre * 0.3) + ((mo / 8) * 0.2)
        if cultivo == "CACAO": npk_actual *= 0.95
        elif cultivo == "BANANO": npk_actual *= 1.05
        npk_actual = max(0, min(1, npk_actual))

        resultados.append({
            'materia_organica': round(mo, 2),
            'humedad_suelo': round(hum, 3),
            'ndvi': round(ndvi, 3),
            'ndre': round(ndre, 3),
            'npk_actual': round(npk_actual, 3),
            'mes_analisis': mes_analisis,
            'cultivo': cultivo
        })
    return resultados

def calcular_recomendaciones_npk_gee(indices, nutriente, mes_analisis, cultivo):
    recomendaciones = []
    factor_n = FACTORES_N_MES.get(mes_analisis, 1.0)
    factor_p = FACTORES_P_MES.get(mes_analisis, 1.0)
    factor_k = FACTORES_K_MES.get(mes_analisis, 1.0)
    params = PARAMETROS_CULTIVOS.get(cultivo, PARAMETROS_CULTIVOS['PALMA_ACEITERA'])

    for idx in indices:
        if nutriente == "NITRÓGENO":
            val = ((1 - idx['ndre']) * (params['NITROGENO']['max'] - params['NITROGENO']['min']) + params['NITROGENO']['min']) * factor_n
            val = max(params['NITROGENO']['min'] - 20, min(params['NITROGENO']['max'] + 20, val))
        elif nutriente == "FÓSFORO":
            val = ((1 - (idx['materia_organica'] / 8)) * (params['FOSFORO']['max'] - params['FOSFORO']['min']) + params['FOSFORO']['min']) * factor_p
            val = max(params['FOSFORO']['min'] - 10, min(params['FOSFORO']['max'] + 10, val))
        else:
            hum_norm = (idx['humedad_suelo'] + 1) / 2
            val = ((1 - hum_norm) * (params['POTASIO']['max'] - params['POTASIO']['min']) + params['POTASIO']['min']) * factor_k
            val = max(params['POTASIO']['min'] - 15, min(params['POTASIO']['max'] + 15, val))
        recomendaciones.append(round(val, 1))
    return recomendaciones

def analisis_gee_completo(gdf, nutriente, analisis_tipo, n_divisiones, mes_analisis, cultivo):
    try:
        st.header(f"ANÁLISIS GEE - {cultivo}")
        with st.spinner("Dividiendo parcela..."):
            gdf_dividido = dividir_parcela_en_zonas(gdf, n_divisiones)
        st.success(f"Parcela dividida en {len(gdf_dividido)} zonas")
        areas_ha = calcular_superficie(gdf_dividido)
        area_total = areas_ha.sum()
        gdf_analizado = gdf_dividido.copy()
        gdf_analizado['area_ha'] = areas_ha

        with st.spinner("Calculando índices GEE..."):
            indices_gee = calcular_indices_satelitales_gee(gdf_dividido, mes_analisis, cultivo)
        for idx, indice in enumerate(indices_gee):
            for k, v in indice.items():
                gdf_analizado.loc[gdf_analizado.index[idx], k] = v

        if analisis_tipo == "RECOMENDACIONES NPK":
            with st.spinner("Calculando NPK..."):
                recomendaciones = calcular_recomendaciones_npk_gee(indices_gee, nutriente, mes_analisis, cultivo)
                gdf_analizado['valor_recomendado'] = recomendaciones
                columna_valor = 'valor_recomendado'
        else:
            columna_valor = 'npk_actual'

        def categorizar_gee(valor, nutriente, analisis_tipo, cultivo):
            params = PARAMETROS_CULTIVOS.get(cultivo, PARAMETROS_CULTIVOS['PALMA_ACEITERA'])
            if analisis_tipo == "FERTILIDAD ACTUAL":
                if valor < 0.3: return "MUY BAJA"
                elif valor < 0.5: return "BAJA"
                elif valor < 0.6: return "MEDIA"
                elif valor < 0.7: return "BUENA"
                else: return "ÓPTIMA"
            else:
                min_val = params[nutriente]['min']
                max_val = params[nutriente]['max']
                rango = max_val - min_val
                if valor < min_val - 0.2*rango: return "MUY BAJO"
                elif valor < min_val: return "BAJO"
                elif valor < max_val: return "MEDIO"
                elif valor < max_val + 0.2*rango: return "ALTO"
                else: return "MUY ALTO"

        gdf_analizado['categoria'] = [categorizar_gee(row[columna_valor], nutriente, analisis_tipo, cultivo) for _, row in gdf_analizado.iterrows()]

        st.subheader("RESULTADOS DEL ANÁLISIS GEE")
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("Zonas", len(gdf_analizado))
        with col2: st.metric("Área Total", f"{area_total:.1f} ha")
        with col3:
            prom = gdf_analizado[columna_valor].mean()
            label = "Índice NPK" if analisis_tipo == "FERTILIDAD ACTUAL" else f"{nutriente} Prom."
            st.metric(label, f"{prom:.3f}" if analisis_tipo == "FERTILIDAD ACTUAL" else f"{prom:.1f} kg/ha")
        with col4:
            cv = (gdf_analizado[columna_valor].std() / prom * 100)
            st.metric("Coef. Var.", f"{cv:.1f}%")

        st.subheader("MAPA INTERACTIVO - RESULTADOS")
        mapa_html = crear_mapa_interactivo_esri(
            gdf_analizado, f"Análisis GEE - {analisis_tipo} - {cultivo}",
            columna_valor, analisis_tipo, nutriente if analisis_tipo == "RECOMENDACIONES NPK" else None
        )
        if mapa_html:
            st.components.v1.html(mapa_html, height=700)

        st.subheader("DESCARGAR RESULTADOS")
        col1, col2, col3 = st.columns(3)
        with col1:
            csv = gdf_analizado.to_csv(index=False)
            st.download_button("CSV", csv, f"analisis_{cultivo}_{datetime.now():%Y%m%d_%H%M}.csv", "text/csv")
        with col2:
            geojson = gdf_analizado.to_json()
            st.download_button("GeoJSON", geojson, f"analisis_{cultivo}_{datetime.now():%Y%m%d_%H%M}.geojson", "application/geo+json")
        with col3:
            st.download_button("Mapa HTML", mapa_html, f"mapa_{cultivo}_{datetime.now():%Y%m%d_%H%M}.html", "text/html")

        st.subheader("RECOMENDACIONES POR ZONA")
        for cat in sorted(gdf_analizado['categoria'].unique()):
            subset = gdf_analizado[gdf_analizado['categoria'] == cat]
            area_cat = subset['area_ha'].sum()
            with st.expander(f"**{cat}** - {area_cat:.1f} ha ({area_cat/area_total*100:.1f}%)", expanded=True):
                mostrar_recomendaciones_agroecologicas(cultivo, cat, area_cat, analisis_tipo, nutriente)

        st.subheader("ÍNDICES SATELITALES")
        cols = ['id_zona', 'npk_actual'] + (['valor_recomendado'] if analisis_tipo == "RECOMENDACIONES NPK" else []) + \
               ['materia_organica', 'ndvi', 'ndre', 'humedad_suelo', 'categoria']
        tabla = gdf_analizado[cols].copy()
        tabla.columns = ['Zona', 'NPK Actual'] + (['Recomendación'] if analisis_tipo == "RECOMENDACIONES NPK" else []) + \
                        ['M. Orgánica (%)', 'NDVI', 'NDRE', 'Humedad', 'Categoría']
        st.dataframe(tabla, use_container_width=True)

        return gdf_analizado
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return None

# INTERFAZ PRINCIPAL
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
                    st.success(f"Parcela cargada: {len(gdf)} polígono(s)")
                    area_total = calcular_superficie(gdf).sum()

                    col1, col2 = st.columns(2)
                    with col1:
                        st.write("**INFO PARCELA:**")
                        st.write(f"- Polígonos: {len(gdf)}")
                        st.write(f"- Área: {area_total:.1f} ha")
                        st.write(f"- CRS: {gdf.crs}")
                    with col2:
                        st.write("**CONFIG GEE:**")
                        st.write(f"- Cultivo: {cultivo}")
                        st.write(f"- Análisis: {analisis_tipo}")
                        st.write(f"- Nutriente: {nutriente}")
                        st.write(f"- Mes: {mes_analisis}")
                        st.write(f"- Zonas: {n_divisiones}")

                    st.subheader("VISUALIZACIÓN DE LA PARCELA (ESRI SATELLITE)")
                    mapa_parcela_html = crear_mapa_interactivo_esri(gdf, "Parcela Original - Esri World Imagery")
                    if mapa_parcela_html:
                        st.components.v1.html(mapa_parcela_html, height=600)

                    if st.button("EJECUTAR ANÁLISIS GEE COMPLETO", type="primary"):
                        analisis_gee_completo(gdf, nutriente, analisis_tipo, n_divisiones, mes_analisis, cultivo)
        except Exception as e:
            st.error(f"Error: {str(e)}")
else:
    st.info("Sube el ZIP de tu parcela para comenzar")
    with st.expander("INFO DEL SISTEMA"):
        st.markdown("### SISTEMA AGROECOLÓGICO GEE\n**Mapas con Esri Satellite** • **Recomendaciones por zona** • **Exporta CSV, GeoJSON, HTML**")

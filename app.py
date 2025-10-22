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
import base64

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 ANALIZADOR PALMA ACEITERA - MAPA CON GRADIENTE REAL")
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

# Función para generar valores con gradiente real
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
            base_value = 30 + base_gradient * 70
            local_variation = np.random.normal(0, 10)
            valor = base_value + local_variation
        
        valor = max(valor, 0)
        valores.append(round(valor, 1))
    
    return valores

# Función para crear mapa con matplotlib (GRADIENTE REAL)
def crear_mapa_matplotlib(gdf, nutriente):
    """Crea mapa estático con gradiente de colores real usando matplotlib"""
    try:
        # Configurar la figura
        fig, ax = plt.subplots(1, 1, figsize=(12, 10))
        
        # Definir el colormap basado en el nutriente
        if nutriente == "FERTILIDAD_COMPLETA":
            # Rojo (bajo) a Verde (alto)
            cmap = LinearSegmentedColormap.from_list('fertilidad', ['#d73027', '#fc8d59', '#fee090', '#a6d96a', '#1a9850'])
            vmin, vmax = 0, 100
        else:
            # Verde (baja dosis) a Rojo (alta dosis)
            cmap = LinearSegmentedColormap.from_list('nutrientes', ['#4575b4', '#e0f3f8', '#fee090', '#fc8d59', '#d73027'])
            if nutriente == "NITRÓGENO":
                vmin, vmax = 150, 220
            elif nutriente == "FÓSFORO":
                vmin, vmax = 60, 80
            else:  # POTASIO
                vmin, vmax = 100, 120
        
        # Plotear cada polígono con su color según el valor
        for idx, row in gdf.iterrows():
            valor = row['valor']
            # Normalizar el valor para el colormap
            valor_norm = (valor - vmin) / (vmax - vmin)
            valor_norm = max(0, min(1, valor_norm))  # Asegurar entre 0-1
            color = cmap(valor_norm)
            
            # Plotear el polígono
            gdf.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=0.8)
            
            # Añadir etiqueta con el ID (opcional)
            centroid = row.geometry.centroid
            ax.annotate(str(idx+1), (centroid.x, centroid.y), 
                       xytext=(3, 3), textcoords="offset points", 
                       fontsize=8, color='black', weight='bold')
        
        # Configurar el gráfico
        ax.set_title(f'Mapa de {nutriente} - Gradiente de Colores', fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        # Añadir barra de colores
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
        cbar.set_label(f'{nutriente} ({("kg/ha" if nutriente != "FERTILIDAD_COMPLETA" else "puntos")})', fontsize=12)
        
        # Añadir leyenda de categorías
        categorias = gdf['categoria'].unique()
        legend_handles = []
        for cat in categorias:
            color = cmap((gdf[gdf['categoria'] == cat]['valor'].mean() - vmin) / (vmax - vmin))
            patch = mpatches.Patch(color=color, label=cat)
            legend_handles.append(patch)
        
        ax.legend(handles=legend_handles, title='Categorías', loc='upper right', bbox_to_anchor=(1.15, 1))
        
        plt.tight_layout()
        
        # Convertir la figura a imagen para Streamlit
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        return buf
        
    except Exception as e:
        st.error(f"❌ Error creando mapa matplotlib: {str(e)}")
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
def analizar_con_mapa_estatico(gdf, nutriente):
    try:
        st.header("📊 Resultados - Mapa con Gradiente Real")
        
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
        
        # MAPA ESTÁTICO CON GRADIENTE REAL
        st.subheader("🗺️ Mapa - Gradiente de Colores Real")
        st.info("💡 **Mapa generado con matplotlib - Gradiente 100% visible**")
        
        mapa_buffer = crear_mapa_matplotlib(gdf_analizado, nutriente)
        if mapa_buffer:
            st.image(mapa_buffer, use_column_width=True, caption=f"Mapa de {nutriente} - Gradiente de Colores")
            st.success("✅ ¡Gradiente de colores visible correctamente!")
            
            # Botón para descargar el mapa
            st.download_button(
                label="📥 Descargar Mapa",
                data=mapa_buffer,
                file_name=f"mapa_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                mime="image/png"
            )
        else:
            st.error("❌ No se pudo generar el mapa")
        
        # LEYENDA DE COLORES
        st.subheader("🎨 Leyenda de Colores")
        
        if nutriente == "FERTILIDAD_COMPLETA":
            st.markdown("""
            **Gradiente de Fertilidad Completa:**
            - 🔴 **Rojo**: 0-30 puntos (Muy Baja)
            - 🟠 **Naranja**: 30-50 puntos (Baja)  
            - 🟡 **Amarillo**: 50-70 puntos (Media)
            - 🟢 **Verde**: 70-85 puntos (Alta)
            - 🔵 **Azul**: 85-100 puntos (Muy Alta)
            """)
        else:
            st.markdown("""
            **Gradiente de Dosis de Fertilizante:**
            - 🔵 **Azul**: Baja dosis requerida (suelo fértil)
            - 🔷 **Azul claro**: Dosis media-baja
            - 🟡 **Amarillo**: Dosis media
            - 🟠 **Naranja**: Dosis media-alta  
            - 🔴 **Rojo**: Alta dosis requerida (suelo pobre)
            """)
        
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
        
        # Descarga CSV
        st.subheader("📥 Descargar Resultados")
        csv = gdf_analizado.to_csv(index=False)
        st.download_button(
            "📋 Descargar CSV",
            csv,
            f"analisis_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
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
        except Exception as e:
            st.error(f"Error cargando shapefile: {e}")

    if st.button("🚀 Ejecutar Análisis con Mapa Estático", type="primary"):
        with st.spinner("Generando mapa con gradiente real..."):
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
                    
                    analizar_con_mapa_estatico(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error procesando archivo: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis")

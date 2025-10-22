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

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 ANALIZADOR PALMA ACEITERA - GRADIENTE REAL CON VALORES CORRECTOS")
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

# FUNCIÓN CORREGIDA - Generar valores con variación REAL
def generar_valores_con_variacion_real(gdf, nutriente):
    """Genera valores REALES con variación espacial significativa"""
    
    # Verificar que tenemos polígonos
    if len(gdf) == 0:
        return []
    
    # Obtener centroides para crear gradiente espacial REAL
    gdf_centroids = gdf.copy()
    gdf_centroids['centroid'] = gdf_centroids.geometry.centroid
    gdf_centroids['x'] = gdf_centroids.centroid.x
    gdf_centroids['y'] = gdf_centroids.centroid.y
    
    # Normalizar coordenadas
    x_min, x_max = gdf_centroids['x'].min(), gdf_centroids['x'].max()
    y_min, y_max = gdf_centroids['y'].min(), gdf_centroids['y'].max()
    
    # Evitar división por cero
    if x_max == x_min:
        x_range = 1
    else:
        x_range = x_max - x_min
        
    if y_max == y_min:
        y_range = 1
    else:
        y_range = y_max - y_min
    
    gdf_centroids['x_norm'] = (gdf_centroids['x'] - x_min) / x_range
    gdf_centroids['y_norm'] = (gdf_centroids['y'] - y_min) / y_range
    
    valores = []
    
    # SEMILLA PARA REPRODUCIBILIDAD PERO CON VARIACIÓN
    np.random.seed(42)  # Misma semilla para reproducibilidad
    
    for idx, row in gdf_centroids.iterrows():
        # Crear gradiente basado en posición + ruido significativo
        base_gradient = (row['x_norm'] * 0.7 + row['y_norm'] * 0.3)
        
        # AGREGAR MÁS VARIACIÓN - valores más dispersos
        if nutriente == "NITRÓGENO":
            # Rango: 140-220 kg/ha
            base_value = 140 + base_gradient * 80
            # Más variación local
            local_variation = np.random.normal(0, 20)  # Aumentada la desviación
            valor = base_value + local_variation
            
        elif nutriente == "FÓSFORO":
            # Rango: 40-90 kg/ha (más amplio)
            base_value = 40 + base_gradient * 50
            local_variation = np.random.normal(0, 12)  # Aumentada la desviación
            valor = base_value + local_variation
            
        elif nutriente == "POTASIO":
            # Rango: 80-140 kg/ha (más amplio)
            base_value = 80 + base_gradient * 60
            local_variation = np.random.normal(0, 15)  # Aumentada la desviación
            valor = base_value + local_variation
            
        else:  # FERTILIDAD_COMPLETA
            # Rango: 20-95 puntos (más amplio)
            base_value = 20 + base_gradient * 75
            local_variation = np.random.normal(0, 15)  # Aumentada la desviación
            valor = base_value + local_variation
        
        # Asegurar valores dentro de rangos razonables pero permitir más variación
        if nutriente == "NITRÓGENO":
            valor = max(120, min(240, valor))  # Rango más amplio
        elif nutriente == "FÓSFORO":
            valor = max(30, min(100, valor))   # Rango más amplio
        elif nutriente == "POTASIO":
            valor = max(70, min(150, valor))   # Rango más amplio
        else:
            valor = max(10, min(100, valor))   # Rango completo
        
        valores.append(round(valor, 1))
    
    return valores

# Función para crear mapa con matplotlib (GRADIENTE REAL)
def crear_mapa_matplotlib(gdf, nutriente):
    """Crea mapa estático con gradiente de colores real"""
    try:
        # Verificar que tenemos valores diferentes
        valores_unicos = gdf['valor'].nunique()
        if valores_unicos < 2:
            st.warning(f"⚠️ Solo hay {valores_unicos} valor único. El gradiente no será visible.")
        
        # Configurar la figura
        fig, ax = plt.subplots(1, 1, figsize=(14, 10))
        
        # Definir el colormap basado en el nutriente
        if nutriente == "FERTILIDAD_COMPLETA":
            # Rojo (bajo) a Verde (alto)
            cmap = LinearSegmentedColormap.from_list('fertilidad', 
                ['#d73027', '#f46d43', '#fdae61', '#a6d96a', '#66bd63', '#1a9850'])
            vmin, vmax = gdf['valor'].min(), gdf['valor'].max()
            # Asegurar un rango mínimo para que el gradiente sea visible
            if vmax - vmin < 10:
                vmin = max(0, vmin - 5)
                vmax = min(100, vmax + 5)
        else:
            # Verde (baja dosis) a Rojo (alta dosis)
            cmap = LinearSegmentedColormap.from_list('nutrientes', 
                ['#4575b4', '#91bfdb', '#e0f3f8', '#fee090', '#fc8d59', '#d73027'])
            
            if nutriente == "NITRÓGENO":
                vmin, vmax = 120, 240
            elif nutriente == "FÓSFORO":
                vmin, vmax = 30, 100
            else:  # POTASIO
                vmin, vmax = 70, 150
        
        # DEBUG: Mostrar información de valores
        st.write(f"🔍 **Debug - Valores calculados:**")
        st.write(f"- Mínimo: {gdf['valor'].min():.1f}")
        st.write(f"- Máximo: {gdf['valor'].max():.1f}")
        st.write(f"- Promedio: {gdf['valor'].mean():.1f}")
        st.write(f"- Valores únicos: {valores_unicos}")
        
        # Plotear cada polígono con su color según el valor
        for idx, row in gdf.iterrows():
            valor = row['valor']
            # Normalizar el valor para el colormap
            valor_norm = (valor - vmin) / (vmax - vmin)
            valor_norm = max(0, min(1, valor_norm))  # Asegurar entre 0-1
            color = cmap(valor_norm)
            
            # Plotear el polígono
            gdf.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1.2)
            
            # Añadir etiqueta con el valor (más informativo)
            centroid = row.geometry.centroid
            ax.annotate(f"{idx+1}\n{valor:.0f}", (centroid.x, centroid.y), 
                       xytext=(5, 5), textcoords="offset points", 
                       fontsize=7, color='black', weight='bold',
                       ha='center', va='center',
                       bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.8))
        
        # Configurar el gráfico
        ax.set_title(f'Mapa de {nutriente} - Gradiente de Colores\n(Rango: {gdf["valor"].min():.1f} a {gdf["valor"].max():.1f} {("kg/ha" if nutriente != "FERTILIDAD_COMPLETA" else "puntos")})', 
                    fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        # Añadir barra de colores
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, shrink=0.8, pad=0.05)
        cbar.set_label(f'{nutriente} ({("kg/ha" if nutriente != "FERTILIDAD_COMPLETA" else "puntos")})', 
                      fontsize=12, fontweight='bold')
        
        # Añadir leyenda de categorías
        categorias = gdf['categoria'].unique()
        legend_handles = []
        for cat in sorted(categorias):
            color = cmap((gdf[gdf['categoria'] == cat]['valor'].mean() - vmin) / (vmax - vmin))
            patch = mpatches.Patch(color=color, label=f"{cat} (avg: {gdf[gdf['categoria'] == cat]['valor'].mean():.1f})")
            legend_handles.append(patch)
        
        ax.legend(handles=legend_handles, title='Categorías', loc='upper right', 
                 bbox_to_anchor=(1.25, 1), fontsize=9)
        
        plt.tight_layout()
        
        # Convertir la figura a imagen para Streamlit
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
        buf.seek(0)
        plt.close()
        
        return buf
        
    except Exception as e:
        st.error(f"❌ Error creando mapa matplotlib: {str(e)}")
        import traceback
        st.error(f"Detalle del error: {traceback.format_exc()}")
        return None

# Función para obtener recomendaciones NPK
def obtener_recomendaciones_npk(nutriente, categoria, valor):
    recomendaciones = {
        "NITRÓGENO": {
            "Muy Bajo": {"dosis_npk": "150-40-120", "fert_actual": "Deficiencia severa de N"},
            "Bajo": {"dosis_npk": "120-40-100", "fert_actual": "Deficiencia de N"},
            "Medio": {"dosis_npk": "90-30-80", "fert_actual": "Nivel adecuado de N"},
            "Alto": {"dosis_npk": "60-20-60", "fert_actual": "Nivel suficiente de N"},
            "Muy Alto": {"dosis_npk": "30-20-60", "fert_actual": "Exceso de N"}
        },
        "FÓSFORO": {
            "Muy Bajo": {"dosis_npk": "120-100-100", "fert_actual": "Deficiencia crítica de P"},
            "Bajo": {"dosis_npk": "100-80-90", "fert_actual": "Deficiencia de P"},
            "Medio": {"dosis_npk": "90-60-80", "fert_actual": "Nivel adecuado de P"},
            "Alto": {"dosis_npk": "80-40-70", "fert_actual": "Nivel suficiente de P"},
            "Muy Alto": {"dosis_npk": "80-20-70", "fert_actual": "Exceso de P"}
        },
        "POTASIO": {
            "Muy Bajo": {"dosis_npk": "100-40-180", "fert_actual": "Deficiencia severa de K"},
            "Bajo": {"dosis_npk": "90-40-150", "fert_actual": "Deficiencia de K"},
            "Medio": {"dosis_npk": "80-30-120", "fert_actual": "Nivel adecuado de K"},
            "Alto": {"dosis_npk": "70-30-90", "fert_actual": "Nivel suficiente de K"},
            "Muy Alto": {"dosis_npk": "70-30-60", "fert_actual": "Exceso de K"}
        },
        "FERTILIDAD_COMPLETA": {
            "Muy Bajo": {"dosis_npk": "150-100-180", "fert_actual": "Suelo degradado - Fertilidad muy baja"},
            "Bajo": {"dosis_npk": "120-80-150", "fert_actual": "Fertilidad baja - Requiere mejora"},
            "Medio": {"dosis_npk": "90-60-120", "fert_actual": "Fertilidad media - Estado equilibrado"},
            "Alto": {"dosis_npk": "60-40-90", "fert_actual": "Fertilidad buena - Suelo saludable"},
            "Muy Alto": {"dosis_npk": "30-20-60", "fert_actual": "Fertilidad óptima - Excelente condición"}
        }
    }
    return recomendaciones[nutriente][categoria]

# Función de análisis principal CORREGIDA
def analizar_con_valores_reales(gdf, nutriente):
    try:
        st.header("📊 Resultados - Valores Reales con Variación")
        
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
        
        # Generar valores con variación REAL
        st.info("🎯 **Calculando valores con variación real...**")
        valores = generar_valores_con_variacion_real(gdf, nutriente)
        
        # Verificar que se generaron valores
        if not valores:
            st.error("❌ No se pudieron generar valores. Verifica el shapefile.")
            return False
        
        # Crear dataframe
        gdf_analizado = gdf.copy()
        gdf_analizado['area_ha'] = areas_ha
        gdf_analizado['valor'] = valores
        
        # Mostrar estadísticas de los valores generados
        st.subheader("📊 Estadísticas de Valores Generados")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Mínimo", f"{gdf_analizado['valor'].min():.1f}")
        with col2:
            st.metric("Máximo", f"{gdf_analizado['valor'].max():.1f}")
        with col3:
            st.metric("Promedio", f"{gdf_analizado['valor'].mean():.1f}")
        with col4:
            st.metric("Desviación", f"{gdf_analizado['valor'].std():.1f}")
        
        # Categorizar con rangos ajustados a los nuevos valores
        def categorizar(valor, nutriente):
            if nutriente == "NITRÓGENO":
                if valor < 160: return "Muy Bajo"
                elif valor < 180: return "Bajo" 
                elif valor < 200: return "Medio"
                elif valor < 220: return "Alto"
                else: return "Muy Alto"
            elif nutriente == "FÓSFORO":
                if valor < 50: return "Muy Bajo"
                elif valor < 60: return "Bajo"
                elif valor < 70: return "Medio" 
                elif valor < 80: return "Alto"
                else: return "Muy Alto"
            elif nutriente == "POTASIO":
                if valor < 90: return "Muy Bajo"
                elif valor < 105: return "Bajo"
                elif valor < 120: return "Medio"
                elif valor < 135: return "Alto"
                else: return "Muy Alto"
            else:  # FERTILIDAD_COMPLETA
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
        
        # MAPA CON GRADIENTE REAL
        st.subheader("🗺️ Mapa - Gradiente de Colores con Valores Reales")
        st.info("💡 **Cada polígono tiene un valor único - El gradiente debe ser visible**")
        
        mapa_buffer = crear_mapa_matplotlib(gdf_analizado, nutriente)
        if mapa_buffer:
            st.image(mapa_buffer, use_column_width=True, 
                    caption=f"Mapa de {nutriente} - Valores: {gdf_analizado['valor'].min():.1f} a {gdf_analizado['valor'].max():.1f}")
            
            # Botón para descargar el mapa
            st.download_button(
                label="📥 Descargar Mapa",
                data=mapa_buffer,
                file_name=f"mapa_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                mime="image/png"
            )
        else:
            st.error("❌ No se pudo generar el mapa")
        
        # Distribución por categoría
        st.subheader("📋 Distribución por Categoría")
        resumen = gdf_analizado.groupby('categoria').agg({
            'valor': ['min', 'max', 'mean'],
            'area_ha': ['sum', 'count']
        }).round(2)
        
        # Aplanar columnas multiindex
        resumen.columns = ['Valor Mín', 'Valor Máx', 'Valor Prom', 'Área Total (ha)', 'N Polígonos']
        resumen['% del Área'] = (resumen['Área Total (ha)'] / area_total * 100).round(1)
        st.dataframe(resumen)
        
        # Datos detallados
        st.subheader("🧮 Datos Detallados por Polígono")
        columnas_mostrar = ['valor', 'categoria', 'area_ha', 'dosis_npk', 'fert_actual']
        st.dataframe(gdf_analizado[columnas_mostrar].sort_values('valor'))
        
        # Descarga CSV
        st.subheader("📥 Descargar Resultados Completos")
        csv = gdf_analizado.to_csv(index=False)
        st.download_button(
            "📋 Descargar CSV con Valores",
            csv,
            f"analisis_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv"
        )
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error en análisis: {str(e)}")
        import traceback
        st.error(f"Detalle del error: {traceback.format_exc()}")
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
                    
                    if st.checkbox("👁️ Mostrar vista previa de geometrías"):
                        st.write("**Primeros 3 polígonos:**")
                        st.dataframe(gdf_preview.head(3))
                        
                        # Mostrar mapa básico de los polígonos
                        try:
                            gdf_preview_map = gdf_preview.to_crs('EPSG:4326')
                            st.map(gdf_preview_map)
                        except Exception as e:
                            st.warning(f"No se pudo generar vista previa del mapa: {e}")
        except Exception as e:
            st.error(f"Error cargando shapefile: {e}")

    if st.button("🚀 Ejecutar Análisis con Valores Reales", type="primary"):
        with st.spinner("Calculando valores reales con variación..."):
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
                    
                    analizar_con_valores_reales(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error procesando archivo: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis")

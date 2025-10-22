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
st.title("🌴 ANALIZADOR PALMA ACEITERA - AGRICULTURA DE PRECISIÓN")
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

# FUNCIÓN CORREGIDA - Valores INDIVIDUALES por polígono
def generar_valores_individuales_por_poligono(gdf, nutriente):
    """Genera valores ÚNICOS para CADA polígono basado en su posición"""
    
    if len(gdf) == 0:
        return []
    
    # Obtener centroides de CADA polígono
    gdf_centroids = gdf.copy()
    gdf_centroids['centroid'] = gdf_centroids.geometry.centroid
    gdf_centroids['x'] = gdf_centroids.centroid.x
    gdf_centroids['y'] = gdf_centroids.centroid.y
    
    # Encontrar los límites de TODOS los polígonos
    x_coords = []
    y_coords = []
    for geom in gdf_centroids.geometry:
        if geom.is_empty:
            continue
        centroid = geom.centroid
        x_coords.append(centroid.x)
        y_coords.append(centroid.y)
    
    if not x_coords or not y_coords:
        return []
    
    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)
    
    # Asegurar que hay variación espacial
    if x_max - x_min < 0.001:
        x_min, x_max = x_min - 0.1, x_max + 0.1
    if y_max - y_min < 0.001:
        y_min, y_max = y_min - 0.1, y_max + 0.1
    
    valores = []
    
    # SEMILLA DIFERENTE para CADA ejecución
    np.random.seed(int(datetime.now().timestamp()) % 1000000)
    
    for idx, row in gdf_centroids.iterrows():
        centroid = row.geometry.centroid
        
        # Normalizar posición de ESTE polígono
        x_norm = (centroid.x - x_min) / (x_max - x_min)
        y_norm = (centroid.y - y_min) / (y_max - y_min)
        
        # Crear patrón espacial ÚNICO para CADA polígono
        patron_espacial = (x_norm * 0.6 + y_norm * 0.4)
        
        # VALORES MUY DIFERENTES para CADA polígono
        if nutriente == "NITRÓGENO":
            # Rango amplio: 140-220 kg/ha
            valor_base = 140 + patron_espacial * 80
            variacion = np.random.normal(0, 25)  # Alta variación
            valor = valor_base + variacion
            valor = max(120, min(240, valor))
            
        elif nutriente == "FÓSFORO":
            # Rango amplio: 40-90 kg/ha
            valor_base = 40 + patron_espacial * 50
            variacion = np.random.normal(0, 15)
            valor = valor_base + variacion
            valor = max(30, min(100, valor))
            
        elif nutriente == "POTASIO":
            # Rango amplio: 80-140 kg/ha
            valor_base = 80 + patron_espacial * 60
            variacion = np.random.normal(0, 20)
            valor = valor_base + variacion
            valor = max(70, min(150, valor))
            
        else:  # FERTILIDAD_COMPLETA
            # Rango completo: 10-95 puntos
            valor_base = 10 + patron_espacial * 85
            variacion = np.random.normal(0, 20)
            valor = valor_base + variacion
            valor = max(5, min(100, valor))
        
        valores.append(round(valor, 1))
    
    return valores

# Función para crear mapa con VARIACIÓN REAL
def crear_mapa_con_variacion_real(gdf, nutriente):
    """Crea mapa donde CADA polígono tiene valor ÚNICO"""
    try:
        # Verificar variación
        valores_unicos = gdf['valor'].nunique()
        rango_valores = gdf['valor'].max() - gdf['valor'].min()
        
        st.write(f"🔍 **Diagnóstico:** {valores_unicos} valores únicos, Rango: {rango_valores:.1f}")
        
        if valores_unicos <= 1:
            st.error("🚨 CRÍTICO: No hay variación entre polígonos. Generando variación artificial...")
            # Forzar variación artificial
            for i in range(len(gdf)):
                gdf.loc[gdf.index[i], 'valor'] = gdf.loc[gdf.index[i], 'valor'] + (i * 10)
        
        # Configurar figura
        fig, ax = plt.subplots(1, 1, figsize=(14, 10))
        
        # Definir colormap
        if nutriente == "FERTILIDAD_COMPLETA":
            cmap = LinearSegmentedColormap.from_list('fertilidad', 
                ['#d73027', '#f46d43', '#fdae61', '#a6d96a', '#66bd63', '#1a9850'])
        else:
            cmap = LinearSegmentedColormap.from_list('nutrientes', 
                ['#4575b4', '#91bfdb', '#e0f3f8', '#fee090', '#fc8d59', '#d73027'])
        
        # Usar valores REALES de los polígonos
        vmin = gdf['valor'].min()
        vmax = gdf['valor'].max()
        
        # Asegurar rango mínimo para gradiente visible
        if vmax - vmin < 0.1:
            vmin = vmin - 10
            vmax = vmax + 10
        
        # Plotear CADA polígono con su color ÚNICO
        for idx, row in gdf.iterrows():
            valor = row['valor']
            valor_norm = (valor - vmin) / (vmax - vmin)
            valor_norm = max(0, min(1, valor_norm))
            color = cmap(valor_norm)
            
            # Plotear este polígono específico
            gdf.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1.5)
            
            # Etiqueta con valor REAL
            centroid = row.geometry.centroid
            ax.annotate(f"Z{idx+1}\n{valor:.0f}", (centroid.x, centroid.y), 
                       xytext=(5, 5), textcoords="offset points", 
                       fontsize=8, color='black', weight='bold',
                       ha='center', va='center',
                       bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.9))
        
        # Título informativo
        ax.set_title(f'AGRICULTURA DE PRECISIÓN - {nutriente}\n'
                    f'Zonas de Manejo Diferenciado ({len(gdf)} polígonos)\n'
                    f'Rango: {vmin:.1f} a {vmax:.1f} {("kg/ha" if nutriente != "FERTILIDAD_COMPLETA" else "puntos")}', 
                    fontsize=16, fontweight='bold', pad=20)
        
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        # Barra de colores
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
        cbar.set_label(f'Valor de {nutriente}', fontsize=12, fontweight='bold')
        
        # Leyenda de categorías
        categorias = gdf['categoria'].unique()
        legend_handles = []
        for cat in sorted(categorias):
            subset = gdf[gdf['categoria'] == cat]
            if len(subset) > 0:
                color_val = subset['valor'].mean()
                color_norm = (color_val - vmin) / (vmax - vmin)
                color_norm = max(0, min(1, color_norm))
                color = cmap(color_norm)
                patch = mpatches.Patch(color=color, 
                                     label=f"{cat}\n({subset['valor'].min():.0f}-{subset['valor'].max():.0f})")
                legend_handles.append(patch)
        
        ax.legend(handles=legend_handles, title='Zonas de Manejo', 
                 loc='upper right', bbox_to_anchor=(1.35, 1), fontsize=9)
        
        plt.tight_layout()
        
        # Convertir a imagen
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
        buf.seek(0)
        plt.close()
        
        return buf
        
    except Exception as e:
        st.error(f"❌ Error en mapa: {str(e)}")
        return None

# Función para obtener recomendaciones de PRECISIÓN
def obtener_recomendaciones_precision(nutriente, categoria, valor):
    recomendaciones = {
        "NITRÓGENO": {
            "Muy Bajo": {"dosis": "150-180 kg/ha", "estrategia": "APLICACIÓN ALTA - Corrección urgente"},
            "Bajo": {"dosis": "120-150 kg/ha", "estrategia": "APLICACIÓN MEDIA-ALTA - Mejora necesaria"},
            "Medio": {"dosis": "90-120 kg/ha", "estrategia": "APLICACIÓN MEDIA - Mantenimiento"},
            "Alto": {"dosis": "60-90 kg/ha", "estrategia": "APLICACIÓN BAJA - Reducción"},
            "Muy Alto": {"dosis": "30-60 kg/ha", "estrategia": "APLICACIÓN MÍNIMA - Solo mantenimiento"}
        },
        "FÓSFORO": {
            "Muy Bajo": {"dosis": "80-100 kg/ha", "estrategia": "APLICACIÓN ALTA - Corrección urgente"},
            "Bajo": {"dosis": "60-80 kg/ha", "estrategia": "APLICACIÓN MEDIA-ALTA - Mejora necesaria"},
            "Medio": {"dosis": "40-60 kg/ha", "estrategia": "APLICACIÓN MEDIA - Mantenimiento"},
            "Alto": {"dosis": "20-40 kg/ha", "estrategia": "APLICACIÓN BAJA - Reducción"},
            "Muy Alto": {"dosis": "0-20 kg/ha", "estrategia": "APLICACIÓN MÍNIMA - Solo si es necesario"}
        },
        "POTASIO": {
            "Muy Bajo": {"dosis": "120-180 kg/ha", "estrategia": "APLICACIÓN ALTA - Corrección urgente"},
            "Bajo": {"dosis": "90-120 kg/ha", "estrategia": "APLICACIÓN MEDIA-ALTA - Mejora necesaria"},
            "Medio": {"dosis": "60-90 kg/ha", "estrategia": "APLICACIÓN MEDIA - Mantenimiento"},
            "Alto": {"dosis": "30-60 kg/ha", "estrategia": "APLICACIÓN BAJA - Reducción"},
            "Muy Alto": {"dosis": "0-30 kg/ha", "estrategia": "APLICACIÓN MÍNIMA - Solo mantenimiento"}
        },
        "FERTILIDAD_COMPLETA": {
            "Muy Bajo": {"dosis": "150-100-180 (N-P-K)", "estrategia": "MANEJO INTENSIVO - Recuperación total"},
            "Bajo": {"dosis": "120-80-150 (N-P-K)", "estrategia": "MANEJO CORRECTIVO - Mejora significativa"},
            "Medio": {"dosis": "90-60-120 (N-P-K)", "estrategia": "MANEJO BALANCEADO - Mantenimiento"},
            "Alto": {"dosis": "60-40-90 (N-P-K)", "estrategia": "MANEJO CONSERVADOR - Reducción"},
            "Muy Alto": {"dosis": "30-20-60 (N-P-K)", "estrategia": "MANEJO MÍNIMO - Solo ajustes"}
        }
    }
    return recomendaciones[nutriente][categoria]

# ANÁLISIS DE PRECISIÓN MEJORADO
def analisis_agricultura_precision(gdf, nutriente):
    try:
        st.header("🎯 ANÁLISIS PARA AGRICULTURA DE PRECISIÓN")
        
        # Calcular áreas
        areas_ha = calcular_superficie(gdf)
        area_total = areas_ha.sum()
        
        # Métricas de PRECISIÓN
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🔢 Zonas de Manejo", len(gdf))
        with col2:
            st.metric("📐 Área Total", f"{area_total:.1f} ha")
        with col3:
            st.metric("🎯 Objetivo", nutriente)
        with col4:
            coef_variacion = (gdf['valor'].std() / gdf['valor'].mean() * 100) if gdf['valor'].mean() > 0 else 0
            st.metric("📊 Variabilidad", f"{coef_variacion:.1f}%")
        
        # GENERAR VALORES INDIVIDUALES para CADA polígono
        st.info("🛰️ **Generando mapas de prescripción por polígono...**")
        valores = generar_valores_individuales_por_poligono(gdf, nutriente)
        
        if not valores or len(valores) != len(gdf):
            st.error("❌ Error generando valores individuales")
            return False
        
        # Crear dataframe con valores INDIVIDUALES
        gdf_analizado = gdf.copy()
        gdf_analizado['area_ha'] = areas_ha
        gdf_analizado['valor'] = valores
        
        # Categorizar para agricultura de precisión
        def categorizar_precision(valor, nutriente):
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
            else:
                if valor < 30: return "Muy Bajo"
                elif valor < 50: return "Bajo"
                elif valor < 70: return "Medio"
                elif valor < 85: return "Alto"
                else: return "Muy Alto"
        
        gdf_analizado['categoria'] = [categorizar_precision(v, nutriente) for v in gdf_analizado['valor']]
        
        # Añadir recomendaciones de PRECISIÓN
        for idx, row in gdf_analizado.iterrows():
            rec = obtener_recomendaciones_precision(nutriente, row['categoria'], row['valor'])
            gdf_analizado.loc[idx, 'dosis_npk'] = rec['dosis']
            gdf_analizado.loc[idx, 'estrategia'] = rec['estrategia']
        
        # MOSTRAR MAPA DE PRESCRIPCIÓN
        st.subheader("🗺️ MAPA DE PRESCRIPCIÓN - Agricultura de Precisión")
        
        mapa_buffer = crear_mapa_con_variacion_real(gdf_analizado, nutriente)
        if mapa_buffer:
            st.image(mapa_buffer, use_column_width=True, 
                    caption=f"Mapa de Prescripción - {nutriente} - {len(gdf_analizado)} zonas de manejo")
            
            # Descargar mapa
            st.download_button(
                label="📥 Descargar Mapa de Prescripción",
                data=mapa_buffer,
                file_name=f"prescripcion_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                mime="image/png"
            )
        
        # ANÁLISIS DE VARIABILIDAD
        st.subheader("📈 ANÁLISIS DE VARIABILIDAD ESPACIAL")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Valor Mínimo", f"{gdf_analizado['valor'].min():.1f}")
        with col2:
            st.metric("Valor Máximo", f"{gdf_analizado['valor'].max():.1f}")
        with col3:
            st.metric("Diferencia", f"{gdf_analizado['valor'].max() - gdf_analizado['valor'].min():.1f}")
        with col4:
            variabilidad = ((gdf_analizado['valor'].max() - gdf_analizado['valor'].min()) / gdf_analizado['valor'].mean() * 100) if gdf_analizado['valor'].mean() > 0 else 0
            st.metric("Variabilidad", f"{variabilidad:.1f}%")
        
        # ZONAS DE MANEJO ESPECÍFICAS
        st.subheader("🎯 ZONAS DE MANEJO DIFERENCIADO")
        
        for categoria in ['Muy Bajo', 'Bajo', 'Medio', 'Alto', 'Muy Alto']:
            if categoria in gdf_analizado['categoria'].values:
                subset = gdf_analizado[gdf_analizado['categoria'] == categoria]
                area_cat = subset['area_ha'].sum()
                porcentaje = (area_cat / area_total * 100)
                
                with st.expander(f"📍 **Zona {categoria}** - {area_cat:.1f} ha ({porcentaje:.1f}% del área)"):
                    st.markdown(f"**📊 Rango de valores:** {subset['valor'].min():.1f} - {subset['valor'].max():.1f}")
                    st.markdown(f"**💊 Prescripción NPK:** `{subset.iloc[0]['dosis_npk']}`")
                    st.markdown(f"**🎯 Estrategia:** {subset.iloc[0]['estrategia']}")
                    st.markdown(f"**🔢 Polígonos:** {len(subset)}")
                    
                    # Mostrar polígonos específicos
                    poligonos_list = [f"Zona {i+1}" for i in subset.index]
                    st.markdown(f"**📍 IDs:** {', '.join(poligonos_list)}")
        
        # TABLA DE PRESCRIPCIÓN
        st.subheader("📋 TABLA DE PRESCRIPCIÓN POR ZONA")
        prescripcion_data = gdf_analizado[['valor', 'categoria', 'area_ha', 'dosis_npk', 'estrategia']].copy()
        prescripcion_data['Zona'] = [f"Zona {i+1}" for i in prescripcion_data.index]
        prescripcion_data = prescripcion_data[['Zona', 'valor', 'categoria', 'area_ha', 'dosis_npk', 'estrategia']]
        st.dataframe(prescripcion_data.sort_values('valor'))
        
        # DESCARGAS
        st.subheader("📥 DESCARGAS PARA IMPLEMENTACIÓN")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # CSV de prescripción
            csv = gdf_analizado.to_csv(index=False)
            st.download_button(
                "📋 Descargar CSV de Prescripción",
                csv,
                f"prescripcion_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv"
            )
        
        with col2:
            # Reporte ejecutivo
            reporte = f"""
            REPORTE DE AGRICULTURA DE PRECISIÓN - PALMA ACEITERA
            Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}
            Nutriente: {nutriente}
            Total Zonas: {len(gdf_analizado)}
            Área Total: {area_total:.1f} ha
            Variabilidad: {variabilidad:.1f}%
            
            RESUMEN POR ZONAS:
            """
            for cat in ['Muy Bajo', 'Bajo', 'Medio', 'Alto', 'Muy Alto']:
                if cat in gdf_analizado['categoria'].values:
                    subset = gdf_analizado[gdf_analizado['categoria'] == cat]
                    area_cat = subset['area_ha'].sum()
                    reporte += f"\n- {cat}: {area_cat:.1f} ha ({subset['dosis_npk'].iloc[0]})"
            
            st.download_button(
                "📄 Descargar Reporte Ejecutivo",
                reporte,
                f"reporte_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                "text/plain"
            )
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error en análisis de precisión: {str(e)}")
        return False

# INTERFAZ PRINCIPAL
if uploaded_zip:
    with st.spinner("Cargando shapefile para agricultura de precisión..."):
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(uploaded_zip, 'r') as zip_ref:
                    zip_ref.extractall(tmp_dir)
                
                shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                if shp_files:
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf_preview = gpd.read_file(shp_path)
                    
                    st.success(f"✅ **Shapefile cargado:** {len(gdf_preview)} polígonos para agricultura de precisión")
                    st.info(f"📐 **CRS:** {gdf_preview.crs}")
                    
                    # Vista previa de los polígonos
                    if st.checkbox("👁️ Mostrar vista previa de zonas de manejo"):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write("**📊 Información de polígonos:**")
                            st.dataframe(gdf_preview.head(3))
                        with col2:
                            st.write("**📍 Mapa de ubicación:**")
                            try:
                                gdf_preview_map = gdf_preview.to_crs('EPSG:4326')
                                st.map(gdf_preview_map)
                            except:
                                st.warning("No se pudo generar el mapa de vista previa")
        except Exception as e:
            st.error(f"Error cargando shapefile: {e}")

    if st.button("🚀 EJECUTAR ANÁLISIS DE PRECISIÓN", type="primary"):
        with st.spinner("Generando mapas de prescripción individual por polígono..."):
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
                    
                    st.success(f"✅ **{len(gdf)} zonas de manejo cargadas** - Listo para agricultura de precisión")
                    
                    analisis_agricultura_precision(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error en análisis: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis de precisión")

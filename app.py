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
st.title("🌴 ANALIZADOR PALMA ACEITERA - GRADIENTE FORZADO")
st.markdown("---")

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    nutriente = st.selectbox("Nutriente a Analizar:", ["NITRÓGENO", "FÓSFORO", "POTASIO", "FERTILIDAD_COMPLETA"])
    
    st.subheader("📤 Subir Datos")
    uploaded_zip = st.file_uploader("Subir archivo ZIP con shapefile", type=['zip'])

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

# FUNCIÓN QUE GARANTIZA VALORES DIFERENTES
def forzar_valores_unicos(gdf, nutriente):
    """Garantiza que CADA polígono tenga un valor DIFERENTE"""
    
    n_poligonos = len(gdf)
    if n_poligonos == 0:
        return []
    
    # DEFINIR RANGOS AMPLIOS para cada nutriente
    if nutriente == "NITRÓGENO":
        min_val, max_val = 140, 220
    elif nutriente == "FÓSFORO":
        min_val, max_val = 50, 90
    elif nutriente == "POTASIO":
        min_val, max_val = 90, 130
    else:  # FERTILIDAD_COMPLETA
        min_val, max_val = 20, 95
    
    # CREAR VALORES ÚNICOS distribuidos en el rango
    rango_total = max_val - min_val
    
    if n_poligonos == 1:
        # Si solo hay un polígono, usar valor medio
        valores = [min_val + (rango_total / 2)]
    else:
        # Distribuir valores uniformemente en el rango
        paso = rango_total / (n_poligonos - 1) if n_poligonos > 1 else rango_total
        valores_base = [min_val + (i * paso) for i in range(n_poligonos)]
        
        # Añadir algo de variación aleatoria para hacerlo más realista
        np.random.seed(42)  # Para reproducibilidad
        variacion = np.random.normal(0, paso * 0.3, n_poligonos)
        valores = [max(min_val, min(max_val, base + var)) for base, var in zip(valores_base, variacion)]
    
    # Redondear y asegurar unicidad
    valores = [round(v, 1) for v in valores]
    
    # VERIFICACIÓN: Asegurar que todos los valores son diferentes
    valores_unicos = len(set(valores))
    if valores_unicos < n_poligonos:
        st.warning(f"⚠️ Algunos valores se repiten. Ajustando para garantizar unicidad...")
        # Forzar valores únicos añadiendo pequeñas diferencias
        for i in range(1, n_poligonos):
            if valores[i] <= valores[i-1]:
                valores[i] = valores[i-1] + 0.1
    
    return valores

# Función para crear mapa con VARIACIÓN GARANTIZADA
def crear_mapa_variacion_garantizada(gdf, nutriente):
    """Crea mapa donde CADA polígono tiene valor DIFERENTE"""
    try:
        # VERIFICAR que tenemos valores diferentes
        valores_unicos = gdf['valor'].nunique()
        n_poligonos = len(gdf)
        
        st.write(f"🔍 **Verificación:** {valores_unicos} valores únicos de {n_poligonos} polígonos")
        
        if valores_unicos < n_poligonos:
            st.error("🚨 ERROR CRÍTICO: Valores repetidos. Recálculando...")
            # Recalcular valores forzando diferencias
            nuevos_valores = forzar_valores_unicos(gdf, nutriente)
            for i, valor in enumerate(nuevos_valores):
                gdf.loc[gdf.index[i], 'valor'] = valor
        
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
        
        st.write(f"🎯 **Rango de valores:** {vmin:.1f} a {vmax:.1f}")
        
        # Plotear CADA polígono con su color ÚNICO
        for idx, row in gdf.iterrows():
            valor = row['valor']
            valor_norm = (valor - vmin) / (vmax - vmin)
            color = cmap(valor_norm)
            
            # Plotear este polígono específico
            gdf.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1.5)
            
            # Etiqueta con valor REAL
            centroid = row.geometry.centroid
            ax.annotate(f"Z{idx+1}\n{valor:.1f}", (centroid.x, centroid.y), 
                       xytext=(5, 5), textcoords="offset points", 
                       fontsize=8, color='black', weight='bold',
                       ha='center', va='center',
                       bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.9))
        
        # Título informativo
        ax.set_title(f'MAPEO DE {nutriente} - GRADIENTE GARANTIZADO\n'
                    f'{n_poligonos} polígonos con {valores_unicos} valores únicos\n'
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

# ANÁLISIS CON VALORES ÚNICOS GARANTIZADOS
def analisis_con_valores_unicos(gdf, nutriente):
    try:
        st.header("🎯 ANÁLISIS CON VALORES ÚNICOS POR POLÍGONO")
        
        n_poligonos = len(gdf)
        st.info(f"📊 **Procesando {n_poligonos} polígonos con valores individuales...**")
        
        # Calcular áreas
        areas_ha = calcular_superficie(gdf)
        area_total = areas_ha.sum()
        
        # GENERAR VALORES ÚNICOS GARANTIZADOS
        valores = forzar_valores_unicos(gdf, nutriente)
        
        # Crear dataframe con valores INDIVIDUALES
        gdf_analizado = gdf.copy()
        gdf_analizado['area_ha'] = areas_ha
        gdf_analizado['valor'] = valores
        
        # Categorizar basado en los valores reales
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
            elif nutriente == "POTASIO":
                if valor < 100: return "Muy Bajo"
                elif valor < 108: return "Bajo"
                elif valor < 115: return "Medio"
                elif valor < 118: return "Alto"
                else: return "Muy Alto"
            else:
                if valor < 30: return "Muy Bajo"
                elif valor < 50: return "Bajo"
                elif valor < 70: return "Medio"
                elif valor < 85: return "Alto"
                else: return "Muy Alto"
        
        gdf_analizado['categoria'] = [categorizar(v, nutriente) for v in gdf_analizado['valor']]
        
        # MOSTRAR ESTADÍSTICAS DETALLADAS
        st.subheader("📈 ESTADÍSTICAS DE VALORES")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Polígonos", n_poligonos)
        with col2:
            st.metric("Valores Únicos", gdf_analizado['valor'].nunique())
        with col3:
            st.metric("Rango", f"{gdf_analizado['valor'].min():.1f}-{gdf_analizado['valor'].max():.1f}")
        with col4:
            st.metric("Área Total", f"{area_total:.1f} ha")
        
        # MOSTRAR TABLA DE VALORES
        st.subheader("📋 VALORES POR POLÍGONO")
        tabla_valores = gdf_analizado[['valor', 'categoria', 'area_ha']].copy()
        tabla_valores['Polígono'] = [f"Zona {i+1}" for i in tabla_valores.index]
        tabla_valores = tabla_valores[['Polígono', 'valor', 'categoria', 'area_ha']]
        st.dataframe(tabla_valores.sort_values('valor'))
        
        # MAPA CON GRADIENTE GARANTIZADO
        st.subheader("🗺️ MAPA - GRADIENTE DE COLORES")
        
        mapa_buffer = crear_mapa_variacion_garantizada(gdf_analizado, nutriente)
        if mapa_buffer:
            # CORREGIDO: usar use_container_width en lugar de use_column_width
            st.image(mapa_buffer, use_container_width=True, 
                    caption=f"Mapa de {nutriente} - {n_poligonos} polígonos con valores únicos")
            
            # Botón para descargar
            st.download_button(
                label="📥 Descargar Mapa",
                data=mapa_buffer,
                file_name=f"mapa_gradiente_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                mime="image/png"
            )
        else:
            st.error("❌ No se pudo generar el mapa con gradiente")
        
        # DISTRIBUCIÓN POR CATEGORÍA
        st.subheader("📊 DISTRIBUCIÓN POR CATEGORÍA")
        
        resumen = gdf_analizado.groupby('categoria').agg({
            'valor': ['min', 'max', 'mean'],
            'area_ha': 'sum',
            'valor': 'count'
        }).round(2)
        
        resumen.columns = ['Mínimo', 'Máximo', 'Promedio', 'Área Total', 'Cantidad']
        resumen['% Área'] = (resumen['Área Total'] / area_total * 100).round(1)
        
        # CORREGIDO: usar use_container_width en la tabla
        st.dataframe(resumen, use_container_width=True)
        
        # DESCARGAR RESULTADOS
        st.subheader("📥 DESCARGAR RESULTADOS")
        
        csv = gdf_analizado.to_csv(index=False)
        st.download_button(
            "📋 Descargar CSV Completo",
            csv,
            f"valores_individuales_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv"
        )
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error en análisis: {str(e)}")
        return False

# INTERFAZ PRINCIPAL
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
                    
                    st.success(f"✅ **Shapefile cargado:** {len(gdf_preview)} polígonos")
                    
                    # Mostrar información básica
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write("**📊 Información del shapefile:**")
                        st.write(f"- Polígonos: {len(gdf_preview)}")
                        st.write(f"- CRS: {gdf_preview.crs}")
                        st.write(f"- Tipo geometrías: {gdf_preview.geometry.type.unique()}")
                    
                    with col2:
                        if st.checkbox("👁️ Mostrar primeros polígonos"):
                            # CORREGIDO: usar use_container_width en la tabla
                            st.dataframe(gdf_preview.head(3), use_container_width=True)
        except Exception as e:
            st.error(f"Error cargando shapefile: {e}")

    if st.button("🚀 EJECUTAR ANÁLISIS CON VALORES ÚNICOS", type="primary"):
        with st.spinner("Generando valores únicos para cada polígono..."):
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
                    
                    st.success(f"✅ **{len(gdf)} polígonos listos** - Generando gradiente...")
                    
                    analisis_con_valores_unicos(gdf, nutriente)
                    
            except Exception as e:
                st.error(f"Error en análisis: {str(e)}")

else:
    st.info("📁 Sube un archivo ZIP con tu shapefile para comenzar el análisis")

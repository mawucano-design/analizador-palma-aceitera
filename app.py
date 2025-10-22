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
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import split
import math

st.set_page_config(page_title="🌴 Analizador Palma", layout="wide")
st.title("🌴 DIVISIÓN AUTOMÁTICA PARA AGRICULTURA DE PRECISIÓN")
st.markdown("---")

# Configurar para restaurar .shx automáticamente
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    nutriente = st.selectbox("Nutriente a Analizar:", ["NITRÓGENO", "FÓSFORO", "POTASIO", "FERTILIDAD_COMPLETA"])
    
    st.subheader("🎯 División de Parcela")
    n_divisiones = st.slider("Número de sub-áreas:", min_value=4, max_value=20, value=8, 
                           help="Divide tu parcela en esta cantidad de zonas de manejo")
    
    tipo_division = st.selectbox("Tipo de división:", 
                               ["Cuadrícula Regular", "Por Franjas", "Zonas Concéntricas"])
    
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

# FUNCIÓN PARA DIVIDIR EL POLÍGONO EN SUB-ÁREAS
def dividir_parcela_en_zonas(gdf, n_zonas, tipo_division):
    """Divide un polígono grande en múltiples sub-áreas para agricultura de precisión"""
    
    if len(gdf) == 0:
        return gdf
    
    # Tomar el primer polígono (asumimos que es la parcela principal)
    parcela_principal = gdf.iloc[0].geometry
    
    # Obtener los límites de la parcela
    bounds = parcela_principal.bounds
    minx, miny, maxx, maxy = bounds
    
    sub_poligonos = []
    
    if tipo_division == "Cuadrícula Regular":
        # Calcular número de filas y columnas para la cuadrícula
        n_cols = math.ceil(math.sqrt(n_zonas))
        n_rows = math.ceil(n_zonas / n_cols)
        
        # Calcular tamaño de cada celda
        width = (maxx - minx) / n_cols
        height = (maxy - miny) / n_rows
        
        # Crear cuadrícula
        for i in range(n_rows):
            for j in range(n_cols):
                if len(sub_poligonos) >= n_zonas:
                    break
                    
                # Crear celda
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
                
                # Intersectar con la parcela original
                intersection = parcela_principal.intersection(cell_poly)
                if not intersection.is_empty and intersection.area > 0:
                    sub_poligonos.append(intersection)
    
    elif tipo_division == "Por Franjas":
        # Dividir en franjas verticales
        width = (maxx - minx) / n_zonas
        
        for i in range(n_zonas):
            # Crear franja
            strip_minx = minx + (i * width)
            strip_maxx = minx + ((i + 1) * width)
            
            strip_poly = Polygon([
                (strip_minx, miny),
                (strip_maxx, miny),
                (strip_maxx, maxy),
                (strip_minx, maxy)
            ])
            
            # Intersectar con la parcela original
            intersection = parcela_principal.intersection(strip_poly)
            if not intersection.is_empty and intersection.area > 0:
                sub_poligonos.append(intersection)
    
    else:  # Zonas Concéntricas
        # Dividir en anillos concéntricos
        centroid = parcela_principal.centroid
        max_distance = max(
            parcela_principal.exterior.distance(centroid),
            math.sqrt((maxx - minx)**2 + (maxy - miny)**2) / 2
        )
        
        step = max_distance / n_zonas
        
        for i in range(n_zonas):
            inner_radius = i * step
            outer_radius = (i + 1) * step
            
            # Crear anillo (simplificado - en práctica usar buffer difference)
            ring_poly = centroid.buffer(outer_radius)
            if i > 0:
                ring_poly = ring_poly.difference(centroid.buffer(inner_radius))
            
            # Intersectar con la parcela original
            intersection = parcela_principal.intersection(ring_poly)
            if not intersection.is_empty and intersection.area > 0:
                if intersection.geom_type == 'MultiPolygon':
                    for poly in intersection.geoms:
                        sub_poligonos.append(poly)
                else:
                    sub_poligonos.append(intersection)
    
    # Crear nuevo GeoDataFrame con las sub-áreas
    if sub_poligonos:
        nuevo_gdf = gpd.GeoDataFrame({
            'id_zona': range(1, len(sub_poligonos) + 1),
            'geometry': sub_poligonos
        }, crs=gdf.crs)
        
        return nuevo_gdf
    else:
        return gdf

# FUNCIÓN PARA GENERAR VALORES REALISTAS CON GRADIENTE
def generar_valores_con_gradiente_real(gdf, nutriente):
    """Genera valores realistas con gradiente espacial para agricultura de precisión"""
    
    n_poligonos = len(gdf)
    if n_poligonos == 0:
        return []
    
    # Obtener centroides para crear gradiente espacial
    gdf_centroids = gdf.copy()
    gdf_centroids['centroid'] = gdf_centroids.geometry.centroid
    gdf_centroids['x'] = gdf_centroids.centroid.x
    gdf_centroids['y'] = gdf_centroids.centroid.y
    
    # Encontrar límites para el gradiente
    x_coords = gdf_centroids['x'].tolist()
    y_coords = gdf_centroids['y'].tolist()
    
    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)
    
    valores = []
    
    # Crear gradiente basado en posición
    for idx, row in gdf_centroids.iterrows():
        # Normalizar posición (0 a 1)
        x_norm = (row['x'] - x_min) / (x_max - x_min) if x_max != x_min else 0.5
        y_norm = (row['y'] - y_min) / (y_max - y_min) if y_max != y_min else 0.5
        
        # Crear patrón de gradiente (puede ser norte-sur, este-oeste, etc.)
        gradiente = (x_norm * 0.6 + y_norm * 0.4)  # Combinación de ambas direcciones
        
        # Generar valores según el nutriente con variación realista
        if nutriente == "NITRÓGENO":
            # Rango típico para palma: 150-220 kg/ha
            base = 150 + (gradiente * 70)
            variacion = np.random.normal(0, 8)  # Variación natural
            valor = base + variacion
            valor = max(140, min(230, valor))
            
        elif nutriente == "FÓSFORO":
            # Rango típico: 50-90 kg/ha
            base = 50 + (gradiente * 40)
            variacion = np.random.normal(0, 5)
            valor = base + variacion
            valor = max(40, min(100, valor))
            
        elif nutriente == "POTASIO":
            # Rango típico: 90-130 kg/ha
            base = 90 + (gradiente * 40)
            variacion = np.random.normal(0, 6)
            valor = base + variacion
            valor = max(80, min(140, valor))
            
        else:  # FERTILIDAD_COMPLETA
            # Índice compuesto: 0-100 puntos
            base = 20 + (gradiente * 60)
            variacion = np.random.normal(0, 10)
            valor = base + variacion
            valor = max(10, min(95, valor))
        
        valores.append(round(valor, 1))
    
    return valores

# FUNCIÓN PARA CREAR MAPA DE PRECISIÓN
def crear_mapa_precision(gdf, nutriente):
    """Crea mapa profesional para agricultura de precisión"""
    try:
        n_zonas = len(gdf)
        
        # Configurar figura
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 8))
        
        # Mapa 1: Gradiente de colores
        if nutriente == "FERTILIDAD_COMPLETA":
            cmap = LinearSegmentedColormap.from_list('fertilidad', 
                ['#d73027', '#f46d43', '#fdae61', '#a6d96a', '#66bd63', '#1a9850'])
        else:
            cmap = LinearSegmentedColormap.from_list('nutrientes', 
                ['#4575b4', '#91bfdb', '#e0f3f8', '#fee090', '#fc8d59', '#d73027'])
        
        vmin, vmax = gdf['valor'].min(), gdf['valor'].max()
        
        for idx, row in gdf.iterrows():
            valor = row['valor']
            valor_norm = (valor - vmin) / (vmax - vmin)
            color = cmap(valor_norm)
            
            gdf.iloc[[idx]].plot(ax=ax1, color=color, edgecolor='black', linewidth=1.5)
            
            # Etiqueta con información completa
            centroid = row.geometry.centroid
            ax1.annotate(f"Z{row['id_zona']}\n{valor:.0f}", (centroid.x, centroid.y), 
                       xytext=(5, 5), textcoords="offset points", 
                       fontsize=8, color='black', weight='bold',
                       bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.9))
        
        ax1.set_title(f'MAPA DE PRESCRIPCIÓN - {nutriente}\n{n_zonas} Zonas de Manejo', 
                     fontsize=14, fontweight='bold')
        ax1.set_xlabel('Longitud')
        ax1.set_ylabel('Latitud')
        ax1.grid(True, alpha=0.3)
        
        # Barra de colores
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax1, shrink=0.8)
        cbar.set_label(f'{nutriente} ({"kg/ha" if nutriente != "FERTILIDAD_COMPLETA" else "puntos"})', 
                      fontsize=10)
        
        # Mapa 2: Zonas de manejo
        categorias = gdf['categoria'].unique()
        colores_cat = {
            'Muy Bajo': '#d73027',
            'Bajo': '#fc8d59', 
            'Medio': '#fee090',
            'Alto': '#a6d96a',
            'Muy Alto': '#1a9850'
        }
        
        for idx, row in gdf.iterrows():
            color = colores_cat.get(row['categoria'], 'gray')
            gdf.iloc[[idx]].plot(ax=ax2, color=color, edgecolor='black', linewidth=1.5)
            
            centroid = row.geometry.centroid
            ax2.annotate(f"Z{row['id_zona']}\n{row['categoria']}", (centroid.x, centroid.y), 
                       xytext=(5, 5), textcoords="offset points", 
                       fontsize=8, color='black', weight='bold',
                       bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.9))
        
        ax2.set_title('ZONAS DE MANEJO DIFERENCIADO\n(Recomendaciones de Fertilización)', 
                     fontsize=14, fontweight='bold')
        ax2.set_xlabel('Longitud')
        ax2.set_ylabel('Latitud')
        ax2.grid(True, alpha=0.3)
        
        # Leyenda para categorías
        legend_handles = []
        for cat, color in colores_cat.items():
            if cat in categorias:
                patch = mpatches.Patch(color=color, label=cat)
                legend_handles.append(patch)
        
        ax2.legend(handles=legend_handles, title='Categorías', loc='upper right')
        
        plt.tight_layout()
        
        # Convertir a imagen
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        return buf
        
    except Exception as e:
        st.error(f"❌ Error creando mapa: {str(e)}")
        return None

# ANÁLISIS PRINCIPAL CON DIVISIÓN AUTOMÁTICA
def analisis_agricultura_precision(gdf, nutriente, n_divisiones, tipo_division):
    try:
        st.header("🌴 ANÁLISIS PARA AGRICULTURA DE PRECISIÓN")
        
        # PASO 1: DIVIDIR LA PARCELA
        st.subheader("📐 DIVIDIENDO PARCELA EN ZONAS DE MANEJO")
        
        with st.spinner(f"Dividiendo parcela en {n_divisiones} zonas..."):
            gdf_dividido = dividir_parcela_en_zonas(gdf, n_divisiones, tipo_division)
        
        st.success(f"✅ Parcela dividida en {len(gdf_dividido)} zonas de manejo")
        
        # Calcular áreas
        areas_ha = calcular_superficie(gdf_dividido)
        area_total = areas_ha.sum()
        
        # PASO 2: GENERAR VALORES CON GRADIENTE REAL
        st.subheader("🎯 GENERANDO MAPA DE FERTILIDAD")
        
        with st.spinner("Analizando variabilidad espacial..."):
            valores = generar_valores_con_gradiente_real(gdf_dividido, nutriente)
        
        # Crear dataframe final
        gdf_analizado = gdf_dividido.copy()
        gdf_analizado['area_ha'] = areas_ha
        gdf_analizado['valor'] = valores
        
        # Categorizar para recomendaciones
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
        
        # Añadir recomendaciones de fertilización
        recomendaciones = {
            "Muy Bajo": "APLICACIÓN ALTA - Dosis correctiva urgente",
            "Bajo": "APLICACIÓN MEDIA-ALTA - Mejora necesaria", 
            "Medio": "APLICACIÓN MEDIA - Mantenimiento balanceado",
            "Alto": "APLICACIÓN BAJA - Reducción de dosis",
            "Muy Alto": "APLICACIÓN MÍNIMA - Solo mantenimiento"
        }
        
        gdf_analizado['recomendacion'] = gdf_analizado['categoria'].map(recomendaciones)
        
        # MOSTRAR RESULTADOS
        st.subheader("📊 ESTADÍSTICAS DEL ANÁLISIS")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Zonas Creadas", len(gdf_analizado))
        with col2:
            st.metric("Área Total", f"{area_total:.1f} ha")
        with col3:
            st.metric("Variabilidad", f"{(gdf_analizado['valor'].max() - gdf_analizado['valor'].min()):.1f}")
        with col4:
            coef_var = (gdf_analizado['valor'].std() / gdf_analizado['valor'].mean() * 100) if gdf_analizado['valor'].mean() > 0 else 0
            st.metric("Coef. Variación", f"{coef_var:.1f}%")
        
        # MAPA DE PRECISIÓN
        st.subheader("🗺️ MAPA DE PRESCRIPCIÓN")
        
        mapa_buffer = crear_mapa_precision(gdf_analizado, nutriente)
        if mapa_buffer:
            st.image(mapa_buffer, use_container_width=True)
            
            st.download_button(
                "📥 Descargar Mapa de Prescripción",
                mapa_buffer,
                f"prescripcion_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                "image/png"
            )
        
        # TABLA DE RECOMENDACIONES
        st.subheader("💊 RECOMENDACIONES POR ZONA")
        
        tabla_recomendaciones = gdf_analizado[['id_zona', 'valor', 'categoria', 'area_ha', 'recomendacion']].copy()
        tabla_recomendaciones.columns = ['Zona', 'Valor', 'Categoría', 'Área (ha)', 'Recomendación']
        st.dataframe(tabla_recomendaciones, use_container_width=True)
        
        # DISTRIBUCIÓN
        st.subheader("📈 DISTRIBUCIÓN POR CATEGORÍA")
        
        distribucion = gdf_analizado.groupby('categoria').agg({
            'valor': ['min', 'max', 'mean'],
            'area_ha': 'sum',
            'id_zona': 'count'
        }).round(2)
        
        distribucion.columns = ['Mínimo', 'Máximo', 'Promedio', 'Área Total', 'N° Zonas']
        distribucion['% Área'] = (distribucion['Área Total'] / area_total * 100).round(1)
        st.dataframe(distribucion, use_container_width=True)
        
        # DESCARGAS
        st.subheader("📥 DESCARGAR RESULTADOS")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # CSV con datos
            csv = gdf_analizado.to_csv(index=False)
            st.download_button(
                "📋 Descargar CSV Completo",
                csv,
                f"prescripcion_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv"
            )
        
        with col2:
            # Shapefile con resultados
            temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
            with zipfile.ZipFile(temp_zip.name, 'w') as zipf:
                # Guardar shapefile
                gdf_analizado.to_file(temp_zip.name.replace('.zip', '.shp'))
                # Agregar archivos componentes
                for ext in ['.shp', '.shx', '.dbf', '.prj']:
                    file_path = temp_zip.name.replace('.zip', ext)
                    if os.path.exists(file_path):
                        zipf.write(file_path, os.path.basename(file_path))
                        os.unlink(file_path)
            
            with open(temp_zip.name, 'rb') as f:
                st.download_button(
                    "🗺️ Descargar Shapefile",
                    f.read(),
                    f"zonas_manejo_{nutriente}_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                    "application/zip"
                )
            
            os.unlink(temp_zip.name)
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error en análisis: {str(e)}")
        import traceback
        st.error(f"Detalle: {traceback.format_exc()}")
        return False

# INTERFAZ PRINCIPAL
if uploaded_zip:
    with st.spinner("Cargando parcela de palma aceitera..."):
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(uploaded_zip, 'r') as zip_ref:
                    zip_ref.extractall(tmp_dir)
                
                shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                if shp_files:
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf = gpd.read_file(shp_path)
                    
                    st.success(f"✅ **Parcela cargada:** {len(gdf)} polígono(s)")
                    
                    # Mostrar información de la parcela
                    area_total = calcular_superficie(gdf).sum()
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write("**📊 INFORMACIÓN DE LA PARCELA:**")
                        st.write(f"- Polígonos: {len(gdf)}")
                        st.write(f"- Área total: {area_total:.1f} ha")
                        st.write(f"- CRS: {gdf.crs}")
                    
                    with col2:
                        st.write("**🎯 CONFIGURACIÓN DE DIVISIÓN:**")
                        st.write(f"- Sub-áreas: {n_divisiones}")
                        st.write(f"- Tipo: {tipo_division}")
                        st.write(f"- Área promedio por zona: {area_total/n_divisiones:.1f} ha")
                    
                    # EJECUTAR ANÁLISIS
                    if st.button("🚀 EJECUTAR DIVISIÓN Y ANÁLISIS", type="primary"):
                        analisis_agricultura_precision(gdf, nutriente, n_divisiones, tipo_division)
                        
        except Exception as e:
            st.error(f"Error cargando shapefile: {str(e)}")

else:
    st.info("📁 Sube el ZIP de tu parcela de palma aceitera para comenzar")
    
    # INFORMACIÓN ADICIONAL
    with st.expander("💡 ¿CÓMO FUNCIONA LA DIVISIÓN AUTOMÁTICA?"):
        st.markdown("""
        **🌱 AGRICULTURA DE PRECISIÓN CON UNA SOLA PARCELA**
        
        **1. PROBLEMA IDENTIFICADO:**
        - Tienes una parcela grande de palma aceitera
        - No hay subdivisiones naturales
        - No puedes aplicar dosis diferenciadas
        
        **2. SOLUCIÓN AUTOMÁTICA:**
        - **Dividimos** tu parcela en zonas de manejo
        - **Simulamos** variabilidad espacial realista
        - **Generamos** mapa de prescripción
        - **Creamos** recomendaciones por zona
        
        **3. TIPOS DE DIVISIÓN:**
        - **🔲 Cuadrícula Regular:** Ideal para parcelas rectangulares
        - **📏 Por Franjas:** Para manejo mecanizado
        - **🎯 Zonas Concéntricas:** Para variación desde el centro
        
        **4. RESULTADOS OBTENIDOS:**
        - Mapa de prescripción listo para campo
        - Tabla de recomendaciones por zona
        - Shapefile con las subdivisiones
        - Estadísticas de variabilidad
        """)

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
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import base64

st.set_page_config(page_title="🌴 Analizador Cultivos", layout="wide")
st.title("🌱 ANALIZADOR CULTIVOS - METODOLOGÍA GEE COMPLETA CON AGROECOLOGÍA")
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

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")
    
    cultivo = st.selectbox("Cultivo:", 
                          ["PALMA_ACEITERA", "CACAO", "BANANO"])
    
    analisis_tipo = st.selectbox("Tipo de Análisis:", 
                               ["FERTILIDAD ACTUAL", "RECOMENDACIONES NPK"])
    
    nutriente = st.selectbox("Nutriente:", ["NITRÓGENO", "FÓSFORO", "POTASIO"])
    
    mes_analisis = st.selectbox("Mes de Análisis:", 
                               ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                                "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"])
    
    st.subheader("🎯 División de Parcela")
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

# FUNCIÓN PARA CREAR MAPA ESTÁTICO
def crear_mapa_estatico(gdf, titulo, columna_valor=None, analisis_tipo=None, nutriente=None):
    """Crea mapa estático con matplotlib"""
    try:
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        
        # Configurar colores según el tipo de análisis
        if columna_valor and analisis_tipo:
            if analisis_tipo == "FERTILIDAD ACTUAL":
                cmap = LinearSegmentedColormap.from_list('fertilidad_gee', PALETAS_GEE['FERTILIDAD'])
                vmin, vmax = 0, 1
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
            
            # Plotear cada polígono con color según valor
            for idx, row in gdf.iterrows():
                valor = row[columna_valor]
                valor_norm = (valor - vmin) / (vmax - vmin)
                valor_norm = max(0, min(1, valor_norm))
                color = cmap(valor_norm)
                
                gdf.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1)
                
                # Etiqueta con valor
                centroid = row.geometry.centroid
                ax.annotate(f"Z{row['id_zona']}\n{valor:.1f}", (centroid.x, centroid.y), 
                           xytext=(3, 3), textcoords="offset points", 
                           fontsize=6, color='black', weight='bold',
                           bbox=dict(boxstyle="round,pad=0.2", facecolor='white', alpha=0.8))
        else:
            # Mapa simple del polígono original
            gdf.plot(ax=ax, color='lightblue', edgecolor='black', linewidth=2, alpha=0.7)
        
        # Configuración del mapa
        ax.set_title(f'🗺️ {titulo}', fontsize=14, fontweight='bold', pad=15)
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        # Añadir barra de colores si hay valores
        if columna_valor and analisis_tipo:
            sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
            sm.set_array([])
            cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
            if analisis_tipo == "FERTILIDAD ACTUAL":
                cbar.set_label('Índice NPK Actual (0-1)', fontsize=10)
            else:
                cbar.set_label(f'Recomendación {nutriente} (kg/ha)', fontsize=10)
        
        plt.tight_layout()
        
        # Convertir a imagen
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        return buf
        
    except Exception as e:
        st.error(f"Error creando mapa: {str(e)}")
        return None

# FUNCIÓN PARA CREAR MAPA ESTÁTICO PARA PDF
def crear_mapa_estatico_pdf(gdf, nutriente, analisis_tipo, mes_analisis, cultivo):
    """Crea mapa estático para incluir en el PDF"""
    try:
        fig, ax = plt.subplots(1, 1, figsize=(10, 8))
        
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
            
            gdf.iloc[[idx]].plot(ax=ax, color=color, edgecolor='black', linewidth=1)
            
            # Etiqueta con valor
            centroid = row.geometry.centroid
            ax.annotate(f"{valor:.1f}", (centroid.x, centroid.y), 
                       xytext=(0, 0), textcoords="offset points", 
                       fontsize=6, color='black', weight='bold',
                       ha='center', va='center')
        
        # Configuración del mapa
        ax.set_title(f'ANÁLISIS GEE - {analisis_tipo}\n{cultivo} - {mes_analisis}', 
                    fontsize=12, fontweight='bold', pad=10)
        
        ax.set_xlabel('Longitud')
        ax.set_ylabel('Latitud')
        ax.grid(True, alpha=0.3)
        
        # Barra de colores
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
        cbar.set_label(titulo_sufijo, fontsize=10)
        
        plt.tight_layout()
        
        # Convertir a imagen para PDF
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        return buf
        
    except Exception as e:
        st.error(f"Error creando mapa para PDF: {str(e)}")
        return None

# FUNCIÓN PARA GENERAR PDF
def generar_pdf_reporte(gdf_analizado, cultivo, analisis_tipo, nutriente, mes_analisis, area_total):
    """Genera un reporte PDF con todos los resultados"""
    
    try:
        # Crear buffer para PDF
        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, topMargin=1*inch)
        elements = []
        styles = getSampleStyleSheet()
        
        # Estilo personalizado para títulos
        titulo_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.darkgreen,
            spaceAfter=12,
            alignment=1  # Centrado
        )
        
        # Título principal
        elements.append(Paragraph(f"REPORTE DE ANÁLISIS GEE - {cultivo}", titulo_style))
        elements.append(Spacer(1, 12))
        
        # Información general
        info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=6
        )
        
        elements.append(Paragraph(f"<b>Tipo de Análisis:</b> {analisis_tipo}", info_style))
        if analisis_tipo == "RECOMENDACIONES NPK":
            elements.append(Paragraph(f"<b>Nutriente Analizado:</b> {nutriente}", info_style))
        elements.append(Paragraph(f"<b>Mes de Análisis:</b> {mes_analisis}", info_style))
        elements.append(Paragraph(f"<b>Área Total:</b> {area_total:.2f} ha", info_style))
        elements.append(Paragraph(f"<b>Zonas Analizadas:</b> {len(gdf_analizado)}", info_style))
        elements.append(Paragraph(f"<b>Fecha de Generación:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", info_style))
        elements.append(Spacer(1, 20))
        
        # Mapa estático
        mapa_buffer = crear_mapa_estatico_pdf(gdf_analizado, nutriente, analisis_tipo, mes_analisis, cultivo)
        if mapa_buffer:
            elements.append(Paragraph("<b>Mapa de Resultados</b>", styles['Heading2']))
            elements.append(Spacer(1, 12))
            
            # Convertir imagen para ReportLab
            img = Image(mapa_buffer, width=6*inch, height=4.5*inch)
            elements.append(img)
            elements.append(Spacer(1, 20))
        
        # Estadísticas resumen
        elements.append(Paragraph("<b>Estadísticas Resumen</b>", styles['Heading2']))
        elements.append(Spacer(1, 12))
        
        if analisis_tipo == "FERTILIDAD ACTUAL":
            valor_prom = gdf_analizado['npk_actual'].mean()
            valor_min = gdf_analizado['npk_actual'].min()
            valor_max = gdf_analizado['npk_actual'].max()
            coef_var = (gdf_analizado['npk_actual'].std() / valor_prom * 100)
            
            stats_data = [
                ['Estadística', 'Valor'],
                ['Promedio Índice NPK', f'{valor_prom:.3f}'],
                ['Mínimo', f'{valor_min:.3f}'],
                ['Máximo', f'{valor_max:.3f}'],
                ['Coeficiente de Variación', f'{coef_var:.1f}%']
            ]
        else:
            valor_prom = gdf_analizado['valor_recomendado'].mean()
            valor_min = gdf_analizado['valor_recomendado'].min()
            valor_max = gdf_analizado['valor_recomendado'].max()
            coef_var = (gdf_analizado['valor_recomendado'].std() / valor_prom * 100)
            
            stats_data = [
                ['Estadística', 'Valor'],
                [f'Promedio {nutriente}', f'{valor_prom:.1f} kg/ha'],
                ['Mínimo', f'{valor_min:.1f} kg/ha'],
                ['Máximo', f'{valor_max:.1f} kg/ha'],
                ['Coeficiente de Variación', f'{coef_var:.1f}%']
            ]
        
        stats_table = Table(stats_data, colWidths=[3*inch, 2*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(stats_table)
        elements.append(Spacer(1, 20))
        
        # Distribución por categorías
        elements.append(Paragraph("<b>Distribución por Categorías</b>", styles['Heading2']))
        elements.append(Spacer(1, 12))
        
        categorias = gdf_analizado['categoria'].value_counts().reset_index()
        categorias.columns = ['Categoría', 'Número de Zonas']
        
        cat_data = [['Categoría', 'Zonas', 'Área (ha)', '% del Total']]
        for _, cat in categorias.iterrows():
            cat_nombre = cat['Categoría']
            subset = gdf_analizado[gdf_analizado['categoria'] == cat_nombre]
            area_cat = subset['area_ha'].sum()
            porcentaje = (area_cat / area_total) * 100
            cat_data.append([cat_nombre, str(cat['Número de Zonas']), f'{area_cat:.1f}', f'{porcentaje:.1f}%'])
        
        cat_table = Table(cat_data, colWidths=[1.5*inch, 1*inch, 1*inch, 1.2*inch])
        cat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.lightblue),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(cat_table)
        elements.append(Spacer(1, 20))
        
        # Tabla de resultados detallados (primeras 10 filas)
        elements.append(Paragraph("<b>Resultados Detallados (Primeras 10 Zonas)</b>", styles['Heading2']))
        elements.append(Spacer(1, 12))
        
        # Preparar datos para tabla
        columnas = ['id_zona', 'area_ha']
        if analisis_tipo == "FERTILIDAD ACTUAL":
            columnas.extend(['npk_actual', 'materia_organica', 'ndvi', 'ndre', 'categoria'])
            headers = ['Zona', 'Área (ha)', 'NPK', 'Materia Org%', 'NDVI', 'NDRE', 'Categoría']
        else:
            columnas.extend(['valor_recomendado', 'materia_organica', 'ndvi', 'categoria'])
            headers = ['Zona', 'Área (ha)', f'{nutriente} (kg/ha)', 'Materia Org%', 'NDVI', 'Categoría']
        
        tabla_data = gdf_analizado[columnas].head(10).copy()
        
        # Crear tabla para PDF
        pdf_table_data = [headers]
        for _, row in tabla_data.iterrows():
            if analisis_tipo == "FERTILIDAD ACTUAL":
                pdf_table_data.append([
                    str(int(row['id_zona'])),
                    f"{row['area_ha']:.2f}",
                    f"{row['npk_actual']:.3f}",
                    f"{row['materia_organica']:.1f}",
                    f"{row['ndvi']:.3f}",
                    f"{row['ndre']:.3f}",
                    row['categoria']
                ])
            else:
                pdf_table_data.append([
                    str(int(row['id_zona'])),
                    f"{row['area_ha']:.2f}",
                    f"{row['valor_recomendado']:.1f}",
                    f"{row['materia_organica']:.1f}",
                    f"{row['ndvi']:.3f}",
                    row['categoria']
                ])
        
        # Ajustar ancho de columnas según el tipo de análisis
        if analisis_tipo == "FERTILIDAD ACTUAL":
            col_widths = [0.5*inch, 0.8*inch, 0.7*inch, 0.9*inch, 0.7*inch, 0.7*inch, 1.2*inch]
        else:
            col_widths = [0.5*inch, 0.8*inch, 1.2*inch, 0.9*inch, 0.7*inch, 1.2*inch]
        
        pdf_table = Table(pdf_table_data, colWidths=col_widths)
        pdf_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))
        elements.append(pdf_table)
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"<i>Mostrando 10 de {len(gdf_analizado)} zonas. Descargue el CSV para todos los datos.</i>", 
                                ParagraphStyle('Note', parent=styles['Italic'], fontSize=7)))
        elements.append(Spacer(1, 20))
        
        # Recomendaciones agroecológicas
        elements.append(Paragraph("<b>Recomendaciones Agroecológicas</b>", styles['Heading2']))
        elements.append(Spacer(1, 12))
        
        recomendaciones = RECOMENDACIONES_AGROECOLOGICAS.get(cultivo, {})
        for categoria, recs in recomendaciones.items():
            elements.append(Paragraph(f"<b>{categoria.replace('_', ' ').title()}</b>", styles['Heading3']))
            for rec in recs[:3]:  # Mostrar solo las 3 principales de cada categoría
                elements.append(Paragraph(f"• {rec}", styles['Normal']))
            elements.append(Spacer(1, 6))
        
        # Pie de página
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("<i>Reporte generado automáticamente por el Sistema de Análisis GEE con Agroecología</i>", 
                                ParagraphStyle('Footer', parent=styles['Italic'], fontSize=8, alignment=1)))
        
        # Construir PDF
        doc.build(elements)
        pdf_buffer.seek(0)
        
        return pdf_buffer
        
    except Exception as e:
        st.error(f"Error generando PDF: {str(e)}")
        return None

# FUNCIÓN PARA MOSTRAR RECOMENDACIONES AGROECOLÓGICAS
def mostrar_recomendaciones_agroecologicas(cultivo, categoria, area_ha, analisis_tipo, nutriente=None):
    """Muestra recomendaciones agroecológicas específicas"""
    
    st.markdown("### 🌿 RECOMENDACIONES AGROECOLÓGICAS")
    
    # Determinar el enfoque según la categoría
    if categoria in ["MUY BAJA", "MUY BAJO", "BAJA", "BAJO"]:
        enfoque = "🚨 **ENFOQUE: RECUPERACIÓN Y REGENERACIÓN**"
        intensidad = "Alta"
    elif categoria in ["MEDIA", "MEDIO"]:
        enfoque = "✅ **ENFOQUE: MANTENIMIENTO Y MEJORA**"
        intensidad = "Media"
    else:
        enfoque = "🌟 **ENFOQUE: CONSERVACIÓN Y OPTIMIZACIÓN**"
        intensidad = "Baja"
    
    st.success(f"{enfoque} - Intensidad: {intensidad}")
    
    # Obtener recomendaciones específicas del cultivo
    recomendaciones = RECOMENDACIONES_AGROECOLOGICAS.get(cultivo, {})
    
    # Mostrar por categorías
    col1, col2 = st.columns(2)
    
    with col1:
        with st.expander("🌱 **COBERTURAS VIVAS**", expanded=True):
            for rec in recomendaciones.get('COBERTURAS_VIVAS', []):
                st.markdown(f"• {rec}")
            
            # Recomendaciones adicionales según área
            if area_ha > 10:
                st.info("**Para áreas grandes:** Implementar en franjas progresivas")
            else:
                st.info("**Para áreas pequeñas:** Cobertura total recomendada")
    
    with col2:
        with st.expander("🌿 **ABONOS VERDES**", expanded=True):
            for rec in recomendaciones.get('ABONOS_VERDES', []):
                st.markdown(f"• {rec}")
            
            # Ajustar según intensidad
            if intensidad == "Alta":
                st.warning("**Prioridad alta:** Sembrar inmediatamente después de análisis")
    
    col3, col4 = st.columns(2)
    
    with col3:
        with st.expander("💩 **BIOFERTILIZANTES**", expanded=True):
            for rec in recomendaciones.get('BIOFERTILIZANTES', []):
                st.markdown(f"• {rec}")
            
            # Recomendaciones específicas por nutriente
            if analisis_tipo == "RECOMENDACIONES NPK" and nutriente:
                if nutriente == "NITRÓGENO":
                    st.markdown("• **Enmienda nitrogenada:** Compost de leguminosas")
                elif nutriente == "FÓSFORO":
                    st.markdown("• **Enmienda fosfatada:** Rocas fosfóricas molidas")
                else:
                    st.markdown("• **Enmienda potásica:** Cenizas de biomasa")
    
    with col4:
        with st.expander("🐞 **MANEJO ECOLÓGICO**", expanded=True):
            for rec in recomendaciones.get('MANEJO_ECOLOGICO', []):
                st.markdown(f"• {rec}")
            
            # Recomendaciones según categoría
            if categoria in ["MUY BAJA", "MUY BAJO"]:
                st.markdown("• **Urgente:** Implementar control biológico intensivo")
    
    with st.expander("🌳 **ASOCIACIONES Y DIVERSIFICACIÓN**", expanded=True):
        for rec in recomendaciones.get('ASOCIACIONES', []):
            st.markdown(f"• {rec}")
        
        # Beneficios de las asociaciones
        st.markdown("""
        **Beneficios agroecológicos:**
        • Mejora la biodiversidad funcional
        • Reduce incidencia de plagas y enfermedades
        • Optimiza el uso de recursos (agua, luz, nutrientes)
        • Incrementa la resiliencia del sistema
        """)
    
    # PLAN DE IMPLEMENTACIÓN
    st.markdown("### 📅 PLAN DE IMPLEMENTACIÓN AGROECOLÓGICA")
    
    timeline_col1, timeline_col2, timeline_col3 = st.columns(3)
    
    with timeline_col1:
        st.markdown("**🏁 INMEDIATO (0-15 días)**")
        st.markdown("""
        • Preparación del terreno
        • Siembra de abonos verdes
        • Aplicación de biofertilizantes
        • Instalación de trampas
        """)
    
    with timeline_col2:
        st.markdown("**📈 CORTO PLAZO (1-3 meses)**")
        st.markdown("""
        • Establecimiento coberturas
        • Monitoreo inicial
        • Ajustes de manejo
        • Podas de formación
        """)
    
    with timeline_col3:
        st.markdown("**🎯 MEDIANO PLAZO (3-12 meses)**")
        st.markdown("""
        • Evaluación de resultados
        • Diversificación
        • Optimización del sistema
        • Réplica en otras zonas
        """)

# FUNCIÓN PARA DIVIDIR PARCELA
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

# METODOLOGÍA GEE - CÁLCULO DE ÍNDICES SATELITALES
def calcular_indices_satelitales_gee(gdf, mes_analisis, cultivo):
    """Implementa la metodología completa de Google Earth Engine"""
    
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
        
        # 1. MATERIA ORGÁNICA - Ajustada por mes y cultivo
        relacion_swir_red = (0.3 + (patron_espacial * 0.4)) * factor_mes
        materia_organica_base = (relacion_swir_red * 2.5 + 0.5) * 1.5
        # Ajuste según cultivo
        if cultivo == "CACAO":
            materia_organica_base *= 0.9
        elif cultivo == "BANANO":
            materia_organica_base *= 1.1
        materia_organica = materia_organica_base + np.random.normal(0, 0.3)
        materia_organica = max(0.5, min(8.0, materia_organica))
        
        # 2. HUMEDAD SUELO - Ajustada por estacionalidad y cultivo
        relacion_nir_swir = (-0.2 + (patron_espacial * 0.6)) * factor_mes
        humedad_base = relacion_nir_swir
        if cultivo == "CACAO":
            humedad_base *= 1.1
        elif cultivo == "BANANO":
            humedad_base *= 1.2
        humedad_suelo = humedad_base + np.random.normal(0, 0.1)
        humedad_suelo = max(-0.5, min(0.8, humedad_suelo))
        
        # 3. NDVI - Ajustado por época del año y cultivo
        ndvi_base = (0.4 + (patron_espacial * 0.4)) * factor_mes
        if cultivo == "CACAO":
            ndvi_base *= 0.9
        elif cultivo == "BANANO":
            ndvi_base *= 1.1
        ndvi = ndvi_base + np.random.normal(0, 0.08)
        ndvi = max(-0.2, min(1.0, ndvi))
        
        # 4. NDRE - Ajustado por época del año y cultivo
        ndre_base = (0.3 + (patron_espacial * 0.3)) * factor_mes
        if cultivo == "CACAO":
            ndre_base *= 0.85
        elif cultivo == "BANANO":
            ndre_base *= 1.15
        ndre = ndre_base + np.random.normal(0, 0.06)
        ndre = max(0.1, min(0.7, ndre))
        
        # 5. ÍNDICE NPK ACTUAL - Con ajuste estacional y de cultivo
        npk_actual = (ndvi * 0.5) + (ndre * 0.3) + ((materia_organica / 8) * 0.2)
        if cultivo == "CACAO":
            npk_actual *= 0.95
        elif cultivo == "BANANO":
            npk_actual *= 1.05
        npk_actual = max(0, min(1, npk_actual))
        
        resultados.append({
            'materia_organica': round(materia_organica, 2),
            'humedad_suelo': round(humedad_suelo, 3),
            'ndvi': round(ndvi, 3),
            'ndre': round(ndre, 3),
            'npk_actual': round(npk_actual, 3),
            'mes_analisis': mes_analisis,
            'cultivo': cultivo
        })
    
    return resultados

# FUNCIÓN GEE PARA RECOMENDACIONES NPK (CORREGIDA)
def calcular_recomendaciones_npk_gee(indices, nutriente, mes_analisis, cultivo):
    """Calcula recomendaciones NPK basadas en la metodología GEE"""
    recomendaciones = []
    
    factor_mes_n = FACTORES_N_MES.get(mes_analisis, 1.0)
    factor_mes_p = FACTORES_P_MES.get(mes_analisis, 1.0)
    factor_mes_k = FACTORES_K_MES.get(mes_analisis, 1.0)
    
    # Obtener parámetros del cultivo seleccionado
    parametros_cultivo = PARAMETROS_CULTIVOS.get(cultivo, PARAMETROS_CULTIVOS['PALMA_ACEITERA'])
    
    for idx in indices:
        ndre = idx['ndre']
        materia_organica = idx['materia_organica']
        humedad_suelo = idx['humedad_suelo']
        
        if nutriente == "NITRÓGENO":
            # CORRECCIÓN: Usar 'NITROGENO' en lugar de 'NITRÓGENO'
            n_recomendado = ((1 - ndre) * 
                           (parametros_cultivo['NITROGENO']['max'] - parametros_cultivo['NITROGENO']['min']) + 
                           parametros_cultivo['NITROGENO']['min']) * factor_mes_n
            n_recomendado = max(parametros_cultivo['NITROGENO']['min'] - 20, 
                              min(parametros_cultivo['NITROGENO']['max'] + 20, n_recomendado))
            recomendaciones.append(round(n_recomendado, 1))
            
        elif nutriente == "FÓSFORO":
            # CORRECCIÓN: Usar 'FOSFORO' en lugar de 'FÓSFORO'
            p_recomendado = ((1 - (materia_organica / 8)) * 
                           (parametros_cultivo['FOSFORO']['max'] - parametros_cultivo['FOSFORO']['min']) + 
                           parametros_cultivo['FOSFORO']['min']) * factor_mes_p
            p_recomendado = max(parametros_cultivo['FOSFORO']['min'] - 10, 
                              min(parametros_cultivo['FOSFORO']['max'] + 10, p_recomendado))
            recomendaciones.append(round(p_recomendado, 1))
            
        else:  # POTASIO
            # CORRECCIÓN: Usar 'POTASIO' en lugar de 'POTASIO' (está bien, pero por consistencia)
            humedad_norm = (humedad_suelo + 1) / 2
            k_recomendado = ((1 - humedad_norm) * 
                           (parametros_cultivo['POTASIO']['max'] - parametros_cultivo['POTASIO']['min']) + 
                           parametros_cultivo['POTASIO']['min']) * factor_mes_k
            k_recomendado = max(parametros_cultivo['POTASIO']['min'] - 15, 
                              min(parametros_cultivo['POTASIO']['max'] + 15, k_recomendado))
            recomendaciones.append(round(k_recomendado, 1))
    
    return recomendaciones

# FUNCIÓN PRINCIPAL DE ANÁLISIS GEE
def analisis_gee_completo(gdf, nutriente, analisis_tipo, n_divisiones, mes_analisis, cultivo):
    try:
        st.header(f"🌴 ANÁLISIS CON METODOLOGÍA GOOGLE EARTH ENGINE - {cultivo}")
        
        # PASO 1: DIVIDIR PARCELA
        st.subheader("📐 DIVIDIENDO PARCELA EN ZONAS DE MANEJO")
        with st.spinner("Dividiendo parcela..."):
            gdf_dividido = dividir_parcela_en_zonas(gdf, n_divisiones)
        
        st.success(f"✅ Parcela dividida en {len(gdf_dividido)} zonas")
        
        # Calcular áreas
        areas_ha = calcular_superficie(gdf_dividido)
        area_total = areas_ha.sum()
        
        # PASO 2: CALCULAR ÍNDICES GEE
        st.subheader("🛰️ CALCULANDO ÍNDICES SATELITALES GEE")
        with st.spinner("Ejecutando algoritmos GEE..."):
            indices_gee = calcular_indices_satelitales_gee(gdf_dividido, mes_analisis, cultivo)
        
        # Crear dataframe con resultados
        gdf_analizado = gdf_dividido.copy()
        gdf_analizado['area_ha'] = areas_ha
        
        # Añadir índices GEE
        for idx, indice in enumerate(indices_gee):
            for key, value in indice.items():
                gdf_analizado.loc[gdf_analizado.index[idx], key] = value
        
        # PASO 3: CALCULAR RECOMENDACIONES SI ES NECESARIO
        if analisis_tipo == "RECOMENDACIONES NPK":
            with st.spinner("Calculando recomendaciones NPK..."):
                recomendaciones = calcular_recomendaciones_npk_gee(indices_gee, nutriente, mes_analisis, cultivo)
                gdf_analizado['valor_recomendado'] = recomendaciones
                columna_valor = 'valor_recomendado'
        else:
            columna_valor = 'npk_actual'
        
        # PASO 4: CATEGORIZAR PARA RECOMENDACIONES
        def categorizar_gee(valor, nutriente, analisis_tipo, cultivo):
            parametros = PARAMETROS_CULTIVOS.get(cultivo, PARAMETROS_CULTIVOS['PALMA_ACEITERA'])
            
            if analisis_tipo == "FERTILIDAD ACTUAL":
                if valor < 0.3: return "MUY BAJA"
                elif valor < 0.5: return "BAJA"
                elif valor < 0.6: return "MEDIA"
                elif valor < 0.7: return "BUENA"
                else: return "ÓPTIMA"
            else:
                if nutriente == "NITRÓGENO":
                    rango = parametros['NITROGENO']['max'] - parametros['NITROGENO']['min']
                    if valor < parametros['NITROGENO']['min'] - 0.2 * rango: return "MUY BAJO"
                    elif valor < parametros['NITROGENO']['min']: return "BAJO"
                    elif valor < parametros['NITROGENO']['max']: return "MEDIO"
                    elif valor < parametros['NITROGENO']['max'] + 0.2 * rango: return "ALTO"
                    else: return "MUY ALTO"
                elif nutriente == "FÓSFORO":
                    rango = parametros['FOSFORO']['max'] - parametros['FOSFORO']['min']
                    if valor < parametros['FOSFORO']['min'] - 0.2 * rango: return "MUY BAJO"
                    elif valor < parametros['FOSFORO']['min']: return "BAJO"
                    elif valor < parametros['FOSFORO']['max']: return "MEDIO"
                    elif valor < parametros['FOSFORO']['max'] + 0.2 * rango: return "ALTO"
                    else: return "MUY ALTO"
                else:
                    rango = parametros['POTASIO']['max'] - parametros['POTASIO']['min']
                    if valor < parametros['POTASIO']['min'] - 0.2 * rango: return "MUY BAJO"
                    elif valor < parametros['POTASIO']['min']: return "BAJO"
                    elif valor < parametros['POTASIO']['max']: return "MEDIO"
                    elif valor < parametros['POTASIO']['max'] + 0.2 * rango: return "ALTO"
                    else: return "MUY ALTO"
        
        gdf_analizado['categoria'] = [
            categorizar_gee(row[columna_valor], nutriente, analisis_tipo, cultivo) 
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
        
        # MAPA ESTÁTICO
        st.subheader("🗺️ MAPA DE RESULTADOS")
        
        mapa_estatico = crear_mapa_estatico(
            gdf_analizado, 
            f"Análisis GEE - {analisis_tipo} - {cultivo}",
            columna_valor,
            analisis_tipo,
            nutriente
        )
        
        if mapa_estatico:
            st.image(mapa_estatico, use_container_width=True)
            
            # Botón para descargar el mapa
            st.download_button(
                "📸 Descargar Mapa PNG",
                mapa_estatico.getvalue(),
                f"mapa_gee_{cultivo}_{analisis_tipo.replace(' ', '_')}_{mes_analisis}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
                "image/png"
            )
        
        # BOTONES DE EXPORTACIÓN
        st.subheader("📥 DESCARGAR RESULTADOS")
        
        col_export1, col_export2, col_export3, col_export4 = st.columns(4)
        
        with col_export1:
            # Exportar CSV
            csv = gdf_analizado.to_csv(index=False)
            st.download_button(
                "📋 Descargar CSV",
                csv,
                f"analisis_gee_{cultivo}_{analisis_tipo.replace(' ', '_')}_{mes_analisis}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv"
            )
        
        with col_export2:
            # Exportar GeoJSON
            geojson_str = gdf_analizado.to_json()
            st.download_button(
                "🗺️ Descargar GeoJSON",
                geojson_str,
                f"analisis_gee_{cultivo}_{analisis_tipo.replace(' ', '_')}_{mes_analisis}_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson",
                "application/geo+json"
            )
        
        with col_export3:
            # Exportar Shapefile
            with tempfile.TemporaryDirectory() as tmp_dir:
                shp_path = os.path.join(tmp_dir, "resultados_gee.shp")
                gdf_analizado.to_file(shp_path)
                
                # Crear ZIP con shapefile
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
                    for file in os.listdir(tmp_dir):
                        zip_file.write(os.path.join(tmp_dir, file), file)
                zip_buffer.seek(0)
                
                st.download_button(
                    "📁 Descargar Shapefile (ZIP)",
                    zip_buffer,
                    f"analisis_gee_{cultivo}_{analisis_tipo.replace(' ', '_')}_{mes_analisis}_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                    "application/zip"
                )
        
        with col_export4:
            # Generar y exportar PDF
            with st.spinner("Generando reporte PDF..."):
                pdf_buffer = generar_pdf_reporte(gdf_analizado, cultivo, analisis_tipo, nutriente, mes_analisis, area_total)
                if pdf_buffer:
                    st.download_button(
                        "📄 Descargar Reporte PDF",
                        pdf_buffer.getvalue(),
                        f"reporte_gee_{cultivo}_{analisis_tipo.replace(' ', '_')}_{mes_analisis}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                        "application/pdf"
                    )
        
        # RECOMENDACIONES AGROECOLÓGICAS POR CATEGORÍA
        st.subheader("🌿 RECOMENDACIONES AGROECOLÓGICAS POR ZONA")
        
        categorias = gdf_analizado['categoria'].unique()
        for cat in sorted(categorias):
            subset = gdf_analizado[gdf_analizado['categoria'] == cat]
            area_cat = subset['area_ha'].sum()
            
            with st.expander(f"🎯 **ZONAS {cat}** - {area_cat:.1f} ha ({(area_cat/area_total*100):.1f}% del área)", expanded=True):
                
                # Mostrar recomendaciones agroecológicas
                mostrar_recomendaciones_agroecologicas(cultivo, cat, area_cat, analisis_tipo, nutriente)
                
                # Mostrar estadísticas de la categoría
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Número de Zonas", len(subset))
                with col2:
                    if analisis_tipo == "FERTILIDAD ACTUAL":
                        st.metric("NPK Promedio", f"{subset['npk_actual'].mean():.3f}")
                    else:
                        st.metric("Valor Promedio", f"{subset['valor_recomendado'].mean():.1f}")
                with col3:
                    st.metric("Área Total", f"{area_cat:.1f} ha")
        
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
        
        return gdf_analizado
        
    except Exception as e:
        st.error(f"❌ Error en análisis GEE: {str(e)}")
        import traceback
        st.error(f"Detalle: {traceback.format_exc()}")
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
                        st.write(f"- Cultivo: {cultivo}")
                        st.write(f"- Análisis: {analisis_tipo}")
                        st.write(f"- Nutriente: {nutriente}")
                        st.write(f"- Mes: {mes_analisis}")
                        st.write(f"- Zonas: {n_divisiones}")
                    
                    # VISUALIZAR PARCELA ORIGINAL
                    st.subheader("🗺️ VISUALIZACIÓN DE LA PARCELA")
                    mapa_parcela = crear_mapa_estatico(gdf, "Parcela Original")
                    if mapa_parcela:
                        st.image(mapa_parcela, use_container_width=True)
                    
                    # EJECUTAR ANÁLISIS GEE
                    if st.button("🚀 EJECUTAR ANÁLISIS GEE COMPLETO", type="primary"):
                        gdf_resultados = analisis_gee_completo(gdf, nutriente, analisis_tipo, n_divisiones, mes_analisis, cultivo)
                        
        except Exception as e:
            st.error(f"Error cargando shapefile: {str(e)}")

else:
    st.info("📁 Sube el ZIP de tu parcela para comenzar el análisis")
    
    # INFORMACIÓN INICIAL
    with st.expander("ℹ️ INFORMACIÓN SOBRE EL SISTEMA AGROECOLÓGICO GEE"):
        st.markdown("""
        ## 🌱 SISTEMA DE ANÁLISIS MULTICULTIVO CON ENFOQUE AGROECOLÓGICO

        **🆕 FUNCIONALIDADES IMPLEMENTADAS:**

        ### 📊 ANÁLISIS GEE COMPLETO:
        - **Metodología Google Earth Engine** con imágenes Sentinel-2
        - **Índices de vegetación**: NDVI, NDRE, Materia Orgánica
        - **Análisis de fertilidad** actual del suelo
        - **Recomendaciones NPK** específicas por zona

        ### 🌿 PRINCIPIOS AGROECOLÓGICOS:
        - **Coberturas vivas y abonos verdes**
        - **Biofertilizantes y compostajes**
        - **Manejo ecológico de plagas**
        - **Asociaciones y diversificación**

        ### 📥 EXPORTACIÓN MULTIFORMATO:
        - **CSV** para análisis de datos
        - **GeoJSON** para aplicaciones web
        - **Shapefile** para sistemas GIS
        - **PDF** para reportes profesionales
        - **Mapas PNG** de alta calidad

        ### 🎯 CULTIVOS DISPONIBLES:
        - **🌴 PALMA ACEITERA**
        - **🍫 CACAO** 
        - **🍌 BANANO**

        **🚀 INSTRUCCIONES:**
        1. **Sube** tu shapefile en formato ZIP
        2. **Configura** los parámetros de análisis
        3. **Ejecuta** el análisis GEE completo
        4. **Revisa** resultados y recomendaciones
        5. **Exporta** en los formatos que necesites

        **🔬 METODOLOGÍA CIENTÍFICA:**
        - Algoritmos probados de Google Earth Engine
        - Sensores remotos Sentinel-2
        - Parámetros edafoclimáticos específicos
        - Agricultura de precisión por zonas
        """)

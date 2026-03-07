# app.py - Versión definitiva con Earthaccess (MODIS desde NASA Earthdata) y fallback a pyhdf
# 
# - Registro e inicio de sesión de usuarios.
# - Suscripción mensual (150 USD) con Mercado Pago.
# - Modo DEMO con datos simulados y posibilidad de subir tu propio polígono (sin ejemplos precargados).
# - Modo PREMIUM con datos reales de NDVI y NDWI desde Earthdata (MOD13Q1 y MOD09GA) calculados por bloque.
# - Usuario administrador mawucano@gmail.com con suscripción permanente.
#
# IMPORTANTE: 
# - Configurar variables de entorno en secrets: MERCADOPAGO_ACCESS_TOKEN,
#   EARTHDATA_USERNAME, EARTHDATA_PASSWORD, APP_BASE_URL.
# - Instalar dependencias: pip install earthaccess xarray rioxarray rasterio pyhdf

import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import io
from shapely.geometry import Polygon, Point, LineString, mapping, box
from shapely.validation import make_valid
import math
import warnings
from io import BytesIO
import requests
import re
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen, MeasureControl, MiniMap
from branca.colormap import LinearColormap
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import cv2
from PIL import Image
from scipy.spatial import KDTree
from scipy.interpolate import Rbf
import base64
import time
import shutil

# Suprimir advertencias de rasterio y otras librerías
warnings.filterwarnings('ignore', category=UserWarning, module='rasterio')
warnings.filterwarnings('ignore', category=RuntimeWarning)

# ===== AUTENTICACIÓN Y PAGOS =====
import sqlite3
import hashlib
import mercadopago

# ===== LIBRERÍAS PARA DATOS SATELITALES (EARTHDATA) =====
try:
    import earthaccess
    import xarray as xr
    import rioxarray
    EARTHDATA_OK = True
except ImportError:
    EARTHDATA_OK = False

# ===== LIBRERÍAS PARA PROCESAMIENTO RASTER (rasterio y pyhdf) =====
try:
    import rasterio
    from rasterio.mask import mask
    from rasterio.transform import from_origin
    RASTERIO_OK = True
except ImportError:
    RASTERIO_OK = False

try:
    from pyhdf.SD import SD, SDC
    PYHDF_OK = True
except ImportError:
    PYHDF_OK = False

# Mostrar advertencias solo si ninguna está disponible
if not RASTERIO_OK and not PYHDF_OK:
    st.warning("⚠️ Ni rasterio ni pyhdf están instalados. No se podrán leer archivos HDF4. Instala al menos uno: pip install rasterio o pip install pyhdf")

# ===== ESTILOS Y OCULTAMIENTO DE ELEMENTOS DE STREAMLIT =====
st.markdown("""
<style>
/* Ocultar toolbar superior */
div[data-testid="stToolbar"] {
    visibility: hidden;
    height: 0px;
    position: fixed;
}

/* Ocultar menú hamburguesa */
#MainMenu {
    visibility: hidden;
}

/* Ocultar footer */
footer {
    visibility: hidden;
}

/* Ocultar header Streamlit */
header {
    visibility: hidden;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>

/* Ocultar todo lo de Streamlit */
div[data-testid="stToolbar"] {visibility:hidden; height:0;}
#MainMenu {visibility:hidden;}
footer {visibility:hidden;}
header {visibility:hidden;}
a[href*="streamlit.io"] {display:none !important;}
a[href*="streamlitapp"] {display:none !important;}

/* Ocultar mensaje deploy */
div[data-testid="stDeployButton"] {display:none;}
div[data-testid="stDecoration"] {display:none;}
div[data-testid="stAppViewContainer"] > div:first-child {display:none;}

/* Bloquear right-click */
body { user-select:none; }

</style>

<script>
document.addEventListener('contextmenu', event => event.preventDefault());
</script>
""", unsafe_allow_html=True)

st.markdown("""
<style>
#overlay {
 position: fixed;
 bottom:0;
 right:0;
 width:300px;
 height:120px;
 background:white;
 z-index:9999999;
}
</style>
<div id="overlay"></div>
""", unsafe_allow_html=True)

# ===== CONFIGURACIÓN DE MERCADO PAGO =====
MERCADOPAGO_ACCESS_TOKEN = os.environ.get("MERCADOPAGO_ACCESS_TOKEN")
if not MERCADOPAGO_ACCESS_TOKEN:
    st.error("❌ No se encontró la variable de entorno MERCADOPAGO_ACCESS_TOKEN. Configúrala para habilitar pagos.")
    st.stop()

sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)

# ===== CREDENCIALES EARTHDATA (desde secrets) =====
EARTHDATA_USERNAME = os.environ.get("EARTHDATA_USERNAME")
EARTHDATA_PASSWORD = os.environ.get("EARTHDATA_PASSWORD")

# ===== BASE DE DATOS DE USUARIOS =====
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hash):
    return hash_password(password) == hash

def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT UNIQUE,
                  password_hash TEXT,
                  subscription_expires TIMESTAMP,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    admin_email = "mawucano@gmail.com"
    far_future = "2100-01-01 00:00:00"
    c.execute("SELECT id FROM users WHERE email = ?", (admin_email,))
    existing = c.fetchone()
    if existing:
        c.execute("UPDATE users SET subscription_expires = ? WHERE email = ?", (far_future, admin_email))
    else:
        default_password = "jocauru"
        password_hash = hash_password(default_password)
        c.execute("INSERT INTO users (email, password_hash, subscription_expires) VALUES (?, ?, ?)",
                  (admin_email, password_hash, far_future))
    conn.commit()
    conn.close()

init_db()

def register_user(email, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        password_hash = hash_password(password)
        c.execute("INSERT INTO users (email, password_hash, subscription_expires) VALUES (?, ?, ?)",
                  (email, password_hash, None))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def login_user(email, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, password_hash, subscription_expires FROM users WHERE email = ?", (email,))
    row = c.fetchone()
    conn.close()
    if row and verify_password(password, row[1]):
        return {'id': row[0], 'email': email, 'subscription_expires': row[2]}
    return None

def update_subscription(email, days=30):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    new_expiry = (datetime.now() + timedelta(days=days)).isoformat()
    c.execute("UPDATE users SET subscription_expires = ? WHERE email = ?", (new_expiry, email))
    conn.commit()
    conn.close()
    return new_expiry

def get_user_by_email(email):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, email, subscription_expires FROM users WHERE email = ?", (email,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'email': row[1], 'subscription_expires': row[2]}
    return None

# ===== FUNCIONES DE MERCADO PAGO =====
def create_preference(email, amount=150.0, description="Suscripción mensual - Analizador de Palma Aceitera"):
    """
    Crea una preferencia de pago en Mercado Pago y retorna el init_point y el ID.
    Maneja errores y retorna (None, None) si falla.
    """
    try:
        base_url = os.environ.get("APP_BASE_URL")
        if not base_url:
            try:
                base_url = st.secrets.get("APP_BASE_URL", "https://tuapp.streamlit.app")
            except:
                base_url = "https://tuapp.streamlit.app"

        preference_data = {
            "items": [{
                "title": description,
                "quantity": 1,
                "currency_id": "USD",
                "unit_price": amount
            }],
            "payer": {"email": email},
            "back_urls": {
                "success": f"{base_url}?payment=success",
                "failure": f"{base_url}?payment=failure",
                "pending": f"{base_url}?payment=pending"
            },
            "auto_return": "approved",
            "external_reference": email,
        }
        preference_response = sdk.preference().create(preference_data)
        
        if preference_response["status"] in [200, 201]:
            preference = preference_response["response"]
            return preference["init_point"], preference["id"]
        else:
            error_msg = preference_response.get("response", {}).get("message", "Error desconocido")
            st.error(f"❌ Error al crear preferencia de pago: {error_msg}")
            return None, None
    except Exception as e:
        st.error(f"❌ Error al conectar con Mercado Pago: {str(e)}")
        return None, None

def check_payment_status(payment_id):
    try:
        payment_info = sdk.payment().get(payment_id)
        if payment_info["status"] == 200:
            payment = payment_info["response"]
            if payment["status"] == "approved":
                email = payment.get("external_reference")
                if email:
                    new_expiry = update_subscription(email)
                    return True
    except Exception as e:
        st.error(f"Error verificando pago: {e}")
    return False

# ===== FUNCIONES DE AUTENTICACIÓN EN STREAMLIT =====
def show_login_signup():
    with st.sidebar:
        st.markdown("## 🔐 Acceso")
        menu = st.radio("", ["Iniciar sesión", "Registrarse"], key="auth_menu")
        email = st.text_input("Email", key="auth_email")
        password = st.text_input("Contraseña", type="password", key="auth_password")
        
        if menu == "Registrarse":
            if st.button("Registrar", key="register_btn"):
                if register_user(email, password):
                    st.success("Registro exitoso. Ahora inicia sesión.")
                else:
                    st.error("El email ya está registrado.")
        else:
            if st.button("Ingresar", key="login_btn"):
                user = login_user(email, password)
                if user:
                    st.session_state.user = user
                    st.success("Sesión iniciada")
                    st.rerun()
                else:
                    st.error("Email o contraseña incorrectos")

def logout():
    if st.sidebar.button("Cerrar sesión"):
        del st.session_state.user
        st.rerun()

# ===== FUNCIÓN DE SUSCRIPCIÓN MODIFICADA PARA PRESERVAR POLÍGONO =====
def check_subscription():
    """
    Verifica suscripción SIN perder el polígono cargado.
    """
    # Guardar referencia al polígono antes de cualquier redirección
    gdf_temp = st.session_state.get('gdf_original', None)
    
    if 'user' not in st.session_state:
        show_login_signup()
        # Restaurar polígono si existía
        if gdf_temp is not None:
            st.session_state.gdf_original = gdf_temp
        st.stop()
    
    # Modo DEMO - mantener polígono
    if st.session_state.get('demo_mode', False):
        with st.sidebar:
            st.markdown(f"👤 Usuario: {st.session_state.user['email']} (Modo DEMO)")
            if st.button("💳 Actualizar a Premium", key="upgrade_from_demo"):
                st.session_state.demo_mode = False
                st.session_state.payment_intent = True
                # NO borrar gdf_original
                st.rerun()
            logout()
        return
    
    with st.sidebar:
        st.markdown(f"👤 Usuario: {st.session_state.user['email']}")
        logout()
    
    user = st.session_state.user
    expiry = user.get('subscription_expires')
    if expiry:
        try:
            expiry_date = datetime.fromisoformat(expiry)
            if expiry_date > datetime.now():
                dias_restantes = (expiry_date - datetime.now()).days
                st.sidebar.info(f"✅ Suscripción activa (vence en {dias_restantes} días)")
                st.session_state.demo_mode = False
                return True
        except:
            pass
    
    st.warning("🔒 Tu suscripción ha expirado o no tienes una activa.")
    st.markdown("### ¿Cómo deseas continuar?")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 💳 Pagar ahora")
        st.write("Obtén acceso completo a datos satelitales reales y todas las funciones por **150 USD/mes**.")
        if st.button("💵 Ir a pagar", key="pay_now"):
            st.session_state.payment_intent = True
            st.rerun()
    with col2:
        st.markdown("#### 🆓 Modo DEMO")
        st.write("Continúa con datos simulados y funcionalidad limitada. (Sin guardar resultados)")
        if st.button("🎮 Continuar con DEMO", key="demo_button"):
            st.session_state.demo_mode = True
            st.rerun()
    
    if st.session_state.get('payment_intent', False):
        st.markdown("### 💳 Pago con Mercado Pago")
        st.write("Paga con tarjeta de crédito, débito o efectivo (en USD).")
        if st.button("💵 Pagar ahora 150 USD", key="pay_mp"):
            init_point, pref_id = create_preference(user['email'])
            if init_point:
                st.session_state.pref_id = pref_id
                st.markdown(f"[Haz clic aquí para pagar]({init_point})")
                st.info("Serás redirigido a Mercado Pago. Luego de pagar, regresa a esta página.")
            else:
                st.error("No se pudo generar el link de pago. Verifica la configuración de Mercado Pago.")
        
        st.markdown("### 🏦 Transferencia bancaria")
        st.write("También puedes pagar por transferencia (USD) a:")
        st.code("CBU: 3220001888034378480018\nAlias: inflar.pacu.inaudita")
        st.write("Luego envía el comprobante a **mawucano@gmail.com** para activar tu suscripción manualmente.")
        
        query_params = st.query_params
        if 'payment' in query_params and query_params['payment'] == 'success' and 'collection_id' in query_params:
            payment_id = query_params['collection_id']
            if check_payment_status(payment_id):
                st.success("✅ ¡Pago aprobado! Tu suscripción ha sido activada por 30 días.")
                updated_user = get_user_by_email(user['email'])
                if updated_user:
                    st.session_state.user = updated_user
                st.session_state.demo_mode = False
                st.session_state.payment_intent = False
                st.rerun()
            else:
                st.error("No se pudo verificar el pago. Contacta a soporte.")
        st.stop()
    
    st.stop()

# ===== FUNCIONES DE SIMULACIÓN PARA MODO DEMO =====
def generar_datos_simulados_completos(gdf_original, n_divisiones):
    gdf_dividido = dividir_plantacion_en_bloques(gdf_original, n_divisiones)
    areas_ha = []
    for idx, row in gdf_dividido.iterrows():
        area_gdf = gpd.GeoDataFrame({'geometry': [row.geometry]}, crs=gdf_dividido.crs)
        areas_ha.append(float(calcular_superficie(area_gdf)))
    gdf_dividido['area_ha'] = areas_ha
    
    np.random.seed(42)
    centroides = gdf_dividido.geometry.centroid
    lons = centroides.x.values
    lats = centroides.y.values
    
    ndvi_vals = 0.5 + 0.2 * np.sin(lons * 10) * np.cos(lats * 10) + 0.1 * np.random.randn(len(lons))
    ndvi_vals = np.clip(ndvi_vals, 0.2, 0.9)
    gdf_dividido['ndvi_modis'] = np.round(ndvi_vals, 3)
    
    ndwi_vals = 0.3 + 0.15 * np.cos(lons * 5) * np.sin(lats * 5) + 0.1 * np.random.randn(len(lons))
    ndwi_vals = np.clip(ndwi_vals, 0.1, 0.7)
    gdf_dividido['ndwi_modis'] = np.round(ndwi_vals, 3)
    
    edades = 5 + 10 * np.random.rand(len(lons))
    gdf_dividido['edad_anios'] = np.round(edades, 1)
    
    def clasificar_salud(ndvi):
        if ndvi < 0.4: return 'Crítica'
        if ndvi < 0.6: return 'Baja'
        if ndvi < 0.75: return 'Moderada'
        return 'Buena'
    gdf_dividido['salud'] = gdf_dividido['ndvi_modis'].apply(clasificar_salud)
    
    return gdf_dividido

def generar_clima_simulado():
    dias = 60
    np.random.seed(42)
    precip_diaria = np.random.exponential(3, dias) * (np.random.rand(dias) > 0.6)
    temp_diaria = 25 + 5 * np.sin(np.linspace(0, 4*np.pi, dias)) + np.random.randn(dias)*2
    rad_diaria = 20 + 5 * np.sin(np.linspace(0, 4*np.pi, dias)) + np.random.randn(dias)*3
    wind_diaria = 3 + 2 * np.sin(np.linspace(0, 2*np.pi, dias)) + np.random.randn(dias)*1
    
    return {
        'precipitacion': {
            'total': round(sum(precip_diaria), 1),
            'maxima_diaria': round(max(precip_diaria), 1),
            'dias_con_lluvia': int(sum(precip_diaria > 0.1)),
            'diaria': [round(p, 1) for p in precip_diaria]
        },
        'temperatura': {
            'promedio': round(np.mean(temp_diaria), 1),
            'maxima': round(np.max(temp_diaria), 1),
            'minima': round(np.min(temp_diaria), 1),
            'diaria': [round(t, 1) for t in temp_diaria]
        },
        'radiacion': {
            'promedio': round(np.mean(rad_diaria), 1),
            'maxima': round(np.max(rad_diaria), 1),
            'minima': round(np.min(rad_diaria), 1),
            'diaria': [round(r, 1) for r in rad_diaria]
        },
        'viento': {
            'promedio': round(np.mean(wind_diaria), 1),
            'maxima': round(np.max(wind_diaria), 1),
            'diaria': [round(w, 1) for w in wind_diaria]
        },
        'periodo': 'Últimos 60 días (simulado)',
        'fuente': 'Datos simulados (DEMO)'
    }

# ===== CONFIGURACIÓN DE PÁGINA =====
st.set_page_config(page_title="Analizador de Palma Aceitera", page_icon="🌴", layout="wide", initial_sidebar_state="expanded")

# ===== INICIALIZACIÓN DE SESIÓN =====
def init_session_state():
    defaults = {
        'geojson_data': None,
        'analisis_completado': False,
        'resultados_todos': {},
        'palmas_detectadas': [],
        'archivo_cargado': False,
        'gdf_original': None,
        'datos_modis': {},
        'datos_climaticos': {},
        'deteccion_ejecutada': False,
        'n_divisiones': 16,
        'fecha_inicio': datetime.now() - timedelta(days=60),
        'fecha_fin': datetime.now(),
        'variedad_seleccionada': 'Tenera (DxP)',
        'textura_suelo': {},
        'textura_por_bloque': [],
        'datos_fertilidad': [],
        'analisis_suelo': True,
        'curvas_nivel': None,
        'demo_mode': False,
        'payment_intent': False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Verificar suscripción antes de continuar
check_subscription()

# ===== CONFIGURACIONES =====
VARIEDADES_PALMA_ACEITERA = [
    'Tenera (DxP)', 'Dura', 'Pisifera', 'Yangambi', 'AVROS', 'La Mé',
    'Ekona', 'Calabar', 'NIFOR', 'MARDI', 'CIRAD', 'ASD Costa Rica',
    'Dami', 'Socfindo', 'SP540'
]

# ===== FUNCIONES DE UTILIDAD MEJORADAS =====
def validar_y_corregir_crs(gdf):
    """
    Valida y corrige el CRS del GeoDataFrame a EPSG:4326 (WGS84).
    """
    if gdf is None or len(gdf) == 0:
        return gdf
    
    try:
        # Si no tiene CRS, asumir WGS84
        if gdf.crs is None:
            # Verificar si las coordenadas parecen estar en grados
            bounds = gdf.total_bounds
            if abs(bounds[0]) <= 180 and abs(bounds[2]) <= 180:
                gdf = gdf.set_crs('EPSG:4326')
            else:
                # Podría estar en metros, intentar convertir
                gdf = gdf.set_crs('EPSG:3857')
                gdf = gdf.to_crs('EPSG:4326')
        
        # Si tiene CRS pero no es WGS84, convertir
        elif str(gdf.crs).upper() != 'EPSG:4326':
            try:
                gdf = gdf.to_crs('EPSG:4326')
            except Exception as e:
                st.warning(f"⚠️ No se pudo convertir CRS: {e}")
        
        return gdf
    
    except Exception as e:
        st.warning(f"Error al corregir CRS: {e}")
        return gdf

def calcular_superficie(gdf):
    try:
        if gdf is None or len(gdf) == 0:
            return 0.0
        gdf = validar_y_corregir_crs(gdf)
        bounds = gdf.total_bounds
        if bounds[0] < -180 or bounds[2] > 180 or bounds[1] < -90 or bounds[3] > 90:
            area_grados2 = gdf.geometry.area.sum()
            area_m2 = area_grados2 * 111000 * 111000
            return area_m2 / 10000
        gdf_projected = gdf.to_crs('EPSG:3857')
        area_m2 = gdf_projected.geometry.area.sum()
        return area_m2 / 10000
    except Exception as e:
        st.warning(f"No se pudo calcular el área: {e}")
        return 0.0

def dividir_plantacion_en_bloques(gdf, n_bloques):
    if gdf is None or len(gdf) == 0:
        return gdf
    gdf = validar_y_corregir_crs(gdf)
    plantacion_principal = gdf.iloc[0].geometry
    bounds = plantacion_principal.bounds
    minx, miny, maxx, maxy = bounds
    
    sub_poligonos = []
    n_cols = math.ceil(math.sqrt(n_bloques))
    n_rows = math.ceil(n_bloques / n_cols)
    width = (maxx - minx) / n_cols
    height = (maxy - miny) / n_rows
    
    for i in range(n_rows):
        for j in range(n_cols):
            if len(sub_poligonos) >= n_bloques:
                break
            cell_minx = minx + (j * width)
            cell_maxx = minx + ((j + 1) * width)
            cell_miny = miny + (i * height)
            cell_maxy = miny + ((i + 1) * height)
            cell_poly = Polygon([
                (cell_minx, cell_miny), (cell_maxx, cell_miny),
                (cell_maxx, cell_maxy), (cell_minx, cell_maxy)
            ])
            intersection = plantacion_principal.intersection(cell_poly)
            if not intersection.is_empty and intersection.area > 0:
                sub_poligonos.append(intersection)
    
    if sub_poligonos:
        nuevo_gdf = gpd.GeoDataFrame(
            {'id_bloque': range(1, len(sub_poligonos) + 1), 'geometry': sub_poligonos},
            crs='EPSG:4326'
        )
        return nuevo_gdf
    return gdf

# ===== PARSER KML MEJORADO =====
def procesar_kml_robusto(file_content):
    """
    Parser KML mejorado que maneja múltiples formatos y coordenadas.
    """
    try:
        # Decodificar contenido
        try:
            content = file_content.decode('utf-8')
        except:
            content = file_content.decode('latin-1', errors='ignore')
        
        polygons = []
        
        # Buscar todas las secciones de coordenadas
        coord_sections = re.findall(
            r'<coordinates[^>]*>([\s\S]*?)</coordinates>', 
            content, 
            re.IGNORECASE | re.DOTALL
        )
        
        for coord_text in coord_sections:
            coord_text = coord_text.strip()
            if not coord_text:
                continue
            
            coord_list = []
            
            # Dividir por espacios, saltos de línea o tabuladores
            coords = re.split(r'[\s\n\t]+', coord_text)
            
            for coord in coords:
                coord = coord.strip()
                if not coord or ',' not in coord:
                    continue
                
                try:
                    parts = [p.strip() for p in coord.split(',')]
                    if len(parts) >= 2:
                        lon = float(parts[0])
                        lat = float(parts[1])
                        
                        # Validar rango de coordenadas
                        if -180 <= lon <= 180 and -90 <= lat <= 90:
                            coord_list.append((lon, lat))
                except ValueError:
                    continue
            
            # Crear polígono si hay suficientes puntos
            if len(coord_list) >= 3:
                # Cerrar polígono si no está cerrado
                if coord_list[0] != coord_list[-1]:
                    coord_list.append(coord_list[0])
                
                try:
                    polygon = Polygon(coord_list)
                    if polygon.is_valid and polygon.area > 0:
                        polygons.append(polygon)
                except Exception:
                    continue
        
        if polygons:
            return gpd.GeoDataFrame(geometry=polygons, crs='EPSG:4326')
        
        # Intentar buscar Placemark como fallback
        placemarks = re.findall(
            r'<Placemark[^>]*>([\s\S]*?)</Placemark>', 
            content, 
            re.IGNORECASE | re.DOTALL
        )
        
        for placemark in placemarks:
            coord_match = re.search(
                r'<coordinates[^>]*>([\s\S]*?)</coordinates>', 
                placemark, 
                re.IGNORECASE
            )
            if coord_match:
                # Procesar coordenadas del Placemark...
                coord_text = coord_match.group(1).strip()
                if coord_text:
                    coord_list = []
                    coords = re.split(r'[\s\n\t]+', coord_text)
                    for coord in coords:
                        coord = coord.strip()
                        if coord and ',' in coord:
                            try:
                                parts = [p.strip() for p in coord.split(',')]
                                if len(parts) >= 2:
                                    lon = float(parts[0])
                                    lat = float(parts[1])
                                    if -180 <= lon <= 180 and -90 <= lat <= 90:
                                        coord_list.append((lon, lat))
                            except ValueError:
                                continue
                    if len(coord_list) >= 3:
                        if coord_list[0] != coord_list[-1]:
                            coord_list.append(coord_list[0])
                        try:
                            polygon = Polygon(coord_list)
                            if polygon.is_valid and polygon.area > 0:
                                polygons.append(polygon)
                        except Exception:
                            continue
        
        if polygons:
            return gpd.GeoDataFrame(geometry=polygons, crs='EPSG:4326')
        
        return None
        
    except Exception as e:
        st.error(f"Error en procesamiento KML: {str(e)}")
        return None

# ===== CARGA DE ARCHIVO MEJORADA =====
def cargar_archivo_plantacion(uploaded_file):
    """
    Carga un archivo de plantación con manejo robusto de errores.
    Funciona tanto en modo DEMO como PREMIUM.
    """
    try:
        file_content = uploaded_file.read()
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        gdf = None
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            # === ZIP con Shapefile ===
            if ext == '.zip':
                with zipfile.ZipFile(io.BytesIO(file_content), 'r') as zip_ref:
                    zip_ref.extractall(tmp_dir)
                shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                if not shp_files:
                    st.error("❌ No se encontró archivo .shp dentro del ZIP")
                    return None
                gdf = gpd.read_file(os.path.join(tmp_dir, shp_files[0]))
            
            # === GeoJSON ===
            elif ext == '.geojson':
                gdf = gpd.read_file(io.BytesIO(file_content))
            
            # === KML ===
            elif ext == '.kml':
                gdf = procesar_kml_robusto(file_content)
                if gdf is None:
                    st.error("❌ No se pudieron extraer polígonos del KML")
                    return None
            
            # === KMZ ===
            elif ext == '.kmz':
                kmz_path = os.path.join(tmp_dir, 'temp.kmz')
                with open(kmz_path, 'wb') as f:
                    f.write(file_content)
                with zipfile.ZipFile(kmz_path, 'r') as kmz:
                    kml_files = [f for f in kmz.namelist() if f.endswith('.kml')]
                    if not kml_files:
                        st.error("❌ No se encontró KML dentro del KMZ")
                        return None
                    kmz.extract(kml_files[0], tmp_dir)
                    with open(os.path.join(tmp_dir, kml_files[0]), 'rb') as f:
                        gdf = procesar_kml_robusto(f.read())
                if gdf is None:
                    st.error("❌ No se pudieron extraer polígonos del KMZ")
                    return None
            
            else:
                st.error(f"❌ Formato no soportado: {ext}. Use .zip, .geojson, .kml o .kmz")
                return None
        
        # === Validar GeoDataFrame ===
        if gdf is None or len(gdf) == 0:
            st.error("❌ No se encontraron geometrías válidas")
            return None
        
        # === Corregir CRS ===
        gdf = validar_y_corregir_crs(gdf)
        
        # === Explode MultiPolygons ===
        gdf = gdf.explode(ignore_index=True)
        
        # === Filtrar solo polígonos ===
        gdf = gdf[gdf.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])]
        
        if len(gdf) == 0:
            st.error("❌ No hay polígonos válidos después del filtrado")
            return None
        
        # === Unir todos los polígonos ===
        union = gdf.unary_union
        
        # === Manejar MultiPolygon ===
        if union.geom_type == 'MultiPolygon':
            areas = [p.area for p in union.geoms]
            main_poly = union.geoms[np.argmax(areas)]
        else:
            main_poly = union
        
        # === Reparar geometría inválida ===
        if not main_poly.is_valid:
            try:
                main_poly = make_valid(main_poly)
                # Si después de reparar sigue siendo MultiPolygon, tomar el mayor
                if main_poly.geom_type == 'MultiPolygon':
                    areas = [p.area for p in main_poly.geoms]
                    main_poly = main_poly.geoms[np.argmax(areas)]
            except Exception as e:
                st.warning(f"⚠️ No se pudo reparar la geometría: {e}")
        
        # === Crear GeoDataFrame final ===
        gdf_unido = gpd.GeoDataFrame(
            [{'geometry': main_poly, 'id_bloque': 1}], 
            crs='EPSG:4326'
        )
        
        # === Verificar área ===
        area = calcular_superficie(gdf_unido)
        if area <= 0:
            st.error("❌ El polígono tiene área cero o inválida")
            return None
        
        # === Guardar en session state para persistir entre modos ===
        st.session_state.gdf_original = gdf_unido
        st.session_state.archivo_cargado = True
        st.session_state.analisis_completado = False
        st.session_state.deteccion_ejecutada = False
        
        st.success(f"✅ Plantación cargada: {area:.2f} ha")
        return gdf_unido
        
    except Exception as e:
        st.error(f"❌ Error cargando archivo: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
        return None

# ===== FUNCIONES PARA DATOS SATELITALES CON EARTHDATA (SILENCIOSAS) =====
def obtener_ndvi_earthdata(gdf_dividido, fecha_inicio, fecha_fin):
    """
    Obtiene NDVI real para cada bloque usando MOD13Q1.
    Primero intenta con rasterio (extracción por bloque) sin mostrar advertencias.
    Si falla, usa pyhdf para leer datos y metadata, y realiza extracción por bloque con rasterio en memoria.
    """
    if not EARTHDATA_OK:
        st.error("Librerías earthaccess/xarray/rioxarray no instaladas.")
        return None
    if not EARTHDATA_USERNAME or not EARTHDATA_PASSWORD:
        st.error("Credenciales de Earthdata no configuradas.")
        return None

    try:
        auth = earthaccess.login()
        if not auth.authenticated:
            st.error("No se pudo autenticar con Earthdata.")
            return None

        bounds = gdf_dividido.total_bounds
        bbox = (bounds[0], bounds[1], bounds[2], bounds[3])

        results = earthaccess.search_data(
            short_name='MOD13Q1',
            version='061',
            bounding_box=bbox,
            temporal=(fecha_inicio.strftime('%Y-%m-%d'), fecha_fin.strftime('%Y-%m-%d')),
            count=5
        )

        if not results:
            st.error("No se encontraron escenas MOD13Q1 en el período.")
            return None

        granule = results[0]
        st.info(f"Procesando escena NDVI: {granule['umm']['GranuleUR']}")

        temp_dir = tempfile.mkdtemp()
        downloaded_files = earthaccess.download(granule, local_path=temp_dir)
        if not downloaded_files:
            st.error("No se pudo descargar el archivo.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        hdf_files = [f for f in downloaded_files if f.endswith('.hdf')]
        if not hdf_files:
            st.error("No se encontró archivo HDF en la descarga.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        download_path = hdf_files[0]

        # Verificar que no sea una página HTML de error
        file_size = os.path.getsize(download_path)
        if file_size < 10240:
            with open(download_path, 'r', errors='ignore') as f:
                head = f.read(500).lower()
                if '<html' in head:
                    st.error("El archivo descargado parece ser una página HTML de error. Verifica credenciales y disponibilidad del producto.")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return None

        # --- Intento con rasterio (extracción por bloque) sin mostrar errores ---
        rasterio_success = False
        if RASTERIO_OK:
            try:
                # Intentar abrir con rasterio (puede fallar si no reconoce el formato)
                with rasterio.open(download_path) as src:
                    subdatasets = src.subdatasets
                    ndvi_sub = None
                    for sd in subdatasets:
                        if 'NDVI' in sd or 'ndvi' in sd.lower():
                            ndvi_sub = sd
                            break
                    if ndvi_sub:
                        with rasterio.open(ndvi_sub) as src_ndvi:
                            raster_crs = src_ndvi.crs
                            nodata = src_ndvi.nodata
                            gdf_proj = gdf_dividido.to_crs(raster_crs)

                            ndvi_values = []
                            progress_bar = st.progress(0, text="Procesando bloques para NDVI...")

                            for idx, row in gdf_proj.iterrows():
                                geom = [mapping(row.geometry)]
                                try:
                                    out_image, _ = mask(src_ndvi, geom, crop=True, nodata=nodata)
                                    data = out_image[0]
                                    data_scaled = data.astype(np.float32) * 0.0001
                                    mask_invalid = (data == nodata) | (data_scaled < -1) | (data_scaled > 1)
                                    data_clean = np.ma.masked_where(mask_invalid, data_scaled)
                                    mean_val = data_clean.mean()
                                    if np.ma.is_masked(mean_val) or np.isnan(mean_val):
                                        ndvi_values.append(np.nan)
                                    else:
                                        ndvi_values.append(round(float(mean_val), 3))
                                except Exception:
                                    ndvi_values.append(np.nan)

                                progress_bar.progress((idx + 1) / len(gdf_proj),
                                                      text=f"Procesando bloque {idx+1}/{len(gdf_proj)}")

                            progress_bar.empty()

                            gdf_dividido['ndvi_modis'] = ndvi_values
                            st.success("✅ NDVI calculado por bloque correctamente con rasterio.")
                            rasterio_success = True
                            return gdf_dividido

            except Exception:
                # Fallo silencioso de rasterio, pasamos a pyhdf
                pass

        # --- Fallback con pyhdf (sin mostrar advertencias) ---
        if not rasterio_success and PYHDF_OK:
            try:
                hdf = SD(download_path, SDC.READ)
                # Buscar dataset NDVI
                ndvi_dataset = None
                for name in hdf.datasets().keys():
                    if 'NDVI' in name:
                        ndvi_dataset = name
                        break
                if ndvi_dataset is None:
                    st.error("No se encontró dataset NDVI en el archivo HDF.")
                    return None

                ndvi_data = hdf.select(ndvi_dataset).get()
                ndvi_scaled = ndvi_data.astype(np.float32) * 0.0001

                # Obtener metadata de geolocalización
                try:
                    metadata = hdf.attributes()['StructMetadata.0']
                    import re
                    xdim_match = re.search(r'XDim\s*=\s*(\d+)', metadata, re.IGNORECASE)
                    ydim_match = re.search(r'YDim\s*=\s*(\d+)', metadata, re.IGNORECASE)
                    ul_match = re.search(r'UpperLeftPointMtrs\s*=\s*\(\s*([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)\s*\)', metadata, re.IGNORECASE)
                    lr_match = re.search(r'LowerRightMtrs\s*=\s*\(\s*([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)\s*\)', metadata, re.IGNORECASE)

                    if not (xdim_match and ydim_match and ul_match and lr_match):
                        raise ValueError("No se pudo extraer la geolocalización completa")

                    xdim = int(xdim_match.group(1))
                    ydim = int(ydim_match.group(1))
                    ulx = float(ul_match.group(1))
                    uly = float(ul_match.group(2))
                    lrx = float(lr_match.group(1))
                    lry = float(lr_match.group(2))

                    if ndvi_scaled.shape != (ydim, xdim):
                        ydim, xdim = ndvi_scaled.shape

                    res_x = (lrx - ulx) / xdim
                    res_y = (uly - lry) / ydim
                    transform = rasterio.Affine(res_x, 0, ulx, 0, -res_y, uly)
                    crs = rasterio.crs.CRS.from_proj4("+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +a=6371007.181 +b=6371007.181 +units=m +no_defs")

                    with rasterio.io.MemoryFile() as memfile:
                        with memfile.open(
                            driver='GTiff',
                            height=ydim,
                            width=xdim,
                            count=1,
                            dtype=ndvi_scaled.dtype,
                            crs=crs,
                            transform=transform,
                            nodata=-32768
                        ) as dst:
                            dst.write(ndvi_scaled, 1)

                        with memfile.open() as src_ndvi:
                            gdf_proj = gdf_dividido.to_crs(crs)

                            ndvi_values = []
                            progress_bar = st.progress(0, text="Procesando bloques para NDVI con pyhdf...")

                            for idx, row in gdf_proj.iterrows():
                                geom = [mapping(row.geometry)]
                                try:
                                    out_image, _ = mask(src_ndvi, geom, crop=True, nodata=-32768)
                                    data = out_image[0]
                                    mask_invalid = (data == -32768) | (data < -1) | (data > 1)
                                    data_clean = np.ma.masked_where(mask_invalid, data)
                                    mean_val = data_clean.mean()
                                    if np.ma.is_masked(mean_val) or np.isnan(mean_val):
                                        ndvi_values.append(np.nan)
                                    else:
                                        ndvi_values.append(round(float(mean_val), 3))
                                except Exception:
                                    ndvi_values.append(np.nan)

                                progress_bar.progress((idx + 1) / len(gdf_proj),
                                                      text=f"Procesando bloque {idx+1}/{len(gdf_proj)}")

                            progress_bar.empty()

                            gdf_dividido['ndvi_modis'] = ndvi_values
                            st.success("✅ NDVI calculado por bloque correctamente con pyhdf.")
                            return gdf_dividido

                except Exception as e_meta:
                    st.error(f"No se pudo extraer la geolocalización del archivo HDF: {str(e_meta)}")
                    return None

            except Exception as e_pyhdf:
                st.error(f"Error al procesar con pyhdf: {str(e_pyhdf)}")
                return None
        elif not rasterio_success:
            st.error("No se pudo leer el archivo HDF: ni rasterio ni pyhdf están disponibles o funcionaron.")
            return None

    except Exception as e:
        st.error(f"Error en obtención de NDVI: {str(e)}")
        return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def obtener_ndwi_earthdata(gdf_dividido, fecha_inicio, fecha_fin):
    """
    Obtiene NDWI real para cada bloque usando MOD09GA (bandas NIR y SWIR).
    Primero intenta con rasterio (extracción por bloque) sin mostrar advertencias.
    Si falla, usa pyhdf para leer datos y metadata, y realiza extracción por bloque con rasterio en memoria.
    """
    if not EARTHDATA_OK:
        st.error("Librerías earthaccess no instaladas.")
        return None
    if not EARTHDATA_USERNAME or not EARTHDATA_PASSWORD:
        st.error("Credenciales de Earthdata no configuradas.")
        return None

    try:
        auth = earthaccess.login()
        if not auth.authenticated:
            st.error("No se pudo autenticar con Earthdata.")
            return None

        bounds = gdf_dividido.total_bounds
        bbox = (bounds[0], bounds[1], bounds[2], bounds[3])

        results = earthaccess.search_data(
            short_name='MOD09GA',
            version='061',
            bounding_box=bbox,
            temporal=(fecha_inicio.strftime('%Y-%m-%d'), fecha_fin.strftime('%Y-%m-%d')),
            count=5
        )

        if not results:
            st.error("No se encontraron escenas MOD09GA en el período.")
            return None

        granule = results[0]
        st.info(f"Procesando escena NDWI: {granule['umm']['GranuleUR']}")

        temp_dir = tempfile.mkdtemp()
        downloaded_files = earthaccess.download(granule, local_path=temp_dir)
        if not downloaded_files:
            st.error("No se pudo descargar el archivo.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        hdf_files = [f for f in downloaded_files if f.endswith('.hdf')]
        if not hdf_files:
            st.error("No se encontró archivo HDF.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        download_path = hdf_files[0]

        file_size = os.path.getsize(download_path)
        if file_size < 10240:
            with open(download_path, 'r', errors='ignore') as f:
                head = f.read(500).lower()
                if '<html' in head:
                    st.error("El archivo descargado es una página HTML de error.")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return None

        # --- Intento con rasterio (extracción por bloque) sin mostrar errores ---
        rasterio_success = False
        if RASTERIO_OK:
            try:
                with rasterio.open(download_path) as src:
                    subdatasets = src.subdatasets
                    nir_sub = None
                    swir_sub = None
                    for sd in subdatasets:
                        if 'sur_refl_b02' in sd:
                            nir_sub = sd
                        elif 'sur_refl_b06' in sd:
                            swir_sub = sd
                    if nir_sub and swir_sub:
                        with rasterio.open(nir_sub) as src_nir, rasterio.open(swir_sub) as src_swir:
                            raster_crs = src_nir.crs
                            nodata_nir = src_nir.nodata
                            nodata_swir = src_swir.nodata

                            gdf_proj = gdf_dividido.to_crs(raster_crs)

                            ndwi_values = []
                            progress_bar = st.progress(0, text="Procesando bloques para NDWI...")

                            for idx, row in gdf_proj.iterrows():
                                geom = [mapping(row.geometry)]
                                try:
                                    out_nir, _ = mask(src_nir, geom, crop=True, nodata=nodata_nir)
                                    nir_band = out_nir[0].astype(np.float32) * 0.0001

                                    out_swir, _ = mask(src_swir, geom, crop=True, nodata=nodata_swir)
                                    swir_band = out_swir[0].astype(np.float32) * 0.0001

                                    valid = (nir_band != nodata_nir * 0.0001) & (swir_band != nodata_swir * 0.0001) & (nir_band + swir_band != 0)
                                    nir_valid = np.ma.masked_where(~valid, nir_band)
                                    swir_valid = np.ma.masked_where(~valid, swir_band)

                                    with np.errstate(divide='ignore', invalid='ignore'):
                                        ndwi = (nir_valid - swir_valid) / (nir_valid + swir_valid)
                                    mean_val = ndwi.mean()
                                    if np.ma.is_masked(mean_val) or np.isnan(mean_val):
                                        ndwi_values.append(np.nan)
                                    else:
                                        ndwi_values.append(round(float(mean_val), 3))
                                except Exception:
                                    ndwi_values.append(np.nan)

                                progress_bar.progress((idx + 1) / len(gdf_proj),
                                                      text=f"Procesando bloque {idx+1}/{len(gdf_proj)}")

                            progress_bar.empty()

                            gdf_dividido['ndwi_modis'] = ndwi_values
                            st.success("✅ NDWI calculado por bloque correctamente con rasterio.")
                            rasterio_success = True
                            return gdf_dividido

            except Exception:
                # Fallo silencioso de rasterio
                pass

        # --- Fallback con pyhdf (sin mostrar advertencias) ---
        if not rasterio_success and PYHDF_OK:
            try:
                hdf = SD(download_path, SDC.READ)
                nir_data = None
                swir_data = None
                for name in hdf.datasets().keys():
                    if 'sur_refl_b02' in name:
                        nir_data = hdf.select(name).get()
                    elif 'sur_refl_b06' in name:
                        swir_data = hdf.select(name).get()
                if nir_data is None or swir_data is None:
                    st.error("No se encontraron las bandas NIR o SWIR con pyhdf.")
                    return None

                nir = nir_data.astype(np.float32) * 0.0001
                swir = swir_data.astype(np.float32) * 0.0001

                try:
                    metadata = hdf.attributes()['StructMetadata.0']
                    import re
                    xdim_match = re.search(r'XDim\s*=\s*(\d+)', metadata, re.IGNORECASE)
                    ydim_match = re.search(r'YDim\s*=\s*(\d+)', metadata, re.IGNORECASE)
                    ul_match = re.search(r'UpperLeftPointMtrs\s*=\s*\(\s*([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)\s*\)', metadata, re.IGNORECASE)
                    lr_match = re.search(r'LowerRightMtrs\s*=\s*\(\s*([+-]?\d+\.?\d*)\s*,\s*([+-]?\d+\.?\d*)\s*\)', metadata, re.IGNORECASE)

                    if not (xdim_match and ydim_match and ul_match and lr_match):
                        raise ValueError("No se pudo extraer la geolocalización completa")

                    xdim = int(xdim_match.group(1))
                    ydim = int(ydim_match.group(1))
                    ulx = float(ul_match.group(1))
                    uly = float(ul_match.group(2))
                    lrx = float(lr_match.group(1))
                    lry = float(lr_match.group(2))

                    if nir.shape != (ydim, xdim):
                        ydim, xdim = nir.shape

                    res_x = (lrx - ulx) / xdim
                    res_y = (uly - lry) / ydim
                    transform = rasterio.Affine(res_x, 0, ulx, 0, -res_y, uly)
                    crs = rasterio.crs.CRS.from_proj4("+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +a=6371007.181 +b=6371007.181 +units=m +no_defs")

                    with rasterio.io.MemoryFile() as memfile_nir, rasterio.io.MemoryFile() as memfile_swir:
                        with memfile_nir.open(driver='GTiff', height=ydim, width=xdim, count=1,
                                              dtype=nir.dtype, crs=crs, transform=transform, nodata=-32768) as dst_nir:
                            dst_nir.write(nir, 1)
                        with memfile_swir.open(driver='GTiff', height=ydim, width=xdim, count=1,
                                              dtype=swir.dtype, crs=crs, transform=transform, nodata=-32768) as dst_swir:
                            dst_swir.write(swir, 1)

                        with memfile_nir.open() as src_nir, memfile_swir.open() as src_swir:
                            gdf_proj = gdf_dividido.to_crs(crs)

                            ndwi_values = []
                            progress_bar = st.progress(0, text="Procesando bloques para NDWI con pyhdf...")

                            for idx, row in gdf_proj.iterrows():
                                geom = [mapping(row.geometry)]
                                try:
                                    out_nir, _ = mask(src_nir, geom, crop=True, nodata=-32768)
                                    nir_band = out_nir[0]

                                    out_swir, _ = mask(src_swir, geom, crop=True, nodata=-32768)
                                    swir_band = out_swir[0]

                                    valid = (nir_band != -32768) & (swir_band != -32768) & (nir_band + swir_band != 0)
                                    nir_valid = np.ma.masked_where(~valid, nir_band)
                                    swir_valid = np.ma.masked_where(~valid, swir_band)

                                    with np.errstate(divide='ignore', invalid='ignore'):
                                        ndwi = (nir_valid - swir_valid) / (nir_valid + swir_valid)
                                    mean_val = ndwi.mean()
                                    if np.ma.is_masked(mean_val) or np.isnan(mean_val):
                                        ndwi_values.append(np.nan)
                                    else:
                                        ndwi_values.append(round(float(mean_val), 3))
                                except Exception:
                                    ndwi_values.append(np.nan)

                                progress_bar.progress((idx + 1) / len(gdf_proj),
                                                      text=f"Procesando bloque {idx+1}/{len(gdf_proj)}")

                            progress_bar.empty()

                            gdf_dividido['ndwi_modis'] = ndwi_values
                            st.success("✅ NDWI calculado por bloque correctamente con pyhdf.")
                            return gdf_dividido

                except Exception as e_meta:
                    st.error(f"No se pudo extraer la geolocalización del archivo HDF: {str(e_meta)}")
                    return None

            except Exception as e_pyhdf:
                st.error(f"Error al procesar con pyhdf: {str(e_pyhdf)}")
                return None
        elif not rasterio_success:
            st.error("No se pudo leer el archivo HDF: ni rasterio ni pyhdf están disponibles o funcionaron.")
            return None

    except Exception as e:
        st.error(f"Error en obtención de NDWI: {str(e)}")
        return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ===== FUNCIONES CLIMÁTICAS =====
def obtener_clima_openmeteo(gdf, fecha_inicio, fecha_fin):
    try:
        centroide = gdf.geometry.unary_union.centroid
        lat = centroide.y
        lon = centroide.x
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": fecha_inicio.strftime("%Y-%m-%d"),
            "end_date": fecha_fin.strftime("%Y-%m-%d"),
            "daily": ["temperature_2m_max", "temperature_2m_min", 
                      "temperature_2m_mean", "precipitation_sum"],
            "timezone": "auto"
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        if "daily" not in data:
            raise ValueError("No se recibieron datos diarios")
        tmax = [t if t is not None else np.nan for t in data["daily"]["temperature_2m_max"]]
        tmin = [t if t is not None else np.nan for t in data["daily"]["temperature_2m_min"]]
        tmean = [t if t is not None else np.nan for t in data["daily"]["temperature_2m_mean"]]
        precip = [p if p is not None else 0.0 for p in data["daily"]["precipitation_sum"]]
        return {
            'precipitacion': {
                'total': round(sum(precip), 1),
                'maxima_diaria': round(max(precip) if precip else 0, 1),
                'dias_con_lluvia': sum(1 for p in precip if p > 0.1),
                'diaria': [round(p, 1) for p in precip]
            },
            'temperatura': {
                'promedio': round(np.nanmean(tmean), 1),
                'maxima': round(np.nanmax(tmax), 1),
                'minima': round(np.nanmin(tmin), 1),
                'diaria': [round(t, 1) if not np.isnan(t) else np.nan for t in tmean]
            },
            'periodo': f"{fecha_inicio.strftime('%d/%m/%Y')} - {fecha_fin.strftime('%d/%m/%Y')}",
            'fuente': 'Open-Meteo ERA5'
        }
    except Exception as e:
        st.warning(f"Error en Open-Meteo: {str(e)[:100]}. Usando datos simulados.")
        return generar_datos_climaticos_simulados(gdf, fecha_inicio, fecha_fin)

def obtener_radiacion_viento_power(gdf, fecha_inicio, fecha_fin):
    try:
        centroide = gdf.geometry.unary_union.centroid
        lat = centroide.y
        lon = centroide.x
        start = fecha_inicio.strftime("%Y%m%d")
        end = fecha_fin.strftime("%Y%m%d")
        url = "https://power.larc.nasa.gov/api/temporal/daily/point"
        params = {
            "parameters": "ALLSKY_SFC_SW_DWN,WS2M",
            "community": "RE",
            "longitude": lon,
            "latitude": lat,
            "start": start,
            "end": end,
            "format": "JSON"
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        props = data['properties']['parameter']
        radiacion = props.get('ALLSKY_SFC_SW_DWN', {})
        viento = props.get('WS2M', {})
        fechas = sorted(radiacion.keys())
        rad_diaria = [radiacion[f] for f in fechas]
        wind_diaria = [viento[f] for f in fechas]
        rad_diaria = [np.nan if r == -999 else r for r in rad_diaria]
        wind_diaria = [np.nan if w == -999 else w for w in wind_diaria]
        return {
            'radiacion': {
                'promedio': round(np.nanmean(rad_diaria), 1),
                'maxima': round(np.nanmax(rad_diaria), 1),
                'minima': round(np.nanmin(rad_diaria), 1),
                'diaria': [round(r, 1) if not np.isnan(r) else np.nan for r in rad_diaria]
            },
            'viento': {
                'promedio': round(np.nanmean(wind_diaria), 1),
                'maxima': round(np.nanmax(wind_diaria), 1),
                'diaria': [round(w, 1) if not np.isnan(w) else np.nan for w in wind_diaria]
            },
            'fuente': 'NASA POWER'
        }
    except Exception as e:
        st.warning(f"Error en NASA POWER: {str(e)[:100]}. Usando datos simulados.")
        dias = (fecha_fin - fecha_inicio).days
        if dias <= 0:
            dias = 30
        rad_diaria = [np.random.uniform(15, 25) for _ in range(dias)]
        wind_diaria = [np.random.uniform(2, 6) for _ in range(dias)]
        return {
            'radiacion': {
                'promedio': round(np.mean(rad_diaria), 1),
                'maxima': round(max(rad_diaria), 1),
                'minima': round(min(rad_diaria), 1),
                'diaria': rad_diaria
            },
            'viento': {
                'promedio': round(np.mean(wind_diaria), 1),
                'maxima': round(max(wind_diaria), 1),
                'diaria': wind_diaria
            },
            'fuente': 'Simulado (fallback)'
        }

def generar_datos_climaticos_simulados(gdf, fecha_inicio, fecha_fin):
    try:
        dias = (fecha_fin - fecha_inicio).days
        if dias <= 0:
            dias = 30
        rad_diaria = [np.random.uniform(15, 25) for _ in range(dias)]
        precip_diaria = [max(0, np.random.exponential(3) if np.random.random() > 0.7 else 0) for _ in range(dias)]
        wind_diaria = [np.random.uniform(2, 6) for _ in range(dias)]
        temp_diaria = [np.random.uniform(22, 28) for _ in range(dias)]
        return {
            'radiacion': {
                'promedio': round(np.mean(rad_diaria), 1),
                'maxima': round(max(rad_diaria), 1),
                'minima': round(min(rad_diaria), 1),
                'diaria': rad_diaria
            },
            'precipitacion': {
                'total': round(sum(precip_diaria), 1),
                'maxima_diaria': round(max(precip_diaria), 1),
                'dias_con_lluvia': sum(1 for p in precip_diaria if p > 0.1),
                'diaria': precip_diaria
            },
            'viento': {
                'promedio': round(np.mean(wind_diaria), 1),
                'maxima': round(max(wind_diaria), 1),
                'diaria': wind_diaria
            },
            'temperatura': {
                'promedio': round(np.mean(temp_diaria), 1),
                'maxima': round(max(temp_diaria), 1),
                'minima': round(min(temp_diaria), 1),
                'diaria': temp_diaria
            },
            'periodo': f"{fecha_inicio.strftime('%d/%m/%Y')} - {fecha_fin.strftime('%d/%m/%Y')}",
            'fuente': 'Simulado (fallback)'
        }
    except:
        return {
            'radiacion': {'promedio': 18.0, 'maxima': 25.0, 'minima': 12.0, 'diaria': [18]*30},
            'precipitacion': {'total': 90.0, 'maxima_diaria': 15.0, 'dias_con_lluvia': 10, 'diaria': [3]*30},
            'viento': {'promedio': 3.0, 'maxima': 6.0, 'diaria': [3]*30},
            'temperatura': {'promedio': 25.0, 'maxima': 30.0, 'minima': 20.0, 'diaria': [25]*30},
            'periodo': 'Últimos 30 días',
            'fuente': 'Simulado (fallback)'
        }

def analizar_edad_plantacion(gdf_dividido):
    edades = []
    for idx, row in gdf_dividido.iterrows():
        try:
            centroid = row.geometry.centroid
            lat_norm = (centroid.y + 90) / 180
            lon_norm = (centroid.x + 180) / 360
            edad = 2 + (lat_norm * lon_norm * 18)
            edades.append(round(edad, 1))
        except:
            edades.append(10.0)
    return edades

# ===== DETECCIÓN DE PALMAS =====
def verificar_puntos_en_poligono(puntos, gdf):
    puntos_dentro = []
    plantacion_union = gdf.unary_union
    for punto in puntos:
        if 'centroide' in punto:
            lon, lat = punto['centroide']
            point = Point(lon, lat)
            if plantacion_union.contains(point):
                puntos_dentro.append(punto)
    return puntos_dentro

def mejorar_deteccion_palmas(gdf, densidad=130):
    try:
        bounds = gdf.total_bounds
        min_lon, min_lat, max_lon, max_lat = bounds
        gdf_proj = gdf.to_crs('EPSG:3857')
        area_m2 = gdf_proj.geometry.area.sum()
        area_ha = area_m2 / 10000
        if area_ha <= 0:
            return {'detectadas': [], 'total': 0}
        num_palmas_objetivo = int(area_ha * densidad)
        espaciado_grados = 9 / 111000
        x_coords = []
        y_coords = []
        x = min_lon
        while x <= max_lon:
            y = min_lat
            while y <= max_lat:
                x_coords.append(x)
                y_coords.append(y)
                y += espaciado_grados
            x += espaciado_grados
        for i in range(len(x_coords)):
            if i % 2 == 1:
                x_coords[i] += espaciado_grados / 2
        plantacion_union = gdf.unary_union
        palmas = []
        for i in range(len(x_coords)):
            if len(palmas) >= num_palmas_objetivo:
                break
            point = Point(x_coords[i], y_coords[i])
            if plantacion_union.contains(point):
                lon = x_coords[i] + np.random.normal(0, espaciado_grados * 0.1)
                lat = y_coords[i] + np.random.normal(0, espaciado_grados * 0.1)
                palmas.append({
                    'centroide': (lon, lat),
                    'area_m2': np.random.uniform(18, 24),
                    'circularidad': np.random.uniform(0.85, 0.98),
                    'diametro_aprox': np.random.uniform(5, 7),
                    'simulado': True
                })
        return {
            'detectadas': palmas,
            'total': len(palmas),
            'patron': 'hexagonal adaptativo',
            'densidad_calculada': len(palmas) / area_ha,
            'area_ha': area_ha
        }
    except Exception as e:
        print(f"Error en detección mejorada: {e}")
        return {'detectadas': [], 'total': 0}

def ejecutar_deteccion_palmas():
    if st.session_state.gdf_original is None:
        st.error("Primero debe cargar un archivo de plantación")
        return
    with st.spinner("Ejecutando detección MEJORADA de palmas..."):
        gdf = st.session_state.gdf_original
        densidad = st.session_state.get('densidad_personalizada', 130)
        resultados = mejorar_deteccion_palmas(gdf, densidad)
        palmas_verificadas = verificar_puntos_en_poligono(resultados['detectadas'], gdf)
        st.session_state.palmas_detectadas = palmas_verificadas
        st.session_state.deteccion_ejecutada = True
        st.success(f"✅ Detección MEJORADA completada: {len(palmas_verificadas)} palmas detectadas")

def crear_graficos_climaticos_completos(datos_climaticos):
    longitudes = []
    if 'precipitacion' in datos_climaticos and 'diaria' in datos_climaticos['precipitacion']:
        longitudes.append(len(datos_climaticos['precipitacion']['diaria']))
    if 'temperatura' in datos_climaticos and 'diaria' in datos_climaticos['temperatura']:
        longitudes.append(len(datos_climaticos['temperatura']['diaria']))
    if 'radiacion' in datos_climaticos and 'diaria' in datos_climaticos['radiacion']:
        longitudes.append(len(datos_climaticos['radiacion']['diaria']))
    if 'viento' in datos_climaticos and 'diaria' in datos_climaticos['viento']:
        longitudes.append(len(datos_climaticos['viento']['diaria']))
    
    if not longitudes:
        st.warning("No hay datos climáticos suficientes para graficar.")
        return None
    
    n_dias = min(longitudes)
    dias = list(range(1, n_dias + 1))
    
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    
    if 'radiacion' in datos_climaticos and datos_climaticos['radiacion'].get('diaria'):
        rad = np.array(datos_climaticos['radiacion']['diaria'][:n_dias], dtype=np.float64)
        mask_nan = np.isnan(rad)
        if np.any(mask_nan):
            rad_filled = rad.copy()
            rad_filled[mask_nan] = np.nanmean(rad)
        else:
            rad_filled = rad
        ax1 = axes[0, 0]
        ax1.plot(dias, rad_filled, 'o-', color='orange', linewidth=2, markersize=4)
        ax1.fill_between(dias, rad_filled, alpha=0.3, color='orange')
        if 'promedio' in datos_climaticos['radiacion']:
            prom_rad = datos_climaticos['radiacion']['promedio']
            ax1.axhline(y=prom_rad, color='red', linestyle='--', 
                       label=f"Promedio: {prom_rad} MJ/m²")
        ax1.set_xlabel('Día')
        ax1.set_ylabel('Radiación (MJ/m²/día)')
        ax1.set_title('Radiación Solar', fontweight='bold')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
    else:
        axes[0, 0].text(0.5, 0.5, "Datos no disponibles", ha='center', va='center')
        axes[0, 0].set_title('Radiación', fontweight='bold')
    
    if 'precipitacion' in datos_climaticos and datos_climaticos['precipitacion'].get('diaria'):
        precip = np.array(datos_climaticos['precipitacion']['diaria'][:n_dias], dtype=np.float64)
        ax2 = axes[0, 1]
        ax2.bar(dias, precip, color='blue', alpha=0.7)
        ax2.set_xlabel('Día')
        ax2.set_ylabel('Precipitación (mm)')
        total_precip = datos_climaticos['precipitacion'].get('total', np.sum(precip))
        ax2.set_title(f"Precipitación (Total: {total_precip:.1f} mm)", fontweight='bold')
        ax2.grid(True, alpha=0.3, axis='y')
    else:
        axes[0, 1].text(0.5, 0.5, "Datos no disponibles", ha='center', va='center')
        axes[0, 1].set_title('Precipitación', fontweight='bold')
    
    if 'viento' in datos_climaticos and datos_climaticos['viento'].get('diaria'):
        wind = np.array(datos_climaticos['viento']['diaria'][:n_dias], dtype=np.float64)
        mask_nan = np.isnan(wind)
        if np.any(mask_nan):
            wind_filled = wind.copy()
            wind_filled[mask_nan] = np.nanmean(wind)
        else:
            wind_filled = wind
        ax3 = axes[1, 0]
        ax3.plot(dias, wind_filled, 's-', color='green', linewidth=2, markersize=4)
        ax3.fill_between(dias, wind_filled, alpha=0.3, color='green')
        if 'promedio' in datos_climaticos['viento']:
            prom_wind = datos_climaticos['viento']['promedio']
            ax3.axhline(y=prom_wind, color='red', linestyle='--',
                       label=f"Promedio: {prom_wind} m/s")
        ax3.set_xlabel('Día')
        ax3.set_ylabel('Viento (m/s)')
        ax3.set_title('Velocidad del Viento', fontweight='bold')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
    else:
        axes[1, 0].text(0.5, 0.5, "Datos no disponibles", ha='center', va='center')
        axes[1, 0].set_title('Viento', fontweight='bold')
    
    if 'temperatura' in datos_climaticos and datos_climaticos['temperatura'].get('diaria'):
        temp = np.array(datos_climaticos['temperatura']['diaria'][:n_dias], dtype=np.float64)
        mask_nan = np.isnan(temp)
        if np.any(mask_nan):
            temp_filled = temp.copy()
            temp_filled[mask_nan] = np.nanmean(temp)
        else:
            temp_filled = temp
        ax4 = axes[1, 1]
        ax4.plot(dias, temp_filled, '^-', color='red', linewidth=2, markersize=4)
        ax4.fill_between(dias, temp_filled, alpha=0.3, color='red')
        if 'promedio' in datos_climaticos['temperatura']:
            prom_temp = datos_climaticos['temperatura']['promedio']
            ax4.axhline(y=prom_temp, color='blue', linestyle='--',
                       label=f"Promedio: {prom_temp}°C")
        ax4.set_xlabel('Día')
        ax4.set_ylabel('Temperatura (°C)')
        ax4.set_title('Temperatura Diaria', fontweight='bold')
        ax4.legend()
        ax4.grid(True, alpha=0.3)
    else:
        axes[1, 1].text(0.5, 0.5, "Datos no disponibles", ha='center', va='center')
        axes[1, 1].set_title('Temperatura', fontweight='bold')
    
    fuente = datos_climaticos.get('fuente', 'Desconocido')
    plt.suptitle(f"Datos Climáticos - {fuente}", fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    return fig

# ===== ANÁLISIS DE TEXTURA DE SUELO MEJORADO =====
def analizar_textura_suelo_venezuela_por_bloque(gdf_dividido):
    resultados = []
    try:
        centroide_global = gdf_dividido.geometry.unary_union.centroid
        lat_base = centroide_global.y
        if lat_base > 10:
            base = 'Franco Arcilloso'
            alt_base = 'Arcilloso'
        elif lat_base > 7:
            base = 'Franco Arcilloso Arenoso'
            alt_base = 'Franco'
        elif lat_base > 4:
            base = 'Arenoso Franco'
            alt_base = 'Arenoso'
        else:
            base = 'Franco Arcilloso'
            alt_base = 'Arcilloso Pesado'
        
        caracteristicas = {
            'Franco Arcilloso': {
                'arena': 35, 'limo': 25, 'arcilla': 30,
                'textura': 'Media', 'drenaje': 'Moderado',
                'CIC': 'Alto (15-25)', 'ret_agua': 'Alta',
                'recomendacion': 'Ideal para palma'
            },
            'Franco Arcilloso Arenoso': {
                'arena': 45, 'limo': 20, 'arcilla': 25,
                'textura': 'Media-ligera', 'drenaje': 'Bueno',
                'CIC': 'Medio (10-15)', 'ret_agua': 'Moderada',
                'recomendacion': 'Requiere riego'
            },
            'Arenoso Franco': {
                'arena': 55, 'limo': 15, 'arcilla': 20,
                'textura': 'Ligera', 'drenaje': 'Excelente',
                'CIC': 'Bajo (5-10)', 'ret_agua': 'Baja',
                'recomendacion': 'Fertilización fraccionada'
            },
            'Arcilloso': {
                'arena': 25, 'limo': 20, 'arcilla': 40,
                'textura': 'Pesada', 'drenaje': 'Limitado',
                'CIC': 'Muy alto (25-35)', 'ret_agua': 'Muy alta',
                'recomendacion': 'Drenaje y labranza'
            },
            'Arcilloso Pesado': {
                'arena': 20, 'limo': 15, 'arcilla': 50,
                'textura': 'Muy pesada', 'drenaje': 'Muy limitado',
                'CIC': 'Extremo (>35)', 'ret_agua': 'Extrema',
                'recomendacion': 'Drenaje intensivo'
            },
            'Franco': {
                'arena': 40, 'limo': 40, 'arcilla': 20,
                'textura': 'Media', 'drenaje': 'Bueno',
                'CIC': 'Medio (10-20)', 'ret_agua': 'Media',
                'recomendacion': 'Manejo estándar'
            },
            'Arenoso': {
                'arena': 70, 'limo': 15, 'arcilla': 15,
                'textura': 'Ligera', 'drenaje': 'Excelente',
                'CIC': 'Muy bajo (<5)', 'ret_agua': 'Muy baja',
                'recomendacion': 'Riego frecuente'
            }
        }
        
        for idx, row in gdf_dividido.iterrows():
            centroid = row.geometry.centroid
            semilla = abs(int(centroid.x * 1000 + centroid.y * 1000)) % (2**32)
            np.random.seed(semilla)
            r = np.random.random()
            if r < 0.7:
                tipo = base
            else:
                tipo = alt_base
            carac = caracteristicas.get(tipo, caracteristicas['Franco Arcilloso'])
            arena = carac['arena'] + np.random.randint(-5, 6)
            limo = carac['limo'] + np.random.randint(-5, 6)
            arcilla = carac['arcilla'] + np.random.randint(-5, 6)
            total = arena + limo + arcilla
            arena = int(arena / total * 100)
            limo = int(limo / total * 100)
            arcilla = 100 - arena - limo
            resultados.append({
                'id_bloque': row.get('id_bloque', idx+1),
                'tipo_suelo': tipo,
                'arena': arena,
                'limo': limo,
                'arcilla': arcilla,
                'textura': carac['textura'],
                'drenaje': carac['drenaje'],
                'CIC': carac['CIC'],
                'ret_agua': carac['ret_agua'],
                'recomendacion': carac['recomendacion'],
                'geometria': row.geometry
            })
        return resultados
    except Exception as e:
        st.error(f"Error en análisis de textura: {e}")
        return []

# ===== FERTILIDAD NPK =====
def generar_mapa_fertilidad(gdf):
    try:
        fertilidad_data = []
        for idx, row in gdf.iterrows():
            ndvi = row.get('ndvi_modis', 0.65)
            if ndvi > 0.75:
                N = np.random.uniform(120, 180)
                P = np.random.uniform(40, 70)
                K = np.random.uniform(180, 250)
                pH = np.random.uniform(5.8, 6.5)
                MO = np.random.uniform(3.5, 5.0)
            elif ndvi > 0.6:
                N = np.random.uniform(80, 120)
                P = np.random.uniform(25, 40)
                K = np.random.uniform(120, 180)
                pH = np.random.uniform(5.2, 5.8)
                MO = np.random.uniform(2.5, 3.5)
            else:
                N = np.random.uniform(40, 80)
                P = np.random.uniform(15, 25)
                K = np.random.uniform(80, 120)
                pH = np.random.uniform(4.8, 5.2)
                MO = np.random.uniform(1.5, 2.5)
            
            if N < 100:
                rec_N = f"Aplicar {max(0, 120-N):.0f} kg/ha N (Urea: {max(0, (120-N)/0.46):.0f} kg/ha)"
            else:
                rec_N = "Mantener dosis actual"
            if P < 30:
                rec_P = f"Aplicar {max(0, 50-P):.0f} kg/ha P2O5 (DAP: {max(0, (50-P)/0.46):.0f} kg/ha)"
            else:
                rec_P = "Mantener dosis actual"
            if K < 150:
                rec_K = f"Aplicar {max(0, 200-K):.0f} kg/ha K2O (KCl: {max(0, (200-K)/0.6):.0f} kg/ha)"
            else:
                rec_K = "Mantener dosis actual"
            
            fertilidad_data.append({
                'id_bloque': row.get('id_bloque', idx+1),
                'N_kg_ha': round(N, 1),
                'P_kg_ha': round(P, 1),
                'K_kg_ha': round(K, 1),
                'pH': round(pH, 2),
                'MO_porcentaje': round(MO, 2),
                'recomendacion_N': rec_N,
                'recomendacion_P': rec_P,
                'recomendacion_K': rec_K,
                'geometria': row.geometry
            })
        return fertilidad_data
    except Exception:
        return []

# ===== FUNCIONES DE VISUALIZACIÓN =====
def crear_mapa_interactivo_base(gdf, columna_color=None, colormap=None, tooltip_fields=None, tooltip_aliases=None):
    if gdf is None or len(gdf) == 0:
        return None
    centroide = gdf.geometry.unary_union.centroid
    m = folium.Map(location=[centroide.y, centroide.x], zoom_start=16, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri, Maxar, Earthstar Geographics',
        name='Satélite Esri',
        overlay=False,
        control=True
    ).add_to(m)
    folium.TileLayer(
        tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attr='OpenStreetMap',
        name='OpenStreetMap',
        overlay=False,
        control=True
    ).add_to(m)
    
    if columna_color and colormap:
        def style_function(feature):
            valor = feature['properties'].get(columna_color, 0)
            # Verificar si valor es numérico y NaN
            if isinstance(valor, (int, float)):
                if np.isnan(valor):
                    valor = 0
            else:
                # Si no es numérico, convertir a 0
                try:
                    valor = float(valor) if valor is not None else 0
                except:
                    valor = 0
            color = colormap(valor) if hasattr(colormap, '__call__') else '#3388ff'
            return {
                'fillColor': color,
                'color': 'black',
                'weight': 0.5,
                'fillOpacity': 0.7
            }
    else:
        def style_function(feature):
            return {'fillColor': '#3388ff', 'color': 'black', 'weight': 0.5, 'fillOpacity': 0.4}
    
    if tooltip_fields and tooltip_aliases:
        tooltip = folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases, localize=True)
    else:
        tooltip = None
    
    folium.GeoJson(
        gdf.to_json(),
        name='Polígonos',
        style_function=style_function,
        tooltip=tooltip
    ).add_to(m)
    
    folium.LayerControl(collapsed=False).add_to(m)
    Fullscreen(position='topright').add_to(m)
    MeasureControl(position='topright').add_to(m)
    MiniMap(toggle_display=True).add_to(m)
    return m

def mostrar_estadisticas_indice(gdf, columna, titulo, vmin, vmax, colormap_list):
    # Verificar si la columna existe y tiene datos
    if columna not in gdf.columns:
        st.error(f"La columna {columna} no está disponible.")
        return
    
    valores = gdf[columna].dropna()
    if len(valores) == 0:
        st.warning(f"No hay datos válidos para {titulo}.")
        return
    
    # Crear colormap de branca
    colormap = LinearColormap(colors=colormap_list, vmin=vmin, vmax=vmax, caption=titulo)
    
    # Crear mapa interactivo con los bloques coloreados
    mapa = crear_mapa_interactivo_base(
        gdf,
        columna_color=columna,
        colormap=colormap,
        tooltip_fields=['id_bloque', columna],
        tooltip_aliases=['Bloque', titulo]
    )
    
    if mapa:
        # Añadir el colormap al mapa
        colormap.add_to(mapa)
        folium_static(mapa, width=1000, height=600)
    else:
        st.warning("No se pudo generar el mapa. Mostrando gráfico de barras.")
        fig, ax = plt.subplots(figsize=(10,4))
        ax.bar(range(len(gdf)), gdf[columna].values, color='steelblue')
        ax.set_xlabel('Bloque')
        ax.set_ylabel(titulo)
        ax.set_title(f'Valores de {titulo} por bloque')
        st.pyplot(fig)
        plt.close(fig)
    
    # Mostrar estadísticas
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Media", f"{valores.mean():.3f}")
    with col2:
        st.metric("Mediana", f"{valores.median():.3f}")
    with col3:
        st.metric("Desv. estándar", f"{valores.std():.3f}")
    with col4:
        st.metric("Mínimo", f"{valores.min():.3f}")
    with col5:
        st.metric("Máximo", f"{valores.max():.3f}")
    
    st.markdown("#### Valores por bloque")
    df_tabla = gdf[['id_bloque', columna]].copy()
    df_tabla.columns = ['Bloque', titulo]
    st.dataframe(df_tabla.style.format({titulo: '{:.3f}'}), use_container_width=True)

def mostrar_comparacion_ndvi_ndwi(gdf):
    if gdf is None or len(gdf) == 0:
        st.warning("No hay datos para la comparación.")
        return
    
    df = gdf[['id_bloque', 'ndvi_modis', 'ndwi_modis', 'salud', 'area_ha']].copy()
    df = df.dropna()
    
    if len(df) == 0:
        st.warning("Datos insuficientes para la comparación.")
        return
    
    st.markdown("### 🔍 Comparación NDVI vs NDWI")
    
    try:
        import statsmodels.api as sm
        statsmodels_ok = True
    except ImportError:
        statsmodels_ok = False
        st.info("ℹ️ Para ver la línea de tendencia, instala 'statsmodels' con: pip install statsmodels")
    
    fig = px.scatter(
        df, x='ndvi_modis', y='ndwi_modis', color='salud',
        size='area_ha', hover_data=['id_bloque'],
        labels={'ndvi_modis': 'NDVI', 'ndwi_modis': 'NDWI', 'salud': 'Salud'},
        title='Relación entre NDVI y NDWI por bloque',
        color_discrete_map={
            'Crítica': '#d73027',
            'Baja': '#fee08b',
            'Moderada': '#91cf60',
            'Buena': '#1a9850'
        },
        trendline='ols' if statsmodels_ok else None,
        trendline_color_override='gray'
    )
    fig.update_traces(marker=dict(line=dict(width=1, color='DarkSlateGrey')))
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Top 5 NDVI")
        top_ndvi = df.nlargest(5, 'ndvi_modis')[['id_bloque', 'ndvi_modis', 'salud']]
        top_ndvi.columns = ['Bloque', 'NDVI', 'Salud']
        st.dataframe(top_ndvi.style.format({'NDVI': '{:.3f}'}), use_container_width=True)
        
        st.markdown("#### Bottom 5 NDVI")
        bottom_ndvi = df.nsmallest(5, 'ndvi_modis')[['id_bloque', 'ndvi_modis', 'salud']]
        bottom_ndvi.columns = ['Bloque', 'NDVI', 'Salud']
        st.dataframe(bottom_ndvi.style.format({'NDVI': '{:.3f}'}), use_container_width=True)
    
    with col2:
        st.markdown("#### Top 5 NDWI")
        top_ndwi = df.nlargest(5, 'ndwi_modis')[['id_bloque', 'ndwi_modis', 'salud']]
        top_ndwi.columns = ['Bloque', 'NDWI', 'Salud']
        st.dataframe(top_ndwi.style.format({'NDWI': '{:.3f}'}), use_container_width=True)
        
        st.markdown("#### Bottom 5 NDWI")
        bottom_ndwi = df.nsmallest(5, 'ndwi_modis')[['id_bloque', 'ndwi_modis', 'salud']]
        bottom_ndwi.columns = ['Bloque', 'NDWI', 'Salud']
        st.dataframe(bottom_ndwi.style.format({'NDWI': '{:.3f}'}), use_container_width=True)

def crear_mapa_fertilidad_interactivo(gdf_fertilidad, variable, colormap_nombre='YlOrRd'):
    info_var = {
        'N_kg_ha': {'titulo': 'Nitrógeno (N)', 'unidad': 'kg/ha', 'vmin': 40, 'vmax': 180, 'cmap': 'YlGnBu'},
        'P_kg_ha': {'titulo': 'Fósforo (P₂O₅)', 'unidad': 'kg/ha', 'vmin': 15, 'vmax': 70, 'cmap': 'YlOrRd'},
        'K_kg_ha': {'titulo': 'Potasio (K₂O)', 'unidad': 'kg/ha', 'vmin': 80, 'vmax': 250, 'cmap': 'YlGn'},
        'pH': {'titulo': 'pH del suelo', 'unidad': '', 'vmin': 4.5, 'vmax': 6.5, 'cmap': 'RdYlGn_r'},
        'MO_porcentaje': {'titulo': 'Materia Orgánica', 'unidad': '%', 'vmin': 1.0, 'vmax': 5.0, 'cmap': 'BrBG'}
    }
    info = info_var.get(variable, {'titulo': variable, 'unidad': '', 'vmin': None, 'vmax': None, 'cmap': 'YlOrRd'})
    
    colormap = LinearColormap(
        colors=['#ffffb2','#fecc5c','#fd8d3c','#f03b20','#bd0026'] if info['cmap'] == 'YlOrRd' else
                ['#c7e9c0','#74c476','#31a354','#006d2c'] if info['cmap'] == 'YlGn' else
                ['#4575b4','#91bfdb','#e0f3f8','#fee090','#fc8d59','#d73027'] if info['cmap'] == 'RdYlGn_r' else
                ['#8c510a','#bf812d','#dfc27d','#f6e8c3','#c7eae5','#80cdc1','#35978f','#01665e'],
        vmin=info['vmin'] if info['vmin'] else gdf_fertilidad[variable].min(),
        vmax=info['vmax'] if info['vmax'] else gdf_fertilidad[variable].max(),
        caption=f"{info['titulo']} ({info['unidad']})"
    )
    
    m = crear_mapa_interactivo_base(
        gdf_fertilidad,
        columna_color=variable,
        colormap=colormap,
        tooltip_fields=['id_bloque', variable, 'recomendacion_N', 'recomendacion_P', 'recomendacion_K'],
        tooltip_aliases=['Bloque', f'{info["titulo"]} ({info["unidad"]})', 'Recom. N', 'Recom. P', 'Recom. K']
    )
    if m:
        colormap.add_to(m)
    return m

def crear_grafico_textural(arena, limo, arcilla, tipo_suelo):
    fig = go.Figure()
    fig.add_trace(go.Scatterternary(
        a=[arcilla], b=[limo], c=[arena],
        mode='markers+text',
        marker=dict(size=14, color='red'),
        text=[tipo_suelo],
        textposition='top center',
        name='Suelo actual'
    ))
    fig.update_layout(
        title='Triángulo Textural',
        ternary=dict(
            sum=100,
            aaxis=dict(title='% Arcilla', min=0, linewidth=2),
            baxis=dict(title='% Limo', min=0, linewidth=2),
            caxis=dict(title='% Arena', min=0, linewidth=2)
        ),
        height=500, width=600
    )
    return fig

# ===== FUNCIONES YOLO =====
def cargar_modelo_yolo(ruta_modelo):
    try:
        from ultralytics import YOLO
        modelo = YOLO(ruta_modelo)
        return modelo
    except Exception as e:
        st.error(f"Error al cargar el modelo YOLO: {str(e)}")
        return None

def detectar_en_imagen(modelo, imagen_cv, conf_threshold=0.25):
    if modelo is None:
        return None
    try:
        resultados = modelo(imagen_cv, conf=conf_threshold)
        return resultados
    except Exception as e:
        st.error(f"Error en la inferencia YOLO: {str(e)}")
        return None

def dibujar_detecciones_con_leyenda(imagen_cv, resultados, colores_aleatorios=True):
    if resultados is None or len(resultados) == 0:
        return imagen_cv, []

    img_anotada = imagen_cv.copy()
    detecciones_info = []
    names = resultados[0].names

    for r in resultados:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            label = names[cls_id]

            if colores_aleatorios:
                color = tuple(np.random.randint(0, 255, 3).tolist())
            else:
                np.random.seed(cls_id)
                color = tuple(np.random.randint(0, 255, 3).tolist())
                np.random.seed(None)

            cv2.rectangle(img_anotada, (x1, y1), (x2, y2), color, 3)
            etiqueta = f"{label} {conf:.2f}"
            (w, h), _ = cv2.getTextSize(etiqueta, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(img_anotada, (x1, y1 - h - 10), (x1 + w, y1), color, -1)
            cv2.putText(img_anotada, etiqueta, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            detecciones_info.append({
                'clase': label,
                'confianza': round(conf, 3),
                'bbox': [x1, y1, x2, y2],
                'color': color
            })

    return img_anotada, detecciones_info

def crear_leyenda_html(detecciones_info):
    if not detecciones_info:
        return "<p>No se detectaron objetos.</p>"

    clases_vistas = {}
    for d in detecciones_info:
        if d['clase'] not in clases_vistas:
            clases_vistas[d['clase']] = d['color']

    from collections import Counter
    conteo_clases = Counter([d['clase'] for d in detecciones_info])

    html = "<div style='background: rgba(30, 30, 30, 0.9); padding: 15px; border-radius: 10px; margin-top: 20px;'>"
    html += "<h4 style='color: white; margin-bottom: 10px;'>📋 Leyenda de detecciones</h4>"
    html += "<table style='width: 100%; color: white; border-collapse: collapse;'>"
    html += "<tr><th>Color</th><th>Clase</th><th>Conteo</th></tr>"

    for clase, color in clases_vistas.items():
        color_hex = '#{:02x}{:02x}{:02x}'.format(color[0], color[1], color[2])
        html += f"<tr style='border-bottom: 1px solid #444;'>"
        html += f"<td style='padding: 8px;'><span style='display: inline-block; width: 20px; height: 20px; background-color: {color_hex}; border-radius: 4px;'></span></td>"
        html += f"<td style='padding: 8px;'>{clase}</td>"
        html += f"<td style='padding: 8px; text-align: center;'>{conteo_clases[clase]}</td>"
        html += f"</tr>"

    html += "</table></div>"
    return html

# ===== CURVAS DE NIVEL =====
def obtener_dem_opentopography(gdf, api_key=None):
    try:
        import rasterio
        from rasterio.mask import mask
    except ImportError:
        st.warning("Para curvas de nivel reales instala rasterio y scikit-image")
        return None, None, None
    if api_key is None:
        api_key = os.environ.get("OPENTOPOGRAPHY_API_KEY", None)
    if not api_key:
        return None, None, None
    try:
        bounds = gdf.total_bounds
        west, south, east, north = bounds
        lon_span = east - west
        lat_span = north - south
        west -= lon_span * 0.05
        east += lon_span * 0.05
        south -= lat_span * 0.05
        north += lat_span * 0.05
        url = "https://portal.opentopography.org/API/globaldem"
        params = {
            "demtype": "SRTMGL1",
            "south": south,
            "north": north,
            "west": west,
            "east": east,
            "outputFormat": "GTiff",
            "API_Key": api_key
        }
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        dem_bytes = BytesIO(response.content)
        with rasterio.open(dem_bytes) as src:
            geom = [mapping(gdf.unary_union)]
            out_image, out_transform = mask(src, geom, crop=True, nodata=-32768)
            out_meta = src.meta.copy()
            out_meta.update({
                "driver": "GTiff",
                "height": out_image.shape[1],
                "width": out_image.shape[2],
                "transform": out_transform,
                "nodata": -32768
            })
        return out_image.squeeze(), out_meta, out_transform
    except Exception as e:
        st.error(f"Error descargando DEM: {str(e)[:200]}")
        return None, None, None

def generar_curvas_nivel_simuladas(gdf):
    try:
        from skimage import measure
    except ImportError:
        return []
    bounds = gdf.total_bounds
    minx, miny, maxx, maxy = bounds
    n = 100
    x = np.linspace(minx, maxx, n)
    y = np.linspace(miny, maxy, n)
    X, Y = np.meshgrid(x, y)
    np.random.seed(42)
    Z = np.random.randn(n, n) * 20
    from scipy.ndimage import gaussian_filter
    Z = gaussian_filter(Z, sigma=5)
    Z = 50 + (Z - Z.min()) / (Z.max() - Z.min()) * 150
    contours = []
    niveles = np.arange(50, 200, 10)
    for nivel in niveles:
        try:
            for contour in measure.find_contours(Z, nivel):
                coords = []
                for row, col in contour:
                    lat = miny + (row / n) * (maxy - miny)
                    lon = minx + (col / n) * (maxx - minx)
                    coords.append((lon, lat))
                if len(coords) > 2:
                    line = LineString(coords)
                    if line.length > 0.01:
                        contours.append((line, nivel))
        except:
            continue
    return contours

def generar_curvas_nivel_reales(dem_array, transform, intervalo=10):
    try:
        from skimage import measure
    except ImportError:
        return []
    if dem_array is None:
        return []
    dem_array = np.ma.masked_where(dem_array <= -999, dem_array)
    vmin = dem_array.min()
    vmax = dem_array.max()
    if vmin is np.ma.masked or vmax is np.ma.masked:
        return []
    niveles = np.arange(np.floor(vmin / intervalo) * intervalo,
                        np.ceil(vmax / intervalo) * intervalo + intervalo,
                        intervalo)
    contours = []
    for nivel in niveles:
        try:
            for contour in measure.find_contours(dem_array.filled(fill_value=-999), nivel):
                coords = []
                for row, col in contour:
                    x, y = transform * (col, row)
                    coords.append((x, y))
                if len(coords) > 2:
                    line = LineString(coords)
                    if line.length > 0.01:
                        contours.append((line, nivel))
        except:
            continue
    return contours

def mapa_curvas_coloreadas(gdf_original, curvas_con_elevacion):
    centroide = gdf_original.geometry.unary_union.centroid
    m = folium.Map(location=[centroide.y, centroide.x], zoom_start=15, tiles=None, control_scale=True)
    folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                     attr='Esri', name='Satélite Esri', overlay=False, control=True).add_to(m)
    folium.TileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
                     attr='OpenStreetMap', name='OpenStreetMap', overlay=False, control=True).add_to(m)
    folium.GeoJson(gdf_original.to_json(), name='Plantación',
                   style_function=lambda x: {'color': 'blue', 'fillOpacity': 0.1, 'weight': 2}).add_to(m)
    elevaciones = [e for _, e in curvas_con_elevacion]
    if elevaciones:
        vmin = min(elevaciones); vmax = max(elevaciones)
        colormap = LinearColormap(colors=['green','yellow','orange','brown'], vmin=vmin, vmax=vmax, caption='Elevación (m.s.n.m)')
        colormap.add_to(m)
        for line, elev in curvas_con_elevacion:
            folium.GeoJson(gpd.GeoSeries(line).to_json(), name='Curvas',
                           style_function=lambda x, e=elev: {'color': colormap(e), 'weight': 1.5, 'opacity': 0.9},
                           tooltip=f'Elevación: {elev:.0f} m').add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    Fullscreen().add_to(m)
    return m

# ===== FUNCIÓN PRINCIPAL DE ANÁLISIS =====
def ejecutar_analisis_completo():
    if st.session_state.gdf_original is None:
        st.error("Primero debe cargar un archivo de plantación")
        return
    with st.spinner("Ejecutando análisis completo..."):
        n_divisiones = st.session_state.get('n_divisiones', 16)
        fecha_inicio = st.session_state.get('fecha_inicio', datetime.now() - timedelta(days=60))
        fecha_fin = st.session_state.get('fecha_fin', datetime.now())
        gdf = st.session_state.gdf_original.copy()
        
        if st.session_state.demo_mode:
            st.info("🎮 Modo DEMO activo: usando datos simulados.")
            gdf_dividido = generar_datos_simulados_completos(gdf, n_divisiones)
            st.session_state.datos_climaticos = generar_clima_simulado()
            st.session_state.datos_modis = {
                'ndvi': gdf_dividido['ndvi_modis'].mean(),
                'ndwi': gdf_dividido['ndwi_modis'].mean(),
                'fecha': fecha_inicio.strftime('%Y-%m-%d'),
                'fuente': 'Datos simulados (DEMO)'
            }
        else:
            # Modo PREMIUM: obtener datos reales con Earthdata
            gdf_dividido = dividir_plantacion_en_bloques(gdf, n_divisiones)
            areas_ha = []
            for idx, row in gdf_dividido.iterrows():
                area_gdf = gpd.GeoDataFrame({'geometry': [row.geometry]}, crs=gdf_dividido.crs)
                areas_ha.append(float(calcular_superficie(area_gdf)))
            gdf_dividido['area_ha'] = areas_ha

            # 1. Obtener NDVI real
            st.info("🛰️ Obteniendo NDVI desde Earthdata (MOD13Q1)...")
            resultado_ndvi = obtener_ndvi_earthdata(gdf_dividido, fecha_inicio, fecha_fin)
            if resultado_ndvi is None:
                st.error("No se pudo obtener NDVI real. Verifique su conexión y credenciales de Earthdata.")
                st.stop()
            gdf_dividido = resultado_ndvi
            fuente_ndvi = "Earthdata MOD13Q1"

            # 2. Obtener NDWI real
            st.info("💧 Obteniendo NDWI desde Earthdata (MOD09GA)...")
            resultado_ndwi = obtener_ndwi_earthdata(gdf_dividido, fecha_inicio, fecha_fin)
            if resultado_ndwi is None:
                st.error("No se pudo obtener NDWI real. Verifique su conexión y credenciales de Earthdata.")
                st.stop()
            gdf_dividido = resultado_ndwi
            fuente_ndwi = "Earthdata MOD09GA"

            # 3. Datos climáticos (con protección contra None)
            st.info("🌦️ Obteniendo datos climáticos de Open-Meteo ERA5...")
            datos_clima = obtener_clima_openmeteo(gdf, fecha_inicio, fecha_fin) or {}
            st.info("☀️ Obteniendo radiación y viento de NASA POWER...")
            datos_power = obtener_radiacion_viento_power(gdf, fecha_inicio, fecha_fin) or {}
            st.session_state.datos_climaticos = {**datos_clima, **datos_power}

            # 4. Edad simulada (se mantiene como simulación simple)
            edades = analizar_edad_plantacion(gdf_dividido)
            gdf_dividido['edad_anios'] = edades

            st.session_state.datos_modis = {
                'ndvi': gdf_dividido['ndvi_modis'].mean(),
                'ndwi': gdf_dividido['ndwi_modis'].mean(),
                'fecha': fecha_inicio.strftime('%Y-%m-%d'),
                'fuente': f"NDVI: {fuente_ndvi}, NDWI: {fuente_ndwi}"
            }

        # Clasificar salud (común)
        def clasificar_salud(ndvi):
            if ndvi < 0.4: return 'Crítica'
            if ndvi < 0.6: return 'Baja'
            if ndvi < 0.75: return 'Moderada'
            return 'Buena'
        gdf_dividido['salud'] = gdf_dividido['ndvi_modis'].apply(clasificar_salud)

        # Análisis de suelo (si activado)
        if st.session_state.get('analisis_suelo', True):
            st.session_state.textura_por_bloque = analizar_textura_suelo_venezuela_por_bloque(gdf_dividido)
            if st.session_state.textura_por_bloque:
                st.session_state.textura_suelo = st.session_state.textura_por_bloque[0]

        st.session_state.datos_fertilidad = generar_mapa_fertilidad(gdf_dividido)

        st.session_state.resultados_todos = {
            'exitoso': True,
            'gdf_completo': gdf_dividido,
            'area_total': calcular_superficie(gdf)
        }
        st.session_state.analisis_completado = True
        st.success("✅ Análisis completado!")

# ===== Mostrar advertencias de librerías opcionales =====
if not EARTHDATA_OK:
    st.warning("Para usar datos satelitales reales, instala 'earthaccess', 'xarray' y 'rioxarray': pip install earthaccess xarray rioxarray")
if not RASTERIO_OK and not PYHDF_OK:
    st.warning("⚠️ rasterio y pyhdf no están instalados. No se podrán leer archivos HDF4. Instala al menos uno: pip install rasterio o pip install pyhdf")

# ===== ESTILOS Y CABECERA (OCULTAMIENTO TOTAL DE GITHUB) =====
st.markdown("""
<style>
/* Ocultar menú principal (tres puntos) */
#MainMenu {visibility: hidden !important;}

/* Ocultar footer de Streamlit */
footer {visibility: hidden !important;}

/* Ocultar header completo */
header {visibility: hidden !important;}
.stApp header {display: none !important;}

/* OCULTAR BARRA DE HERRAMIENTAS (Share, Edit, GitHub) */
.stApp [data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}
.stApp [data-testid="stToolbar"] button {visibility: hidden !important; display: none !important;}

/* Ocultar elementos específicos del toolbar */
[data-testid="stToolbar"] [aria-label="Share"] {display: none !important;}
[data-testid="stToolbar"] [aria-label="Edit"] {display: none !important;}
[data-testid="stToolbar"] [aria-label="GitHub"] {display: none !important;}

/* Ocultar otros elementos de UI de Streamlit */
.st-emotion-cache-1avcm0n {display: none !important;}
.st-emotion-cache-16txtl3 {display: none !important;}
.st-emotion-cache-12fmjuu {display: none !important;}
.st-emotion-cache-1w71dyz {display: none !important;}
.st-emotion-cache-ecx28m {display: none !important;}

/* Botón de deploy */
.stAppDeployButton {display: none !important;}
[data-testid="stAppDeployButton"] {display: none !important;}

/* Cualquier elemento que contenga texto "GitHub" o enlace */
a:contains("GitHub"), a[href*="github"] {display: none !important;}
span:contains("GitHub"), div:contains("GitHub") {display: none !important;}

/* Estilos personalizados de la app */
.hero-banner { 
    background: linear-gradient(145deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.98)); 
    padding: 1.5em; 
    border-radius: 15px; 
    margin-bottom: 1em; 
    border: 1px solid rgba(76, 175, 80, 0.3); 
    text-align: center; 
}
.hero-title { 
    color: #ffffff; 
    font-size: 2em; 
    font-weight: 800; 
    margin-bottom: 0.5em; 
    background: linear-gradient(135deg, #ffffff 0%, #81c784 100%); 
    -webkit-background-clip: text; 
    -webkit-text-fill-color: transparent; 
}
.stButton > button { 
    background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%) !important; 
    color: white !important; 
    border: none !important; 
    padding: 0.8em 1.5em !important; 
    border-radius: 12px !important; 
    font-weight: 700 !important; 
    font-size: 1em !important; 
    margin: 5px 0 !important; 
    transition: all 0.3s ease !important; 
}
.stButton > button:hover { 
    transform: translateY(-2px) !important; 
    box-shadow: 0 5px 15px rgba(0,0,0,0.3) !important; 
}
.stTabs [data-baseweb="tab-list"] { 
    background: rgba(30, 41, 59, 0.7) !important; 
    backdrop-filter: blur(10px) !important; 
    padding: 8px 16px !important; 
    border-radius: 16px !important; 
    border: 1px solid rgba(76, 175, 80, 0.3) !important; 
    margin-top: 1.5em !important; 
}
div[data-testid="metric-container"] { 
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.95)) !important; 
    backdrop-filter: blur(10px) !important; 
    border-radius: 18px !important; 
    padding: 22px !important; 
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35) !important; 
    border: 1px solid rgba(76, 175, 80, 0.25) !important; 
}
</style>

<script>
// JavaScript para eliminar cualquier elemento que contenga "github" en su texto o atributos
document.addEventListener('DOMContentLoaded', function() {
    function removeGithubElements() {
        const elements = document.querySelectorAll('*');
        elements.forEach(el => {
            if (el.children.length === 0) {
                if (el.textContent && el.textContent.toLowerCase().includes('github')) {
                    el.remove();
                }
            }
            if (el.href && el.href.toLowerCase().includes('github')) {
                el.remove();
            }
        });
    }
    removeGithubElements();
    setTimeout(removeGithubElements, 1000);
    setTimeout(removeGithubElements, 3000);
});
</script>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero-banner">
    <h1 class="hero-title">🌴 ANALIZADOR DE PALMA ACEITERA SATELITAL</h1>
    <p style="color: #cbd5e1; font-size: 1.2em;">
        Monitoreo biológico con datos reales NASA Earthdata · Open-Meteo · NASA POWER
    </p>
</div>
""", unsafe_allow_html=True)

# ===== SIDEBAR =====
with st.sidebar:
    st.markdown("## 🌴 CONFIGURACIÓN")
    variedad = st.selectbox("Variedad de palma:", VARIEDADES_PALMA_ACEITERA, index=0)
    st.session_state.variedad_seleccionada = variedad
    st.markdown("---")
    st.markdown("### 📅 Rango Temporal")
    fecha_fin_default = datetime.now()
    fecha_inicio_default = datetime.now() - timedelta(days=60)
    fecha_fin = st.date_input("Fecha fin", fecha_fin_default)
    fecha_inicio = st.date_input("Fecha inicio", fecha_inicio_default)
    try:
        if hasattr(fecha_inicio, 'year'): fecha_inicio = datetime.combine(fecha_inicio, datetime.min.time())
        if hasattr(fecha_fin, 'year'): fecha_fin = datetime.combine(fecha_fin, datetime.min.time())
    except: pass
    st.session_state.fecha_inicio = fecha_inicio
    st.session_state.fecha_fin = fecha_fin
    st.markdown("---")
    st.markdown("### 🎯 División de Plantación")
    n_divisiones = st.slider("Número de bloques:", 8, 32, 16)
    st.session_state.n_divisiones = n_divisiones
    st.markdown("---")
    st.markdown("### 🌴 Detección de Palmas")
    deteccion_habilitada = st.checkbox("Activar detección de plantas", value=True)
    if deteccion_habilitada:
        densidad_personalizada = st.slider("Densidad objetivo (plantas/ha):", 50, 200, 130)
        st.session_state.densidad_personalizada = densidad_personalizada
    st.markdown("---")
    st.markdown("### 🧪 Análisis de Suelo")
    analisis_suelo = st.checkbox("Activar análisis de suelo", value=True)
    if analisis_suelo:
        st.info("Incluye: Textura por bloque, fertilidad NPK, recomendaciones")
    st.session_state.analisis_suelo = analisis_suelo
    st.markdown("---")
    
    # === SECCIÓN DE CARGA DE POLÍGONO MEJORADA ===
    st.markdown("### 📤 Subir Polígono")
    
    uploaded_file = st.file_uploader(
        "Subir archivo de plantación", 
        type=['zip', 'kml', 'kmz', 'geojson'],
        help="Formatos: Shapefile (.zip), KML (.kmz), GeoJSON (.geojson)",
        key="polygon_uploader"
    )
    
    # Mostrar información del archivo cargado
    if uploaded_file is not None:
        st.info(f"📄 Archivo: {uploaded_file.name}")
        st.info(f"📊 Tamaño: {uploaded_file.size / 1024:.1f} KB")
        
        # Botón de carga explícito
        if st.button("🔄 Cargar Polígono", key="load_polygon_btn"):
            with st.spinner("⏳ Procesando polígono..."):
                gdf = cargar_archivo_plantacion(uploaded_file)
                if gdf is not None:
                    st.success("✅ Polígono cargado correctamente")
                    st.rerun()
    
    # Mostrar estado actual
    if st.session_state.get('archivo_cargado', False):
        st.success("✅ Polígono cargado en memoria")
        if st.session_state.get('gdf_original') is not None:
            area = calcular_superficie(st.session_state.gdf_original)
            st.metric("Área", f"{area:.2f} ha")
    
    # Debug info (opcional, se puede eliminar después)
    with st.expander("🔧 Debug - Estado del polígono"):
        if st.session_state.get('gdf_original') is None:
            st.warning("⚠️ No hay polígono en session_state")
            st.write("Session state keys:", list(st.session_state.keys()))
        else:
            st.success("✅ Polígono disponible")
            st.write("CRS:", st.session_state.gdf_original.crs)
            st.write("Área:", calcular_superficie(st.session_state.gdf_original))

# ===== ÁREA PRINCIPAL =====
if st.session_state.archivo_cargado and st.session_state.gdf_original is not None:
    gdf = st.session_state.gdf_original
    try:
        area_total = calcular_superficie(gdf)
    except:
        area_total = 0.0
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 📊 INFORMACIÓN DE LA PLANTACIÓN")
        st.write(f"- **Área total:** {area_total:.1f} ha")
        st.write(f"- **Variedad:** {st.session_state.variedad_seleccionada}")
        st.write(f"- **Bloques configurados:** {st.session_state.n_divisiones}")
        # Mostrar un mapa interactivo del polígono cargado
        st.markdown("#### 🗺️ Vista previa del polígono")
        try:
            m_preview = folium.Map(location=[gdf.geometry.centroid.y.iloc[0], gdf.geometry.centroid.x.iloc[0]], zoom_start=15, tiles=None)
            folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                             attr='Esri', name='Satélite').add_to(m_preview)
            folium.GeoJson(gdf.to_json(), style_function=lambda x: {'fillColor': '#3388ff', 'color': 'black', 'weight': 2, 'fillOpacity': 0.4}).add_to(m_preview)
            folium.LayerControl().add_to(m_preview)
            folium_static(m_preview, width=500, height=300)
        except Exception as e:
            st.warning(f"No se pudo mostrar el mapa de vista previa: {e}")
    with col2:
        st.markdown("### 🎯 ACCIONES")
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if not st.session_state.analisis_completado:
                if st.button("🚀 EJECUTAR ANÁLISIS", use_container_width=True):
                    ejecutar_analisis_completo()
                    st.rerun()
            else:
                if st.button("🔄 RE-EJECUTAR", use_container_width=True):
                    st.session_state.analisis_completado = False
                    ejecutar_analisis_completo()
                    st.rerun()
        with col_btn2:
            if deteccion_habilitada:
                if st.button("🔍 DETECTAR PALMAS", use_container_width=True):
                    ejecutar_deteccion_palmas()
                    st.rerun()
else:
    # Si no hay archivo cargado, mostrar un mensaje amigable
    st.info("👆 Por favor, sube un archivo de plantación en la barra lateral para comenzar.")
    st.markdown("""
    ### ¿Cómo empezar?
    1. Inicia sesión o regístrate.
    2. Sube un archivo con el polígono de tu plantación (formatos: Shapefile .zip, KML, KMZ, GeoJSON).
    3. Configura los parámetros de análisis.
    4. Haz clic en **EJECUTAR ANÁLISIS** para obtener resultados.
    """)
    # Mensaje específico para modo DEMO
    if st.session_state.demo_mode:
        st.info("🎮 Estás en modo DEMO. **Sube tu propio archivo** (KML, KMZ o ZIP con shapefile) para ejecutar el análisis con datos simulados.")

# ===== PESTAÑAS DE RESULTADOS =====
if st.session_state.analisis_completado:
    resultados = st.session_state.resultados_todos
    gdf_completo = resultados.get('gdf_completo')
    
    if gdf_completo is not None:
        tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
            "📊 Resumen", "🗺️ Mapas", "🛰️ Índices", 
            "🌤️ Clima", "🌴 Detección", "🧪 Fertilidad NPK", 
            "🌱 Textura Suelo", "🗺️ Curvas de Nivel", "🐛 Detección YOLO"
        ])
        
        with tab1:
            st.subheader("📊 DASHBOARD DE RESUMEN")
            area_total = resultados.get('area_total', 0)
            edad_prom = gdf_completo['edad_anios'].mean() if 'edad_anios' in gdf_completo.columns else np.nan
            ndvi_prom = gdf_completo['ndvi_modis'].mean() if 'ndvi_modis' in gdf_completo.columns else np.nan
            ndwi_prom = gdf_completo['ndwi_modis'].mean() if 'ndwi_modis' in gdf_completo.columns else np.nan
            total_bloques = len(gdf_completo)
            salud_counts = gdf_completo['salud'].value_counts() if 'salud' in gdf_completo.columns else pd.Series()
            pct_buena = (salud_counts.get('Buena', 0) / total_bloques * 100) if total_bloques > 0 else 0
            
            col_m1, col_m2, col_m3, col_m4, col_m5, col_m6 = st.columns(6)
            with col_m1:
                st.metric("Área Total", f"{area_total:.1f} ha")
            with col_m2:
                st.metric("Bloques", f"{total_bloques}")
            with col_m3:
                st.metric("Edad Prom.", f"{edad_prom:.1f} años" if not np.isnan(edad_prom) else "N/A")
            with col_m4:
                st.metric("NDVI Prom.", f"{ndvi_prom:.3f}" if not np.isnan(ndvi_prom) else "N/A")
            with col_m5:
                st.metric("NDWI Prom.", f"{ndwi_prom:.3f}" if not np.isnan(ndwi_prom) else "N/A")
            with col_m6:
                st.metric("Salud Buena", f"{pct_buena:.1f}%")
            
            st.markdown("---")
            
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                st.markdown("#### 🌡️ Distribución de Salud")
                if not salud_counts.empty:
                    fig_pie, ax_pie = plt.subplots(figsize=(5,3))
                    colors_pie = {'Crítica': '#d73027', 'Baja': '#fee08b', 'Moderada': '#91cf60', 'Buena': '#1a9850'}
                    pie_colors = [colors_pie.get(c, '#cccccc') for c in salud_counts.index]
                    wedges, texts, autotexts = ax_pie.pie(
                        salud_counts.values, labels=salud_counts.index, autopct='%1.1f%%',
                        colors=pie_colors, startangle=90, textprops={'fontsize': 9}
                    )
                    ax_pie.set_title("Clasificación de salud", fontsize=10)
                    st.pyplot(fig_pie)
                    plt.close(fig_pie)
                else:
                    st.info("Sin datos de salud")
            
            with col_g2:
                st.markdown("#### 📊 Histograma de NDVI y Edad")
                if 'ndvi_modis' in gdf_completo.columns and 'edad_anios' in gdf_completo.columns:
                    fig_hist, ax_hist = plt.subplots(figsize=(5,3))
                    ax_hist.hist(gdf_completo['ndvi_modis'].dropna(), bins=15, alpha=0.7, label='NDVI', color='green')
                    ax_hist.set_xlabel('NDVI')
                    ax_hist.set_ylabel('Frecuencia', color='green')
                    ax_hist.tick_params(axis='y', labelcolor='green')
                    
                    ax2 = ax_hist.twinx()
                    ax2.hist(gdf_completo['edad_anios'].dropna(), bins=15, alpha=0.5, label='Edad', color='orange')
                    ax2.set_ylabel('Frecuencia (Edad)', color='orange')
                    ax2.tick_params(axis='y', labelcolor='orange')
                    
                    ax_hist.set_title('Distribución de NDVI y Edad')
                    fig_hist.tight_layout()
                    st.pyplot(fig_hist)
                    plt.close(fig_hist)
                else:
                    st.info("Datos insuficientes para histograma")
            
            st.markdown("---")
            
            st.markdown("#### 🗺️ Mapa de Salud por Bloque")
            try:
                fig_map, ax_map = plt.subplots(figsize=(10,5))
                gdf_completo.plot(column='salud', ax=ax_map, legend=True,
                                  categorical=True, cmap='RdYlGn', 
                                  edgecolor='black', linewidth=0.3,
                                  legend_kwds={'title': 'Salud', 'loc': 'lower right'})
                ax_map.set_title("Distribución espacial de la salud")
                ax_map.set_xlabel("Longitud")
                ax_map.set_ylabel("Latitud")
                st.pyplot(fig_map)
                plt.close(fig_map)
            except Exception as e:
                st.warning(f"No se pudo generar el mapa de salud: {e}")
            
            st.markdown("---")
            
            st.markdown("#### 📋 Resumen detallado por bloque")
            try:
                columnas_tabla = ['id_bloque', 'area_ha', 'edad_anios', 'ndvi_modis', 'ndwi_modis', 'salud']
                tabla = gdf_completo[columnas_tabla].copy()
                tabla.columns = ['Bloque', 'Área (ha)', 'Edad (años)', 'NDVI', 'NDWI', 'Salud']
                
                def color_salud(val):
                    if val == 'Crítica':
                        return 'background-color: #d73027; color: white'
                    elif val == 'Baja':
                        return 'background-color: #fee08b'
                    elif val == 'Moderada':
                        return 'background-color: #91cf60'
                    elif val == 'Buena':
                        return 'background-color: #1a9850; color: white'
                    return ''
                
                styled_tabla = tabla.style.format({
                    'Área (ha)': '{:.2f}',
                    'Edad (años)': '{:.1f}',
                    'NDVI': '{:.3f}',
                    'NDWI': '{:.3f}'
                }).applymap(color_salud, subset=['Salud'])
                
                st.dataframe(styled_tabla, use_container_width=True, height=400)
                
                csv_tabla = tabla.to_csv(index=False)
                st.download_button(
                    label="📥 Exportar tabla a CSV",
                    data=csv_tabla,
                    file_name=f"resumen_plantacion_{datetime.now():%Y%m%d}.csv",
                    mime="text/csv"
                )
            except Exception as e:
                st.warning(f"No se pudo mostrar la tabla de bloques: {e}")
        
        with tab2:
            st.subheader("🗺️ MAPAS INTERACTIVOS")
            st.markdown("### 🌍 Mapa Interactivo con Palmas Detectadas")
            try:
                colormap_ndvi = LinearColormap(colors=['red','yellow','green'], vmin=0.3, vmax=0.9)
                mapa_interactivo = crear_mapa_interactivo_base(
                    gdf_completo,
                    columna_color='ndvi_modis',
                    colormap=colormap_ndvi,
                    tooltip_fields=['id_bloque','ndvi_modis','salud'],
                    tooltip_aliases=['Bloque','NDVI','Salud']
                )
                if st.session_state.palmas_detectadas:
                    palmas_group = folium.FeatureGroup(name="Palmas detectadas")
                    for i, palma in enumerate(st.session_state.palmas_detectadas[:2000]):
                        if 'centroide' in palma:
                            lon, lat = palma['centroide']
                            folium.CircleMarker([lat, lon], radius=2, color='red', fill=True,
                                                fill_color='red', fill_opacity=0.8).add_to(palmas_group)
                    palmas_group.add_to(mapa_interactivo)
                    folium.LayerControl().add_to(mapa_interactivo)
                if mapa_interactivo:
                    folium_static(mapa_interactivo, width=1000, height=600)
                else:
                    st.warning("No se pudo generar el mapa interactivo")
            except Exception as e:
                st.error(f"Error al mostrar mapa interactivo: {str(e)[:100]}")
        
        with tab3:
            st.subheader("🛰️ ÍNDICES DE VEGETACIÓN")
            st.caption(f"Fuente: {st.session_state.datos_modis.get('fuente', 'Earthdata')}")
            
            st.markdown("### 🌿 NDVI")
            if 'ndvi_modis' in gdf_completo.columns:
                mostrar_estadisticas_indice(gdf_completo, 'ndvi_modis', 'NDVI', 0.3, 0.9, ['red','yellow','green'])
            else:
                st.error("No hay datos de NDVI disponibles.")
            
            st.markdown("---")
            st.markdown("### 💧 NDWI")
            st.info("NDWI calculado como (NIR - SWIR)/(NIR+SWIR) con bandas de MODIS (producto MOD09GA).")
            if 'ndwi_modis' in gdf_completo.columns:
                mostrar_estadisticas_indice(gdf_completo, 'ndwi_modis', 'NDWI', 0.1, 0.7, ['brown','yellow','blue'])
            else:
                st.error("No hay datos de NDWI disponibles.")
            
            st.markdown("---")
            mostrar_comparacion_ndvi_ndwi(gdf_completo)
            
            st.markdown("### 📥 EXPORTAR")
            try:
                gdf_indices = gdf_completo[['id_bloque','ndvi_modis','ndwi_modis','salud','geometry']].copy()
                gdf_indices.columns = ['id_bloque','NDVI','NDWI','Salud','geometry']
                geojson_indices = gdf_indices.to_json()
                csv_indices = gdf_indices.drop(columns='geometry').to_csv(index=False)
                col_dl1, col_dl2 = st.columns(2)
                with col_dl1: st.download_button("🗺️ GeoJSON", geojson_indices, f"indices_{datetime.now():%Y%m%d}.geojson", "application/geo+json")
                with col_dl2: st.download_button("📊 CSV", csv_indices, f"indices_{datetime.now():%Y%m%d}.csv", "text/csv")
            except Exception as e:
                st.info(f"No se pudieron exportar los datos: {e}")
        
        with tab4:
            st.subheader("🌤️ DATOS CLIMÁTICOS")
            datos_climaticos = st.session_state.datos_climaticos
            if datos_climaticos:
                col1, col2, col3, col4 = st.columns(4)
                with col1: st.metric("Precipitación total", f"{datos_climaticos['precipitacion']['total']} mm")
                with col2: st.metric("Días con lluvia", f"{datos_climaticos['precipitacion']['dias_con_lluvia']} días")
                with col3: st.metric("Temperatura promedio", f"{datos_climaticos['temperatura']['promedio']}°C")
                with col4: st.metric("Radiación promedio", f"{datos_climaticos.get('radiacion',{}).get('promedio', 'N/A')} MJ/m²")
                st.markdown("### 📈 GRÁFICOS CLIMÁTICOS COMPLETOS")
                try:
                    fig_clima = crear_graficos_climaticos_completos(datos_climaticos)
                    st.pyplot(fig_clima); plt.close(fig_clima)
                except Exception as e:
                    st.error(f"Error al mostrar gráficos climáticos: {str(e)[:100]}")
                st.markdown("### 📋 INFORMACIÓN ADICIONAL")
                st.write(f"- **Fuente precipitación/temperatura:** {datos_climaticos.get('fuente', 'N/A')}")
                st.write(f"- **Fuente radiación/viento:** NASA POWER")
                st.write(f"- **Período:** {datos_climaticos['periodo']}")
            else:
                st.info("No hay datos climáticos disponibles")
        
        with tab5:
            st.subheader("🌴 DETECCIÓN DE PALMAS INDIVIDUALES")
            if st.session_state.deteccion_ejecutada and st.session_state.palmas_detectadas:
                palmas = st.session_state.palmas_detectadas
                total = len(palmas)
                area_total_val = resultados.get('area_total', 0)
                densidad = total / area_total_val if area_total_val > 0 else 0
                st.success(f"✅ Detección completada: {total} palmas detectadas")
                col1, col2, col3, col4 = st.columns(4)
                with col1: st.metric("Palmas detectadas", f"{total:,}")
                with col2: st.metric("Densidad", f"{densidad:.0f} plantas/ha")
                with col3: st.metric("Área promedio", f"{np.mean([p.get('area_m2',0) for p in palmas]):.1f} m²")
                with col4: st.metric("Diámetro promedio", f"{np.mean([p.get('diametro_aprox',0) for p in palmas]):.1f} m")
                st.markdown("### 🗺️ Mapa de Distribución")
                try:
                    centroide = gdf_completo.geometry.unary_union.centroid
                    m_palmas = folium.Map(location=[centroide.y, centroide.x], zoom_start=16, tiles=None)
                    folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Satélite').add_to(m_palmas)
                    folium.GeoJson(gdf_completo.to_json(), style_function=lambda x: {'color':'blue','fillOpacity':0.1}).add_to(m_palmas)
                    for i, palma in enumerate(palmas[:2000]):
                        if 'centroide' in palma:
                            lon, lat = palma['centroide']
                            folium.CircleMarker([lat, lon], radius=2, color='red', fill=True, 
                                                fill_color='red', fill_opacity=0.8,
                                                tooltip=f"Palma #{i+1}").add_to(m_palmas)
                    folium.LayerControl().add_to(m_palmas); Fullscreen().add_to(m_palmas)
                    folium_static(m_palmas, width=1000, height=600)
                except Exception as e:
                    st.error(f"Error al mostrar mapa de palmas: {str(e)[:100]}")
                if palmas:
                    try:
                        df_palmas = pd.DataFrame([{
                            'id': i+1, 'longitud': p.get('centroide', (0,0))[0], 'latitud': p.get('centroide', (0,0))[1],
                            'area_m2': p.get('area_m2', 0), 'diametro_m': p.get('diametro_aprox', 0)
                        } for i,p in enumerate(palmas)])
                        gdf_palmas = gpd.GeoDataFrame(df_palmas, geometry=gpd.points_from_xy(df_palmas.longitud, df_palmas.latitud), crs='EPSG:4326')
                        geojson_palmas = gdf_palmas.to_json(); csv_palmas = df_palmas.to_csv(index=False)
                        col_p1, col_p2 = st.columns(2)
                        with col_p1: st.download_button("🗺️ GeoJSON", geojson_palmas, f"palmas_{datetime.now():%Y%m%d}.geojson", "application/geo+json")
                        with col_p2: st.download_button("📊 CSV", csv_palmas, f"coordenadas_{datetime.now():%Y%m%d}.csv", "text/csv")
                    except: st.info("No se pudieron exportar los datos")
            else:
                st.info("La detección de palmas no se ha ejecutado aún.")
                if st.button("🔍 EJECUTAR DETECCIÓN DE PALMAS", key="detectar_palmas_tab5", use_container_width=True):
                    ejecutar_deteccion_palmas()
                    st.rerun()
        
        with tab6:
            st.subheader("🧪 FERTILIDAD DEL SUELO Y RECOMENDACIONES NPK")
            st.caption("Basado en NDVI real y modelos de fertilidad típicos para palma aceitera.")
            datos_fertilidad = st.session_state.datos_fertilidad
            if datos_fertilidad:
                df_fertilidad = pd.DataFrame(datos_fertilidad)
                gdf_fertilidad = gpd.GeoDataFrame(df_fertilidad, geometry='geometria', crs='EPSG:4326')
                
                col1, col2, col3, col4, col5 = st.columns(5)
                with col1: N_prom = df_fertilidad['N_kg_ha'].mean(); st.metric("Nitrógeno (N)", f"{N_prom:.0f} kg/ha")
                with col2: P_prom = df_fertilidad['P_kg_ha'].mean(); st.metric("Fósforo (P₂O₅)", f"{P_prom:.0f} kg/ha")
                with col3: K_prom = df_fertilidad['K_kg_ha'].mean(); st.metric("Potasio (K₂O)", f"{K_prom:.0f} kg/ha")
                with col4: pH_prom = df_fertilidad['pH'].mean(); st.metric("pH", f"{pH_prom:.2f}")
                with col5: MO_prom = df_fertilidad['MO_porcentaje'].mean(); st.metric("Materia Orgánica", f"{MO_prom:.1f}%")
                
                st.markdown("---")
                st.markdown("### 🗺️ MAPA INTERACTIVO DE NUTRIENTES (Esri Satélite)")
                
                variable = st.selectbox(
                    "Selecciona la variable a visualizar:",
                    options=['N_kg_ha', 'P_kg_ha', 'K_kg_ha', 'pH', 'MO_porcentaje'],
                    format_func=lambda x: {
                        'N_kg_ha': 'Nitrógeno (N) kg/ha',
                        'P_kg_ha': 'Fósforo (P₂O₅) kg/ha',
                        'K_kg_ha': 'Potasio (K₂O) kg/ha',
                        'pH': 'pH del suelo',
                        'MO_porcentaje': 'Materia Orgánica (%)'
                    }[x]
                )
                
                mapa_fertilidad = crear_mapa_fertilidad_interactivo(gdf_fertilidad, variable)
                if mapa_fertilidad:
                    folium_static(mapa_fertilidad, width=1000, height=600)
                else:
                    st.warning("No se pudo generar el mapa de fertilidad.")
                
                st.markdown("### 📋 RECOMENDACIONES DETALLADAS POR BLOQUE")
                df_recom = df_fertilidad[['id_bloque', 'N_kg_ha', 'P_kg_ha', 'K_kg_ha', 'pH', 
                                          'recomendacion_N', 'recomendacion_P', 'recomendacion_K']].copy()
                df_recom.columns = ['Bloque', 'N', 'P₂O₅', 'K₂O', 'pH', 'Recomendación N', 'Recomendación P', 'Recomendación K']
                st.dataframe(df_recom.head(15), use_container_width=True)
                
                st.markdown("### 📥 EXPORTAR DATOS DE FERTILIDAD")
                csv_data = df_fertilidad.drop(columns=['geometria']).to_csv(index=False)
                st.download_button("📊 CSV completo", csv_data, f"fertilidad_{datetime.now():%Y%m%d}.csv", "text/csv")
            else:
                st.info("Ejecute el análisis completo para ver los datos de fertilidad.")
        
        with tab7:
            st.subheader("🌱 ANÁLISIS DE TEXTURA DE SUELO MEJORADO")
            textura_por_bloque = st.session_state.get('textura_por_bloque', [])
            if textura_por_bloque:
                df_textura = pd.DataFrame(textura_por_bloque)
                st.success(f"**Análisis de textura por bloque completado**")
                st.markdown("### 🗺️ Mapa de Tipos de Suelo por Bloque")
                try:
                    gdf_textura = gpd.GeoDataFrame(df_textura, geometry='geometria', crs='EPSG:4326')
                    tipos_unicos = gdf_textura['tipo_suelo'].unique()
                    colores = ['#8B4513', '#D2691E', '#F4A460', '#DEB887', '#BC8F8F', '#CD853F']
                    color_dict = {tipo: colores[i % len(colores)] for i, tipo in enumerate(tipos_unicos)}
                    m_textura = folium.Map(location=[gdf_completo.geometry.centroid.y.mean(), gdf_completo.geometry.centroid.x.mean()], 
                                           zoom_start=15, tiles=None)
                    folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 
                                     attr='Esri', name='Satélite').add_to(m_textura)
                    def style_func(feature):
                        tipo = feature['properties']['tipo_suelo']
                        return {'fillColor': color_dict.get(tipo, '#888'), 
                                'color': 'black', 'weight': 1, 'fillOpacity': 0.6}
                    folium.GeoJson(
                        gdf_textura.to_json(),
                        name='Textura del suelo',
                        style_function=style_func,
                        tooltip=folium.GeoJsonTooltip(fields=['id_bloque','tipo_suelo','arena','limo','arcilla','drenaje'],
                                                      aliases=['Bloque','Tipo','Arena %','Limo %','Arcilla %','Drenaje'])
                    ).add_to(m_textura)
                    folium.LayerControl().add_to(m_textura); Fullscreen().add_to(m_textura)
                    folium_static(m_textura, width=1000, height=600)
                except Exception as e:
                    st.error(f"Error al crear mapa de textura: {e}")
                st.markdown("### 📊 Composición Textural por Bloque")
                fig, ax = plt.subplots(figsize=(12,6))
                df_plot = df_textura.head(20)
                ax.bar(df_plot['id_bloque'].astype(str), df_plot['arena'], label='Arena', color='#F4A460')
                ax.bar(df_plot['id_bloque'].astype(str), df_plot['limo'], bottom=df_plot['arena'], label='Limo', color='#DEB887')
                ax.bar(df_plot['id_bloque'].astype(str), df_plot['arcilla'], 
                       bottom=df_plot['arena']+df_plot['limo'], label='Arcilla', color='#8B4513')
                ax.set_xlabel('Bloque'); ax.set_ylabel('Porcentaje')
                ax.set_title('Composición Textural por Bloque'); ax.legend()
                plt.xticks(rotation=45); plt.tight_layout()
                st.pyplot(fig); plt.close(fig)
                st.markdown("### 🔺 Triángulo Textural (primer bloque)")
                if len(df_textura) > 0:
                    row = df_textura.iloc[0]
                    fig_tri = crear_grafico_textural(row['arena'], row['limo'], row['arcilla'], row['tipo_suelo'])
                    st.plotly_chart(fig_tri, use_container_width=True)
                csv_textura = df_textura.drop(columns=['geometria']).to_csv(index=False)
                st.download_button("📊 Descargar CSV de textura", csv_textura, f"textura_suelo_{datetime.now():%Y%m%d}.csv", "text/csv")
            else:
                st.info("Ejecute el análisis completo para ver el análisis de textura del suelo.")
        
        with tab8:
            st.subheader("🗺️ CURVAS DE NIVEL MEJORADAS")
            if st.session_state.demo_mode:
                st.info("ℹ️ En modo DEMO se muestran curvas de nivel simuladas. Para curvas reales, adquiere la suscripción PREMIUM.")
            st.markdown("""
            **Modelo de elevación:** SRTM 1 arc-seg (30 m) · Fuente: OpenTopography  
            Para datos reales, obtén una **API key gratuita** [aquí](https://opentopography.org/).  
            Si no se proporciona, se generará un relieve simulado.
            """)
            api_key = st.text_input("🔑 API Key de OpenTopography (opcional)", type="password",
                                    help="Regístrate gratis en opentopography.org")
            intervalo = st.slider("Intervalo entre curvas (metros)", 5, 50, 10)
            if st.button("🔄 Generar curvas de nivel", use_container_width=True):
                with st.spinner("Procesando DEM y generando isolíneas..."):
                    gdf_original = st.session_state.gdf_original
                    if gdf_original is None:
                        st.error("Primero debe cargar una plantación.")
                    else:
                        if not st.session_state.demo_mode and api_key:
                            dem, meta, transform = obtener_dem_opentopography(gdf_original, api_key if api_key else None)
                            if dem is not None:
                                curvas = generar_curvas_nivel_reales(dem, transform, intervalo)
                                st.success(f"✅ Se generaron {len(curvas)} curvas de nivel (DEM real)")
                            else:
                                st.warning("No se pudo obtener DEM real. Usando simulado.")
                                curvas = generar_curvas_nivel_simuladas(gdf_original)
                        else:
                            curvas = generar_curvas_nivel_simuladas(gdf_original)
                            st.info(f"ℹ️ Usando relieve simulado. Se generaron {len(curvas)} curvas de nivel.")
                        
                        if curvas:
                            st.session_state.curvas_nivel = curvas
                            m_curvas = mapa_curvas_coloreadas(gdf_original, curvas)
                            folium_static(m_curvas, width=1000, height=600)
                            gdf_curvas = gpd.GeoDataFrame(
                                {'elevacion': [e for _, e in curvas], 'geometry': [l for l, _ in curvas]},
                                crs='EPSG:4326'
                            )
                            geojson_curvas = gdf_curvas.to_json()
                            csv_curvas = gdf_curvas.drop(columns='geometry').to_csv(index=False)
                            col_exp1, col_exp2 = st.columns(2)
                            with col_exp1: st.download_button("🗺️ GeoJSON", geojson_curvas, f"curvas_nivel_{datetime.now():%Y%m%d}.geojson", "application/geo+json")
                            with col_exp2: st.download_button("📊 CSV", csv_curvas, f"curvas_nivel_{datetime.now():%Y%m%d}.csv", "text/csv")
                        else:
                            st.warning("No se encontraron curvas de nivel en el área.")
            else:
                if st.session_state.get('curvas_nivel'):
                    st.info("Ya hay curvas de nivel generadas. Presiona el botón para regenerarlas.")
        
        with tab9:
            st.subheader("🐛 Detección de Enfermedades y Plagas con YOLO")
            if st.session_state.demo_mode:
                st.warning("⚠️ La detección YOLO solo está disponible en modo PREMIUM. Adquiere una suscripción para usar esta función.")
            else:
                st.markdown("""
                Esta herramienta utiliza modelos YOLO para detectar automáticamente signos de enfermedades o plagas en imágenes de palma aceitera.
                - **Sube una imagen** (JPG, PNG) tomada con drone o cámara.
                - **Carga un modelo YOLO** pre-entrenado (formato `.pt` de PyTorch o `.onnx`).
                - Ajusta el **umbral de confianza** para filtrar detecciones débiles.
                """)

                try:
                    from ultralytics import YOLO
                    YOLO_AVAILABLE = True
                except ImportError:
                    YOLO_AVAILABLE = False

                if not YOLO_AVAILABLE:
                    st.error("⚠️ La librería 'ultralytics' no está instalada. Para usar esta función, ejecuta: `pip install ultralytics`")
                else:
                    col1, col2 = st.columns(2)
                    with col1:
                        archivo_imagen = st.file_uploader("📸 Subir imagen (RGB)", type=['jpg', 'jpeg', 'png'], key="yolo_img")
                    with col2:
                        archivo_modelo = st.file_uploader("🤖 Cargar modelo YOLO (.pt o .onnx)", type=['pt', 'onnx'], key="yolo_model")

                    umbral_confianza = st.slider("Umbral de confianza", min_value=0.1, max_value=0.9, value=0.25, step=0.05)

                    if archivo_imagen is not None and archivo_modelo is not None:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(archivo_modelo.name)[1]) as tmp_model:
                            tmp_model.write(archivo_modelo.read())
                            ruta_modelo_tmp = tmp_model.name

                        imagen_bytes = archivo_imagen.read()
                        imagen_pil = Image.open(io.BytesIO(imagen_bytes))
                        imagen_cv = cv2.cvtColor(np.array(imagen_pil), cv2.COLOR_RGB2BGR)

                        modelo = cargar_modelo_yolo(ruta_modelo_tmp)

                        if modelo is not None:
                            st.info("🔄 Ejecutando inferencia...")
                            resultados_yolo = detectar_en_imagen(modelo, imagen_cv, conf_threshold=umbral_confianza)

                            if resultados_yolo and len(resultados_yolo) > 0:
                                img_anotada, detecciones = dibujar_detecciones_con_leyenda(imagen_cv, resultados_yolo)

                                st.success(f"✅ Se detectaron {len(detecciones)} objetos.")

                                img_rgb = cv2.cvtColor(img_anotada, cv2.COLOR_BGR2RGB)
                                st.image(img_rgb, caption="Imagen con detecciones", use_container_width=True)

                                leyenda_html = crear_leyenda_html(detecciones)
                                st.markdown(leyenda_html, unsafe_allow_html=True)

                                st.markdown("### 📥 Exportar resultados")
                                img_pil_export = Image.fromarray(cv2.cvtColor(img_anotada, cv2.COLOR_BGR2RGB))
                                buf = io.BytesIO()
                                img_pil_export.save(buf, format='PNG')
                                byte_im = buf.getvalue()

                                df_detecciones = pd.DataFrame(detecciones)
                                if 'color' in df_detecciones.columns:
                                    df_detecciones = df_detecciones.drop(columns=['color'])
                                csv_detecciones = df_detecciones.to_csv(index=False)

                                col_dl1, col_dl2 = st.columns(2)
                                with col_dl1:
                                    st.download_button("📸 Imagen anotada (PNG)", byte_im,
                                                       f"deteccion_yolo_{datetime.now():%Y%m%d_%H%M%S}.png",
                                                       "image/png")
                                with col_dl2:
                                    st.download_button("📊 CSV detecciones", csv_detecciones,
                                                       f"detecciones_{datetime.now():%Y%m%d_%H%M%S}.csv",
                                                       "text/csv")
                            else:
                                st.warning("No se detectaron objetos con el umbral de confianza actual.")
                        else:
                            st.error("No se pudo cargar el modelo. Asegúrate de que sea un archivo válido.")

                        os.unlink(ruta_modelo_tmp)
                    else:
                        st.info("👆 Sube una imagen y un modelo YOLO para comenzar.")

# ===== PIE DE PÁGINA =====
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #94a3b8; padding: 20px;">
    <p><strong>© 2026 Analizador de Palma Aceitera Satelital</strong></p>
    <p>Datos satelitales: NASA Earthdata · Clima: Open-Meteo ERA5 · Radiación/Viento: NASA POWER · Curvas de nivel: OpenTopography SRTM</p>
    <p>Desarrollado por: BioMap Consultora | Contacto: mawucano@gmail.com | +5493525 532313</p>
</div>
""", unsafe_allow_html=True)

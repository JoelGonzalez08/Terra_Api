import os
import json
import math
import ee
from google.oauth2 import service_account
from dotenv import load_dotenv
import xml.etree.ElementTree as ET
from shapely.geometry import Polygon, mapping
import re

# Cargar variables del archivo .env automáticamente
load_dotenv()

SA_EMAIL = os.getenv("EE_SERVICE_ACCOUNT_EMAIL")
SA_KEY_JSON = os.getenv("EE_SERVICE_ACCOUNT_KEY_JSON")
BASE_OUTPUT_DIR = os.getenv("BASE_OUTPUT_DIR", "./outputs")

# Crear carpeta de salida si no existe
os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)

def init_ee():
    if not SA_EMAIL or not SA_KEY_JSON:
        raise RuntimeError("Faltan EE_SERVICE_ACCOUNT_EMAIL o EE_SERVICE_ACCOUNT_KEY_JSON en .env")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(SA_KEY_JSON),
        scopes=[
            "https://www.googleapis.com/auth/earthengine.readonly",
            "https://www.googleapis.com/auth/devstorage.read_write",
            "https://www.googleapis.com/auth/drive"
        ],
        subject=SA_EMAIL
    )
    ee.Initialize(creds)

# --------- Utilidades para KML ---------
def parse_kml_to_geojson(kml_content: str):
    root = ET.fromstring(kml_content)
    coordinates_elements = []
    for elem in root.iter():
        if elem.tag.endswith('coordinates') or 'coordinates' in elem.tag:
            if elem.text and elem.text.strip():
                coordinates_elements.append(elem.text.strip())
    if not coordinates_elements:
        return {
            "success": False,
            "message": "No se encontraron coordenadas válidas en el archivo KML",
            "geometry": None,
            "features_count": 0,
            "area_hectares": 0,
            "bounds": None
        }
    features = []
    total_area = 0
    bounds = {"north": -90, "south": 90, "east": -180, "west": 180}
    for coord_text in coordinates_elements:
        try:
            coord_text = re.sub(r'\s+', ' ', coord_text.strip())
            coord_pairs = coord_text.split()
            if len(coord_pairs) < 3:
                continue
            coordinates = []
            for pair in coord_pairs:
                parts = pair.split(',')
                if len(parts) >= 2:
                    try:
                        lon = float(parts[0])
                        lat = float(parts[1])
                        coordinates.append([lon, lat])
                    except ValueError:
                        continue
            if len(coordinates) < 3:
                continue
            if coordinates[0] != coordinates[-1]:
                coordinates.append(coordinates[0])
            polygon = Polygon(coordinates)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if not polygon.is_valid:
                continue
            area_sq_degrees = polygon.area
            area_sq_meters = area_sq_degrees * 111000 * 111000
            area_hectares = area_sq_meters / 10000
            total_area += area_hectares
            geom_bounds = polygon.bounds
            bounds["west"] = min(bounds["west"], geom_bounds[0])
            bounds["south"] = min(bounds["south"], geom_bounds[1])
            bounds["east"] = max(bounds["east"], geom_bounds[2])
            bounds["north"] = max(bounds["north"], geom_bounds[3])
            geojson_geom = mapping(polygon)
            features.append({
                "type": "Feature",
                "properties": {
                    "name": f"Parcela {len(features) + 1}",
                    "description": "Extraído de archivo KML",
                    "area_hectares": round(area_hectares, 2)
                },
                "geometry": geojson_geom
            })
        except Exception as e:
            continue
    if not features:
        return {
            "success": False,
            "message": "No se pudieron procesar las coordenadas del archivo KML",
            "geometry": None,
            "features_count": 0,
            "area_hectares": 0,
            "bounds": None
        }
    main_geometry = features[0]["geometry"]
    return {
        "success": True,
        "message": f"KML procesado correctamente. {len(features)} polígono(s) encontrado(s).",
        "geometry": main_geometry,
        "features_count": len(features),
        "area_hectares": round(total_area, 2),
        "bounds": bounds,
        "features": features
    }

def composite_embedding(roi, start, end, cloud_pct=None):
    """Crea una composición de embeddings para el área y fechas especificadas"""
    col = (
        ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
        .filterBounds(roi)
        .filterDate(start, end)
    )
    # Para embeddings, tomamos la primera imagen disponible en el rango
    return col.first().clip(roi)


# --------- Función para análisis de índices ---------
def composite_embedding_with_analysis(roi, start, end, index):
    """
    Genera una imagen de análisis para el área y fechas especificadas según el índice solicitado.
    Soporta: ndvi, ndwi, evi, savi, gci, vegetation_health, water_detection, urban_index, soil_moisture, change_detection, ndmi
    """
    col = (
        ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
        .filterBounds(roi)
        .filterDate(start, end)
    )
    img = col.first()
    if img is None:
        return None

    index = index.lower()
    # Bandas de Alpha Earth Embedding
    # A01: Red, A16: NIR, A09: Green (según documentación Alpha Earth)
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))

    red = safe_band(img, 'A01')
    nir = safe_band(img, 'A16')
    green = safe_band(img, 'A09')
    blue = safe_band(img, 'A04')  # Si existe, para EVI

    # Cálculos de índices usando bandas Alpha Earth
    if index == 'ndvi':
        # NDVI = (NIR - RED) / (NIR + RED)
        result = nir.subtract(red).divide(nir.add(red)).rename('ndvi')
    elif index == 'ndwi':
        # NDWI = (Green - NIR) / (Green + NIR)
        result = green.subtract(nir).divide(green.add(nir)).rename('ndwi')
    elif index == 'evi':
        # EVI = 2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)
        result = img.expression(
            '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {
                'NIR': nir,
                'RED': red,
                'BLUE': blue
            }
        ).rename('evi')
    elif index == 'savi':
        # SAVI = ((NIR - RED) / (NIR + RED + 0.5)) * 1.5
        result = img.expression(
            '((NIR - RED) / (NIR + RED + 0.5)) * 1.5',
            {
                'NIR': nir,
                'RED': red
            }
        ).rename('savi')
    elif index == 'gci':
        # GCI = (NIR / Green) - 1
        result = nir.divide(green).subtract(1).rename('gci')
    elif index == 'vegetation_health':
        ndvi = nir.subtract(red).divide(nir.add(red))
        evi = img.expression(
            '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {
                'NIR': nir,
                'RED': red,
                'BLUE': blue
            }
        )
        result = ndvi.add(evi).divide(2).rename('vegetation_health')
    elif index == 'water_detection':
        # Water = (Green - NIR) / (Green + NIR)
        result = green.subtract(nir).divide(green.add(nir)).rename('water_detection')
    elif index == 'urban_index':
        # Urban index = (NIR - Green) / (NIR + Green)
        result = nir.subtract(green).divide(nir.add(green)).rename('urban_index')
    elif index == 'soil_moisture':
        # Soil moisture = (NIR - RED) / (NIR + RED)
        result = nir.subtract(red).divide(nir.add(red)).rename('soil_moisture')
    elif index == 'ndmi':
        # NDMI = (NIR - SWIR) / (NIR + SWIR) -- Usando bandas Alpha Earth, A16 (NIR), A12 (SWIR)
        swir = safe_band(img, 'A12')
        result = nir.subtract(swir).divide(nir.add(swir)).rename('ndmi')
    elif index == 'change_detection':
        # Cambio simple: diferencia NIR - RED
        result = nir.subtract(red).rename('change_detection')
    else:
        result = img

    return result.clip(roi)

# --------- Funciones auxiliares para series temporales ---------
def get_embedding_collection(roi, start, end):
    """Obtiene la colección de embeddings para el área y fechas especificadas"""
    return (
        ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
        .filterBounds(roi)
        .filterDate(start, end)
    )

def compute_ndvi_proxy(img):
    """Calcula NDVI usando bandas Alpha Earth"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    red = safe_band(img, 'A01')
    nir = safe_band(img, 'A16')
    ndvi = nir.subtract(red).divide(nir.add(red)).rename('ndvi')
    return img.addBands(ndvi)

def compute_ndwi_proxy(img):
    """Calcula NDWI usando bandas Alpha Earth"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    green = safe_band(img, 'A09')
    nir = safe_band(img, 'A16')
    ndwi = green.subtract(nir).divide(green.add(nir)).rename('ndwi')
    return img.addBands(ndwi)

def compute_evi_proxy(img):
    """Calcula EVI usando bandas Alpha Earth"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    red = safe_band(img, 'A01')
    nir = safe_band(img, 'A16')
    blue = safe_band(img, 'A04')
    
    evi = img.expression(
        '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
        {
            'NIR': nir,
            'RED': red,
            'BLUE': blue
        }
    ).rename('evi')
    return img.addBands(evi)

def compute_savi_proxy(img):
    """Calcula SAVI usando bandas Alpha Earth"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    red = safe_band(img, 'A01')
    nir = safe_band(img, 'A16')
    
    savi = img.expression(
        '((NIR - RED) / (NIR + RED + 0.5)) * 1.5',
        {
            'NIR': nir,
            'RED': red
        }
    ).rename('savi')
    return img.addBands(savi)

def compute_gci_proxy(img):
    """Calcula GCI usando bandas Alpha Earth"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    green = safe_band(img, 'A09')
    nir = safe_band(img, 'A16')
    gci = nir.divide(green).subtract(1).rename('gci')
    return img.addBands(gci)

def compute_vegetation_health(img):
    """Calcula salud de vegetación combinando NDVI y EVI"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    red = safe_band(img, 'A01')
    nir = safe_band(img, 'A16')
    blue = safe_band(img, 'A04')
    
    ndvi = nir.subtract(red).divide(nir.add(red))
    evi = img.expression(
        '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
        {
            'NIR': nir,
            'RED': red,
            'BLUE': blue
        }
    )
    vegetation_health = ndvi.add(evi).divide(2).rename('vegetation_health')
    return img.addBands(vegetation_health)

def compute_water_detection(img):
    """Detecta agua usando bandas Alpha Earth"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    green = safe_band(img, 'A09')
    nir = safe_band(img, 'A16')
    water_detection = green.subtract(nir).divide(green.add(nir)).rename('water_detection')
    return img.addBands(water_detection)

def compute_urban_index(img):
    """Calcula índice urbano usando bandas Alpha Earth"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    green = safe_band(img, 'A09')
    nir = safe_band(img, 'A16')
    urban_index = nir.subtract(green).divide(nir.add(green)).rename('urban_index')
    return img.addBands(urban_index)

def compute_soil_moisture(img):
    """Calcula humedad del suelo usando bandas Alpha Earth"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    red = safe_band(img, 'A01')
    nir = safe_band(img, 'A16')
    soil_moisture = nir.subtract(red).divide(nir.add(red)).rename('soil_moisture')
    return img.addBands(soil_moisture)

def compute_change_detection(img):
    """Calcula detección de cambios usando bandas Alpha Earth"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    red = safe_band(img, 'A01')
    nir = safe_band(img, 'A16')
    change_detection = nir.subtract(red).rename('change_detection')
    return img.addBands(change_detection)

def compute_ndmi_proxy(img):
    """Calcula NDMI usando bandas Alpha Earth"""
    def safe_band(img, band):
        band_names = img.bandNames()
        return ee.Image(ee.Algorithms.If(band_names.contains(band), img.select(band), ee.Image(0).rename(band)))
    
    nir = safe_band(img, 'A16')
    swir = safe_band(img, 'A12')
    ndmi = nir.subtract(swir).divide(nir.add(swir)).rename('ndmi')
    return img.addBands(ndmi)
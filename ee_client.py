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

# --------- Funciones para Sentinel-2 (Heatmaps y Series) ---------
def maskS2clouds(image):
    """
    Aplica máscara de nubes usando Scene Classification Layer (SCL)
    """
    scl = image.select('SCL')
    # Máscara para excluir: sombras(3), nubes med(8), nubes altas(9), cirrus(10), nieve/hielo(11)
    mask = (scl.neq(3)
           .And(scl.neq(8))
           .And(scl.neq(9))
           .And(scl.neq(10))
           .And(scl.neq(11)))
    return image.updateMask(mask)

def get_sentinel2_collection(roi, start, end, cloud_pct=30):
    """
    Obtiene colección Sentinel-2 con máscara de nubes aplicada
    """
    return (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
            .filterBounds(roi)
            .filterDate(start, end)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloud_pct))
            .map(maskS2clouds))

def get_sentinel2_time_series(roi, start, end, index, cloud_pct=70):
    """
    Obtiene serie temporal de cada pasada individual de Sentinel-2 (OPTIMIZADA)
    Retorna datos de cada imagen por separado con enfoque en velocidad
    """
    # Para velocidad, usar thresholds más permisivos desde el inicio
    cloud_thresholds = [min(cloud_pct, 80), 90]  # Máximo 2 intentos
    
    for threshold in cloud_thresholds:
        print(f"Intentando con threshold de nubes: {threshold}%")
        
        collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterBounds(roi)
                     .filterDate(start, end)
                     .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', threshold))
                     .sort('system:time_start')  # Ordenar por fecha desde el inicio
                     .limit(30))  # Limitar desde el filtro inicial para velocidad
        
        # Verificar si hay imágenes sin aplicar máscara
        size_before_mask = collection.size().getInfo()
        print(f"Imágenes encontradas (limitadas a 30): {size_before_mask}")
        
        if size_before_mask == 0:
            print(f"No hay imágenes con threshold {threshold}%, probando siguiente...")
            continue
            
        # Aplicar máscara de nubes más simple para velocidad
        def simple_cloud_mask(img):
            scl = img.select('SCL')
            # Solo eliminar nubes altas y cirrus (más permisivo = más rápido)
            mask = scl.neq(9).And(scl.neq(10))
            return img.updateMask(mask)
        
        collection = collection.map(simple_cloud_mask)
        
        # Verificar tamaño final
        size_after_mask = collection.size().getInfo()
        print(f"Imágenes después de máscara simple: {size_after_mask}")
        
        if size_after_mask > 0:
            print(f"Sentinel-2 Series OPTIMIZADA: Usando {size_after_mask} imágenes con threshold {threshold}%")
            break
    else:
        # Si no se encontraron imágenes con ningún threshold
        print("No se encontraron imágenes de Sentinel-2 con ningún threshold de nubes")
        return []
    
    # Función optimizada para agregar el índice específico a cada imagen
    def add_index_band_fast(img):
        # Versiones simplificadas para velocidad
        if index.lower() == 'ndvi':
            return img.addBands(img.normalizedDifference(['B8', 'B4']).rename(index))
        elif index.lower() == 'ndwi':
            return img.addBands(img.normalizedDifference(['B3', 'B8']).rename(index))
        elif index.lower() == 'ndmi':
            return img.addBands(img.normalizedDifference(['B8', 'B11']).rename(index))
        elif index.lower() == 'evi':
            # EVI simplificado
            evi = img.normalizedDifference(['B8', 'B4']).multiply(2.5).rename(index)
            return img.addBands(evi)
        elif index.lower() == 'savi':
            # SAVI simplificado
            savi = img.normalizedDifference(['B8', 'B4']).multiply(1.5).rename(index)
            return img.addBands(savi)
        else:
            # Para otros índices, usar NDVI como fallback rápido
            return img.addBands(img.normalizedDifference(['B8', 'B4']).rename(index))
    
    # Agregar banda del índice a cada imagen
    print(f"Agregando banda del índice {index} a la colección (modo rápido)...")
    processed_collection = collection.map(add_index_band_fast)
    print("Banda agregada exitosamente a todas las imágenes")
    
    # Función para extraer estadísticas de cada imagen
    def extract_stats(img):
        try:
            # Obtener estadísticas del ROI con manejo de errores
            stats = img.select(index).reduceRegion(
                reducer=ee.Reducer.mean().combine(
                    reducer2=ee.Reducer.min(), sharedInputs=True
                ).combine(
                    reducer2=ee.Reducer.max(), sharedInputs=True
                ).combine(
                    reducer2=ee.Reducer.stdDev(), sharedInputs=True
                ),
                geometry=roi,
                scale=10,  # Resolución de 10m para Sentinel-2
                maxPixels=1e9,
                bestEffort=True
            )
            
            # Obtener información temporal y de metadatos
            date = ee.Date(img.get('system:time_start'))
            cloud_cover = img.get('CLOUDY_PIXEL_PERCENTAGE')
            
            # Crear feature con manejo seguro de nombres de bandas
            mean_key = f'{index}_mean'
            min_key = f'{index}_min'
            max_key = f'{index}_max'
            stddev_key = f'{index}_stdDev'
            
            return ee.Feature(None, {
                'date': date.format('YYYY-MM-dd'),
                'datetime': date.format('YYYY-MM-dd HH:mm:ss'),
                'timestamp': img.get('system:time_start'),
                'mean': stats.get(mean_key),
                'min': stats.get(min_key),
                'max': stats.get(max_key),
                'stdDev': stats.get(stddev_key),
                'cloud_cover': cloud_cover,
                'satellite': 'Sentinel-2',
                'product_id': img.get('PRODUCT_ID'),
                'cloud_threshold_used': threshold
            })
        except Exception as e:
            print(f"Error procesando imagen individual: {str(e)}")
            # Retornar feature con valores None en caso de error
            return ee.Feature(None, {
                'date': None,
                'datetime': None,
                'timestamp': None,
                'mean': None,
                'min': None,
                'max': None,
                'stdDev': None,
                'cloud_cover': None,
                'satellite': 'Sentinel-2',
                'product_id': None,
                'cloud_threshold_used': threshold,
                'error': str(e)
            })
    
    # Extraer estadísticas de todas las imágenes
    try:
        print("Procesando estadísticas con método optimizado...")
        
        # Método simplificado: procesar imagen por imagen
        limited_collection = processed_collection.limit(30)  # Limitar para velocidad
        image_count = limited_collection.size().getInfo()
        print(f"Procesando {image_count} imágenes (limitado para velocidad)...")
        
        # Obtener lista de imágenes
        image_list = limited_collection.toList(image_count)
        
        time_series = []
        for i in range(image_count):
            try:
                img = ee.Image(image_list.get(i))
                
                # Obtener estadísticas directamente
                stats = img.select(index).reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=roi,
                    scale=60,
                    maxPixels=1e5,
                    bestEffort=True
                ).getInfo()
                
                # Obtener metadatos
                metadata = img.getInfo()
                date_ms = metadata['properties']['system:time_start']
                cloud_cover = metadata['properties'].get('CLOUDY_PIXEL_PERCENTAGE', None)
                
                # Convertir timestamp a fecha
                import datetime
                date_obj = datetime.datetime.fromtimestamp(date_ms / 1000)
                date_str = date_obj.strftime('%Y-%m-%d')
                
                # Obtener valor del índice
                mean_value = stats.get(index)
                
                if mean_value is not None:
                    time_series.append({
                        'date': date_str,
                        'datetime': date_str + ' 12:00:00',
                        'timestamp': date_ms,
                        'mean': float(mean_value),
                        'min': None,
                        'max': None,
                        'stdDev': None,
                        'cloud_cover': float(cloud_cover) if cloud_cover is not None else None,
                        'satellite': 'Sentinel-2',
                        'product_id': None,
                        'cloud_threshold_used': threshold
                    })
                    print(f"Procesada imagen {i+1}/{image_count}: {date_str}, {index}={mean_value:.4f}")
                else:
                    print(f"Imagen {i+1}/{image_count}: Sin datos válidos para {index}")
                    
            except Exception as e:
                print(f"Error procesando imagen {i+1}: {str(e)}")
                continue
        
        # Ordenar por fecha
        time_series.sort(key=lambda x: x.get('timestamp', 0))
        
        print(f"Serie temporal optimizada: {len(time_series)} puntos válidos procesados")
        return time_series
        
    except Exception as e:
        print(f"Error procesando series temporales: {str(e)}")
        import traceback
        print(f"Traceback completo: {traceback.format_exc()}")
        return []

def compute_sentinel2_index(roi, start, end, index, cloud_pct=30):
    """
    Computa índices específicos usando Sentinel-2 para heatmaps
    """
    collection = get_sentinel2_collection(roi, start, end, cloud_pct)
    
    # Si no hay imágenes, retornar None
    size = collection.size().getInfo()
    print(f"Sentinel-2 Heatmap: Encontradas {size} imágenes para composición con cloud_pct < {cloud_pct}%")
    if size == 0:
        return None
    
    if index.lower() == 'ndvi':
        # NDVI = (NIR - RED) / (NIR + RED)
        def addNDVI(img):
            ndvi = img.normalizedDifference(['B8', 'B4']).rename('ndvi')
            return img.addBands(ndvi)
        
        processed = collection.map(addNDVI)
        composite = processed.select('ndvi').median().clip(roi)
        return composite
        
    elif index.lower() == 'ndwi':
        # NDWI = (GREEN - NIR) / (GREEN + NIR)
        def addNDWI(img):
            ndwi = img.normalizedDifference(['B3', 'B8']).rename('ndwi')
            return img.addBands(ndwi)
            
        processed = collection.map(addNDWI)
        composite = processed.select('ndwi').median().clip(roi)
        return composite
        
    elif index.lower() == 'evi':
        # EVI = 2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)
        def addEVI(img):
            evi = img.expression(
                '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                {
                    'NIR': img.select('B8'),
                    'RED': img.select('B4'),
                    'BLUE': img.select('B2')
                }
            ).rename('evi')
            return img.addBands(evi)
            
        processed = collection.map(addEVI)
        composite = processed.select('evi').median().clip(roi)
        return composite
        
    elif index.lower() == 'savi':
        # SAVI = ((NIR - RED) / (NIR + RED + 0.5)) * 1.5
        def addSAVI(img):
            savi = img.expression(
                '((NIR - RED) / (NIR + RED + 0.5)) * 1.5',
                {
                    'NIR': img.select('B8'),
                    'RED': img.select('B4')
                }
            ).rename('savi')
            return img.addBands(savi)
            
        processed = collection.map(addSAVI)
        composite = processed.select('savi').median().clip(roi)
        return composite
        
    elif index.lower() == 'gci':
        # GCI = (NIR / GREEN) - 1
        def addGCI(img):
            gci = img.select('B8').divide(img.select('B3')).subtract(1).rename('gci')
            return img.addBands(gci)
            
        processed = collection.map(addGCI)
        composite = processed.select('gci').median().clip(roi)
        return composite
        
    elif index.lower() == 'vegetation_health':
        # Combinación de NDVI y EVI
        def addVegHealth(img):
            ndvi = img.normalizedDifference(['B8', 'B4'])
            evi = img.expression(
                '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                {
                    'NIR': img.select('B8'),
                    'RED': img.select('B4'),
                    'BLUE': img.select('B2')
                }
            )
            veg_health = ndvi.add(evi).divide(2).rename('vegetation_health')
            return img.addBands(veg_health)
            
        processed = collection.map(addVegHealth)
        composite = processed.select('vegetation_health').median().clip(roi)
        return composite
        
    elif index.lower() == 'water_detection':
        # Misma fórmula que NDWI pero enfocada en detección de agua
        def addWater(img):
            water = img.normalizedDifference(['B3', 'B8']).rename('water_detection')
            return img.addBands(water)
            
        processed = collection.map(addWater)
        composite = processed.select('water_detection').median().clip(roi)
        return composite
        
    elif index.lower() == 'urban_index':
        # NDBI = (SWIR - NIR) / (SWIR + NIR)
        def addUrban(img):
            urban = img.normalizedDifference(['B11', 'B8']).rename('urban_index')
            return img.addBands(urban)
            
        processed = collection.map(addUrban)
        composite = processed.select('urban_index').median().clip(roi)
        return composite
        
    elif index.lower() == 'soil_moisture':
        # NDMI = (NIR - SWIR) / (NIR + SWIR)
        def addSoilMoisture(img):
            soil_moisture = img.normalizedDifference(['B8', 'B11']).rename('soil_moisture')
            return img.addBands(soil_moisture)
            
        processed = collection.map(addSoilMoisture)
        composite = processed.select('soil_moisture').median().clip(roi)
        return composite
        
    elif index.lower() == 'ndmi':
        # NDMI = (NIR - SWIR) / (NIR + SWIR)
        def addNDMI(img):
            ndmi = img.normalizedDifference(['B8', 'B11']).rename('ndmi')
            return img.addBands(ndmi)
            
        processed = collection.map(addNDMI)
        composite = processed.select('ndmi').median().clip(roi)
        return composite
        
    elif index.lower() == 'change_detection':
        # Para detección de cambios, usamos diferencia temporal de NDVI
        def addChangeDetection(img):
            ndvi = img.normalizedDifference(['B8', 'B4'])
            return img.addBands(ndvi.rename('change_detection'))
            
        processed = collection.map(addChangeDetection)
        composite = processed.select('change_detection').median().clip(roi)
        return composite
        
    elif index.lower() == 'rgb':
        # RGB natural: R=B4, G=B3, B=B2
        composite = collection.median().select(['B4', 'B3', 'B2']).clip(roi)
        return composite
        
    else:
        # Por defecto, RGB
        composite = collection.median().select(['B4', 'B3', 'B2']).clip(roi)
        return composite
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

# Import shared config
from config import BASE_OUTPUT_DIR

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

# Import index computations from ee_indices (keeps compatibility)
from services.ee.ee_indices import compute_sentinel2_index

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
    # Si hay múltiples polígonos, construir MultiPolygon como geometría principal
    if len(features) > 1:
        try:
            from shapely.geometry import MultiPolygon
            multip = MultiPolygon([Polygon(f['geometry']['coordinates'][0]) if f['geometry']['type']=='Polygon' else Polygon(f['geometry']['coordinates'][0][0]) for f in features])
            main_geometry = mapping(multip)
        except Exception:
            main_geometry = features[0]["geometry"]
    else:
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


# --------- Funciones auxiliares para Sentinel-2 (Heatmaps y Series) ---------
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
    # For speed we use permissive thresholds and a simplified mask
    cloud_thresholds = [min(cloud_pct, 80), 90]

    for threshold in cloud_thresholds:
        collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterBounds(roi)
                     .filterDate(start, end)
                     .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', threshold))
                     .sort('system:time_start')
                     .limit(30))

        size_before_mask = collection.size().getInfo()
        if size_before_mask == 0:
            continue

        def simple_cloud_mask(img):
            scl = img.select('SCL')
            mask = scl.neq(9).And(scl.neq(10))
            return img.updateMask(mask)

        collection = collection.map(simple_cloud_mask)
        size_after_mask = collection.size().getInfo()
        if size_after_mask > 0:
            break
    else:
        return []

    def add_index_band_fast(img):
        idx = index.lower()
        if idx == 'ndvi':
            return img.addBands(img.normalizedDifference(['B8', 'B4']).rename(index))
        elif idx == 'ndwi':
            return img.addBands(img.normalizedDifference(['B3', 'B8']).rename(index))
        elif idx == 'ndmi':
            return img.addBands(img.normalizedDifference(['B8', 'B11']).rename(index))
        elif idx == 'evi':
            evi = img.normalizedDifference(['B8', 'B4']).multiply(2.5).rename(index)
            return img.addBands(evi)
        elif idx == 'savi':
            savi = img.normalizedDifference(['B8', 'B4']).multiply(1.5).rename(index)
            return img.addBands(savi)
        else:
            return img.addBands(img.normalizedDifference(['B8', 'B4']).rename(index))

    processed_collection = collection.map(add_index_band_fast)

    try:
        limited_collection = processed_collection.limit(30)
        image_count = limited_collection.size().getInfo()
        image_list = limited_collection.toList(image_count)
        time_series = []
        for i in range(image_count):
            try:
                img = ee.Image(image_list.get(i))
                stats = img.select(index).reduceRegion(reducer=ee.Reducer.mean(), geometry=roi, scale=60, maxPixels=1e5, bestEffort=True).getInfo()
                metadata = img.getInfo()
                date_ms = metadata['properties']['system:time_start']
                import datetime
                date_obj = datetime.datetime.fromtimestamp(date_ms / 1000)
                date_str = date_obj.strftime('%Y-%m-%d')
                mean_value = stats.get(index)
                if mean_value is not None:
                    # Redondear a 2 cifras significativas antes de devolver
                    try:
                        from utils_pkg.io import round_sig
                        rounded = round_sig(float(mean_value), sig=2)
                    except Exception:
                        rounded = float(mean_value)
                    time_series.append({'date': date_str, 'datetime': date_str + ' 12:00:00', 'timestamp': date_ms, 'mean': rounded})
            except Exception:
                continue
        time_series.sort(key=lambda x: x.get('timestamp', 0))
        return time_series
    except Exception:
        return []


def get_sentinel2_dates(roi, start, end, cloud_pct=100):
    """
    Obtiene todas las fechas disponibles de imágenes Sentinel-2 para una geometría.
    
    Args:
        roi: ee.Geometry - región de interés
        start: str - fecha inicio (YYYY-MM-DD)
        end: str - fecha fin (YYYY-MM-DD)
        cloud_pct: int - filtro max de cobertura de nubes (0-100), default 100 (todas)
    
    Returns:
        List[dict] - lista de diccionarios con metadata de cada imagen:
            - date: str (YYYY-MM-DD)
            - system_time_start: int (milliseconds)
            - cloud_cover: float (0-100)
            - tile_id: str (MGRS tile)
    """
    try:
        # Obtener colección sin máscara (queremos todas las fechas disponibles)
        collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                     .filterBounds(roi)
                     .filterDate(start, end)
                     .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', cloud_pct))
                     .sort('system:time_start'))
        
        # Obtener el tamaño de la colección
        size = collection.size().getInfo()
        
        if size == 0:
            return []
        
        # Convertir a lista y extraer metadata
        image_list = collection.toList(size)
        dates = []
        
        for i in range(size):
            try:
                img = ee.Image(image_list.get(i))
                props = img.getInfo()['properties']
                
                date_ms = props.get('system:time_start')
                if not date_ms:
                    continue
                
                # Convertir timestamp a fecha ISO
                import datetime
                date_obj = datetime.datetime.utcfromtimestamp(date_ms / 1000)
                date_str = date_obj.strftime('%Y-%m-%d')
                
                # Extraer metadata adicional
                cloud_cover = props.get('CLOUDY_PIXEL_PERCENTAGE')
                tile_id = props.get('MGRS_TILE', props.get('system:index'))
                
                dates.append({
                    'date': date_str,
                    'system_time_start': date_ms,
                    'cloud_cover': float(cloud_cover) if cloud_cover is not None else None,
                    'tile_id': str(tile_id) if tile_id else None
                })
            except Exception:
                # Skip imágenes con errores de metadata
                continue
        
        return dates
    
    except Exception as e:
        raise RuntimeError(f"Error obteniendo fechas de Sentinel-2: {str(e)}")


# rest of file omitted for brevity; original content preserved

import os
import math
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any
import ee
from ee_client import init_ee, composite_embedding, BASE_OUTPUT_DIR, parse_kml_to_geojson
from models import ComputeRequest, ComputeResponse, TimePoint, TimeSeriesRequest, KMLUploadResponse

def index_band_and_vis(index):
    """
    Devuelve las bandas y parámetros de visualización para cada índice soportado.
    """
    if index == "rgb":
        # Bandas RGB para Earth Embedding
        return (["A01", "A16", "A09"], {"min": 0, "max": 1})
    elif index == "ndvi":
        # Paleta NDVI personalizada
        return ("ndvi", {
            "min": -1, "max": 1,
            "palette": [
                "#8B4513",  # -1 a -0.1
                "#D2B48C",  # -0.1 a 0.1
                "#FFD700",  # 0.1 a 0.3
                "#9ACD32",  # 0.3 a 0.5
                "#32CD32",  # 0.5 a 0.7
                "#006400"   # 0.7 a 1
            ]
        })
    elif index == "ndwi":
        # Paleta NDWI personalizada
        return ("ndwi", {
            "min": -1, "max": 1,
            "palette": [
                "#8B4513",  # -1 a -0.3
                "#DEB887",  # -0.3 a -0.1
                "#F0E68C",  # -0.1 a 0.1
                "#87CEEB",  # 0.1 a 0.3
                "#4169E1",  # 0.3 a 0.6
                "#0000FF"   # 0.6 a 1
            ]
        })
    elif index == "evi":
        # Paleta EVI personalizada
        return ("evi", {
            "min": -1, "max": 1,
            "palette": [
                "#8B4513",  # -1 a 0
                "#D2B48C",  # 0 a 0.2
                "#FFD700",  # 0.2 a 0.4
                "#9ACD32",  # 0.4 a 0.6
                "#32CD32",  # 0.6 a 0.8
                "#006400"   # 0.8 a 1
            ]
        })
    elif index == "savi":
        # Paleta SAVI personalizada
        return ("savi", {
            "min": -1, "max": 1,
            "palette": [
                "#8B4513",  # -1 a 0
                "#D2B48C",  # 0 a 0.15
                "#FFD700",  # 0.15 a 0.3
                "#9ACD32",  # 0.3 a 0.45
                "#32CD32",  # 0.45 a 0.6
                "#006400"   # 0.6 a 1
            ]
        })
    elif index == "ndmi":
        # Paleta NDMI sugerida (puedes ajustar los colores si lo deseas)
        return ("ndmi", {
            "min": -1, "max": 1,
            "palette": [
                "#8B4513",  # -1 a -0.3 (muy seco)
                "#DEB887",  # -0.3 a -0.1 (seco)
                "#F0E68C",  # -0.1 a 0.1 (moderado)
                "#87CEEB",  # 0.1 a 0.3 (húmedo)
                "#4169E1",  # 0.3 a 0.6 (muy húmedo)
                "#0000FF"   # 0.6 a 1 (agua/saturado)
            ]
        })
    elif index == "gci":
        return ("gci", {"min": -1, "max": 1, "palette": ["red", "white", "green"]})
    elif index == "vegetation_health":
        return ("vegetation_health", {"min": 0, "max": 1, "palette": ["red", "yellow", "green"]})
    elif index == "water_detection":
        return ("water_detection", {"min": 0, "max": 1, "palette": ["white", "blue"]})
    elif index == "urban_index":
        return ("urban_index", {"min": 0, "max": 1, "palette": ["white", "gray", "black"]})
    elif index == "soil_moisture":
        return ("soil_moisture", {"min": 0, "max": 1, "palette": ["yellow", "brown", "blue"]})
    elif index == "change_detection":
        return ("change_detection", {"min": -1, "max": 1, "palette": ["red", "white", "green"]})
    else:
        # Fallback a RGB
        return (["A01", "A16", "A09"], {"min": 0, "max": 1})

load_dotenv()
app = FastAPI(title="GEE FastAPI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def meters_to_degrees(lon, lat, width_m, height_m):
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(lat))
    half_width_deg = (width_m / 2) / meters_per_deg_lon
    half_height_deg = (height_m / 2) / meters_per_deg_lat
    return [
        lon - half_width_deg, lat - half_height_deg,
        lon + half_width_deg, lat + half_height_deg
    ]

def make_roi_from_geojson(geometry):
    return ee.Geometry(geometry)

def make_roi(lon, lat, width_m, height_m):
    return ee.Geometry.Rectangle(meters_to_degrees(lon, lat, width_m, height_m))

def ensure_outputs_dir():
    os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)

@app.on_event("startup")
def _startup():
    init_ee()
    ensure_outputs_dir()

@app.get("/")
def root():
    return {
        "message": "Terra API - Google Earth Engine Alpha Embedding",
        "status": "active",
        "available_analyses": [
            "rgb", "ndvi", "ndwi", "evi", "savi", "gci", "vegetation_health",
            "water_detection", "urban_index", "soil_moisture", "change_detection"
        ],
        "endpoints": {
            "/": "Información de la API",
            "/health": "Estado de la conexión con Earth Engine",
            "/upload-kml": "Subir archivo KML de parcelas (POST)",
            "/time-series": "Análisis de series temporales (POST)",
            "/compute": "Análisis de heatmaps y exports (POST)"
        },
        "docs": "/docs"
    }

@app.get("/health")
def health():
    try:
        _ = ee.Date('2020-01-01').format().getInfo()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.post("/upload-kml")
async def upload_kml(file: UploadFile = File(...)):
    """
    Endpoint para subir archivos KML que representen polígonos de parcelas.
    
    El archivo KML debe contener uno o más polígonos que definan las áreas de interés.
    Retorna la geometría en formato GeoJSON compatible con Earth Engine.
    """
    try:
        # Validar tipo de archivo
        if not file.filename.lower().endswith('.kml'):
            raise HTTPException(
                status_code=400, 
                detail="El archivo debe tener extensión .kml"
            )
        
        # Leer contenido del archivo
        content = await file.read()
        kml_content = content.decode('utf-8')
        
        # Procesar KML y convertir a GeoJSON
        result = parse_kml_to_geojson(kml_content)
        
        if not result["success"]:
            raise HTTPException(
                status_code=400,
                detail=result["message"]
            )
        
        # Retornar directamente el diccionario para evitar problemas con Pydantic
        return {
            "success": result["success"],
            "message": result["message"],
            "geometry": result["geometry"],
            "features_count": result["features_count"],
            "area_hectares": result["area_hectares"],
            "bounds": result["bounds"]
        }
        
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Error al decodificar el archivo KML. Asegúrate de que sea un archivo de texto válido."
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error procesando archivo KML: {str(e)}"
        )


@app.post("/time-series")
def get_time_series(req: TimeSeriesRequest):
    """
    Endpoint principal para series temporales mensuales usando Sentinel-2
    Basado en el enfoque mensual de Google Earth Engine que funciona correctamente
    """
    try:
        init_ee()
        
        # Crear ROI
        if req.geometry:
            roi = make_roi_from_geojson(req.geometry)
        else:
            roi = make_roi(req.lon, req.lat, req.width_m, req.height_m)
        
        # Colección base Sentinel-2
        s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
              .filterBounds(roi)
              .filterDate(req.start, req.end))
        
        # Máscara de nubes SCL (Scene Classification Layer)
        def maskS2SCL(img):
            scl = img.select('SCL')
            good = (scl.neq(3)    # shadow
                   .And(scl.neq(8))   # cloud medium probability  
                   .And(scl.neq(9))   # cloud high probability
                   .And(scl.neq(10))  # cirrus
                   .And(scl.neq(11))) # snow/ice
            return img.updateMask(good)
        
        # Seleccionar función de índice según el parámetro
        if req.index == "ndvi":
            def addIndex(img):
                return img.addBands(img.normalizedDifference(['B8','B4']).rename('INDEX'))
        elif req.index == "gci":
            def addIndex(img):
                nir = img.select('B8')
                green = img.select('B3')
                return img.addBands(nir.divide(green).subtract(1).rename('INDEX'))
        elif req.index == "ndwi":
            def addIndex(img):
                return img.addBands(img.normalizedDifference(['B3','B8']).rename('INDEX'))
        elif req.index == "evi":
            def addIndex(img):
                nir = img.select('B8')
                red = img.select('B4')
                blue = img.select('B2')
                evi = nir.subtract(red).multiply(2.5).divide(
                    nir.add(red.multiply(6)).subtract(blue.multiply(7.5)).add(1)
                ).rename('INDEX')
                return img.addBands(evi)
        elif req.index == "savi":
            def addIndex(img):
                nir = img.select('B8')
                red = img.select('B4')
                savi = nir.subtract(red).multiply(1.5).divide(
                    nir.add(red).add(0.5)
                ).rename('INDEX')
                return img.addBands(savi)
        elif req.index == "rgb":
            def addIndex(img):
                # Para RGB usamos banda roja como proxy
                return img.addBands(img.select('B4').rename('INDEX'))
        else:
            # Fallback a NDVI
            def addIndex(img):
                return img.addBands(img.normalizedDifference(['B8','B4']).rename('INDEX'))
        
        # Aplicar máscara e índice
        s2prep = s2.map(maskS2SCL).map(addIndex)
        
        # Procesar cada mes manualmente (método que funciona)
        start_date = ee.Date(req.start)
        end_date = ee.Date(req.end)
        
        time_series = []
        
        # Iterar por cada mes
        current_date = start_date
        while current_date.difference(end_date, 'month').getInfo() < 0:
            month_end = current_date.advance(1, 'month')
            
            # Filtrar imágenes del mes
            monthly_imgs = s2prep.filterDate(current_date, month_end)
            img_count = monthly_imgs.size().getInfo()
            
            if img_count > 0:
                # Crear composición mensual (promedio)
                composite = monthly_imgs.select('INDEX').mean()
                
                # Extraer estadísticas de la región
                stats = composite.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=roi,
                    scale=10,
                    bestEffort=True,
                    maxPixels=1e6
                )
                
                index_value = stats.get('INDEX').getInfo()
                
                if index_value is not None:
                    time_series.append({
                        'date': current_date.format('YYYY-MM').getInfo(),
                        'year': int(current_date.get('year').getInfo()),
                        'month': int(current_date.get('month').getInfo()),
                        'mean': float(index_value),
                        'image_count': img_count,
                        'min': None,  # Se puede implementar con otros reductores
                        'max': None,
                        'std': None,
                        'pixels': None
                    })
            
            # Avanzar al siguiente mes
            current_date = month_end
        
        if not time_series:
            raise HTTPException(status_code=404, detail="No se encontraron datos válidos para el análisis especificado")
        
        # Calcular estadísticas resumen del período
        values = [point['mean'] for point in time_series]
        total_images = sum([point['image_count'] for point in time_series])
        
        summary_stats = {
            "total_points": len(time_series),
            "valid_points": len(values),
            "period_mean": sum(values) / len(values),
            "period_min": min(values),
            "period_max": max(values),
            "total_images_used": total_images,
            "data_source": "Sentinel-2 SR Harmonized (Monthly Composites)",
            "composite_method": "mean",
            "cloud_mask": "SCL (Scene Classification Layer)",
            "trend": "increasing" if len(values) > 1 and values[-1] > values[0] else "decreasing" if len(values) > 1 else "stable"
        }
        
        return {
            "analysis_type": req.index,
            "roi": roi.getInfo(),
            "date_range": {"start": req.start, "end": req.end},
            "time_series": time_series,
            "summary": summary_stats
        }
        
    except ee.EEException as eex:
        raise HTTPException(status_code=500, detail=f"Earth Engine error: {str(eex)}")
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Error generando serie temporal: {str(ex)}")

# ---------- core endpoint ----------
@app.post("/compute", response_model=ComputeResponse)
def compute(req: ComputeRequest):
    """
    Endpoint principal para heatmaps y export usando Alpha Earth Embedding.
    
    Nota: Para series temporales se recomienda usar el endpoint /time-series 
    que utiliza Sentinel-2 y permite fechas personalizadas.
    """
    try:
        # Permitir ROI por GeoJSON o por lon/lat/width/height
        if req.geometry:
            roi = make_roi_from_geojson(req.geometry)
        else:
            # Validar que todos los campos estén presentes y sean válidos
            missing = []
            for field in ["lon", "lat", "width_m", "height_m"]:
                if getattr(req, field) is None:
                    missing.append(field)
            if missing:
                raise HTTPException(status_code=400, detail=f"Faltan los campos requeridos: {', '.join(missing)}")
            roi = make_roi(req.lon, req.lat, req.width_m, req.height_m)
        # Validar que roi sea un ee.Geometry válido antes de convertir a GeoJSON
        if not isinstance(roi, ee.Geometry):
            raise HTTPException(status_code=500, detail="No se pudo construir la geometría del área de interés (ROI)")

        # Determinar el tipo de análisis a realizar
        band, vis = index_band_and_vis(req.index)
        
        # Para análisis que requieren cálculos especiales
        if req.index in ["ndvi", "ndwi", "evi", "savi", "gci", "vegetation_health", 
                        "water_detection", "urban_index", "soil_moisture", "change_detection"]:
            from ee_client import composite_embedding_with_analysis
            img = composite_embedding_with_analysis(roi, req.start, req.end, req.index)
            if img is None:
                raise HTTPException(status_code=404, detail="No se encontraron imágenes de embedding para el rango de fechas especificado")
            layer = img.select(band)
        else:
            # Para RGB o análisis simples
            dataset = ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
            img = dataset.filterDate(req.start, req.end).filterBounds(roi).first()
            
            if img is None:
                raise HTTPException(status_code=404, detail="No se encontraron imágenes de embedding para el rango de fechas especificado")
                
            img = img.clip(roi)
            
            if req.index == "rgb":
                # Para RGB, seleccionar las 3 bandas y verificar que existan
                try:
                    layer = img.select(band)  # band será ["A01", "A16", "A09"]
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Error seleccionando bandas RGB {band}: {str(e)}")
            else:
                # Para otros casos
                layer = img.select(band)

        # MODO HEATMAP: devolver plantilla de tiles XYZ (para React/Leaflet/Native)
        if req.mode == "heatmap":
            try:
                m = layer.getMapId(vis)
                return ComputeResponse(
                    mode=req.mode, index=req.index,
                    roi=roi.getInfo(),
                    tileUrlTemplate=m['tile_fetcher'].url_format,
                    vis=vis
                )
            except Exception as e:
                import logging
                logging.error(f"Error generando mapa: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Error generando heatmap: {str(e)}")

        # MODO SERIES: promedio por fecha dentro del ROI (serie temporal)
        if req.mode == "series":
            import logging
            
            # Para análisis que requieren cálculos especiales
            if req.index in ["ndvi", "ndwi", "evi", "savi", "gci", "vegetation_health",
                            "water_detection", "urban_index", "soil_moisture", "change_detection"]:
                from ee_client import get_embedding_collection
                from ee_client import (compute_ndvi_proxy, compute_ndwi_proxy, compute_evi_proxy, 
                                     compute_savi_proxy, compute_gci_proxy, compute_vegetation_health, compute_water_detection,
                                     compute_urban_index, compute_soil_moisture, compute_change_detection)
                
                col = get_embedding_collection(roi, req.start, req.end)
                count_imgs = col.size().getInfo()
                logging.warning(f"[GEE] Imágenes de embedding en la colección: {count_imgs}")
                
                # Aplicar el análisis específico a cada imagen
                analysis_functions = {
                    "ndvi": compute_ndvi_proxy,
                    "ndwi": compute_ndwi_proxy,
                    "evi": compute_evi_proxy,
                    "savi": compute_savi_proxy,
                    "gci": compute_gci_proxy,
                    "vegetation_health": compute_vegetation_health,
                    "water_detection": compute_water_detection,
                    "urban_index": compute_urban_index,
                    "soil_moisture": compute_soil_moisture,
                    "change_detection": compute_change_detection
                }
                
                processed_col = col.map(analysis_functions[req.index])
                band, vis = index_band_and_vis(req.index)
                sel = processed_col.select(band)
            else:
                # Para RGB o análisis simples
                dataset = ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
                col = dataset.filterDate(req.start, req.end).filterBounds(roi)
                count_imgs = col.size().getInfo()
                logging.warning(f"[GEE] Imágenes de embedding en la colección: {count_imgs}")
                
                band, vis = index_band_and_vis(req.index)
                if req.index == "rgb":
                    # Para RGB, usar la primera banda como referencia
                    band = band[0]  # A01
                
                sel = col.select(band)
            
            def per_img(i):
                stat = i.select(band).reduceRegion(
                    ee.Reducer.mean()
                    .combine(reducer2=ee.Reducer.min(), sharedInputs=True)
                    .combine(reducer2=ee.Reducer.max(), sharedInputs=True),
                    roi, 60)
                return ee.Feature(None, {
                    'date': ee.Date(i.get('system:time_start')).format('YYYY-MM-dd'),
                    'mean': stat.get(f'{band}_mean'),
                    'min': stat.get(f'{band}_min'),
                    'max': stat.get(f'{band}_max')
                })
            fc = ee.FeatureCollection(sel.map(per_img))
            arr = fc.aggregate_array('properties').getInfo()
            logging.warning(f"[GEE] Resultados de la serie (incluyendo None): {arr}")
            # Mostrar todos los valores, incluso None, en la respuesta
            series = arr  # [{date, mean, min, max}, ...]
            return ComputeResponse(
                mode=req.mode, index=req.index,
                roi=roi.getInfo(),
                series=series
            )

        # MODO EXPORT: guardar GeoTIFF + CSV en ./outputs
        if req.mode == "export":
            ensure_outputs_dir()
            ts = int(time.time())
            base = f"{req.index}_{req.start}_{req.end}_{ts}"
            geotiff_path = Path(BASE_OUTPUT_DIR) / f"{base}.tif"
            csv_path = Path(BASE_OUTPUT_DIR) / f"{base}.csv"

            # 1) GeoTIFF (descarga directa con getDownloadURL)
            url = layer.getDownloadURL({
                'scale': 30,  # Earth Embedding tiene resolución de 30m
                'region': roi,
                'format': 'GEO_TIFF',
                'crs': 'EPSG:4326'
            })
            def download_url_to(path, url):
                import requests
                response = requests.get(url, stream=True)
                response.raise_for_status()
                with open(path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            download_url_to(geotiff_path, url)

            # 2) Serie temporal → CSV (fecha, mean, min, max)
            if req.index in ["ndvi", "ndwi", "evi", "savi", "gci", "vegetation_health",
                            "water_detection", "urban_index", "soil_moisture", "change_detection"]:
                from ee_client import get_embedding_collection
                from ee_client import (compute_ndvi_proxy, compute_ndwi_proxy, compute_evi_proxy,
                                     compute_savi_proxy, compute_gci_proxy, compute_vegetation_health, compute_water_detection,
                                     compute_urban_index, compute_soil_moisture, compute_change_detection)
                
                col = get_embedding_collection(roi, req.start, req.end)
                
                # Aplicar el análisis específico
                analysis_functions = {
                    "ndvi": compute_ndvi_proxy,
                    "ndwi": compute_ndwi_proxy,
                    "evi": compute_evi_proxy,
                    "savi": compute_savi_proxy,
                    "gci": compute_gci_proxy,
                    "vegetation_health": compute_vegetation_health,
                    "water_detection": compute_water_detection,
                    "urban_index": compute_urban_index,
                    "soil_moisture": compute_soil_moisture,
                    "change_detection": compute_change_detection
                }
                
                processed_col = col.map(analysis_functions[req.index])
                band, vis = index_band_and_vis(req.index)
                sel = processed_col.select(band)
            else:
                # Para RGB o análisis simples
                dataset = ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
                col = dataset.filterDate(req.start, req.end).filterBounds(roi)
                band, vis = index_band_and_vis(req.index)
                if req.index == "rgb":
                    band = band[0]  # Usar primera banda como referencia
                sel = col.select(band)

            def per_img(i):
                stat = i.select(band).reduceRegion(
                    ee.Reducer.mean()
                    .combine(reducer2=ee.Reducer.min(), sharedInputs=True)
                    .combine(reducer2=ee.Reducer.max(), sharedInputs=True),
                    roi, 30)
                return ee.Feature(None, {
                    'date': ee.Date(i.get('system:time_start')).format('YYYY-MM-dd'),
                    f'{band}_mean': stat.get(f'{band}_mean'),
                    f'{band}_min': stat.get(f'{band}_min'),
                    f'{band}_max': stat.get(f'{band}_max')
                })
            fc = ee.FeatureCollection(sel.map(per_img))
            url_table = fc.getDownloadURL('csv')
            download_url_to(csv_path, url_table)

            return ComputeResponse(
                mode=req.mode, index=req.index,
                roi=roi.getInfo(),
                saved_files={'geotiff': str(geotiff_path), 'csv': str(csv_path)}
            )

        raise HTTPException(status_code=400, detail="mode inválido")

    except ee.EEException as eex:
        raise HTTPException(status_code=500, detail=f"EarthEngine error: {str(eex)}")
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))

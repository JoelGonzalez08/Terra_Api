import os
import math
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from auth_models import UserLoginRequest, UserLoginResponse, UserInfoResponse
from auth_utils import authenticate_user, create_access_token, get_user_by_id
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any
import ee
from ee_client import init_ee, composite_embedding, BASE_OUTPUT_DIR, parse_kml_to_geojson
import uuid
import pathlib
from models import ComputeRequest, ComputeResponse, TimePoint, TimeSeriesRequest, KMLUploadResponse

def index_band_and_vis(index, satellite="sentinel2"):
    """
    Devuelve las bandas y parámetros de visualización para cada índice soportado.
    satellite: "sentinel2" para heatmaps, "alpha_earth" para series y export
    """
    if index == "rgb":
        if satellite == "sentinel2":
            return (["B4", "B3", "B2"], {"min": 0, "max": 3000})
        else:
            # Alpha Earth Embedding
            return (["A01", "A16", "A09"], {"min": 0, "max": 1})
    elif index == "ndvi":
        # Paleta NDVI más pronunciada y contrastada
        return ("ndvi", {
            "min": -1, "max": 1,
            "palette": [
                '#8B0000',  # rojo intenso (valores muy bajos, sin vegetación)
                '#FF4500',  # naranja rojizo
                '#FFD700',  # amarillo dorado
                '#ADFF2F',  # verde amarillento
                '#32CD32',  # verde lima
                '#228B22',  # verde bosque
                '#006400'   # verde oscuro intenso (vegetación muy densa)
            ]
        })
    elif index == "ndwi":
        # Paleta NDWI más pronunciada (tierra seca a agua)
        return ("ndwi", {
            "min": -1, "max": 1,
            "palette": [
                '#8B4513',  # marrón tierra seca
                '#D2691E',  # chocolate
                '#F4A460',  # arena
                '#FFFF99',  # amarillo claro
                '#87CEEB',  # azul cielo
                '#4169E1',  # azul real
                '#0000CD',  # azul medio
                '#000080'   # azul marino (agua profunda)
            ]
        })
    elif index == "evi":
        # Paleta EVI más pronunciada
        return ("evi", {
            "min": -1, "max": 1,
            "palette": [
                '#8B0000',  # rojo oscuro
                '#FF0000',  # rojo puro
                '#FF8C00',  # naranja oscuro
                '#FFD700',  # oro
                '#ADFF2F',  # verde amarillo
                '#32CD32',  # verde lima
                '#228B22',  # verde bosque
                '#004225'   # verde muy oscuro
            ]
        })
    elif index == "savi":
        # Paleta SAVI más pronunciada
        return ("savi", {
            "min": -1, "max": 1,
            "palette": [
                '#800000',  # granate
                '#DC143C',  # carmesí
                '#FF6347',  # tomate
                '#FFA500',  # naranja
                '#FFD700',  # dorado
                '#9ACD32',  # verde amarillo
                '#32CD32',  # verde lima
                '#228B22'   # verde bosque
            ]
        })
    elif index == "ndmi":
        # Paleta NDMI más pronunciada (seco a húmedo)
        return ("ndmi", {
            "min": -1, "max": 1,
            "palette": [
                '#8B0000',  # rojo oscuro (muy seco)
                '#CD853F',  # marrón claro
                '#F0E68C',  # caqui
                '#FFFF00',  # amarillo puro
                '#ADFF2F',  # verde amarillo
                '#00CED1',  # turquesa
                '#1E90FF',  # azul dodger
                '#0000FF'   # azul puro (muy húmedo/agua)
            ]
        })
    elif index == "gci":
        # Paleta GCI más pronunciada (clorofila)
        return ("gci", {
            "min": -1, "max": 1,
            "palette": [
                '#8B0000',  # rojo oscuro (sin clorofila)
                '#FF6347',  # tomate
                '#FFA500',  # naranja
                '#FFD700',  # dorado
                '#ADFF2F',  # verde amarillo
                '#32CD32',  # verde lima
                '#228B22',  # verde bosque
                '#006400'   # verde oscuro (alta clorofila)
            ]
        })
    elif index == "vegetation_health":
        # Paleta de salud de vegetación más pronunciada
        return ("vegetation_health", {
            "min": 0, "max": 1,
            "palette": [
                '#8B0000',  # rojo intenso (vegetación enferma)
                '#FF4500',  # naranja rojizo
                '#FFD700',  # dorado (salud moderada)
                '#ADFF2F',  # verde amarillo
                '#00FF00'   # verde brillante (vegetación sana)
            ]
        })
    elif index == "water_detection":
        # Paleta de detección de agua más pronunciada
        return ("water_detection", {
            "min": 0, "max": 1,
            "palette": [
                '#FFFFFF',  # blanco puro (sin agua)
                '#87CEEB',  # azul cielo claro
                '#4169E1',  # azul real
                '#0000FF'   # azul puro (agua)
            ]
        })
    elif index == "urban_index":
        # Paleta urbana más pronunciada
        return ("urban_index", {
            "min": 0, "max": 1,
            "palette": [
                '#FFFFFF',  # blanco (natural)
                '#C0C0C0',  # plata
                '#808080',  # gris
                '#000000'   # negro (urbano intenso)
            ]
        })
    elif index == "soil_moisture":
        # Paleta de humedad del suelo más pronunciada
        return ("soil_moisture", {
            "min": 0, "max": 1,
            "palette": [
                '#FFFF00',  # amarillo brillante (seco)
                '#FFA500',  # naranja
                '#8B4513',  # marrón (húmedo)
                '#0000FF'   # azul intenso (saturado)
            ]
        })
    elif index == "change_detection":
        # Paleta de detección de cambios más pronunciada
        return ("change_detection", {
            "min": -1, "max": 1,
            "palette": [
                '#FF0000',  # rojo puro (pérdida)
                '#FFFFFF',  # blanco (sin cambio)
                '#00FF00'   # verde puro (ganancia)
            ]
        })
    else:
        # Fallback a RGB
        if satellite == "sentinel2":
            return (["B4", "B3", "B2"], {"min": 0, "max": 3000})
        else:
            return (["A01", "A16", "A09"], {"min": 0, "max": 1})

load_dotenv()

# --- Auth config ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

def get_current_user(token: str = Depends(oauth2_scheme)):
    from jose import JWTError, jwt
    from auth_utils import SECRET_KEY, ALGORITHM
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

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
    """Versión que solo retorna la geometría (para compatibilidad)"""
    return ee.Geometry.Rectangle(meters_to_degrees(lon, lat, width_m, height_m))

def ensure_outputs_dir():
    os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)

@app.on_event("startup")
def _startup():
    init_ee()
    ensure_outputs_dir()

# --- Login endpoint ---
@app.post("/login", response_model=UserLoginResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    access_token = create_access_token(data={"sub": user["id"]})
    return UserLoginResponse(
        id=user["id"],
        username=user["username"],
        role=user["role"],
        access_token=access_token,
        token_type="bearer"
    )

# --- User info endpoint ---
@app.get("/user", response_model=UserInfoResponse)
def get_user_info(current_user: dict = Depends(get_current_user)):
    return UserInfoResponse(
        id=current_user["id"],
        username=current_user["username"],
        role=current_user["role"]
    )

@app.get("/")
def root():
    return {
        "message": "Terra API - Google Earth Engine con Sentinel-2 (Heatmaps) y Alpha Earth (Series/Export)",
        "status": "active",
        "data_sources": {
            "heatmaps": "Sentinel-2 SR Harmonized - Procesamiento en tiempo real con máscara de nubes SCL",
            "time_series": "Sentinel-2 SR Harmonized - Composiciones mensuales", 
            "export": "Alpha Earth Embedding - Datos pre-procesados"
        },
        "available_analyses": [
            "rgb", "ndvi", "ndwi", "evi", "savi", "gci", "vegetation_health",
            "water_detection", "urban_index", "soil_moisture", "change_detection", "ndmi"
        ],
        "endpoints": {
            "/": "Información de la API",
            "/login": "Autenticación de usuario (POST)",
            "/user": "Información del usuario (GET - requiere token)",
            "/health": "Estado de la conexión con Earth Engine",
            "/upload-kml": "Subir archivo KML de parcelas (POST)",
            "/time-series": "Análisis de series temporales con Sentinel-2 (POST)",
            "/compute": "Análisis de heatmaps con Sentinel-2 y exports con Alpha Earth (POST)"
        },
        "docs": "/docs",
        "authentication": {
            "required": True,
            "method": "Bearer Token",
            "demo_users": {
                "admin": "admin123",
                "cliente": "cliente123", 
                "tecnico": "tecnico123"
            }
        }
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
        
        # Guardar geometría en disco para referencia posterior (/compute)
        kml_dir = pathlib.Path(BASE_OUTPUT_DIR) / 'kml_uploads'
        kml_dir.mkdir(parents=True, exist_ok=True)
        kml_id = str(uuid.uuid4())
        geojson_path = kml_dir / f"{kml_id}.geojson"
        with open(geojson_path, 'w', encoding='utf-8') as fh:
            json.dump({
                'type': 'FeatureCollection',
                'features': result.get('features', [])
            }, fh, ensure_ascii=False)

        # Retornar info incluyendo kml_id que el cliente puede pasar a /compute
        return {
            "success": result["success"],
            "message": result["message"],
            "geometry": result["geometry"],
            "features_count": result["features_count"],
            "area_hectares": result["area_hectares"],
            "bounds": result["bounds"],
            "kml_id": kml_id
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
    Endpoint para series temporales con datos de cada pasada individual de Sentinel-2
    Retorna datos de cada imagen por separado (no composiciones mensuales)
    """
    import logging
    import traceback
    
    # Configurar logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Iniciando serie temporal para índice: {req.index}")
        logger.info(f"Rango de fechas: {req.start} - {req.end}")
        
        init_ee()
        logger.info("Earth Engine inicializado correctamente")
        
        # Crear ROI
        if req.geometry:
            roi = make_roi_from_geojson(req.geometry)
            logger.info("ROI creado desde geometría GeoJSON")
        else:
            roi = make_roi(req.lon, req.lat, req.width_m, req.height_m)
            logger.info(f"ROI creado desde coordenadas: {req.lon}, {req.lat}")
        
        # Obtener parámetro de nubosidad desde el request o usar default
        cloud_pct = getattr(req, 'cloud_pct', 70)  # Más permisivo para series temporales
        logger.info(f"Usando threshold de nubes: {cloud_pct}%")
        
        # Usar la nueva función de series temporales individuales
        from ee_client import get_sentinel2_time_series
        logger.info("Función get_sentinel2_time_series importada")
        
        logger.info("Iniciando procesamiento de series temporales...")
        series_data = get_sentinel2_time_series(roi, req.start, req.end, req.index, cloud_pct)
        logger.info(f"Series temporales procesadas: {len(series_data) if series_data else 0} puntos")
        
        if not series_data:
            logger.warning("No se encontraron datos de series temporales")
            raise HTTPException(
                status_code=404, 
                detail=f"No se encontraron imágenes de Sentinel-2 para el índice {req.index} en el rango {req.start} - {req.end}"
            )
        
        # Calcular estadísticas de resumen
        logger.info("Calculando estadísticas de resumen...")
        values = [point['mean'] for point in series_data if point.get('mean') is not None]
        total_images = len(series_data)
        logger.info(f"Valores válidos encontrados: {len(values)} de {total_images}")
        
        if values:
            summary_stats = {
                "total_points": total_images,
                "valid_points": len(values),
                "period_mean": sum(values) / len(values),
                "period_min": min(values),
                "period_max": max(values),
                "total_images_used": total_images,
                "data_source": "Sentinel-2 SR Harmonized (Individual Passes)",
                "temporal_resolution": "5-day average revisit",
                "cloud_mask": "SCL (Scene Classification Layer)",
                "cloud_threshold": f"< {cloud_pct}%",
                "trend": "increasing" if len(values) > 1 and values[-1] > values[0] else "decreasing" if len(values) > 1 else "stable",
                "date_range_coverage": {
                    "first_image": series_data[0]['date'] if series_data else None,
                    "last_image": series_data[-1]['date'] if series_data else None
                }
            }
        else:
            summary_stats = {
                "total_points": 0,
                "valid_points": 0,
                "period_mean": None,
                "period_min": None,
                "period_max": None,
                "total_images_used": 0,
                "data_source": "Sentinel-2 SR Harmonized (Individual Passes)",
                "cloud_threshold": f"< {cloud_pct}%",
                "trend": "no_data"
            }
        
        logger.info("Preparando respuesta final...")
        response = {
            "analysis_type": req.index,
            "roi": roi.getInfo(),
            "date_range": {"start": req.start, "end": req.end},
            "time_series": series_data,
            "summary": summary_stats
        }
        
        logger.info("Serie temporal completada exitosamente")
        return response
        
    except HTTPException as he:
        logger.error(f"HTTPException: {he.detail}")
        raise he
    except Exception as ex:
        logger.error(f"Error inesperado en series temporales: {str(ex)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
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
        # Permitir ROI por kml_id (guardado), GeoJSON o por lon/lat/width/height
        roi_bounds = None  # Para almacenar coordenadas exactas del rectángulo

        # 1) si se proporcionó kml_id, cargar la geojson guardada
        if getattr(req, 'kml_id', None):
            try:
                kml_dir = Path(BASE_OUTPUT_DIR) / 'kml_uploads'
                geojson_path = kml_dir / f"{req.kml_id}.geojson"
                if not geojson_path.exists():
                    raise HTTPException(status_code=404, detail='kml_id no encontrado')
                with open(geojson_path, 'r', encoding='utf-8') as fh:
                    fc = json.load(fh)
                if not fc.get('features'):
                    raise HTTPException(status_code=400, detail='GeoJSON guardado inválido')
                geom = fc['features'][0]['geometry']
                roi = make_roi_from_geojson(geom)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f'Error cargando kml guardado: {str(e)}')

        # 2) fallback a geometry en la request
        elif req.geometry:
            roi = make_roi_from_geojson(req.geometry)
        else:
            # Validar que todos los campos estén presentes y sean válidos
            missing = []
            for field in ["lon", "lat", "width_m", "height_m"]:
                if getattr(req, field) is None:
                    missing.append(field)
            if missing:
                raise HTTPException(status_code=400, detail=f"Faltan los campos requeridos: {', '.join(missing)}")

            # Obtener ROI y coordenadas exactas
            roi_bounds = meters_to_degrees(req.lon, req.lat, req.width_m, req.height_m)
            roi = ee.Geometry.Rectangle(roi_bounds)
            
        # Validar que roi sea un ee.Geometry válido antes de convertir a GeoJSON
        if not isinstance(roi, ee.Geometry):
            raise HTTPException(status_code=500, detail="No se pudo construir la geometría del área de interés (ROI)")

        # Determinar el tipo de análisis a realizar
        band, vis = index_band_and_vis(req.index, satellite="sentinel2")
        
        # Para heatmaps, usar Sentinel-2
        if req.mode == "heatmap":
            from ee_client import compute_sentinel2_index
            # Obtener parámetro de nubosidad, default 30% para heatmaps
            cloud_pct = getattr(req, 'cloud_pct', 30)
            img = compute_sentinel2_index(roi, req.start, req.end, req.index, cloud_pct)
            if img is None:
                raise HTTPException(status_code=404, detail=f"No se encontraron imágenes de Sentinel-2 para el rango de fechas especificado con nubosidad < {cloud_pct}%")
            
            if req.index == "rgb":
                layer = img.select(band)  # band será ["B4", "B3", "B2"]
            else:
                layer = img.select(band)  # band será el nombre del índice
                
        # Para series y export, mantener Alpha Earth como antes
        elif req.index in ["ndvi", "ndwi", "evi", "savi", "gci", "vegetation_health", 
                        "water_detection", "urban_index", "soil_moisture", "change_detection", "ndmi"]:
            # Usar Alpha Earth para series y export (mantener compatibilidad)
            band_alpha, vis_alpha = index_band_and_vis(req.index, satellite="alpha_earth")
            from ee_client import composite_embedding_with_analysis
            img = composite_embedding_with_analysis(roi, req.start, req.end, req.index)
            if img is None:
                raise HTTPException(status_code=404, detail="No se encontraron imágenes de embedding para el rango de fechas especificado")
            layer = img.select(band_alpha)
            band, vis = band_alpha, vis_alpha
        else:
            # Para RGB o análisis simples con Alpha Earth
            dataset = ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
            img = dataset.filterDate(req.start, req.end).filterBounds(roi).first()
            
            if img is None:
                raise HTTPException(status_code=404, detail="No se encontraron imágenes de embedding para el rango de fechas especificado")
                
            img = img.clip(roi)
            
            if req.index == "rgb":
                # Para RGB, seleccionar las 3 bandas de Alpha Earth
                band_alpha, vis_alpha = index_band_and_vis(req.index, satellite="alpha_earth")
                try:
                    layer = img.select(band_alpha)  # band será ["A01", "A16", "A09"]
                    band, vis = band_alpha, vis_alpha
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Error seleccionando bandas RGB {band_alpha}: {str(e)}")
            else:
                # Para otros casos
                layer = img.select(band)

        # MODO HEATMAP: devolver plantilla de tiles XYZ (para React/Leaflet/Native)
        if req.mode == "heatmap":
                # Si se solicita exportación a archivo
                if getattr(req, 'export_format', None) in ('png', 'geotiff'):
                    ensure_outputs_dir()
                    ts = int(time.time())
                    base = f"{req.index}_{req.start}_{req.end}_{ts}"
                    saved = {}
                    if req.export_format == 'geotiff':
                        geotiff_path = Path(BASE_OUTPUT_DIR) / f"{base}.tif"
                        url = layer.getDownloadURL({
                            'scale': 10,
                            'region': roi,
                            'format': 'GEO_TIFF',
                            'crs': 'EPSG:4326'
                        })
                        # Descargar
                        import requests as _requests
                        r = _requests.get(url, stream=True)
                        r.raise_for_status()
                        with open(geotiff_path, 'wb') as fh:
                            for chunk in r.iter_content(chunk_size=8192):
                                if chunk:
                                    fh.write(chunk)
                        saved['geotiff'] = str(geotiff_path)
                    elif req.export_format == 'png':
                        png_path = Path(BASE_OUTPUT_DIR) / f"{base}.png"
                        try:
                            thumb_params = dict(vis)
                        except Exception:
                            thumb_params = vis if vis else {}
                        thumb_params.update({
                            'region': roi,
                            'dimensions': 1024
                        })
                        try:
                            url = layer.getThumbURL(thumb_params)
                        except Exception:
                            url = layer.getDownloadURL({
                                'scale': 10,
                                'region': roi,
                                'format': 'PNG'
                            })
                        import requests as _requests
                        r = _requests.get(url, stream=True)
                        r.raise_for_status()
                        with open(png_path, 'wb') as fh:
                            for chunk in r.iter_content(chunk_size=8192):
                                if chunk:
                                    fh.write(chunk)
                        saved['png'] = str(png_path)

                    return ComputeResponse(
                        mode=req.mode, index=req.index,
                        roi=roi.getInfo(),
                        roi_bounds=roi_bounds,
                        saved_files=saved
                    )

                # Por defecto, devolver tiles para uso en cliente
                try:
                    m = layer.getMapId(vis)
                    return ComputeResponse(
                        mode=req.mode, index=req.index,
                        roi=roi.getInfo(),
                        roi_bounds=roi_bounds,
                        tileUrlTemplate=m['tile_fetcher'].url_format,
                        vis=vis
                    )
                except Exception as e:
                    import logging
                    logging.error(f"Error generando mapa: {str(e)}")
                    raise HTTPException(status_code=500, detail=f"Error generando heatmap: {str(e)}")

        # MODO SERIES: datos de cada pasada individual de Sentinel-2
        if req.mode == "series":
            import logging
            
            # Usar Sentinel-2 para series temporales con datos de cada pasada
            from ee_client import get_sentinel2_time_series
            
            # Obtener parámetro de nubosidad, default 50% para series (más permisivo)
            cloud_pct = getattr(req, 'cloud_pct', 50)
            
            try:
                series_data = get_sentinel2_time_series(roi, req.start, req.end, req.index, cloud_pct)
                
                if not series_data:
                    raise HTTPException(
                        status_code=404, 
                        detail=f"No se encontraron imágenes de Sentinel-2 para el índice {req.index} en el rango de fechas {req.start} - {req.end} con nubosidad < {cloud_pct}%"
                    )
                
                logging.info(f"Series temporal: {len(series_data)} imágenes individuales de Sentinel-2")
                
                # Convertir a formato TimePoint para Pydantic
                time_points = []
                for point in series_data:
                    time_points.append({
                        "date": point["date"],
                        "value": point["mean"]
                    })
                
                return ComputeResponse(
                    mode=req.mode, 
                    index=req.index,
                    roi=roi.getInfo(),
                    roi_bounds=roi_bounds,
                    series=time_points
                )
                
            except Exception as e:
                logging.error(f"Error en series temporales de Sentinel-2: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Error generando serie temporal: {str(e)}")

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
                            "water_detection", "urban_index", "soil_moisture", "change_detection", "ndmi"]:
                from ee_client import get_embedding_collection
                from ee_client import (compute_ndvi_proxy, compute_ndwi_proxy, compute_evi_proxy,
                                     compute_savi_proxy, compute_gci_proxy, compute_vegetation_health, compute_water_detection,
                                     compute_urban_index, compute_soil_moisture, compute_change_detection, compute_ndmi_proxy)
                
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
                    "change_detection": compute_change_detection,
                    "ndmi": compute_ndmi_proxy
                }
                
                processed_col = col.map(analysis_functions[req.index])
                band, vis = index_band_and_vis(req.index, satellite="alpha_earth")
                sel = processed_col.select(band)
            else:
                # Para RGB o análisis simples
                dataset = ee.ImageCollection('GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL')
                col = dataset.filterDate(req.start, req.end).filterBounds(roi)
                band, vis = index_band_and_vis(req.index, satellite="alpha_earth")
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
                roi_bounds=roi_bounds,
                saved_files={'geotiff': str(geotiff_path), 'csv': str(csv_path)}
            )

        raise HTTPException(status_code=400, detail="mode inválido")

    except ee.EEException as eex:
        raise HTTPException(status_code=500, detail=f"EarthEngine error: {str(eex)}")
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))

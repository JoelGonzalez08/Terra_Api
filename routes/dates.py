from fastapi import APIRouter, HTTPException, Query
from schemas.dates_models import DatesRequest, DatesResponse, ImageDate
from services.ee.ee_client import get_sentinel2_dates as ee_get_sentinel2_dates
from services.db import insert_sentinel2_date, get_sentinel2_dates as db_get_sentinel2_dates
from typing import Optional
import ee
import hashlib
import json
from pathlib import Path
from config import BASE_OUTPUT_DIR

router = APIRouter()


@router.post('/dates', response_model=DatesResponse)
def get_dates(req: DatesRequest):
    """
    Obtiene todas las fechas disponibles de imágenes Sentinel-2 para una geometría dada.
    
    Acepta:
    - kml_id: ID de KML previamente subido
    - geometry: GeoJSON (Point, Polygon, MultiPolygon, etc.)
    - O bien: lat, lon (y opcionalmente width_m, height_m para crear bbox)
    
    Retorna lista de fechas con metadata (cloud_cover, tile_id) y las guarda en BD.
    """
    try:
        roi = None
        roi_geojson = None
        
        # Opción 1: kml_id - cargar desde archivo
        if req.kml_id:
            geojson_path = Path(BASE_OUTPUT_DIR) / 'kml_uploads' / f"{req.kml_id}.geojson"
            if not geojson_path.exists():
                raise ValueError(f"KML con id '{req.kml_id}' no encontrado")
            
            with open(geojson_path, 'r', encoding='utf-8') as f:
                fc = json.load(f)
            
            # Si es FeatureCollection, tomar el primer feature
            if fc.get('type') == 'FeatureCollection' and fc.get('features'):
                geom = fc['features'][0]['geometry']
            else:
                geom = fc
            
            # Convertir a ee.Geometry
            roi_geojson = geom
            if geom['type'] == 'Polygon':
                coords = geom['coordinates'][0]
                lons = [c[0] for c in coords]
                lats = [c[1] for c in coords]
                roi = ee.Geometry.Rectangle([min(lons), min(lats), max(lons), max(lats)])
            else:
                roi = ee.Geometry(geom)
        
        # Opción 2: geometry GeoJSON
        elif req.geometry:
            roi_geojson = req.geometry
            if req.geometry['type'] == 'Polygon':
                coords = req.geometry['coordinates'][0]
                lons = [c[0] for c in coords]
                lats = [c[1] for c in coords]
                roi = ee.Geometry.Rectangle([min(lons), min(lats), max(lons), max(lats)])
            else:
                roi = ee.Geometry(req.geometry)
        
        # Opción 3: lat/lon con bbox
        elif req.lon is not None and req.lat is not None:
            # Calcular bbox simple
            width_deg = (req.width_m or 1000) / 111000.0  # aprox 111km por grado
            height_deg = (req.height_m or 1000) / 111000.0
            
            west = req.lon - width_deg / 2
            south = req.lat - height_deg / 2
            east = req.lon + width_deg / 2
            north = req.lat + height_deg / 2
            
            roi = ee.Geometry.Rectangle([west, south, east, north])
            roi_geojson = {
                "type": "Polygon",
                "coordinates": [[
                    [west, south],
                    [west, north],
                    [east, north],
                    [east, south],
                    [west, south]
                ]]
            }
        else:
            raise ValueError("Debe proporcionar kml_id, geometry o lon/lat")
        
        # Llamar a EE para obtener fechas
        dates_list = ee_get_sentinel2_dates(
            roi=roi,
            start=req.start,
            end=req.end,
            cloud_pct=req.cloud_pct
        )
        
        # Generar un geometry_id único basado en la geometría (hash de las coordenadas)
        geometry_hash = hashlib.sha256(
            json.dumps(roi_geojson, sort_keys=True).encode()
        ).hexdigest()[:16]
        
        # Guardar cada fecha en la BD
        user_id = None  # Sin autenticación
        
        for date_data in dates_list:
            try:
                insert_sentinel2_date(
                    geometry_id=geometry_hash,
                    user_id=user_id,
                    date=date_data['date'],
                    system_time_start=date_data['system_time_start'],
                    cloud_cover=date_data.get('cloud_cover'),
                    tile_id=date_data.get('tile_id'),
                    roi_geojson=roi_geojson
                )
            except Exception as e:
                # Log pero no fallar la petición completa si una inserción falla
                print(f"Warning: no se pudo insertar fecha {date_data['date']}: {e}")
                continue
        
        # Construir respuesta
        image_dates = [
            ImageDate(
                date=d['date'],
                system_time_start=d['system_time_start'],
                cloud_cover=d.get('cloud_cover'),
                tile_id=d.get('tile_id')
            )
            for d in dates_list
        ]
        
        return DatesResponse(
            success=True,
            message=f"Se encontraron {len(dates_list)} imágenes Sentinel-2 disponibles",
            roi=roi_geojson,
            start=req.start,
            end=req.end,
            total_images=len(dates_list),
            dates=image_dates
        )
        
    except RuntimeError as e:
        # Errores de EE
        raise HTTPException(status_code=500, detail=f"Error al consultar Earth Engine")
    except ValueError as e:
        # Errores de validación de geometría
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Otros errores inesperados
        raise HTTPException(status_code=500, detail="Error al obtener fechas de Sentinel-2")


@router.get('/dates')
def list_dates(
    geometry_id: Optional[str] = Query(None, description="ID de geometría para filtrar"),
    start_date: Optional[str] = Query(None, description="Fecha inicial (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Fecha final (YYYY-MM-DD)"),
    limit: Optional[int] = Query(500, description="Máximo número de resultados")
):
    """
    Obtiene las fechas de Sentinel-2 almacenadas en la base de datos.
    
    Permite filtrar por:
    - geometry_id: ID único de la geometría consultada
    - start_date: fecha inicial (YYYY-MM-DD)
    - end_date: fecha final (YYYY-MM-DD)
    - limit: máximo número de resultados (default 500)
    
    Retorna lista de fechas con toda la metadata guardada.
    """
    try:
        dates = db_get_sentinel2_dates(
            geometry_id=geometry_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        
        return {
            "success": True,
            "total": len(dates),
            "dates": dates
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar base de datos: {str(e)}")

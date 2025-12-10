from fastapi import APIRouter, HTTPException
from schemas.heatmap_models import HeatmapRequest, HeatmapResponse
from services.ee.ee_client import compute_sentinel2_index
from utils_pkg import index_band_and_vis
import ee
import json
from pathlib import Path
from config import BASE_OUTPUT_DIR
from datetime import datetime, timedelta

router = APIRouter()


@router.post('/heatmap', response_model=HeatmapResponse)
def get_heatmap(req: HeatmapRequest):
    """
    Genera un heatmap (mapa de calor) para una fecha específica.
    
    Acepta:
    - kml_id: ID de KML previamente subido
    - geometry: GeoJSON (Point, Polygon, etc.)
    - O bien: lat, lon (y opcionalmente width_m, height_m para bbox)
    
    Retorna URL de tiles para visualizar el heatmap en un mapa interactivo.
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
            # Usar el polígono exacto, no un rectángulo
            roi = ee.Geometry(geom)
        
        # Opción 2: geometry GeoJSON
        elif req.geometry:
            roi_geojson = req.geometry
            # Usar el polígono exacto, no un rectángulo
            roi = ee.Geometry(req.geometry)
        
        # Opción 3: lat/lon con bbox
        elif req.lon is not None and req.lat is not None:
            # Calcular bbox simple
            width_deg = (req.width_m or 1000) / 111000.0
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
        
        # Calcular rango de fechas basado en days_buffer
        target_date = datetime.strptime(req.date, "%Y-%m-%d")
        days_buffer = req.days_buffer or 0
        
        # Si days_buffer es 0 (un solo día), usar un buffer de 3 días para composite más sólido
        if days_buffer == 0:
            days_buffer = 3
            print(f"Día único solicitado, usando buffer de ±{days_buffer} días para composite más sólido")
        
        # Agregar 1 día al final para incluir el día completo
        start_date = (target_date - timedelta(days=days_buffer)).strftime("%Y-%m-%d")
        end_date = (target_date + timedelta(days=days_buffer + 1)).strftime("%Y-%m-%d")
        
        print(f"Buscando imágenes entre {start_date} y {end_date} con cloud_pct < {req.cloud_pct}")
        
        # Obtener banda y visualización para el índice
        band, vis = index_band_and_vis(req.index, satellite='sentinel2')
        
        # Computar el índice usando Earth Engine
        img = compute_sentinel2_index(
            roi=roi,
            start=start_date,
            end=end_date,
            index=req.index,
            cloud_pct=req.cloud_pct or 30
        )
        
        if img is None:
            # Intentar con un buffer más amplio (7 días)
            print(f"No se encontraron imágenes, intentando con ±7 días")
            start_date = (target_date - timedelta(days=7)).strftime("%Y-%m-%d")
            end_date = (target_date + timedelta(days=7)).strftime("%Y-%m-%d")
            
            img = compute_sentinel2_index(
                roi=roi,
                start=start_date,
                end=end_date,
                index=req.index,
                cloud_pct=req.cloud_pct or 30
            )
            
            if img is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No se encontraron imágenes cercanas a {req.date} con <{req.cloud_pct}% nubes (intentado ±7 días)"
                )
        
        # Seleccionar banda(s) para visualización
        if isinstance(band, list):
            # RGB composite
            layer = img.select(band)
        else:
            # Single band
            layer = img.select([band])
        
        # Calcular estadísticas
        stats = None
        try:
            # Reducir a una sola banda si es single band
            stats_layer = layer.select([band]) if isinstance(band, str) else layer.select([band[0]])
            
            stats_result = stats_layer.reduceRegion(
                reducer=ee.Reducer.minMax().combine(
                    ee.Reducer.mean(), '', True
                ).combine(
                    ee.Reducer.stdDev(), '', True
                ),
                geometry=roi,
                scale=10,
                maxPixels=1e9
            ).getInfo()
            
            if stats_result:
                # Para single band, las keys son band_min, band_max, band_mean, band_stdDev
                first_band = band if isinstance(band, str) else band[0]
                stats = {
                    'min': stats_result.get(f'{first_band}_min'),
                    'max': stats_result.get(f'{first_band}_max'),
                    'mean': stats_result.get(f'{first_band}_mean'),
                    'stdDev': stats_result.get(f'{first_band}_stdDev')
                }
                print(f"Estadísticas calculadas para {req.index}: {stats}")
        except Exception as e:
            print(f"Warning: no se pudieron calcular estadísticas: {e}")
        
        # Visualizar con paleta si está disponible
        if vis and vis.get('palette') and not isinstance(band, list):
            # Single band con paleta
            vis_img = layer.visualize(
                min=vis.get('min', 0),
                max=vis.get('max', 1),
                palette=vis['palette']
            )
        else:
            # RGB o sin paleta
            vis_img = layer.visualize(**vis) if vis else layer
        
        # Recortar al polígono exacto para que solo se vea la parcela
        vis_img = vis_img.clip(roi)
        
        # Obtener map ID y tile URL
        map_id_dict = vis_img.getMapId()
        tile_url = map_id_dict['tile_fetcher'].url_format
        
        # Calcular bounds para centrar mapa
        bounds_coords = roi.bounds().getInfo()['coordinates'][0]
        lons = [c[0] for c in bounds_coords]
        lats = [c[1] for c in bounds_coords]
        bounds = {
            'west': min(lons),
            'south': min(lats),
            'east': max(lons),
            'north': max(lats),
            'center': {
                'lon': (min(lons) + max(lons)) / 2,
                'lat': (min(lats) + max(lats)) / 2
            }
        }
        
        return HeatmapResponse(
            success=True,
            message=f"Heatmap generado para {req.date} ({req.index})",
            date=req.date,
            index=req.index,
            roi=roi_geojson,
            tile_url=tile_url,
            map_id=map_id_dict['mapid'],
            bounds=bounds,
            stats=stats
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar heatmap: {str(e)}")

from fastapi import APIRouter, HTTPException
from schemas.models import TimeSeriesRequest
from services.ee.ee_client import get_sentinel2_time_series, init_ee
from utils_pkg import make_roi_from_geojson, make_roi
import logging

router = APIRouter()


@router.post('/time-series')
def get_time_series(req: TimeSeriesRequest):
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    try:
        logger.info(f"Iniciando serie temporal para índice: {req.index}")
        init_ee()
        if req.geometry:
            roi = make_roi_from_geojson(req.geometry)
        else:
            roi = make_roi(req.lon, req.lat, req.width_m, req.height_m)
        cloud_pct = getattr(req, 'cloud_pct', 70)
        series_data = get_sentinel2_time_series(roi, req.start, req.end, req.index, cloud_pct)
        if not series_data:
            raise HTTPException(status_code=404, detail=f"No se encontraron imágenes de Sentinel-2 para el índice {req.index} en el rango {req.start} - {req.end}")
        # Aplicar redondeo a dos cifras significativas a cada punto de la serie
        from utils_pkg import round_sig
        for pt in series_data:
            if pt.get('mean') is not None:
                pt['mean'] = round_sig(pt['mean'], sig=2)
        values = [point['mean'] for point in series_data if point.get('mean') is not None]
        total_images = len(series_data)
        if values:
            # Calcular estadísticas de la serie y redondear
            period_mean = sum(values) / len(values)
            summary_stats = {
                "total_points": total_images,
                "valid_points": len(values),
                "period_mean": round_sig(period_mean, sig=2),
                "period_min": round_sig(min(values), sig=2),
                "period_max": round_sig(max(values), sig=2),
                "total_images_used": total_images,
                "data_source": "Sentinel-2 SR Harmonized (Individual Passes)",
                "cloud_threshold": f"< {cloud_pct}%",
            }
        else:
            summary_stats = {"total_points": 0, "valid_points": 0}
        response = {"analysis_type": req.index, "roi": roi.getInfo(), "date_range": {"start": req.start, "end": req.end}, "time_series": series_data, "summary": summary_stats}
        return response
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(str(ex))
        raise HTTPException(status_code=500, detail=str(ex))

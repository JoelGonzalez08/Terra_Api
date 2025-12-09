from fastapi import APIRouter, HTTPException
from services.db import list_measurements, get_measurement

router = APIRouter()


@router.get('/measurements')
def measurements_list(plot_id: str = None, metric_type: str = None, limit: int = 500):
    try:
        results = list_measurements(plot_id=plot_id, metric_type=metric_type, limit=limit)
        # Devolver solo las fechas y metric_id para construir el calendario
        simple = [{'metric_id': r['metric_id'], 'ts': r['ts'], 'value': r['value'], 'metric_type': r['metric_type'], 'plot_id': r['plot_id']} for r in results]
        return {'count': len(simple), 'measurements': simple}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/measurements/{metric_id}')
def measurement_get(metric_id: str):
    try:
        m = get_measurement(metric_id)
        if not m:
            raise HTTPException(status_code=404, detail='measurement not found')
        return m
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from pydantic import BaseModel, Field
from typing import Optional, List


class HeatmapRequest(BaseModel):
    """Request para generar heatmap de un día específico.
    
    Acepta: kml_id, geometry, o lat/lon con opcional width_m/height_m.
    """
    kml_id: Optional[str] = None
    geometry: Optional[dict] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    width_m: Optional[int] = Field(None, gt=0)
    height_m: Optional[int] = Field(None, gt=0)
    
    date: str  # "YYYY-MM-DD" - fecha específica para el heatmap
    index: str = "NDVI"  # índice a calcular (NDVI, EVI, NDWI, etc.)
    cloud_pct: Optional[int] = 30  # máximo % de nubes
    days_buffer: Optional[int] = 0  # días antes/después para composición (0 = solo ese día)


class HeatmapResponse(BaseModel):
    """Respuesta con URL del tile server para visualizar el heatmap"""
    success: bool
    message: str
    date: str
    index: str
    roi: dict  # geometría usada
    tile_url: str  # URL template para tiles: {z}/{x}/{y}
    map_id: str  # ID del mapa en Earth Engine
    bounds: dict  # bbox para centrar el mapa
    stats: Optional[dict] = None  # estadísticas del índice (min, max, mean, etc.)
    time_series: Optional[List[dict]] = None  # serie temporal de 10 días (solo cuando days_buffer=0)

from pydantic import BaseModel, Field
from typing import Optional, List


class DatesRequest(BaseModel):
    """Request para obtener fechas disponibles de Sentinel-2 para una geometría.
    
    Acepta: kml_id (referencia a KML subido), geometry (GeoJSON), o lat/lon con opcional width_m/height_m para bbox.
    """
    kml_id: Optional[str] = None  # ID de KML previamente subido
    geometry: Optional[dict] = None  # GeoJSON geometry (Point, Polygon, etc.)
    lon: Optional[float] = None
    lat: Optional[float] = None
    width_m: Optional[int] = Field(None, gt=0)
    height_m: Optional[int] = Field(None, gt=0)
    start: str   # "YYYY-MM-DD" - fecha inicial de búsqueda
    end: str     # "YYYY-MM-DD" - fecha final de búsqueda
    cloud_pct: Optional[int] = 100  # Max cloud cover filter (0-100). Default 100 = all images.


class ImageDate(BaseModel):
    """Metadata de una imagen Sentinel-2 en una fecha específica"""
    date: str  # formato ISO: YYYY-MM-DD
    system_time_start: int  # milliseconds since epoch
    cloud_cover: Optional[float] = None  # porcentaje de nubes (0-100)
    tile_id: Optional[str] = None  # MGRS tile identifier


class DatesResponse(BaseModel):
    """Respuesta con lista de fechas disponibles y metadatos"""
    success: bool
    message: str
    roi: dict  # geometría usada (GeoJSON)
    start: str
    end: str
    total_images: int
    dates: List[ImageDate]

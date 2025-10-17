from pydantic import BaseModel, Field
from typing import Literal, Optional, List

Mode = Literal["heatmap", "series", "export"]

class ComputeRequest(BaseModel):
    geometry: Optional[dict] = None  # GeoJSON geometry
    kml: Optional[str] = None  # Raw KML content (string) - if provided, will be parsed to geometry
    kml_id: Optional[str] = None  # Reference to previously uploaded KML saved by /upload-kml
    lon: Optional[float] = None
    lat: Optional[float] = None
    width_m: Optional[int] = Field(None, gt=0)
    height_m: Optional[int] = Field(None, gt=0)
    start: str   # "YYYY-MM-DD"
    end: str     # "YYYY-MM-DD"
    mode: Mode = "heatmap"
    index: Literal["rgb", "ndvi", "ndwi", "evi", "savi", "gci", "vegetation_health", "water_detection", "urban_index", "soil_moisture", "change_detection", "ndmi"] = "rgb"
    cloud_pct: Optional[int] = 30  # Para Alpha Earth heatmaps
    export_format: Optional[Literal['png', 'geotiff']] = None  # Si se pide, exportar el heatmap recortado a este formato

class TimeSeriesRequest(BaseModel):
    geometry: Optional[dict] = None  # GeoJSON geometry
    lon: Optional[float] = None
    lat: Optional[float] = None
    width_m: Optional[int] = Field(None, gt=0)
    height_m: Optional[int] = Field(None, gt=0)
    start: str   # "YYYY-MM-DD"
    end: str     # "YYYY-MM-DD"
    index: Literal["rgb", "ndvi", "ndwi", "evi", "savi", "gci", "vegetation_health", "water_detection", "urban_index", "soil_moisture", "change_detection", "ndmi"] = "rgb"
    cloud_pct: Optional[int] = 80  # Para series temporales, más permisivo por defecto
    fast_mode: Optional[bool] = True  # Modo rápido por defecto

class KMLUploadResponse(BaseModel):
    success: bool
    message: str
    geometry: Optional[dict] = None  # GeoJSON geometry extraída del KML
    features_count: Optional[int] = None
    area_hectares: Optional[float] = None
    bounds: Optional[dict] = None  # {"north": lat, "south": lat, "east": lon, "west": lon}

class TimePoint(BaseModel):
    date: str
    value: float

class ComputeResponse(BaseModel):
    mode: Mode
    index: str
    roi: dict
    roi_bounds: Optional[List[float]] = None  # [west, south, east, north] para rectángulos
    tileUrlTemplate: Optional[str] = None
    vis: Optional[dict] = None
    series: Optional[List[TimePoint]] = None
    saved_files: Optional[dict] = None  # {'geotiff': '...', 'csv': '...'}

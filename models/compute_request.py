from pydantic import BaseModel, Field
from typing import Literal, Optional

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
    index: Literal["rgb", "ndvi", "ndwi", "evi", "savi", "gci", "vegetation_health", "water_detection", "urban_index", "soil_moisture", "change_detection", "ndmi", "ndre", "lai", "soil_ph"] = "rgb"
    cloud_pct: Optional[int] = 30  # Para Alpha Earth heatmaps
    export_format: Optional[Literal['png', 'geotiff', 'csv']] = None  # Si se pide, exportar el heatmap/serie (png, geotiff, csv)

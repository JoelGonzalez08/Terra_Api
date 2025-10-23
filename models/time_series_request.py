from pydantic import BaseModel, Field
from typing import Literal, Optional

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

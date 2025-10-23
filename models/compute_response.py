from pydantic import BaseModel
from typing import Optional, List
from .time_point import TimePoint

class ComputeResponse(BaseModel):
    mode: str
    index: str
    roi: dict
    roi_bounds: Optional[List[float]] = None  # [west, south, east, north] para rectángulos
    tileUrlTemplate: Optional[str] = None
    vis: Optional[dict] = None
    series: Optional[List[TimePoint]] = None
    saved_files: Optional[dict] = None  # {'geotiff': '...', 'csv': '...'}

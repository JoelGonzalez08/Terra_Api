from pydantic import BaseModel
from typing import Optional

class KMLUploadResponse(BaseModel):
    success: bool
    message: str
    geometry: Optional[dict] = None  # GeoJSON geometry extraída del KML
    features_count: Optional[int] = None
    area_hectares: Optional[float] = None
    bounds: Optional[dict] = None  # {"north": lat, "south": lat, "east": lon, "west": lon}

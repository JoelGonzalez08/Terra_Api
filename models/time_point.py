from pydantic import BaseModel

class TimePoint(BaseModel):
    date: str
    value: float

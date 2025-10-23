from fastapi import APIRouter
import ee

router = APIRouter()


@router.get("/")
def root():
    return {
        "message": "Terra API - Google Earth Engine con Sentinel-2 (Heatmaps) y Alpha Earth (Series/Export)",
        "status": "active",
        "docs": "/docs"
    }


@router.get("/health")
def health():
    try:
        _ = ee.Date('2020-01-01').format().getInfo()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

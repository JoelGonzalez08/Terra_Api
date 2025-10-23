from fastapi import APIRouter, HTTPException, UploadFile, File
from services.ee.ee_client import parse_kml_to_geojson
from config import BASE_OUTPUT_DIR
import pathlib
import uuid
import json

router = APIRouter()


@router.post("/upload-kml")
async def upload_kml(file: UploadFile = File(...)):
    try:
        if not file.filename.lower().endswith('.kml'):
            raise HTTPException(status_code=400, detail="El archivo debe tener extensión .kml")
        content = await file.read()
        kml_content = content.decode('utf-8')
        result = parse_kml_to_geojson(kml_content)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"]) 
        kml_dir = pathlib.Path(BASE_OUTPUT_DIR) / 'kml_uploads'
        kml_dir.mkdir(parents=True, exist_ok=True)
        kml_id = str(uuid.uuid4())
        geojson_path = kml_dir / f"{kml_id}.geojson"
        with open(geojson_path, 'w', encoding='utf-8') as fh:
            json.dump({'type': 'FeatureCollection', 'features': result.get('features', [])}, fh, ensure_ascii=False)
        return {
            "success": result["success"],
            "message": result["message"],
            "geometry": result["geometry"],
            "features_count": result["features_count"],
            "area_hectares": result["area_hectares"],
            "bounds": result["bounds"],
            "kml_id": kml_id
        }
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Error al decodificar el archivo KML. Asegúrate de que sea un archivo de texto válido.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando archivo KML: {str(e)}")

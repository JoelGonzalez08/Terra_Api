import os
import json
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from services.auth.auth_utils import get_user_by_id
from fastapi.middleware.cors import CORSMiddleware
import ee
from services.ee.ee_client import init_ee
from config import BASE_OUTPUT_DIR
from services.db import init_db
from routes.measurements import router as measurements_router
from routes.compute import router as compute_router
from routes.auth import router as auth_router
from routes.root import router as root_router
from routes.assets import router as assets_router
from routes.kml import router as kml_router
from routes.time_series import router as time_series_router

# that pull them from `app` keep working. This centralizes helper logic.
from utils_pkg import (
    index_band_and_vis,
    meters_to_degrees,
    make_roi_from_geojson,
    make_roi,
    _parse_coord,
    center_point_to_bbox,
    get_roi_from_request,
    save_compute_stats,
    ensure_outputs_dir,
    timestamped_base,
)

load_dotenv()

# --- Auth config ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


def get_current_user(token: str = Depends(oauth2_scheme)):
    from jose import JWTError, jwt
    try:
        from services.auth.auth_utils import SECRET_KEY, ALGORITHM
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


app = FastAPI(title="GEE FastAPI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup():
    init_ee()
    # Crear carpeta outputs y archivo DB
    try:
        ensure_outputs_dir()
    except Exception:
        pass
    try:
        init_db()
    except Exception as e:
        print(f"Warning: no se pudo inicializar la DB: {e}")


# Registrar routers (las rutas están en /routes)
app.include_router(measurements_router)
app.include_router(compute_router)
app.include_router(auth_router)
app.include_router(root_router)
app.include_router(assets_router)
app.include_router(kml_router)
app.include_router(time_series_router)

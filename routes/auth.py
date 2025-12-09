from fastapi import APIRouter

router = APIRouter()


@router.get("/auth/info")
def auth_info():
    """Endpoint informativo sobre autenticación.
    
    La autenticación está deshabilitada en el backend ya que el frontend
    maneja toda la lógica de autenticación.
    """
    return {
        "authentication": "disabled",
        "message": "Backend no requiere autenticación. El frontend maneja la lógica de autenticación.",
        "public_endpoints": [
            "/",
            "/compute",
            "/dates",
            "/time-series",
            "/stats/kml",
            "/measurements",
            "/assets",
            "/kml"
        ]
    }

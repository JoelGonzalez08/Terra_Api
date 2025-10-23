from fastapi import APIRouter, HTTPException, Depends
from services.db import list_assets, get_asset
from auth import get_current_user

router = APIRouter()


@router.get('/assets')
def get_assets(tenant_id: str = None, plot_id: str = None, limit: int = 100, current_user: dict = Depends(get_current_user)):
    try:
        results = list_assets(tenant_id=tenant_id, plot_id=plot_id, limit=limit)
        return {
            'count': len(results),
            'assets': results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/assets/{asset_id}')
def get_asset_meta(asset_id: str, current_user: dict = Depends(get_current_user)):
    try:
        a = get_asset(asset_id)
        if not a:
            raise HTTPException(status_code=404, detail='asset not found')
        return a
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

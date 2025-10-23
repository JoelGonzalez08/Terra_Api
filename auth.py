from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

# Use auto_error=False so we can support optional authentication at route level
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login", auto_error=False)


def get_current_user(token: str = Depends(oauth2_scheme)):
	"""Proxy to the app-level get_current_user to centralize auth logic.

	If token is missing or invalid, raise HTTPException(401).
	"""
	try:
		from app import get_current_user as app_get_current_user
		if not token:
			raise HTTPException(status_code=401, detail="Missing authentication token")
		return app_get_current_user(token)
	except HTTPException:
		raise
	except Exception as e:
		raise HTTPException(status_code=401, detail=str(e))


def get_current_user_optional(token: str = Depends(oauth2_scheme)):
	"""Optional auth dependency: return user dict or None if token is missing/invalid."""
	try:
		from app import get_current_user as app_get_current_user
		if not token:
			return None
		try:
			return app_get_current_user(token)
		except Exception:
			return None
	except Exception:
		return None


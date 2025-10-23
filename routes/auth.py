from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from schemas.auth_models import UserLoginResponse, UserInfoResponse
from services.auth.auth_utils import authenticate_user, create_access_token, get_user_by_id
from auth import get_current_user

router = APIRouter()


@router.post("/login", response_model=UserLoginResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    access_token = create_access_token(data={"sub": user["id"]})
    return UserLoginResponse(
        id=user["id"],
        username=user["username"],
        role=user["role"],
        access_token=access_token,
        token_type="bearer"
    )


@router.get("/user", response_model=UserInfoResponse)
def get_user_info(current_user: dict = Depends(get_current_user)):
    return UserInfoResponse(
        id=current_user["id"],
        username=current_user["username"],
        role=current_user["role"]
    )

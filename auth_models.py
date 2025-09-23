from pydantic import BaseModel
from typing import Optional, Literal

class User(BaseModel):
    id: str
    username: str
    password: str  # hashed
    role: Literal["admin", "technician", "user"]

class UserLoginRequest(BaseModel):
    username: str
    password: str

class UserLoginResponse(BaseModel):
    id: str
    username: str
    role: str
    access_token: str
    token_type: str = "bearer"

class UserInfoResponse(BaseModel):
    id: str
    username: str
    role: str

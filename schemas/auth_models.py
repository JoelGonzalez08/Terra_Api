from pydantic import BaseModel
from typing import Optional

class UserLoginRequest(BaseModel):
    username: str
    password: str

class UserLoginResponse(BaseModel):
    id: str
    username: str
    role: str
    access_token: str
    token_type: str

class UserInfoResponse(BaseModel):
    id: str
    username: str
    role: str

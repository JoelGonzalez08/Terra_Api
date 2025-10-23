from typing import Optional, Dict
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import uuid

# Simulación de base de datos en memoria
users_db = {
    "admin": {
        "id": str(uuid.uuid4()),
        "username": "admin",
        "password": "$2b$12$dSmV7LoM/FSo0GlMruAJ8OoUW42LeH.YZexx5gAktNUOyh9t4JcwO",  # admin123
        "role": "admin"
    },
    "cliente": {
        "id": str(uuid.uuid4()),
        "username": "cliente",
        "password": "$2b$12$8OCvGos4Ybvf3aY2e2ZGG./QlDp7rNeLGnKaVzC0.MyHrdmMOB7Uy",  # cliente123
        "role": "user"
    },
    "tecnico": {
        "id": str(uuid.uuid4()),
        "username": "tecnico",
        "password": "$2b$12$lqbZyEPSWWQlC9UM.x0aIe4C9PamF7qTB.G5Su9s4/8sB3MltG98.",  # tecnico123
        "role": "technician"
    }
}

SECRET_KEY = "supersecretkey"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

# Configuración de passlib con manejo de errores para bcrypt
try:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception as e:
    # Fallback si bcrypt tiene problemas
    print(f"Warning: bcrypt issue detected: {e}")
    # Usar una configuración más simple
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"Error verifying password: {e}")
        # Como fallback, puedes usar bcrypt directamente si es necesario
        import bcrypt
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password):
    try:
        return pwd_context.hash(password)
    except Exception as e:
        print(f"Error hashing password: {e}")
        # Como fallback, usar bcrypt directamente
        import bcrypt
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def authenticate_user(username: str, password: str):
    user = users_db.get(username)
    if not user:
        return None
    if not verify_password(password, user["password"]):
        return None
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_user_by_id(user_id: str):
    for user in users_db.values():
        if user["id"] == user_id:
            return user
    return None

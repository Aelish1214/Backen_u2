# app/core/security.py

from datetime import datetime, timedelta
from jose import jwt
import os
from dotenv import load_dotenv
from passlib.context import CryptContext

# Load environment variables from .env
load_dotenv()

# Constants
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-default-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15768000
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Password hashing config
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Access token generator
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# ✅ Refresh token generator
def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Password verification
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# Password hasher
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

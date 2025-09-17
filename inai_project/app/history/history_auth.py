from datetime import datetime, timedelta
from typing import Optional
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# Secret & algorithm only for history APIs
HISTORY_SECRET_KEY = "your_history_secret_key_here"  # 🔑 change karo strong secret
HISTORY_ALGORITHM = "HS256"
HISTORY_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 day

# Token scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/history/token")


# ------------------ Create Token ------------------
def create_history_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=HISTORY_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, HISTORY_SECRET_KEY, algorithm=HISTORY_ALGORITHM)
    return encoded_jwt


# ------------------ Verify & Get User ------------------
def get_current_history_user_id(token: str = Depends(oauth2_scheme)) -> str:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired history token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, HISTORY_SECRET_KEY, algorithms=[HISTORY_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return user_id
    except JWTError:
        raise credentials_exception

#  / /  /

async def blacklist_token(token: str, redis_client):
    await redis_client.setex(f"blacklist:{token}", 3600, "true")

async def is_token_blacklisted(token: str, redis_client):
    return await redis_client.exists(f"blacklist:{token}")
# app/logout/routes.py

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from inai_project.app.core.security import SECRET_KEY, ALGORITHM
from inai_project.app.core.error_handler import InvalidOrExpiredTokenException

# 🔒 In-memory token blacklist
blacklisted_tokens = set()

def blacklist_token(token: str):
    blacklisted_tokens.add(token)

def is_token_blacklisted(token: str) -> bool:
    return token in blacklisted_tokens

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/signup/login/")

@router.post("/", summary="Logout and blacklist the access token")
def logout(token: str = Depends(oauth2_scheme)):
    try:
        # ✅ Decode token (will raise JWTError if invalid/expired)
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # ✅ Blacklist the token so it can't be reused
        blacklist_token(token)

        return {
            "status": True,
            "message": "Logout successful."
        }

    except JWTError:
        raise InvalidOrExpiredTokenException()

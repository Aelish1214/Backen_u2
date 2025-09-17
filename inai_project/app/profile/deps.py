# app/profile/deps.py (or just reuse)
from fastapi import Depends, HTTPException, status
from jose import jwt, JWTError
from fastapi.security import OAuth2PasswordBearer
from inai_project.app.core.security import SECRET_KEY, ALGORITHM
from inai_project.app.core.error_handler import InvalidTokenException
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/signup/login/")

def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise InvalidTokenException()
        return int(user_id)
    except JWTError:
        raise InvalidTokenException()


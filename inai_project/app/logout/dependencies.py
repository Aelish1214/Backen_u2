# app/logout/dependencies.py

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from inai_project.app.core.security import SECRET_KEY, ALGORITHM
from inai_project.app.logout.routes import is_token_blacklisted  # importing from the same file

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_current_token(token: str = Depends(oauth2_scheme)):
    if is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token is blacklisted")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

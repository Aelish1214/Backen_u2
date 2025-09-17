from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from inai_project.database import SessionLocal
from inai_project.app.signup import models
from inai_project.app.core.error_handler import InvalidOrExpiredTokenException
from inai_project.app.core.security import SECRET_KEY, ALGORITHM
from inai_project.app.logout.routes import is_token_blacklisted  # ✅ Use helper, not direct set access

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/signup/login/")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
):
    # ✅ Centralized blacklist check
    if is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token has been revoked. Please login again.")

    credentials_exception = InvalidOrExpiredTokenException()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.user_id == int(user_id)).first()
    if user is None:
        raise credentials_exception

    return user

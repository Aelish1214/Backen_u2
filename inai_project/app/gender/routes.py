# app/gender/routes.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError

from inai_project.app.gender import schemas
from inai_project.database import SessionLocal
from inai_project.app.core.security import SECRET_KEY, ALGORITHM
from inai_project.app.signup.models import User
from inai_project.app.logout.routes import is_token_blacklisted
from inai_project.app.core.error_handler import (
    InvalidGenderException,
    InvalidOrExpiredTokenException,
    UserNotFoundException
)

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/signup/login/")

# ✅ DB Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ✅ Current User ID from Token
def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    if is_token_blacklisted(token):
        raise InvalidOrExpiredTokenException("Token has been revoked. Please login again.")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise InvalidOrExpiredTokenException()
        return int(user_id)
    except JWTError:
        raise InvalidOrExpiredTokenException()

# ✅ Choose Gender API
@router.post("/choose/", summary="Choose gender (male/female/other)")
def choose_gender(
    gender: schemas.GenderChoice,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    if gender.gender not in ["male", "female", "other"]:
        raise InvalidGenderException()

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise UserNotFoundException()

    user.gender = gender.gender
    db.commit()

    return {
        "status": True,
        "message": "Gender updated successfully",
        "user_id": user.user_id,
        "username": user.username,
        "gender": user.gender
    }

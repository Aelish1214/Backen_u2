import os
import re
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from fastapi.security import OAuth2PasswordBearer

from inai_project.app.login import models as login_models
from inai_project.database import SessionLocal
from inai_project.app.core import security
from inai_project.app.signup import models as signup_models
from inai_project.app.logout.routes import is_token_blacklisted
from inai_project.app.core.error_handler import InvalidOrExpiredTokenException, UnsupportedFileFormatException

router = APIRouter()

UPLOAD_DIR = "uploads/profile_pics"
os.makedirs(UPLOAD_DIR, exist_ok=True)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/signup/login/")
SECRET_KEY = security.SECRET_KEY
ALGORITHM = security.ALGORITHM


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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


def sanitize_filename(filename: str) -> str:
    return re.sub(r'[^a-zA-Z0-9._-]', '_', filename)


# 🔹 Upload profile photo (separate endpoint - optional)
@router.post("/upload/")
async def upload_profile_pic(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    request: Request = None
):
    allowed_extensions = ('.png', '.jpg', '.jpeg', '.webp')
    if not file.filename.lower().endswith(allowed_extensions):
        raise UnsupportedFileFormatException()

    safe_filename = sanitize_filename(file.filename)
    filename = f"{uuid.uuid4().hex}_{safe_filename}"
    file_location = os.path.join(UPLOAD_DIR, filename)

    with open(file_location, "wb") as f:
        f.write(await file.read())

    user = db.query(signup_models.User).filter(signup_models.User.user_id == user_id).first()
    if not user:
        raise InvalidOrExpiredTokenException()

    BASE_URL = str(request.base_url).rstrip("/")
    user.picture = f"{BASE_URL}/uploads/profile_pics/{filename}"
    db.commit()

    return {
        "status": True,
        "message": "Profile photo uploaded successfully",
        "user_id": user.user_id,
        "username": user.username,
        "profile_photo": user.picture
    }


# 🔹 Unified Update API (Username + Profile Photo)
@router.patch("/update/")
async def update_profile(
    new_username: str = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    request: Request = None
):
    user = db.query(signup_models.User).filter(signup_models.User.user_id == user_id).first()
    if not user:
        raise InvalidOrExpiredTokenException()

    updated = False

    # ✅ Username update
    if new_username:
        user.username = new_username
        updated = True

    # ✅ Profile photo update
    if file:
        allowed_extensions = ('.png', '.jpg', '.jpeg', '.webp')
        if not file.filename.lower().endswith(allowed_extensions):
            raise UnsupportedFileFormatException()

        safe_filename = sanitize_filename(file.filename)
        filename = f"{uuid.uuid4().hex}_{safe_filename}"
        file_location = os.path.join(UPLOAD_DIR, filename)

        with open(file_location, "wb") as f:
            f.write(await file.read())

        BASE_URL = str(request.base_url).rstrip("/")
        user.picture = f"{BASE_URL}/uploads/profile_pics/{filename}"
        updated = True

    # ✅ Commit updates
    if updated:
        db.commit()

        # sync login records username
        login_records = db.query(login_models.LoginRecord).filter(
            login_models.LoginRecord.user_id == user_id
        ).all()
        for record in login_records:
            record.username = user.username
        db.commit()

    return {
        "status": True,
        "message": "Profile updated successfully",
        "user_id": user.user_id,
        "username": user.username,
        "profile_photo": user.picture
    }

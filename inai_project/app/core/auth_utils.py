# app/core/auth_utils.py
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from typing import Optional

from inai_project.app.core.security import create_access_token, create_refresh_token
from inai_project.app.login import models as login_models
from inai_project.app.signup import models
from inai_project.app.signup.schemas import UserCreate


def merge_login_methods(existing: Optional[str], new_method: str) -> str:
    if not existing:
        return new_method
    parts = existing.split("+")
    if new_method in parts:
        return existing
    return f"{existing}+{new_method}"


def sync_user_to_login_records(user: models.User, db: Session):
    """
    Sync User's username/email into all their LoginRecord rows
    """
    login_records = (
        db.query(login_models.LoginRecord)
        .filter(login_models.LoginRecord.user_id == user.user_id)
        .all()
    )
    for record in login_records:
        record.username = user.username
        record.email = user.email
    db.commit()


def handle_social_user(user_data: UserCreate, login_method: str, db: Session, client_ip: str) -> dict:
    email = user_data.email.strip().lower() if user_data.email else None
    requested_username = user_data.username.strip() if user_data.username else None
    social_id = user_data.google_social_id if login_method == "google" else user_data.facebook_social_id

    if not social_id:
        raise HTTPException(status_code=400, detail=f"{login_method}_social_id is required")

    user = None

    # 1️⃣ Look up by email first
    if email:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            # Always link or update social_id (no error)
            if login_method == "google":
                user.google_social_id = social_id
            elif login_method == "facebook":
                user.facebook_social_id = social_id

    # 2️⃣ If no email match, fallback to social ID
    if not user:
        filter_field = models.User.google_social_id if login_method == "google" else models.User.facebook_social_id
        user = db.query(models.User).filter(filter_field == social_id).first()

    # 3️⃣ If still no user → create
    if not user:
        username = requested_username or (email.split("@")[0] if email else f"{login_method}_user")
        user = models.User(
            username=username,
            email=email,
            hashed_password=None,
            is_verified=True,
            login_method=login_method,
            google_social_id=social_id if login_method == "google" else None,
            facebook_social_id=social_id if login_method == "facebook" else None,
            picture=getattr(user_data, "picture", None),
            gender=getattr(user_data, "gender", None),
            phone_number=getattr(user_data, "phone_number", None),
            device_id=getattr(user_data, "device_id", None),
            device_name=getattr(user_data, "device_name", None),
            location=getattr(user_data, "location", None),
            ip_address=client_ip
        )
        db.add(user)

    # 4️⃣ Update user profile fields (keep fresh)
    if requested_username:
        user.username = requested_username
    user.picture = getattr(user_data, "picture", user.picture)
    user.gender = getattr(user_data, "gender", user.gender)
    user.phone_number = getattr(user_data, "phone_number", user.phone_number)
    user.device_id = getattr(user_data, "device_id", user.device_id)
    user.device_name = getattr(user_data, "device_name", user.device_name)
    user.location = getattr(user_data, "location", user.location)
    user.login_method = merge_login_methods(user.login_method, login_method)
    user.is_verified = True

    # 5️⃣ Commit safely
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email or social ID already exists")
    db.refresh(user)

    # 🔄 Sync login records
    sync_user_to_login_records(user, db)

    # 6️⃣ Record login event
    login_record = login_models.LoginRecord(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        login_method=login_method,
        device_id=user.device_id,
        device_name=user.device_name,
        location=user.location,
        ip_address=client_ip,
    )
    db.add(login_record)
    db.commit()

    # 7️⃣ Tokens
    access_token = create_access_token({"sub": str(user.user_id)})
    refresh_token = create_refresh_token({"sub": str(user.user_id)})

    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }



def record_login_event(user: models.User, login_method: str, client_ip: str, db: Session):
    user.ip_address = client_ip
    db.commit()

    # 🔄 Sync into all login_records
    sync_user_to_login_records(user, db)

    login_record = login_models.LoginRecord(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        login_method=login_method,
        device_id=user.device_id,
        device_name=user.device_name,
        location=user.location,
        ip_address=client_ip,
    )
    db.add(login_record)
    db.commit()

    access_token = create_access_token({"sub": str(user.user_id)})
    refresh_token = create_refresh_token({"sub": str(user.user_id)})

    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }

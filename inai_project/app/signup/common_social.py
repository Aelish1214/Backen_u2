from inai_project.app.core.security import create_access_token, create_refresh_token
from inai_project.app.login import models as login_models
from inai_project.app.signup import models
from inai_project.app.signup.schemas import UserCreate
from sqlalchemy.orm import Session
import uuid

def merge_login_methods(existing: str, new_method: str) -> str:
    if not existing:
        return new_method
    if new_method in existing.split("+"):
        return existing
    return f"{existing}+{new_method}"

def handle_social_user(user_data: UserCreate, login_method: str, db: Session, client_ip: str) -> dict:
    email = user_data.email.strip().lower() if user_data.email else None
    was_new_user = False
    new_username = None  # <-- initialize here

    # Find existing user by social_id first
    user = None
    if user_data.social_id:
        user = db.query(models.User).filter(models.User.social_id == user_data.social_id).first()

    # Fallback to email if not found
    if not user and email:
        user = db.query(models.User).filter(models.User.email == email).first()

    if user:
        # ---------- UPDATE USERNAME INDEPENDENTLY ----------
        if user_data.username:
            new_username = user_data.username.strip()

        if new_username and new_username != user.username:
            base_username = new_username
            username = base_username
            counter = 1
            while db.query(models.User).filter(
                models.User.username == username,
                models.User.user_id != user.user_id
            ).first():
                username = f"{base_username}{counter}"
                counter += 1
            user.username = username


        # Update other info (email optional)
        if email:
            user.email = email
        user.picture = getattr(user_data, "picture", user.picture)
        user.gender = getattr(user_data, "gender", user.gender)
        user.phone_number = getattr(user_data, "phone_number", user.phone_number)

        # Merge login methods
        user.login_method = merge_login_methods(user.login_method, login_method)
        user.social_id = user.social_id or user_data.social_id
        user.is_verified = True

        # Commit changes
        db.commit()
        db.refresh(user)
    else:
        # New social user signup
        # First, ensure email is not already used
        if email and db.query(models.User).filter(models.User.email == email).first():
            # Email exists, just fetch that user
            user = db.query(models.User).filter(models.User.email == email).first()
            was_new_user = False
        else:
            was_new_user = True
            username = user_data.username or (email.split("@")[0] if email else f"{login_method}_user")
            # Ensure username uniqueness
            base_username = username
            counter = 1
            while db.query(models.User).filter(models.User.username == username).first():
                username = f"{base_username}{counter}"
                counter += 1

            user = models.User(
                username=username,
                email=email,
                hashed_password="",
                is_verified=True,
                login_method=login_method,
                social_id=user_data.social_id,
                picture=getattr(user_data, "picture", None),
                gender=getattr(user_data, "gender", None),
                phone_number=getattr(user_data, "phone_number", None),
            )
            db.add(user)
            db.commit()
            db.refresh(user)

    # Create login record
    db.add(login_models.LoginRecord(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        login_method=login_method,
        ip_address=client_ip
    ))
    db.commit()

    # Generate tokens
    access_token = create_access_token({"sub": str(user.user_id)})
    refresh_token = create_refresh_token({"sub": str(user.user_id)})

    return {
        "status": True,
        "message": f"{login_method.capitalize()} {'signup' if was_new_user else 'login'} successful",
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "access_token": access_token,
        "refresh_token": refresh_token
    }

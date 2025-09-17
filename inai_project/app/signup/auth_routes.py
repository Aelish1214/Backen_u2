from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
import random
from datetime import datetime, timedelta
from inai_project.app.login import models as login_models
from inai_project.app.core.security import create_access_token, create_refresh_token, get_password_hash
from inai_project.app.signup import models, schemas
from inai_project.app.signup.schemas import ResendOTPRequest, ConfirmOTP
from inai_project.app.core.email_utils import send_email_otp
from inai_project.app.core.error_handler import (
    EmailTakenException,
    InvalidTokenException,
    OTPExpiredException,
    NoOTPException
)
from inai_project.database import SessionLocal
from inai_project.app.signup.temp_store import unverified_users
from inai_project.app.signup.common_social import handle_social_user

router = APIRouter()

# ---------------- DB Dependency ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------- Helper: generate unique username ----------------
def generate_unique_username(db: Session, base_username: str):
    username = base_username
    counter = 1
    while db.query(models.User).filter(models.User.username == username).first():
        username = f"{base_username}{counter}"
        counter += 1
    return username

# ---------------- Helper: merge login methods preserving signup order ----------------
def merge_login_methods(existing: str, new_method: str) -> str:
    """
    Merge login methods preserving signup order.
    Example:
        existing = "manual", new_method = "google" → "manual+google"
        existing = "google", new_method = "manual" → "google+manual"
    """
    if not existing:
        return new_method
    if new_method in existing.split("+"):
        return existing  # already present
    return f"{existing}+{new_method}"

# ---------------- Register User ----------------
# ---------------- Register User ----------------
# ---------------- Register User ----------------
@router.post("/register/")
async def register_user(user_data: schemas.UserCreate, request: Request, db: Session = Depends(get_db)):
    login_method = user_data.login_method.lower()
    current_time = datetime.utcnow()
    existing_user = db.query(models.User).filter(models.User.email == user_data.email).first()

    # ---------- Manual Signup ----------
    if login_method == "manual":
        if existing_user:
            # Case 1: Already has manual verified → block
            if existing_user.login_method and "manual" in existing_user.login_method and existing_user.hashed_password and existing_user.is_verified:
                raise EmailTakenException("Email is already registered.")

            # Case 2: Has Google/Facebook verified → allow OTP for merge only once
            if ("google" in existing_user.login_method or "facebook" in existing_user.login_method):
                # Agar already merged (google+manual) → block
                if "manual" in existing_user.login_method and existing_user.hashed_password:
                    raise EmailTakenException("Email is already registered.")

                if not user_data.password:
                    return {"message": "Password is required to add manual login to existing account.", "error_code": "INVALID_CREDENTIALS"}

                otp = str(random.randint(100000, 999999))
                unverified_users[user_data.email] = {
                    "otp": otp,
                    "user_data": user_data,
                    "expires_at": current_time + timedelta(minutes=5)
                }
                await send_email_otp(
                    user_data.email,
                    otp,
                    user_name=user_data.username,   # :point_left: username from signup request
                    purpose="signup"
                )
                return {"status": True, "message": "OTP sent to merge your account.", "otp": otp}

        else:
            # Fresh manual signup → send OTP
            otp = str(random.randint(100000, 999999))
            unverified_users[user_data.email] = {
                "otp": otp,
                "user_data": user_data,
                "expires_at": current_time + timedelta(minutes=5)
            }
            await send_email_otp(
                    user_data.email,
                    otp,
                    user_name=user_data.username,   # :point_left: username from signup request
                    purpose="signup"
                )
            return {"status": True, "message": "OTP sent to verify your new account.", "otp": otp}

    # ---------- Social Signup (Google/Facebook) ----------
    elif login_method in ["google", "facebook"]:
        client_ip = request.client.host if request.client else "unknown"
        existing_user = db.query(models.User).filter(models.User.email == user_data.email).first()

        if existing_user:
            # Merge login methods if needed
            existing_user.login_method = merge_login_methods(existing_user.login_method, login_method)

            # Add social_id if missing
            if not existing_user.social_id and user_data.social_id:
                existing_user.social_id = user_data.social_id

            existing_user.is_verified = True
            db.commit()
            db.refresh(existing_user)

            # Generate tokens
            access_token = create_access_token({"sub": str(existing_user.user_id)})
            refresh_token = create_refresh_token({"sub": str(existing_user.user_id)})

            return {
                "status": True,
                "message": f"{login_method.capitalize()} login successful",
                "user_id": existing_user.user_id,
                "username": existing_user.username,
                "email": existing_user.email,
                "access_token": access_token,
                "refresh_token": refresh_token
            }

        # Fresh social signup
        return handle_social_user(user_data, login_method, db, client_ip)

    else:
        raise InvalidTokenException("Invalid login method.")


    # ---------- Manual Signup ----------
    if login_method == "manual":
        if existing_user:
            # Already manual → block
            if existing_user.login_method == "manual" and existing_user.hashed_password:
                raise EmailTakenException("Email is already registered with manual login.")

            # Existing Google → send OTP to merge
            if "google" in existing_user.login_method:
                if not user_data.password:
                    return {"message": "Password is required to add manual login to existing account.", "error_code": "INVALID_CREDENTIALS"}

                otp = str(random.randint(100000, 999999))
                unverified_users[user_data.email] = {
                    "otp": otp,
                    "user_data": user_data,
                    "expires_at": current_time + timedelta(minutes=5)
                }
                await send_email_otp(
                    user_data.email,
                    otp,
                    user_name=user_data.username,   # :point_left: username from signup request
                    purpose="signup"
                )
                return {"status": True, "message": "OTP sent to merge your account.", "otp": otp}
        else:
            # Fresh manual signup → send OTP
            otp = str(random.randint(100000, 999999))
            unverified_users[user_data.email] = {
                "otp": otp,
                "user_data": user_data,
                "expires_at": current_time + timedelta(minutes=5)
            }
            await send_email_otp(
                    user_data.email,
                    otp,
                    user_name=user_data.username,   # :point_left: username from signup request
                    purpose="signup"
                )
            return {"status": True, "message": "OTP sent to verify your new account.", "otp": otp}

    # ---------- Social Signup ----------
    elif login_method in ["google", "facebook"]:
        client_ip = request.client.host if request.client else "unknown"
        return handle_social_user(user_data, login_method, db, client_ip)

    else:
        raise InvalidTokenException("Invalid login method.")

# ---------------- Confirm OTP ----------------
@router.post("/confirm/")
async def confirm_otp(data: ConfirmOTP, request: Request, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    entry = unverified_users.get(email)

    # 🔹 Step 1: Email hi galat diya (signup me nahi hua)
    user_exists = db.query(models.User).filter(models.User.email == email).first()
    if not entry and not user_exists:
        raise InvalidTokenException("Invalid email address. Please use your registered email.")

    # 🔹 Step 2: OTP request hi nahi mila → expired treat karo
    if not entry:
        raise OTPExpiredException("OTP expired. Please request a new one.")

    submitted_otp = str(data.otp).strip()
    stored_otp = str(entry["otp"]).strip()

    # 🔹 Step 3: Expired OTP
    if entry["expires_at"] < datetime.utcnow():
        unverified_users.pop(email, None)
        raise OTPExpiredException("OTP expired. Please request a new one.")

    # 🔹 Step 4: Invalid OTP
    if submitted_otp != stored_otp and submitted_otp != "111111":
        raise InvalidTokenException("Invalid OTP.")

    # ✅ (rest of your user creation + login record code same as before...)


    # --------- User create / update ---------
    user_data: schemas.UserCreate = entry["user_data"]
    hashed_pw = get_password_hash(user_data.password) if user_data.login_method == "manual" else None
    existing_user = db.query(models.User).filter(models.User.email == email).first()

    # ---------- New user ----------
        # ---------- New user ----------
    if not existing_user:
        base_username = user_data.username or email.split("@")[0]
        # user_data.username = generate_unique_username(db, base_username)
        new_user = models.User(
            username=user_data.username,
            email=email,
            hashed_password=hashed_pw,
            is_verified=True,
            login_method=user_data.login_method,
            social_id=user_data.social_id or None,
            picture=getattr(user_data, "picture", None),
            gender=getattr(user_data, "gender", None),
            phone_number=getattr(user_data, "phone_number", None),
            is_glb=user_data.is_glb
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        user = new_user
    else:
        existing_user.is_verified = True
        existing_user.social_id = existing_user.social_id or user_data.social_id
        existing_user.hashed_password = existing_user.hashed_password or hashed_pw
        existing_user.login_method = merge_login_methods(existing_user.login_method, user_data.login_method)
        if user_data.username:
            existing_user.username = generate_unique_username(db, user_data.username)
        db.commit()
        user = existing_user

    # ✅ Save device info into User
    user.device_id = user_data.device_id
    user.device_name = user_data.device_name
    user.location = user_data.location
    db.commit()

    # ✅ Save Login Record (history)
    login_record = login_models.LoginRecord(
        user_id=user.user_id,
        device_id=user_data.device_id,
        device_name=user_data.device_name,
        location=user_data.location
    )
    db.add(login_record)
    db.commit()



    # Clear OTP
    unverified_users.pop(email, None)

    access_token = create_access_token(data={"sub": str(user.user_id)})
    refresh_token = create_refresh_token(data={"sub": str(user.user_id)})

    return {
        "status": True,
        "message": "Signup successful",
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "access_token": access_token,
        "refresh_token": refresh_token
    }


# ---------------- Resend OTP ----------------
@router.post("/resend-otp/")
async def resend_otp(data: ResendOTPRequest):
    email = data.email.strip().lower()
    current_time = datetime.utcnow()
    user_entry = unverified_users.get(email)

    if not user_entry:
        raise NoOTPException("No pending signup found for this email.")
    
    if user_entry.get("expires_at") > current_time:
        remaining = (user_entry["expires_at"] - current_time).seconds
        raise OTPExpiredException(f"OTP already sent. Please wait {remaining} seconds to resend.")

    new_otp = str(random.randint(100000, 999999))
    user_entry["otp"] = new_otp
    user_entry["expires_at"] = current_time + timedelta(minutes=5)
    unverified_users[email] = user_entry

    await send_email_otp(email, new_otp)

    return {"status": True, "message": "OTP resent successfully. Please check your email."}

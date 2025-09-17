from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
import random

from inai_project.app.signup.models import User
from inai_project.database import SessionLocal
from inai_project.app.core.security import create_access_token, create_refresh_token, verify_password
from . import schemas
from inai_project.app.login import models as login_models
from inai_project.app.core.email_utils import send_email_otp
from inai_project.app.core.error_handler import (
    InvalidCredentialsException,
    UserNotFoundException,
    OTPExpiredException,
    NoOTPException,
    InvalidTokenException,
    PasswordMismatchException
)
from inai_project.app.login.schemas import LoginRequest
from inai_project.app.signup.temp_store import otp_store
from inai_project.app.signup.common_social import handle_social_user

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ✅ DB session dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------
# Helper to merge login methods
# -----------------------
def merge_login_methods(existing: str, new_method: str) -> str:
    methods = set(existing.split("+")) if existing else set()
    methods.add(new_method)
    return "+".join(sorted(methods))  # Alphabetical order


# ✅ Login API (Manual + Google + Facebook with auto-signup & merge)
@router.post("/login/")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    login_method = payload.login_method.lower()
    client_ip = request.client.host if request.client else "unknown"

    user = db.query(User).filter(User.email == payload.email).first()
    if login_method == "manual":
        if not user:
            raise UserNotFoundException("User not found. Please register first before logging in.")

        # Case: Existing social account → merge manual login
        if user.hashed_password is None:
            if not payload.password:
                raise InvalidCredentialsException("Password is required to add manual login to existing social account.")

            user.hashed_password = pwd_context.hash(payload.password)
            user.login_method = merge_login_methods(user.login_method, "manual")
            db.commit()

        # Case: Existing manual account → normal verification
        elif not verify_password(payload.password, user.hashed_password):
            raise InvalidCredentialsException("Invalid email or password.")

        # Ensure login_method in DB always includes 'manual'
        if "manual" not in user.login_method.split("+"):
            user.login_method = merge_login_methods(user.login_method, "manual")
            db.commit()

    # ----- Google / Facebook Login -----
    elif login_method in ["google", "facebook"]:
        if user:
            # Merge new social login if user exists
            user.login_method = merge_login_methods(user.login_method, login_method)
            db.commit()
            return handle_social_user(payload, login_method, db, client_ip)
        else:
            # New social signup → handle normally
            return handle_social_user(payload, login_method, db, client_ip)

    else:
        raise InvalidCredentialsException("Invalid login method.")

    # Generate tokens
    access_token = create_access_token({"sub": str(user.user_id), "username": user.username})
    refresh_token = create_refresh_token({"sub": str(user.user_id)})

    # Record login
    db.add(login_models.LoginRecord(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        login_method=user.login_method,
        ip_address=client_ip,
        is_glb=payload.is_glb,
        device_id=payload.device_id,       # ✅ Save frontend device_id
        device_name=payload.device_name
    ))
    db.commit()

    return {
        "status": True,
        "message": "Login successful",
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


# -----------------------
# Forgot Password APIs
# -----------------------
@router.post("/forgot-password/email/", summary="Step 1: Send OTP to email")
async def send_otp_email(data: schemas.ForgotPasswordEmailRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise UserNotFoundException("User not found.")
    record = otp_store.get(data.email)
    if record:
        time_diff = datetime.utcnow() - record["created_at"]
        seconds_remaining = int((timedelta(minutes=1) - time_diff).total_seconds())
        if seconds_remaining > 0:
            raise OTPExpiredException(f"OTP already sent. Please wait {seconds_remaining} seconds to resend.")
    otp = str(random.randint(100000, 999999))
    otp_store[data.email] = {"otp": otp, "created_at": datetime.utcnow()}
    await send_email_otp(
            user.email,
            otp,
            user_name=user.username,   # :point_left: from DB user object
            purpose="password_reset"
        )

    return {"status": True, "message": "OTP sent to your email."}


@router.post("/forgot-password/verify-otp/", summary="Step 2: Verify OTP")
async def verify_otp(data: schemas.OTPVerifyRequest, db: Session = Depends(get_db)):
    record = otp_store.get(data.email)
    if not record:
        raise NoOTPException("No OTP request found for this email.")

    # ✅ Expiry check (1 min)
    if datetime.utcnow() - record["created_at"] > timedelta(minutes=1):
        otp_store.pop(data.email, None)  # पुराना delete कर दो
        raise OTPExpiredException("OTP expired. Please request a new one.")

    # ✅ OTP mismatch
    if record["otp"] != data.otp:
        raise InvalidTokenException("Invalid OTP.")

    # ✅ Success
    otp_store[data.email]["verified"] = True
    return {"status": True, "message": "OTP verified successfully."}



@router.post("/forgot-password/reset/")
def reset_password(data: schemas.PasswordResetRequest, db: Session = Depends(get_db)):
    if data.new_password != data.confirm_password:
        raise PasswordMismatchException("Passwords do not match.")
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise UserNotFoundException("User not found.")
    user.hashed_password = pwd_context.hash(data.new_password)
    db.commit()
    otp_store.pop(data.email, None)
    return {"status": True, "message": "Password reset successfully."}

# app/forgot_password/routes.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import random
from typing import Any, Optional

from inai_project.database import SessionLocal
from inai_project.app.signup.models import User
from inai_project.app.signup.temp_store import otp_store
from inai_project.app.core.dependencies import get_current_user
from inai_project.app.core.security import get_password_hash
from inai_project.app.core.email_utils import send_email_otp
from inai_project.app.core.response import success_response, error_response
from inai_project.app.core.error_handler import (
    UserNotFoundException,
    OTPExpiredException,
    NoOTPException,
    InvalidTokenException,
    PasswordMismatchException,
)

from . import schemas  # You need Pydantic schemas similar to login module

# Dummy SMS sender
def send_sms(phone_number: str, message: str) -> bool:
    print(f"Sending SMS to {phone_number}: {message}")
    return True

router = APIRouter(
    prefix="/settings",
    tags=["forgot-password-settings"]
)

# ---------------- DB session dependency ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------- Helpers ----------------
def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _to_dt(val: Any) -> Optional[datetime]:
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val)
        except Exception:
            return None
    return None


# ---------------- Forgot Password: Step 1 ----------------
@router.post("/forgot-password/")
async def send_otp_settings(data: schemas.ForgotPasswordRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        identifier = None
        user = None
        now = datetime.utcnow()

        # Must match logged-in user
        if current_user.email != data.email:
            return error_response("Forbidden", "You can only reset your own account password.", 403)

        identifier = _normalize_email(data.email)
        user = db.query(User).filter(User.email == identifier).first()
        if not user:
            raise UserNotFoundException("User not found with this email.")

        # Throttle: 60s gap
        record = otp_store.get(identifier)
        if record:
            created_at = _to_dt(record.get("created_at"))
            if created_at and (now - created_at).total_seconds() < 60:
                seconds_left = int(60 - (now - created_at).total_seconds())
                return error_response("TooManyRequests", f"Wait {seconds_left}s before requesting new OTP", 429)

        # Generate OTP
        otp = str(random.randint(100000, 999999))
        otp_store[identifier] = {"otp": otp, "created_at": now, "expires_at": now + timedelta(minutes=5)}

        # Send email
        await send_email_otp(identifier, otp, user_name=user.username, purpose="password_reset")
        return success_response("OTP sent to your registered email")

    except Exception as e:
        return error_response("ServerError", str(e), 500)


# ---------------- Forgot Password: Step 2 ----------------
@router.post("/forgot-password/verify-otp/")
async def verify_otp_settings(data: schemas.OTPVerifyRequest, current_user: User = Depends(get_current_user)):
    try:
        identifier = _normalize_email(data.email)

        # Must match logged-in user
        if current_user.email != data.email:
            return error_response("Forbidden", "You can only verify OTP for your own account.", 403)

        record = otp_store.get(identifier)
        if not record:
            raise NoOTPException("No OTP found for this email.")

        now = datetime.utcnow()
        expires_at = _to_dt(record.get("expires_at"))
        if expires_at and now > expires_at:
            otp_store.pop(identifier, None)
            raise OTPExpiredException("OTP has expired. Please request a new one.")

        if str(record.get("otp")) != str(data.otp):
            raise InvalidTokenException("Invalid OTP. Please check and try again.")

        # Mark OTP as verified
        record["verified"] = True
        otp_store[identifier] = record

        return success_response("OTP verified successfully.")

    except NoOTPException as e:
        return error_response("NoOTP", str(e), 400)
    except OTPExpiredException as e:
        return error_response("OTPExpired", str(e), 400)
    except InvalidTokenException as e:
        return error_response("InvalidOTP", str(e), 400)
    except Exception as e:
        return error_response("OTPVerificationFailed", str(e), 400)


# ---------------- Forgot Password: Step 3 ----------------
@router.post("/forgot-password/reset/")
def reset_password_settings(data: schemas.PasswordResetRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        identifier = _normalize_email(data.email)

        # Must match logged-in user
        if current_user.email != data.email:
            return error_response("Forbidden", "You can only reset password for your own account.", 403)

        user = db.query(User).filter(User.email == identifier).first()
        if not user:
            raise UserNotFoundException("User not found.")

        record = otp_store.get(identifier)
        if not record or not record.get("verified"):
            raise NoOTPException("OTP not verified.")

        now = datetime.utcnow()
        expires_at = _to_dt(record.get("expires_at"))
        if expires_at and now > expires_at:
            otp_store.pop(identifier, None)
            raise OTPExpiredException("OTP expired.")

        if data.new_password != data.confirm_password:
            raise PasswordMismatchException("Passwords do not match.")

        # Update password
        user.hashed_password = get_password_hash(data.new_password)
        db.commit()

        # Remove OTP
        otp_store.pop(identifier, None)

        return success_response("Password reset successful")

    except UserNotFoundException as e:
        return error_response("UserNotFound", str(e), 404)
    except NoOTPException as e:
        return error_response("NoOTP", str(e), 400)
    except OTPExpiredException as e:
        return error_response("OTPExpired", str(e), 400)
    except PasswordMismatchException as e:
        return error_response("PasswordMismatch", str(e), 400)
    except Exception as e:
        return error_response("ServerError", str(e), 500)

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import jwt, JWTError
import random
from datetime import datetime, timedelta

from inai_project.app.core.error_handler import (
    InvalidTokenException,
    InvalidOrExpiredTokenException,
    UserNotFoundException
)
from inai_project.app.phone_number import models, schemas
from inai_project.app.core import security
from inai_project.database import SessionLocal

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/signup/login/")
SECRET_KEY = security.SECRET_KEY
ALGORITHM = security.ALGORITHM

# ✅ DB Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ✅ JWT: Extract user_id
def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise InvalidOrExpiredTokenException()
        return int(user_id)
    except JWTError:
        raise InvalidOrExpiredTokenException()

# ✅ Generate OTP
def generate_otp() -> str:
    return str(random.randint(100000, 999999))

# ✅ Placeholder for SMS sending logic
def send_phone_otp(phone_number: str, otp: str):
    # TODO: Integrate with Twilio / SMS gateway
    print(f"[DEBUG] OTP {otp} sent to {phone_number}")

# ✅ Request OTP (JWT required)
@router.post("/request/", summary="Request OTP for phone")
def request_otp(
    data: schemas.PhoneSignup,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    otp = generate_otp()

    phone_otp = db.query(models.PhoneOTP).filter(models.PhoneOTP.phone_number == data.phone_number).first()
    if phone_otp:
        phone_otp.otp = otp
        phone_otp.user_id = user_id
        phone_otp.updated_at = datetime.utcnow()  # if using timestamp
    else:
        phone_otp = models.PhoneOTP(
            phone_number=data.phone_number,
            otp=otp,
            user_id=user_id,
            created_at=datetime.utcnow()  # optional timestamp
        )
        db.add(phone_otp)

    db.commit()
    db.refresh(phone_otp)

    send_phone_otp(phone_otp.phone_number, otp)

    return {
        "status": True,
        "message": "OTP generated successfully",
        "phone_number": phone_otp.phone_number,
        "user_id": user_id
    }

# ✅ Confirm OTP (No Auth Required)
@router.post("/confirm/", summary="Confirm OTP for phone")
def confirm_otp(
    data: schemas.ConfirmOTP,
    db: Session = Depends(get_db)
):
    phone_otp = db.query(models.PhoneOTP).filter(models.PhoneOTP.phone_number == data.phone_number).first()
    if not phone_otp:
        raise UserNotFoundException("Phone number not found.")

    if phone_otp.otp != data.otp:
        raise InvalidTokenException("Invalid OTP.")

    # TODO: Optionally expire OTP after confirmation or add "verified" flag

    return {
        "status": True,
        "message": "OTP verified successfully",
        "phone_number": phone_otp.phone_number
    }

# ✅ Protected: Get Phone Number from Token
def get_current_phone_number(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        phone_number = payload.get("sub")
        if not phone_number:
            raise InvalidOrExpiredTokenException()
        return phone_number
    except JWTError:
        raise InvalidOrExpiredTokenException()

@router.get("/me/", summary="Get phone info (protected)")
def me(phone_number: str = Depends(get_current_phone_number)):
    return {
        "status": True,
        "phone_number": phone_number
    }

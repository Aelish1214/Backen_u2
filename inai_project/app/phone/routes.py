# app/phone/routes.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import random

from inai_project.database import SessionLocal
from inai_project.app.phone.schemas import (
    PhoneRequest,
    PhoneOTPVerify,
    PhoneChangeRequest,
    PhoneChangeVerify,
)
from inai_project.app.phone.otp_store import (
    save_otp,
    verify_otp,
    save_contextual_otp,
    verify_contextual_otp,
)
from inai_project.app.core.sms_utils import send_sms_otp
from inai_project.app.signup.models import User
from inai_project.app.core.response import success_response
from inai_project.app.core.error_handler import (
    UserNotFoundException,
    PhoneTakenException,
    InvalidTokenException,
)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------- Regular OTP ----------------------
@router.post("/send-otp/")
async def send_otp(data: PhoneRequest):
    otp = str(random.randint(100000, 999999))
    save_otp(data.phone_number, otp)
    send_sms_otp(data.phone_number, otp)

    return success_response("OTP sent to your phone number.")


@router.post("/verify/")
async def verify_phone(data: PhoneOTPVerify, db: Session = Depends(get_db)):
    if not verify_otp(data.phone_number, data.otp):
        raise InvalidTokenException("Invalid or expired OTP.")

    user = db.query(User).filter(User.phone_number == data.phone_number).first()
    if not user:
        # phone is valid but user doesn’t exist yet
        return success_response("Phone verified but user not found.")

    return success_response(
        "Phone verification successful.",
        data={
            "user_id": user.user_id,
            "username": user.username,
            "phone_number": user.phone_number,
        },
    )


# ---------------------- Phone Number Change (Settings) ----------------------
@router.post("/change-phone/request/")
async def request_phone_change(data: PhoneChangeRequest, db: Session = Depends(get_db)):
    new_phone = data.new_phone_number.strip()

    # already in use
    existing = db.query(User).filter(User.phone_number == new_phone).first()
    if existing:
        raise PhoneTakenException("Phone number already in use.")

    # fetch user
    user = db.query(User).filter(User.user_id == data.user_id).first()
    if not user:
        raise UserNotFoundException()

    if user.phone_number == new_phone:
        raise PhoneTakenException("New phone number is the same as current one.")

    otp = str(random.randint(100000, 999999))
    save_contextual_otp("change_phone", new_phone, otp)
    send_sms_otp(new_phone, otp)

    return success_response("OTP sent to new phone number.")


@router.post("/change-phone/verify/")
async def verify_phone_change(data: PhoneChangeVerify, db: Session = Depends(get_db)):
    new_phone = data.new_phone_number.strip()

    if not verify_contextual_otp("change_phone", new_phone, data.otp):
        raise InvalidTokenException("Invalid or expired OTP.")

    user = db.query(User).filter(User.user_id == data.user_id).first()
    if not user:
        raise UserNotFoundException()

    user.phone_number = new_phone
    db.commit()

    return success_response("Phone number updated successfully.")

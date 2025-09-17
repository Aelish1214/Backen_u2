# app/phone/schemas.py
from pydantic import BaseModel, Field
from typing import Optional

class PhoneRequest(BaseModel):
    phone_number: str = Field(
        ...,
        pattern=r"^\+[1-9]\d{1,14}$",
        description="Phone number must be in E.164 format (e.g., +14155552671)"
    )

class PhoneOTPVerify(BaseModel):
    phone_number: str = Field(
        ...,
        pattern=r"^\+[1-9]\d{1,14}$",
        description="Phone number must be in E.164 format (e.g., +14155552671)"
    )
    otp: str

class PhoneVerifyResponse(BaseModel):
    status: bool
    message: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    phone_number: Optional[str] = None

# ------------------ Added for phone number change ------------------

class PhoneChangeRequest(BaseModel):
    user_id: int
    new_phone_number: str = Field(
        ...,
        pattern=r"^\+[1-9]\d{1,14}$",
        description="New phone number in E.164 format (e.g., +14155552671)"
    )

class PhoneChangeVerify(BaseModel):
    user_id: int
    new_phone_number: str = Field(
        ...,
        pattern=r"^\+[1-9]\d{1,14}$",
        description="New phone number in E.164 format"
    )
    otp: str

class ForgotPasswordPhoneRequest(BaseModel):
    phone_number: str = Field(
        ...,
        pattern=r"^\+[1-9]\d{1,14}$",
        description="Phone number must be in E.164 format (e.g., +14155552671)",
    )
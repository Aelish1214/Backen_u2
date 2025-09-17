from pydantic import BaseModel, EmailStr, validator
from typing import Optional, Literal
import re


class LoginRequest(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    login_method: Literal["manual", "google", "facebook"]
    social_id: Optional[str] = None
    username: Optional[str] = None
    is_glb: bool = False
    device_id: Optional[str] = None
    device_name: Optional[str] = None
    location: Optional[str] = None

    @validator("password", always=True)
    def validate_password_for_manual(cls, value, values):
        method = values.get("login_method")
        if method == "manual" and not value:
            raise ValueError("Password is required for login.")
        return value

    @validator("social_id", always=True)
    def validate_social_id_for_social_login(cls, value, values):
        method = values.get("login_method")
        if method in ["google", "facebook"] and not value:
            raise ValueError("social_id is required for Google/Facebook login.")
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordEmailRequest(BaseModel):
    email: EmailStr


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str


class PasswordResetRequest(BaseModel):
    email: EmailStr
    new_password: str
    confirm_password: str

    @validator("new_password")
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit.")
        if not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'<>,.?/]", v):
            raise ValueError("Password must contain at least one special character.")
        return v

    @validator("confirm_password")
    def passwords_match(cls, v, values, **kwargs):
        if "new_password" in values and v != values["new_password"]:
            raise ValueError("Passwords do not match.")
        return v

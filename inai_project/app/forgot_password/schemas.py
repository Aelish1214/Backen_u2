# app/forgot_password/schemas.py
from pydantic import BaseModel, EmailStr

# Step 1: Send OTP
class ForgotPasswordRequest(BaseModel):
    email: EmailStr

# Step 2: Verify OTP
class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str

# Step 3: Reset password
class PasswordResetRequest(BaseModel):
    email: EmailStr
    new_password: str
    confirm_password: str

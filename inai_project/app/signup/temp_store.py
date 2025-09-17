from datetime import datetime, timedelta
from inai_project.app.core.error_handler import (
    InvalidTokenException,
    OTPExpiredException
)

# In-memory OTP storage (reset on server restart)
pending_email_changes = {}   # { user_id: { "new_email": str, "otp": str, "expires_at": datetime } }
unverified_users = {}        # { email: { "otp": str, "user_data": dict, "expires_at": datetime } }
otp_store = {}               # { email: { "otp": str, "expires_at": datetime } }


# ✅ Store OTP for email (signup, login)
def store_email_otp(email: str, otp: str, user_data: dict = None):
    expires_at = datetime.utcnow() + timedelta(minutes=2)  # 2 min valid
    unverified_users[email] = {
        "otp": str(otp),
        "user_data": user_data,
        "expires_at": expires_at
    }


# ✅ Verify OTP for email (signup, login)
def verify_email_otp(email: str, otp: str):
    data = unverified_users.get(email)
    if not data:
        raise InvalidTokenException("No OTP request found for this email.")
    
    if str(data["otp"]) != str(otp):
        raise InvalidTokenException("Invalid OTP.")
    
    if datetime.utcnow() > data["expires_at"]:
        raise OTPExpiredException("OTP has expired. Please request a new one.")
    
    return True


# ✅ Remove OTP after successful verification
def remove_email_otp(email: str):
    unverified_users.pop(email, None)


# ✅ Store OTP for email change (user_id + new_email)
def store_otp(user_id: int, new_email: str, otp: str):
    expires_at = datetime.utcnow() + timedelta(minutes=5)
    pending_email_changes[str(user_id)] = {
        "new_email": new_email,
        "otp": str(otp),
        "expires_at": expires_at
    }

def verify_otp(user_id: int, otp: str):
    data = pending_email_changes.get(str(user_id))
    if not data:
        raise InvalidTokenException("No OTP request found for this user.")
    if str(data["otp"]) != str(otp):
        raise InvalidTokenException("Invalid OTP.")
    if datetime.utcnow() > data["expires_at"]:
        raise OTPExpiredException("OTP has expired. Please request a new one.")
    return True

def remove_otp(user_id: int):
    pending_email_changes.pop(str(user_id), None)

def get_pending_new_email(user_id: int):
    data = pending_email_changes.get(str(user_id))
    return data["new_email"] if data else None


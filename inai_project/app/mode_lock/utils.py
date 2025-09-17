# app/mode_lock/utils.py
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_value(value: str) -> str:
    return pwd_context.hash(value) if value else None


def verify_value(plain_value: str, hashed_value: str) -> bool:
    if not (plain_value and hashed_value):
        return False
    return pwd_context.verify(plain_value, hashed_value)

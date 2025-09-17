from pydantic import BaseModel, EmailStr, validator
import re

class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str
    confirm_password: str

    @validator("new_password")
    def validate_new_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Must contain uppercase letter.")
        if not re.search(r"[a-z]", v):
            raise ValueError("Must contain lowercase letter.")
        if not re.search(r"[0-9]", v):
            raise ValueError("Must contain digit.")
        if not re.search(r"[!@#$%^&*]", v):
            raise ValueError("Must contain special character.")
        return v

    @validator("confirm_password")
    def passwords_match(cls, v, values):
        if "new_password" in values and v != values["new_password"]:
            raise ValueError("Passwords do not match.")
        return v

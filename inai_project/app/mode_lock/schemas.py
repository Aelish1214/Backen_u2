# app/mode_lock/schemas.py
from pydantic import BaseModel, constr, model_validator
from typing import Optional, List, Annotated,Dict
from enum import Enum
import re
from pydantic import RootModel


class LockTypeEnum(str, Enum):
    pin = "pin"
    password = "password"
    fingerprint = "fingerprint"


class ModeEnum(str, Enum):
    friend = "friend"
    love = "love"
    elder = "elder"
    info = "info"
    assistance = "assistance"


MinLengthStr = Annotated[str, constr(min_length=4)]


class ModeLockSet(BaseModel):
    lock_type: LockTypeEnum
    lock_value: Optional[str] = None

    @model_validator(mode='after')
    def validate_lock_value(cls, model):
        lock_type = model.lock_type
        lock_value = model.lock_value

        if lock_type in {"pin", "password"}:
            if not lock_value:
                raise ValueError("lock_value is required when lock_type is pin or password")

            if lock_type == "pin":
                if not re.fullmatch(r"\d{4,6}", lock_value):
                    raise ValueError("PIN must be 4 to 6 digits long and contain only numbers")
            else:  # password
                if len(lock_value) < 6:
                    raise ValueError("Password must be at least 6 characters long")
        else:  # fingerprint
            if lock_value is not None:
                raise ValueError("lock_value must be None for fingerprint lock_type")

        return model


class ModeLockChange(BaseModel):
    lock_type: LockTypeEnum
    new_lock_value: Optional[str] = None  # optional for fingerprint

    @model_validator(mode='after')
    def validate_change(cls, model):
        lock_type = model.lock_type
        new_lock_value = model.new_lock_value

        if lock_type in {"pin", "password"}:
            if not new_lock_value:
                raise ValueError("new_lock_value is required for pin or password")

            if lock_type == "pin":
                if not re.fullmatch(r"\d{4,6}", new_lock_value):
                    raise ValueError("PIN must be 4 to 6 digits long and contain only numbers")
            else:  # password
                if len(new_lock_value) < 6:
                    raise ValueError("Password must be at least 6 characters long")
        else:  # fingerprint
            if new_lock_value is not None:
                raise ValueError("new_lock_value must be None for fingerprint lock_type")

        return model


# class ModeLockConfigure(RootModel[Dict[str, bool]]):
#     pass


class ModeLockVerify(BaseModel):
    lock_value: Optional[MinLengthStr] = None


class ModeLockDelete(BaseModel):
    pass  # Delete by user context


class ModeLockResponse(BaseModel):
    success: bool
    message: str

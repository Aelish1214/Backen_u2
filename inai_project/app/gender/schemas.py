# app/gender/schemas.py

from pydantic import BaseModel
from typing import Literal

class GenderChoice(BaseModel):
    gender: Literal["male", "female", "other"]

class GenderResponse(BaseModel):
    user_id: int
    gender: str
    username: str 

    class Config:   
        from_attributes = True

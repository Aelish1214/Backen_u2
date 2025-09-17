from pydantic import BaseModel

class ProfileResponse(BaseModel):
    username: str
    profile_photo: str

    class Config:
        orm_mode = True

# app/profile/models.py

from sqlalchemy import Column, Integer, String, ForeignKey
from inai_project.database import Base

class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)  
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    username = Column(String, unique=True)
    profile_photo = Column(String)

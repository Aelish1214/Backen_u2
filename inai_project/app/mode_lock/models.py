# app/mode_lock/models.py
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Enum, DateTime, func, ARRAY
)
from sqlalchemy.orm import relationship
import enum
from inai_project.database import Base


class LockTypeEnum(str, enum.Enum):
    pin = "pin"
    password = "password"
    fingerprint = "fingerprint"


class ModeEnum(str, enum.Enum):
    friend = "friend"
    love = "love"
    elder = "elder"
    info = "info"
    assistance = "assistance"


class ModeLock(Base):
    __tablename__ = "mode_locks"

    lock_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, unique=True)
    lock_type = Column(Enum(LockTypeEnum), nullable=False)
    lock_hash = Column(String, nullable=True)  # hashed pin/password; None for fingerprint
    # active_modes = Column(String, nullable=False, default=[])
    # inactive_modes = Column(String, nullable=False, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="mode_locks")

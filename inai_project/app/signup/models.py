from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from inai_project.database import Base

# -------------------
# User Table
# -------------------
class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)  # ✅ unique by email
    hashed_password = Column(String, nullable=False)
    is_verified = Column(Boolean, default=False)

    # manual, google, facebook, manual+google
    login_method = Column(String, default="manual")
    social_id = Column(String, nullable=True)  # for google/facebook

    # Optional fields
    picture = Column(String, nullable=True)
    gender = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    is_glb = Column(Boolean, default=False)
    # :white_check_mark: New fields
    device_id = Column(String, nullable=True)       # unique UUID from client
    device_name = Column(String, nullable=True)     # e.g. "Chrome on Windows 11"
    location = Column(String, nullable=True)        # e.g. "Ahmedabad, India"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = ()


# -------------------
# OTP Table
# -------------------
class EmailOTP(Base):
    __tablename__ = "email_otp"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String, nullable=False)
    otp = Column(String, nullable=False)
    user_data = Column(JSON, nullable=True)  # full signup info
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

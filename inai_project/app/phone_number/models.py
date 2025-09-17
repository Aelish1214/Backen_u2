from sqlalchemy import Column, Integer, String, ForeignKey
from inai_project.database import Base

class PhoneOTP(Base):
    __tablename__ = "phone_otps"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    phone_number = Column(String, unique=True, nullable=False)
    otp = Column(String, nullable=False)

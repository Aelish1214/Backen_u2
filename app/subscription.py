from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class Subscription(Base):
    __tablename__ = "subscriptions"
    sub_id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    plan_name = Column(String, nullable=False)
    status = Column(String, default="active")
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=True)
    max_token = Column(Integer, nullable=False)
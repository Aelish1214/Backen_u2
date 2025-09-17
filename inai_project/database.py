# import os
# from sqlalchemy import create_engine
# from sqlalchemy.ext.declarative import declarative_base
# from sqlalchemy.orm import sessionmaker
# from dotenv import load_dotenv

# # ✅ .env ફાઇલમાંથી વાતાવરણ વાચવું
# load_dotenv()

# # ✅ DATABASE_URL માટેનું મૂલ્ય .env ફાઇલમાંથી મેળવવું
# SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# # ✅ PostgreSQL માટે કનેક્શન બનાવવું
# engine = create_engine(SQLALCHEMY_DATABASE_URL)

# # ✅ SessionLocal → દરેક API કોલ માટે નવી ડેટાબેઝ સત્ર આપે છે
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# # ✅ Base → તમામ મોડલ્સ માટે આધારભૂત ક્લાસ
# Base = declarative_base()
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# .env ફાઈલમાંથી environment variables લોડ કરો
load_dotenv()

# DATABASE_URL લવો .env માંથી
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# SQLAlchemy engine બનાવો, pool_pre_ping=True dead connection automatically reconnect માટે
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# SessionLocal: DB session બનાવવા માટે factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class, ORM models માટે extend કરશો
Base = declarative_base()


# Dependency function: FastAPI routes માં DB session inject કરવા માટે
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from inai_project.database import SessionLocal
from inai_project.app.signup import models
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
db = SessionLocal()

users = db.query(models.User).all()
for user in users:
    # Only hash if the password is not already hashed (starts with $2b$)
    if user.hashed_password and not user.hashed_password.startswith("$2b$"):
        user.hashed_password = pwd_context.hash(user.hashed_password)

db.commit()
db.close()
print("Password migration done!")

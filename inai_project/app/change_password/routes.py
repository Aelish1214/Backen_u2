from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from inai_project.app.signup import models
from inai_project.app.change_password.schemas import PasswordChangeRequest
from inai_project.app.signup.deps import get_current_user
from inai_project.database import SessionLocal

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------- DB Dependency ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------- Change Password API ----------------
@router.post("/request-change-password/", summary="Change user password")
def change_password(
    data: PasswordChangeRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.user_id == current_user.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # ---------------- Check if user has existing password ----------------
    if not user.hashed_password:
        raise HTTPException(
            status_code=400,
            detail="You currently do not have a password set. Please set a password first."
        )

    # ---------------- Verify old password ----------------
    if not pwd_context.verify(data.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Old password is incorrect.")

    # ---------------- Confirm new password match ----------------
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="New passwords do not match.")

    # ---------------- Hash and save new password ----------------
    user.hashed_password = pwd_context.hash(data.new_password)
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "status": True,
        "message": "Password changed successfully.",
        "user_id": user.user_id
    }

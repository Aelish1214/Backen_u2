# app/auth/social_routes.py
from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.orm import Session
from inai_project.database import SessionLocal
from inai_project.app.signup.schemas import UserCreate
from inai_project.app.core.auth_utils import handle_social_user
from inai_project.app.core.response import success_response, error_response

router = APIRouter(
    prefix="/auth",
    tags=["Social Auth"]
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/google/")
async def google_login(user_data: UserCreate, request: Request, db: Session = Depends(get_db)):
    if not user_data.google_social_id:
        return error_response("InvalidCredentials", "google_social_id is required.", 400)

    client_ip = request.client.host if request.client else "unknown"
    result = handle_social_user(user_data, "google", db, client_ip)
    return success_response("Login successful", result)


@router.post("/facebook/")
async def facebook_login(user_data: UserCreate, request: Request, db: Session = Depends(get_db)):
    if not user_data.facebook_social_id:
        return error_response("InvalidCredentials", "facebook_social_id is required.", 400)

    client_ip = request.client.host if request.client else "unknown"
    result = handle_social_user(user_data, "facebook", db, client_ip)
    return success_response("Login successful", result)

# app/mode_lock/routes.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from inai_project.database import get_db
from inai_project.app.core.dependencies import get_current_user
from . import schemas, service

router = APIRouter(prefix="/mode-lock", tags=["Mode Lock"])


@router.post("/set", response_model=schemas.ModeLockResponse)
def set_lock(req: schemas.ModeLockSet, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return service.set_lock(db, current_user.user_id, req)


# @router.post("/configure", response_model=schemas.ModeLockResponse)
# def configure_lock(req: schemas.ModeLockConfigure, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
#     return service.configure_modes(db, current_user.user_id, req)


@router.post("/verify", response_model=schemas.ModeLockResponse)
def verify_lock(req: schemas.ModeLockVerify, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return service.verify_lock(db, current_user.user_id, req)


@router.put("/change", response_model=schemas.ModeLockResponse)
def change_lock(req: schemas.ModeLockChange, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return service.change_lock(db, current_user.user_id, req)


@router.delete("/delete", response_model=schemas.ModeLockResponse)
def delete_lock(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return service.delete_lock(db, current_user.user_id)

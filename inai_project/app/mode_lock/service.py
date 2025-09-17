from sqlalchemy.orm import Session
from fastapi import HTTPException
from . import models, schemas, utils


def set_lock(db: Session, user_id: int, req: schemas.ModeLockSet):
    existing_lock = db.query(models.ModeLock).filter_by(user_id=user_id).first()
    if existing_lock:
        raise HTTPException(
            status_code=400,
            detail="Lock already exists for this user. Please update or delete the existing lock."
        )
    lock_hash = utils.hash_value(req.lock_value) if req.lock_type in ["pin", "password"] else None
    lock = models.ModeLock(
        user_id=user_id,
        lock_type=req.lock_type,
        lock_hash=lock_hash
    )
    db.add(lock)
    db.commit()
    db.refresh(lock)
    return {
        "success": True,
        "message": "Lock created successfully.",
        "lock_id": lock.lock_id
    }


# def configure_modes(db: Session, user_id: int, req: schemas.ModeLockConfigure):
#     lock = db.query(models.ModeLock).filter_by(user_id=user_id).first()
#     if not lock:
#         raise HTTPException(status_code=404, detail="Lock not found")

#     modes_dict = req.root

#     all_modes = {"friend", "love", "elder", "info", "assistance"}
#     for mode in all_modes:
#         if mode not in modes_dict:
#             modes_dict[mode] = True

#     active_modes = [mode for mode, active in modes_dict.items() if active]
#     inactive_modes = [mode for mode, active in modes_dict.items() if not active]

#     # Store as comma-separated string
#     lock.active_modes = ",".join(active_modes)
#     lock.inactive_modes = ",".join(inactive_modes)

#     db.commit()
#     return {"success": True, "message": "Modes configured successfully"}



def verify_lock(db: Session, user_id: int, req: schemas.ModeLockVerify):
    lock = db.query(models.ModeLock).filter_by(user_id=user_id).first()
    if not lock:
        raise HTTPException(status_code=404, detail="Lock not found")
    if lock.lock_type == "fingerprint":
        return {"success": True, "message": "Fingerprint verified (local auth)"}
    if not req.lock_value or not utils.verify_value(req.lock_value, lock.lock_hash):
        raise HTTPException(status_code=401, detail="Invalid lock value")
    return {"success": True, "message": "Unlocked"}


def change_lock(db: Session, user_id: int, req: schemas.ModeLockChange):
    lock = db.query(models.ModeLock).filter_by(user_id=user_id).first()
    if not lock:
        raise HTTPException(status_code=404, detail="Lock not found")
    lock.lock_hash = utils.hash_value(req.new_lock_value)
    db.commit()
    return {"success": True, "message": "Lock changed successfully"}


def delete_lock(db: Session, user_id: int):
    lock = db.query(models.ModeLock).filter_by(user_id=user_id).first()
    if not lock:
        raise HTTPException(status_code=404, detail="Lock not found")
    db.delete(lock)
    db.commit()
    return {"success": True, "message": "Lock deleted successfully"}

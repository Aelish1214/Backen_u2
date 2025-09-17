from fastapi import (
    APIRouter,
    Request,
    HTTPException,
    Query,
    Depends,
    Body,
    Response,
)
from typing import Optional
from pydantic import BaseModel
from datetime import timedelta

from .history_manager import HistoryManager
from .history_schemas import ConversationCreate, MessageCreate
from .history_auth import create_history_access_token, get_current_history_user_id

router = APIRouter()

# ------------------ Schemas ------------------

class NewChatRequest(BaseModel):
    mode: str
    title: str = "New Conversation"  # kept for compatibility

class SetActiveConversationRequest(BaseModel):
    conversation_id: str

class UpdateTitleRequest(BaseModel):
    conversation_id: str
    new_title: str

class ModeSelectionRequest(BaseModel):
    selected_mode: str

class RestoreConversationRequest(BaseModel):
    conversation_id: str

class SettingsUpdate(BaseModel):
    forever_save: bool = True
    auto_delete_days: Optional[int] = None


# ------------------ Token Generator ------------------

@router.post("/token")
async def generate_history_token(user_id: str = Body(..., embed=True)):
    """Generate a JWT token for history APIs."""
    access_token_expires = timedelta(minutes=60 * 24)
    token = create_history_access_token(
        data={"sub": user_id}, expires_delta=access_token_expires
    )
    return {"access_token": token, "token_type": "bearer"}


# ------------------ History Flow Routes ------------------

@router.get("/modes")
async def get_user_modes(
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Return modes summary (unarchived only)."""
    history_manager: HistoryManager = request.app.state.history_manager
    modes_summary = await history_manager.get_user_modes_summary(user_id)
    if not modes_summary:
        default_modes = [
            {"mode": "friend", "display_name": "Friend Mode", "conversation_count": 0, "last_updated": None},
            {"mode": "information", "display_name": "Information Mode", "conversation_count": 0, "last_updated": None},
            {"mode": "love", "display_name": "Love Mode", "conversation_count": 0, "last_updated": None},
            {"mode": "elder", "display_name": "Elder Mode", "conversation_count": 0, "last_updated": None},
            {"mode": "assistant", "display_name": "Assistant Mode", "conversation_count": 0, "last_updated": None} 
        ]
        return {"modes": default_modes, "total": len(default_modes), "status": "success"}
    return {"modes": modes_summary, "total": len(modes_summary), "status": "success"}


@router.get("/conversations/{mode}")
async def get_conversations_by_mode(
    mode: str,
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """List unarchived conversations for selected mode."""
    history_manager: HistoryManager = request.app.state.history_manager
    conversations = await history_manager.get_user_conversations_by_mode(user_id, mode)
    return {"conversations": conversations, "mode": mode, "total": len(conversations), "status": "success"}


@router.get("/conversation/{conversation_id}")
async def get_conversation_messages(
    conversation_id: str,
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Fetch messages for selected conversation."""
    history_manager: HistoryManager = request.app.state.history_manager
    conversation_details = await history_manager.get_conversation_details(conversation_id, user_id)
    if not conversation_details:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await history_manager.get_conversation_messages(conversation_id)
    return {"conversation": conversation_details, "messages": messages, "conversation_id": conversation_id, "total_messages": len(messages), "status": "success"}


# ------------------ Create / Select ------------------

@router.post("/new-chat")
async def create_new_chat(
    request_data: NewChatRequest,
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Always create NEW conversation id."""
    history_manager: HistoryManager = request.app.state.history_manager
    conversation_id = await history_manager.start_new_conversation(user_id=user_id, mode=request_data.mode)
    return {"conversation_id": conversation_id, "message": "New chat created successfully", "status": "success"}


# @router.post("/set-active")
# async def set_active_conversation(
#     request_data: SetActiveConversationRequest,
#     request: Request,
#     user_id: str = Depends(get_current_history_user_id),
# ):
#     """Set active conversation."""
#     history_manager: HistoryManager = request.app.state.history_manager
#     try:
#         await history_manager.set_active_conversation(user_id=user_id, conversation_id=request_data.conversation_id)
#         return {"message": "Active conversation updated", "conversation_id": request_data.conversation_id, "status": "success"}
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=str(e))
@router.post("/set-active")
async def set_active_conversation(
    request_data: SetActiveConversationRequest,
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Set active conversation."""
    history_manager: HistoryManager = request.app.state.history_manager
    redis_client = request.app.state.redis   # <-- Redis client

    try:
        # 1. DB में active conversation set करना
        await history_manager.set_active_conversation(
            user_id=user_id,
            conversation_id=request_data.conversation_id
        )

        # 2. Redis cache में भी save कर देना (1 घंटे expiry)
        await redis_client.setex(
            f"user:{user_id}:active_conversation",
            3600,  # expiry in seconds
            str(request_data.conversation_id)
        )

        return {
            "message": "Active conversation updated",
            "conversation_id": str(request_data.conversation_id),
            "status": "success",
            "cached_in": "redis"
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to set active conversation: {str(e)}")



@router.get("/conversations")
async def get_user_conversations(
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """All unarchived conversations with preview."""
    history_manager: HistoryManager = request.app.state.history_manager
    conversations = await history_manager.get_user_conversations_with_preview(user_id=user_id)
    return {"conversations": conversations, "total": len(conversations), "status": "success"}


# ------------------ Soft delete / Restore ------------------

@router.delete("/conversation/{conversation_id}")
async def archive_conversation(
    conversation_id: str,
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Soft-delete conversation."""
    history_manager: HistoryManager = request.app.state.history_manager
    await history_manager.archive_conversation(conversation_id=conversation_id, user_id=user_id)
    return {"message": "Conversation archived successfully", "conversation_id": conversation_id, "status": "success"}


@router.post("/conversation/restore")
async def restore_conversation(
    req: RestoreConversationRequest,
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Restore an archived conversation."""
    history_manager: HistoryManager = request.app.state.history_manager
    await history_manager.unarchive_conversation(conversation_id=req.conversation_id, user_id=user_id)
    return {"status": "success", "message": "Conversation restored", "conversation_id": req.conversation_id}


@router.get("/archived")
async def list_archived(
    request: Request,
    mode: Optional[str] = Query(None),
    user_id: str = Depends(get_current_history_user_id),
):
    """List archived conversations."""
    history_manager: HistoryManager = request.app.state.history_manager
    data = await history_manager.list_archived_conversations(user_id=user_id, mode=mode)
    return {"status": "success", "archived": data, "total": len(data)}


@router.delete("/conversation/{conversation_id}/purge")
async def purge_conversation(
    conversation_id: str,
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Hard delete conversation."""
    history_manager: HistoryManager = request.app.state.history_manager
    await history_manager.purge_conversation(conversation_id=conversation_id, user_id=user_id)
    return {"status": "success", "message": "Conversation purged", "conversation_id": conversation_id}


# ------------------ Other helpers ------------------

@router.put("/conversation/title")
async def update_conversation_title(
    request_data: UpdateTitleRequest,
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Update conversation title."""
    history_manager: HistoryManager = request.app.state.history_manager
    await history_manager.update_conversation_title(
        conversation_id=request_data.conversation_id,
        new_title=request_data.new_title,
        user_id=user_id,
    )
    return {"message": "Title updated successfully", "new_title": request_data.new_title, "status": "success"}


@router.post("/message/save")
async def save_message(
    message: MessageCreate,
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Save message."""
    history_manager: HistoryManager = request.app.state.history_manager
    await history_manager.save_message(conversation_id=message.conversation_id, role=message.role, content=message.content)
    return {"status": "saved"}


# ------------------ Settings ------------------

@router.get("/settings")
async def get_settings(
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Fetch per-user history settings."""
    history_manager: HistoryManager = request.app.state.history_manager
    data = await history_manager.get_user_settings(user_id)
    return {"status": "success", "settings": data}


@router.put("/settings")
async def update_settings(
    body: SettingsUpdate,
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    """Update per-user history settings."""
    history_manager: HistoryManager = request.app.state.history_manager
    days = None if body.forever_save else (body.auto_delete_days if body.auto_delete_days and body.auto_delete_days > 0 else None)
    await history_manager.upsert_user_settings(user_id, body.forever_save, days)
    return {"status": "success", "message": "Settings updated", "settings": {"forever_save": body.forever_save, "auto_delete_days": days}}


# ------------------ Download / Export ------------------

@router.get("/download/conversation")
async def download_conversation(
    conversation_id: str,
    format: str = Query("pdf"),
    request: Request = None,
    user_id: str = Depends(get_current_history_user_id),
):
    history_manager: HistoryManager = request.app.state.history_manager
    if format not in ("pdf", "txt", "json"):
        raise HTTPException(status_code=400, detail="Unsupported format")
    try:
        payload_bytes, mime, filename = await history_manager.export_single_conversation(
            user_id=user_id, conversation_id=conversation_id, out_format=format
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=payload_bytes, media_type=mime, headers=headers)


@router.post("/clear-all")
async def clear_all_history(
    request: Request,
    user_id: str = Depends(get_current_history_user_id),
):
    history_manager: HistoryManager = request.app.state.history_manager
    try:
        count = await history_manager.archive_all_conversations(user_id)
        return {"status": "success", "archived": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/pdf")
async def download_pdf(
    request: Request,
    mode: Optional[str] = Query(None),
    user_id: str = Depends(get_current_history_user_id),
):
    """Export conversations to PDF."""
    history_manager: HistoryManager = request.app.state.history_manager
    try:
        pdf_bytes = await history_manager.export_history_pdf(user_id=user_id, mode=mode)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    filename = f"inai_history_{user_id}{'_' + mode if mode else ''}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)





from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ConversationCreate(BaseModel):
    user_id: str
    mode: str

class MessageCreate(BaseModel):
    conversation_id: str
    role: str           # "user" | "assistant"
    content: str
    
class MessageCreate(BaseModel):
    conversation_id: str
    role: str
    content: str


class ConversationCreate(BaseModel):
    user_id: str
    title: str
    mode: str


class MessageResponse(BaseModel):
    role: str
    content: str
    created_at: datetime
    audio_url: Optional[str]


class ConversationResponse(BaseModel):
    id: str
    title: str
    mode: str
    created_at: datetime
    updated_at: datetime
    is_archived: bool
    preview: Optional[str] = None
    message_count: Optional[int] = 0


class ConversationWithMessages(BaseModel):
    conversation: ConversationResponse
    messages: List[MessageResponse]
    total_messages: int


class ModeResponse(BaseModel):
    mode: str
    display_name: str
    conversation_count: int
    last_updated: Optional[datetime]


class HistoryFlowResponse(BaseModel):
    """Response for history flow endpoints"""
    status: str
    message: Optional[str] = None


class ModesListResponse(HistoryFlowResponse):
    modes: List[ModeResponse]
    total: int


class ConversationsListResponse(HistoryFlowResponse):
    conversations: List[ConversationResponse]
    mode: str
    total: int


class ConversationDetailResponse(HistoryFlowResponse):
    conversation: ConversationResponse
    messages: List[MessageResponse]
    conversation_id: str
    total_messages: int


# Request schemas for history flow
class SelectModeRequest(BaseModel):
    user_id: str
    mode: str


class SelectConversationRequest(BaseModel):
    user_id: str
    conversation_id: str



class CreateNewConversationFromHistory(BaseModel):
    user_id: str
    mode: str
    title: str = "New Conversation"
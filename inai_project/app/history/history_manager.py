import logging
import ssl
import uuid
import re
import datetime
import os
from io import BytesIO
from typing import Dict, List, Optional
from pathlib import Path
from asyncio import Lock

import asyncpg
import boto3
import redis.asyncio as redis
import json
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Email Configuration
EMAIL_CONFIG = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_FROM=os.getenv("MAIL_FROM"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
    MAIL_SERVER=os.getenv("MAIL_SERVER"),
    MAIL_FROM_NAME=os.getenv("MAIL_FROM_NAME", "INAI"),
    MAIL_STARTTLS=os.getenv("MAIL_STARTTLS", "True").lower() == "true",
    MAIL_SSL_TLS=os.getenv("MAIL_SSL_TLS", "False").lower() == "true",
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

# Logging Configuration
logger = logging.getLogger("HistoryManager")
logging.basicConfig(level=logging.INFO)

# SQL Queries
SQL_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_archived BOOLEAN DEFAULT FALSE,
    archived_at TIMESTAMP NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    audio_url TEXT
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT PRIMARY KEY,
    forever_save BOOLEAN DEFAULT TRUE,
    auto_delete_days INT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

SQL_ALTER_ARCHIVED_AT = """
ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL
"""

SQL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_mode ON conversations(mode)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_is_archived ON conversations(is_archived)",
    "CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id)",
]

SQL_GET_USER_SETTINGS = """
SELECT forever_save, auto_delete_days
FROM user_settings
WHERE user_id = $1
"""

SQL_UPSERT_USER_SETTINGS = """
INSERT INTO user_settings (user_id, forever_save, auto_delete_days, updated_at)
VALUES ($1, $2, $3, NOW())
ON CONFLICT (user_id) DO UPDATE
SET forever_save = EXCLUDED.forever_save,
    auto_delete_days = EXCLUDED.auto_delete_days,
    updated_at = NOW()
"""

SQL_ENFORCE_AUTO_ARCHIVE = """
UPDATE conversations
SET is_archived = TRUE,
    archived_at = COALESCE(archived_at, NOW()),
    updated_at = NOW()
WHERE user_id = $1
  AND is_archived = FALSE
  AND updated_at < (NOW() - ($2 || ' days')::interval)
"""

SQL_CONV_TITLE_AND_COUNT = """
SELECT title,
       (SELECT COUNT(*) FROM messages WHERE conversation_id=$1) AS msg_count
FROM conversations
WHERE id=$1
"""

SQL_UPDATE_CONV_TITLE = """
UPDATE conversations
SET title=$1, updated_at=NOW()
WHERE id=$2
"""

SQL_VALIDATE_ACTIVE = """
SELECT id
FROM conversations
WHERE id=$1 AND user_id=$2 AND mode=$3 AND is_archived=false
"""

SQL_NEW_CONVERSATION = """
INSERT INTO conversations (id, user_id, title, mode, created_at, updated_at)
VALUES ($1, $2, $3, $4, NOW(), NOW())
"""

SQL_LAST_ACTIVE_CONVERSATION = """
SELECT id FROM conversations
WHERE user_id=$1 AND mode=$2 AND is_archived=false
ORDER BY updated_at DESC
LIMIT 1
"""

SQL_CONV_MODE_USER_ARCHIVE = """
SELECT mode, user_id, is_archived
FROM conversations
WHERE id=$1
"""

SQL_INSERT_MESSAGE = """
INSERT INTO messages (conversation_id, role, content, audio_url, created_at)
VALUES ($1, $2, $3, $4, NOW())
"""

SQL_TOUCH_CONVERSATION = """
UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = $1
"""

SQL_IS_ARCHIVED = """
SELECT is_archived FROM conversations WHERE id=$1
"""

SQL_FETCH_MESSAGES = """
SELECT role, content, created_at, audio_url
FROM messages
WHERE conversation_id = $1
ORDER BY created_at ASC
"""

SQL_CONVS_BY_MODE = """
SELECT
    c.id,
    c.title,
    c.mode,
    c.created_at,
    c.updated_at,
    c.is_archived,
    m.content as last_message,
    COUNT(msg.id) as message_count
FROM conversations c
LEFT JOIN LATERAL (
    SELECT content
    FROM messages
    WHERE conversation_id = c.id
    ORDER BY created_at DESC
    LIMIT 1
) m ON true
LEFT JOIN messages msg ON msg.conversation_id = c.id
WHERE c.user_id = $1 AND c.mode = $2 AND c.is_archived = false
GROUP BY c.id, c.title, c.mode, c.created_at, c.updated_at, c.is_archived, m.content
ORDER BY c.updated_at DESC
"""

SQL_MODES_SUMMARY = """
SELECT
    mode,
    COUNT(*) as conversation_count,
    MAX(updated_at) as last_updated
FROM conversations
WHERE user_id = $1 AND is_archived = false
GROUP BY mode
ORDER BY last_updated DESC
"""

SQL_CONVS_ALL_ACTIVE = """
SELECT
    c.id,
    c.title,
    c.mode,
    c.created_at,
    c.updated_at,
    c.is_archived,
    m.content as last_message,
    COUNT(msg.id) as message_count
FROM conversations c
LEFT JOIN LATERAL (
    SELECT content
    FROM messages
    WHERE conversation_id = c.id
    ORDER BY created_at DESC
    LIMIT 1
) m ON true
LEFT JOIN messages msg ON msg.conversation_id = c.id
WHERE c.user_id = $1 AND c.is_archived = false
GROUP BY c.id, c.title, c.mode, c.created_at, c.updated_at, c.is_archived, m.content
ORDER BY c.updated_at DESC
"""

SQL_CONV_DETAILS = """
SELECT id, title, mode, created_at, updated_at, is_archived, archived_at
FROM conversations
WHERE id = $1 AND user_id = $2
"""

SQL_CONV_MODE_FOR_USER = """
SELECT mode FROM conversations WHERE id=$1 AND user_id=$2
"""

SQL_ARCHIVE_CONV = """
UPDATE conversations
SET is_archived=true, archived_at=NOW(), updated_at=NOW()
WHERE id=$1 AND user_id=$2
"""

SQL_UNARCHIVE_CONV = """
UPDATE conversations
SET is_archived=false, archived_at=NULL, updated_at=NOW()
WHERE id=$1 AND user_id=$2
"""

SQL_LIST_ARCHIVED_BY_MODE = """
SELECT c.id, c.title, c.mode, c.created_at, c.updated_at, c.archived_at, c.is_archived,
       (SELECT content FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) AS last_message
FROM conversations c
WHERE c.user_id=$1 AND c.is_archived=true AND c.mode=$2
ORDER BY c.archived_at DESC NULLS LAST, c.updated_at DESC
"""

SQL_LIST_ARCHIVED_ALL = """
SELECT c.id, c.title, c.mode, c.created_at, c.updated_at, c.archived_at, c.is_archived,
       (SELECT content FROM messages WHERE conversation_id=c.id ORDER BY created_at DESC LIMIT 1) AS last_message
FROM conversations c
WHERE c.user_id=$1 AND c.is_archived=true
ORDER BY c.archived_at DESC NULLS LAST, c.updated_at DESC
"""

SQL_PURGE_CONV = """
DELETE FROM conversations WHERE id=$1 AND user_id=$2
"""

SQL_EXPORT_CONV_META = """
SELECT id, title, mode, created_at, updated_at, is_archived
FROM conversations WHERE id=$1 AND user_id=$2
"""

SQL_HISTORY_CONVS_ACTIVE_BY_MODE = """
SELECT id, title, mode, created_at, updated_at
FROM conversations
WHERE user_id=$1 AND is_archived=FALSE AND mode=$2
ORDER BY updated_at DESC
"""

SQL_HISTORY_CONVS_ACTIVE_ALL = """
SELECT id, title, mode, created_at, updated_at
FROM conversations
WHERE user_id=$1 AND is_archived=FALSE
ORDER BY updated_at DESC
"""

SQL_ARCHIVE_ALL = """
UPDATE conversations
SET is_archived = TRUE,
    archived_at = COALESCE(archived_at, NOW()),
    updated_at = NOW()
WHERE user_id=$1 AND is_archived=FALSE
"""

class HistoryManager:
    """Manages chat history, conversations, messages, exports, and user settings."""

    def __init__(
        self,
        db_url: str,
        bucket_name: str,
        aws_access_key: str,
        aws_secret_key: str,
        region: str,
        logger: logging.Logger = logger,
        rds_ca_path: Optional[str] = r"E:\INAI_Backend_MD_Final 2\certs\rds-ca.pem",
        redis_url: str = "redis://localhost:7272/0"
    ):
        self.db_url = db_url
        self.bucket_name = bucket_name
        self.region = region
        self.logger = logger
        self._rds_ca_path = rds_ca_path
        self.redis = redis.from_url(redis_url, decode_responses=True)

        self.pool: Optional[asyncpg.Pool] = None
        self.active_conversations: Dict[str, Dict[str, str]] = {}
        self._locks: Dict[str, Lock] = {}

        try:
            self.s3 = boto3.client(
                "s3",
                region_name=region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
            )
            self.logger.info("S3 client initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize S3 client: {e}")
            self.s3 = None

    # Database Operations
    async def init_db(self) -> None:
        """Create pool and ensure tables/indexes exist."""
        try:
            ssl_context = (
                ssl.create_default_context(cafile=self._rds_ca_path)
                if self._rds_ca_path
                else None
            )
            self.pool = await asyncpg.create_pool(
                dsn=self.db_url,
                min_size=1,
                max_size=10,
                command_timeout=60,
                ssl=ssl_context,
            )
            async with self.pool.acquire() as conn:
                for stmt in SQL_CREATE_TABLES.split(";\n"):
                    if stmt.strip():
                        await conn.execute(stmt)
                await conn.execute(SQL_ALTER_ARCHIVED_AT)
                for idx in SQL_INDEXES:
                    await conn.execute(idx)
            self.logger.info("✅ Database tables created/verified successfully.")
        except Exception as e:
            self.logger.error(f"❌ Database initialization failed: {e}")
            raise

    async def close(self) -> None:
        """Close pool."""
        if self.pool:
            await self.pool.close()
            self.logger.info("Database connection closed")

    # Internal Helpers
    @staticmethod
    def _lock_key(user_id: str, mode: str) -> str:
        return f"{user_id}:{mode}"

    def _get_lock(self, user_id: str, mode: str) -> Lock:
        key = self._lock_key(user_id, mode)
        if key not in self._locks:
            self._locks[key] = Lock()
        return self._locks[key]

    def _get_active_conversation_id(self, user_id: str, mode: str) -> Optional[str]:
        return self.active_conversations.get(user_id, {}).get(mode)

    def _set_active_conversation_id(
        self, user_id: str, mode: str, conversation_id: str
    ) -> None:
        self.active_conversations.setdefault(user_id, {})[mode] = conversation_id
        self.logger.info(
            f"🎯 Set active conversation: {conversation_id} for user {user_id} [{mode}]"
        )

    def _clear_active_conversation(self, user_id: str, mode: Optional[str] = None) -> None:
        if user_id not in self.active_conversations:
            return
        if mode is None:
            del self.active_conversations[user_id]
            self.logger.info(f"🗑️ Cleared all active conversations for user {user_id}")
        else:
            self.active_conversations[user_id].pop(mode, None)
            self.logger.info(
                f"🗑️ Cleared active conversation for user {user_id}[{mode}]"
            )
        if user_id in self.active_conversations and not self.active_conversations[user_id]:
            del self.active_conversations[user_id]

    # User Settings
    async def get_user_settings(self, user_id: str) -> Dict:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(SQL_GET_USER_SETTINGS, user_id)
            if row:
                return dict(row)
            return {"forever_save": True, "auto_delete_days": None}
        except Exception as e:
            self.logger.error(f"❌ get_user_settings failed: {e}")
            return {"forever_save": True, "auto_delete_days": None}

    async def upsert_user_settings(
        self, user_id: str, forever_save: bool, auto_delete_days: Optional[int]
    ) -> None:
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    SQL_UPSERT_USER_SETTINGS, user_id, forever_save, auto_delete_days
                )
            self.logger.info(
                f"⚙️ Settings updated for {user_id}: forever={forever_save}, days={auto_delete_days}"
            )
        except Exception as e:
            self.logger.error(f"❌ upsert_user_settings failed: {e}")
            raise

    async def enforce_auto_archive(self, user_id: str) -> str:
        """Apply auto-archive based on settings; returns PG status or 'noop'/'error'."""
        try:
            s = await self.get_user_settings(user_id)
            if s.get("forever_save", True):
                return "noop"
            days = s.get("auto_delete_days")
            if not days or days <= 0:
                return "noop"
            async with self.pool.acquire() as conn:
                res = await conn.execute(SQL_ENFORCE_AUTO_ARCHIVE, user_id, days)
                self.logger.info(f"🧹 Auto-archive applied for {user_id}: {res}")
                return res
        except Exception as e:
            self.logger.error(f"❌ enforce_auto_archive failed: {e}")
            return "error"

    # Title Management
    def _generate_title_from_response(self, ai_response: str) -> str:
        if not ai_response or not ai_response.strip():
            return "New Conversation"
        response = ai_response.strip()
        sentences = response.split(".")
        first_sentence = sentences[0].strip()
        if len(first_sentence) < 10 and len(sentences) > 1:
            first_sentence = (first_sentence + ". " + sentences[1]).strip()
        title = first_sentence[:47] + "..." if len(first_sentence) > 50 else first_sentence
        for p in [
            "I understand",
            "I can help",
            "Sure",
            "Of course",
            "Let me help",
            "I'd be happy",
            "Certainly",
            "Hello",
        ]:
            if title.lower().startswith(p.lower()):
                title = title[len(p) :].lstrip(" ,.")
                break
        if not title:
            title = "New Conversation"
        return title[0].upper() + title[1:] if len(title) > 1 else title.upper()

    def _generate_title_from_user(self, user_text: str) -> str:
        if not user_text or not user_text.strip():
            return "New Conversation"
        text = user_text.strip()
        parts = text.split(".")
        first = parts[0].strip()
        if len(first) < 15 and len(parts) > 1:
            first = (first + ". " + parts[1].strip())[:50]
        return (
            first[:47] + "..."
            if len(first) > 50
            else (first[0].upper() + first[1:] if len(first) > 1 else first.upper())
        )

    async def ensure_title_on_first_message(self, conversation_id: str, user_message: str) -> None:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(SQL_CONV_TITLE_AND_COUNT, conversation_id)
                if not row:
                    return
                if row["msg_count"] == 0 and (row["title"] not in (None, "", "New Conversation")):
                    return
        except Exception as e:
            self.logger.error(f"❌ ensure_title_on_first_message failed: {e}")

    async def ensure_title_on_second_message(self, conversation_id: str, role: str, content: str) -> None:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(SQL_CONV_TITLE_AND_COUNT, conversation_id)
                if not row:
                    return
                current_title = (row["title"] or "").strip()
                msg_count = int(row["msg_count"] or 0)
                if msg_count == 2 and current_title in ("", "New Conversation", "Untitled"):
                    if role == "user":
                        new_title = self._generate_title_from_user(content or "")
                    else:
                        new_title = self._generate_title_from_response(content or "")
                    await conn.execute(SQL_UPDATE_CONV_TITLE, new_title, conversation_id)
                    self.logger.info(f"📝 Title auto-updated on 2nd message [{conversation_id}] -> {new_title}")
        except Exception as e:
            self.logger.error(f"❌ ensure_title_on_second_message failed: {e}")

    async def update_conversation_title(
        self, conversation_id: str, new_title: str, user_id: str
    ) -> None:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id FROM conversations WHERE id=$1 AND user_id=$2",
                    conversation_id,
                    user_id,
                )
                if not row:
                    raise Exception("Conversation not found or not owned by user")
                await conn.execute(
                    SQL_UPDATE_CONV_TITLE, (new_title or "Untitled").strip(), conversation_id
                )
            self.logger.info(f"📝 Title updated [{conversation_id}] -> {new_title}")
        except Exception as e:
            self.logger.error(f"❌ update_conversation_title failed: {e}")
            raise

    # Conversation Management
    async def _validate_active_mapping(self, user_id: str, mode: str) -> Optional[str]:
        mapped = self._get_active_conversation_id(user_id, mode)
        if not mapped:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(SQL_VALIDATE_ACTIVE, mapped, user_id, mode)
                if row:
                    return str(row["id"])
        except Exception as e:
            self.logger.error(f"validate_active_mapping error: {e}")
        self._clear_active_conversation(user_id, mode)
        return None

    async def get_current_conversation_id(self, user_id: str, mode: str) -> Optional[str]:
        return await self._validate_active_mapping(user_id, mode)

    async def start_new_conversation(self, user_id: str, mode: str) -> str:
        conversation_id = str(uuid.uuid4())
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    SQL_NEW_CONVERSATION, conversation_id, user_id, "New Conversation", mode
                )
            self._set_active_conversation_id(user_id, mode, conversation_id)
            self.logger.info(
                f"🚀 Created new conversation: {conversation_id} for {user_id} [{mode}]"
            )
            return conversation_id
        except Exception as e:
            self.logger.error(f"❌ Failed to create new conversation: {e}")
            raise

    async def get_or_create_authoritative(self, user_id: str, mode: str) -> str:
        lock = self._get_lock(user_id, mode)
        async with lock:
            mapped = await self._validate_active_mapping(user_id, mode)
            if mapped:
                return mapped
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(SQL_LAST_ACTIVE_CONVERSATION, user_id, mode)
                if row:
                    conv_id = str(row["id"])
                    self._set_active_conversation_id(user_id, mode, conv_id)
                    return conv_id
            return await self.start_new_conversation(user_id, mode)

    async def set_active_conversation(self, user_id: str, conversation_id: str) -> None:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(SQL_CONV_MODE_USER_ARCHIVE, conversation_id)
            if not row or row["user_id"] != user_id or row["is_archived"]:
                raise Exception("Conversation not found / not owned / archived")
            mode = row["mode"]
            self._set_active_conversation_id(user_id, mode, conversation_id)
            self.logger.info(
                f"🔄 Active conversation changed to {conversation_id} for user {user_id} [{mode}]"
            )
        except Exception as e:
            self.logger.error(f"❌ Failed to set active conversation: {e}")
            raise

    async def create_conversation_with_first_exchange(
        self,
        user_id: str,
        mode: str,
        user_message: str,
        ai_response: str,
        audio_url: str = None,
    ) -> str:
        conversation_id = str(uuid.uuid4())
        title = "New Conversation"
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "INSERT INTO conversations (id, user_id, title, mode) VALUES ($1, $2, $3, $4)",
                        conversation_id, user_id, title, mode,
                    )
                    await conn.execute(
                        "INSERT INTO messages (conversation_id, role, content) VALUES ($1, $2, $3)",
                        conversation_id, "user", user_message,
                    )
                    await conn.execute(
                        "INSERT INTO messages (conversation_id, role, content, audio_url) VALUES ($1, $2, $3, $4)",
                        conversation_id, "assistant", ai_response, audio_url,
                    )
            await self.ensure_title_on_second_message(conversation_id, "assistant", ai_response or "")
            self._set_active_conversation_id(user_id, mode, conversation_id)
            self.logger.info(f"NEW CHAT WITH EXCHANGE: {conversation_id} 'New Conversation' for {user_id} [{mode}]")
            return conversation_id
        except Exception as e:
            self.logger.error(f"Failed to create conversation with first exchange: {e}")
            raise

    async def get_or_create_conversation_with_exchange(
        self,
        user_id: str,
        mode: str,
        user_message: str,
        ai_response: str,
        audio_url: str = None,
    ) -> str:
        lock = self._get_lock(user_id, mode)
        async with lock:
            mapped = await self._validate_active_mapping(user_id, mode)
            if mapped:
                await self.save_message(mapped, "user", user_message)
                await self.save_message(mapped, "assistant", ai_response, audio_url)
                return mapped
            return await self.create_conversation_with_first_exchange(
                user_id, mode, user_message, ai_response, audio_url
            )

    # Message Management
    async def _ensure_not_archived(self, conversation_id: str) -> None:
        async with self.pool.acquire() as conn:
            archived = await conn.fetchval(SQL_IS_ARCHIVED, conversation_id)
        if archived is None:
            raise Exception("Conversation not found")
        if archived:
            raise Exception("Cannot add messages to an archived conversation")

    async def save_message(
        self, conversation_id: str, role: str, content: str, audio_url: str = None
    ) -> None:
        try:
            await self._ensure_not_archived(conversation_id)
            async with self.pool.acquire() as conn:
                await conn.execute(SQL_INSERT_MESSAGE, conversation_id, role, content, audio_url)
                await conn.execute(SQL_TOUCH_CONVERSATION, conversation_id)
            await self.ensure_title_on_second_message(conversation_id, role, content or "")
            self.logger.info(f"Saved {role} message to conversation {conversation_id}")
        except Exception as e:
            self.logger.error(f"Failed to save message: {e}")
            raise

    async def upload_audio_bytes(self, audio_bytes: bytes) -> Optional[str]:
        if not self.s3:
            self.logger.error("S3 client not initialized")
            return None
        try:
            filename = f"audio_{uuid.uuid4()}.mp3"
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=filename,
                Body=audio_bytes,
                ContentType="audio/mpeg",
            )
            url = f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{filename}"
            self.logger.info(f"Audio uploaded: {url}")
            return url
        except Exception as e:
            self.logger.error(f"Error uploading audio: {e}")
            return None

    async def save_message_with_audio_bytes(
        self, conversation_id: str, role: str, content: str, audio_bytes: bytes = None
    ) -> Optional[str]:
        audio_url = None
        if audio_bytes:
            audio_url = await self.upload_audio_bytes(audio_bytes)
        await self.save_message(conversation_id, role, content, audio_url)
        return audio_url

    # Fetch Operations
    async def get_conversation_messages(self, conversation_id: str) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(SQL_FETCH_MESSAGES, conversation_id)
            return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Failed to get messages: {e}")
            return []

    async def get_user_conversations_by_mode(self, user_id: str, mode: str) -> List[Dict]:
        try:
            await self.enforce_auto_archive(user_id)
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(SQL_CONVS_BY_MODE, user_id, mode)
            conversations: List[Dict] = []
            for row in rows:
                conv = dict(row)
                last = conv.get("last_message") or ""
                conv["preview"] = (last[:50] + "...") if len(last) > 50 else (last or "No messages yet")
                conversations.append(conv)
            self.logger.info(
                f"Found {len(conversations)} conversations for user {user_id} in mode {mode}"
            )
            return conversations
        except Exception as e:
            self.logger.error(
                f"Failed to get mode-wise conversations for {user_id}: {e}"
            )
            return []

    async def get_user_modes_summary(self, user_id: str) -> List[Dict]:
        try:
            await self.enforce_auto_archive(user_id)
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(SQL_MODES_SUMMARY, user_id)
            out: List[Dict] = []
            names = {
                "friend": "Friend Mode",
                "information": "Information Mode",
                "love": "Love Mode",
                "elder": "Elder Mode",
                "assistant": "Assistant Mode"
            }
            for r in rows:
                d = dict(r)
                d["display_name"] = names.get(d["mode"], d["mode"].title())
                out.append(d)
            self.logger.info(f"Found {len(out)} active modes for user {user_id}")
            return out
        except Exception as e:
            self.logger.error(f"Failed to get modes summary for {user_id}: {e}")
            return []

    async def get_user_conversations_with_preview(self, user_id: str) -> List[Dict]:
        cache_key = f"user:{user_id}:conversations_preview"
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)
        try:
            await self.enforce_auto_archive(user_id)
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(SQL_CONVS_ALL_ACTIVE, user_id)
            conversations: List[Dict] = []
            for row in rows:
                conv = dict(row)
                last = conv.get("last_message") or ""
                conv["preview"] = (last[:50] + "...") if len(last) > 50 else (last or "No messages yet")
                conversations.append(conv)
            await self.redis.setex(cache_key, 60, json.dumps(conversations))
            return conversations
        except Exception as e:
            self.logger.error(f"Failed to get conversations for user {user_id}: {e}")
            return []

    async def get_conversation_details(
        self, conversation_id: str, user_id: str
    ) -> Optional[Dict]:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(SQL_CONV_DETAILS, conversation_id, user_id)
            return dict(row) if row else None
        except Exception as e:
            self.logger.error(f"❌ Failed to get conversation details: {e}")
            return None

    # Archive Operations
    async def archive_conversation(self, conversation_id: str, user_id: str) -> None:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(SQL_CONV_MODE_FOR_USER, conversation_id, user_id)
                if not row:
                    raise Exception("Conversation not found or doesn't belong to user")
                mode = row["mode"]
                await conn.execute(SQL_ARCHIVE_CONV, conversation_id, user_id)
            if self._get_active_conversation_id(user_id, mode) == conversation_id:
                self._clear_active_conversation(user_id, mode)
            self.logger.info(f"🗄️ Archived conversation {conversation_id} for user {user_id}")
        except Exception as e:
            self.logger.error(f" Failed to archive conversation: {e}")
            raise

    async def unarchive_conversation(self, conversation_id: str, user_id: str) -> None:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(SQL_CONV_MODE_FOR_USER, conversation_id, user_id)
                if not row:
                    raise Exception("Conversation not found or doesn't belong to user")
                mode = row["mode"]
                await conn.execute(SQL_UNARCHIVE_CONV, conversation_id, user_id)
            self._set_active_conversation_id(user_id, mode, conversation_id)
            self.logger.info(f"♻️ Unarchived conversation {conversation_id} for user {user_id}")
        except Exception as e:
            self.logger.error(f"❌ Failed to unarchive conversation: {e}")
            raise

    async def list_archived_conversations(
        self, user_id: str, mode: Optional[str] = None
    ) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                if mode:
                    rows = await conn.fetch(SQL_LIST_ARCHIVED_BY_MODE, user_id, mode)
                else:
                    rows = await conn.fetch(SQL_LIST_ARCHIVED_ALL, user_id)
            out: List[Dict] = []
            for r in rows:
                d = dict(r)
                last = d.get("last_message") or ""
                d["preview"] = (last[:50] + "...") if len(last) > 50 else last
                out.append(d)
            return out
        except Exception as e:
            self.logger.error(f"❌ Failed to list archived conversations: {e}")
            return []

    async def purge_conversation(self, conversation_id: str, user_id: str) -> None:
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(SQL_PURGE_CONV, conversation_id, user_id)
            for mode, conv_id in list(self.active_conversations.get(user_id, {}).items()):
                if conv_id == conversation_id:
                    self._clear_active_conversation(user_id, mode)
            self.logger.info(f"🧹 Purged conversation {conversation_id} for user {user_id}")
        except Exception as e:
            self.logger.error(f"❌ Failed to purge conversation: {e}")
            raise

    # Export Operations
    async def export_single_conversation(
        self,
        user_id: str,
        conversation_id: str,
        out_format: str = "pdf",
    ):
        """Export a single conversation in PDF format (Hindi + English + Gujarati support)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(SQL_EXPORT_CONV_META, conversation_id, user_id)
        if not row:
            raise RuntimeError("Conversation not found or not owned")
        conv = dict(row)
        msgs = await self.get_conversation_messages(conversation_id)

        def sanitize_filename(name: str) -> str:
            name = (name or "").strip() or "Untitled"
            return re.sub(r'[^a-zA-Z0-9_ -]', "_", name)

        safe_title = sanitize_filename(conv.get("title") or "Untitled")

        if out_format != "pdf":
            raise RuntimeError("Only PDF format is supported")

        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4

        FONT_LATIN = "Helvetica"
        HERE = Path(__file__).resolve()
        candidate_dirs = []
        FONT_DIR_ENV = os.getenv("FONT_DIR")
        if FONT_DIR_ENV:
            candidate_dirs.append(Path(FONT_DIR_ENV))
        candidate_dirs += [
            HERE.parent / "static" / "fonts",
            Path.cwd() / "app" / "history" / "static" / "fonts",
        ]

        def find_font(*names: str) -> Path | None:
            for d in candidate_dirs:
                for n in names:
                    p = (d / n).resolve()
                    if p.exists():
                        return p
            return None

        def is_valid_ttf(path: Path) -> bool:
            try:
                with open(path, "rb") as f:
                    head = f.read(4)
                return head in (b"\x00\x01\x00\x00", b"ttcf")
            except Exception:
                return False

        hindi_candidates = ["NotoSansDevanagari-Regular.ttf", "Mangal.ttf", "Nirmala.ttf"]
        gujarati_candidates = ["NotoSansGujarati-Regular.ttf"]

        def pick_font(candidates):
            for name in candidates:
                p = find_font(name)
                if p and is_valid_ttf(p):
                    return p
            return None

        hindi_path = pick_font(hindi_candidates)
        gujarati_path = pick_font(gujarati_candidates)

        if not hindi_path or not gujarati_path:
            raise RuntimeError(
                "Required fonts not found. Add TTFs in static/fonts or set FONT_DIR."
            )

        try:
            pdfmetrics.registerFont(TTFont("HindiFont", str(hindi_path)))
            pdfmetrics.registerFont(TTFont("GujaratiFont", str(gujarati_path)))
        except Exception as e:
            self.logger.error(f"Failed to register fonts: {e}")
            raise RuntimeError(f"Font registration failed: {e}")

        FONT_HINDI = "HindiFont"
        FONT_GUJARATI = "GujaratiFont"

        left, right = 2 * cm, width - 2 * cm
        top, bottom = height - 2 * cm, 2 * cm
        y = top

        FS_TITLE = 14
        FS_MODE = 11
        FS_TEXT = 11
        LINE_H = FS_TEXT * 1.4

        PAD_X, PAD_Y = 6, 6
        RADIUS = 8
        MAX_BUBBLE_W = (right - left) * 0.72

        def is_dev(ch: str) -> bool:
            return 0x0900 <= ord(ch) <= 0x097F

        def is_guj(ch: str) -> bool:
            return 0x0A80 <= ord(ch) <= 0x0AFF

        def split_runs(text: str):
            if not text:
                return []
            runs = []
            cur_type = "lat"
            first = text[0]
            if is_dev(first):
                cur_type = "dev"
            elif is_guj(first):
                cur_type = "guj"
            cur_buf = [first]
            for ch in text[1:]:
                if is_dev(ch):
                    t = "dev"
                elif is_guj(ch):
                    t = "guj"
                else:
                    t = "lat"
                if t == cur_type:
                    cur_buf.append(ch)
                else:
                    runs.append(("".join(cur_buf), cur_type))
                    cur_buf = [ch]
                    cur_type = t
            runs.append(("".join(cur_buf), cur_type))
            return runs

        def font_for(script: str) -> str:
            if script == "dev":
                return FONT_HINDI
            elif script == "guj":
                return FONT_GUJARATI
            return FONT_LATIN

        def line_width(line: str, size: int) -> float:
            total_width = 0.0
            for txt, scr in split_runs(line):
                try:
                    width = pdfmetrics.stringWidth(txt, font_for(scr), size)
                    total_width += width
                except Exception as e:
                    self.logger.error(f"Error calculating width for text '{txt}' with font {font_for(scr)}: {e}")
                    continue
            return total_width

        def wrap_text_multifont(text: str, max_w: float, size: int):
            lines, cur = [], ""
            for ch in text.replace("\r", ""):
                if ch == "\n":
                    lines.append(cur)
                    cur = ""
                    continue
                test = cur + ch
                if line_width(test, size) <= max_w or cur == "":
                    cur = test
                else:
                    lines.append(cur)
                    cur = ch
            if cur:
                lines.append(cur)
            return lines

        def draw_multifont_line(xpos: float, y_baseline: float, line: str, size: int):
            xcursor = xpos
            for txt, scr in split_runs(line):
                font = font_for(scr)
                try:
                    c.setFont(font, size)
                    c.drawString(xcursor, y_baseline, txt)
                    width = pdfmetrics.stringWidth(txt, font, size)
                    xcursor += width
                except Exception as e:
                    self.logger.error(f"Error drawing text '{txt}' with font {font}: {e}")
                    continue

        def draw_centered(text: str, y_baseline: float, size: int):
            w = line_width(text, size)
            draw_multifont_line((width - w) / 2.0, y_baseline, text, size)

        def clean_text(txt: str) -> str:
            return re.sub(r"[^\x09\x0A\x0D\x20-\uFFFF]", "", txt) if txt else ""

        def new_page():
            nonlocal y
            c.showPage()
            y = top

        def _draw_lines(lines, x, bubble_color, text_color, align_right=False):
            nonlocal y
            max_line_w = max((line_width(ln, FS_TEXT) for ln in lines), default=0)
            bubble_w = min(MAX_BUBBLE_W, max_line_w + 2 * PAD_X)
            text_h = len(lines) * LINE_H
            bubble_h = text_h + 2 * PAD_Y
            if align_right:
                x = right - bubble_w
            c.setFillColorRGB(*bubble_color)
            c.roundRect(x, y - bubble_h, bubble_w, bubble_h, RADIUS, stroke=0, fill=1)
            c.setFillColorRGB(*text_color)
            ty = y - PAD_Y - FS_TEXT
            for ln in lines:
                draw_multifont_line(x + PAD_X, ty, ln, FS_TEXT)
                ty -= LINE_H
            y -= bubble_h

        def draw_bubble(role: str, text: str, skip_check=False):
            nonlocal y
            text = clean_text(text)
            wrapped = wrap_text_multifont(text, MAX_BUBBLE_W - 2 * PAD_X, FS_TEXT)
            if role == "user":
                bubble_color = (0.85, 0.85, 0.85)
                text_color = (0, 0, 0)
                align_right = True
            else:
                bubble_color = (0.20, 0.20, 0.20)
                text_color = (1, 1, 1)
                align_right = False
            part = []
            for ln in wrapped:
                part.append(ln)
                part_h = len(part) * LINE_H + 2 * PAD_Y
                if y - part_h <= bottom + 20:
                    _draw_lines(part, left, bubble_color, text_color, align_right)
                    new_page()
                    part = []
            if part:
                _draw_lines(part, left, bubble_color, text_color, align_right)
            y -= 20

        c.setTitle(f"Inai Conversation - {conversation_id}")
        title_text = conv.get("title") or "Untitled"
        c.setFillColorRGB(0, 0, 0)
        draw_centered(title_text, y, FS_TITLE)
        y -= 0.6 * cm

        mode_label = conv.get("mode", "") or ""
        if mode_label:
            c.setFillColorRGB(0.3, 0.3, 0.3)
            draw_centered(mode_label, y, FS_MODE)
            y -= 0.8 * cm
        else:
            y -= 0.5 * cm

        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(1)
        c.line(left, y, right, y)
        y -= 0.6 * cm

        first_message = True
        for m in msgs:
            role = "user" if m.get("role") == "user" else "ai"
            text = m.get("content", "") or ""
            draw_bubble(role, text, skip_check=first_message)
            first_message = False

        c.save()
        pdf = buf.getvalue()
        buf.close()
        return pdf, "application/pdf", f"{safe_title}.pdf"

    # Bulk Operations
    async def archive_all_conversations(self, user_id: str) -> int:
        try:
            async with self.pool.acquire() as conn:
                res = await conn.execute(SQL_ARCHIVE_ALL, user_id)
                try:
                    count = int(res.split()[-1])
                except Exception:
                    count = 0
            self._clear_active_conversation(user_id, None)
            return count
        except Exception as e:
            self.logger.error(f"❌ archive_all_conversations failed: {e}")
            raise

    # Email Operations
    async def send_conversation_pdf_email(
        self,
        user_id: str,
        conversation_id: str,
        to_email: str,
        user_email: str = None
    ) -> Dict[str, str]:
        """Export conversation as PDF and send via email."""
        try:
            pdf_bytes, content_type, filename = await self.export_single_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
                out_format="pdf"
            )
            
            conv_details = await self.get_conversation_details(conversation_id, user_id)
            conv_title = conv_details.get('title', 'Untitled') if conv_details else 'Untitled'
            
            subject = "INAI Conversation Export - PDF"
            
            html_body = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>{subject}</title>
            </head>
            <body style="margin:0; padding:0; background:#f0f2f5; font-family:Arial, Helvetica, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="padding:30px 0; background:#f0f2f5;">
                <tr>
                    <td align="center">
                        <table cellpadding="0" cellspacing="0" border="0"
                            style="background:#ffffff; border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,0.15); 
                                   padding:25px; max-width:600px; width:100%;">
                            <tr>
                                <td align="center" style="padding-bottom:20px;">
                                    <h1 style="margin:0; font-size:24px; color:#2563eb; letter-spacing:2px;">INAI</h1>
                                </td>
                            </tr>
                            <tr>
                                <td style="text-align:left; font-size:15px; color:#333333; padding-bottom:20px;">
                                    <p style="margin:0 0 16px 0;">Hello,</p>
                                    <p style="margin:0 0 16px 0;">Please find attached your INAI conversation export in PDF format.</p>
                                    <p style="margin:0 0 16px 0;"><strong>Conversation:</strong> {conv_title}</p>
                                    <p style="margin:0 0 16px 0;"><strong>Exported on:</strong> {datetime.datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
                                </td>
                            </tr>
                            <tr>
                                <td align="center" style="padding:20px 0;">
                                    <div style="
                                        background:#f1f5f9; 
                                        padding:15px 20px; 
                                        border-radius:8px; 
                                        border-left:4px solid #2563eb;
                                    ">
                                        <p style="margin:0; font-size:14px; color:#1f2937;">
                                            📎 <strong>Attachment:</strong> {filename}
                                        </p>
                                    </div>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding:20px 0; text-align:center; font-size:13px; color:#666666; border-top:1px solid #e5e5e5;">
                                    <p style="margin:0 0 8px 0;">This export was generated from your INAI conversation history.</p>
                                    <p style="margin:0;">If you have any questions, contact us at 
                                    <a href="mailto:help@inaiworlds.com" style="color:#1a73e8; text-decoration:none;">help@inaiworlds.com</a>
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
            </body>
            </html>
            """

            message = MessageSchema(
                subject=subject,
                recipients=[to_email],
                body=html_body,
                subtype=MessageType.html,
                attachments=[
                    {
                        "file": pdf_bytes,
                        "filename": filename,
                        "content_type": content_type
                    }
                ]
            )

            fm = FastMail(EMAIL_CONFIG)
            await fm.send_message(message)
            
            self.logger.info(f"📧 PDF sent successfully to {to_email} for conversation {conversation_id}")
            
            return {
                "status": "success",
                "message": f"PDF exported and sent to {to_email}",
                "filename": filename,
                "conversation_title": conv_title
            }

        except Exception as e:
            self.logger.error(f"❌ Failed to send PDF email: {e}")
            return {
                "status": "error",
                "message": str(e)
            }

    # Back-compat Wrappers
    async def create_new_conversation(self, user_id: str, mode: str) -> str:
        return await self.start_new_conversation(user_id, mode)

    async def get_or_create_conversation(self, user_id: str, mode: str) -> str:
        return await self.get_or_create_authoritative(user_id, mode)
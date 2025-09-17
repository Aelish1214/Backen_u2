from fastapi import FastAPI, Request, HTTPException, Query
from fastapi import UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime , timedelta
from dotenv import load_dotenv
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
import mimetypes
import glob
from pathlib import Path
import os
import uuid
import logging
import json
import asyncio
from typing import Optional, Dict, Any

# -----------------------
# Your existing internal imports
# -----------------------
from .key_manager import (
    assign_key_to_user, release_key_for_user, get_monitor_data, get_usage_logs,
    add_tokens, check_user_limit, count_tokens, DEFAULT_DAILY_TOKEN_LIMIT,
    update_last_active, user_sessions
)
from .logger import Logger
from .config import Config
from .modes import ChatModes
from .tts import TextToSpeech
# from .subscription import Subscription
from .session import UserSessionManager
from .chat import ChatManager
from .speech import SpeechRecognition
from inai_project.app.history.history_manager import HistoryManager
from inai_project.app.history import history_routes
from inai_project.app.signup import models as signup_models
from inai_project.database import engine
from .socket import WebRTCHandler  # Your WebRTCHandler

# -----------------------
# NEW: Prometheus / Metrics imports (added as requested)
# -----------------------
# These come from your provided snippet; integrated without altering existing functionality.
from exporter import metrics_middleware, metrics_endpoint, http_exception_handler, validation_error_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError

# -----------------------
# App boot
# -----------------------
app = FastAPI()

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("INAIApp")

# -----------------------
# FastAPI setup
# (keeping your original setup & title)
# -----------------------
app = FastAPI(title="INAI WebRTC Chatbot", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------
# NEW: Metrics middleware & handlers (Prometheus)
# Placed after app is created and CORS middleware is added.
# -----------------------

# Collect per-request metrics
app.middleware("http")(metrics_middleware)

# Expose Prometheus metrics
@app.get("/metrics")
def get_metrics():
    return metrics_endpoint()

# Custom HTTP error handler (e.g., 404/500 coming from Starlette exceptions)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)

# Custom handler for request validation errors (400)
app.add_exception_handler(RequestValidationError, validation_error_handler)

# -----------------------
# Admin session management (from old main.py)
# NOTE: This is separate from any user session state you maintain elsewhere.
# -----------------------
SESSION_EXPIRE_MINUTES = 30
user_sessions = {}

# -----------------------
# Pydantic Models
# -----------------------
class OfferRequest(BaseModel):
    user_id: str
    sdp: str
    type: str
    
class IceCandidate(BaseModel):
    candidate: str
    sdpMid: Optional[str] = None
    sdpMLineIndex: Optional[int] = None
    
    class Config:
        extra = "allow"   # accept unknown fields

class CandidateRequest(BaseModel):
    user_id: str
    candidate: IceCandidate

class StreamingMessageRequest(BaseModel):
    user_id: str
    mode: str = "friend"
    text: str
    voice_model: str = "female1"  # Added voice model
    stream: bool = True

class AudioMessageRequest(BaseModel):
    user_id: str
    mode: str = "friend"
    audio: str
    voice_model: str = "female1"  # Added voice model

class TextMessageRequest(BaseModel):
    user_id: str
    mode: str = "friend"
    text: str
    voice_model: str = "female1"  # Added voice model
    stream: bool = False

class ToggleRequest(BaseModel):
    password: str

# -----------------------
# Admin Panel Middleware (from old main.py)
# -----------------------
@app.middleware("http")
async def protect_inai520(request: Request, call_next):
    path = request.url.path
    # Only protect INAI520 pages except login page
    if path.startswith("/INAI520") and path != "/INAI520":
        session_id = request.cookies.get("session_id")
        session = user_sessions.get(session_id)
        # No valid session or expired → redirect to login
        if not session or session["expires_at"] < datetime.utcnow():
            return RedirectResponse(url="/INAI520")
        # Update session expiry on activity
        session["expires_at"] = datetime.utcnow() + timedelta(minutes=SESSION_EXPIRE_MINUTES)
        user_sessions[session_id] = session
    return await call_next(request)

# -----------------------
# INAI Application Class
# -----------------------
class INAIApplication:
    def __init__(self, history_manager: HistoryManager):
        self.logger = Logger()
        self.config = Config()
        self.modes = ChatModes()
        self.history = history_manager
        self.tts = TextToSpeech(self.config, self.logger)
        self.chat_manager = ChatManager(self.config, self.modes, self.logger)
        self.speech_recognition = SpeechRecognition(self.logger)
        self.session_manager = UserSessionManager(self.logger)
        self.templates = Jinja2Templates(directory="templates")
        self.active_pcs: Dict[str, RTCPeerConnection] = {}

        # WebRTC connection tracking
        # self.active_pcs = {}  # user_id → RTCPeerConnection
        
        # Create WebRTC handler instance with enhanced features
        self.webrtc_handler = WebRTCHandler(
            session_manager=self.session_manager,
            config=self.config,
            tts=self.tts,
            chat_manager=self.chat_manager,
            speech_recognition=self.speech_recognition,
            history=self.history,
            modes=self.modes,
            logger=self.logger
        )

        # Mount static directories
        self.app = app
        self._setup_static_directories()
        self._setup_routes()

    def _setup_static_directories(self):
        """Setup static file directories"""
        directories = ["frontend", "uploads", "Data"]
        
        for directory in directories:
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                
            if directory == "Data":
                self.app.mount("/data", StaticFiles(directory=directory), name="data")
            else:
                self.app.mount(f"/{directory}", StaticFiles(directory=directory), name=directory)

    # -----------------------
    # Route Setup
    # -----------------------
    def _setup_routes(self):

        @self.app.post("/upload/pdf")
        async def upload_pdf(request: Request, file: UploadFile = File(...)):
            try:
                # Get form data
                form_data = await request.form()
                user_id = form_data.get("user_id", "default_user")
                mode = form_data.get("mode", "friend")
                instruction = form_data.get("instruction", "")
                
                api_key = user_sessions.get(user_id, {}).get("api_key", "default_api_key")
                instruction_tokens = count_tokens(instruction, api_key) if instruction else 0
                
                if not check_user_limit(user_id, instruction_tokens):
                    return {
                        "status": "error", 
                        "message": f"Daily token limit of {DEFAULT_DAILY_TOKEN_LIMIT} exceeded."
                    }
                
                # Save the uploaded file
                file_path = f"uploads/{file.filename}"
                with open(file_path, "wb") as f:
                    content = await file.read()
                    f.write(content)

                # Process the file with user instruction
                reply = await self.chat_manager.process_file_with_instruction(
                    user_id, mode, file_path, "pdf", instruction
                )
                
                # Count tokens in the response
                reply_tokens = count_tokens(reply, api_key)
                total_tokens = instruction_tokens + reply_tokens
                
                # Update token usage
                if not add_tokens(user_id, api_key, instruction_tokens, reply_tokens):
                    return {
                        "status": "error", 
                        "message": "Token limit exceeded after processing."
                    }
                        
                # Clean up the uploaded file
                try:
                    os.remove(file_path)
                except:
                    pass
                    
                return {
                    "status": "success", 
                    "reply": reply,
                    "tokens_used": {
                        "instruction_tokens": instruction_tokens,
                        "reply_tokens": reply_tokens,
                        "total_tokens": total_tokens
                    }
                }

            except Exception as e:
                logger.error(f"[Upload] PDF error: {e}")
                return {"status": "error", "message": str(e)}

        # Add these upload routes to your main.py file (around line 200)

        @self.app.post("/upload/docx")
        async def upload_docx(request: Request, file: UploadFile = File(...)):
            try:
                # Get form data
                form_data = await request.form()
                user_id = form_data.get("user_id", "default_user")
                mode = form_data.get("mode", "friend")
                instruction = form_data.get("instruction", "")
                
                # Token limit check
                api_key = user_sessions.get(user_id, {}).get("api_key", "default_api_key")
                instruction_tokens = count_tokens(instruction, api_key) if instruction else 0
                
                if not check_user_limit(user_id, instruction_tokens):
                    return {
                        "status": "error", 
                        "message": f"Daily token limit of {DEFAULT_DAILY_TOKEN_LIMIT} exceeded."
                    }
                
                # Save the uploaded file
                file_path = f"uploads/{file.filename}"
                with open(file_path, "wb") as f:
                    content = await file.read()
                    f.write(content)

                # Process the file with user instruction
                reply = await self.chat_manager.process_file_with_instruction(
                    user_id, mode, file_path, "docx", instruction
                )
                
                # Count tokens in the response
                reply_tokens = count_tokens(reply, api_key)
                total_tokens = instruction_tokens + reply_tokens
                
                # Update token usage
                if not add_tokens(user_id, api_key, instruction_tokens, reply_tokens):
                    return {
                        "status": "error", 
                        "message": "Token limit exceeded after processing."
                    }
                
                # Clean up the uploaded file
                try:
                    os.remove(file_path)
                except:
                    pass
                    
                return {
                    "status": "success", 
                    "reply": reply,
                    "tokens_used": {
                        "instruction_tokens": instruction_tokens,
                        "reply_tokens": reply_tokens,
                        "total_tokens": total_tokens
                    }
                }

            except Exception as e:
                logger.error(f"[Upload] DOCX error: {e}")
                return {"status": "error", "message": str(e)}
            
        # Download endpoint
        @app.get("/download/{filename}")
        async def download_pdf(filename: str):
            file_path = os.path.join("generated_media", filename)
            
            # Check if file exists
            if os.path.exists(file_path):
                return FileResponse(
                    path=file_path,
                    filename=filename,
                    media_type="application/pdf"
                )
            else:
                return {"error": "File not found"}


        @self.app.post("/upload/excel")
        async def upload_excel(request: Request, file: UploadFile = File(...)):
            try:
                # Get form data
                form_data = await request.form()
                user_id = form_data.get("user_id", "default_user")
                mode = form_data.get("mode", "friend")
                instruction = form_data.get("instruction", "")
                
                # Token limit check
                api_key = user_sessions.get(user_id, {}).get("api_key", "default_api_key")
                instruction_tokens = count_tokens(instruction, api_key) if instruction else 0
                
                if not check_user_limit(user_id, instruction_tokens):
                    return {
                        "status": "error", 
                        "message": f"Daily token limit of {DEFAULT_DAILY_TOKEN_LIMIT} exceeded."
                    }
                
                # Save the uploaded file
                file_path = f"uploads/{file.filename}"
                with open(file_path, "wb") as f:
                    content = await file.read()
                    f.write(content)

                # Process the file with user instruction
                reply = await self.chat_manager.process_file_with_instruction(
                    user_id, mode, file_path, "excel", instruction
                )
                
                # Count tokens in the response
                reply_tokens = count_tokens(reply, api_key)
                total_tokens = instruction_tokens + reply_tokens
                
                # Update token usage
                if not add_tokens(user_id, api_key, instruction_tokens, reply_tokens):
                    return {
                        "status": "error", 
                        "message": "Token limit exceeded after processing."
                    }
                
                # Clean up the uploaded file
                try:
                    os.remove(file_path)
                except:
                    pass
                    
                return {
                    "status": "success", 
                    "reply": reply,
                    "tokens_used": {
                        "instruction_tokens": instruction_tokens,
                        "reply_tokens": reply_tokens,
                        "total_tokens": total_tokens
                    }
                }

            except Exception as e:
                logger.error(f"[Upload] Excel error: {e}")
                return {"status": "error", "message": str(e)}

        @self.app.post("/upload/image") 
        async def upload_image(request: Request, file: UploadFile = File(...)):
            try:
                # Get form data
                form_data = await request.form()
                user_id = form_data.get("user_id", "default_user")
                mode = form_data.get("mode", "friend")
                instruction = form_data.get("instruction", "")
                
                # Token limit check
                api_key = user_sessions.get(user_id, {}).get("api_key", "default_api_key")
                instruction_tokens = count_tokens(instruction, api_key) if instruction else 0
                
                if not check_user_limit(user_id, instruction_tokens):
                    return {
                        "status": "error", 
                        "message": f"Daily token limit of {DEFAULT_DAILY_TOKEN_LIMIT} exceeded."
                    }
                
                # Save the uploaded file
                file_path = f"uploads/{file.filename}"
                with open(file_path, "wb") as f:
                    content = await file.read()
                    f.write(content)

                # This will automatically use LLaMA 4 Maverick for images
                reply = await self.chat_manager.process_file_with_instruction(
                    user_id, mode, file_path, "image", instruction
                )
                
                # Count tokens in the response
                reply_tokens = count_tokens(reply, api_key)
                total_tokens = instruction_tokens + reply_tokens
                
                # Update token usage
                if not add_tokens(user_id, api_key, instruction_tokens, reply_tokens):
                    return {
                        "status": "error", 
                        "message": "Token limit exceeded after processing."
                    }
                
                # Add model information to the response
                # reply_with_model_info = f"{reply}\n\n*Processed with LLaMA 4 Maverick (Multimodal)*"
                reply_with_model_info = f"{reply}"
                
                # Clean up the uploaded file
                try:
                    os.remove(file_path)
                except:
                    pass
                    
                return {
                    "status": "success", 
                    "reply": reply_with_model_info,
                    "tokens_used": {
                        "instruction_tokens": instruction_tokens,
                        "reply_tokens": reply_tokens,
                        "total_tokens": total_tokens
                    }
                }

            except Exception as e:
                logger.error(f"[Upload] Image error: {e}")
                return {"status": "error", "message": str(e)}


        @self.app.post("/upload/audio")
        async def upload_audio(request: Request, file: UploadFile = File(...)):
            try:
                # Get form data
                form_data = await request.form()
                user_id = form_data.get("user_id", "default_user")
                mode = form_data.get("mode", "friend")
                instruction = form_data.get("instruction", "")
                
                # Token limit check
                api_key = user_sessions.get(user_id, {}).get("api_key", "default_api_key")
                instruction_tokens = count_tokens(instruction, api_key) if instruction else 0
                
                if not check_user_limit(user_id, instruction_tokens):
                    return {
                        "status": "error", 
                        "message": f"Daily token limit of {DEFAULT_DAILY_TOKEN_LIMIT} exceeded."
                    }
                
                # Save the uploaded file
                file_path = f"uploads/{file.filename}"
                with open(file_path, "wb")  as f:
                    content = await file.read()
                    f.write(content)

                # Process the file with user instruction
                reply = await self.chat_manager.process_file_with_instruction(
                    user_id, mode, file_path, "audio", instruction
                )
                
                # Count tokens in the response
                reply_tokens = count_tokens(reply, api_key)
                total_tokens = instruction_tokens + reply_tokens
                
                # Update token usage
                if not add_tokens(user_id, api_key, instruction_tokens, reply_tokens):
                    return {
                        "status": "error", 
                        "message": "Token limit exceeded after processing."
                    }
                
                # Clean up the uploaded file
                try:
                    os.remove(file_path)
                except:
                    pass
                    
                return {
                    "status": "success", 
                    "reply": reply,
                    "tokens_used": {
                        "instruction_tokens": instruction_tokens,
                        "reply_tokens": reply_tokens,
                        "total_tokens": total_tokens
                    }
                }

            except Exception as e:
                logger.error(f"[Upload] Audio error: {e}")
                return {"status": "error", "message": str(e)}
        
        # Serve main chat interface
        @self.app.get("/", response_class=HTMLResponse)
        @self.app.get("/chat", response_class=HTMLResponse)
        async def chat_page():
            try:
                with open("frontend/index.html", "r", encoding="utf-8") as f:
                    return f.read()
            except FileNotFoundError:
                return HTMLResponse("<h1>Chat interface not found</h1>", status_code=404)

        # Health check endpoint
        @self.app.get("/health")
        async def health_check():
            return {
                "status": "healthy",
                "service": "INAI WebRTC Chatbot",
                "version": "2.0.0",
                "active_connections": len(self.active_pcs),
                "maintenance_mode": self.config.is_maintenance_on(),
                "available_voices": list(self.config.voices.keys())
            }
        
        @self.app.get("/status")
        async def get_status():
            self.config.reload_env()
            return {
                "maintenance": self.config.is_maintenance_on(),
                "socket": self.config.is_socket_on() if hasattr(self.config, 'is_socket_on') else True
            }

        # Get available voice models
        # @self.app.get("/voices")
        # async def get_available_voices():
        #     return {
        #         "voices": self.config.voices,
        #         "default_voice": "female1"
        #     }
        @self.app.get("/voices")
        async def get_available_voices():
            voices = getattr(self.config, 'voices', {
                "female1": "en-IN-NeerjaExpressiveNeural",
                "female2": "en-US-JennyNeural", 
                "male": "en-IN-PrabhatNeural"
            })
            return {
                "voices": voices,
                "default_voice": "female1"
            }
            
        @self.app.get("/INAI520", response_class=HTMLResponse)
        async def admin_panel(request: Request):
            return self.templates.TemplateResponse("login.html", {"request": request, "error": None})

        @self.app.post("/INAI520", response_class=RedirectResponse)
        async def verify_admin(req: Request):
            form = await req.form()
            password = form.get("password")

            if password == os.getenv("TOGGLE_PASSWORD"):
                session_id = str(uuid.uuid4())
                user_sessions[session_id] = {
                    "expires_at": datetime.utcnow() + timedelta(minutes=30)
                }
                response = RedirectResponse(url="/INAI520/home", status_code=303)
                # Set HttpOnly cookie
                response.set_cookie(
                    key="session_id",
                    value=session_id,
                    httponly=True,
                    max_age=1800  # 30 minutes
                )
                return response
            return self.templates(directory="templates").TemplateResponse(
                "login.html", {"request": req, "error": "Invalid password"}
            )

        @self.app.get("/INAI520/home", response_class=HTMLResponse)
        async def admin_home(request: Request):
            return self.templates.TemplateResponse("admin_panel.html", {"request": request})

        @self.app.get("/INAI520/maintenance", response_class=HTMLResponse)
        async def admin_maintenance(request: Request):
            return self.templates.TemplateResponse("maintenance.html", {
                "request": request,
                "socket": self.config.is_socket_on() if hasattr(self.config, 'is_socket_on') else True,
                "maintenance": self.config.is_maintenance_on(),
            })

        # Monitor endpoints (from old main.py)
        @self.app.get("/INAI520/monitor", response_class=HTMLResponse)
        async def monitor_ui(request: Request):
            data = get_monitor_data()
            request.state.timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            return self.templates.TemplateResponse("monitor.html", {
                "request": request,
                "user_sessions": data.get("user_sessions", {}),
                "key_usage": data.get("key_usage", {}),
                "token_usage_per_user": data.get("token_usage_per_user", {}),
                "api_key_token_usage": data.get("api_key_token_usage", {}),
                # "exhausted_users": data.get("exhausted_users", {}),
                "webrtc_stats": await self.webrtc_handler.get_all_connection_stats()
            })

        @self.app.get("/INAI520/monitor/api_key_usage", response_class=HTMLResponse)
        async def monitor_api_keys(request: Request):
            data = get_monitor_data()
            csv_latest = get_usage_logs()

            # Update API key usage from CSV data
            for api_key, row in csv_latest.get("api_keys", {}).items(): 
                data["api_key_token_usage"][api_key] = int(row.get("API Key Total Tokens Used", 0))

            request.state.timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            
            return self.templates.TemplateResponse("api_key_usage.html", {
                "request": request,
                "key_usage": data["key_usage"],
                "api_key_token_usage": data["api_key_token_usage"]
            })

        @self.app.get("/INAI520/monitor/user_sessions", response_class=HTMLResponse)
        async def monitor_user_sessions(request: Request):
            data = get_monitor_data()
            # Add WebRTC connection info to user sessions
            webrtc_stats = await self.webrtc_handler.get_all_connection_stats()
            
            return self.templates.TemplateResponse("sessions.html", {
                "request": request,
                "user_sessions": data["user_sessions"],
                "webrtc_connections": webrtc_stats.get("users", {})
            })

        @self.app.get("/INAI520/monitor/token_usage", response_class=HTMLResponse)
        async def monitor_token_usage(request: Request):
            data = get_monitor_data()
            csv_latest = get_usage_logs()
            
            # Update user token usage from CSV data
            for user_id, row in csv_latest.get("user_ids", {}).items():
                data["token_usage_per_user"][user_id] = int(row.get("Total Tokens", 0))

            request.state.timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                   
            return self.templates.TemplateResponse("tokens.html", {
                "request": request,
                "token_usage_per_user": data["token_usage_per_user"]
            })
        
        # @self.app.get("/INAI520/monitor/subscriptions", response_class=HTMLResponse)
        # async def monitor_subscriptions(request: Request, db: Session = Depends(get_db)):
        #     subscriptions = db.query(Subscription).all()
        #     request.state.timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        #     return self.templates.TemplateResponse("subscriptions.html", {
        #         "request": request,
        #         "subscriptions": subscriptions
        #     })
        
        @self.app.get("/download/{file_name}")
        async def download_file(file_name: str, view: str = Query(None)):
            """Serve generated PDFs for download or viewing"""
            try:
                file_path = os.path.join("generated_media", file_name)
                if not os.path.exists(file_path):
                    self.logger.error(f"File not found: {file_path}")
                    raise HTTPException(status_code=404, detail="File not found")

                # Security check - avoid directory traversal
                real_path = os.path.realpath(file_path)
                allowed_dir = os.path.realpath("generated_media")
                if not real_path.startswith(allowed_dir):
                    self.logger.error(f"Access denied for path: {real_path}")
                    raise HTTPException(status_code=403, detail="Access denied")

                # Determine MIME type
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                    
                # For PDFs, set appropriate content type
                if file_path.lower().endswith('.pdf'):
                    mime_type = "application/pdf"

                # If view parameter is present, display in browser; otherwise download
                if view:
                    # For viewing in browser
                    return FileResponse(
                        path=file_path,
                        media_type=mime_type,
                        headers={
                            "Content-Disposition": f"inline; filename={file_name}",
                            "Cache-Control": "no-cache"
                        }
                    )
                else:
                    # For download
                    return FileResponse(
                        path=file_path,
                        filename=file_name,
                        media_type=mime_type,
                        headers={
                            "Content-Disposition": f"attachment; filename={file_name}",
                            "Cache-Control": "no-cache"
                        }
                    )
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Error serving file {file_name}: {e}")
                raise HTTPException(status_code=500, detail="Failed to serve file")
            
            # Dedicated view route (alternative approach)
        @self.app.get("/view/{file_name}")
        async def view_file(file_name: str):
            """View PDFs and other files in browser"""
            try:
                file_path = os.path.join("generated_media", file_name)
                if not os.path.exists(file_path):
                    raise HTTPException(status_code=404, detail="File not found")

                # Security check
                real_path = os.path.realpath(file_path)
                allowed_dir = os.path.realpath("generated_media")
                if not real_path.startswith(allowed_dir):
                    raise HTTPException(status_code=403, detail="Access denied")

                # Determine MIME type
                mime_type, _ = mimetypes.guess_type(file_path)
                if file_path.lower().endswith('.pdf'):
                    mime_type = "application/pdf"
                elif mime_type is None:
                    mime_type = "application/octet-stream"

                return FileResponse(
                    path=file_path,
                    media_type=mime_type,
                    headers={
                        "Content-Disposition": f"inline; filename={file_name}",
                        "Cache-Control": "public, max-age=3600"  # Cache for 1 hour
                    }
                )
                
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Error viewing file {file_name}: {e}")
                raise HTTPException(status_code=500, detail="Failed to view file")
            
            # List available generated files for a user
        @self.app.get("/generated")
        async def list_generated_files(user_id: str = Query(None)):
            """List all available generated files, optionally filtered by user"""
            try:
                files = []
                media_dir = Path("generated_media")
                
                if media_dir.exists():
                    for file_path in media_dir.glob("*"):
                        if file_path.is_file():
                            # Filter by user if specified
                            if user_id and not file_path.name.startswith(f"report_{user_id}_") and not file_path.name.startswith(f"code_{user_id}_"):
                                continue
                                
                            stat = file_path.stat()
                            files.append({
                                "filename": file_path.name,
                                "size": stat.st_size,
                                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                "type": self._get_file_type(file_path),
                                "download_url": f"/download/{file_path.name}",
                                "view_url": f"/view/{file_path.name}"
                            })
                
                return {"files": sorted(files, key=lambda x: x["created"], reverse=True)}
                
            except Exception as e:
                self.logger.error(f"Error listing generated files: {e}")
                return {"files": [], "error": str(e)}

        # Enhanced file serving for all media types
        @self.app.get("/generated/{filename}")
        async def serve_generated_file(filename: str):
            """Serve generated images, PDFs, and other media files"""
            try:
                file_path = os.path.join("generated_media", filename)
                
                if not os.path.exists(file_path):
                    raise HTTPException(status_code=404, detail="File not found")
                
                # Security check - ensure file is in generated_media directory
                real_path = os.path.realpath(file_path)
                allowed_dir = os.path.realpath("generated_media")
                
                if not real_path.startswith(allowed_dir):
                    raise HTTPException(status_code=403, detail="Access denied")
                
                # Determine media type
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                
                return FileResponse(
                    path=file_path,
                    media_type=mime_type,
                    filename=filename,
                    headers={
                        "Cache-Control": "public, max-age=3600"
                    }
                )
                
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Error serving file {filename}: {e}")
                raise HTTPException(status_code=500, detail="Failed to serve file")

        # Cleanup old generated files (admin endpoint)
        @self.app.delete("/generated/cleanup")
        async def cleanup_old_files(max_age_hours: int = Query(24, description="Maximum age in hours")):
            """Clean up generated files older than specified hours"""
            try:
                removed_files = []
                media_dir = Path("generated_media")
                cutoff_time = datetime.now().timestamp() - (max_age_hours * 3600)
                
                if media_dir.exists():
                    for file_path in media_dir.glob("*"):
                        if file_path.is_file() and file_path.stat().st_ctime < cutoff_time:
                            try:
                                file_path.unlink()
                                removed_files.append(file_path.name)
                            except Exception as e:
                                self.logger.error(f"Failed to remove {file_path}: {e}")
                
                return {
                    "status": "success",
                    "removed_files": removed_files,
                    "count": len(removed_files),
                    "max_age_hours": max_age_hours
                }
                
            except Exception as e:
                self.logger.error(f"Error cleaning up files: {e}")
                return {"status": "error", "message": str(e)}

        # File info endpoint
        @self.app.get("/file-info/{filename}")
        async def get_file_info(filename: str):
            """Get detailed information about a specific file"""
            try:
                file_path = os.path.join("generated_media", filename)
                
                if not os.path.exists(file_path):
                    raise HTTPException(status_code=404, detail="File not found")
                
                # Security check
                real_path = os.path.realpath(file_path)
                allowed_dir = os.path.realpath("generated_media")
                if not real_path.startswith(allowed_dir):
                    raise HTTPException(status_code=403, detail="Access denied")
                
                stat = os.stat(file_path)
                mime_type, _ = mimetypes.guess_type(file_path)
                
                return {
                    "filename": filename,
                    "size": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "mime_type": mime_type,
                    "file_type": self._get_file_type(Path(file_path)),
                    "download_url": f"/download/{filename}",
                    "view_url": f"/view/{filename}",
                    "direct_url": f"/generated/{filename}"
                }
                
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Error getting file info for {filename}: {e}")
                raise HTTPException(status_code=500, detail="Failed to get file info")
            


        @self.app.get("/INAI520", response_class=HTMLResponse)
        async def admin_panel(request: Request):
            return self.templates.TemplateResponse("login.html", {"request": request, "error": None})

        @self.app.post("/INAI520", response_class=RedirectResponse)
        async def verify_admin(req: Request):
            form = await req.form()
            password = form.get("password")

            if password == os.getenv("TOGGLE_PASSWORD"):
                session_id = str(uuid.uuid4())
                user_sessions[session_id] = {
                    "expires_at": datetime.utcnow() + timedelta(minutes=30)
                }
                response = RedirectResponse(url="/INAI520/home", status_code=303)
                # Set HttpOnly cookie
                response.set_cookie(
                    key="session_id",
                    value=session_id,
                    httponly=True,
                    max_age=1800  # 30 minutes
                )
                return response
            return self.templates(directory="templates").TemplateResponse(
                "login.html", {"request": req, "error": "Invalid password"}
            )

        @self.app.get("/INAI520/home", response_class=HTMLResponse)
        async def admin_home(request: Request):
            return self.templates.TemplateResponse("admin_panel.html", {"request": request})

        @self.app.get("/INAI520/maintenance", response_class=HTMLResponse)
        async def admin_maintenance(request: Request):
            return self.templates.TemplateResponse("maintenance.html", {
                "request": request,
                "socket": self.config.is_socket_on() if hasattr(self.config, 'is_socket_on') else True,
                "maintenance": self.config.is_maintenance_on(),
            })

        # Monitor endpoints (from old main.py)
        @self.app.get("/INAI520/monitor", response_class=HTMLResponse)
        async def monitor_ui(request: Request):
            data = get_monitor_data()
            request.state.timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            return self.templates.TemplateResponse("monitor.html", {
                "request": request,
                "user_sessions": data.get("user_sessions", {}),
                "key_usage": data.get("key_usage", {}),
                "token_usage_per_user": data.get("token_usage_per_user", {}),
                "api_key_token_usage": data.get("api_key_token_usage", {}),
                "exhausted_users": data.get("exhausted_users", {}),
                "webrtc_stats": await self.webrtc_handler.get_all_connection_stats()
            })

        @self.app.get("/INAI520/monitor/api_key_usage", response_class=HTMLResponse)
        async def monitor_api_keys(request: Request):
            data = get_monitor_data()
            csv_latest = get_usage_logs()

            # Update API key usage from CSV data
            for api_key, row in csv_latest.get("api_keys", {}).items(): 
                data["api_key_token_usage"][api_key] = int(row.get("API Key Total Tokens Used", 0))

            request.state.timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            
            return self.templates.TemplateResponse("api_key_usage.html", {
                "request": request,
                "key_usage": data["key_usage"],
                "api_key_token_usage": data["api_key_token_usage"]
            })

        @self.app.get("/INAI520/monitor/user_sessions", response_class=HTMLResponse)
        async def monitor_user_sessions(request: Request):
            data = get_monitor_data()
            # Add WebRTC connection info to user sessions
            webrtc_stats = await self.webrtc_handler.get_all_connection_stats()
            
            return self.templates.TemplateResponse("sessions.html", {
                "request": request,
                "user_sessions": data["user_sessions"],
                "webrtc_connections": webrtc_stats.get("users", {})
            })

        @self.app.get("/INAI520/monitor/token_usage", response_class=HTMLResponse)
        async def monitor_token_usage(request: Request):
            data = get_monitor_data()
            csv_latest = get_usage_logs()
            
            # Update user token usage from CSV data
            for user_id, row in csv_latest.get("user_ids", {}).items():
                data["token_usage_per_user"][user_id] = int(row.get("Total Tokens", 0))

            request.state.timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                   
            return self.templates.TemplateResponse("tokens.html", {
                "request": request,
                "token_usage_per_user": data["token_usage_per_user"]
            })

        @self.app.get("/INAI520/monitor/exhausted_users", response_class=HTMLResponse)
        async def monitor_exhausted_users(request: Request):
            data = get_monitor_data()
            return self.templates.TemplateResponse("exhausted_users.html", {
                "request": request,
                "exhausted_users": data.get("exhausted_users", [])
            })

        # WebRTC-specific monitoring endpoint
        @self.app.get("/INAI520/monitor/webrtc", response_class=HTMLResponse)
        async def monitor_webrtc_connections(request: Request):
            webrtc_stats = await self.webrtc_handler.get_all_connection_stats()
            request.state.timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            
            return self.templates.TemplateResponse("webrtc_monitor.html", {
                "request": request,
                "webrtc_stats": webrtc_stats,
                "total_connections": webrtc_stats.get("total_webrtc_connections", 0),
                "active_channels": webrtc_stats.get("active_data_channels", 0),
                "streaming_users": webrtc_stats.get("streaming_users", 0)
            })

        # Toggle maintenance mode (from old main.py)
        @self.app.post("/toggle")
        async def toggle(request: ToggleRequest):
            if not self.config.toggle_state(request.password):
                raise HTTPException(status_code=403, detail="Invalid password")
            self.logger.info("Maintenance toggle triggered")
            
            # Disconnect all WebRTC users when entering maintenance
            await self.webrtc_handler.cleanup_all_connections()
            
            mode = "MAINTENANCE" if self.config.is_maintenance_on() else "NORMAL"
            return {
                "message": f"Mode switched to {mode}",
                "maintenance": self.config.is_maintenance_on(),
                "socket": self.config.is_socket_on() if hasattr(self.config, 'is_socket_on') else True
            }

        @self.app.post("/login")
        async def login(req: ToggleRequest):
            if req.password != os.getenv("TOGGLE_PASSWORD"):
                raise HTTPException(status_code=403, detail="Invalid password")
            return {
                "maintenance": self.config.is_maintenance_on(),
                "socket": self.config.is_socket_on() if hasattr(self.config, 'is_socket_on') else True
            }

        # Key management endpoints (from old main.py)
        @self.app.post("/assign-key")
        async def assign_key(request: Request):
            data = await request.json()
            user_id = data.get("user_id")
            task = data.get("task", "Unknown")
            return assign_key_to_user(user_id, task)

        @self.app.post("/release-key")
        async def release_key(request: Request):
            data = await request.json()
            user_id = data.get("user_id")
            return release_key_for_user(user_id)
        

        # WebRTC offer handling
        @self.app.post("/webrtc/offer")
        async def handle_offer(req: OfferRequest):
            try:
                user_id = req.user_id.replace(" ", "_").lower()
                logger.info(f"[WebRTC] Handling offer from user: {user_id}")
                
                pc = RTCPeerConnection()
                self.active_pcs[user_id] = pc
                assign_key_to_user(user_id, task="WebRTC Offer")
                update_last_active(user_id)

                # Setup data channel handler
                @pc.on("datachannel")
                def on_datachannel(channel):
                    # logger.info(f"[WebRTC] Data channel opened for user: {user_id}")
                    
                    # Store data channel in webrtc_handler
                    self.webrtc_handler.data_channels[user_id] = channel
                    
                    @channel.on("message")
                    async def on_message(message):
                        await self._handle_datachannel_message(user_id, channel, message)

                # Setup connection state monitoring
                @pc.on("connectionstatechange")
                async def on_state_change():
                    logger.info(f"[WebRTC] {user_id} connection state: {pc.connectionState}")
                    
                    if pc.connectionState in ["failed", "closed"]:
                        await self._cleanup_user_connection(user_id)
                    elif pc.connectionState == "connected":
                        logger.info(f"[WebRTC] {user_id} successfully connected")

                # Handle the WebRTC offer
                offer = RTCSessionDescription(sdp=req.sdp, type=req.type)
                await pc.setRemoteDescription(offer)
                
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                
                logger.info(f"[WebRTC] Answer ready for user: {user_id}")
                
                return {
                    "sdp": pc.localDescription.sdp, 
                    "type": pc.localDescription.type,
                    "status": "success"
                }
                
            except Exception as e:
                logger.error(f"[WebRTC] Offer handling error: {e}")
                raise HTTPException(status_code=500, detail=f"WebRTC offer error: {str(e)}")

        # ICE candidate handling
        @self.app.post("/webrtc/candidate")
        async def add_candidate(req: CandidateRequest):
            try:
                user_id = req.user_id.replace(" ", "_").lower()
                
                
                if user_id in self.active_pcs:
                    pc = self.active_pcs[user_id]

                    # ✅ Direct dict pass — aiortc will parse internally
                    await pc.addIceCandidate(req.candidate.dict())
                    
                     # Convert the Pydantic model to a dict for aiortc
                    from aiortc import RTCIceCandidate
                    candidate = {
                        "candidate": req.candidate.candidate,
                        "sdpMid": req.candidate.sdpMid,
                        "sdpMLineIndex": req.candidate.sdpMLineIndex
                    }
                    await pc.addIceCandidate(candidate)

                    logger.info(f"[WebRTC] Candidate added for user: {user_id}")
                    return {"status": "success"}
                else:
                    logger.warning(f"[WebRTC] No peer connection found for user: {user_id}")
                    return {"status": "no_connection"}       
            except Exception as e:
                logger.error(f"[WebRTC] ICE candidate error: {e}")
                raise HTTPException(status_code=500, detail=f"ICE candidate error: {str(e)}")

        # HTTP text message endpoint with streaming support
        @self.app.post("/webrtc/text")
        async def send_text_message(req: TextMessageRequest):
            
            try:
                user_id = req.user_id.replace(" ", "_").lower()
                api_key = user_sessions[user_id]["api_key"] if user_id in user_sessions else "default_api_key"
                question_tokens = count_tokens(req.text, api_key) 
                
                if not check_user_limit(user_id, question_tokens):
                    return {
                        "status": "error",
                        "message": f"Daily token limit of {DEFAULT_DAILY_TOKEN_LIMIT} exceeded."
                    }
                       
                if req.stream and user_id in self.webrtc_handler.data_channels:
                    # Use streaming via WebRTC with voice model
                    await self.webrtc_handler.handle_text_message_streaming(
                        user_id, req.mode, req.text, req.voice_model
                    )
                    return {
                        "status": "streaming", 
                        "message": "Response streaming via WebRTC",
                        "method": "webrtc_datachannel",
                        "voice_model": req.voice_model
                    }
                else:
                    # Fallback to traditional HTTP response
                    result = await self.webrtc_handler.handle_text_message(
                        user_id, req.mode, req.text, req.voice_model
                    )
                    
                    answer_tokens = count_tokens(result, api_key)
                    
                    add_tokens(user_id, result["api_key"], question_tokens, answer_tokens)
                    
                    result["method"] = "http_fallback"
                    return result
                    
            except Exception as e:
                logger.error(f"[WebRTC] Text message error: {e}")
                return {
                    "text": "⚠ An error occurred while processing your message.",
                    "audio": "",
                    "error": str(e)
                }

        # HTTP audio message endpoint
        @self.app.post("/webrtc/audio")
        async def send_audio_message(req: AudioMessageRequest):
            try:
                user_id = req.user_id.replace(" ", "_").lower()
                
                result = await self.webrtc_handler.handle_audio_message(
                    user_id, req.mode, req.audio, req.voice_model
                )
                return result
                
            except Exception as e:
                logger.error(f"[WebRTC] Audio message error: {e}")
                return {
                    "text": "⚠ An error occurred while processing your audio.",
                    "audio": "",
                    "error": str(e)
                }

        # Enhanced streaming endpoint
        @self.app.post("/webrtc/stream")
        async def send_streaming_message(req: StreamingMessageRequest):
            try:
                user_id = req.user_id.replace(" ", "_").lower()
                
                if user_id in self.webrtc_handler.data_channels:
                    await self.webrtc_handler.handle_text_message_streaming(
                        user_id, req.mode, req.text, req.voice_model
                    )
                    return {
                        "status": "streaming", 
                        "message": "Response streaming via WebRTC",
                        "voice_model": req.voice_model
                    }
                else:
                    return {
                        "status": "error", 
                        "message": "WebRTC data channel not available"
                    }
                    
            except Exception as e:
                logger.error(f"[WebRTC] Streaming message error: {e}")
                return {
                    "status": "error", 
                    "message": f"Streaming error: {str(e)}"
                }

        # Get connection and streaming status
        @self.app.get("/webrtc/status/{user_id}")
        async def get_streaming_status(user_id: str):
            try:
                status = await self.webrtc_handler.get_connection_status(user_id)
                return status
                
            except Exception as e:
                logger.error(f"[WebRTC] Status check error: {e}")
                return {
                    "user_id": user_id,
                    "error": str(e),
                    "streaming_supported": False
                }

        # List all active connections (admin endpoint)
        @self.app.get("/webrtc/connections")
        async def list_active_connections():
            try:
                connections = {}
                
                for user_id in self.active_pcs:
                    connections[user_id] = await self.webrtc_handler.get_connection_status(user_id)
                    
                return {
                    "total_connections": len(connections),
                    "connections": connections
                }
                
            except Exception as e:
                logger.error(f"[WebRTC] Connections list error: {e}")
                return {"error": str(e)}

        # Cleanup specific user connection
        @self.app.delete("/webrtc/connection/{user_id}")
        async def cleanup_user_connection(user_id: str):
            try:
                user_id = user_id.replace(" ", "_").lower()
                await self._cleanup_user_connection(user_id)
                return {"status": "cleaned_up", "user_id": user_id}
                
            except Exception as e:
                logger.error(f"[WebRTC] User cleanup error: {e}")
                return {"error": str(e)}
            
    # -----------------------
    # Data Channel Message Handler
    # -----------------------
    async def _handle_datachannel_message(self, user_id: str, channel, message: str):
        """Handle incoming data channel messages"""
        try:
            msg_data = json.loads(message)
            text = msg_data.get("text", "")
            mode = msg_data.get("mode", "friend")
            voice_model = msg_data.get("voice_model", "female1")  # Added voice model support
            stream_enabled = msg_data.get("stream", True)
            
            logger.info(f"[DataChannel] {user_id} sent: {text[:50]}... (voice: {voice_model})")
            
            api_key = user_sessions[user_id]["api_key"] if user_id in user_sessions else "default_api_key"
            question_tokens = count_tokens(text, api_key)

            if not check_user_limit(user_id, question_tokens):
                channel.send(json.dumps({
                    "status": "error",
                    "message": f"Daily token limit of {DEFAULT_DAILY_TOKEN_LIMIT} exceeded."
                }))
                return
            
            if stream_enabled:
                # Use streaming handler with voice model
                await self.webrtc_handler.handle_text_message_streaming(user_id, mode, text, voice_model)
            else:
                # Use traditional handler and send response back
                response = await self.webrtc_handler.handle_text_message(user_id, mode, text, voice_model)
                answer_tokens = count_tokens(response, api_key)

                add_tokens(user_id, response["api_key"], question_tokens, answer_tokens)
                
                if response.get("status") != "streaming":
                    try:
                        channel.send(json.dumps(response))
                    except Exception as e:
                        logger.error(f"[DataChannel] Failed to send response to {user_id}: {e}")
                        
        except json.JSONDecodeError as e:
            logger.error(f"[DataChannel] Invalid JSON from {user_id}: {e}")
            error_response = {
                "type": "error",
                "data": {"message": "Invalid message format", "error": "JSON decode error"}
            }
            try:
                channel.send(json.dumps(error_response))
            except:
                pass
                
        except Exception as e:
            logger.error(f"[DataChannel] Message handling error for {user_id}: {e}")
            error_response = {
                "type": "error",
                "data": {"message": "Failed to process message", "error": str(e)}
            }
            try:
                channel.send(json.dumps(error_response))
            except:
                pass

    # -----------------------
    # Connection Management
    # -----------------------
    async def _cleanup_user_connection(self, user_id: str):
        """Clean up user's WebRTC connection and associated resources"""
        try:
            # Close peer connection
            if user_id in self.active_pcs:
                pc = self.active_pcs.pop(user_id)
                await pc.close()
            
            # Clean up in webrtc handler
            await self.webrtc_handler.cleanup_user(user_id)
            
            logger.info(f"[WebRTC] User {user_id} connection cleaned up successfully")
            
        except Exception as e:
            logger.error(f"[WebRTC] Error cleaning up user {user_id}: {e}")

    async def cleanup_all_connections(self):
        """Clean up all active WebRTC connections"""
        try:
            users_to_cleanup = list(self.active_pcs.keys())
            
            for user_id in users_to_cleanup:
                await self._cleanup_user_connection(user_id)
            
            # Clean up webrtc handler
            await self.webrtc_handler.cleanup_all_connections()
            
            logger.info("[WebRTC] All connections cleaned up")
            
        except Exception as e:
            logger.error(f"[WebRTC] Error during cleanup: {e}")

# -----------------------
# Application Lifecycle Events
# -----------------------
@app.on_event("startup")
async def startup():
    """Initialize the application on startup"""
    try:
        logger.info("🚀 Starting INAI WebRTC Chatbot...")
        
        # Environment variables
        db_url = os.getenv("DATABASE_URL")
        bucket_name = os.getenv("AWS_BUCKET_NAME")
        aws_key = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
        region = os.getenv("AWS_REGION")

        # Initialize history manager
        app.state.history_manager = HistoryManager(
            db_url=db_url,
            bucket_name=bucket_name,
            aws_access_key=aws_key,
            aws_secret_key=aws_secret,
            region=region,
            logger=logger
        )
        
        await app.state.history_manager.init_db()
        
        # Initialize main INAI application
        app.state.inai_app = INAIApplication(app.state.history_manager)
        
        logger.info("✅ INAI WebRTC Chatbot started successfully")
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise

@app.on_event("shutdown")
async def shutdown():
    """Clean up resources on shutdown"""
    try:
        logger.info("🔄 Shutting down INAI WebRTC Chatbot...")
        
        # Clean up all active WebRTC connections
        if hasattr(app.state, 'inai_app'):
            await app.state.inai_app.cleanup_all_connections()
        
        # Close database connections if needed
        if hasattr(app.state, 'history_manager'):
            # Add any cleanup needed for history manager
            pass
            
        logger.info("✅ INAI WebRTC Chatbot shut down successfully")
        
    except Exception as e:
        logger.error(f"❌ Shutdown error: {e}")

# -----------------------
# Error Handlers
# (Your global catch-all remains; metrics handlers are registered above)
# -----------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors"""
    logger.error(f"Unhandled exception: {exc}")
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": "An unexpected error occurred",
            "type": type(exc).__name__
        }
    )

# -----------------------
# Development/Debug Routes
# -----------------------
if os.getenv("ENVIRONMENT") == "development":
    
    @app.get("/debug/config")
    async def debug_config():
        """Debug endpoint to check configuration"""
        if hasattr(app.state, 'inai_app'):
            config = app.state.inai_app.config
            return {
                "mode": config.mode,
                "voices": config.voices,
                "maintenance": config.is_maintenance_on(),
                "api_keys_count": len(config.api_keys)
            }
        return {"error": "App not initialized"}
    
    @app.get("/debug/tts/test/{text}")
    async def debug_tts(text: str, voice_model: str = "female1"):
        """Debug endpoint to test TTS generation"""
        if hasattr(app.state, 'inai_app'):
            try:
                tts = app.state.inai_app.tts
                config = app.state.inai_app.config
                voice = config.get_voice_for_model(voice_model)
                audio_chunks = []
                
                async for chunk_data in tts.generate_tts_stream(text, "debug_user", voice):
                    if chunk_data["type"] == "audio":
                        audio_chunks.append(chunk_data["data"])
                    elif chunk_data["type"] == "complete":
                        break
                
                return {
                    "status": "success",
                    "text": text,
                    "voice_model": voice_model,
                    "voice_used": voice,
                    "audio_chunks": len(audio_chunks),
                    "total_audio_length": len("".join(audio_chunks)) if audio_chunks else 0
                }
                
            except Exception as e:
                return {"error": str(e)}
        
        return {"error": "App not initialized"}
    
    
def _get_file_type(self, file_path: Path) -> str:
    """Determine file type from extension"""
    suffix = file_path.suffix.lower()
    if suffix == '.pdf':
        return 'pdf'
    elif suffix in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
        return 'image'
    elif suffix in ['.mp3', '.wav', '.ogg', '.m4a']:
        return 'audio'
    elif suffix in ['.mp4', '.avi', '.mov', '.wmv']:
        return 'video'
    elif suffix in ['.txt', '.md', '.log']:
        return 'text'
    else:
        return 'unknown'

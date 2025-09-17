import asyncio
import json
import base64
import time
import tempfile
import os
import re
from datetime import datetime
from aiortc import RTCPeerConnection, RTCSessionDescription
from pathlib import Path
from ai_assistant.assistant import AIAssistant
from ai_assistant.tts_engine import TTSEngine

from .key_manager import (
    release_key_for_user,
    count_tokens,
    user_sessions,
    get_user_token_limit,
    move_to_exhausted,
    add_tokens,
    get_user_subscription_info,
    check_user_limit,
    update_csv_log,
    get_user_tokens,
    get_api_key_tokens,
    update_user_tokens,
    update_api_key_tokens,
    reset_user_tokens_if_new_day,
    reset_api_key_tokens_if_new_day,
    track_token_usage,  # Add this
    TokenSource,        # Add this
    TokenUsage,         # Add this
    DEFAULT_DAILY_TOKEN_LIMIT
)

today = datetime.now().strftime("%Y-%m-%d")
DEFAULT_API_KEY = "default_api_key"

class WebRTCHandler:
    def __init__(self, session_manager, config, tts, chat_manager, speech_recognition, history, modes, logger):
        self.session_manager = session_manager
        self.config = config
        self.tts = tts
        self.chat_manager = chat_manager
        self.speech_recognition = speech_recognition
        self.history = history
        self.modes = modes
        self.logger = logger
        self.pcs = {}  # Active peer connections
        self.data_channels = {}  # Data channels for streaming
        self.csv_save_path = os.path.join(os.path.dirname(__file__), "DataMonitor", "token_usage.csv")
        os.makedirs(os.path.dirname(self.csv_save_path), exist_ok=True)
        
        # TTS streaming configuration
        self.tts_chunk_size = 30  # Characters per TTS chunk (reduced for faster streaming)
        self.audio_buffer = {}  # Buffer for audio chunks per user
        self.streaming_states = {}  # Track streaming state per user
        self.active_tasks = {}  # user_id → task
        
        # AI Assistant components
        self.ai_assistant = AIAssistant()
        self.assistant_tts = TTSEngine()
        
        # NEW: Interrupt handling
        self.user_interrupts = {}  # Track interrupt flags per user
        self.stop_words = ["stop", "wait", "ruko", "arre", "sun", "bas", "band", "cancel"]

    # ------------------------
    # Small safe helpers
    # ------------------------
    def _safedict(self, maybe_dict):
        """Ensure we always return a dict, never None"""
        return maybe_dict if isinstance(maybe_dict, dict) else {}
    
    def _get_api_key_for_user(self, user_id: str) -> str:
        """Always return a usable API key string"""
        key = user_sessions.get(user_id, {}).get("api_key")
        if isinstance(key, str) and key.strip():
            return key
        return DEFAULT_API_KEY  # fallback string

    async def _notify_and_exhaust(self, user_id: str, reason: str = "limit"):
        """
        Notify the client over the datachannel that the user is exhausted,
        THEN mark exhausted and clean up. This order avoids 'channel is None' errors.
        """
        try:
            if user_id in self.data_channels:
                await self.send_streaming_chunk(user_id, "error", {
                    "type": "token_limit_exceeded",
                    "message": "Daily token limit exceeded. Try again tomorrow or upgrade."
                })
                await self.send_streaming_chunk(user_id, "final_response", {
                    "text": "⚠ You’ve reached your daily token limit.",
                    "audio": "",
                    "complete": True
                })
        except Exception as e:
            self.logger.error(f"[Token] Failed to notify {user_id} about exhaustion: {e}")

        try:
            move_to_exhausted(user_id)
        except Exception as e:
            self.logger.error(f"[Token] move_to_exhausted failed for {user_id}: {e}")

        try:
            await self.cleanup_user(user_id)
        except Exception as e:
            self.logger.error(f"[WebRTC] Cleanup after exhaust failed for {user_id}: {e}")

    # ------------------------
    # WebRTC signaling
    # ------------------------
    async def handle_offer(self, user_id, sdp, type_):
        user_id = user_id.replace(" ", "_").lower()
        pc = RTCPeerConnection()
        self.pcs[user_id] = pc

        @pc.on("datachannel")
        def on_datachannel(channel):
            self.logger.info(f"[WebRTC] Data channel opened for {user_id}")
            self.data_channels[user_id] = channel
            
            # Handle incoming messages for interrupts
            @channel.on("message")
            def on_message(message):
                try:
                    data = json.loads(message)
                    if data.get("type") == "cancel_stream":
                        self.logger.info(f"[Interrupt] Received cancel signal from {user_id}")
                        self.user_interrupts[user_id] = True
                        asyncio.create_task(self.handle_user_interrupt(user_id))
                except Exception as e:
                    self.logger.error(f"[WebRTC] Message handling error: {e}")

        @pc.on("connectionstatechange")
        async def on_state_change():
            self.logger.info(f"[WebRTC] {user_id} connection state: {pc.connectionState}")
            if pc.connectionState in ["failed", "closed"]:
                await self.cleanup_user(user_id)

        offer = RTCSessionDescription(sdp=sdp, type=type_)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    async def add_ice_candidate(self, user_id, candidate):
        if user_id in self.pcs:
            await self.pcs[user_id].addIceCandidate(candidate)

    async def cleanup_user(self, user_id):
        # Clear interrupt flags
        self.user_interrupts.pop(user_id, None)
        
        if user_id in self.pcs:
            try:
                await self.pcs[user_id].close()
            except Exception:
                pass
            self.pcs.pop(user_id, None)

        self.data_channels.pop(user_id, None)
        self.audio_buffer.pop(user_id, None)
        self.streaming_states.pop(user_id, None)

        try:
            release_key_for_user(user_id)
        except Exception as e:
            self.logger.error(f"[WebRTC] release_key_for_user error for {user_id}: {e}")

        try:
            self.session_manager.cleanup_user_session(user_id)
        except Exception as e:
            self.logger.error(f"[WebRTC] session_manager cleanup error for {user_id}: {e}")

        self.logger.info(f"[WebRTC] Cleaned up user: {user_id}")
        
    # ------------------------
    # NEW: Interrupt handling methods
    # ------------------------
    def is_user_interrupted(self, user_id: str) -> bool:
        """Check if user has sent interrupt signal"""
        return self.user_interrupts.get(user_id, False)
    
    def clear_user_interrupt(self, user_id: str):
        """Clear interrupt flag for user"""
        self.user_interrupts.pop(user_id, False)
    
    async def handle_user_interrupt(self, user_id: str):
        """Handle immediate interrupt from user"""
        self.logger.info(f"[Interrupt] Handling interrupt for {user_id}")
        
        # Cancel active tasks
        if user_id in self.active_tasks:
            task = self.active_tasks[user_id]
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    self.logger.info(f"[Interrupt] Task cancelled for {user_id}")
        
        # Clear streaming state
        self.streaming_states.pop(user_id, None)
        self.audio_buffer.pop(user_id, None)
        
        # Send interrupt acknowledgment
        await self.send_streaming_chunk(user_id, "interrupted", {
            "message": "Response stopped as requested"
        })
    
    def is_stop_command(self, text: str) -> bool:
        """Check if text contains stop words"""
        text_lower = text.lower().strip()
        return any(word in text_lower for word in self.stop_words)

    # ------------------------
    # Streaming helpers
    # ------------------------
    async def send_streaming_chunk(self, user_id: str, chunk_type: str, data: dict):
        channel = self.data_channels.get(user_id)
        if not channel:
            return False
        try:
            message = {
                "type": chunk_type,
                "data": data,
                "timestamp": datetime.now().isoformat()
            }
            channel.send(json.dumps(message))
            return True
        except Exception as e:
            self.logger.error(f"[WebRTC] Error sending chunk to {user_id}: {e}")
            return False

    # ------------------------
    # Voice model mapping
    # ------------------------
    def _get_voice_for_model(self, voice_model: str, mode: str = "friend") -> str:
        """Get appropriate voice based on voice model and conversation mode"""
        if mode == "ai_assistant":
            return "hi-IN-AaravNeural"
           
           
            
        # Voice model mapping
        voice_mapping = {
            "female1": "en-IN-NeerjaExpressiveNeural",
            "female2": "hi-IN-AnanyaNeural", 
            "male": "hi-IN-ArjunNeural"
        }
         
        selected_voice = voice_mapping.get(voice_model, voice_mapping["female1"])
        print(f"[TTS] Selected voice for mode {mode}: {selected_voice}")
        return selected_voice

    async def generate_and_stream_tts_early(self, user_id: str, text_generator, voice_model: str = "female1", mode: str = "friend"):
        """Generate TTS as text comes in, with early start for low latency"""
        if user_id not in self.data_channels:
            return

        try:
            voice = self._get_voice_for_model(voice_model, mode)
            self.streaming_states[user_id] = {
                "tts_buffer": "",
                "audio_started": False,
                "sentence_count": 0,
                "last_flush_time": time.time()
            }
            
            async for text_chunk in text_generator:
                # Check for interrupt at each chunk
                if self.is_user_interrupted(user_id):
                    self.logger.info(f"[TTS] Stopping TTS due to interrupt for {user_id}")
                    break
                    
                if user_id not in self.streaming_states:
                    break
                    
                if not text_chunk or not isinstance(text_chunk, str):
                    continue  # Skip None or non-string chunks
                    
                state = self.streaming_states[user_id]
                state["tts_buffer"] += text_chunk
                
                # Check if should generate TTS
                should_generate_tts = (
                    any(punct in state["tts_buffer"] for punct in ".!?") or
                    len(state["tts_buffer"].strip()) >= self.tts_chunk_size or
                    (time.time() - state["last_flush_time"] > 0.5)
                )
                
                if should_generate_tts and state["tts_buffer"].strip():
                    if not state["audio_started"] and any(punct in state["tts_buffer"] for punct in ".!?"):
                        state["audio_started"] = True
                        self.logger.info(f"[TTS] Starting audio streaming for {user_id}")

                    # Generate and send TTS chunk with error handling
                    try:
                        await self._generate_and_send_tts_chunk(
                            user_id,
                            state["tts_buffer"].strip(),
                            voice,
                            state["sentence_count"],
                            use_assistant_tts=(mode == "ai_assistant")
                        )
                        state["sentence_count"] += 1
                        state["tts_buffer"] = ""
                        state["last_flush_time"] = time.time()
                    except Exception as tts_error:
                        self.logger.error(f"[TTS] Failed to generate audio for chunk {state['sentence_count']}: {tts_error}")
                        # Continue without audio for this chunk
                        state["sentence_count"] += 1
                        state["tts_buffer"] = ""
                        state["last_flush_time"] = time.time()
                    
                    await asyncio.sleep(0.05)  # small yield for asyncio loop
                    
                
            # Flush remaining buffer if not interrupted
            if user_id in self.streaming_states and not self.is_user_interrupted(user_id):
                state = self.streaming_states[user_id]
                if state["tts_buffer"].strip():
                    try:
                        await self._generate_and_send_tts_chunk(
                            user_id,
                            state["tts_buffer"].strip(),
                            voice,
                            state["sentence_count"],
                            use_assistant_tts=(mode == "ai_assistant")
                        )
                    except Exception as tts_error:
                        self.logger.error(f"[TTS] Failed to generate final audio chunk: {tts_error}")
                        
                await self.send_streaming_chunk(user_id, "audio_complete", {
                    "message": "Audio streaming completed"
                })

        except asyncio.CancelledError:
            self.logger.info(f"[TTS] Task cancelled for {user_id}")
            raise
        except Exception as e:
            self.logger.error(f"[TTS] Early streaming error for {user_id}: {e}")
        finally:
            self.streaming_states.pop(user_id, None)

    async def _generate_and_send_tts_chunk(self, user_id: str, text: str, voice: str, chunk_id: int, use_assistant_tts: bool = False):
        try:
            # Track TTS input tokens
            tts_tokens = len(text.split())  # Simple approximation
            tts_usage = track_token_usage(
                user_id=user_id,
                input_tokens=tts_tokens,
                output_tokens=0,
                source=TokenSource.ASSISTANT
            )

            audio_data = b""
            
            # Validate TTS parameters before generation
            if not text or not text.strip():
                self.logger.warning(f"[TTS] Empty text for {user_id}, skipping chunk {chunk_id}")
                return
                
            if not voice:
                self.logger.error(f"[TTS] No voice specified for {user_id}, using default")
                voice = "en-US-JennyNeural"  # Fallback voice
            
            self.logger.info(f"[TTS] Generating audio for {user_id}: '{text[:50]}...' with voice: {voice}")
            
            # Use assistant TTS engine for assistant mode
            if use_assistant_tts:
                async for chunk_data in self.assistant_tts.generate_tts_stream_assistant(text, user_id, voice):
                    # Check for interrupt during generation
                    if self.is_user_interrupted(user_id):
                        self.logger.info(f"[TTS] TTS generation interrupted for {user_id}")
                        return
                    
                    if chunk_data["type"] == "audio" and chunk_data.get("status") == "ok":
                        data = chunk_data["data"]
                        
                        if isinstance(data, str):
                            try:
                                data = base64.b64decode(data)
                            except Exception as decode_error:
                                self.logger.error(f"[TTS] Failed to decode base64 for {user_id}: {decode_error}")
                                data = data.encode('utf-8')
                        elif isinstance(data, bytes):
                            pass
                        else:
                            self.logger.error(f"[TTS] Unexpected data type for {user_id}: {type(data)}")
                            continue

                        audio_data += data
                        
                    elif chunk_data["type"] == "complete":
                        break
                    elif chunk_data["type"] == "error":
                        error_msg = chunk_data.get('message', 'Unknown TTS error')
                        self.logger.error(f"[TTS] Assistant TTS error for {user_id}: {error_msg}")
                        return
            else:
                # Use regular TTS engine for other modes
                async for chunk_data in self.tts.generate_tts_stream(text, user_id, voice):
                    # Check for interrupt during generation
                    if self.is_user_interrupted(user_id):
                        self.logger.info(f"[TTS] TTS generation interrupted for {user_id}")
                        return
                    
                    if chunk_data["type"] == "audio" and chunk_data.get("status") == "ok":
                        data = chunk_data["data"]
                        
                        if isinstance(data, str):
                            try:
                                data = base64.b64decode(data)
                            except Exception as decode_error:
                                self.logger.error(f"[TTS] Failed to decode base64 for {user_id}: {decode_error}")
                                data = data.encode('utf-8')
                        elif isinstance(data, bytes):
                            pass
                        else:
                            self.logger.error(f"[TTS] Unexpected data type for {user_id}: {type(data)}")
                            continue

                        audio_data += data
                        
                    elif chunk_data["type"] == "complete":
                        break
                    elif chunk_data["type"] == "error":
                        error_msg = chunk_data.get('message', 'Unknown TTS error')
                        self.logger.error(f"[TTS] Chunk generation error for {user_id}: {error_msg}")
                        
                        # Check for specific TTS parameter errors
                        if "parameters are correct" in error_msg:
                            self.logger.error(f"[TTS] TTS parameter error - Voice: {voice}, Text: '{text[:100]}'")
                            # Try with fallback voice
                            if voice != "en-US-JennyNeural":
                                self.logger.info(f"[TTS] Retrying with fallback voice for {user_id}")
                                return await self._generate_and_send_tts_chunk(user_id, text, "en-US-JennyNeural", chunk_id, False)
                        return
                        
        except asyncio.CancelledError:
            self.logger.info(f"[TTS] Chunk generation cancelled for {user_id}")
            raise
        except Exception as e:
            self.logger.error(f"[TTS] Chunk generation error: {e}")
            return

        if audio_data and len(audio_data) > 0:
            try:
                if isinstance(audio_data, str):
                    audio_data = audio_data.encode('utf-8')
                    
                # Convert bytes → base64 string for JSON serialization
                audio_base64 = base64.b64encode(audio_data).decode("utf-8")
                
                await self.send_streaming_chunk(user_id, "audio_chunk", {
                    "audio": audio_base64,
                    "text": text,
                    "chunk_id": chunk_id,
                    "timestamp": datetime.now().isoformat(),
                    "tts_tokens": tts_usage.input_tokens
                })   
                self.logger.info(f"[TTS] Sent audio chunk {chunk_id} ({len(text)} chars, {len(audio_data)} bytes) to {user_id}")
            except Exception as e:
                self.logger.error(f"[TTS] Error encoding or sending audio chunk for {user_id}: {e}")
        else:
            self.logger.warning(f"[TTS] No audio data generated for {user_id}, chunk_id: {chunk_id} - text: '{text[:50]}'")
            
    async def handle_file_message_with_instruction(
        self,
        user_id,
        mode,
        file_path,
        file_type,
        instruction: str = "",
        voice_model: str = "female1",
    ):
        """
        Handle uploaded files with user instructions and stream response via WebRTC.
        Uses chat_manager.process_file_with_instruction if available, otherwise falls back
        to chat_manager.process_file_and_chat.
        """
        user_id = user_id.replace(" ", "_").lower()
        mode = mode or "friend"

        try:
            # Get API key for token counting
            api_key = user_sessions.get(user_id, {}).get("api_key", "default_api_key")
            
            # Count instruction tokens
            instruction_tokens = count_tokens(instruction, api_key) if instruction else 0
            
            # Check token limit before processing
            if not check_user_limit(user_id, instruction_tokens):
                # Notify & exhaust for streaming clients; return error for HTTP callers
                await self._notify_and_exhaust(user_id)
                return {"status": "error", "message": f"Daily token limit of {DEFAULT_DAILY_TOKEN_LIMIT} exceeded."}
            
            # Prefer the new method, fallback if not present
            if hasattr(self.chat_manager, "process_file_with_instruction"):
                reply = await self.chat_manager.process_file_with_instruction(
                    user_id, mode, file_path, file_type, instruction
                )
                instruction_processed = True
            else:
                reply = await self.chat_manager.process_file_and_chat(
                    user_id, mode, file_path, file_type
                )
                instruction_processed = False
                
            # Count tokens in the reply
            reply_tokens = count_tokens(reply, api_key)
            total_tokens = instruction_tokens + reply_tokens
            
            # Update token usage (canonical path that also exhausts if needed)
            if not add_tokens(user_id, api_key, instruction_tokens, reply_tokens):
                await self._notify_and_exhaust(user_id)
                return {"status": "error", "message": "Token limit exceeded after processing."}

            # Log token usage
            self.logger.info(f"[File Upload] {user_id} used {total_tokens} tokens "
                             f"(instruction: {instruction_tokens}, reply: {reply_tokens}) "
                             f"for {file_type} file")

            # If WebRTC channel available → stream the response
            if user_id in self.data_channels:
                await self.handle_text_message_streaming(user_id, mode, reply, voice_model)
                return {
                    "status": "streaming",
                    "voice_model": voice_model,
                    "instruction_processed": instruction_processed,
                    "tokens_used": {
                        "instruction_tokens": instruction_tokens,
                        "reply_tokens": reply_tokens,
                        "total_tokens": total_tokens
                    }
                }

            # HTTP fallback
            result = await self.handle_text_message(user_id, mode, reply, voice_model)
            result["tokens_used"] = {
                "instruction_tokens": instruction_tokens,
                "reply_tokens": reply_tokens,
                "total_tokens": total_tokens
            }
            return result

        except Exception as e:
            self.logger.error(f"[WebRTC] File with instruction handling error for {user_id}: {e}")
            return {"status": "error", "message": str(e)}

    async def handle_file_message(
        self, user_id, mode, file_path, file_type, voice_model: str = "female1"
    ):
        """
        Legacy file handler - now calls enhanced version with empty instruction.
        """
        return await self.handle_file_message_with_instruction(
            user_id, mode, file_path, file_type, instruction="", voice_model=voice_model
        )

    async def handle_text_message_streaming_with_media(self, user_id, mode, text, voice_model="female1"):
        """Enhanced streaming handler that supports media generation"""
        user_id = user_id.replace(" ", "_").lower()
        mode = mode or "friend"

        if self.config.is_maintenance_on():
            await self.send_streaming_chunk(user_id, "final_response", {
                "text": "🚧 INAI is under maintenance.",
                "audio": ""
            })
            return

        # -------- PRE-CHECK: avoid starting a doomed stream --------
        api_key = self._get_api_key_for_user(user_id)
        question_tokens = count_tokens(text, api_key)
        if not check_user_limit(user_id, question_tokens):
            await self._notify_and_exhaust(user_id)
            return
        # -----------------------------------------------------------

        # Token daily context
        reset_user_tokens_if_new_day(user_id)

        if user_id not in self.session_manager.user_sessions:
            self.session_manager.create_user_session(user_id, None)

        conversation_id = await self.history.get_or_create_conversation(user_id, mode)
        await self.history.save_message(conversation_id, "user", text)
        await self.send_streaming_chunk(user_id, "stream_start", {"message": "Processing your request..."})

        # Cancel any ongoing streaming for this user
        if user_id in self.active_tasks:
            old_task = self.active_tasks[user_id]
            if not old_task.done():
                old_task.cancel()
                try:
                    await old_task
                except asyncio.CancelledError:
                    self.logger.info(f"[Stream] Old task for {user_id} cancelled cleanly")
            self.active_tasks.pop(user_id, None)

        try:
            full_response = ""
            chunk_count = 0
            media_content = ""  # For detecting media

            # Async generator for streaming
            async def text_stream_generator():
                nonlocal full_response, chunk_count, media_content
                async for chunk in self.chat_manager.chat_with_groq_stream(user_id, mode, text):
                    if chunk.strip():
                        full_response += chunk
                        media_content += chunk
                        chunk_count += 1

                        await self.send_streaming_chunk(user_id, "text_chunk", {
                            "chunk": chunk,
                            "chunk_id": chunk_count
                        })
                        yield chunk
                        await asyncio.sleep(0.05)

            # Start TTS if mode is not info
            if mode != "info":
                tts_task = asyncio.create_task(
                    self.generate_and_stream_tts_early(
                        user_id,
                        text_stream_generator(),
                        voice_model,
                        mode
                    )
                )
                self.active_tasks[user_id] = tts_task

                try:
                    await tts_task
                except Exception as e:
                    self.logger.error(f"[TTS] Task error: {e}")
            else:
                async for _ in text_stream_generator():
                    pass

            # Save full response
            await self.history.save_message(conversation_id, "assistant", full_response)

            # Update tokens (canonical path that also exhausts if needed)
            answer_tokens = count_tokens(full_response, api_key)
            if not add_tokens(user_id, api_key, question_tokens, answer_tokens):
                await self._notify_and_exhaust(user_id)
                return

            # Get updated totals for logging
            final_user_tokens = get_user_tokens(user_id)
            final_api_key_tokens = get_api_key_tokens(api_key)

            self.logger.info(f"[Token] {user_id} used {question_tokens + answer_tokens} tokens (Q: {question_tokens}, A: {answer_tokens})")
            self.logger.info(f"[User Total] {user_id}: {final_user_tokens} tokens")
            self.logger.info(f"[API Key Total] {api_key[:10]}...: {final_api_key_tokens} tokens")

            # Update CSV log (from old socket.py)
            update_csv_log(
                CSV_PATH=Path(self.csv_save_path), 
                user_id=user_id,
                api_key=api_key,
                question_tokens=question_tokens,
                answer_tokens=answer_tokens,
                total_tokens=final_user_tokens,
                api_key_token_total=final_api_key_tokens,
                task=mode
            )

            # Track question and answer tokens with source
            question_usage = track_token_usage(
                user_id=user_id,
                input_tokens=question_tokens,
                output_tokens=0,
                source=TokenSource.GROQ,
                api_key=api_key
            )
            
            answer_usage = track_token_usage(
                user_id=user_id,
                input_tokens=0,
                output_tokens=answer_tokens,
                source=TokenSource.GROQ,
                api_key=api_key
            )

            # Get subscription info for token display (SAFE)
            subscription_info = self._safedict(get_user_subscription_info(user_id))
            token_limit = subscription_info.get('token_limit', DEFAULT_DAILY_TOKEN_LIMIT)
            plan_name = subscription_info.get('plan', 'Free')
            usage_percentage = (final_user_tokens / token_limit) * 100 if token_limit > 0 else 100

            # Update final response to include token source information
            await self.send_streaming_chunk(user_id, "final_response", {
                "text": full_response,
                "audio": "",
                "complete": True,
                "voice_model": voice_model,
                "token_usage": {
                    "used": final_user_tokens,
                    "limit": token_limit,
                    "percentage": usage_percentage,
                    "plan": plan_name,
                    "sources": {
                        "groq": {
                            "input": question_usage.input_tokens,
                            "output": answer_usage.output_tokens,
                            "total": question_usage.input_tokens + answer_usage.output_tokens
                        }
                    }
                }
            })

        except Exception as e:
            self.logger.error(f"[WebRTC] Streaming error for {user_id}: {e}")
            await self.send_streaming_chunk(user_id, "error", {
                "message": "⚠ I faced an error. Try again.",
                "error": str(e)
            })

    def _contains_media_content(self, text: str) -> bool:
        """Detect media indicators in text"""
        media_indicators = [
            "Generated Diagram",
            "Generated PDF Report",
            "📷", "📊", "📄"
        ]
        return any(indicator in text for indicator in media_indicators)

    async def handle_text_message_streaming(self, user_id, mode, text, voice_model="female1"):
        """Enhanced streaming handler with AI assistant and mode switching support"""
        user_id = user_id.replace(" ", "_").lower()
        
        # Check for mode switching command
        mode_switch_match = None
        switch_patterns = [
            r'^switch\s+(?:to\s+)?(?:the\s+)?(love|friend|elder|info|ai_assistant)\s*(?:mode)?$',
            r'^change\s+(?:to\s+)?(?:the\s+)?(love|friend|elder|info|ai_assistant)\s*(?:mode)?$',
            r'^use\s+(?:the\s+)?(love|friend|elder|info|ai_assistant)\s*(?:mode)?$'
        ]
        
        for pattern in switch_patterns:
            match = re.match(pattern, text.lower().strip())
            if match:
                mode_switch_match = match
                break

        if mode_switch_match:
            new_mode = mode_switch_match.group(1)
            response_text = f"🔄 Switching to {new_mode} mode. How can I help you?"
            
            # Send mode switch confirmation
            await self.send_streaming_chunk(user_id, "stream_start", {
                "message": "Switching modes..."
            })
            
            await self.send_streaming_chunk(user_id, "text_chunk", {
                "chunk": response_text,
                "chunk_id": 1
            })
            
            # Generate TTS for mode switch confirmation
            if mode != "info":
                tts_task = asyncio.create_task(
                    self.generate_and_stream_tts_early(
                        user_id,
                        [response_text],
                        voice_model,
                        new_mode  # Use new mode for TTS
                    )
                )
                self.active_tasks[user_id] = tts_task
                
                try:
                    await tts_task
                except Exception as e:
                    self.logger.error(f"[TTS] Mode switch task error: {e}")
            
            await self.send_streaming_chunk(user_id, "final_response", {
                "text": response_text,
                "audio": "",
                "complete": True,
                "voice_model": voice_model,
                "mode_switched": True,
                "new_mode": new_mode
            })
            
            self.logger.info(f"[Mode] User {user_id} switched to {new_mode} mode")
            return
        
        # Continue with existing message handling for non-switch commands
        if mode == "ai_assistant":
            try:
                # Use the AI assistant to process the query
                assistant_result = await self.ai_assistant.process_query_async(text, user_id)
                
                await self.send_streaming_chunk(user_id, "stream_start", {
                    "message": "AI Assistant is processing..."
                })

                # Format the response for the user
                formatted_response = self.ai_assistant.format_response_for_frontend(assistant_result) or {}
                response_text = formatted_response.get("text", "")
                response_url = formatted_response.get("url")
                metadata = formatted_response.get("metadata", {})

                
                # Enhanced URL handling
                url_instruction = ""
                if response_url:
                    if assistant_result.get("type") == "youtube":
                        url_instruction = " I've found the YouTube video you requested."
                    elif assistant_result.get("type") == "maps":
                        url_instruction = " I've prepared the navigation route for you."
                    elif assistant_result.get("type") == "realtime":
                        url_instruction = " I've found the latest information for you."
                    elif assistant_result.get("type") == "open":
                        url_instruction = " I'll open that website for you."
                    else:
                        url_instruction = " I've shared a helpful link for you."
                
                # Create text for speech (shorter for TTS)
                speech_text = response_text + url_instruction if response_url else response_text
                
                # Create text streaming generator
                async def assistant_speech_generator():
                    words = speech_text.split()
                    chunk = ""
                    
                    for i, word in enumerate(words):
                        chunk += word + " "
                        if (i + 1) % 4 == 0 or word.endswith(('.', '!', '?')) or i == len(words) - 1:
                            if chunk.strip():
                                yield chunk
                                chunk = ""
                                await asyncio.sleep(0.1)  # Small delay for natural speech

                # Start TTS streaming
                tts_task = asyncio.create_task(
                    self.generate_and_stream_tts_early(
                        user_id, 
                        assistant_speech_generator(),
                        voice_model,
                        mode
                    )
                )
                self.active_tasks[user_id] = tts_task

                # Stream text response
                words = response_text.split()
                chunk = ""
                chunk_id = 0
                
                for i, word in enumerate(words):
                    chunk += word + " "
                    if (i + 1) % 4 == 0 or word.endswith(('.', '!', '?')) or i == len(words) - 1:
                        if chunk.strip():
                            chunk_id += 1
                            await self.send_streaming_chunk(user_id, "text_chunk", {
                                "chunk": chunk,
                                "chunk_id": chunk_id
                            })
                            chunk = ""
                            await asyncio.sleep(0.1)

                try:
                    await tts_task
                except Exception as e:
                    self.logger.error(f"[TTS] Assistant task error: {e}")
                
                # Prepare metadata for frontend
                metadata = formatted_response.get("metadata", {})
                if assistant_result.get("type") == "maps" and "destination" in metadata:
                    metadata["instruction"] = f"Navigate to {metadata['destination']}"
                elif assistant_result.get("type") == "youtube" and "search_terms" in metadata:
                    metadata["instruction"] = f"Watch videos about '{metadata['search_terms']}'"
                elif assistant_result.get("type") == "realtime":
                    metadata["instruction"] = "View latest information"
                
                # Send final response with enhanced URL data
                final_response = {
                    "text": response_text,
                    "audio": "",
                    "complete": True,
                    "voice_model": voice_model,
                    "assistant_data": {
                        "url": response_url,
                        "type": assistant_result.get("type"),
                        "metadata": metadata,
                        "should_open_url": response_url is not None  # Flag for frontend
                    }
                }
                
                await self.send_streaming_chunk(user_id, "final_response", final_response)
                
                self.logger.info(f"[Assistant] Response sent to {user_id}: {response_text[:100]}... URL: {response_url}")
                return
                    
            except Exception as e:
                self.logger.error(f"[Assistant] Error for {user_id}: {e}")
                await self.send_streaming_chunk(user_id, "error", {
                    "message": "Assistant error occurred. Try again.",
                    "error": str(e)
                })
                return
        
        # Use the enhanced streaming method for all other modes
        return await self.handle_text_message_streaming_with_media(user_id, mode, text, voice_model)

    # ------------------------
    # Traditional text message (HTTP fallback)
    # ------------------------
    async def handle_text_message(self, user_id, mode, text, voice_model="female1"):
        user_id = user_id.replace(" ", "_").lower()
        
        if mode == "ai_assistant":
            try:
                # Process with AI assistant
                assistant_result = await self.ai_assistant.process_query_async(text, user_id)
                formatted_response = self.ai_assistant.format_response_for_frontend(assistant_result)
                
                # Enhanced response with better metadata
                metadata = formatted_response.get("metadata", {})
                
                return {
                    "text": formatted_response["text"], 
                    "audio": "", 
                    "voice_model": voice_model,
                    "assistant_data": {
                        "url": formatted_response.get("url"),
                        "type": assistant_result.get("type"),
                        "metadata": metadata,
                        "should_open_url": formatted_response.get("url") is not None
                    }
                }
                
            except Exception as e:
                self.logger.error(f"[Assistant] Error for {user_id}: {e}")
                return {
                    "text": "Assistant error occurred. Try again.", 
                    "audio": "", 
                    "voice_model": voice_model
                }
     
        mode = mode or "friend"

        if self.config.is_maintenance_on():
            return {"text": "🚧 INAI is under maintenance.", "audio": ""}

        # Token daily context & pre-check
        reset_user_tokens_if_new_day(user_id)
        api_key = self._get_api_key_for_user(user_id)
        question_tokens = count_tokens(text, api_key)
        if not check_user_limit(user_id, question_tokens):
            # For HTTP callers we don't tear WebRTC, just return message
            move_to_exhausted(user_id)  # add_tokens would do this too if wired as earlier
            return {
                "text": "⚠ You’ve reached your daily token limit. Try again tomorrow or upgrade.",
                "audio": "",
                "voice_model": voice_model
            }

        if user_id not in self.session_manager.user_sessions:
            self.session_manager.create_user_session(user_id, None)

        try:
            conversation_id = await self.history.get_or_create_conversation(user_id, mode)
            await self.history.save_message(conversation_id, "user", text)
            
            # Get response from chat manager
            response_text = await self.chat_manager.chat_with_groq_stream(user_id, mode, text)
            await self.history.save_message(conversation_id, "assistant", response_text)

            # Update token usage (canonical)
            answer_tokens = count_tokens(response_text, api_key)
            if not add_tokens(user_id, api_key, question_tokens, answer_tokens):
                # User now exhausted; return message without tearing down anything here
                return {
                    "text": "⚠ You’ve reached your daily token limit. Further requests will be blocked until tomorrow.",
                    "audio": "",
                    "voice_model": voice_model
                }
            
            final_tokens = get_user_tokens(user_id)
            if final_tokens >= DEFAULT_DAILY_TOKEN_LIMIT:
                response_text += "\n\n⚠ You've reached your daily token limit. Future requests will be blocked until tomorrow."

            return {"text": response_text, "audio": "", "voice_model": voice_model}

        except Exception as e:
            self.logger.error(f"[WebRTC] Traditional message error for {user_id}: {e}")
            return {"text": "⚠ I faced an error. Try again.", "audio": ""}

    # ------------------------
    # Audio message handling
    # ------------------------
    async def handle_audio_message(self, user_id, mode, audio_base64, voice_model="female1"):
        user_id = user_id.replace(" ", "_").lower()
        if not audio_base64:
            return {"text": "Audio was empty.", "audio": ""}

        if user_id not in self.session_manager.user_sessions:
            self.session_manager.create_user_session(user_id, None)

        # Process speech recognition
        query = await self.speech_recognition.process_audio(audio_base64)
        if "error" in query.lower():
            return {"text": query, "audio": ""}

        # Track speech recognition tokens
        speech_tokens = len(query.split())  # Simple approximation
        speech_usage = track_token_usage(
            user_id=user_id,
            input_tokens=speech_tokens,
            output_tokens=0,
            source=TokenSource.ASSISTANT
        )

        # Use streaming if data channel is available
        if user_id in self.data_channels:
            await self.handle_text_message_streaming(user_id, mode, query, voice_model)
            return {
                "status": "streaming", 
                "voice_model": voice_model,
                "speech_tokens": speech_usage.input_tokens
            }
        else:
            response = await self.handle_text_message(user_id, mode, query, voice_model)
            response["speech_tokens"] = speech_usage.input_tokens
            return response

    # ------------------------
    # Stop/interrupt handling (from old socket.py)
    # ------------------------
    async def handle_interrupt(self, user_id, query, mode):
        """Handle stop/interrupt commands"""
        query_lower = query.lower()
        
        if mode != "info" and any(word in query_lower for word in ["stop", "wait", "ruko", "arre", "sun"]):
            self.session_manager.cancel_user_tasks(user_id)
            self.session_manager.stop_current_tts(user_id)
            
            # Get interrupt response
            import random
            reply = random.choice(self.modes.interrupt_responses[mode])
            
            # Generate audio response
            audio = await self.tts.generate_tts(reply, user_id, mode)
            
            # Send via WebRTC if available
            if user_id in self.data_channels:
                await self.send_streaming_chunk(user_id, "interrupt_response", {
                    "text": reply,
                    "audio": audio
                })
            
            return True, reply, audio
        
        return False, None, None

    # ------------------------
    # Enhanced cleanup with audio buffer
    # ------------------------
    async def cleanup_all_connections(self):
        """Cleanup all WebRTC connections and resources"""
        users_to_cleanup = list(self.pcs.keys())
        
        for user_id in users_to_cleanup:
            await self.cleanup_user(user_id)
        
        self.pcs.clear()
        self.data_channels.clear()
        self.audio_buffer.clear()
        self.streaming_states.clear()
        
        self.logger.info("[WebRTC] All connections cleaned up")

    # ------------------------
    # Connection status monitoring
    # ------------------------
    async def get_connection_status(self, user_id: str) -> dict:
        """Get detailed connection status for a user"""
        user_id = user_id.replace(" ", "_").lower()
        
        status = {
            "user_id": user_id,
            "webrtc_connected": False,
            "datachannel_available": False,
            "streaming_supported": False,
            "connection_state": "disconnected",
            "audio_buffer_size": 0,
            "streaming_active": user_id in self.streaming_states
        }
        
        if user_id in self.pcs:
            pc = self.pcs[user_id]
            status["webrtc_connected"] = pc.connectionState == "connected"
            status["connection_state"] = pc.connectionState
        
        if user_id in self.data_channels:
            status["datachannel_available"] = True
        
        if user_id in self.audio_buffer:
            status["audio_buffer_size"] = len(self.audio_buffer[user_id])
        
        status["streaming_supported"] = status["webrtc_connected"] and status["datachannel_available"]
        
        return status
    
    # ------------------------
    # Admin monitoring functions (from old socket.py)
    # ------------------------
    async def get_all_connection_stats(self) -> dict:
        """Get comprehensive stats for admin monitoring"""
        stats = {
            "total_webrtc_connections": len(self.pcs),
            "active_data_channels": len(self.data_channels),
            "streaming_users": len(self.streaming_states),
            "audio_buffers": len(self.audio_buffer),
            "timestamp": datetime.now().isoformat()
        }
        
        # Get detailed user stats
        user_stats = {}
        for user_id in self.pcs.keys():
            user_stats[user_id] = await self.get_connection_status(user_id)
        
        stats["users"] = user_stats
        return stats

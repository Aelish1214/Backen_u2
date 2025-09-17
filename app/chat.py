import os
import base64
import asyncio
from docx import Document
import openpyxl
import random
import re
from typing import Dict, List, AsyncGenerator, Optional, Tuple
from datetime import datetime

from openai import OpenAI

# Import our separate modules
from pdf_handler import PDFManager
from text_processor import TextProcessor, MediaRequestDetector


class ChatManager:
    """Enhanced chat manager with selective PDF generation capabilities"""
    
    def __init__(self, config, modes, logger):
        self.config = config
        self.modes = modes
        self.logger = logger
        
        self.active_tasks = {}
        
        # Initialize core components
        self.pdf_manager = PDFManager("generated_media", logger)
        self.text_processor = TextProcessor()
        self.media_detector = MediaRequestDetector()
        
        # Chat state management
        self.chat_histories: Dict[str, Dict[str, List[dict]]] = {}
        self.image_contexts: Dict[str, Dict[str, dict]] = {}
        self.file_contexts: Dict[str, Dict[str, dict]] = {}
        
        # OpenAI client setup
        self.client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=config.groq_api_key,
        )
        
        # Model configuration
        self.primary_model = "llama-3.3-70b-versatile"
        self.fallback_model = "llama-3.1-8b-instant"
        self.multimodal_model = "meta-llama/llama-4-maverick-17b-128e-instruct"
        
        # Rate limiting
        self.rps_limit = getattr(config, "rps_limit", 5)
        self._sema = asyncio.Semaphore(self.rps_limit)
        
    def _cancel_existing_task(self, user_id: str, mode: str):
        """Cancel existing streaming task if running"""
        key = f"{user_id}_{mode}"
        if key in self.active_tasks:
            task = self.active_tasks[key]
            if not task.done():
                task.cancel()
                try:
                    # Wait briefly for proper cancellation
                    asyncio.create_task(self._wait_for_cancellation(task))
                except Exception:
                    pass
                self.logger.info(f"⚠️ Cancelled previous task for {key}")
            del self.active_tasks[key]

    async def _wait_for_cancellation(self, task):
        """Helper to wait for task cancellation"""
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        
    
    async def _process_audio_file(self, user_id: str, mode: str, file_path: str, instruction: str) -> str:
        """Process audio file with Whisper ASR and provide text response"""
        try:
            if not os.path.exists(file_path):
                return "Sorry, the audio file could not be found."

            # Open audio file and send to Whisper
            with open(file_path, "rb") as audio_file:
                transcription = await asyncio.to_thread(
                    lambda: self.client.audio.transcriptions.create(
                        model="whisper-large-v3",
                        file=audio_file
                    )
                )

            transcript_text = transcription.text if hasattr(transcription, "text") else None
            if not transcript_text:
                return "I couldn't transcribe this audio file."

            # Store transcript as file context
            self._store_file_context(user_id, mode, file_path, "audio", transcript_text)

            # Prepare context prompt
            if instruction.strip():
                context_prompt = f"Audio transcription:\n{transcript_text}\n\nInstruction: {instruction}"
            else:
                context_prompt = f"Here is the transcription from the uploaded audio file:\n\n{transcript_text}\n\nPlease analyze/respond."

            # Pass to normal chat flow
            full_reply = ""
            async for chunk in self._handle_regular_chat(user_id, mode, context_prompt):
                full_reply += chunk

            return full_reply

        except Exception as e:
            self.logger.error(f"Error processing audio file: {str(e)}")
            return f"I encountered an error while processing your audio file: {str(e)}"

    
    # ================== UTILITY METHODS ==================
    
    def _get_context_key(self, user_id: str, mode: str) -> str:
        """Generate unique key for user-mode combination"""
        return f"{user_id}_{mode}"
    
    def _is_image_related_query(self, message: str) -> bool:
        """Check if message is related to previously uploaded image"""
        image_keywords = [
            "this image", "the image", "in the image", "from the image",
            "what do you see", "describe this", "analyze this",
            "what's in", "what is in", "tell me about",
            "what color", "how many", "where is", "what type"
        ]
        
        message_lower = message.lower()
        
        # Direct image references
        if any(ref in message_lower for ref in ["this image", "the image", "in the image"]):
            return True
        
        # Short queries with image keywords
        if len(message.split()) <= 10:
            if any(keyword in message_lower for keyword in image_keywords):
                return True
        
        # Questions that commonly follow image uploads
        question_starters = ["what", "where", "how", "why", "who", "when", "is this", "can you"]
        if any(message_lower.startswith(starter) for starter in question_starters):
            return True
        
        return False
    
    def _is_file_related_query(self, message: str) -> bool:
        """Check if message is related to previously uploaded file"""
        file_keywords = [
            "this file", "the file", "this document", "the document",
            "uploaded file", "pdf content", "document content",
            "from the file", "in the file", "based on", "according to"
        ]
        
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in file_keywords)
    
    # ================== FILE CONTEXT MANAGEMENT ==================
    
    def _store_file_context(self, user_id: str, mode: str, file_path: str, file_type: str, extracted_content: str):
        """Store file context for future reference"""
        self.file_contexts.setdefault(user_id, {})[mode] = {
            "file_path": file_path,
            "file_type": file_type,
            "content": extracted_content,
            "timestamp": datetime.now(),
            "message_count": 0
        }
        self.logger.info(f"Stored file context for {user_id}_{mode} - {file_type}")
    
    def _get_file_context(self, user_id: str, mode: str) -> Optional[dict]:
        """Get stored file context if available and recent"""
        context = self.file_contexts.get(user_id, {}).get(mode)
        if context:
            time_diff = (datetime.now() - context["timestamp"]).total_seconds()
            if context["message_count"] < 20 and time_diff < 3600:  # 1 hour, 20 messages
                return context
            else:
                if user_id in self.file_contexts and mode in self.file_contexts[user_id]:
                    del self.file_contexts[user_id][mode]
                self.logger.info(f"Cleaned up old file context for {user_id}_{mode}")
        return None
    
    def _increment_file_message_count(self, user_id: str, mode: str):
        """Increment message count for file context tracking"""
        context = self.file_contexts.get(user_id, {}).get(mode)
        if context:
            context["message_count"] += 1
    
    # ================== IMAGE CONTEXT MANAGEMENT ==================
    
    def _store_image_context(self, user_id: str, mode: str, image_path: str, image_base64: str):
        """Store image context for future reference"""
        self.image_contexts.setdefault(user_id, {})[mode] = {
            "image_path": image_path,
            "image_base64": image_base64,
            "timestamp": datetime.now(),
            "message_count": 0
        }
        self.logger.info(f"Stored image context for {user_id}_{mode}")
    
    def _get_image_context(self, user_id: str, mode: str) -> Optional[dict]:
        """Get stored image context if available and recent"""
        context = self.image_contexts.get(user_id, {}).get(mode)
        if context:
            time_diff = (datetime.now() - context["timestamp"]).total_seconds()
            if context["message_count"] < 20 and time_diff < 1800:  # 30 minutes
                return context
            else:
                if user_id in self.image_contexts and mode in self.image_contexts[user_id]:
                    del self.image_contexts[user_id][mode]
                self.logger.info(f"Cleaned up old image context for {user_id}_{mode}")
        return None
    
    def _increment_message_count(self, user_id: str, mode: str):
        """Increment message count for image context tracking"""
        context = self.image_contexts.get(user_id, {}).get(mode)
        if context:
            context["message_count"] += 1
    
    # ================== AI CLIENT METHODS ==================
    
    async def _create_chat(self, *, model, messages, service_tier, temperature, max_tokens=None, stream=False):
        """Create chat completion with OpenAI client"""
        def _do():
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": stream,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            return self.client.chat.completions.create(**kwargs)
        return await asyncio.to_thread(_do)
    
    async def _with_retry(self, call, *, tries=3, base=0.4, cap=3.0):
        """Execute with exponential backoff retry"""
        last_exc = None
        for attempt in range(1, tries + 1):
            try:
                return await call()
            except Exception as e:
                last_exc = e
                if attempt == tries:
                    break
                delay = min(cap, base * (2 ** (attempt - 1))) + random.uniform(0, 0.2)
                await asyncio.sleep(delay)
        raise last_exc
    
    # ================== PDF GENERATION METHODS ==================
    
    async def _generate_pdf_for_question(self, user_id: str, mode: str, question: str, file_context: dict = None) -> str:
        """Generate PDF with answer to the question and return only PDF link"""
        try:
            # Create enhanced prompt for PDF content
            if file_context:
                # Question about uploaded file
                enhanced_prompt = (
                    f"Please provide a comprehensive and detailed answer to this question based on the uploaded file content:\n\n"
                    f"Question: {question}\n\n"
                    f"File Content:\n{file_context['content']}\n\n"
                    f"Please structure your response as a complete document with proper sections and detailed explanations."
                )
            else:
                # General question
                enhanced_prompt = (
                    f"Please provide a comprehensive and detailed answer to this question:\n\n"
                    f"Question: {question}\n\n"
                    f"Please structure your response as a complete document with proper sections and detailed explanations."
                )
            
            # Get AI response for PDF content (non-streaming)
            messages = [
                {"role": "system", "content": self.modes.modes[mode]},
                {"role": "user", "content": enhanced_prompt}
            ]
            
            completion = await self._with_retry(
                lambda: self._create_chat(
                    model=self.primary_model,
                    messages=messages,
                    service_tier="flex",
                    temperature=0.7,
                    stream=False,
                )
            )
            
            if hasattr(completion, 'choices') and completion.choices:
                ai_answer = completion.choices[0].message.content
            else:
                ai_answer = "Unable to generate response."
            
            # Generate PDF with the AI answer
            pdf_result = self.pdf_manager.create_qa_pdf(question, ai_answer, user_id)
            
            if pdf_result["success"]:
                # Return only the PDF link message
                return f"📄 **PDF Generated!** [Download PDF]({pdf_result['download_url']})"
            else:
                return f"❌ PDF generation failed: {pdf_result.get('error', 'Unknown error')}"
                
        except Exception as e:
            self.logger.error(f"PDF generation error: {e}")
            return f"❌ Error generating PDF: {str(e)}"
        
        
    
    # ================== MULTIMODAL CHAT ==================
    
    async def _chat_with_multimodal(self, user_id: str, mode: str, message: str, image_base64: str) -> str:
        """Handle chat with multimodal model for image-related queries"""
        try:
            messages = [
                {"role": "system", "content": self.modes.modes[mode]},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": message},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }
            ]
            
            completion = await self._with_retry(
                lambda: self._create_chat(
                    model=self.multimodal_model,
                    messages=messages,
                    service_tier="flex",
                    temperature=0.7,
                    stream=False,
                )
            )
            
            if hasattr(completion, 'choices') and completion.choices:
                response = completion.choices[0].message.content
                
                # Add to chat history
                history = self.chat_histories.setdefault(user_id, {}).setdefault(mode, [])
                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": response})
                
                return response
            else:
                return "I couldn't process your request about the image."
                
        except Exception as e:
            self.logger.error(f"Multimodal chat error: {e}")
            return f"I encountered an error while analyzing the image: {str(e)}"
    
    # ================== MAIN STREAMING CHAT METHOD ==================
    
    async def chat_with_groq_stream(self, user_id: str, mode: str, message: str) -> AsyncGenerator[str, None]:
        """Main streaming chat method with selective PDF generation"""
        # Cancel old task before starting new one
        self._cancel_existing_task(user_id, mode)
        
        # Store current task
        key = f"{user_id}_{mode}"
        current_task = asyncio.current_task()
        self.active_tasks[key] = current_task

        async with self._sema:
            try:
                # Get last 2 messages from history
                history = self.chat_histories.setdefault(user_id, {}).setdefault(mode, [])
                last_two_msgs = history[-2:] if len(history) >= 2 else history

                # Get stored file context (audio/pdf/etc.)
                file_context = self._get_file_context(user_id, mode)

                # Check if this is specifically a PDF generation request
                is_media_request, media_type, media_subtype = self.media_detector.detect_request(message)
                
                if is_media_request and media_type == "pdf":
                    # This is a PDF generation request - return only PDF link
                    self.logger.info(f"PDF generation request detected: {message}")
                    
                    if media_subtype == "file_question" and file_context:
                        # PDF generation about uploaded file
                        is_file_pdf, extracted_question = self.media_detector.detect_file_pdf_request(message)
                        question = extracted_question if extracted_question else message
                        pdf_message = await self._generate_pdf_for_question(user_id, mode, question, file_context)
                        
                    elif media_subtype in ["report", "last_qa"]:
                        # General PDF generation
                        pdf_message = await self._generate_pdf_for_question(user_id, mode, message)
                    else:
                        # Default PDF generation
                        pdf_message = await self._generate_pdf_for_question(user_id, mode, message, file_context)
                    
                    # Stream only the PDF link message
                    for chunk in pdf_message.split():
                        if current_task.cancelled():
                            self.logger.info(f"Task cancelled during PDF streaming for {key}")
                            return
                        yield chunk + " "
                    return

                # Audio-related keywords
                audio_keywords = ["audio", "voice", "sound", "speech", "music", "song", "talk", "recording", "transcribe"]
                is_audio_query = any(word in message.lower() for word in audio_keywords)

                # Handle audio queries
                if is_audio_query:
                    recent_audio_uploaded = any(
                        msg["role"] == "user" and "[Audio uploaded]" in msg.get("content", "")
                        for msg in last_two_msgs
                    )

                    if recent_audio_uploaded and file_context and file_context.get("file_type") == "audio":
                        self.logger.info(f"🎧 Using Whisper for: {message}")
                        response = await self._process_audio_file(user_id, mode, file_context["file_path"], message)

                        for chunk in response.split():
                            if current_task.cancelled():
                                return
                            yield chunk + " "
                        return

                # Check for image context
                image_context = self._get_image_context(user_id, mode)
                
                # Handle image queries
                if image_context:
                    recent_image_uploaded = any(
                        msg["role"] == "user" and "[Image uploaded]" in msg.get("content", "")
                        for msg in last_two_msgs
                    )

                    if recent_image_uploaded or self._is_image_related_query(message):
                        self.logger.info(f"🖼 Using multimodal model for image query: {message}")
                        self._increment_message_count(user_id, mode)

                        response = await self._chat_with_multimodal(
                            user_id, mode, message, image_context["image_base64"]
                        )

                        for chunk in response.split():
                            if current_task.cancelled():
                                self.logger.info(f"Task cancelled during multimodal streaming for {key}")
                                return
                            yield chunk + " "
                        return

                # For file-related queries or when file context exists, enhance the message
                if file_context:
                    self._increment_file_message_count(user_id, mode)
                    
                    # Check if query is related to the file
                    if self._is_file_related_query(message) or len(message.split()) <= 10:
                        # Add file content to the message for context
                        enhanced_message = f"Based on the uploaded {file_context['file_type']} file, {message}\n\nFile content:\n{file_context['content'][:2000]}..."
                        message = enhanced_message
                
                # Increment message counts
                if image_context:
                    self._increment_message_count(user_id, mode)
                    
                # Handle regular chat (no PDF generation unless specifically requested)
                self.logger.info(f"🧠 Using regular chat for: {message}")
                async for chunk in self._handle_regular_chat(user_id, mode, message):
                    if current_task.cancelled():
                        return
                    yield chunk

            except asyncio.CancelledError:
                self.logger.info(f"Chat streaming cancelled for {key}")
                yield ""
                raise
            except Exception as e:
                self.logger.error(f"Chat streaming error for user {user_id}: {e}")
                yield "I had trouble understanding. Can you ask again?"
            finally:
                # Cleanup task reference
                if key in self.active_tasks and self.active_tasks[key] == current_task:
                    del self.active_tasks[key]
    
    async def _handle_regular_chat(self, user_id: str, mode: str, message: str):
        """Handle regular chat with full streaming support for all modes"""
        current_task = asyncio.current_task()
        history = self.chat_histories.setdefault(user_id, {}).setdefault(mode, [])
        history.append({"role": "user", "content": message})

        # Prepare prompt based on mode
        system_prompt = self.modes.modes.get(mode, "You are a helpful assistant.")

        # Include last 10 messages for context
        messages = [{"role": "system", "content": system_prompt}, *history[-10:]]
        full_response = ""

        try:
            # First try with primary model
            completion = await self._with_retry(
                lambda: self._create_chat(
                    model=self.primary_model,
                    messages=messages,
                    service_tier="flex",
                    temperature=0.7,
                    stream=True,  # ✅ Enable streaming for all modes
                )
            )
        except Exception as e_primary:
            self.logger.error(f"Primary model failed: {e_primary}, using fallback model")
            completion = await self._with_retry(
                lambda: self._create_chat(
                    model=self.fallback_model,
                    messages=messages,
                    service_tier="flex",
                    temperature=0.7,
                    stream=True,
                )
            )

        # Process chunks in real-time
        async for chunk in self._process_stream(completion):
            # if current_task.cancelled():
            #     self.logger.info("Chat streaming cancelled")
            #     yield "[Response cancelled]"
            #     return

            # full_response += chunk
            yield chunk  # ✅ Live streaming for WebRTC

        # Update history only after successful completion
        if not current_task.cancelled():
            cleaned_response = self.text_processor.clean_extracted_text(full_response)
            history.append({
                "role": "assistant",
                "content": cleaned_response or "I'm sorry, I couldn't generate a response."
            })
        else:
            # If cancelled, remove the last user message to keep history clean
            if history and history[-1]["role"] == "user":
                history.pop()

    async def _process_stream(self, completion):
        for chunk in completion:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            await asyncio.sleep(0)  # yield control to event loop

    
    # ================== FILE PROCESSING METHODS ==================
    
    async def process_file_with_instruction(self, user_id: str, mode: str, file_path: str, file_type: str, instruction: str = "") -> str:
        """Process uploaded files with optional instructions - only text responses"""
        try:
            self.logger.info(f"Processing {file_type} file for user {user_id}: {file_path}")
            
            if not os.path.exists(file_path):
                return "Sorry, the file could not be found for processing."
            
            if file_type == "pdf":
                return await self._process_pdf_file(user_id, mode, file_path, instruction)
            elif file_type == "image":
                return await self._process_image_file(user_id, mode, file_path, instruction)
            elif file_type == "docx":
                return await self._process_docx_file(user_id, mode, file_path, instruction)
            elif file_type == "excel":
                return await self._process_excel_file(user_id, mode, file_path, instruction)
            elif file_type == "audio":
                return await self._process_audio_file(user_id, mode, file_path, instruction)
            else:
                return "Unsupported file type."
                
        except Exception as e:
            self.logger.error(f"Error processing {file_type} file: {str(e)}")
            return f"I encountered an error while processing your {file_type} file. Please try again."
    
    async def _process_pdf_file(self, user_id: str, mode: str, file_path: str, instruction: str) -> str:
        """Process PDF file and provide text response (NO PDF generation)"""
        # Extract text from PDF
        extracted_text = self.pdf_manager.extract_text_from_pdf(file_path)
        
        if not extracted_text or extracted_text.startswith("Error"):
            return "Sorry, I couldn't extract readable text from this PDF file."
        
        # Clean and format the text
        cleaned_text = self.text_processor.clean_extracted_text(extracted_text)
        
        # Store file context for future questions
        self._store_file_context(user_id, mode, file_path, "pdf", cleaned_text)
        
        # Create chat-friendly format
        if instruction.strip():
            context_prompt = f"Please analyze the following PDF content according to this instruction: {instruction}\n\nPDF Content:\n{cleaned_text}"
        else:
            context_prompt = f"Please provide a summary and analysis of this PDF content:\n\n{cleaned_text}"
        
        # Process with regular chat to get AI response
        full_reply = ""
        async for chunk in self._handle_regular_chat(user_id, mode, context_prompt):
            full_reply += chunk
        
        return full_reply
    
    async def _process_docx_file(self, user_id: str, mode: str, file_path: str, instruction: str) -> str:
        """Process Word (.docx) file and provide text response"""
        try:
            doc = Document(file_path)
            extracted_text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
        except Exception as e:
            return f"Error extracting text from Word file: {str(e)}"

        if not extracted_text:
            return "Sorry, I couldn't extract any text from this Word document."

        cleaned_text = self.text_processor.clean_extracted_text(extracted_text)
        
        # Store file context for future questions
        self._store_file_context(user_id, mode, file_path, "docx", cleaned_text)

        if instruction.strip():
            context_prompt = f"Please analyze the following Word document content according to this instruction: {instruction}\n\nDocument Content:\n{cleaned_text}"
        else:
            context_prompt = f"Please provide a summary and analysis of this Word document:\n\n{cleaned_text}"

        # Process with regular chat to get AI response
        full_reply = ""
        async for chunk in self._handle_regular_chat(user_id, mode, context_prompt):
            full_reply += chunk
        
        return full_reply

    async def _process_excel_file(self, user_id: str, mode: str, file_path: str, instruction: str) -> str:
        """Process Excel (.xlsx) file and provide text response"""
        try:
            wb = openpyxl.load_workbook(file_path)
            text_data = []
            for sheet in wb.sheetnames:
                text_data.append(f"=== Sheet: {sheet} ===")
                ws = wb[sheet]
                for row in ws.iter_rows(values_only=True):
                    row_text = [str(cell) for cell in row if cell is not None]
                    if row_text:
                        text_data.append(" | ".join(row_text))
            extracted_text = "\n".join(text_data)
        except Exception as e:
            return f"Error extracting text from Excel file: {str(e)}"

        if not extracted_text:
            return "Sorry, I couldn't extract any text from this Excel file."

        cleaned_text = self.text_processor.clean_extracted_text(extracted_text)
        
        # Store file context for future questions
        self._store_file_context(user_id, mode, file_path, "excel", cleaned_text)

        if instruction.strip():
            context_prompt = f"Please analyze the following Excel data according to this instruction: {instruction}\n\nExcel Data:\n{cleaned_text}"
        else:
            context_prompt = f"Please provide a summary and analysis of this Excel data:\n\n{cleaned_text}"

        # Process with regular chat to get AI response
        full_reply = ""
        async for chunk in self._handle_regular_chat(user_id, mode, context_prompt):
            full_reply += chunk
        
        return full_reply
    
    async def _process_image_file(self, user_id: str, mode: str, file_path: str, instruction: str) -> str:
        """Process image file with multimodal model"""
        try:
            # Convert image to base64 and store context
            with open(file_path, "rb") as img_file:
                img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
            
            # Store image context for future reference
            self._store_image_context(user_id, mode, file_path, img_base64)
            
            context_prompt = instruction if instruction.strip() else "Describe this image in detail and analyze its content."
            
            messages = [
                {"role": "system", "content": "You are a helpful assistant that analyzes images accurately and thoroughly."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": context_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                    ]
                }
            ]
            
            completion = await self._with_retry(
                lambda: self._create_chat(
                    model=self.multimodal_model,
                    messages=messages,
                    service_tier="flex",
                    temperature=0.7,
                    stream=False,
                )
            )
            
            if hasattr(completion, 'choices') and completion.choices:
                response = completion.choices[0].message.content
                
                # Add to chat history
                history = self.chat_histories.setdefault(user_id, {}).setdefault(mode, [])
                history.append({"role": "user", "content": f"[Image uploaded] {context_prompt}"})
                history.append({"role": "assistant", "content": response})
                
                return response
            else:
                return "Unable to process the image."
                
        except Exception as e:
            self.logger.error(f"Image processing failed: {e}")
            return f"I encountered an error while analyzing your image: {str(e)}"
    
    async def process_file_and_chat(self, user_id: str, mode: str, file_path: str, file_type: str) -> str:
        """Process file without additional instruction"""
        return await self.process_file_with_instruction(user_id, mode, file_path, file_type, "")
    
    # ================== CONTEXT MANAGEMENT ==================
    
    def clear_image_context(self, user_id: str, mode: str = None):
        """Clear image context for user (optionally specific mode)"""
        if mode:
            if user_id in self.image_contexts and mode in self.image_contexts[user_id]:
                del self.image_contexts[user_id][mode]
                self.logger.info(f"Cleared image context for {user_id}_{mode}")
        else:
            if user_id in self.image_contexts:
                del self.image_contexts[user_id]
                self.logger.info(f"Cleared all image contexts for user {user_id}")
    
    def clear_file_context(self, user_id: str, mode: str = None):
        """Clear file context for user (optionally specific mode)"""
        if mode:
            if user_id in self.file_contexts and mode in self.file_contexts[user_id]:
                del self.file_contexts[user_id][mode]
                self.logger.info(f"Cleared file context for {user_id}_{mode}")
        else:
            if user_id in self.file_contexts:
                del self.file_contexts[user_id]
                self.logger.info(f"Cleared all file contexts for user {user_id}")
    
    def get_active_file_contexts(self, user_id: str) -> Dict[str, dict]:
        """Get all active file contexts for a user"""
        return self.file_contexts.get(user_id, {})
    
    def get_active_image_contexts(self, user_id: str) -> Dict[str, dict]:
        """Get all active image contexts for a user"""
        return self.image_contexts.get(user_id, {})
    
    def clear_chat_history(self, user_id: str, mode: str = None):
        """Clear chat history for user"""
        if mode:
            if user_id in self.chat_histories and mode in self.chat_histories[user_id]:
                del self.chat_histories[user_id][mode]
                self.logger.info(f"Cleared chat history for {user_id}_{mode}")
        else:
            if user_id in self.chat_histories:
                del self.chat_histories[user_id]
                self.logger.info(f"Cleared all chat history for user {user_id}")
    
    def get_chat_summary(self, user_id: str, mode: str) -> str:
        """Get a summary of recent chat history"""
        history = self.chat_histories.get(user_id, {}).get(mode, [])
        if not history:
            return "No chat history found."
        
        # Get last 5 exchanges
        recent_messages = history[-10:] if len(history) >= 10 else history
        
        summary_parts = []
        for msg in recent_messages:
            role_icon = "User" if msg["role"] == "user" else "AI"
            content_preview = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            summary_parts.append(f"{role_icon}: {content_preview}")
        
        return "\n".join(summary_parts)
import re
import base64
import edge_tts
import time
from langdetect import detect
import asyncio

class TextToSpeech:
    def __init__(self, config, logger):
        """
        TTS generator using edge-tts.
        :param config: Config instance with voice settings
        :param logger: Logger instance for info/debug
        """
        self.config = config
        self.logger = logger

    def _clean_text(self, text: str) -> str:
        """Clean text for TTS processing."""
        text = re.sub(r"\((.*?)\)", "", text)
        text = re.sub(r"[*#@%^&_=+\[\]{}<>|~`]", "", text)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r'[\U0001F600-\U0001F64F'
                      r'\U0001F300-\U0001F5FF'
                      r'\U0001F680-\U0001F6FF'
                      r'\U0001F1E0-\U0001F1FF'
                      r'\U00002700-\U000027BF'
                      r'\U0001F900-\U0001F9FF'
                      r'\U00002600-\U000026FF'
                      r'\U00002B00-\U00002BFF'
                      r'\U0001FA70-\U0001FAFF'
                      r'\U000025A0-\U000025FF]+', '', text)
        return text.strip()

    def _detect_language(self, text: str) -> str:
        """Detect text language."""
        try:
            return detect(text)
        except Exception as e:
            self.logger.warning(f"Language detection failed: {e}")
            return "en"

    def _get_voice_from_model(self, voice_model: str) -> str:
        """Get actual voice name from voice model."""
        # Voice model to actual voice mapping
        voice_mapping = {
            "female1": "en-IN-NeerjaExpressiveNeural",
            "female2": "en-US-JennyNeural", 
            # "male": "en-US-GuyNeural"
            "male": "en-IN-PrabhatNeural"
        }
        
        # If it's already a voice name (backward compatibility)
        if voice_model in voice_mapping.values():
            return voice_model
            
        # Get from mapping or default to female1
        return voice_mapping.get(voice_model, voice_mapping["female1"])

    async def generate_tts_stream(self, text: str, user_id: str, voice_model: str = "female1"):
        """Generate TTS audio chunks as base64 with word-level info."""
        start_time = time.time()
        clean_text = self._clean_text(text)
        if not clean_text:
            self.logger.warning(f"Empty text for user {user_id}")
            yield {"type": "error", "message": "Empty text", "status": "failed"}
            return

        # Get actual voice name from voice model
        voice = self._get_voice_from_model(voice_model)
        # audio_buffer = bytearray()
        current_audio_buffer = bytearray()
        # word_buffer = []
        current_word_buffer = []
        last_flush_time = time.time()

        try:
            # self.logger.info(f"[TTS] Starting generation for user {user_id} with voice model '{voice_model}' -> voice '{voice}'")
            # communicate = edge_tts.Communicate(clean_text, voice=voice)
            
            self.logger.info(f"[TTS] Starting generation for user {user_id} with voice '{voice}'")
            communicate = edge_tts.Communicate(clean_text, voice=voice)

            # # Collect audio data first to ensure single generation
            # audio_chunks = []
            # current_audio_buffer = bytearray()
            # current_word_buffer = []

            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    current_audio_buffer.extend(chunk["data"])

                elif chunk["type"] == "WordBoundary":
                    current_word_buffer.append(chunk["text"])
                    
                    # Create audio chunk when we have enough words or hit sentence boundary
                    # if len(current_word_buffer) >= 5 or any(word.endswith(('.', '!', '?')) for word in current_word_buffer):
                    # if any(word.endswith(('.', '!', '?')) for word in current_word_buffer):
                    if (any(word.endswith(('.', '!', '?')) for word in current_word_buffer)
                        or (time.time() - last_flush_time > 0.5)):
                        if current_audio_buffer:
                            elapsed = round(time.time() - start_time, 3)
                            # audio_chunk = base64.b64encode(bytes(current_audio_buffer)).decode("utf-8")
                            audio_data = bytes(current_audio_buffer)
                            
                            # audio_chunks.append({
                            #     "type": "audio",
                            #     "data": audio_chunk,
                            #     "text": " ".join(current_word_buffer),
                            #     "status": "ok",
                            #     "elapsed": elapsed,
                            #     "voice_model": voice_model
                            # })
                            yield {
                                "type": "audio",
                                "data": audio_data,
                                "text": " ".join(current_word_buffer),
                                "status": "ok",
                                "elapsed": elapsed,
                                "voice_model": voice_model
                            }
                            self.logger.info(f"[TTS] Chunk streamed ({elapsed}s)")

                            
                            # self.logger.info(f"[TTS]Sentence audio chunk prepared  ({len(audio_chunk)} chars, {elapsed}s)")
                            current_audio_buffer.clear()
                            current_word_buffer.clear()
                            last_flush_time = time.time()

            # Handle any remaining audio/words
            if current_audio_buffer:
                elapsed = round(time.time() - start_time, 3)
                # audio_chunk = base64.b64encode(bytes(current_audio_buffer)).decode("utf-8")
                audio_data = bytes(current_audio_buffer)
                # audio_chunks.append({
                #     "type": "audio",
                #     "data": audio_chunk,
                #     "text": " ".join(current_word_buffer),
                #     "status": "ok",
                #     "elapsed": elapsed,
                #     "voice_model": voice_model
                # })
                # self.logger.info(f"[TTS] Final audio chunk prepared ({elapsed}s)")
                
                yield {
                    "type": "audio",
                    "data": audio_data,
                    "text": " ".join(current_word_buffer),
                    "status": "ok",
                    "elapsed": elapsed,
                    "voice_model": voice_model
                }
                self.logger.info(f"[TTS] Final chunk streamed ({elapsed}s)")

            # Yield all prepared chunks
            # for audio_chunk in audio_chunks:
            #     yield audio_chunk

            yield {
                "type": "complete", 
                "status": "ok", 
                "elapsed": round(time.time() - start_time, 3),
                "voice_model": voice_model,
                # "chunks_generated": len(audio_chunks)
            }
            
            # self.logger.info(f"[TTS] Completed for user {user_id} in {round(time.time() - start_time, 3)}s with {len(audio_chunks)} chunks")
            self.logger.info(f"[TTS] Completed for user {user_id}")

        except Exception as e:
            elapsed = round(time.time() - start_time, 3)
            self.logger.error(f"[TTS] Streaming error after {elapsed}s: {e}")
            yield {
                "type": "error", 
                "message": str(e), 
                "status": "failed", 
                "elapsed": elapsed,
                "voice_model": voice_model
            }
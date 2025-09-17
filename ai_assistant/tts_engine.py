import io
import asyncio
import pygame
import edge_tts
import threading
import re
import base64

class TTSEngine:
    def __init__(self):
        self.speak_lock = threading.Lock()
        pygame.mixer.init(frequency=22050)
        self.tts_available = True
        self.default_voice = "en-IN-AaravNeural"  # Correct voice for Aarav
        print(f"✅ Edge-TTS ready with voice: {self.default_voice}")

    async def _edge_tts_speak(self, text):
        try:
            output = io.BytesIO()
            communicate = edge_tts.Communicate(text, voice=self.default_voice)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    output.write(chunk["data"])
            output.seek(0)
            pygame.mixer.music.load(output)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
            output.close()
        except Exception as e:
            print(f"❌ Edge-TTS failed for voice {self.default_voice}: {e}")

    async def speak_text(self, text, return_text=False):
        if not text:
            return "" if return_text else None
        text_for_speech = re.sub(r'http[s]?://[^\s]+', '', text).strip()
        if "Playing" in text_for_speech and "YouTube" in text_for_speech:
            text_for_speech = "I have played the YouTube video."
        elif "Flight from" in text_for_speech:
            text_for_speech = f"मैंने {text_for_speech} की जानकारी दे दी है।"
        elif "YouTube link:" in text and not text_for_speech:
            text_for_speech = "I have shared the YouTube link."
        elif "YouTube search:" in text and not text_for_speech:
            text_for_speech = "I have shared the YouTube search link."
        elif "Directions:" in text and not text_for_speech:
            text_for_speech = "I have shared the directions link."
        elif not text_for_speech:
            text_for_speech = "I have shared this."
        print(f"🔊 Speaking: {text_for_speech[:50]}...")
        if return_text:
            return text_for_speech
        if self.tts_available:
            try:
                with self.speak_lock:
                    output = io.BytesIO()
                    communicate = edge_tts.Communicate(text_for_speech, voice=self.default_voice)
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            output.write(chunk["data"])
                    output.seek(0)
                    pygame.mixer.music.load(output)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        await asyncio.sleep(0.1)
                    output.close()
            except Exception as e:
                print(f"❌ TTS error for voice {self.default_voice}: {e}")
        return None

    async def generate_tts_stream_assistant(self, text, user_id, voice=None):
        """Generate TTS audio chunks for streaming in assistant mode.

        Args:
            text: Text to synthesize.
            user_id: User ID for logging.
            voice: Optional voice override; defaults to en-IN-AaravNeural.

        Yields:
            Dict with 'type', 'status', 'data' (base64-encoded audio), or 'error'.
        """
        if not text:
            yield {"type": "error", "message": "No text provided"}
            return

        # Clean text for speech (consistent with speak_text)
        text_for_speech = re.sub(r'http[s]?://[^\s]+', '', text).strip()
        if "Playing" in text_for_speech and "YouTube" in text_for_speech:
            text_for_speech = "I have played the YouTube video."
        elif "Flight from" in text_for_speech:
            text_for_speech = f"मैंने {text_for_speech} की जानकारी दे दी है।"
        elif "YouTube link:" in text and not text_for_speech:
            text_for_speech = "I have shared the YouTube link."
        elif "YouTube search:" in text and not text_for_speech:
            text_for_speech = "I have shared the YouTube search link."
        elif "Directions:" in text and not text_for_speech:
            text_for_speech = "I have shared the directions link."
        elif not text_for_speech:
            text_for_speech = "I have shared this."

        selected_voice = voice or self.default_voice
        print(f"[TTS-Assistant] Streaming for {user_id}: '{text_for_speech[:50]}...' with voice: {selected_voice}")

        try:
            communicate = edge_tts.Communicate(text_for_speech, voice=selected_voice)
            chunk_count = 0
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    # Encode as base64 for WebRTC/JSON transmission
                    audio_base64 = base64.b64encode(chunk["data"]).decode("utf-8")
                    yield {
                        "type": "audio",
                        "status": "ok",
                        "data": audio_base64,
                        "voice": selected_voice,
                        "chunk_id": f"{user_id}_{chunk_count}",
                        "chunk_size": len(chunk["data"])
                    }
                    chunk_count += 1
                elif chunk["type"] == "WordBoundary":
                    continue
            print(f"[TTS-Assistant] Successfully streamed {chunk_count} chunks with {selected_voice}")
            yield {"type": "complete", "voice": selected_voice}
        except Exception as e:
            error_msg = f"TTS generation failed with {selected_voice}: {str(e)}"
            print(f"❌ {error_msg}")
            yield {"type": "error", "message": error_msg}
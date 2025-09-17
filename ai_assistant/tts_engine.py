import io
import asyncio
import pygame
import edge_tts
import threading
import re

class TTSEngine:
    def __init__(self):
        self.speak_lock = threading.Lock()
        pygame.mixer.init(frequency=22050)
        self.tts_available = True
        print("✅ Edge-TTS ready")

    async def _edge_tts_speak(self, text):
        try:
            output = io.BytesIO()
            communicate = edge_tts.Communicate(text, voice="hi-IN-AaravNeural")
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
            print(f"❌ Edge-TTS failed: {e}")

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
                    communicate = edge_tts.Communicate(text_for_speech, voice="hi-IN-AaravNeural")
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
                print(f"❌ TTS error: {e}")
        return None

    async def generate_tts_stream(self, text, user_id, voice):
        """Generate TTS audio chunks for streaming."""
        if not text:
            yield {"type": "error", "message": "No text provided"}
            return
        try:
            communicate = edge_tts.Communicate(text, voice=voice)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield {"type": "audio", "status": "ok", "data": chunk["data"]}
                elif chunk["type"] == "WordBoundary":
                    continue  # Skip word boundaries
            yield {"type": "complete"}
        except Exception as e:
            yield {"type": "error", "message": f"TTS generation failed: {str(e)}"}
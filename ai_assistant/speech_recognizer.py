import speech_recognition as sr

class SpeechRecognizer:

    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 600
        # Using default microphone (sounddevice backend)
        try:
            self.microphone = sr.Microphone()  # sounddevice automatically used if PyAudio not installed
            self._calibrate_microphone()
        except Exception as e:
            print(f"⚠️ Microphone setup failed: {e}")
            self.microphone = None

    def _calibrate_microphone(self):
        if not self.microphone:
            print("❌ No microphone detected. Speech input disabled.")
            return
        print("🎤 Setting up microphone...")
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=3)
            print("✅ Microphone ready")
        except Exception as e:
            print(f"⚠️ Microphone calibration warning: {e}")

    def listen_for_voice(self):
        if not self.microphone:
            # Fallback to text input
            user_input = input("💬 Type a message: ").strip()
            return (user_input, "text") if user_input else ("quit", "quit")

        print("\n🎤 Listening...")
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=15)
            print("🔄 Processing speech...")
            return self.recognizer.recognize_google(audio).strip(), "voice"
        except sr.WaitTimeoutError:
            print("⏱️ No speech detected.")
        except sr.UnknownValueError:
            print("❓ Could not understand speech.")
        except sr.RequestError as e:
            print(f"❌ Speech API request failed: {e}")

        # fallback to manual input
        user_input = input("💬 Type a message or 'quit': ").strip()
        return (user_input, "text") if user_input else ("quit", "quit")


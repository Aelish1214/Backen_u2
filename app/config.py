import os
from dotenv import load_dotenv
from typing import List
import logging
import tempfile
import shutil

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class Config:
    def __init__(self, env_path: str = None):
        # Load environment
        self.env_path = env_path or os.path.join(os.getcwd(), ".env")
        load_dotenv(self.env_path, override=True)
        self.env_vars = os.environ

        # Load API keys
        self.api_keys: List[str] = self._load_api_keys()
        if not self.api_keys:
            raise ValueError("❌ No valid GROQ_API_KEY found in .env (comma-separated values supported)")

        # Groq API key preference
        self.groq_api_key = os.getenv("GROQ_API_KEY") or (self.api_keys[1] if len(self.api_keys) >= 2 else self.api_keys[0])

        # Voice configurations for different models
        self.voices = {
            "female1": "en-IN-NeerjaExpressiveNeural",  # Aria
            "female2": "en-US-JennyNeural",            # Luna
            "male":"en-IN-PrabhatNeural"                   # Alex
        }

        # Default voice
        self.assistant_voice = self.voices["female1"]

        # Voice mapping for different languages (info mode)
        self.voice_map = {
            "en": "en-US-AriaNeural",
            "hi": "hi-IN-SwaraNeural",
            "gu": "gu-IN-DhwaniNeural",
        }

        # Maintenance toggle and mode
        self.mode = self.get("ASSISTANT_MODE", "info")
        self.maintenance_password = self.get("TOGGLE_PASSWORD", "")
        self.toggle_key = self.get("TOGGLE_KEY", "off").lower()

        # Directories
        self.static_dir = os.path.join(os.getcwd(), "static")
        os.makedirs(self.static_dir, exist_ok=True)
        os.makedirs("Data", exist_ok=True)

        # Clean old temp files
        self.cleanup_temp_files()

        logging.info(f"🔐 Loaded API keys: {len(self.api_keys)}")
        logging.info(f"🧠 Using Groq Key: {self.groq_api_key[:30]}...")

    def _load_api_keys(self) -> List[str]:
        keys = self.get("GROQ_API_KEY", "")
        return [k.strip() for k in keys.split(",") if k.strip()]

    def cleanup_temp_files(self):
        try:
            for f in os.listdir("Data"):
                path = os.path.join("Data", f)
                if os.path.isfile(path) and f.lower().endswith(('.mp3', '.wav', '.aac')):
                    os.remove(path)
        except Exception as e:
            logging.warning(f"[Cleanup Error] {e}")

    def reload_env(self):
        load_dotenv(self.env_path, override=True)
        self.env_vars = os.environ
        self.toggle_key = self.get("TOGGLE_KEY", "off").lower()

    def is_maintenance_on(self) -> bool:
        return self.toggle_key == "on"

    def is_socket_on(self) -> bool:
        return self.toggle_key == "off"

    def toggle_state(self, password: str) -> bool:
        """Toggle maintenance mode using password"""
        self.reload_env()
        if password != self.maintenance_password:
            logging.warning("Incorrect toggle password.")
            return False
        new_state = "on" if self.toggle_key == "off" else "off"
        self._set_env_value("TOGGLE_KEY", new_state)
        self.reload_env()
        return True

    def get(self, key: str, default=None) -> str:
        return self.env_vars.get(key, default)

    def _set_env_value(self, key: str, value: str):
        if not os.path.exists(self.env_path):
            logging.error(f".env file not found at {self.env_path}")
            return

        with open(self.env_path, "r") as f:
            lines = f.readlines()

        key_found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                key_found = True
                break

        if not key_found:
            lines.append(f"{key}={value}\n")

        # Safe write using temp file
        with tempfile.NamedTemporaryFile("w", delete=False) as temp_file:
            temp_file.writelines(lines)
            temp_file.flush()
        shutil.move(temp_file.name, self.env_path)

    # ---- Voice Helper Methods ----
    def get_voice_for_model(self, model: str) -> str:
        """Get voice for specific model"""
        return self.voices.get(model, self.voices["female1"])

    def validate_config(self) -> bool:
        """Validate configuration"""
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required")
        return True

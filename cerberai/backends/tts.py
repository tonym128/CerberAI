import os
import io
import tempfile
import asyncio
from typing import Dict, Any
from .base import BaseBackend

class TTSBackend(BaseBackend):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        super().__init__(model_id, config, vram_estimate_gb)
        self.engine_type = config.get("engine", "pyttsx3").lower()
        self.voice = config.get("voice")
        self.rate = config.get("rate", 150)
        self.engine = None

    async def load(self) -> bool:
        """Initialize offline speech engine if pyttsx3 is selected."""
        if self.engine_type == "gtts":
            self._is_loaded = True
            return True
            
        if self.engine:
            self._is_loaded = True
            return True

        print(f"Initializing offline TTS engine (pyttsx3)...")
        try:
            import pyttsx3
            # Initialize inside the run loop context
            self.engine = pyttsx3.init()
            self.engine.setProperty("rate", self.rate)
            if self.voice:
                self.engine.setProperty("voice", self.voice)
            self._is_loaded = True
            return True
        except Exception as e:
            print(f"Failed to load pyttsx3 TTS engine: {e}")
            return False

    async def unload(self) -> bool:
        """Unload and clean up the TTS engine."""
        self.engine = None
        self._is_loaded = False
        return True

    async def handle_audio_speech(self, payload: Dict[str, Any]) -> bytes:
        """Synthesize text to speech bytes."""
        text = payload.get("input", "")
        if not text:
            raise ValueError("Input text is required for text-to-speech.")

        if self.engine_type == "gtts":
            # Cloud-based fallback
            from gtts import gTTS
            tts = gTTS(text=text, lang=payload.get("language", "en"))
            fp = io.BytesIO()
            tts.write_to_fp(fp)
            return fp.getvalue()
            
        # Offline synthesis using pyttsx3
        if not self.engine:
            await self.load()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_path = temp_file.name

        try:
            loop = asyncio.get_running_loop()
            
            def run_synthesis():
                self.engine.save_to_file(text, temp_path)
                self.engine.runAndWait()

            # Execute blocking synthesis in thread executor
            await loop.run_in_executor(None, run_synthesis)
            
            # Read output audio file
            with open(temp_path, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

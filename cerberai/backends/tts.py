import os
import io
import tempfile
import asyncio
from typing import Dict, Any
from .base import BaseBackend

class TTSBackend(BaseBackend):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        super().__init__(model_id, config, vram_estimate_gb)
        self.engine_type = config.get("engine", "kokoro").lower()
        self.voice = config.get("voice", "af_sarah")
        self.rate = config.get("rate", 150)
        
        self.engine = None
        self.kokoro = None
        self.model_path = None
        self.voices_path = None

    async def load(self, progress_callback=None) -> bool:
        """Initialize selected TTS engine (kokoro, pyttsx3 or gtts)."""
        if self.engine_type == "gtts":
            self._is_loaded = True
            return True
            
        if self.engine_type == "kokoro":
            if self.kokoro:
                self._is_loaded = True
                return True
                
            print("Initializing local SOTA TTS engine (Kokoro-82M ONNX)...")
            if progress_callback:
                progress_callback("[2/3] Checking Kokoro ONNX weights & voices...")
            try:
                from ..downloader import ensure_gguf_model
                
                # Auto-download Kokoro ONNX model and voices file from Hugging Face if missing
                self.model_path = await ensure_gguf_model("rumbleFTW/kokoro-v1.0-onnx", "kokoro-v1.0.onnx")
                self.voices_path = await ensure_gguf_model("rumbleFTW/kokoro-v1.0-onnx", "voices-v1.0.bin")
                
                if progress_callback:
                    progress_callback("[3/3] Initializing Kokoro ONNX model pipeline...")
                import numpy as np
                original_load = np.load
                np.load = lambda *args, **kwargs: original_load(*args, allow_pickle=True, **kwargs)
                
                try:
                    from kokoro_onnx import Kokoro
                    self.kokoro = Kokoro(self.model_path, self.voices_path)
                finally:
                    np.load = original_load
                    
                self._is_loaded = True
                return True

            except Exception as e:
                print(f"Warning: Failed to load Kokoro TTS engine ({e}). Falling back to pyttsx3.")
                self.engine_type = "pyttsx3"
                # Fall through to pyttsx3 load

        if self.engine_type == "pyttsx3":
            if self.engine:
                self._is_loaded = True
                return True
                
            print(f"Initializing offline TTS engine (pyttsx3)...")
            if progress_callback:
                progress_callback("[2/3] Initializing offline system voice (pyttsx3)...")
            try:
                import pyttsx3
                self.engine = pyttsx3.init()
                self.engine.setProperty("rate", self.rate)
                if self.voice and self.voice != "af_sarah": # Sarah is a Kokoro voice
                    self.engine.setProperty("voice", self.voice)
                self._is_loaded = True
                return True
            except Exception as e:
                print(f"Warning: Failed to load pyttsx3 TTS engine ({e}).")
                print("To run TTS completely offline without Kokoro, please install the 'espeak' system library:")
                print("  - Ubuntu/Debian:  sudo apt-get install espeak")
                print("  - Fedora/CentOS:  sudo dnf install espeak-ng")
                print("  - macOS (Brew):   brew install espeak")
                print("Falling back to gTTS (online) in the meantime.")
                self.engine_type = "gtts"
                self._is_loaded = True
                return True

    async def unload(self) -> bool:
        """Unload models and release memory."""
        self.engine = None
        self.kokoro = None
        self._is_loaded = False
        return True

    async def handle_audio_speech(self, payload: Dict[str, Any]) -> bytes:
        """Synthesize text to speech bytes using Kokoro, pyttsx3, or gTTS."""
        async with self.lock:
            text = payload.get("input", "")
            if not text:
                raise ValueError("Input text is required for text-to-speech.")
    
            # Ensure correct engine is loaded
            if self.engine_type == "kokoro" and not self.kokoro:
                await self.load()
            elif self.engine_type == "pyttsx3" and not self.engine:
                await self.load()
    
            # 1. Kokoro Local SOTA TTS
            if self.engine_type == "kokoro" and self.kokoro:
                try:
                    voice = payload.get("voice", self.voice)
                    # Sarah is default, but bella or sarah are excellent female voices
                    if voice == "alloy" or voice == "echo":
                        voice = "af_sarah" # Map OpenAI voices to Kokoro
                        
                    print(f"Synthesizing text using Kokoro ONNX (voice: {voice})...")
                    
                    # Create audio samples
                    loop = asyncio.get_running_loop()
                    samples, sample_rate = await loop.run_in_executor(
                        None,
                        lambda: self.kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
                    )
                    
                    # Write to WAV bytes in memory
                    import soundfile as sf
                    fp = io.BytesIO()
                    sf.write(fp, samples, sample_rate, format='WAV')
                    return fp.getvalue()
                except Exception as e:
                    print(f"Warning: Kokoro synthesis failed ({e}). Falling back to gTTS (online).")
                    self.engine_type = "gtts"
                    # Fall through to gTTS
    
            # 2. gTTS Online Fallback
            if self.engine_type == "gtts":
                from gtts import gTTS
                tts = gTTS(text=text, lang=payload.get("language", "en"))
                fp = io.BytesIO()
                tts.write_to_fp(fp)
                return fp.getvalue()
    
            # 3. Offline synthesis using pyttsx3
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
                temp_path = temp_file.name
    
            try:
                loop = asyncio.get_running_loop()
                
                def run_synthesis():
                    self.engine.save_to_file(text, temp_path)
                    self.engine.runAndWait()
    
                await loop.run_in_executor(None, run_synthesis)
                
                with open(temp_path, "rb") as f:
                    return f.read()
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

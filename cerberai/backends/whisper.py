import os
import tempfile
from typing import Dict, Any
from .base import BaseBackend

class WhisperBackend(BaseBackend):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        super().__init__(model_id, config, vram_estimate_gb)
        self.model_name = config.get("model_name", "tiny")
        self.model = None

    async def load(self, progress_callback=None) -> bool:
        """Dynamically load the Whisper model into memory."""
        if self.model:
            self._is_loaded = True
            return True
            
        print(f"Loading Whisper model '{self.model_name}'...")
        try:
            import whisper
            # whisper.load_model automatically downloads model weights if missing
            self.model = whisper.load_model(self.model_name)
            self._is_loaded = True
            return True
        except Exception as e:
            print(f"Failed to load Whisper model: {e}")
            return False

    async def unload(self) -> bool:
        """Unload the model and free memory."""
        if not self.model:
            self._is_loaded = False
            return True
            
        print(f"Unloading Whisper model '{self.model_name}'...")
        self.model = None
        self._is_loaded = False
        
        # Clean up cache
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
            
        return True

    async def handle_audio_transcription(self, file_bytes: bytes, filename: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Save upload bytes to temp file, transcribe, and clean up."""
        async with self.lock:
            if not self.model:
                await self.load()
                
            # Get temp file suffix
            suffix = os.path.splitext(filename)[1] if filename else ".wav"
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(file_bytes)
                temp_path = temp_file.name
    
            try:
                # Run inference (blocking call, so run in executor to prevent freezing loop)
                import asyncio
                loop = asyncio.get_running_loop()
                
                # Options
                temperature = payload.get("temperature", 0.0)
                language = payload.get("language")
                
                options = {}
                if language:
                    options["language"] = language
                    
                print(f"Transcribing audio file {filename}...")
                result = await loop.run_in_executor(
                    None,
                    lambda: self.model.transcribe(temp_path, temperature=temperature, **options)
                )
                return {"text": result.get("text", "").strip()}
            finally:
                # Clean up temp file
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

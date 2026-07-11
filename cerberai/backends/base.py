from abc import ABC, abstractmethod
from typing import Dict, Any, AsyncIterator, Optional
import asyncio
import time

class BaseBackend(ABC):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        self.model_id = model_id
        self.config = config
        self.vram_estimate_gb = vram_estimate_gb
        self._is_loaded = False
        self.lock = asyncio.Lock()
        
        # Diagnostics
        self.load_time_seconds = 0.0
        self.last_active_timestamp = 0.0
        self.calls_count = 0
        self.last_error = None

    @abstractmethod
    async def load(self, progress_callback=None) -> bool:
        """Load the model into RAM/VRAM or start the subprocess server."""
        pass

    @abstractmethod
    async def unload(self) -> bool:
        """Unload the model from RAM/VRAM or stop the subprocess server."""
        pass

    async def is_loaded(self) -> bool:
        """Check if the model is currently active/loaded."""
        return self._is_loaded

    def get_diagnostics(self) -> Dict[str, Any]:
        """Retrieve diagnostics statistics for this model backend."""
        return {
            "model_id": self.model_id,
            "vram_estimate_gb": self.vram_estimate_gb,
            "is_loaded": self._is_loaded,
            "load_time_seconds": self.load_time_seconds,
            "last_active_timestamp": self.last_active_timestamp,
            "calls_count": self.calls_count,
            "last_error": self.last_error
        }

    # Endpoint handlers (backends implement the ones they support)
    async def handle_chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("This backend does not support chat completions.")

    async def stream_chat_completion(self, payload: Dict[str, Any]) -> AsyncIterator[bytes]:
        raise NotImplementedError("This backend does not support streaming chat completions.")
        yield b""

    async def handle_image_generation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("This backend does not support image generation.")

    async def handle_audio_speech(self, payload: Dict[str, Any]) -> bytes:
        raise NotImplementedError("This backend does not support text-to-speech.")

    async def handle_audio_transcription(self, file_bytes: bytes, filename: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("This backend does not support speech-to-text.")

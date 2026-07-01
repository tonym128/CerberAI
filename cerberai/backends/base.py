from abc import ABC, abstractmethod
from typing import Dict, Any, AsyncIterator

class BaseBackend(ABC):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        self.model_id = model_id
        self.config = config
        self.vram_estimate_gb = vram_estimate_gb
        self._is_loaded = False

    @abstractmethod
    async def load(self) -> bool:
        """Load the model into RAM/VRAM or start the subprocess server."""
        pass

    @abstractmethod
    async def unload(self) -> bool:
        """Unload the model from RAM/VRAM or stop the subprocess server."""
        pass

    async def is_loaded(self) -> bool:
        """Check if the model is currently active/loaded."""
        return self._is_loaded

    # Endpoint handlers (backends implement the ones they support)
    async def handle_chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("This backend does not support chat completions.")

    async def stream_chat_completion(self, payload: Dict[str, Any]) -> AsyncIterator[bytes]:
        raise NotImplementedError("This backend does not support streaming chat completions.")
        # Make it an async generator so python doesn't throw a syntax error on instantiation
        yield b""

    async def handle_image_generation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("This backend does not support image generation.")

    async def handle_audio_speech(self, payload: Dict[str, Any]) -> bytes:
        raise NotImplementedError("This backend does not support text-to-speech.")

    async def handle_audio_transcription(self, file_bytes: bytes, filename: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("This backend does not support speech-to-text.")


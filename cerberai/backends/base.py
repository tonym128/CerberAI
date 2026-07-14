from abc import ABC, abstractmethod
from typing import Dict, Any, AsyncIterator, Optional
import asyncio
import time
import inspect

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
        
        # Dynamically wrap subclass methods for automatic diagnostics tracking
        self._wrap_load()
        self._wrap_endpoints()

    def _wrap_load(self):
        if hasattr(self, "_load_wrapped"):
            return
        self._load_wrapped = True
        
        orig_load = self.load
        async def load_diagnostics_wrapper(progress_callback=None) -> bool:
            import time
            start_time = time.time()
            try:
                success = await orig_load(progress_callback)
                self._is_loaded = success
                if success:
                    self.load_time_seconds = time.time() - start_time
                    self.last_active_timestamp = time.time()
                return success
            except Exception as e:
                self.last_error = str(e)
                self._is_loaded = False
                return False
        self.load = load_diagnostics_wrapper

    def _wrap_endpoints(self):
        for name in ["handle_chat_completion", "stream_chat_completion", "handle_image_generation", "handle_audio_speech", "handle_audio_transcription", "handle_video_generation"]:
            method = getattr(self, name, None)
            if method:
                func = getattr(method, "__func__", None)
                base_func = getattr(getattr(BaseBackend, name), "__func__", None)
                if func and base_func and func is not base_func:
                    setattr(self, name, self._make_diagnostic_wrapper(method))

    def _make_diagnostic_wrapper(self, method):
        import time
        
        if inspect.isasyncgenfunction(method):
            async def async_generator_wrapper(*args, **kwargs):
                self.calls_count += 1
                self.last_active_timestamp = time.time()
                try:
                    async for chunk in method(*args, **kwargs):
                        yield chunk
                except Exception as e:
                    self.last_error = str(e)
                    raise
            return async_generator_wrapper
        else:
            async def async_wrapper(*args, **kwargs):
                self.calls_count += 1
                self.last_active_timestamp = time.time()
                try:
                    return await method(*args, **kwargs)
                except Exception as e:
                    self.last_error = str(e)
                    raise
            return async_wrapper

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

    @property
    def actual_model_name(self) -> str:
        """Return the actual model file/name/repo identifier."""
        return self.config.get("filename", self.config.get("model_name", self.config.get("repo_id", self.model_id)))

    def get_diagnostics(self) -> Dict[str, Any]:
        """Retrieve diagnostics statistics for this model backend."""
        return {
            "model_id": self.model_id,
            "vram_estimate_gb": self.vram_estimate_gb,
            "is_loaded": self._is_loaded,
            "load_time_seconds": round(self.load_time_seconds, 2),
            "last_active_timestamp": round(self.last_active_timestamp, 2) if self.last_active_timestamp else 0.0,
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

    async def handle_video_generation(self, payload: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
        raise NotImplementedError("This backend does not support video generation.")

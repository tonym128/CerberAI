import asyncio
import time
from typing import Dict, List, Optional
from .config import AppConfig, ModelConfig
from .backends.base import BaseBackend
from .backends.ollama import OllamaBackend
from .backends.llamacpp import LlamaCppBackend
from .backends.whisper import WhisperBackend
from .backends.tts import TTSBackend
from .backends.diffusers import DiffusersBackend

class DynamicModelManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.backends: Dict[str, BaseBackend] = {}
        self.last_used: Dict[str, float] = {}
        self.lock = asyncio.Lock()
        
        # Initialize backends based on config
        for m_cfg in config.models:
            backend_instance = self._create_backend(m_cfg)
            if backend_instance:
                self.backends[m_cfg.id] = backend_instance

    def _create_backend(self, model_cfg: ModelConfig) -> Optional[BaseBackend]:
        b_type = model_cfg.backend.lower()
        if b_type == "ollama":
            return OllamaBackend(model_cfg.id, model_cfg.backend_config, model_cfg.vram_estimate_gb)
        elif b_type == "llama.cpp" or b_type == "llamacpp":
            return LlamaCppBackend(model_cfg.id, model_cfg.backend_config, model_cfg.vram_estimate_gb)
        elif b_type == "whisper":
            return WhisperBackend(model_cfg.id, model_cfg.backend_config, model_cfg.vram_estimate_gb)
        elif b_type == "tts":
            return TTSBackend(model_cfg.id, model_cfg.backend_config, model_cfg.vram_estimate_gb)
        elif b_type == "diffusers":
            return DiffusersBackend(model_cfg.id, model_cfg.backend_config, model_cfg.vram_estimate_gb)
        else:
            print(f"Warning: Backend '{model_cfg.backend}' for model '{model_cfg.id}' is not implemented yet.")
            # We can create a dummy backend or return None for now
            return None


    async def get_model(self, model_id: str) -> BaseBackend:
        """
        Retrieve a model backend, loading it if not already active.
        Triggers eviction of other models if resource limits are exceeded.
        """
        async with self.lock:
            if model_id not in self.backends:
                raise ValueError(f"Model ID '{model_id}' is not configured.")

            backend = self.backends[model_id]
            
            # Check if it's already loaded (update status)
            is_loaded = await backend.is_loaded()
            
            if not is_loaded:
                # Ensure resources are available
                await self._ensure_resources_for(model_id)
                
                # Load the model
                print(f"Loading model '{model_id}'...")
                success = await backend.load()
                if not success:
                    raise RuntimeError(f"Failed to load model '{model_id}'")
                print(f"Successfully loaded model '{model_id}'")
            
            # Update last used timestamp
            self.last_used[model_id] = time.time()
            return backend

    async def _ensure_resources_for(self, target_model_id: str):
        """
        Evict active models if loading the target model exceeds configured VRAM limits.
        Uses static VRAM estimation from config for cross-platform robustness.
        """
        target_cfg = next(m for m in self.config.models if m.id == target_model_id)
        target_vram = target_cfg.vram_estimate_gb
        max_vram = self.config.resource_limits.max_vram_gb

        # If a single model exceeds total VRAM, we'll try to load it anyway but log a warning
        if target_vram > max_vram:
            print(f"Warning: Model '{target_model_id}' requires {target_vram}GB, which exceeds max VRAM of {max_vram}GB.")

        while True:
            # Calculate current VRAM usage of loaded models (excluding the target model itself)
            loaded_models: List[str] = []
            current_vram = 0.0
            for m_id, b in self.backends.items():
                if m_id != target_model_id and await b.is_loaded():
                    loaded_models.append(m_id)
                    # Find model config to get estimate
                    cfg = next(m for m in self.config.models if m.id == m_id)
                    current_vram += cfg.vram_estimate_gb

            # If fits, break
            if current_vram + target_vram <= max_vram or not loaded_models:
                break

            # Need to evict one model
            # Find the least recently used model among the loaded ones
            lru_model = min(loaded_models, key=lambda m: self.last_used.get(m, 0.0))
            print(f"Evicting model '{lru_model}' to free VRAM for '{target_model_id}'...")
            
            lru_backend = self.backends[lru_model]
            await lru_backend.unload()
            if lru_model in self.last_used:
                del self.last_used[lru_model]

    async def unload_idle_models(self):
        """Periodically runs to unload models that haven't been used within the keep-alive timeout."""
        timeout = self.config.server.timeout_keep_alive
        
        # Don't hold lock for the entire sleep/poll loop
        for m_id, backend in list(self.backends.items()):
            if await backend.is_loaded():
                last_active = self.last_used.get(m_id, 0.0)
                idle_duration = time.time() - last_active
                
                # If idle longer than timeout, unload it
                if idle_duration > timeout:
                    print(f"Model '{m_id}' has been idle for {idle_duration:.1f}s. Unloading...")
                    async with self.lock:
                        await backend.unload()
                        if m_id in self.last_used:
                            del self.last_used[m_id]

    async def unload_all(self):
        """Unload all active model backends."""
        async with self.lock:
            for m_id, backend in list(self.backends.items()):
                if await backend.is_loaded():
                    await backend.unload()
            self.last_used.clear()

    async def start_cleanup_loop(self):
        """Start background loop for idle unloading."""
        while True:
            try:
                await asyncio.sleep(15.0) # Check every 15 seconds
                await self.unload_idle_models()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in cleanup loop: {e}")

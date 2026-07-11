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
from .backends.video import VideoBackend

class DynamicModelManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.backends: Dict[str, BaseBackend] = {}
        self.last_used: Dict[str, float] = {}
        self.loading_status: Dict[str, Dict[str, Any]] = {}
        self.lock = asyncio.Lock()
        
        # Initialize backends based on config
        for m_cfg in config.models:
            backend_instance = self._create_backend(m_cfg)
            if backend_instance:
                self.backends[m_cfg.id] = backend_instance

    def _create_backend(self, model_cfg: ModelConfig) -> Optional[BaseBackend]:
        b_type = model_cfg.backend.lower()
        backend_config = dict(model_cfg.backend_config)

        # Calculate context size (n_ctx / ctx_size) for LLMs and vision models
        if model_cfg.type in ("llm", "vision"):
            max_vram = self.config.resource_limits.max_vram_gb
            model_vram = model_cfg.vram_estimate_gb
            
            # Auto-calculate if not explicitly provided or 0
            if getattr(model_cfg, "n_ctx", None) is not None and model_cfg.n_ctx > 0:
                ctx_size = model_cfg.n_ctx
            else:
                # Heuristic estimation:
                available_vram = max_vram - model_vram
                if available_vram <= 0.5:
                    ctx_size = 2048
                else:
                    # Parameter size estimate: weights VRAM * 1.5 (e.g. 5GB ≈ 8B parameters)
                    model_size = max(1.0, model_vram * 1.5)
                    # FP16 KV cache memory: ~0.12 GB VRAM per 1024 tokens for an 8B model
                    gb_per_1024 = model_size * 0.015
                    estimated_tokens = (available_vram / gb_per_1024) * 1024
                    
                    # Round to the nearest standard context window step (power of 2)
                    ctx_size = 2048
                    for size in [32768, 16384, 8192, 4096]:
                        if estimated_tokens >= size:
                            ctx_size = size
                            break
            
            # Pass n_ctx down as both n_ctx and ctx_size to support various backend formats
            backend_config["ctx_size"] = ctx_size
            backend_config["n_ctx"] = ctx_size
            
            # Save the calculated n_ctx back to model_cfg so that status displays the correct limit
            model_cfg.n_ctx = ctx_size

        if b_type == "ollama":
            return OllamaBackend(model_cfg.id, backend_config, model_cfg.vram_estimate_gb)
        elif b_type == "llama.cpp" or b_type == "llamacpp":
            return LlamaCppBackend(model_cfg.id, backend_config, model_cfg.vram_estimate_gb)
        elif b_type == "whisper":
            max_vram = self.config.resource_limits.max_vram_gb
            if backend_config.get("model_name") == "auto":
                if max_vram <= 4.0:
                    backend_config["model_name"] = "tiny"
                    model_cfg.vram_estimate_gb = 0.5
                elif max_vram <= 6.0:
                    backend_config["model_name"] = "base"
                    model_cfg.vram_estimate_gb = 0.7
                elif max_vram <= 8.0:
                    backend_config["model_name"] = "small"
                    model_cfg.vram_estimate_gb = 1.5
                elif max_vram <= 12.0:
                    backend_config["model_name"] = "medium"
                    model_cfg.vram_estimate_gb = 4.0
                else:
                    backend_config["model_name"] = "large-v3"
                    model_cfg.vram_estimate_gb = 4.8
            return WhisperBackend(model_cfg.id, backend_config, model_cfg.vram_estimate_gb)
        elif b_type == "tts":
            return TTSBackend(model_cfg.id, backend_config, model_cfg.vram_estimate_gb)
        elif b_type == "diffusers":
            return DiffusersBackend(model_cfg.id, backend_config, model_cfg.vram_estimate_gb)
        elif b_type == "video":
            return VideoBackend(model_cfg.id, backend_config, model_cfg.vram_estimate_gb)
        else:
            print(f"Warning: Backend '{model_cfg.backend}' for model '{model_cfg.id}' is not implemented yet.")
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
            is_loaded = await backend.is_loaded()
            
            if not is_loaded:
                # 1/3: Eviction Stage
                self.loading_status[model_id] = {
                    "status": "evicting",
                    "progress": None,
                    "message": "[1/3] Evicting inactive models from VRAM..."
                }
                await self._ensure_resources_for(model_id)
                
                # 2/3: Loading / Initializing Stage
                self.loading_status[model_id] = {
                    "status": "loading",
                    "progress": None,
                    "message": "[2/3] Allocating VRAM & initializing engine..."
                }
                
                def progress_callback(val):
                    if isinstance(val, (int, float)):
                        self.loading_status[model_id] = {
                            "status": "downloading",
                            "progress": round(val, 1),
                            "message": f"[2/3] Downloading model checkpoints... {val:.1f}%"
                        }
                    elif isinstance(val, str):
                        self.loading_status[model_id] = {
                            "status": "loading",
                            "progress": None,
                            "message": val
                        }
                
                # Load the model
                print(f"Loading model '{model_id}'...")
                try:
                    success = await backend.load(progress_callback=progress_callback)
                    if not success:
                        raise RuntimeError(f"Failed to load model '{model_id}'")
                    print(f"Successfully loaded model '{model_id}'")
                finally:
                    self.loading_status.pop(model_id, None)
            
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
        # Deduct a standard system/desktop/runtime overhead buffer
        # (Drivers, display servers, and framework overhead take about 1.5-2.0 GB of VRAM)
        limit_gb = self.config.resource_limits.max_vram_gb
        buffer_gb = 2.0 if limit_gb >= 8.0 else 1.0
        max_vram = max(limit_gb - buffer_gb, limit_gb * 0.7)

        # If a single model exceeds total VRAM, we'll try to load it anyway but log a warning
        if target_vram > max_vram:
            print(f"Warning: Model '{target_model_id}' requires {target_vram}GB, which exceeds effective max VRAM of {max_vram:.1f}GB (with system overhead buffer).")

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
                if m_id not in self.last_used:
                    self.last_used[m_id] = time.time()
                last_active = self.last_used[m_id]
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

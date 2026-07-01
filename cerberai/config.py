import os
import yaml
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    timeout_keep_alive: int = 300

class ResourceLimits(BaseModel):
    max_vram_gb: float = 12.0
    max_ram_gb: float = 16.0
    eviction_strategy: str = "lru"

class RouterConfig(BaseModel):
    model_type: str = "heuristics" # 'llm' or 'heuristics'
    model_name: Optional[str] = None
    fallback_model: str

class ModelConfig(BaseModel):
    id: str
    type: str  # 'llm', 'image', 'tts', 'stt', 'video'
    backend: str  # 'ollama', 'llama.cpp', 'diffusers', 'whisper', etc.
    backend_config: Dict[str, Any] = Field(default_factory=dict)
    vram_estimate_gb: float = 0.0
    purpose: Optional[str] = None

class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    router: RouterConfig
    models: List[ModelConfig] = Field(default_factory=list)

def load_config(config_path: str = "config.yaml") -> AppConfig:
    if not os.path.exists(config_path):
        # Return a fallback config if file doesn't exist
        return AppConfig(
            router=RouterConfig(fallback_model="general-llama3"),
            models=[
                ModelConfig(
                    id="general-llama3",
                    type="llm",
                    backend="ollama",
                    backend_config={"model_name": "llama3"},
                    vram_estimate_gb=6.0
                )
            ]
        )
    
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    
    return AppConfig(**data)

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
    type: str  # 'llm', 'image', 'vision', 'tts', 'stt', 'video'
    backend: str  # 'ollama', 'llama.cpp', 'diffusers', 'whisper', etc.
    backend_config: Dict[str, Any] = Field(default_factory=dict)
    vram_estimate_gb: float = 0.0
    purpose: Optional[str] = None
    n_ctx: Optional[int] = None
    mmproj_repo_id: Optional[str] = None
    mmproj_filename: Optional[str] = None

class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    router: RouterConfig
    models: List[ModelConfig] = Field(default_factory=list)
    hf_token: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

def load_config(config_path: str = "config.yaml") -> AppConfig:
    if not os.path.exists(config_path):
        if config_path == "config.yaml":
            # Create and write a rich default config.yaml
            default_config = {
                "hf_token": None,
                "models": [
                    {
                        "id": "general-llama3",
                        "type": "llm",
                        "backend": "llama.cpp",
                        "backend_config": {
                            "filename": "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
                            "n_gpu_layers": 99,
                            "port": 8081,
                            "repo_id": "bartowski/Qwen2.5-14B-Instruct-GGUF"
                        },
                        "vram_estimate_gb": 9.5,
                        "purpose": "general reasoning"
                    },
                    {
                        "id": "coding-qwen",
                        "type": "llm",
                        "backend": "llama.cpp",
                        "backend_config": {
                            "filename": "qwen2.5-coder-14b-instruct-q4_k_m.gguf",
                            "n_gpu_layers": 99,
                            "port": 8082,
                            "repo_id": "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF"
                        },
                        "vram_estimate_gb": 9.5,
                        "purpose": "general coding"
                    },
                    {
                        "id": "stt-whisper",
                        "type": "stt",
                        "backend": "whisper",
                        "backend_config": {
                            "model_name": "auto"
                        },
                        "vram_estimate_gb": 4.0
                    },
                    {
                        "id": "tts-offline",
                        "type": "tts",
                        "backend": "tts",
                        "backend_config": {
                            "engine": "kokoro",
                            "voice": "af_sarah"
                        },
                        "vram_estimate_gb": 0.5
                    },
                    {
                        "id": "image-lcm",
                        "type": "image",
                        "backend": "diffusers",
                        "backend_config": {
                            "model_name": "stabilityai/sdxl-turbo"
                        },
                        "vram_estimate_gb": 5.5
                    },
                    {
                        "id": "vision-qwen",
                        "type": "vision",
                        "backend": "llama.cpp",
                        "backend_config": {
                            "filename": "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
                            "mmproj_filename": "mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf",
                            "mmproj_repo_id": "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF",
                            "n_gpu_layers": 99,
                            "port": 8084,
                            "repo_id": "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF"
                        },
                        "vram_estimate_gb": 3.5,
                        "purpose": "image-to-text vision analysis"
                    },
                    {
                        "id": "routing-phi",
                        "type": "llm",
                        "backend": "llama.cpp",
                        "backend_config": {
                            "filename": "Phi-3-mini-4k-instruct-q4.gguf",
                            "n_gpu_layers": 99,
                            "port": 8083,
                            "repo_id": "microsoft/Phi-3-mini-4k-instruct-gguf"
                        },
                        "vram_estimate_gb": 2.2,
                        "n_ctx": 4096,
                        "purpose": "routing classification"
                    },
                    {
                        "id": "video-generation",
                        "type": "video",
                        "backend": "video",
                        "backend_config": {
                            "model_name": "THUDM/CogVideoX-2b"
                        },
                        "vram_estimate_gb": 8.0,
                        "purpose": "text-to-video scene generation"
                    }
                ],
                "resource_limits": {
                    "max_vram_gb": 12.0,
                    "max_ram_gb": 16.0,
                    "eviction_strategy": "lru"
                },
                "router": {
                    "fallback_model": "general-llama3",
                    "model_name": "routing-phi",
                    "model_type": "llm"
                },
                "server": {
                    "host": "127.0.0.1",
                    "port": 8000,
                    "timeout_keep_alive": 300
                },
                "telegram_bot_token": None,
                "telegram_chat_id": None
            }
            try:
                with open(config_path, "w") as f:
                    yaml.safe_dump(default_config, f, default_flow_style=False)
                print(f"Created default configuration file at '{config_path}'")
            except Exception as ex:
                print(f"Warning: Could not write default configuration to disk: {ex}")
        else:
            # Fallback for tests/other custom config paths
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

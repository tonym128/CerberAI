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

class SearchConfig(BaseModel):
    provider: str = "duckduckgo" # options: duckduckgo, searxng, tavily, google
    searxng_url: Optional[str] = ""
    tavily_api_key: Optional[str] = ""
    google_api_key: Optional[str] = ""
    google_cse_id: Optional[str] = ""

class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    router: RouterConfig
    models: List[ModelConfig] = Field(default_factory=list)
    search: SearchConfig = Field(default_factory=SearchConfig)
    hf_token: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    mcp_servers: Dict[str, Any] = Field(default_factory=dict)

def load_config(config_path: str = "config.yaml") -> AppConfig:
    # Safely define the fallback defaults dict
    default_config = {
        "hf_token": None,
        "models": [
            {
                "id": "general",
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
                "id": "coding",
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
                "id": "stt",
                "type": "stt",
                "backend": "whisper",
                "backend_config": {
                    "model_name": "auto"
                },
                "vram_estimate_gb": 4.0
            },
            {
                "id": "tts",
                "type": "tts",
                "backend": "tts",
                "backend_config": {
                    "engine": "kokoro",
                    "voice": "af_sarah"
                },
                "vram_estimate_gb": 0.5
            },
            {
                "id": "image",
                "type": "image",
                "backend": "diffusers",
                "backend_config": {
                    "model_name": "stabilityai/sdxl-turbo"
                },
                "vram_estimate_gb": 5.5
            },
            {
                "id": "vision",
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
                "id": "routing",
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
                "id": "video",
                "type": "video",
                "backend": "comfyui",
                "backend_config": {
                    "server_url": "http://127.0.0.1:8188",
                    "workflow_path": "workflows/default_t2v.json"
                },
                "vram_estimate_gb": 0.0,
                "purpose": "text-to-video scene generation via ComfyUI"
            }
        ],
        "resource_limits": {
            "max_vram_gb": 12.0,
            "max_ram_gb": 16.0,
            "eviction_strategy": "lru"
        },
        "router": {
            "fallback_model": "general",
            "model_name": "routing",
            "model_type": "llm"
        },
        "search": {
            "provider": "duckduckgo",
            "searxng_url": "",
            "tavily_api_key": "",
            "google_api_key": "",
            "google_cse_id": ""
        },
        "server": {
            "host": "127.0.0.1",
            "port": 8000,
            "timeout_keep_alive": 300
        },
        "telegram_bot_token": None,
        "telegram_chat_id": None,
        "mcp_servers": {}
    }

    if not os.path.exists(config_path):
        if config_path == "config.yaml":
            try:
                with open(config_path, "w") as f:
                    yaml.safe_dump(default_config, f, default_flow_style=False)
                print(f"Created default configuration file at '{config_path}'")
            except Exception as ex:
                print(f"Warning: Could not write default configuration to disk: {ex}")
        else:
            return AppConfig(**default_config)

    try:
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            
        # Merge key structures to avoid validation crashes on older YAML missing new sections
        if "search" not in data:
            data["search"] = default_config["search"]
            
        return AppConfig(**data)
    except Exception as e:
        print(f"⚠️ [WARNING] Failed to load/validate configuration '{config_path}': {e}")
        print("💡 [INFO] Falling back to safe default configuration to prevent gateway boot crash-loops.")
        return AppConfig(**default_config)

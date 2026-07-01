# CerberAI

CerberAI is an OpenAI-compatible API server designed to optimize local LLM, TTS, STT, and Image/Video generation model resource consumption. It intercepts incoming requests, routes them to specific specialized models using a local router LLM or heuristic classification, and dynamically loads and unloads models in VRAM/RAM on demand.

## Features

- **OpenAI-Compatible Endpoints**: Use with any tool that supports OpenAI's API (e.g. Open WebUI, LibreChat, Cursor, Cline).
- **Dynamic Resource Loading/Unloading**: Keeps memory footprint low by loading models on-demand and unloading them when idle or to make room for other models.
- **Intelligent Routing**: Uses a lightweight router model or heuristics to analyze incoming requests and direct them to the appropriate model (e.g., General, Coding, Image, TTS, STT).
- **Multiple Backends**: Integrates with Ollama, llama.cpp, Whisper, Diffusers, Kokoro, and others.

## Directory Structure

```text
cerberai/
├── cerberai/
│   ├── __init__.py
│   ├── main.py          # FastAPI application
│   ├── config.py        # Configuration management
│   ├── manager.py       # Dynamic Model Manager (DMM)
│   ├── router.py        # Intent Router (Classifier/LLM)
│   ├── automation.py    # Automation pipelines (e.g., News Video Generator)
│   └── backends/        # Adapters for various execution backends
│       ├── __init__.py
│       ├── base.py      # Base backend adapter
│       ├── llamacpp.py  # llama.cpp server subprocess manager
│       ├── ollama.py    # Ollama integration
│       ├── whisper.py   # Local OpenAI-Whisper STT
│       ├── tts.py       # Local SOTA Kokoro / Pyttsx3 / gTTS
│       └── diffusers.py # Diffusers LCM pipelines
├── config.yaml          # Configuration file
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Configure your models in `config.yaml`.
3. To run TTS completely offline, install the system text-to-speech engine:
   ```bash
   # Ubuntu / Debian
   sudo apt-get install espeak -y
   ```
4. Run the server:
   ```bash
   python -m cerberai.main
   ```

---

## Hardware & Model Recommendations (VRAM Tiers)

Below are the recommended models for different VRAM tiers. To ensure optimal performance on these configurations, set `max_vram_gb` in your `config.yaml` to match your system capacity. The Dynamic Model Manager (DMM) will automatically evict models and keep your footprint within your hardware boundaries.

### 1. 4 GB VRAM Tier (Ultra-Lightweight / CPU-Assisted)
Designed for low-end GPUs or laptops. Leverages heavily quantized models and CPU assistance for audio and image generation.
*   **General LLM**: `Qwen/Qwen2.5-1.5B-Instruct-GGUF` (File: `qwen2.5-1.5b-instruct-q4_k_m.gguf` ~ 1.2 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF` (File: `qwen2.5-coder-1.5b-instruct-q4_k_m.gguf` ~ 1.2 GB VRAM)
*   **Image Generation**: `Lykon/dreamshaper-8-lcm` (CPU mode, or 4-step generation, ~4.0 GB VRAM peak)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (CPU execution, ~0.3 GB RAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `tiny` ~ 0.5 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 4.0` in `config.yaml`.

### 2. 6 GB VRAM Tier (Medium Budget)
The sweet-spot for budget gaming laptops or older desktop cards (e.g., RTX 2060/3050).
*   **General LLM**: `Qwen/Qwen2.5-3B-Instruct-GGUF` (File: `qwen2.5-3b-instruct-q4_k_m.gguf` ~ 2.2 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-3B-Instruct-GGUF` (File: `qwen2.5-coder-3b-instruct-q4_k_m.gguf` ~ 2.2 GB VRAM)
*   **Image Generation**: `Lykon/dreamshaper-8-lcm` (Offloaded to GPU, ~4.0 GB VRAM)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (CPU execution, ~0.3 GB RAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `base` ~ 0.7 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 6.0` in `config.yaml`.

### 3. 8 GB VRAM Tier (Standard Desktop)
Perfect for standard mainstream cards (e.g., RTX 3060/4060, RX 6600/7600).
*   **General LLM**: `QuantFactory/Meta-Llama-3.1-8B-Instruct-GGUF` (File: `Meta-Llama-3.1-8B-Instruct.Q4_K_M.gguf` ~ 4.8 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF` (File: `qwen2.5-coder-7b-instruct-q4_k_m.gguf` ~ 4.7 GB VRAM)
*   **Image Generation**: `Lykon/dreamshaper-8-lcm` (Fits completely in VRAM ~ 4.0 GB)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (GPU execution, ~0.3 GB VRAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `small` ~ 1.5 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 8.0` in `config.yaml`.

### 4. 16 GB VRAM Tier (Enthusiast / Pro Creator)
For high-end workstation cards (e.g., RTX 4080, RX 7800 XT, or dual-GPU setups). Allows loading larger reasoning models and SOTA graphics pipelines.
*   **General LLM**: `Qwen/Qwen2.5-14B-Instruct-GGUF` (File: `qwen2.5-14b-instruct-q4_k_m.gguf` ~ 9.0 GB VRAM) or `Meta-Llama-3.1-8B-Instruct` (FP16 or Q8_0 ~ 8.5 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-14B-Instruct-GGUF` (File: `qwen2.5-coder-14b-instruct-q4_k_m.gguf` ~ 9.0 GB VRAM)
*   **Image Generation**: `stabilityai/stable-diffusion-xl-base-1.0` (with LCM LoRA or SSD-1B distilled ~ 6.0 GB VRAM) or `black-forest-labs/FLUX.1-schnell` (Quantized ~ 12.0 GB VRAM)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (GPU execution, ~0.3 GB VRAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `large-v3` ~ 4.8 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 16.0` in `config.yaml`.

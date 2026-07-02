# CerberAI

CerberAI is an OpenAI-compatible API gateway designed to optimize local AI model execution. It intercepts incoming LLM, Image, TTS, STT, and Video requests, routes them to specialized local backends on-the-fly, and dynamically manages system VRAM/RAM by loading and unloading models on-demand.

*A note on the name: Cerberus is the infamous three-headed hound guarding the gates of the Underworld. If you run multiple instances of Cerberus, you get Cerberi (or Cerberii). Since this gateway sits at the gates of your GPU routing traffic to multiple specialized model "heads" simultaneously, it is only logical to call it **CerberAI**.*

---

## Why CerberAI Exists (The Problem)

Local AI has reached a point where consumer-grade hardware (NVIDIA, AMD, Intel Arc) can run highly capable models (such as Llama 3, Qwen 2.5 Coder, Stable Diffusion XL, Flux, Kokoro TTS, and Whisper) completely offline.

However, **VRAM is a hard constraint**. Typically, to run a complete local assistant suite, users must run multiple independent software servers concurrently (e.g., Ollama for general tasks, llama-server for coding, a Diffusers API for graphics, and specialized packages for audio synthesis and transcription). 
Running all of these concurrently will instantly trigger **Out-Of-Memory (OOM) crashes**, or force models to offload to the CPU, reducing performance to a crawl.

**CerberAI solves this by acting as a single, unified, intelligent broker.** It presents a single OpenAI-compatible API gateway. Under the hood, it monitors active model lifespans and dynamically swaps models in and out of GPU memory depending on the user's intent.

---

## Project Goals

1.  **Zero-Downtime Swapping**: Swap models in and out of GPU VRAM transparently during active chat and generation workflows without interrupting the user.
2.  **Unified API Surface**: Provide a single, standardized endpoint (`/v1/chat/completions`, `/v1/images/generations`, `/v1/audio/transcriptions`) that mimics OpenAI's API, allowing it to drop into any existing frontend (e.g., Open WebUI, LibreChat, Cursor, Cline).
3.  **Hardware Inclusivity**: Run efficiently on consumer graphics hardware from all major manufacturers—NVIDIA (CUDA), AMD (ROCm), and Intel (XPU).
4.  **Complete Privacy & Autonomy**: Zero external api keys, zero internet telemetry, and zero subscription costs. The gateway is designed to run 100% offline.

---

## System Design & Implementation

CerberAI is built on a modular, event-driven Python architecture:

*   **FastAPI Gateway**: Serves as the high-throughput asynchronous API shell. It intercepts incoming OpenAI-compatible payloads and handles request queueing, client connections, and SSE stream formatting.
*   **Dynamic Model Manager (DMM)**: Keeps track of all loaded models and their estimated memory footprints (VRAM/RAM). If loading a new model exceeds the user's configured `max_vram_gb`, the DMM triggers a **Least-Recently-Used (LRU)** eviction chain, cleanly unloading stale models before initializing the new one.
*   **Dynamic Purpose Intent Router**: Classifies incoming requests using lightweight regex-based heuristics or a local classifier LLM. When using LLM routing, the system dynamically queries the loaded LLM with a list of all active model IDs and their configured **purpose specifiers** to choose the best engine on-the-fly, bypassing network loops.
*   **Self-Healing Subprocess Adapters**: Adapters (such as `LlamaCppBackend`) manage running model processes. If a connection drop occurs, the adapter automatically calls `unload()` followed by `load()` to restart the local `llama-server` process transparently.
*   **ReAct Tool Executor**: Contains an inline agent executor. If tool calling is enabled, it parses model responses for tool calls, executes them locally (e.g., executing Python script code, searching the web locally using DuckDuckGo), and feeds the results back to the model before returning the final response.
*   **Global Settings & Gated Models**: Allows configuration of a global `hf_token` variable which is hot-injected into environment variables to authorize gated downloads from Hugging Face.

---

## Features

- **OpenAI-Compatible Endpoints**: Use with any tool that supports OpenAI's API (e.g. Open WebUI, LibreChat, Cursor, Cline).
- **Dynamic Resource Loading/Unloading**: Keeps memory footprint low by loading models on-demand and unloading them when idle or to make room for other models.
- **Dynamic Purpose-Based LLM Routing**: Introspects model definitions and matches them to incoming intents using custom descriptions.
- **Interactive Setup Dashboard**: An inline WebUI configuration screen to add, remove, and update LLM/STT/Image models and hot-reload settings in memory.
- **Persistent Conversation Threads**: Track, review, and delete historical chats from a dynamic sidebar, with automatic session naming based on context.
- **Inline Query Performance Metrics**: Real-time measurement and rendering of wall time, total completion tokens, and generation speed (tokens per second) for streaming and non-streaming prompts.
- **Dynamic Context Size & KV Cache Allocator**: Auto-calculates model-level maximum supported KV cache size dynamically using the remaining VRAM budget, with optional custom token limit overrides.
- **Real-Time Load & Download Indicators**: Dynamic polling updates the WebUI sidebar catalog and the active chat bubble with real-time model initialization and download progress percentages.
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
*   **Vision (Image-to-Text)**: `ggml-org/nanollava-GGUF` (NanoLLaVA 1B, ultra-lightweight vision, ~1.0 GB VRAM)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (CPU execution, ~0.3 GB RAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `tiny` ~ 0.5 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 4.0` in `config.yaml`.

### 2. 6 GB VRAM Tier (Medium Budget)
The sweet-spot for budget gaming laptops or older desktop cards (e.g., RTX 2060/3050).
*   **General LLM**: `Qwen/Qwen2.5-3B-Instruct-GGUF` (File: `qwen2.5-3b-instruct-q4_k_m.gguf` ~ 2.2 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-3B-Instruct-GGUF` (File: `qwen2.5-coder-3b-instruct-q4_k_m.gguf` ~ 2.2 GB VRAM)
*   **Image Generation**: `Lykon/dreamshaper-8-lcm` (Offloaded to GPU, ~4.0 GB VRAM)
*   **Vision (Image-to-Text)**: `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF` (File: `Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` + mmproj ~ 2.5 GB VRAM)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (CPU execution, ~0.3 GB RAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `base` ~ 0.7 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 6.0` in `config.yaml`.

### 3. 8 GB VRAM Tier (Standard Desktop)
Perfect for standard mainstream cards (e.g., RTX 3060/4060, RX 6600/7600).
*   **General LLM**: `QuantFactory/Meta-Llama-3.1-8B-Instruct-GGUF` (File: `Meta-Llama-3.1-8B-Instruct.Q4_K_M.gguf` ~ 4.8 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF` (File: `qwen2.5-coder-7b-instruct-q4_k_m.gguf` ~ 4.7 GB VRAM)
*   **Image Generation**: `Lykon/dreamshaper-8-lcm` (Fits completely in VRAM ~ 4.0 GB)
*   **Vision (Image-to-Text)**: `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF` (File: `Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` + mmproj ~ 2.5 GB VRAM)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (GPU execution, ~0.3 GB VRAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `small` ~ 1.5 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 8.0` in `config.yaml`.

### 4. 16 GB VRAM Tier (Enthusiast / Pro Creator)
For high-end workstation cards (e.g., RTX 4080, RX 7800 XT, or dual-GPU setups). Allows loading larger reasoning models and SOTA graphics pipelines.
*   **General LLM**: `Qwen/Qwen2.5-14B-Instruct-GGUF` (File: `qwen2.5-14b-instruct-q4_k_m.gguf` ~ 9.0 GB VRAM) or `Meta-Llama-3.1-8B-Instruct` (FP16 or Q8_0 ~ 8.5 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-14B-Instruct-GGUF` (File: `qwen2.5-coder-14b-instruct-q4_k_m.gguf` ~ 9.0 GB VRAM)
*   **Image Generation**: `stabilityai/sdxl-turbo` (1-step distilled high-quality image generation ~ 5.5 GB VRAM / fits comfortably with 16 GB system RAM and 16 GB GPU VRAM)
*   **Vision (Image-to-Text)**: `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF` (File: `Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` + mmproj ~ 3.5 GB VRAM)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (GPU execution, ~0.3 GB VRAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `large-v3` ~ 4.8 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 16.0` in `config.yaml`.

### 5. 24 GB VRAM Tier (Extreme Workstation / Single Flagship GPU)
For extreme-performance consumer setups (e.g., RTX 3090, RTX 4090, RX 7900 XTX). Run flagship-grade parameters locally.
*   **General LLM**: `Qwen/Qwen2.5-32B-Instruct-GGUF` (File: `qwen2.5-32b-instruct-q4_k_m.gguf` ~ 20.3 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-32B-Instruct-GGUF` (File: `qwen2.5-coder-32b-instruct-q4_k_m.gguf` ~ 20.3 GB VRAM)
*   **Image Generation**: `black-forest-labs/FLUX.1-schnell` (quantized GGUF or NF4 ~ 11.5 GB VRAM)
*   **Vision (Image-to-Text)**: `ggml-org/Qwen2.5-VL-7B-Instruct-GGUF` (File: `Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf` + mmproj ~ 5.5 GB VRAM)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (GPU execution, ~0.3 GB VRAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `large-v3` ~ 4.8 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 24.0` in `config.yaml`.

### 6. 32 GB VRAM Tier (Pro Workstation / Dual-GPU)
For professional workstations, base Apple Silicon Mac Studios, or dual-GPU setups (e.g. dual 16GB cards).
*   **General LLM**: `Qwen/Qwen2.5-32B-Instruct-GGUF` (File: `qwen2.5-32b-instruct-q5_k_m.gguf` ~ 24.5 GB VRAM) or `QuantFactory/Meta-Llama-3.3-70B-Instruct-GGUF` (File: `Meta-Llama-3.3-70B-Instruct.Q3_K_S.gguf` ~ 29.5 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-32B-Instruct-GGUF` (File: `qwen2.5-coder-32b-instruct-q5_k_m.gguf` ~ 24.5 GB VRAM)
*   **Image Generation**: `black-forest-labs/FLUX.1-dev` (quantized GGUF or NF4 ~ 12.0 GB VRAM)
*   **Vision (Image-to-Text)**: `ggml-org/Qwen2.5-VL-7B-Instruct-GGUF` (File: `Qwen2.5-VL-7B-Instruct-Q8_0.gguf` + mmproj ~ 9.0 GB VRAM)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (GPU execution, ~0.3 GB VRAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `large-v3` ~ 4.8 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 32.0` in `config.yaml`.

### 7. 64 GB VRAM Tier (AI Workstation Node / Apple Silicon Mac Studio)
For high-end Apple Silicon Macs (64GB Unified Memory) or multi-GPU desktop towers (e.g., dual RTX 3090/4090).
*   **General LLM**: `QuantFactory/Meta-Llama-3.3-70B-Instruct-GGUF` (File: `Meta-Llama-3.3-70B-Instruct.Q5_K_M.gguf` ~ 48.0 GB VRAM) or `Qwen/Qwen2.5-72B-Instruct-GGUF` (File: `qwen2.5-72b-instruct-q4_k_m.gguf` ~ 44.0 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-32B-Instruct-GGUF` (File: `qwen2.5-coder-32b-instruct-q8_0.gguf` ~ 35.0 GB VRAM)
*   **Image Generation**: `black-forest-labs/FLUX.1-dev` (Full FP16 or Q8 ~ 16.0 GB VRAM)
*   **Vision (Image-to-Text)**: `ggml-org/Qwen2.5-VL-32B-Instruct-GGUF` (File: `Qwen2.5-VL-32B-Instruct-Q4_K_M.gguf` + mmproj ~ 20.0 GB VRAM)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (GPU execution, ~0.3 GB VRAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `large-v3` ~ 4.8 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 64.0` in `config.yaml`.

### 8. 128 GB VRAM Tier (Datacenter / Enterprise Node / Maxed Mac Studio)
For state-of-the-art enterprise servers, maxed Apple Silicon Macs (128GB Unified Memory), or multi-GPU computing nodes.
*   **General LLM**: `QuantFactory/Meta-Llama-3.3-70B-Instruct-GGUF` (File: `Meta-Llama-3.3-70B-Instruct.Q8_0.gguf` ~ 75.0 GB VRAM) or `Qwen/Qwen2.5-72B-Instruct-GGUF` (File: `qwen2.5-72b-instruct-q8_0.gguf` ~ 77.0 GB VRAM)
*   **Coding LLM**: `Qwen/Qwen2.5-Coder-32B-Instruct-GGUF` (File: `qwen2.5-coder-32b-instruct-q8_0.gguf` ~ 35.0 GB VRAM) or `Qwen/Qwen2.5-Coder-72B-Instruct-GGUF` (File: `qwen2.5-coder-72b-instruct-q5_k_m.gguf` ~ 50.0 GB VRAM)
*   **Image Generation**: `black-forest-labs/FLUX.1-dev` (Full FP16 ~ 22.0 GB VRAM)
*   **Vision (Image-to-Text)**: `ggml-org/Qwen2.5-VL-72B-Instruct-GGUF` (File: `Qwen2.5-VL-72B-Instruct-Q4_K_M.gguf` + mmproj ~ 44.0 GB VRAM)
*   **Speech (TTS)**: `Kokoro-82M ONNX` (GPU execution, ~0.3 GB VRAM)
*   **Transcription (STT)**: `openai-whisper` (Model: `large-v3` ~ 4.8 GB VRAM)
*   *Config Recommendation*: Set `max_vram_gb: 128.0` in `config.yaml`.

---

## GPU Hardware Acceleration Setup (NVIDIA, AMD, Intel)

To run high-fidelity graphics (Diffusers / Flux) and transcription models at hardware speed, PyTorch must be configured to communicate with your specific graphics card. Follow the steps below for your hardware manufacturer:

### 1. NVIDIA GPUs (CUDA)
NVIDIA cards are supported out-of-the-box by standard PyPI packages.
*   **Prerequisites**: Verify your system has NVIDIA drivers and the CUDA Toolkit installed (`nvidia-smi`).
*   **Installation**:
    ```bash
    pip install torch torchvision
    ```
*   **Verification**:
    ```bash
    python -c "import torch; print('CUDA Available:', torch.cuda.is_available())"
    ```

### 2. AMD GPUs (ROCm)
AMD cards are supported on Linux via ROCm. Since the default PyPI packages only compile CUDA libraries, you must force-reinstall PyTorch from PyTorch's official ROCm wheel repositories.
*   **Prerequisites**:
    1. Verify ROCm is installed on your host system (e.g., check `/opt/rocm`).
    2. Check your host ROCm version:
       ```bash
       cat /opt/rocm/.info/version
       ```
*   **Installation**: Force-reinstall PyTorch using the matching ROCm index URL (e.g., if your host is running ROCm `7.2.4`, use `rocm7.2`; if running `6.0.x`, use `rocm6.0`):
    ```bash
    pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/rocm7.2
    ```
*   **llama.cpp GPU offloading (ROCm)**: Precompiled `llama.cpp` release binaries from GitHub only support CPU or NVIDIA CUDA. To enable GPU offloading for LLM models on AMD cards, compile `llama-server` from source using the provided automated script:
    ```bash
    ./build_llama_rocm.sh
    ```
    This script will clone `llama.cpp` (master branch), build it natively with `-DGGML_HIP=ON` using your ROCm LLVM Clang compiler, and place the executable and its dynamic libraries directly into CerberAI's local binaries cache (`~/.cache/cerberai/bin/`).
*   **Verification**: PyTorch uses the standard `cuda` device name namespace for ROCm as well. Verify your Radeon card is visible:
    ```bash
    python -c "import torch; print('ROCm Available:', torch.cuda.is_available()); print('Device Name:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None')"
    ```

### 3. Intel GPUs (XPU)
Intel Arc and Xe graphics cards are supported natively in recent PyTorch releases via the `XPU` backend.
*   **Prerequisites**:
    1. Ensure Intel GPU drivers are configured on your Linux host.
    2. Install Intel Level Zero runtime libraries (e.g., `sudo apt install level-zero level-zero-dev`).
*   **Installation**: Install PyTorch from PyTorch's specialized XPU wheel index:
    ```bash
    pip install torch torchvision --index-url https://download.pytorch.org/whl/xpu
    ```
*   **Verification**: Intel GPUs use the `xpu` device namespace. CerberAI automatically detects this backend and routes diffusion tasks to your Arc GPU:
    ```bash
    python -c "import torch; print('XPU Available:', torch.xpu.is_available() if hasattr(torch, 'xpu') else False)"
    ```


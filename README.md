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
│   └── backends/        # Adapters for various execution backends
│       ├── __init__.py
│       ├── base.py      # Base backend adapter
│       ├── ollama.py    # Ollama integration
│       └── llamacpp.py  # llama.cpp server subprocess manager
├── config.yaml          # Sample configuration file
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

## Quick Start (Under Development)

1. Clone or copy the repository to your local machine.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `config.yaml.example` to `config.yaml` and configure your models.
4. Run the server:
   ```bash
   python -m cerberai.main
   ```

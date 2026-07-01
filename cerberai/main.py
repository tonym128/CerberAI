import asyncio
import io
import json
import re
import time
import warnings
warnings.filterwarnings("ignore")

from contextlib import asynccontextmanager
from typing import Dict, Any
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from .config import load_config
from .manager import DynamicModelManager
from .router import IntentRouter
from .agent import AgentExecutor

# Load application configuration
config = load_config()

# Initialize managers
manager = DynamicModelManager(config)
router = IntentRouter(config.router, config.models)
agent = AgentExecutor(config)
cleanup_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: launch the DMM cleanup background task
    global cleanup_task
    cleanup_task = asyncio.create_task(manager.start_cleanup_loop())
    print("CerberAI Started. Dynamic Model Manager cleanup loop active.")
    yield
    # Shutdown: cancel background task and unload all active models
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
            
    print("Unloading all models for shutdown...")
    for model_id, backend in manager.backends.items():
        if await backend.is_loaded():
            print(f"Unloading '{model_id}'...")
            await backend.unload()
    print("CerberAI shutdown complete.")

app = FastAPI(
    title="CerberAI",
    description="Dynamic Model Routing & Resource Optimization OpenAI-compatible API Gateway",
    version="0.1.0",
    lifespan=lifespan
)

# Enable CORS for generic frontend compatibility (LibreChat, Open WebUI, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="cerberai/static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("cerberai/static/index.html")

@app.get("/status")
async def get_status():
    """Retrieve server resource details, configured models, and active load statuses."""
    active_models = []
    total_estimated_vram = 0.0
    
    for model_id, backend in manager.backends.items():
        loaded = await backend.is_loaded()
        cfg = next(m for m in config.models if m.id == model_id)
        if loaded:
            active_models.append({
                "id": model_id,
                "type": cfg.type,
                "backend": cfg.backend,
                "vram_estimate_gb": cfg.vram_estimate_gb,
                "last_active": manager.last_used.get(model_id, 0.0)
            })
            total_estimated_vram += cfg.vram_estimate_gb

    return {
        "status": "healthy",
        "limits": {
            "max_vram_gb": config.resource_limits.max_vram_gb,
            "max_ram_gb": config.resource_limits.max_ram_gb,
            "eviction_strategy": config.resource_limits.eviction_strategy,
            "timeout_keep_alive_seconds": config.server.timeout_keep_alive
        },
        "vram_usage": {
            "estimated_active_gb": total_estimated_vram,
            "percentage": (total_estimated_vram / config.resource_limits.max_vram_gb * 100) if config.resource_limits.max_vram_gb > 0 else 0
        },
        "active_models": active_models,
        "all_configured_models": [
            {"id": m.id, "type": m.type, "backend": m.backend, "vram_estimate_gb": m.vram_estimate_gb}
            for m in config.models
        ]
    }

@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible model listing endpoint."""
    data = []
    for model_cfg in config.models:
        data.append({
            "id": model_cfg.id,
            "object": "model",
            "created": 1677610602,  # Arbitrary timestamp
            "owned_by": "cerberai",
            "permission": [],
            "root": model_cfg.id,
            "parent": None
        })
    # Include 'auto' as a virtual model that maps to our intelligent router
    data.append({
        "id": "auto",
        "object": "model",
        "created": 1677610602,
        "owned_by": "cerberai",
        "permission": [],
        "root": "auto",
        "parent": None
    })
    return {"object": "list", "data": data}

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completion endpoint with dynamic routing and lazy model loading."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    messages = payload.get("messages", [])
    requested_model = payload.get("model", "auto")
    stream = payload.get("stream", False)


    # 1. Route request to appropriate model
    try:
        target_model_id = await router.route_chat(messages, requested_model)
    except Exception as e:
        print(f"Routing error: {e}")
        target_model_id = config.router.fallback_model

    print(f"Request routed to model: '{target_model_id}' (requested: '{requested_model}')")

    # 2. Get backend (triggers lazy load & memory eviction if required)
    try:
        backend = await manager.get_model(target_model_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load or acquire model backend '{target_model_id}': {str(e)}"
        )

    # If the routed model is an image generation model, generate the image inline and return a Markdown image link
    model_cfg = next((m for m in config.models if m.id == target_model_id), None)
    if model_cfg and model_cfg.type == "image":
        try:
            last_message_content = messages[-1].get("content", "") if messages else ""
            img_result = await backend.handle_image_generation({"prompt": last_message_content})
            b64_data = img_result["data"][0]["b64_json"]
            markdown_content = f"Here is the image you requested for **\"{last_message_content}\"**:\n\n![Generated Image](data:image/png;base64,{b64_data})"
            
            chat_response = {
                "id": f"chatcmpl-image-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": target_model_id,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": markdown_content
                    },
                    "finish_reason": "stop"
                }]
            }
            
            if stream:
                async def stream_image_markdown():
                    # Stream role and empty block first
                    yield f"data: {json.dumps({'choices': [{'delta': {'role': 'assistant', 'content': ''}, 'index': 0, 'finish_reason': None}]})}\n\n"
                    # Stream the full markdown image block
                    yield f"data: {json.dumps({'choices': [{'delta': {'content': markdown_content}, 'index': 0, 'finish_reason': None}]})}\n\n"
                    # Stream stop indicator
                    yield f"data: {json.dumps({'choices': [{'delta': {}, 'index': 0, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(stream_image_markdown(), media_type="text/event-stream")
            else:
                return JSONResponse(content=chat_response)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Image generation error: {str(e)}")

    # 3. Execute completion (stream vs regular response)


    if stream:
        try:
            return StreamingResponse(
                backend.stream_chat_completion(payload),
                media_type="text/event-stream"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")
    else:
        try:
            result = await backend.handle_chat_completion(payload)
            return JSONResponse(content=result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")

# Endpoint routers for Speech, Transcriptions, and Images
@app.post("/v1/audio/speech")
async def audio_speech(request: Request):
    """OpenAI-compatible Text-to-Speech (TTS) endpoint."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    tts_models = [m.id for m in config.models if m.type == "tts"]
    if not tts_models:
        raise HTTPException(status_code=501, detail="No TTS models configured.")
    
    target_model_id = tts_models[0]
    try:
        backend = await manager.get_model(target_model_id)
        audio_bytes = await backend.handle_audio_speech(payload)
        
        response_format = payload.get("response_format", "mp3")
        media_type = "audio/mpeg"
        if response_format == "wav":
            media_type = "audio/wav"
            
        return StreamingResponse(io.BytesIO(audio_bytes), media_type=media_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/audio/transcriptions")
async def audio_transcriptions(
    file: UploadFile = File(...),
    model: str = Form("auto"),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
    language: str = Form(None)
):
    """OpenAI-compatible Speech-to-Text (STT) transcription endpoint."""
    stt_models = [m.id for m in config.models if m.type == "stt"]
    if not stt_models:
        raise HTTPException(status_code=501, detail="No STT models configured.")
    
    target_model_id = stt_models[0]
    try:
        backend = await manager.get_model(target_model_id)
        file_bytes = await file.read()
        payload = {
            "response_format": response_format,
            "temperature": temperature,
            "language": language
        }
        result = await backend.handle_audio_transcription(file_bytes, file.filename, payload)
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/images/generations")
async def image_generations(request: Request):
    """Placeholder image generations router."""
    image_models = [m.id for m in config.models if m.type == "image"]
    if not image_models:
        raise HTTPException(status_code=501, detail="No image generation models configured.")
    
    target_model_id = image_models[0]
    try:
        backend = await manager.get_model(target_model_id)
        result = await backend.handle_image_generation(await request.json())
        return JSONResponse(content=result)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail=f"Image generation not implemented for backend type.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(
        "cerberai.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=True
    )


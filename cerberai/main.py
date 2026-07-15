import os
import sys
import asyncio
import base64
import io
import json
import re
import time
import warnings
warnings.filterwarnings("ignore")

def get_resource_path(relative_path: str) -> str:
    """Get absolute path to resource, supporting PyInstaller bundles."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.abspath(relative_path)


from contextlib import asynccontextmanager
from typing import Dict, Any
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging

class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "GET /status" not in record.getMessage()

# Register the filter at import time
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

from .config import load_config
from .manager import DynamicModelManager
from .router import IntentRouter
from .agent import AgentExecutor

# Load application configuration
config = load_config()
if config.hf_token:
    os.environ["HF_TOKEN"] = config.hf_token

# Optimize PyTorch memory allocation to avoid VRAM fragmentation
if "PYTORCH_CUDA_ALLOC_CONF" not in os.environ:
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# Detect AMD ROCm environment at startup and apply safety variables
if sys.platform.startswith("linux"):
    is_rocm_env = os.path.exists("/dev/kfd") or any(os.path.exists(p) for p in ["/dev/dri", "/opt/rocm"])
    if is_rocm_env:
        # Prevent GPU hangs during frequent host-device VRAM copies (CPU offloading)
        if "HSA_ENABLE_SDMA" not in os.environ:
            os.environ["HSA_ENABLE_SDMA"] = "1"
            print("CerberAI: AMD ROCm detected. Setting HSA_ENABLE_SDMA=1 (SDMA enabled).")

# Initialize managers
manager = DynamicModelManager(config)
router = IntentRouter(config.router, config.models)
agent = AgentExecutor(config)
from .mcp import MCPManager
mcp_manager = MCPManager(getattr(config, "mcp_servers", {}))
from .orchestrator import Orchestrator
orchestrator = Orchestrator(config, manager, agent)
cleanup_task = None
scheduler_task = None
telegram_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: launch background tasks
    global cleanup_task, scheduler_task, telegram_task
    
    # Ensure uvicorn access logs filter out spammy GET /status checks
    logging.getLogger("uvicorn.access").addFilter(EndpointFilter())
    
    cleanup_task = asyncio.create_task(manager.start_cleanup_loop())
    
    from .schedules import start_scheduler_loop
    scheduler_task = asyncio.create_task(start_scheduler_loop(config, manager, agent))
    
    from .telegram import start_telegram_loop
    telegram_task = asyncio.create_task(start_telegram_loop(config, manager, agent))
    
    print("Initializing MCP Manager and booting servers...")
    await mcp_manager.start_all()
    
    print("Starting Agent Orchestrator task runner...")
    orchestrator.start()
    
    print("CerberAI Started. Cleanup, Scheduler, and Telegram loops active.")
    yield
    # Shutdown: cancel background tasks and unload all active models
    for task in (cleanup_task, scheduler_task, telegram_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            
    print("Stopping Agent Orchestrator task runner...")
    await orchestrator.stop()
            
    print("Stopping MCP servers...")
    await mcp_manager.stop_all()
            
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
app.mount("/static", StaticFiles(directory=get_resource_path("cerberai/static")), name="static")

@app.get("/")
async def read_index():
    return FileResponse(get_resource_path("cerberai/static/index.html"))

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
                "n_ctx": getattr(cfg, "n_ctx", None),
                "last_active": manager.last_used.get(model_id, 0.0)
            })
            total_estimated_vram += cfg.vram_estimate_gb

    # Fetch lifetime stats from database for each model
    db_stats = {}
    try:
        from .database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT model_id, COUNT(*) as count, AVG(load_time) as avg_load, AVG(time_to_first_token) as avg_ttft,
                   SUM(completion_tokens) as total_comp, SUM(total_time - load_time) as total_gen
            FROM inference_stats
            GROUP BY model_id
        """)
        for row in cursor.fetchall():
            m_id = row["model_id"]
            total_comp = row["total_comp"] or 0
            total_gen = row["total_gen"] or 0
            if total_gen <= 0:
                total_gen = 1.0 # Safe default
            db_stats[m_id] = {
                "calls": row["count"],
                "avg_load": round(row["avg_load"], 2) if row["avg_load"] else 0.0,
                "avg_ttft": round(row["avg_ttft"], 2) if row["avg_ttft"] else 0.0,
                "tps": round(total_comp / total_gen, 1) if total_gen > 0 else 0.0
            }
        conn.close()
    except Exception as db_err:
        print(f"Warning: Failed to fetch status stats from DB: {db_err}")

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
        "loading_status": manager.loading_status,
        "all_configured_models": [
            {
                "id": m.id,
                "type": m.type,
                "backend": m.backend,
                "vram_estimate_gb": m.vram_estimate_gb,
                "n_ctx": getattr(m, "n_ctx", None),
                "model_name": (
                    manager.backends[m.id].actual_model_name 
                    if m.id in manager.backends and isinstance(getattr(manager.backends[m.id], "actual_model_name", None), str)
                    else m.backend_config.get("filename", m.backend_config.get("model_name", m.backend_config.get("repo_id", m.id)))
                ),
                "diagnostics": manager.backends[m.id].get_diagnostics() if m.id in manager.backends else {},
                "stats": db_stats.get(m.id, {"calls": 0, "avg_load": 0.0, "avg_ttft": 0.0, "tps": 0.0}),
                "downloaded": _check_model_downloaded(m)
            }
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
    # Include 'autorouting' as a virtual model that maps to our intelligent router
    data.append({
        "id": "autorouting",
        "object": "model",
        "created": 1677610602,
        "owned_by": "cerberai",
        "permission": [],
        "root": "autorouting",
        "parent": None
    })
    return {"object": "list", "data": data}

STARTUP_TIME = time.time()

from typing import AsyncIterator

async def stream_with_metrics(
    generator: AsyncIterator[bytes],
    model_id: str,
    load_time: float = 0.0,
    prompt_tokens: int = 0,
    model_name: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    manager = None
) -> AsyncIterator[bytes]:
    start_time = time.time()
    first_token_time = None
    total_tokens = 0
    accumulated_content = ""
    
    try:
        async for chunk in generator:
            try:
                chunk_str = chunk.decode("utf-8")
                for line in chunk_str.split("\n"):
                    line = line.strip()
                    if line.startswith("data: ") and not line.endswith("[DONE]"):
                        data = json.loads(line[6:])
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                if first_token_time is None:
                                    first_token_time = time.time()
                                accumulated_content += content
            except Exception:
                pass
                
            yield chunk
    except Exception as e:
        print(f"Error streaming chat completion: {e}")
        raise
        
    end_time = time.time()
    wall_time = end_time - start_time
    
    if accumulated_content:
        total_tokens = max(1, len(accumulated_content) // 4)
        
    tps = 0.0
    if first_token_time is not None:
        active_time = end_time - first_token_time
        tps = total_tokens / active_time if active_time > 0 else 0.0
        
    metrics = {
        "model": model_id,
        "wall_time_sec": wall_time,
        "completion_tokens": total_tokens,
        "tokens_per_second": tps
    }
    
    try:
        from .database import db_add_inference_stat
        ttft = (first_token_time - start_time) if first_token_time else wall_time
        db_add_inference_stat(
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=total_tokens,
            load_time=load_time,
            time_to_first_token=ttft,
            total_time=wall_time,
            model_name=model_name
        )
    except Exception as stat_err:
        print(f"Failed to record stream stats: {stat_err}")
        
    if messages and manager and accumulated_content:
        try:
            from .memory import extract_and_save_memories
            history = messages + [{"role": "assistant", "content": accumulated_content}]
            asyncio.create_task(extract_and_save_memories(history, manager))
        except Exception as e:
            print(f"Memory extraction from stream failed: {e}")

    yield f"data: {json.dumps({'metrics': metrics})}\n\n".encode("utf-8")

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

    # Ensure a generous max_tokens limit if not explicitly set by the client
    # to avoid premature truncation by the backend server.
    if "max_tokens" not in payload and "max_completion_tokens" not in payload:
        payload["max_tokens"] = 8192


    # 1. Route request to appropriate model
    try:
        target_model_id = await router.route_chat(messages, requested_model, manager)
    except Exception as e:
        print(f"Routing error: {e}")
        target_model_id = config.router.fallback_model

    print(f"Request routed to model: '{target_model_id}' (requested: '{requested_model}')")

    # If we used a router model and the target model is different, unload the router to free VRAM
    if config.router.model_type == "llm" and config.router.model_name:
        router_id = config.router.model_name
        if target_model_id != router_id and router_id in manager.backends:
            router_backend = manager.backends[router_id]
            if await router_backend.is_loaded():
                print(f"Unloading router model '{router_id}' to free VRAM for target model '{target_model_id}'...")
                try:
                    await router_backend.unload()
                except Exception as ex:
                    print(f"Warning: Failed to unload router model: {ex}")

    # 2. Get backend (triggers lazy load & memory eviction if required)
    is_already_loaded = False
    if target_model_id in manager.backends:
        try:
            is_already_loaded = await manager.backends[target_model_id].is_loaded()
        except Exception:
            pass
            
    t0 = time.time()
    try:
        backend = await manager.get_model(target_model_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load or acquire model backend '{target_model_id}': {str(e)}"
        )
    load_time = time.time() - t0 if not is_already_loaded else 0.0
    prompt_tokens_est = sum(len(str(m.get('content', ''))) // 4 for m in messages)

    # If the routed model is an image generation model, generate the image inline and return a Markdown image link
    model_cfg = next((m for m in config.models if m.id == target_model_id), None)

    # Sanitize messages content if target model is a text-only LLM model (unsupported list content type in llama-server)
    if model_cfg and model_cfg.type == "llm":
        # Dynamic Semantic Memory Context Injection
        try:
            from .memory import get_embedding, search_memories
            latest_query = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        latest_query = content
                    elif isinstance(content, list):
                        latest_query = "\n".join([item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"])
                    break
                    
            if latest_query:
                query_emb = await get_embedding(latest_query, manager)
                if query_emb:
                    memories = search_memories(query_emb, threshold=0.72, limit=4)
                    if memories:
                        memory_bullet_points = "\n".join([f"- {m['content']}" for m in memories])
                        memory_system_inject = (
                            "\n\n[System Memory of User Context - Use this information to personalize your answer if relevant]:\n"
                            f"{memory_bullet_points}\n"
                        )
                        # Find system message or insert one
                        sys_msg = None
                        for m in messages:
                            if m.get("role") == "system":
                                sys_msg = m
                                break
                        if sys_msg:
                            sys_msg["content"] = sys_msg["content"] + memory_system_inject
                        else:
                            messages.insert(0, {"role": "system", "content": memory_system_inject.strip()})
        except Exception as e:
            print(f"Warning: Failed to retrieve/inject semantic memories: {e}")

        sanitized_messages = []
        for msg in messages:
            msg_copy = msg.copy()
            content = msg_copy.get("content")
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        text_parts.append(item)
                msg_copy["content"] = "\n".join(text_parts)
            sanitized_messages.append(msg_copy)
        messages = sanitized_messages

        # Sliding context window check to fit within model n_ctx limit
        n_ctx = model_cfg.n_ctx or 16384
        safe_limit = max(3000, n_ctx - 3000)
        
        system_msg = None
        other_msgs = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg
            else:
                other_msgs.append(msg)
                
        def est_tokens(msgs):
            total_chars = 0
            for m in msgs:
                content = m.get("content", "")
                if isinstance(content, str):
                    total_chars += len(content)
            return total_chars // 3
            
        sys_tokens = est_tokens([system_msg]) if system_msg else 0
        while other_msgs and (sys_tokens + est_tokens(other_msgs) > safe_limit):
            other_msgs.pop(0)
            
        pruned_messages = []
        if system_msg:
            pruned_messages.append(system_msg)
        pruned_messages.extend(other_msgs)
        messages = pruned_messages
        payload["messages"] = messages
        
        # Re-estimate prompt tokens after pruning
        prompt_tokens_est = sum(len(str(m.get('content', ''))) // 3 for m in messages)

    if model_cfg and model_cfg.type == "image":
        try:
            last_message_content = messages[-1].get("content", "") if messages else ""
            img_result = await backend.handle_image_generation({"prompt": last_message_content})
            b64_data = img_result["data"][0]["b64_json"]
            
            # Save the image to the static generated assets folder
            import uuid
            img_filename = f"image_{uuid.uuid4().hex}.png"
            img_dir = os.path.join("cerberai", "static", "generated")
            os.makedirs(img_dir, exist_ok=True)
            img_path = os.path.join(img_dir, img_filename)
            with open(img_path, "wb") as fh:
                fh.write(base64.b64decode(b64_data))
            
            base_url = str(request.base_url).rstrip("/")
            static_url = f"{base_url}/static/generated/{img_filename}"
            markdown_content = f"Here is the image you requested for **\"{last_message_content}\"**:\n\n![Generated Image]({static_url})"
            
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

    # If the routed model is a video generation model, generate the video inline and return a Markdown video player
    if model_cfg and model_cfg.type == "video":
        try:
            last_msg = messages[-1] if messages else {}
            content = last_msg.get("content", "")
            
            prompt = ""
            image_b64 = None
            
            if isinstance(content, str):
                prompt = content
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        item_type = item.get("type", "")
                        if item_type == "text":
                            prompt = item.get("text", "")
                        elif item_type == "image_url":
                            img_url = item.get("image_url", {}).get("url", "")
                            if img_url.startswith("data:image/"):
                                if "," in img_url:
                                    image_b64 = img_url.split(",", 1)[1]
                                else:
                                    image_b64 = img_url
            
            payload_to_send = {}
            if prompt:
                payload_to_send["prompt"] = prompt
            if image_b64:
                payload_to_send["image"] = image_b64
                
            desc_prompt = prompt or "Uploaded Image"
            
            if stream:
                async def stream_video_markdown():
                    queue = asyncio.Queue()
                    
                    # Yield initial status
                    await queue.put("🎬 **Starting Video Generation...**\n\n")
                    
                    async def progress_cb(msg: str):
                        await queue.put(msg)
                        
                    async def run_generation():
                        try:
                            res = await backend.handle_video_generation(
                                payload_to_send,
                                progress_callback=progress_cb
                            )
                            await queue.put(res)
                        except Exception as err:
                            await queue.put(err)
                            
                    # Start generation task in the background
                    gen_task = asyncio.create_task(run_generation())
                    
                    role_sent = False
                    while True:
                        item = await queue.get()
                        if isinstance(item, str):
                            # Stream status update to chat client
                            if not role_sent:
                                yield f"data: {json.dumps({'choices': [{'delta': {'role': 'assistant', 'content': item}, 'index': 0, 'finish_reason': None}]})}\n\n"
                                role_sent = True
                            else:
                                yield f"data: {json.dumps({'choices': [{'delta': {'content': item}, 'index': 0, 'finish_reason': None}]})}\n\n"
                        elif isinstance(item, dict):
                            # Success! Save the video to the static generated assets folder
                            b64_data = item["b64_json"]
                            import uuid
                            vid_filename = f"video_{uuid.uuid4().hex}.mp4"
                            vid_dir = os.path.join("cerberai", "static", "generated")
                            os.makedirs(vid_dir, exist_ok=True)
                            vid_path = os.path.join(vid_dir, vid_filename)
                            with open(vid_path, "wb") as fh:
                                fh.write(base64.b64decode(b64_data))
                                
                            base_url = str(request.base_url).rstrip("/")
                            static_url = f"{base_url}/static/generated/{vid_filename}"
                            final_markdown = f"\n\n🎬 **Video Generated Successfully!**\n\n<video src=\"{static_url}\" controls style=\"width: 100%; max-width: 512px; border-radius: 8px;\"></video>\n\n[Download Video]({static_url})"
                            
                            yield f"data: {json.dumps({'choices': [{'delta': {'content': final_markdown}, 'index': 0, 'finish_reason': None}]})}\n\n"
                            yield f"data: {json.dumps({'choices': [{'delta': {}, 'index': 0, 'finish_reason': 'stop'}]})}\n\n"
                            yield "data: [DONE]\n\n"
                            break
                        else:
                            # Exception occurred
                            err_msg = f"\n\n❌ **Video Generation Failed:** {str(item)}"
                            yield f"data: {json.dumps({'choices': [{'delta': {'content': err_msg}, 'index': 0, 'finish_reason': 'stop'}]})}\n\n"
                            yield "data: [DONE]\n\n"
                            break
                return StreamingResponse(stream_video_markdown(), media_type="text/event-stream")
            else:
                # Non-streaming request (like telegram / api calls)
                vid_result = await backend.handle_video_generation(payload_to_send)
                b64_data = vid_result["b64_json"]
                
                import uuid
                vid_filename = f"video_{uuid.uuid4().hex}.mp4"
                vid_dir = os.path.join("cerberai", "static", "generated")
                os.makedirs(vid_dir, exist_ok=True)
                vid_path = os.path.join(vid_dir, vid_filename)
                with open(vid_path, "wb") as fh:
                    fh.write(base64.b64decode(b64_data))
                
                base_url = str(request.base_url).rstrip("/")
                static_url = f"{base_url}/static/generated/{vid_filename}"
                markdown_content = f"Here is the video you requested for **\"{desc_prompt}\"**:\n\n<video src=\"{static_url}\" controls style=\"width: 100%; max-width: 512px; border-radius: 8px;\"></video>\n\n[Download Video]({static_url})"
                
                chat_response = {
                    "id": f"chatcmpl-video-{int(time.time())}",
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
                return JSONResponse(content=chat_response)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Video generation error: {str(e)}")

    # If the routed model is a vision model, forward the request directly (llama-server handles multimodal input natively)
    if model_cfg and model_cfg.type == "vision":
        if stream:
            try:
                return StreamingResponse(
                    stream_with_metrics(backend.stream_chat_completion(payload), target_model_id, load_time=load_time, prompt_tokens=prompt_tokens_est, model_name=backend.actual_model_name, messages=messages, manager=manager),
                    media_type="text/event-stream"
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Vision streaming error: {str(e)}")
        else:
            try:
                start_time = time.time()
                result = await backend.handle_chat_completion(payload)
                end_time = time.time()
                
                wall_time = end_time - start_time
                content = result["choices"][0]["message"]["content"]
                completion_tokens = 0
                if "usage" in result and "completion_tokens" in result["usage"]:
                    completion_tokens = result["usage"]["completion_tokens"]
                else:
                    completion_tokens = max(1, len(content) // 4)
                    
                tps = completion_tokens / wall_time if wall_time > 0 else 0.0
                metrics = {
                    "model": target_model_id,
                    "wall_time_sec": wall_time,
                    "completion_tokens": completion_tokens,
                    "tokens_per_second": tps
                }
                result["metrics"] = metrics
                try:
                    from .database import db_add_inference_stat
                    db_add_inference_stat(
                        model_id=target_model_id,
                        prompt_tokens=prompt_tokens_est,
                        completion_tokens=completion_tokens,
                        load_time=load_time,
                        time_to_first_token=wall_time,
                        total_time=wall_time,
                        model_name=backend.actual_model_name
                    )
                except Exception as stat_err:
                    print(f"Failed to record vision inference stats: {stat_err}")
                return JSONResponse(content=result)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Vision inference error: {str(e)}")

    # If the routed model is a TTS model, handle inline audio synthesis
    if model_cfg and model_cfg.type == "tts":
        try:
            last_message_content = messages[-1].get("content", "") if messages else ""
            audio_bytes = await backend.handle_audio_speech({"input": last_message_content})
            
            # Save audio to static generated assets folder
            import uuid
            audio_filename = f"audio_{uuid.uuid4().hex}.mp3"
            img_dir = os.path.join("cerberai", "static", "generated")
            os.makedirs(img_dir, exist_ok=True)
            audio_path = os.path.join(img_dir, audio_filename)
            with open(audio_path, "wb") as fh:
                fh.write(audio_bytes)
                
            base_url = str(request.base_url).rstrip("/")
            static_url = f"{base_url}/static/generated/{audio_filename}"
            markdown_content = f"Here is the spoken audio for **\"{last_message_content}\"**:\n\n<audio controls src=\"{static_url}\" style=\"width: 100%; margin-top: 8px;\"></audio>"
            
            chat_response = {
                "id": f"chatcmpl-tts-{int(time.time())}",
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
                async def stream_tts_markdown():
                    yield f"data: {json.dumps({'choices': [{'delta': {'role': 'assistant', 'content': ''}, 'index': 0, 'finish_reason': None}]})}\n\n"
                    yield f"data: {json.dumps({'choices': [{'delta': {'content': markdown_content}, 'index': 0, 'finish_reason': None}]})}\n\n"
                    yield f"data: {json.dumps({'choices': [{'delta': {}, 'index': 0, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(stream_tts_markdown(), media_type="text/event-stream")
            else:
                return JSONResponse(content=chat_response)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"TTS inline error: {str(e)}")

    # If the routed model is an STT model, prompt the user on how to use it
    if model_cfg and model_cfg.type == "stt":
        markdown_content = "🎙️ **Speech-to-Text Model Selected**\n\nTo transcribe audio, please click the **Microphone** icon button next to the input area to upload an audio file directly into the chat."
        
        chat_response = {
            "id": f"chatcmpl-stt-{int(time.time())}",
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
            async def stream_stt_markdown():
                yield f"data: {json.dumps({'choices': [{'delta': {'role': 'assistant', 'content': ''}, 'index': 0, 'finish_reason': None}]})}\n\n"
                yield f"data: {json.dumps({'choices': [{'delta': {'content': markdown_content}, 'index': 0, 'finish_reason': None}]})}\n\n"
                yield f"data: {json.dumps({'choices': [{'delta': {}, 'index': 0, 'finish_reason': 'stop'}]})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(stream_stt_markdown(), media_type="text/event-stream")
        else:
            return JSONResponse(content=chat_response)

    # Check if tool calling should run
    tools_enabled = payload.get("tools_enabled", True)

    if tools_enabled and agent.tools and model_cfg and model_cfg.type == "llm" and not payload.get("tools"):
        try:
            start_time = time.time()
            sys_extension = agent.get_system_prompt_extension()
            local_messages = list(messages)
            
            # Inject system instructions
            if local_messages and local_messages[0].get("role") == "system":
                system_msg = local_messages[0].copy()
                system_msg["content"] += sys_extension
                local_messages[0] = system_msg
            else:
                local_messages.insert(0, {
                    "role": "system",
                    "content": "You are a helpful assistant." + sys_extension
                })
                
            # For small models, also append a reminder directly to the last user message
            for msg in reversed(local_messages):
                if msg.get("role") == "user":
                    user_msg = msg.copy()
                    user_msg["content"] += (
                        "\n\n[TOOL CALL REMINDER]\n"
                        "To search the web, you must output exactly:\n"
                        "<tool_call>{\"name\": \"web_search\", \"arguments\": {\"query\": \"search keywords\"}}</tool_call>"
                    )
                    idx = local_messages.index(msg)
                    local_messages[idx] = user_msg
                    break

            local_payload = dict(payload)
            local_payload["messages"] = local_messages
            local_payload["stream"] = False  # Disable streaming for intermediate agent reasoning steps

            if stream:
                async def stream_agent_workflow():
                    yield f"data: {json.dumps({'choices': [{'delta': {'role': 'assistant', 'content': ''}, 'index': 0, 'finish_reason': None}]})}\n\n"
                    
                    loop_limit = 5
                    content = ""
                    for step in range(loop_limit):
                        response = await backend.handle_chat_completion(local_payload)
                        content = response["choices"][0]["message"]["content"]
                        
                        match = re.search(r"<tool_call>(.*?)</tool_call>", content, re.DOTALL)
                        if match:
                            tool_call_json = match.group(1).strip()
                            
                            # Parse details
                            tool_name = "unknown"
                            tool_args_str = ""
                            try:
                                tc_data = json.loads(tool_call_json)
                                tool_name = tc_data.get("name", "unknown")
                                tool_args_str = json.dumps(tc_data.get("arguments", {}))
                            except Exception:
                                func_match = re.match(r"^(\w+)\((.*)\)$", tool_call_json, re.DOTALL)
                                if func_match:
                                    tool_name = func_match.group(1)
                                    tool_args_str = func_match.group(2).strip()
                                else:
                                    tool_name = "tool_call"
                                    tool_args_str = tool_call_json[:150]
                                    
                            # Stream "Running" block
                            sandbox_running_html = (
                                f"\n<div class=\"tool-sandbox-call\" data-tool=\"{tool_name}\">\n"
                                f"  <div class=\"tool-sandbox-header\">🔧 Running tool: <strong>{tool_name}</strong></div>\n"
                                f"  <div class=\"tool-sandbox-query\">arguments: <code>{tool_args_str}</code></div>\n"
                                f"  <div class=\"tool-sandbox-status pulse\">Executing locally...</div>\n"
                                f"</div>\n\n"
                            )
                            yield f"data: {json.dumps({'choices': [{'delta': {'content': sandbox_running_html}, 'index': 0, 'finish_reason': None}]})}\n\n"
                            
                            # Execute tool
                            tool_result = await agent.execute_tool(tool_call_json)
                            
                            # Truncate
                            truncated_result = tool_result
                            if len(truncated_result) > 2000:
                                truncated_result = truncated_result[:2000] + "\n\n... [Output Truncated for View] ..."
                                
                            # Stream "Finished" block
                            sandbox_finished_html = (
                                f"\n<div class=\"tool-sandbox-call success\" data-tool=\"{tool_name}\">\n"
                                f"  <details open>\n"
                                f"    <summary>✓ Ran tool: <strong>{tool_name}</strong> (Click to collapse results)</summary>\n"
                                f"    <pre class=\"tool-sandbox-result\">{truncated_result}</pre>\n"
                                f"  </details>\n"
                                f"</div>\n\n"
                            )
                            yield f"data: {json.dumps({'choices': [{'delta': {'content': sandbox_finished_html}, 'index': 0, 'finish_reason': None}]})}\n\n"
                            
                            # Append history
                            local_messages.append({"role": "assistant", "content": content})
                            local_messages.append({
                                "role": "user",
                                "content": f"[TOOL RESPONSE]\n{tool_result}"
                            })
                            local_payload["messages"] = local_messages
                            continue
                        else:
                            # Final response
                            chunk_size = 6
                            for i in range(0, len(content), chunk_size):
                                chunk = content[i:i+chunk_size]
                                yield f"data: {json.dumps({'choices': [{'delta': {'content': chunk}, 'index': 0, 'finish_reason': None}]})}\n\n"
                                await asyncio.sleep(0.01)
                            break
                            
                    # Yield metrics and stop
                    end_time = time.time()
                    wall_time = end_time - start_time
                    completion_tokens = max(1, len(content) // 4)
                    tps = completion_tokens / wall_time if wall_time > 0 else 0.0
                    metrics = {
                        "model": target_model_id,
                        "wall_time_sec": wall_time,
                        "completion_tokens": completion_tokens,
                        "tokens_per_second": tps
                    }
                    yield f"data: {json.dumps({'metrics': metrics})}\n\n"
                    yield f"data: {json.dumps({'choices': [{'delta': {}, 'index': 0, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                
                return StreamingResponse(stream_agent_workflow(), media_type="text/event-stream")
            else:
                loop_limit = 5
                accumulated_content = ""
                content = ""
                response = None
                for step in range(loop_limit):
                    response = await backend.handle_chat_completion(local_payload)
                    content = response["choices"][0]["message"]["content"]
                    
                    match = re.search(r"<tool_call>(.*?)</tool_call>", content, re.DOTALL)
                    if match:
                        tool_call_json = match.group(1).strip()
                        
                        tool_name = "unknown"
                        try:
                            tc_data = json.loads(tool_call_json)
                            tool_name = tc_data.get("name", "unknown")
                        except Exception:
                            func_match = re.match(r"^(\w+)\((.*)\)$", tool_call_json, re.DOTALL)
                            if func_match:
                                tool_name = func_match.group(1)
                                
                        tool_result = await agent.execute_tool(tool_call_json)
                        
                        truncated_result = tool_result
                        if len(truncated_result) > 2000:
                            truncated_result = truncated_result[:2000] + "\n\n... [Output Truncated for View] ..."
                            
                        sandbox_html = (
                            f"\n<div class=\"tool-sandbox-call success\" data-tool=\"{tool_name}\">\n"
                            f"  <details>\n"
                            f"    <summary>🔧 Ran tool: <strong>{tool_name}</strong> (Click to view results)</summary>\n"
                            f"    <pre class=\"tool-sandbox-result\">{truncated_result}</pre>\n"
                            f"  </details>\n"
                            f"</div>\n\n"
                        )
                        accumulated_content += sandbox_html
                        
                        local_messages.append({"role": "assistant", "content": content})
                        local_messages.append({
                            "role": "user",
                            "content": f"[TOOL RESPONSE]\n{tool_result}"
                        })
                        local_payload["messages"] = local_messages
                        continue
                    else:
                        accumulated_content += content
                        break
                        
                end_time = time.time()
                wall_time = end_time - start_time
                completion_tokens = max(1, len(accumulated_content) // 4)
                tps = completion_tokens / wall_time if wall_time > 0 else 0.0
                
                response["choices"][0]["message"]["content"] = accumulated_content
                response["metrics"] = {
                    "model": target_model_id,
                    "wall_time_sec": wall_time,
                    "completion_tokens": completion_tokens,
                    "tokens_per_second": tps
                }
                return JSONResponse(content=response)
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Agent loop error: {str(e)}")

    # 3. Execute completion (stream vs regular response)
    if stream:
        try:
            return StreamingResponse(
                stream_with_metrics(backend.stream_chat_completion(payload), target_model_id, load_time=load_time, prompt_tokens=prompt_tokens_est, model_name=backend.actual_model_name, messages=messages, manager=manager),
                media_type="text/event-stream"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Streaming error: {str(e)}")
    else:
        try:
            start_time = time.time()
            result = await backend.handle_chat_completion(payload)
            end_time = time.time()
            
            wall_time = end_time - start_time
            content = result["choices"][0]["message"]["content"]
            completion_tokens = 0
            if "usage" in result and "completion_tokens" in result["usage"]:
                completion_tokens = result["usage"]["completion_tokens"]
            else:
                completion_tokens = max(1, len(content) // 4)
                
            tps = completion_tokens / wall_time if wall_time > 0 else 0.0
            metrics = {
                "model": target_model_id,
                "wall_time_sec": wall_time,
                "completion_tokens": completion_tokens,
                "tokens_per_second": tps
            }
            result["metrics"] = metrics
            
            if content:
                try:
                    from .memory import extract_and_save_memories
                    history = messages + [result["choices"][0]["message"]]
                    asyncio.create_task(extract_and_save_memories(history, manager))
                except Exception as e:
                    print(f"Memory extraction failed: {e}")
            try:
                from .database import db_add_inference_stat
                db_add_inference_stat(
                    model_id=target_model_id,
                    prompt_tokens=prompt_tokens_est,
                    completion_tokens=completion_tokens,
                    load_time=load_time,
                    time_to_first_token=wall_time,
                    total_time=wall_time,
                    model_name=backend.actual_model_name
                )
            except Exception as stat_err:
                print(f"Failed to record LLM inference stats: {stat_err}")
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

@app.post("/v1/automate/news-video")
async def start_news_video_automation(request: Request):
    """Trigger the news video generation workflow by enqueuing a job in the Orchestrator."""
    from .automation import get_status, update_status
    from .database import db_create_job
    
    current_status = get_status()
    if current_status["status"] in ("running", "pending"):
        return JSONResponse(content={"message": "Automation is already running or queued.", "status": current_status})
        
    topic = None
    date_str = None
    video_mode = "image"
    try:
        payload = await request.json()
        topic = payload.get("topic")
        date_str = payload.get("date")
        video_mode = payload.get("video_mode", "image")
    except Exception:
        pass
        
    update_status("pending", 0, "Job enqueued in Orchestrator...")
    job_id = db_create_job("news-video", {"topic": topic, "date": date_str, "video_mode": video_mode}, vram_required=10.0)
    return JSONResponse(content={"message": "Automation job enqueued successfully.", "job_id": job_id, "status": get_status()})

@app.get("/v1/automate/news-video/status")
async def get_news_video_automation_status():
    """Retrieve the real-time status of the news video automation task."""
    from .automation import get_status
    return JSONResponse(content=get_status())

@app.get("/v1/automate/news-video/history")
async def get_news_video_history():
    """Retrieve the history list of generated news videos."""
    from .database import db_get_media_history
    try:
        return JSONResponse(content=db_get_media_history("video"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read history: {str(e)}")


@app.post("/v1/automate/deep-research")
async def start_deep_research_automation(request: Request):
    """Trigger the recursive deep research report workflow by enqueuing a job in the Orchestrator."""
    from .automation import get_research_status, update_research_status
    from .database import db_create_job
    
    current_status = get_research_status()
    if current_status["status"] in ("running", "pending"):
        return JSONResponse(content={"message": "Research task is already running or queued.", "status": current_status})
        
    query = None
    try:
        payload = await request.json()
        query = payload.get("query")
    except Exception:
        pass
        
    if not query:
        raise HTTPException(status_code=400, detail="Query parameter is required.")
        
    update_research_status("pending", 0, "Job enqueued in Orchestrator...", query=query)
    job_id = db_create_job("deep-research", {"topic": query}, vram_required=8.0)
    return JSONResponse(content={"message": "Deep Research job enqueued successfully.", "job_id": job_id, "status": get_research_status()})

@app.get("/v1/automate/deep-research/status")
async def get_deep_research_status_endpoint():
    """Retrieve the real-time status of the deep research task."""
    from .automation import get_research_status
    return JSONResponse(content=get_research_status())

@app.get("/v1/automate/deep-research/history")
async def get_deep_research_history():
    """Retrieve the history list of generated deep research reports."""
    from .database import db_get_media_history
    try:
        return JSONResponse(content=db_get_media_history("report"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read history: {str(e)}")


@app.post("/v1/automate/podcast")
async def start_podcast_automation(request: Request):
    """Trigger the daily podcast news briefing generation by enqueuing a job in the Orchestrator."""
    from .automation import get_podcast_status, update_podcast_status
    from .database import db_create_job
    
    current_status = get_podcast_status()
    if current_status["status"] in ("running", "pending"):
        return JSONResponse(content={"message": "Podcast briefing task is already running or queued.", "status": current_status})
        
    topic = None
    date_str = None
    try:
        payload = await request.json()
        topic = payload.get("topic")
        date_str = payload.get("date")
    except Exception:
        pass
        
    update_podcast_status("pending", 0, "Job enqueued in Orchestrator...", query=topic)
    job_id = db_create_job("podcast", {"topic": topic, "date": date_str}, vram_required=8.0)
    return JSONResponse(content={"message": "Podcast job enqueued successfully.", "job_id": job_id, "status": get_podcast_status()})

@app.get("/v1/automate/podcast/status")
async def get_podcast_status_endpoint():
    """Retrieve the real-time status of the podcast briefing generation."""
    from .automation import get_podcast_status
    return JSONResponse(content=get_podcast_status())

@app.get("/v1/automate/podcast/history")
async def get_podcast_history():
    """Retrieve the history list of generated podcasts."""
    from .database import db_get_media_history
    try:
        return JSONResponse(content=db_get_media_history("podcast"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read history: {str(e)}")


@app.get("/api/schedules")
async def get_schedules_endpoint():
    """List all configured daily schedules."""
    from .schedules import load_schedules
    try:
        return JSONResponse(content=load_schedules())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/schedules")
async def create_schedule_endpoint(request: Request):
    """Create or update a schedule entry."""
    from .schedules import load_schedules, save_schedules
    import uuid
    try:
        data = await request.json()
        
        # Validation
        if not data.get("type") or not data.get("target") or not data.get("time"):
            raise HTTPException(status_code=400, detail="Missing required schedule fields: 'type', 'target', or 'time'.")
            
        schedules = load_schedules()
        
        # Check if updating or creating
        schedule_id = data.get("id")
        if schedule_id:
            idx = next((i for i, s in enumerate(schedules) if s["id"] == schedule_id), -1)
            if idx != -1:
                schedules[idx] = data
            else:
                schedules.append(data)
        else:
            data["id"] = f"sch_{uuid.uuid4().hex[:8]}"
            data["last_run"] = None
            schedules.append(data)
            
        save_schedules(schedules)
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule_endpoint(schedule_id: str):
    """Delete a schedule entry by ID."""
    from .schedules import load_schedules, save_schedules
    try:
        schedules = load_schedules()
        new_schedules = [s for s in schedules if s["id"] != schedule_id]
        if len(schedules) == len(new_schedules):
            raise HTTPException(status_code=404, detail="Schedule not found.")
        save_schedules(new_schedules)
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/telegram/history")
async def get_telegram_history_endpoint():
    """Retrieve the Telegram message history logs."""
    from .database import db_get_telegram_history
    import datetime
    try:
        history = db_get_telegram_history()
        formatted = []
        for item in history:
            dt_str = datetime.datetime.fromtimestamp(item["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            formatted.append({
                "timestamp": dt_str,
                "sender": item["role"],
                "message": item["content"]
            })
        return JSONResponse(content=formatted)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/models/{model_id}/load")
async def load_model_endpoint(model_id: str):
    """Force load a model into VRAM."""
    try:
        await manager.get_model(model_id)
        return {"status": "success", "message": f"Model '{model_id}' loaded successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/models/{model_id}/unload")
async def unload_model_endpoint(model_id: str):
    """Force unload a model (purge from VRAM)."""
    if model_id not in manager.backends:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found.")
    try:
        backend = manager.backends[model_id]
        await backend.unload()
        if model_id in manager.last_used:
            del manager.last_used[model_id]
        return {"status": "success", "message": f"Model '{model_id}' unloaded successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/images")
async def list_generated_images():
    """List all generated images in the static generated folder."""
    from pathlib import Path
    img_dir = Path("cerberai/static/generated")
    if not img_dir.exists():
        return JSONResponse(content=[])
    try:
        files = []
        for ext in ("*.png", "*.jpg", "*.jpeg"):
            for path in img_dir.glob(ext):
                # Exclude video or audio temp files if stored here
                if "video_" in path.name or "audio_" in path.name:
                    continue
                stat = path.stat()
                files.append({
                    "name": path.name,
                    "url": f"/static/generated/{path.name}",
                    "created": int(stat.st_mtime)
                })
        # Sort by creation time descending
        files.sort(key=lambda x: x["created"], reverse=True)
        return JSONResponse(content=files)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/media/{item_id}")
async def delete_media_item(item_id: str):
    """Delete a media history item (video, report, podcast) and its files from disk."""
    from .database import db_delete_media_history
    from pathlib import Path
    try:
        item = db_delete_media_history(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Media item not found.")
        
        # Determine the directory based on item type
        item_type = item.get("type")
        if item_type == "video":
            target_dir = Path("cerberai/static/videos")
        elif item_type == "podcast":
            target_dir = Path("cerberai/static/podcasts")
        elif item_type == "report":
            target_dir = Path("cerberai/static/reports")
        else:
            target_dir = Path("cerberai/static/generated")
            
        deleted_files = []
        for key in ("filename", "md_filename", "pdf_filename"):
            fname = item.get(key)
            if fname:
                filepath = target_dir / fname
                if filepath.exists():
                    filepath.unlink()
                    deleted_files.append(fname)
        return {"status": "success", "message": "Media item and files deleted.", "files": deleted_files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/images/{filename}")
async def delete_image_file(filename: str):
    """Delete a generated image file from the disk."""
    from pathlib import Path
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    try:
        filepath = Path("cerberai/static/generated") / filename
        if not filepath.exists():
            raise HTTPException(status_code=404, detail="Image not found on disk.")
        filepath.unlink()
        return {"status": "success", "message": f"Image '{filename}' deleted from disk."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
async def get_inference_stats():
    """Retrieve aggregated inference statistics across all time intervals."""
    from .database import db_get_aggregated_stats
    try:
        return JSONResponse(content=db_get_aggregated_stats(STARTUP_TIME))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve stats: {str(e)}")

@app.get("/api/models/registry")
async def get_model_registry():
    """Retrieve the full model registry including historical models."""
    from .database import db_get_model_registry
    try:
        return JSONResponse(content=db_get_model_registry())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve model registry: {str(e)}")

def _check_model_downloaded(m) -> bool:
    """Check if a model's weights are downloaded locally."""
    from .downloader import is_model_downloaded
    return is_model_downloaded(m.backend, m.backend_config)

# Global tracking dict for bulk download progress
_download_all_status = {"running": False, "total": 0, "completed": 0, "current_model": "", "errors": []}

@app.post("/api/models/download-all")
async def download_all_models(background_tasks: BackgroundTasks):
    """Trigger background download of all enabled llama.cpp models that are not yet cached."""
    from .downloader import is_model_downloaded, ensure_gguf_model
    global _download_all_status
    
    if _download_all_status["running"]:
        return JSONResponse(content={"message": "A bulk download is already in progress.", "status": _download_all_status})
    
    models_to_download = []
    for m in config.models:
        if m.backend == "llama.cpp" and not is_model_downloaded(m.backend, m.backend_config):
            repo_id = m.backend_config.get("repo_id", "")
            filename = m.backend_config.get("filename", "")
            if repo_id and filename:
                models_to_download.append({"id": m.id, "repo_id": repo_id, "filename": filename})
    
    if not models_to_download:
        return JSONResponse(content={"message": "All models are already downloaded.", "status": _download_all_status})
    
    _download_all_status = {"running": True, "total": len(models_to_download), "completed": 0, "current_model": "", "errors": []}
    
    async def _download_worker():
        global _download_all_status
        for entry in models_to_download:
            _download_all_status["current_model"] = entry["id"]
            try:
                print(f"[Download All] Downloading model '{entry['id']}': {entry['repo_id']}/{entry['filename']}...")
                await ensure_gguf_model(entry["repo_id"], entry["filename"])
                print(f"[Download All] Finished downloading model '{entry['id']}'.")
            except Exception as e:
                err_msg = f"{entry['id']}: {str(e)}"
                print(f"[Download All] Error downloading model '{entry['id']}': {e}")
                _download_all_status["errors"].append(err_msg)
            _download_all_status["completed"] += 1
        _download_all_status["running"] = False
        _download_all_status["current_model"] = ""
        print(f"[Download All] Bulk download complete. {_download_all_status['completed']}/{_download_all_status['total']} models processed.")
    
    asyncio.create_task(_download_worker())
    return JSONResponse(content={"message": f"Started downloading {len(models_to_download)} model(s) in background.", "status": _download_all_status})

@app.get("/api/cache/stats")
async def get_cache_stats():
    """Retrieve cache sizes and status of all cached and configured models."""
    import os
    from pathlib import Path
    from .database import get_db_connection
    import yaml
    
    # 1. Read current config to know active models
    active_models = []
    try:
        with open("config.yaml", "r") as f:
            cfg = yaml.safe_load(f)
            active_models = cfg.get("models", [])
    except Exception:
        pass
        
    active_ids = {m.get("id") for m in active_models if m.get("id")}
    active_repos = {m.get("backend_config", {}).get("repo_id") for m in active_models if m.get("backend_config", {}).get("repo_id")}
    active_filenames = {m.get("backend_config", {}).get("filename") for m in active_models if m.get("backend_config", {}).get("filename")}

    # Helper to calculate size
    def get_path_size(p: Path) -> int:
        if not p.exists():
            return 0
        if p.is_file():
            return p.stat().st_size
        total = 0
        try:
            for entry in p.rglob('*'):
                if entry.is_file():
                    total += entry.stat().st_size
        except Exception:
            pass
        return total

    # 2. Paths
    GGUF_DIR = Path(os.path.expanduser("~/.cache/cerberai/models"))
    HF_DIR = Path(os.path.expanduser("~/.cache/huggingface/hub"))
    
    # 3. Retrieve database registry
    registry_models = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM model_registry")
        rows = cursor.fetchall()
        registry_models = [dict(r) for r in rows]
        conn.close()
    except Exception:
        pass
        
    registry_by_repo = {r.get("repo_id"): r for r in registry_models if r.get("repo_id")}
    registry_by_filename = {r.get("filename"): r for r in registry_models if r.get("filename")}

    # Map of all unique models we discover
    # Key is repo_id or filename
    models_dict = {}

    # A. Scan active config models
    for m in active_models:
        m_id = m.get("id")
        backend = m.get("backend")
        m_type = m.get("type")
        bc = m.get("backend_config", {})
        repo_id = bc.get("repo_id")
        filename = bc.get("filename")
        purpose = m.get("purpose", "")
        vram = m.get("vram_estimate_gb", 0.0)
        
        key = repo_id if repo_id else filename
        if not key:
            continue
            
        # Get from registry if exists
        reg = registry_by_repo.get(repo_id) if repo_id else registry_by_filename.get(filename)
        last_seen = reg.get("last_seen") if reg else None
        display_name = reg.get("display_name") if reg else (repo_id or filename)

        # Size estimation
        size_bytes = 0
        is_downloaded = False
        if filename: # GGUF
            p = GGUF_DIR / filename
            if p.exists():
                size_bytes = get_path_size(p)
                is_downloaded = True
        elif repo_id: # HF
            folder_name = f"models--{repo_id.replace('/', '--')}"
            p = HF_DIR / folder_name
            if p.exists():
                size_bytes = get_path_size(p)
                is_downloaded = True

        models_dict[key] = {
            "id": m_id,
            "display_name": display_name,
            "type": m_type,
            "backend": backend,
            "repo_id": repo_id,
            "filename": filename,
            "purpose": purpose,
            "vram_estimate_gb": vram,
            "is_configured": True,
            "is_downloaded": is_downloaded,
            "size_bytes": size_bytes,
            "last_used": last_seen
        }

    # B. Scan database registry for historical models not in active config
    for reg in registry_models:
        repo_id = reg.get("repo_id")
        filename = reg.get("filename")
        key = repo_id if repo_id else filename
        if not key or key in models_dict:
            continue

        size_bytes = 0
        is_downloaded = False
        if filename:
            p = GGUF_DIR / filename
            if p.exists():
                size_bytes = get_path_size(p)
                is_downloaded = True
        elif repo_id:
            folder_name = f"models--{repo_id.replace('/', '--')}"
            p = HF_DIR / folder_name
            if p.exists():
                size_bytes = get_path_size(p)
                is_downloaded = True

        models_dict[key] = {
            "id": reg.get("function_id"),
            "display_name": reg.get("display_name") or repo_id or filename,
            "type": reg.get("model_type"),
            "backend": reg.get("backend"),
            "repo_id": repo_id,
            "filename": filename,
            "purpose": reg.get("purpose", ""),
            "vram_estimate_gb": reg.get("vram_estimate_gb", 0.0),
            "is_configured": False,
            "is_downloaded": is_downloaded,
            "size_bytes": size_bytes,
            "last_used": reg.get("last_seen")
        }

    # C. Scan disk directories for any model files not in config or registry
    # Check GGUF models
    if GGUF_DIR.exists():
        try:
            for item in GGUF_DIR.glob("*.gguf"):
                if item.is_file() and item.name not in models_dict:
                    size_bytes = get_path_size(item)
                    models_dict[item.name] = {
                        "id": None,
                        "display_name": item.name,
                        "type": "llm",
                        "backend": "llama.cpp",
                        "repo_id": None,
                        "filename": item.name,
                        "purpose": "Unconfigured GGUF model in cache",
                        "vram_estimate_gb": 0.0,
                        "is_configured": False,
                        "is_downloaded": True,
                        "size_bytes": size_bytes,
                        "last_used": item.stat().st_mtime
                    }
        except Exception:
            pass

    # Check HF models
    if HF_DIR.exists():
        try:
            for item in HF_DIR.glob("models--*"):
                if item.is_dir():
                    # Parse repo ID
                    folder_name = item.name
                    parts = folder_name[8:].split("--")
                    repo_id = "/".join(parts)
                    if repo_id not in models_dict:
                        size_bytes = get_path_size(item)
                        # Infer type from name
                        lower_repo = repo_id.lower()
                        m_type = "llm"
                        backend = "diffusers"
                        if "whisper" in lower_repo or "moonshine" in lower_repo:
                            m_type = "stt"
                            backend = "whisper"
                        elif "kokoro" in lower_repo or "tts" in lower_repo:
                            m_type = "tts"
                            backend = "tts"
                        elif "wan" in lower_repo or "cogvideo" in lower_repo or "ltx" in lower_repo or "hunyuan" in lower_repo or "svd" in lower_repo or "img2vid" in lower_repo:
                            m_type = "video"
                            backend = "video"
                        elif "sd" in lower_repo or "flux" in lower_repo or "diffusion" in lower_repo:
                            m_type = "image"
                            backend = "diffusers"

                        models_dict[repo_id] = {
                            "id": None,
                            "display_name": repo_id,
                            "type": m_type,
                            "backend": backend,
                            "repo_id": repo_id,
                            "filename": None,
                            "purpose": "Unconfigured HF model in cache",
                            "vram_estimate_gb": 0.0,
                            "is_configured": False,
                            "is_downloaded": True,
                            "size_bytes": size_bytes,
                            "last_used": item.stat().st_mtime
                        }
        except Exception:
            pass

    # Calculate overall cache stats
    total_gguf_size = 0
    if GGUF_DIR.exists():
        total_gguf_size = get_path_size(GGUF_DIR)
        
    total_hf_size = 0
    if HF_DIR.exists():
        total_hf_size = get_path_size(HF_DIR)

    return JSONResponse(content={
        "total_gguf_size_bytes": total_gguf_size,
        "total_hf_size_bytes": total_hf_size,
        "total_cache_size_bytes": total_gguf_size + total_hf_size,
        "models": list(models_dict.values())
    })

@app.delete("/api/cache/models")
async def delete_model_cache(request: Request):
    """Delete a cached model's files from disk to free up space."""
    import os
    import shutil
    from pathlib import Path
    
    try:
        payload = await request.json()
        filename = payload.get("filename")
        repo_id = payload.get("repo_id")
        
        if not filename and not repo_id:
            raise HTTPException(status_code=400, detail="Either filename or repo_id must be provided.")
            
        deleted_size = 0
        deleted_path = ""
        
        if filename: # GGUF
            GGUF_DIR = Path(os.path.expanduser("~/.cache/cerberai/models"))
            p = GGUF_DIR / filename
            if p.exists():
                deleted_size = p.stat().st_size
                p.unlink()
                deleted_path = str(p)
            else:
                return JSONResponse(status_code=404, content={"message": f"File {filename} not found in GGUF cache."})
        elif repo_id: # HF
            HF_DIR = Path(os.path.expanduser("~/.cache/huggingface/hub"))
            folder_name = f"models--{repo_id.replace('/', '--')}"
            p = HF_DIR / folder_name
            if p.exists():
                # Helper to count size before deleting
                def get_dir_size(path: Path) -> int:
                    total = 0
                    for entry in path.rglob('*'):
                        if entry.is_file():
                            total += entry.stat().st_size
                    return total
                deleted_size = get_dir_size(p)
                shutil.rmtree(p)
                deleted_path = str(p)
                
                # Also delete associated lock file if it exists
                lock_file = HF_DIR / f".locks/models--{repo_id.replace('/', '--')}"
                if lock_file.exists():
                    try:
                        if lock_file.is_file():
                            lock_file.unlink()
                        else:
                            shutil.rmtree(lock_file)
                    except Exception:
                        pass
            else:
                return JSONResponse(status_code=404, content={"message": f"Repository {repo_id} not found in Hugging Face cache."})
                
        return JSONResponse(content={
            "success": True,
            "message": f"Successfully deleted model cache at {deleted_path}",
            "deleted_size_bytes": deleted_size
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete model cache: {str(e)}")

@app.get("/api/config")
async def get_current_config():
    """Retrieve the raw configuration values directly from config.yaml."""
    import yaml
    try:
        with open("config.yaml", "r") as f:
            data = yaml.safe_load(f)
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read config: {str(e)}")

@app.post("/api/config")
async def save_config(request: Request):
    """Save the updated configuration payload to config.yaml and reload it in the active server memory."""
    global config, manager, agent
    import yaml
    try:
        new_data = await request.json()
        
        # Verify basic structure
        if "models" not in new_data or "resource_limits" not in new_data:
            raise HTTPException(status_code=400, detail="Invalid config format. Missing 'models' or 'resource_limits'.")
            
        # Write to config.yaml
        with open("config.yaml", "w") as f:
            yaml.safe_dump(new_data, f, default_flow_style=False)
            
        # Unload all currently loaded models first
        await manager.unload_all()
        
        # Reload configuration in memory
        from .config import load_config
        config = load_config()
        if config.hf_token:
            os.environ["HF_TOKEN"] = config.hf_token
        else:
            os.environ.pop("HF_TOKEN", None)
        manager = DynamicModelManager(config)
        
        # Update the agent executor references
        agent.config = config
        agent.manager = manager
        agent.reload_tools()  # Rescan tools if models changed
        
        return JSONResponse(content={"message": "Configuration updated and reloaded successfully!"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save or reload config: {str(e)}")

@app.get("/api/mcp/servers")
async def get_mcp_servers():
    """Retrieve details and running statuses of all configured MCP servers."""
    try:
        servers = []
        for name, client in mcp_manager.clients.items():
            servers.append({
                "name": name,
                "command": client.command,
                "args": client.args,
                "is_running": client._running and client.process is not None
            })
        for name, cfg in getattr(config, "mcp_servers", {}).items():
            if name not in mcp_manager.clients:
                servers.append({
                    "name": name,
                    "command": cfg.get("command"),
                    "args": cfg.get("args", []),
                    "is_running": False
                })
        return JSONResponse(content={"servers": servers})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/mcp/tools")
async def get_mcp_tools():
    """Retrieve all available tools exposed by active MCP servers."""
    try:
        tools = await mcp_manager.get_all_tools()
        return JSONResponse(content={"tools": tools})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mcp/call")
async def call_mcp_tool(request: Request):
    """Execute a tool call against a specific MCP server."""
    try:
        body = await request.json()
        server_name = body.get("server_name")
        tool_name = body.get("tool_name")
        arguments = body.get("arguments", {})
        
        if not server_name or not tool_name:
            raise HTTPException(status_code=400, detail="Missing server_name or tool_name parameters.")
            
        result = await mcp_manager.call_tool(server_name, tool_name, arguments)
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jobs")
async def get_jobs():
    """Retrieve list of all enqueued and running agent jobs."""
    from .database import db_list_jobs
    try:
        return JSONResponse(content=db_list_jobs())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Retrieve details for a specific orchestrator job."""
    from .database import db_get_job
    try:
        job = db_get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return JSONResponse(content=job)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jobs/queue/status")
async def get_queue_status():
    """Get the current paused status of the orchestrator queue."""
    return JSONResponse(content={"paused": orchestrator.paused})

@app.post("/api/jobs/queue/toggle")
async def toggle_queue():
    """Toggle the orchestrator queue between active and paused."""
    orchestrator.paused = not orchestrator.paused
    print(f"Orchestrator queue paused state toggled to: {orchestrator.paused}")
    return JSONResponse(content={"paused": orchestrator.paused})

@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a running job or delete a pending job from the queue."""
    from .database import db_get_job, db_update_job_status, db_delete_job
    try:
        job = db_get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        status = job["status"]
        if status == "running":
            if job_id in orchestrator.running_jobs:
                task = orchestrator.running_jobs[job_id]
                task.cancel()
                db_update_job_status(job_id, "failed", progress=0.0, error="Cancelled by user")
            else:
                db_update_job_status(job_id, "failed", progress=0.0, error="Cancelled by user")
        elif status == "pending":
            db_delete_job(job_id)
            
        return JSONResponse(content={"success": True, "message": "Job cancelled and removed."})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jobs/{job_id}/move")
async def move_job(job_id: str, request: Request):
    """Move a pending job up or down in the queue."""
    from .database import db_move_job
    try:
        body = await request.json()
        direction = body.get("direction")
        if direction not in ("up", "down"):
            raise HTTPException(status_code=400, detail="Direction must be 'up' or 'down'")
            
        success = db_move_job(job_id, direction)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to move job (e.g. not pending or already at end)")
            
        return JSONResponse(content={"success": True})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/conversations")
async def get_conversations_endpoint():
    """List all stored conversations."""
    from .conversations import list_conversations
    try:
        return JSONResponse(content=list_conversations())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/conversations/{conv_id}")
async def get_conversation_endpoint(conv_id: str):
    """Retrieve full details of a specific conversation."""
    from .conversations import get_conversation
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return JSONResponse(content=conv)

@app.post("/api/conversations")
async def create_conversation_endpoint(request: Request):
    """Create a new conversation."""
    from .conversations import create_conversation
    try:
        payload = await request.json()
        title = payload.get("title", "New Chat")
        conv = create_conversation(title)
        return JSONResponse(content=conv)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/conversations/{conv_id}")
async def update_conversation_endpoint(conv_id: str, request: Request):
    """Update/save a conversation's messages and metadata."""
    from .conversations import save_conversation
    try:
        data = await request.json()
        if data.get("id") != conv_id:
            raise HTTPException(status_code=400, detail="Conversation ID mismatch")
        save_conversation(data)
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/conversations/{conv_id}")
async def delete_conversation_endpoint(conv_id: str):
    """Delete a conversation."""
    from .conversations import delete_conversation
    if delete_conversation(conv_id):
        return JSONResponse(content={"status": "success"})
    raise HTTPException(status_code=404, detail="Conversation not found")

if __name__ == "__main__":
    is_frozen = getattr(sys, 'frozen', False)
    uvicorn.run(
        app if is_frozen else "cerberai.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=False if is_frozen else True
    )


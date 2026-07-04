import os
import asyncio
import base64
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
if config.hf_token:
    os.environ["HF_TOKEN"] = config.hf_token

# Initialize managers
manager = DynamicModelManager(config)
router = IntentRouter(config.router, config.models)
agent = AgentExecutor(config)
cleanup_task = None
scheduler_task = None
telegram_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: launch background tasks
    global cleanup_task, scheduler_task, telegram_task
    cleanup_task = asyncio.create_task(manager.start_cleanup_loop())
    
    from .schedules import start_scheduler_loop
    scheduler_task = asyncio.create_task(start_scheduler_loop(config, manager, agent))
    
    from .telegram import start_telegram_loop
    telegram_task = asyncio.create_task(start_telegram_loop(config, manager, agent))
    
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
                "n_ctx": getattr(cfg, "n_ctx", None),
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
        "loading_status": manager.loading_status,
        "all_configured_models": [
            {
                "id": m.id,
                "type": m.type,
                "backend": m.backend,
                "vram_estimate_gb": m.vram_estimate_gb,
                "n_ctx": getattr(m, "n_ctx", None)
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
    return {"object": "list", "data": data}

from typing import AsyncIterator

async def stream_with_metrics(generator: AsyncIterator[bytes], model_id: str) -> AsyncIterator[bytes]:
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
            
            # Save the image to the static generated assets folder
            import uuid
            img_filename = f"image_{uuid.uuid4().hex}.png"
            img_dir = os.path.join("cerberai", "static", "generated")
            os.makedirs(img_dir, exist_ok=True)
            img_path = os.path.join(img_dir, img_filename)
            with open(img_path, "wb") as fh:
                fh.write(base64.b64decode(b64_data))
            
            static_url = f"/static/generated/{img_filename}"
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
                                
                            static_url = f"/static/generated/{vid_filename}"
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
                
                static_url = f"/static/generated/{vid_filename}"
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
                    stream_with_metrics(backend.stream_chat_completion(payload), target_model_id),
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
                
            static_url = f"/static/generated/{audio_filename}"
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

    if tools_enabled and agent.tools and model_cfg and model_cfg.type == "llm":
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

            loop_limit = 5
            for step in range(loop_limit):
                response = await backend.handle_chat_completion(local_payload)
                content = response["choices"][0]["message"]["content"]
                
                # Check for tool call tags
                match = re.search(r"<tool_call>(.*?)</tool_call>", content, re.DOTALL)
                if match:
                    tool_call_json = match.group(1).strip()
                    tool_result = await agent.execute_tool(tool_call_json)
                    
                    # Append history
                    local_messages.append({"role": "assistant", "content": content})
                    local_messages.append({
                        "role": "user",
                        "content": f"[TOOL RESPONSE]\n{tool_result}"
                    })
                    local_payload["messages"] = local_messages
                    continue
                else:
                    # Final response reached!
                    end_time = time.time()
                    wall_time = end_time - start_time
                    completion_tokens = 0
                    if "usage" in response and "completion_tokens" in response["usage"]:
                        completion_tokens = response["usage"]["completion_tokens"]
                    else:
                        completion_tokens = max(1, len(content) // 4)
                        
                    tps = completion_tokens / wall_time if wall_time > 0 else 0.0
                    metrics = {
                        "model": target_model_id,
                        "wall_time_sec": wall_time,
                        "completion_tokens": completion_tokens,
                        "tokens_per_second": tps
                    }
                    
                    if stream:
                        async def stream_pregenerated():
                            yield f"data: {json.dumps({'choices': [{'delta': {'role': 'assistant', 'content': ''}, 'index': 0, 'finish_reason': None}]})}\n\n"
                            yield f"data: {json.dumps({'choices': [{'delta': {'content': content}, 'index': 0, 'finish_reason': None}]})}\n\n"
                            yield f"data: {json.dumps({'metrics': metrics})}\n\n"
                            yield f"data: {json.dumps({'choices': [{'delta': {}, 'index': 0, 'finish_reason': 'stop'}]})}\n\n"
                            yield "data: [DONE]\n\n"
                        return StreamingResponse(stream_pregenerated(), media_type="text/event-stream")
                    else:
                        response["metrics"] = metrics
                        return JSONResponse(content=response)
            
            # If loop limit exceeded, return last response
            end_time = time.time()
            wall_time = end_time - start_time
            completion_tokens = max(1, len(content) // 4)
            tps = completion_tokens / wall_time if wall_time > 0 else 0.0
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
                stream_with_metrics(backend.stream_chat_completion(payload), target_model_id),
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
async def start_news_video_automation(request: Request, background_tasks: BackgroundTasks):
    """Trigger the news video generation workflow in the background."""
    from .automation import generate_yesterday_news_video, get_status, update_status
    
    current_status = get_status()
    if current_status["status"] == "running":
        return JSONResponse(content={"message": "Automation is already running.", "status": current_status})
        
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
        
    update_status("running", 0, "Starting automation task...")
    background_tasks.add_task(generate_yesterday_news_video, manager, agent, topic, date_str, video_mode)
    return JSONResponse(content={"message": "Automation started successfully.", "status": get_status()})

@app.get("/v1/automate/news-video/status")
async def get_news_video_automation_status():
    """Retrieve the real-time status of the news video automation task."""
    from .automation import get_status
    return JSONResponse(content=get_status())

@app.get("/v1/automate/news-video/history")
async def get_news_video_history():
    """Retrieve the history list of generated news videos."""
    import json
    from pathlib import Path
    history_path = Path("cerberai/static/videos/history.json")
    if not history_path.exists():
        return JSONResponse(content=[])
    try:
        with open(history_path, "r") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read history: {str(e)}")


@app.post("/v1/automate/deep-research")
async def start_deep_research_automation(request: Request, background_tasks: BackgroundTasks):
    """Trigger the recursive deep research report workflow in the background."""
    from .automation import generate_deep_research_report, get_research_status, update_research_status
    
    current_status = get_research_status()
    if current_status["status"] == "running":
        return JSONResponse(content={"message": "Research task is already running.", "status": current_status})
        
    query = None
    try:
        payload = await request.json()
        query = payload.get("query")
    except Exception:
        pass
        
    if not query:
        raise HTTPException(status_code=400, detail="Query parameter is required.")
        
    update_research_status("running", 0, "Initializing deep research agent loop...", query=query)
    background_tasks.add_task(generate_deep_research_report, manager, agent, query)
    return JSONResponse(content={"message": "Deep Research automation started.", "status": get_research_status()})

@app.get("/v1/automate/deep-research/status")
async def get_deep_research_status_endpoint():
    """Retrieve the real-time status of the deep research task."""
    from .automation import get_research_status
    return JSONResponse(content=get_research_status())

@app.get("/v1/automate/deep-research/history")
async def get_deep_research_history():
    """Retrieve the history list of generated deep research reports."""
    import json
    from pathlib import Path
    history_path = Path("cerberai/static/reports/history.json")
    if not history_path.exists():
        return JSONResponse(content=[])
    try:
        with open(history_path, "r") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read history: {str(e)}")


@app.post("/v1/automate/podcast")
async def start_podcast_automation(request: Request, background_tasks: BackgroundTasks):
    """Trigger the daily podcast news briefing generation in the background."""
    from .automation import generate_daily_podcast, get_podcast_status, update_podcast_status
    
    current_status = get_podcast_status()
    if current_status["status"] == "running":
        return JSONResponse(content={"message": "Podcast briefing task is already running.", "status": current_status})
        
    topic = None
    date_str = None
    try:
        payload = await request.json()
        topic = payload.get("topic")
        date_str = payload.get("date")
    except Exception:
        pass
        
    update_podcast_status("running", 0, "Initializing multi-speaker podcast generation...", query=topic)
    background_tasks.add_task(generate_daily_podcast, manager, agent, topic, date_str)
    return JSONResponse(content={"message": "Podcast briefing automation started.", "status": get_podcast_status()})

@app.get("/v1/automate/podcast/status")
async def get_podcast_status_endpoint():
    """Retrieve the real-time status of the podcast briefing generation."""
    from .automation import get_podcast_status
    return JSONResponse(content=get_podcast_status())

@app.get("/v1/automate/podcast/history")
async def get_podcast_history():
    """Retrieve the history list of generated podcasts."""
    import json
    from pathlib import Path
    history_path = Path("cerberai/static/podcasts/history.json")
    if not history_path.exists():
        return JSONResponse(content=[])
    try:
        with open(history_path, "r") as f:
            data = json.load(f)
        return JSONResponse(content=data)
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
    import json
    from pathlib import Path
    log_path = Path("cerberai/static/telegram_history.json")
    if not log_path.exists():
        return JSONResponse(content=[])
    try:
        with open(log_path, "r") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
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
        agent.tools = agent._scan_and_load_tools()  # Rescan tools if models changed
        
        return JSONResponse(content={"message": "Configuration updated and reloaded successfully!"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save or reload config: {str(e)}")

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
    uvicorn.run(
        "cerberai.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=True
    )


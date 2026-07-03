import os
import json
import asyncio
import re
import httpx
from pathlib import Path
from typing import Dict, Any

def log_telegram_interaction(sender: str, message: str):
    """Log user/bot telegram messages into a static JSON history array."""
    import datetime
    log_path = Path("cerberai/static/telegram_history.json")
    history = []
    if log_path.exists():
        try:
            with open(log_path, "r") as f:
                history = json.load(f)
        except Exception:
            pass
            
    new_entry = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sender": sender,
        "message": message
    }
    history.insert(0, new_entry)
    history = history[:100]
    
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_path, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Failed to log Telegram interaction: {e}")

async def send_telegram_voice(config, voice_bytes: bytes, caption: str = None):
    """Upload and send a raw voice note (OGG/Opus) via Telegram Bot API."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendVoice"
    try:
        log_telegram_interaction("Bot", f"[Voice note sent] {caption if caption else ''}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"voice": ("voice.ogg", voice_bytes, "audio/ogg")}
            data = {"chat_id": config.telegram_chat_id}
            if caption:
                data["caption"] = caption
            response = await client.post(url, data=data, files=files)
            if response.status_code != 200:
                print(f"Failed to send Telegram voice: {response.text}")
    except Exception as e:
        print(f"Failed to send Telegram voice: {e}")

async def convert_wav_to_ogg(wav_bytes: bytes) -> bytes:
    """Convert raw WAV audio bytes to OGG/Opus using FFmpeg."""
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f_in:
        f_in.write(wav_bytes)
        in_path = f_in.name
        
    out_path = in_path.replace(".wav", ".ogg")
    try:
        cmd = ["ffmpeg", "-y", "-i", in_path, "-c:a", "libopus", out_path]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        with open(out_path, "rb") as f_out:
            return f_out.read()
    finally:
        for p in (in_path, out_path):
            try:
                os.unlink(p)
            except Exception:
                pass

async def convert_ogg_to_wav(ogg_bytes: bytes) -> bytes:
    """Convert raw OGG audio bytes to WAV (16kHz, mono) using FFmpeg for STT processing."""
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as f_in:
        f_in.write(ogg_bytes)
        in_path = f_in.name
        
    out_path = in_path.replace(".ogg", ".wav")
    try:
        cmd = ["ffmpeg", "-y", "-i", in_path, "-ar", "16000", "-ac", "1", out_path]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        with open(out_path, "rb") as f_out:
            return f_out.read()
    finally:
        for p in (in_path, out_path):
            try:
                os.unlink(p)
            except Exception:
                pass

async def send_telegram_photo(config, photo_path: str, caption: str = None):
    """Upload and send a local photo file via Telegram Bot API."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendPhoto"
    if not os.path.exists(photo_path):
        print(f"Telegram photo upload failed: file does not exist at {photo_path}")
        return
    try:
        log_telegram_interaction("Bot", f"[Photo sent] {caption if caption else ''}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": config.telegram_chat_id}
                if caption:
                    data["caption"] = caption
                response = await client.post(url, data=data, files=files)
                if response.status_code != 200:
                    print(f"Failed to send Telegram photo: {response.text}")
    except Exception as e:
        print(f"Failed to send Telegram photo: {e}")

async def send_telegram_message(config, text: str):
    """Send a markdown formatted text message via Telegram Bot API."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return
    log_telegram_interaction("Bot", text)
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": config.telegram_chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

async def send_telegram_video(config, video_path: str, caption: str):
    """Upload and send a local video file via Telegram Bot API."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return
    log_telegram_interaction("Bot", f"[Video File Sent] {caption}")
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendVideo"
    if not os.path.exists(video_path):
        print(f"Telegram video upload failed: file does not exist at {video_path}")
        return
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(video_path, "rb") as f:
                files = {"video": f}
                data = {
                    "chat_id": config.telegram_chat_id, 
                    "caption": caption
                }
                await client.post(url, data=data, files=files)
    except Exception as e:
        print(f"Failed to send Telegram video: {e}")

async def handle_telegram_message(text: str, config, manager, agent, reply_with_tts: bool = False):
    """Routing and command processing for incoming Telegram messages."""
    text_lower = text.lower()
    
    # 1. HELP / START Command
    if text_lower in ("/start", "/help"):
        help_msg = (
            "🤖 **CerberAI Telegram Bot Interface**\n\n"
            "Here are the available commands:\n"
            "• `/help` - Show this instructions menu.\n"
            "• `/chat <your prompt>` - Query the active LLM router.\n"
            "• `/history` - View stored WebUI chat conversations.\n"
            "• `/videos` - View generated video history catalog.\n"
            "• `/sendvideo <video_id>` - Download a video from history.\n"
            "• `/logs` - Read recent server logs (`llama.log`).\n"
            "• `/schedules` - List all configured daily schedules.\n"
            "• `/run [topic]` - Manually trigger a news video generation.\n\n"
            "Or simply send a direct message, and I will route it and respond!\n"
            "🎤 You can also send me a voice note to get voice and text answers!"
        )
        await send_telegram_message(config, help_msg)
        return
        
    # 2. CHAT / DIRECT QUERY Command
    elif text_lower.startswith("/chat ") or not text.startswith("/"):
        prompt = text[6:].strip() if text_lower.startswith("/chat ") else text
        if not prompt:
            await send_telegram_message(config, "⚠️ Please provide a prompt query.")
            return
            
        await send_telegram_message(config, "🤔 Thinking...")
        try:
            from .router import IntentRouter
            router = IntentRouter(config.router, config.models)
            messages = [{"role": "user", "content": prompt}]
            target_model_id = await router.route_chat(messages, "auto", manager)
            
            # Verify model type and capabilities
            model_cfg = next((m for m in config.models if m.id == target_model_id), None)
            if not model_cfg:
                await send_telegram_message(config, f"❌ Error: Model `{target_model_id}` is not configured.")
                return
                
            backend = await manager.get_model(target_model_id)
            
            # Special case for image generation
            if model_cfg.type == "image":
                await send_telegram_message(config, "🎨 Generating image...")
                img_result = await backend.handle_image_generation({"prompt": prompt})
                b64_data = img_result["data"][0]["b64_json"]
                
                import uuid
                import base64
                img_filename = f"image_{uuid.uuid4().hex}.png"
                img_dir = os.path.join("cerberai", "static", "generated")
                os.makedirs(img_dir, exist_ok=True)
                img_path = os.path.join(img_dir, img_filename)
                with open(img_path, "wb") as fh:
                    fh.write(base64.b64decode(b64_data))
                
                await send_telegram_photo(config, img_path, f"🎨 Generated Image for: \"{prompt}\"")
                return
                
            # STT and TTS models do not support chat completion
            if model_cfg.type not in ("llm", "vision"):
                await send_telegram_message(config, f"⚠️ The selected model `{target_model_id}` (type: {model_cfg.type}) does not support text chat completions.")
                return
                
            payload = {
                "messages": messages,
                "temperature": 0.7
            }
            # Execute completion
            response = await backend.handle_chat_completion(payload)
            ans = response["choices"][0]["message"]["content"]
            await send_telegram_message(config, f"💬 **Response ({target_model_id}):**\n\n{ans}")
            
            if reply_with_tts:
                try:
                    await send_telegram_message(config, "🎤 Synthesizing voice response...")
                    tts_backend = await manager.get_model("tts-offline")
                    wav_bytes = await tts_backend.handle_audio_speech({"input": ans})
                    ogg_bytes = await convert_wav_to_ogg(wav_bytes)
                    await send_telegram_voice(config, ogg_bytes, f"Voice response ({target_model_id})")
                except Exception as ttse:
                    print(f"Failed to generate Telegram voice response: {ttse}")
                    await send_telegram_message(config, "⚠️ Failed to generate voice response.")
        except Exception as e:
            await send_telegram_message(config, f"❌ Error querying model: {e}")
            
    # 3. CHAT HISTORIES Command
    elif text_lower == "/history":
        from .conversations import list_conversations
        try:
            convs = list_conversations()
            if not convs:
                await send_telegram_message(config, "💬 No stored conversation histories found.")
                return
            lines = []
            for c in convs[:15]:
                lines.append(f"• `{c['title']}` (ID: `{c['id']}`)")
            await send_telegram_message(config, "💬 **Recent Chat Histories:**\n\n" + "\n".join(lines))
        except Exception as e:
            await send_telegram_message(config, f"Error reading histories: {e}")
            
    # 4. VIDEOS HISTORY CATALOG Command
    elif text_lower == "/videos":
        history_path = Path("cerberai/static/videos/history.json")
        if not history_path.exists():
            await send_telegram_message(config, "🎬 No generated videos history found.")
            return
        try:
            with open(history_path, "r") as f:
                data = json.load(f)
            if not data:
                await send_telegram_message(config, "🎬 No generated videos history found.")
                return
            lines = []
            for i, item in enumerate(data[:10]):
                lines.append(
                    f"{i+1}. **{item['topic']}** (Date: {item['date']})\n"
                    f"   Reply: `/sendvideo {item['id']}`"
                )
            await send_telegram_message(config, "🎬 **Generated Videos History:**\n\n" + "\n\n".join(lines))
        except Exception as e:
            await send_telegram_message(config, f"Error reading video history: {e}")
            
    # 5. SEND VIDEO FILE Command
    elif text_lower.startswith("/sendvideo "):
        video_id = text[11:].strip()
        if not video_id:
            await send_telegram_message(config, "⚠️ Please provide a video ID.")
            return
        video_filename = f"{video_id}.mp4"
        video_path = f"cerberai/static/videos/{video_filename}"
        if not os.path.exists(video_path):
            await send_telegram_message(config, f"❌ Video file `{video_filename}` does not exist.")
            return
            
        # Try to extract stories from history to send as links in the caption
        stories_caption = ""
        try:
            history_path = Path("cerberai/static/videos/history.json")
            if history_path.exists():
                with open(history_path, "r") as hf:
                    h_data = json.load(hf)
                matched = [x for x in h_data if x.get("id") == video_id]
                if matched and "stories" in matched[0]:
                    story_links = []
                    for s in matched[0]["stories"]:
                        if s.get("source_url") and s.get("title"):
                            story_links.append(f"• [{s['title']}]({s['source_url']})")
                    if story_links:
                        stories_caption = "\n\n📰 **Featured Stories:**\n" + "\n".join(story_links[:5])
        except Exception as ex:
            print(f"Failed to lookup stories for Telegram caption: {ex}")
            
        await send_telegram_message(config, f"📤 Sending video file `{video_filename}`...")
        await send_telegram_video(config, video_path, f"🎬 **Breaking News Video**\nID: {video_id}{stories_caption}")
        
    # 6. LOGS RETRIEVAL Command
    elif text_lower == "/logs":
        log_path = Path("llama.log")
        if not log_path.exists():
            await send_telegram_message(config, "📋 No log file (`llama.log`) found.")
            return
        try:
            with open(log_path, "r") as f:
                lines = f.readlines()
            last_lines = "".join(lines[-25:])
            await send_telegram_message(config, f"📋 **Recent Logs (Last 25 lines):**\n```\n{last_lines}\n```")
        except Exception as e:
            await send_telegram_message(config, f"Error reading logs: {e}")
            
    # 7. ACTIVE SCHEDULES LIST Command
    elif text_lower == "/schedules":
        from .schedules import load_schedules
        try:
            sch = load_schedules()
            if not sch:
                await send_telegram_message(config, "⏰ No active daily schedules configured.")
                return
            lines = []
            for s in sch:
                lines.append(f"• `{s.get('time')}` - **{s.get('type').upper()}**: `{s.get('target')}`")
            await send_telegram_message(config, "⏰ **Active Daily Schedules:**\n\n" + "\n".join(lines))
        except Exception as e:
            await send_telegram_message(config, f"Error listing schedules: {e}")
            
    # 8. RUN AUTOMATION Command
    elif text_lower.startswith("/run"):
        topic = text[4:].strip() if len(text) > 4 else None
        await send_telegram_message(config, f"🚀 Initiating video generation task (Topic: `{topic if topic else 'World News'}`)...")
        
        # We start the news video generation in the background
        async def run_and_notify():
            from .automation import generate_yesterday_news_video, get_status
            await generate_yesterday_news_video(manager, agent, topic)
            status_data = get_status()
            if status_data["status"] == "completed":
                video_url = status_data["video_url"]
                video_path = video_url.replace("/static/videos/", "cerberai/static/videos/")
                stories = status_data.get("stories", [])
                
                story_links = []
                for s in stories:
                    if s.get("source_url") and s.get("title"):
                        story_links.append(f"• [{s['title']}]({s['source_url']})")
                stories_caption = ""
                if story_links:
                    stories_caption = "\n\n📰 **Featured Stories:**\n" + "\n".join(story_links[:5])
                    
                await send_telegram_message(config, f"✅ Video generation complete for: `{topic if topic else 'World News'}`")
                await send_telegram_video(config, video_path, f"🎬 **Breaking News:** {topic if topic else 'World News'}{stories_caption}")
            else:
                await send_telegram_message(config, f"❌ Video generation failed: {status_data['message']}")
                
        asyncio.create_task(run_and_notify())

async def start_telegram_loop(config, manager, agent):
    """Background polling loop using Telegram Bot API getUpdates."""
    if not config.telegram_bot_token:
        print("Telegram bot token is not configured. Telegram bot disabled.")
        return
        
    print("Telegram bot polling loop active.")
    offset = 0
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/getUpdates"
    
    # Simple polling loop
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                # getUpdates with offset and long polling timeout
                params = {"offset": offset, "timeout": 20}
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    result = data.get("result", [])
                    for update in result:
                        update_id = update.get("update_id")
                        offset = update_id + 1
                        
                        message = update.get("message")
                        if not message:
                            continue
                            
                        chat_id = message.get("chat", {}).get("id")
                        text = message.get("text", "").strip()
                        
                        # Auto-bind chat id if missing
                        if not config.telegram_chat_id:
                            config.telegram_chat_id = str(chat_id)
                            # Save back to config.yaml
                            import yaml
                            try:
                                with open("config.yaml", "r") as f:
                                    raw_config = yaml.safe_load(f)
                                raw_config["telegram_chat_id"] = str(chat_id)
                                with open("config.yaml", "w") as f:
                                    yaml.safe_dump(raw_config, f, default_flow_style=False)
                            except Exception as ex:
                                print(f"Warning: Failed to save telegram_chat_id to config.yaml: {ex}")
                                
                            print(f"Telegram Bot bound to chat_id: {chat_id}")
                            await send_telegram_message(config, f"🤖 Telegram Bot bound to Chat ID: `{chat_id}`!")
                            
                        # Ignore messages from other chats for safety
                        if str(chat_id) != str(config.telegram_chat_id):
                            print(f"Ignored unauthorized message from chat_id {chat_id}")
                            continue
                            
                        # Check for Voice Note payload
                        voice = message.get("voice")
                        if voice:
                            file_id = voice["file_id"]
                            await send_telegram_message(config, "🎙️ Processing your voice message...")
                            
                            file_info_url = f"https://api.telegram.org/bot{config.telegram_bot_token}/getFile?file_id={file_id}"
                            try:
                                async with httpx.AsyncClient() as c_client:
                                    info_res = await c_client.get(file_info_url)
                                    if info_res.status_code == 200:
                                        info_data = info_res.json()
                                        file_path = info_data.get("result", {}).get("file_path")
                                        if file_path:
                                            file_dl_url = f"https://api.telegram.org/file/bot{config.telegram_bot_token}/{file_path}"
                                            dl_res = await c_client.get(file_dl_url)
                                            if dl_res.status_code == 200:
                                                ogg_bytes = dl_res.content
                                                
                                                # Convert OGG to WAV
                                                wav_bytes = await convert_ogg_to_wav(ogg_bytes)
                                                
                                                # Transcribe WAV to text
                                                whisper_backend = await manager.get_model("stt-whisper")
                                                stt_res = await whisper_backend.handle_audio_transcription(wav_bytes, "voice.wav", {})
                                                transcribed = stt_res.get("text", "").strip()
                                                
                                                if transcribed:
                                                    log_telegram_interaction("User", f"[Voice Note] {transcribed}")
                                                    await send_telegram_message(config, f"📝 **Transcribed:** \"{transcribed}\"")
                                                    # Process normally, requesting tts reply
                                                    asyncio.create_task(handle_telegram_message(transcribed, config, manager, agent, reply_with_tts=True))
                                                else:
                                                    await send_telegram_message(config, "⚠️ Could not understand the voice message.")
                                            else:
                                                await send_telegram_message(config, "❌ Failed to download voice file.")
                                        else:
                                            await send_telegram_message(config, "❌ Could not retrieve voice path.")
                                    else:
                                        await send_telegram_message(config, "❌ Failed to get voice file metadata.")
                            except Exception as ex:
                                print(f"Voice message handling exception: {ex}")
                                await send_telegram_message(config, f"❌ Error processing voice note: {ex}")
                            continue
                            
                        if not text:
                            continue
                        
                        log_telegram_interaction("User", text)
                            
                        # Handle message asynchronously to avoid blocking the polling loop
                        asyncio.create_task(handle_telegram_message(text, config, manager, agent, reply_with_tts=False))
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in telegram bot loop: {e}")
                await asyncio.sleep(5.0)  # Wait on error

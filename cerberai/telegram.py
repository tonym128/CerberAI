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

async def handle_telegram_message(text: str, config, manager, agent):
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
            "Or simply send a direct message, and I will route it and respond!"
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
            backend = await manager.get_model(target_model_id)
            payload = {
                "messages": messages,
                "temperature": 0.7
            }
            # Execute completion
            response = await backend.handle_chat_completion(payload)
            ans = response["choices"][0]["message"]["content"]
            await send_telegram_message(config, f"💬 **Response ({target_model_id}):**\n\n{ans}")
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
        await send_telegram_message(config, f"📤 Sending video file `{video_filename}`...")
        await send_telegram_video(config, video_path, f"Breaking News Video ID: {video_id}")
        
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
                await send_telegram_message(config, f"✅ Video generation complete for: `{topic if topic else 'World News'}`")
                await send_telegram_video(config, video_path, f"Breaking News: {topic if topic else 'World News'}")
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
                            
                        if not text:
                            continue
                        
                        log_telegram_interaction("User", text)
                            
                        # Handle message asynchronously to avoid blocking the polling loop
                        asyncio.create_task(handle_telegram_message(text, config, manager, agent))
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in telegram bot loop: {e}")
                await asyncio.sleep(5.0)  # Wait on error

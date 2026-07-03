import os
import json
import datetime
import asyncio
from pathlib import Path
from typing import List, Dict, Any

SCHEDULES_FILE = Path("schedules.json")

def load_schedules() -> List[Dict[str, Any]]:
    if not SCHEDULES_FILE.exists():
        return []
    try:
        with open(SCHEDULES_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load schedules: {e}")
        return []

def save_schedules(schedules: List[Dict[str, Any]]):
    try:
        with open(SCHEDULES_FILE, "w") as f:
            json.dump(schedules, f, indent=2)
    except Exception as e:
        print(f"Failed to save schedules: {e}")

async def run_scheduled_query(prompt: str, manager, agent, config):
    try:
        print(f"Running scheduled query: {prompt}")
        from .router import IntentRouter
        router = IntentRouter(config.router, config.models)
        messages = [{"role": "user", "content": prompt}]
        target_model_id = await router.route_chat(messages, "auto", manager)
        backend = await manager.get_model(target_model_id)
        payload = {
            "messages": messages,
            "temperature": 0.7
        }
        response = await backend.handle_chat_completion(payload)
        ans = response["choices"][0]["message"]["content"]
        
        # Notify Telegram
        from .telegram import send_telegram_message
        await send_telegram_message(
            config, 
            f"🔔 **Scheduled Query Triggered**\nPrompt: `{prompt}`\n\nResponse:\n{ans}"
        )
    except Exception as e:
        print(f"Error running scheduled query: {e}")

async def run_scheduled_automation(target: str, params: dict, manager, agent, config):
    try:
        print(f"Running scheduled automation: {target} with params {params}")
        if target == "news-video":
            from .automation import generate_yesterday_news_video, get_status
            topic = params.get("topic")
            date_str = params.get("date")
            
            from .telegram import send_telegram_message
            await send_telegram_message(
                config, 
                f"🔔 **Scheduled News Video Triggered**\nTopic: `{topic if topic else 'World News'}`\nDate: `{date_str if date_str else 'Yesterday'}`\nGenerating video in background..."
            )
            
            # Run the generator
            await generate_yesterday_news_video(manager, agent, topic, date_str)
            
            # Check status
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
                
                await send_telegram_message(
                    config, 
                    f"✅ **Scheduled News Video Completed!**\nTopic: `{topic if topic else 'World News'}`"
                )
                
                # Send the video file
                from .telegram import send_telegram_video
                await send_telegram_video(
                    config, 
                    video_path, 
                    f"🎬 **Breaking News:** {topic if topic else 'World News'}{stories_caption}"
                )
            else:
                await send_telegram_message(
                    config, 
                    f"❌ **Scheduled News Video Failed:** {status_data['message']}"
                )
    except Exception as e:
        print(f"Error running scheduled automation: {e}")

async def start_scheduler_loop(config, manager, agent):
    """Background check loop running every 30 seconds for scheduled daily tasks."""
    print("CerberAI Scheduler background loop active.")
    while True:
        try:
            await asyncio.sleep(30.0)
            
            schedules = load_schedules()
            if not schedules:
                continue
                
            now = datetime.datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M")
            
            updated = False
            for s in schedules:
                # Format of s: {id, type, target, time, parameters, last_run}
                # Check if it is time to run and hasn't run today
                if s.get("time") == time_str and s.get("last_run") != today_str:
                    s["last_run"] = today_str
                    updated = True
                    
                    # Spawn task in background
                    if s.get("type") == "query":
                        asyncio.create_task(run_scheduled_query(s.get("target"), manager, agent, config))
                    elif s.get("type") == "automation":
                        asyncio.create_task(run_scheduled_automation(s.get("target"), s.get("parameters", {}), manager, agent, config))
            
            if updated:
                save_schedules(schedules)
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in scheduler loop: {e}")

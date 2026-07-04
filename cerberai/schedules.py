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
        from .telegram import send_telegram_message, send_telegram_document, send_telegram_video
        
        if target == "news-video":
            from .automation import generate_yesterday_news_video, get_status
            topic = params.get("topic")
            date_str = params.get("date")
            
            await send_telegram_message(
                config, 
                f"🔔 **Scheduled News Video Triggered**\nTopic: `{topic if topic else 'World News'}`\nDate: `{date_str if date_str else 'Yesterday'}`\nGenerating video in background..."
            )
            
            await generate_yesterday_news_video(manager, agent, topic, date_str)
            
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
                
                await send_telegram_video(
                    config, 
                    video_path, 
                    f"🎬 **Breaking News Briefing:** {topic if topic else 'World News'}{stories_caption}"
                )
            else:
                await send_telegram_message(
                    config, 
                    f"❌ **Scheduled News Video Failed:** {status_data['message']}"
                )

        elif target == "deep-research":
            from .automation import generate_deep_research_report, get_research_status
            topic = params.get("topic")
            if not topic:
                topic = "General Interest"
                
            await send_telegram_message(
                config, 
                f"🔔 **Scheduled Deep Research Triggered**\nTopic: `{topic}`\nGenerating comprehensive report in background..."
            )
            
            await generate_deep_research_report(manager, agent, topic)
            
            status_data = get_research_status()
            if status_data["status"] == "success":
                pdf_url = status_data["pdf_url"]
                pdf_path = pdf_url.replace("/static/reports/", "cerberai/static/reports/")
                report_url = status_data["report_url"]
                
                await send_telegram_message(
                    config, 
                    f"✅ **Scheduled Deep Research Completed!**\nTopic: `{topic}`\nMarkdown Version: {report_url}"
                )
                
                await send_telegram_document(
                    config,
                    pdf_path,
                    f"🔬 **Deep Research Report:** {topic}"
                )
            else:
                await send_telegram_message(
                    config, 
                    f"❌ **Scheduled Deep Research Failed:** {status_data['message']}"
                )

        elif target == "podcast":
            from .automation import generate_daily_podcast, get_podcast_status
            topic = params.get("topic")
            date_str = params.get("date")
            
            await send_telegram_message(
                config, 
                f"🔔 **Scheduled Podcast Briefing Triggered**\nTopic: `{topic if topic else 'World News'}`\nGenerating audio briefing..."
            )
            
            await generate_daily_podcast(manager, agent, topic, date_str)
            
            status_data = get_podcast_status()
            if status_data["status"] == "success":
                podcast_url = status_data["podcast_url"]
                podcast_path = podcast_url.replace("/static/podcasts/", "cerberai/static/podcasts/")
                
                await send_telegram_message(
                    config, 
                    f"✅ **Scheduled Podcast Briefing Completed!**\nTopic: `{topic if topic else 'World News'}`"
                )
                
                await send_telegram_document(
                    config,
                    podcast_path,
                    f"🎙️ **Daily Audio News Briefing:** {topic if topic else 'World News'}"
                )
            else:
                await send_telegram_message(
                    config, 
                    f"❌ **Scheduled Podcast Briefing Failed:** {status_data['message']}"
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

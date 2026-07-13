import os
import json
import datetime
import asyncio
from pathlib import Path
from typing import List, Dict, Any

SCHEDULES_FILE = Path("schedules.json")

from .database import db_load_schedules, db_save_schedules

def load_schedules() -> List[Dict[str, Any]]:
    return db_load_schedules()

def save_schedules(schedules: List[Dict[str, Any]]):
    db_save_schedules(schedules)

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
        from .database import db_create_job, db_get_job
        from .telegram import send_telegram_message, send_telegram_document, send_telegram_video
        
        # 1. Determine vram_required and build parameters
        topic = params.get("topic")
        date_str = params.get("date")
        
        if target == "news-video":
            video_mode = params.get("video_mode", "image")
            job_params = {"topic": topic, "date": date_str, "video_mode": video_mode}
            vram_req = 10.0
            display_target = "News Video"
            info_msg = f"Topic: `{topic if topic else 'World News'}`\nDate: `{date_str if date_str else 'Yesterday'}`\nMode: `{video_mode}`"
        elif target == "deep-research":
            if not topic:
                topic = "General Interest"
            job_params = {"topic": topic}
            vram_req = 8.0
            display_target = "Deep Research"
            info_msg = f"Topic: `{topic}`"
        elif target == "podcast":
            job_params = {"topic": topic, "date": date_str}
            vram_req = 8.0
            display_target = "Podcast Briefing"
            info_msg = f"Topic: `{topic if topic else 'World News'}`"
        else:
            print(f"Unknown scheduled automation target: {target}")
            return

        # 2. Enqueue the job in the Orchestrator
        await send_telegram_message(
            config, 
            f"🔔 **Scheduled {display_target} Triggered**\n{info_msg}\nEnqueued in Orchestrator Job Queue..."
        )
        
        job_id = db_create_job(target, job_params, vram_required=vram_req)
        
        # 3. Poll the job status until it is completed or failed
        print(f"Enqueued scheduled job {job_id} for target {target}. Waiting for completion...")
        while True:
            await asyncio.sleep(5.0)
            job = db_get_job(job_id)
            if not job:
                await send_telegram_message(config, f"❌ **Scheduled {display_target} Error**: Job {job_id} not found in database.")
                return
            
            if job["status"] == "completed":
                result = job["result"] or {}
                break
            elif job["status"] == "failed":
                error_msg = job.get("error", "Unknown error")
                await send_telegram_message(config, f"❌ **Scheduled {display_target} Failed**: {error_msg}")
                return

        # 4. Handle completed job outputs
        if target == "news-video":
            video_url = result.get("video_url")
            if video_url:
                video_path = video_url.replace("/static/videos/", "cerberai/static/videos/")
                stories = result.get("stories", [])
                
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
                await send_telegram_message(config, "❌ **Scheduled News Video Failed**: No video URL found in job result.")

        elif target == "deep-research":
            pdf_url = result.get("pdf_url")
            report_url = result.get("report_url")
            if pdf_url:
                pdf_path = pdf_url.replace("/static/reports/", "cerberai/static/reports/")
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
                await send_telegram_message(config, "❌ **Scheduled Deep Research Failed**: No PDF URL found in job result.")

        elif target == "podcast":
            podcast_url = result.get("podcast_url")
            if podcast_url:
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
                await send_telegram_message(config, "❌ **Scheduled Podcast Briefing Failed**: No podcast URL found in job result.")

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

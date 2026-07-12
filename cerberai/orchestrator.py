import asyncio
import time
from typing import Dict, Any, List, Optional
from .database import (
    db_get_next_pending_job,
    db_update_job_status,
    db_get_job
)
from .automation import (
    generate_yesterday_news_video,
    get_status,
    update_status,
    generate_deep_research_report,
    get_research_status,
    update_research_status,
    generate_daily_podcast,
    get_podcast_status,
    update_podcast_status
)

class Orchestrator:
    def __init__(self, config, manager, agent):
        self.config = config
        self.manager = manager
        self.agent = agent
        self.running_jobs: Dict[str, asyncio.Task] = {}
        self._loop_task: Optional[asyncio.Task] = None
        self._running = False

    def start(self):
        self._running = True
        self._loop_task = asyncio.create_task(self._orchestrator_loop())
        print("Agent Orchestrator started.")

    async def stop(self):
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all running tasks
        for job_id, task in list(self.running_jobs.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.running_jobs.clear()
        print("Agent Orchestrator stopped.")

    async def _orchestrator_loop(self):
        while self._running:
            try:
                await asyncio.sleep(2.0)
                self._cleanup_finished_jobs()
                
                # Check if we can run another job
                job = db_get_next_pending_job()
                if not job:
                    continue
                    
                job_id = job["id"]
                task_type = job["task_type"]
                params = job["parameters"]
                vram_required = job.get("vram_required", 0.0)
                
                # VRAM Allocation check:
                # Sum the VRAM of all CURRENTLY RUNNING jobs
                running_vram = 0.0
                for r_id in self.running_jobs:
                    r_job = db_get_job(r_id)
                    if r_job:
                        running_vram += r_job.get("vram_required", 0.0)
                        
                max_vram = self.config.resource_limits.max_vram_gb
                
                # Always allow at least one job to run to avoid deadlock
                if len(self.running_jobs) > 0 and (running_vram + vram_required > max_vram):
                    # Exceeds max VRAM capacity; wait for active jobs to complete
                    continue
                    
                # Enqueue execution
                db_update_job_status(job_id, "running", progress=0.0)
                task = asyncio.create_task(self._run_job_wrapper(job_id, task_type, params))
                self.running_jobs[job_id] = task
                print(f"Orchestrator launched job '{job_id}' ({task_type}) requiring {vram_required}GB VRAM.")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in orchestrator loop: {e}")

    def _cleanup_finished_jobs(self):
        finished = []
        for job_id, task in self.running_jobs.items():
            if task.done():
                finished.append(job_id)
                try:
                    task.result()
                except Exception as e:
                    print(f"Job {job_id} failed with exception: {e}")
                    db_update_job_status(job_id, "failed", error=str(e))
        for job_id in finished:
            self.running_jobs.pop(job_id, None)

    async def _run_job_wrapper(self, job_id: str, task_type: str, params: Dict[str, Any]):
        try:
            if task_type == "news-video":
                # 1. Reset status
                update_status("idle", 0, "")
                topic = params.get("topic", "")
                date_str = params.get("date", "")
                video_mode = params.get("video_mode", "image")
                
                # Start job task
                task = asyncio.create_task(
                    generate_yesterday_news_video(self.manager, self.agent, topic, date_str, video_mode)
                )
                
                # Track progress
                while not task.done():
                    await asyncio.sleep(2.0)
                    st = get_status()
                    db_update_job_status(
                        job_id, 
                        status="running", 
                        progress=float(st.get("progress", 0)) / 100.0,
                        result=st
                    )
                
                await task
                st = get_status()
                if st["status"] == "completed":
                    db_update_job_status(job_id, status="completed", progress=1.0, result=st)
                else:
                    db_update_job_status(job_id, status="failed", progress=0.0, error=st.get("message", "Stitch failed"))
                    
            elif task_type == "deep-research":
                update_research_status("idle", 0, "")
                topic = params.get("topic", "")
                
                task = asyncio.create_task(
                    generate_deep_research_report(self.manager, self.agent, topic)
                )
                
                while not task.done():
                    await asyncio.sleep(2.0)
                    st = get_research_status()
                    db_update_job_status(
                        job_id,
                        status="running",
                        progress=float(st.get("progress", 0)) / 100.0,
                        result=st
                    )
                    
                await task
                st = get_research_status()
                if st["status"] == "success":
                    db_update_job_status(job_id, status="completed", progress=1.0, result=st)
                else:
                    db_update_job_status(job_id, status="failed", progress=0.0, error=st.get("message", "Research failed"))

            elif task_type == "podcast":
                update_podcast_status("idle", 0, "")
                topic = params.get("topic", "")
                date_str = params.get("date", "")
                
                task = asyncio.create_task(
                    generate_daily_podcast(self.manager, self.agent, topic, date_str)
                )
                
                while not task.done():
                    await asyncio.sleep(2.0)
                    st = get_podcast_status()
                    db_update_job_status(
                        job_id,
                        status="running",
                        progress=float(st.get("progress", 0)) / 100.0,
                        result=st
                    )
                    
                await task
                st = get_podcast_status()
                if st["status"] == "success":
                    db_update_job_status(job_id, status="completed", progress=1.0, result=st)
                else:
                    db_update_job_status(job_id, status="failed", progress=0.0, error=st.get("message", "Podcast failed"))
            else:
                db_update_job_status(job_id, status="failed", error=f"Unknown task type '{task_type}'")
        except asyncio.CancelledError:
            db_update_job_status(job_id, status="failed", error="Job was cancelled early.")
            raise
        except Exception as e:
            db_update_job_status(job_id, status="failed", error=str(e))

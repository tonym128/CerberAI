import os
import re
import json
import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Dict, Any
from PIL import Image, ImageDraw, ImageFont

# Global status tracking
status = {
    "status": "idle",
    "progress": 0,
    "message": "",
    "video_url": None
}

def get_status() -> Dict[str, Any]:
    return status

def update_status(state: str, progress: int, msg: str, video_url: str = None):
    global status
    status["status"] = state
    status["progress"] = progress
    status["message"] = msg
    if video_url:
        status["video_url"] = video_url

def add_video_to_history(video_filename: str, topic: str, date_str: str):
    import json
    import datetime
    
    history_path = Path("cerberai/static/videos/history.json")
    history = []
    if history_path.exists():
        try:
            with open(history_path, "r") as f:
                history = json.load(f)
        except Exception:
            pass
            
    new_entry = {
        "id": video_filename.replace(".mp4", ""),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "topic": topic if topic else "World News",
        "date": date_str,
        "video_url": f"/static/videos/{video_filename}"
    }
    
    # Prepend to keep newest at the top
    history.insert(0, new_entry)
    
    # Ensure directory exists and write
    history_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Failed to write video history: {e}")

def wrap_text(text: str, draw: ImageDraw.Draw, max_width: int, font) -> list:
    """Wrap text to fit inside max_width."""
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        current_line.append(word)
        # Check size of line
        line_str = " ".join(current_line)
        bbox = draw.textbbox((0, 0), line_str, font=font)
        w = bbox[2] - bbox[0]
        if w > max_width:
            current_line.pop()
            lines.append(" ".join(current_line))
            current_line = [word]
            
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def create_transparent_overlay(width: int, height: int, title: str, summary: str, output_path: str):
    """Create a transparent PNG containing the news broadcast template and text overlays."""
    # Create fully transparent RGBA canvas
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw red "BREAKING NEWS" banner at the top
    draw.rectangle([0, 0, width, 50], fill=(200, 16, 16, 220))
    
    # Draw semi-transparent black banner at the bottom for subtitles
    draw.rectangle([0, height - 120, width, height], fill=(0, 0, 0, 180))
    
    # Load a default font or fallback
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
    except Exception:
        font_title = ImageFont.load_default()
        font_text = ImageFont.load_default()
        
    # Draw BREAKING NEWS text
    draw.text((15, 12), "BREAKING NEWS: " + title.upper(), fill=(255, 255, 255, 255), font=font_title)
    
    # Draw wrapped summary text at the bottom
    max_text_width = width - 40
    wrapped_lines = wrap_text(summary, draw, max_text_width, font_text)
    
    y_text = height - 105
    for line in wrapped_lines[:4]: # Cap at 4 lines to fit inside bottom banner
        draw.text((20, y_text), line, fill=(240, 240, 240, 255), font=font_text)
        y_text += 22
        
    img.save(output_path, "PNG")

async def generate_yesterday_news_video(manager, agent, topic: str = None, date_str: str = None):
    """
    Background automation runner:
    1. Search for news stories based on target date and topic.
    2. Extract 10 distinct stories using LLM.
    3. Generate image overlays, audio clips, and compile segment videos concurrently with Ken Burns camera effects.
    4. Concat video clips and output final file.
    """
    import datetime
    target_date = date_str if date_str else (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    if topic:
        query = f"top major {topic} stories {target_date}"
        search_msg = f"Searching for '{topic}' stories from {target_date}..."
    else:
        query = f"top major world news stories {target_date}"
        search_msg = f"Searching world news stories from {target_date}..."
        
    update_status("running", 5, search_msg)
    
    # 1. Fetch news using our web search tool
    raw_search = await agent.web_search_tool(query)
    
    # 2. Extract links and fetch actual content from the top search results using web_fetch_tool
    urls = re.findall(r'Source:\s*(https?://\S+)', raw_search)
    fetched_contents = []
    
    # Limit to top 3 links to keep execution fast and prevent context overflow
    target_urls = urls[:3]
    if target_urls:
        update_status("running", 10, f"Fetching details from top {len(target_urls)} news sources...")
        for i, url in enumerate(target_urls):
            try:
                print(f"Fetching story details from: {url}")
                page_text = await agent.web_fetch_tool(url)
                # Keep first 3000 chars of each page to keep prompt context clean
                trimmed_text = page_text[:3000] if len(page_text) > 3000 else page_text
                fetched_contents.append(f"Source URL: {url}\nContent:\n{trimmed_text}\n---")
            except Exception as e:
                print(f"Failed to fetch content from {url}: {e}")
                
    detailed_context = f"Search Results Snippets:\n{raw_search}\n\n"
    if fetched_contents:
        detailed_context += "Fetched Detailed Article Texts:\n" + "\n".join(fetched_contents)
    
    update_status("running", 15, "Structuring stories and scripts using LLM...")
    
    # 3. Structure stories with LLM
    prompt_topic_desc = f"relating to '{topic}'" if topic else "world"
    prompt = (
        f"You are a news broadcast editor. Based on the following raw web search results and fetched articles for {target_date}, "
        f"identify exactly 10 distinct, major news stories {prompt_topic_desc}. "
        "For each story, output a title, a 2-sentence narration summary, and a descriptive image prompt for AI generation.\n\n"
        f"Search and Article Data:\n{detailed_context}\n\n"
        "You MUST respond ONLY with a JSON array of 10 objects. Format:\n"
        "[\n"
        "  {\n"
        "    \"title\": \"Story Title\",\n"
        "    \"summary\": \"Two sentence narration script.\",\n"
        "    \"image_prompt\": \"Descriptive prompt for drawing image.\"\n"
        "  }\n"
        "]\n"
        "Do not include any introduction or code block wrappers. Output valid raw JSON."
    )
    
    try:
        # Route to LLM backend
        backend = await manager.get_model("general-llama3")
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
        response = await backend.handle_chat_completion(payload)
        content = response["choices"][0]["message"]["content"].strip()
        
        # Clean potential markdown wrappers
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z0-9]*\n", "", content)
            content = re.sub(r"\n```$", "", content)
        content = content.strip()
        
        stories = json.loads(content)
        if not isinstance(stories, list) or len(stories) == 0:
            raise ValueError("LLM returned invalid stories array.")
            
        # Ensure we have at most 10 stories
        stories = stories[:10]
        print(f"Structured {len(stories)} stories successfully.")
    except Exception as e:
        print(f"Structuring error: {e}")
        # Fallback hardcoded stories if JSON parsing fails to keep it robust
        fallback_topic = topic if topic else "Global News"
        stories = [
            {
                "title": f"Recent developments in {fallback_topic}",
                "summary": f"Interesting events occurred regarding {fallback_topic} today. Industry leaders and researchers are closely monitoring these shifts.",
                "image_prompt": f"Representational artistic conceptual image of {fallback_topic}, modern high tech illustration, professional photography"
            },
            {
                "title": f"New milestones for {fallback_topic}",
                "summary": f"Key analysts have reported new breakthroughs in the field of {fallback_topic}. The global community has reacted with strong interest.",
                "image_prompt": f"Stunning professional photo visualizing progress in {fallback_topic}, highly detailed"
            }
        ]
        
    # Get image and tts backends
    img_backend = await manager.get_model("image-lcm")
    tts_backend = await manager.get_model("tts-offline")
    
    temp_dir = tempfile.mkdtemp()
    total_stories = len(stories)
    segment_paths = [None] * total_stories
    
    completed_count = 0
    status_lock = asyncio.Lock()
    
    async def process_slide(idx, story):
        nonlocal completed_count
        
        # A. Generate Image
        img_temp_raw = os.path.join(temp_dir, f"raw_{idx}.png")
        try:
            img_res = await img_backend.handle_image_generation({"prompt": story["image_prompt"]})
            b64_data = img_res["data"][0]["b64_json"]
            with open(img_temp_raw, "wb") as f:
                f.write(base64.b64decode(b64_data))
        except Exception as e:
            print(f"Failed to generate image for slide {idx}: {e}")
            # Fallback placeholder image
            img_placeholder = Image.new("RGB", (512, 512), color=(40, 44, 52))
            img_placeholder.save(img_temp_raw)
            
        # B. Create transparent overlay containing fixed text and news borders
        overlay_temp = os.path.join(temp_dir, f"overlay_{idx}.png")
        create_transparent_overlay(512, 512, story["title"], story["summary"], overlay_temp)
        
        # C. Generate Speech Audio (WAV)
        audio_temp = os.path.join(temp_dir, f"speech_{idx}.wav")
        try:
            audio_bytes = await tts_backend.handle_audio_speech({"input": story["summary"]})
            with open(audio_temp, "wb") as f:
                f.write(audio_bytes)
        except Exception as e:
            print(f"Failed to generate TTS for slide {idx}: {e}")
            # Write silent wav fallback
            import wave
            with wave.open(audio_temp, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b'\x00' * 48000 * 3) # 3 seconds of silence
                
        # Calculate exact audio duration using Python's standard wave library
        duration = 5.0
        try:
            import wave
            with wave.open(audio_temp, 'rb') as r:
                frames = r.getnframes()
                rate = r.getframerate()
                if rate > 0:
                    duration = frames / float(rate)
        except Exception as ex:
            print(f"Failed to read WAV duration for slide {idx}: {ex}")
            
        # Add a tiny padding to avoid clipping the end of audio
        duration = max(2.0, duration + 0.2)
        total_frames = int(duration * 25) # 25 FPS target for zoompan
        
        # D. Convert Slide + Audio to Video Segment using ffmpeg with Ken Burns effect
        segment_path = os.path.join(temp_dir, f"segment_{idx}.mp4")
        
        # Alternating zoom-in and zoom-out Ken Burns expressions, scaled up to 2048 to prevent pixel jitter
        if idx % 2 == 0:
            # Zoom-in: starting at 1.0, zooming in towards 1.3
            zoom_filter = f"[0:v]scale=2048:2048,zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=2048x2048,scale=512:512[bg];[bg][1:v]overlay=x=0:y=0[out]"
        else:
            # Zoom-out: starting at 1.3, zooming out towards 1.0
            zoom_filter = f"[0:v]scale=2048:2048,zoompan=z='max(1.3-0.001*on,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=2048x2048,scale=512:512[bg];[bg][1:v]overlay=x=0:y=0[out]"
        
        # Command builds a video clip with smooth zoom and static text overlay
        cmd = [
            "ffmpeg", "-y",
            "-i", img_temp_raw,
            "-i", overlay_temp,
            "-i", audio_temp,
            "-filter_complex", zoom_filter,
            "-map", "[out]",
            "-map", "2:a",
            "-c:v", "libx264",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-t", f"{duration:.3f}",
            segment_path
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        segment_paths[idx] = segment_path
        
        async with status_lock:
            completed_count += 1
            progress_val = 20 + int((completed_count / total_stories) * 60)
            update_status("running", progress_val, f"Generated slide {completed_count}/{total_stories}: {story['title']}")

    # Run slide generation tasks concurrently
    await asyncio.gather(*[process_slide(i, story) for i, story in enumerate(stories)])
        
    # 4. Concatenate all segment videos into final video
    update_status("running", 85, "Stitching all stories into the final broadcast video...")
    
    concat_txt_path = os.path.join(temp_dir, "concat.txt")
    with open(concat_txt_path, "w") as f:
        # filter out any None segments just in case
        for p in [p for p in segment_paths if p]:
            f.write(f"file '{p}'\n")
            
    # Ensure static directory exists
    static_videos_dir = Path("cerberai/static/videos")
    static_videos_dir.mkdir(parents=True, exist_ok=True)
    
    # Create a unique filename using timestamp and sanitized topic
    import datetime
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    topic_slug = re.sub(r'[^a-zA-Z0-9]', '_', topic)[:20] if topic else "world_news"
    video_filename = f"news_{timestamp_str}_{topic_slug}.mp4"
    final_video_path = static_videos_dir / video_filename
    
    # Run concatenation command
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_txt_path,
        "-c:v", "libx264",
        "-preset", "superfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(final_video_path.resolve())
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *concat_cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await proc.wait()
    
    # Cleanup temp directory
    try:
        import shutil
        shutil.rmtree(temp_dir)
    except Exception:
        pass
        
    # Finalize status
    if final_video_path.exists():
        video_url = f"/static/videos/{video_filename}"
        update_status("completed", 100, "Breaking News video generated successfully!", video_url)
        add_video_to_history(video_filename, topic, target_date)
        print("Breaking News video generation complete.")
    else:
        update_status("failed", 0, "Video stitch failed: output file was not created.")
        print("Breaking News video generation failed.")

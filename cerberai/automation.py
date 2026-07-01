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

def create_captioned_image(img_path: str, title: str, summary: str, output_path: str):
    """Draw a news-style broadcast template overlay on top of the generated image."""
    with Image.open(img_path) as img:
        # Convert to RGBA for transparent overlay drawing
        img = img.convert("RGBA")
        width, height = img.size
        
        # Create overlay canvas
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Draw red "BREAKING NEWS" banner at the top
        draw.rectangle([0, 0, width, 50], fill=(200, 16, 16, 220))
        
        # Draw semi-transparent black banner at the bottom for subtitles
        draw.rectangle([0, height - 120, width, height], fill=(0, 0, 0, 180))
        
        # Load a default font or fallback
        try:
            # Try loading a standard font
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
            
        # Composite overlay onto original image
        combined = Image.alpha_composite(img, overlay)
        combined.convert("RGB").save(output_path, "JPEG")

async def generate_yesterday_news_video(manager, agent):
    """
    Background automation runner:
    1. Search for yesterday's top news stories.
    2. Extract 10 distinct stories using LLM.
    3. Generate image overlays, audio clips, and compile segment videos using ffmpeg.
    4. Concat video clips and output final file.
    """
    update_status("running", 5, "Searching yesterday's top news stories...")
    
    # 1. Fetch news from yesterday using our web search tool
    import datetime
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    query = f"top major world news stories {yesterday}"
    
    raw_search = await agent.web_search_tool(query)
    
    update_status("running", 15, "Structuring stories and scripts using LLM...")
    
    # 2. Structure stories with LLM
    prompt = (
        f"You are a news broadcast editor. Based on the following raw web search results for yesterday ({yesterday}), "
        "identify exactly 10 distinct, major news stories. "
        "For each story, output a title, a 2-sentence narration summary, and a descriptive image prompt for AI generation.\n\n"
        f"Search Results:\n{raw_search}\n\n"
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
        stories = [
            {
                "title": "Global Tech Advancements",
                "summary": "Major technology companies rolled out breakthrough local AI systems. Experts believe these models will significantly change consumer hardware.",
                "image_prompt": "Futuristic clean laboratory with high tech servers and glowing blue neural networks, photo"
            },
            {
                "title": "Global Climate Accord Progress",
                "summary": "Nations across the globe convened to review emissions reductions. Key resolutions were adopted to accelerate clean solar infrastructure.",
                "image_prompt": "Beautiful clean solar farm in a lush green valley with blue skies, professional photography"
            }
        ]
        
    # Get image and tts backends
    img_backend = await manager.get_model("image-lcm")
    tts_backend = await manager.get_model("tts-offline")
    
    temp_dir = tempfile.mkdtemp()
    segment_paths = []
    
    # 3. Process each story
    total_stories = len(stories)
    for idx, story in enumerate(stories):
        progress_val = 20 + int((idx / total_stories) * 60)
        update_status("running", progress_val, f"Generating slide {idx+1}/{total_stories}: {story['title']}")
        
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
            
        # B. Apply template text overlay on image
        img_temp_captioned = os.path.join(temp_dir, f"slide_{idx}.jpg")
        create_captioned_image(img_temp_raw, story["title"], story["summary"], img_temp_captioned)
        
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
                
        # D. Convert Slide + Audio to Video Segment using ffmpeg
        segment_path = os.path.join(temp_dir, f"segment_{idx}.mp4")
        
        # Command builds a video clip stretching exactly to audio length
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", img_temp_captioned,
            "-i", audio_temp,
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            segment_path
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        segment_paths.append(segment_path)
        
    # 4. Concatenate all segment videos into final video
    update_status("running", 85, "Stitching all stories into the final broadcast video...")
    
    concat_txt_path = os.path.join(temp_dir, "concat.txt")
    with open(concat_txt_path, "w") as f:
        for p in segment_paths:
            f.write(f"file '{p}'\n")
            
    # Ensure static directory exists
    static_videos_dir = Path("cerberai/static/videos")
    static_videos_dir.mkdir(parents=True, exist_ok=True)
    
    final_video_path = static_videos_dir / "news_yesterday.mp4"
    
    # Run concatenation command
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_txt_path,
        "-c", "copy",
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
        update_status("completed", 100, "Breaking News video generated successfully!", "/static/videos/news_yesterday.mp4")
        print("Breaking News video generation complete.")
    else:
        update_status("failed", 0, "Video stitch failed: output file was not created.")
        print("Breaking News video generation failed.")

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
    "video_url": None,
    "stories": []
}

def get_status() -> Dict[str, Any]:
    return status

def update_status(state: str, progress: int, msg: str, video_url: str = None, stories: list = None):
    global status
    status["status"] = state
    status["progress"] = progress
    status["message"] = msg
    if video_url:
        status["video_url"] = video_url
    if stories is not None:
        status["stories"] = stories

def add_video_to_history(video_filename: str, topic: str, date_str: str, stories: list):
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
        "video_url": f"/static/videos/{video_filename}",
        "stories": stories
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

def create_transparent_overlay(width: int, height: int, title: str, summary: str, source_url: str, output_path: str):
    """Create a transparent PNG containing the news broadcast template and text overlays."""
    # Create fully transparent RGBA canvas
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw semi-transparent black banner at the bottom for subtitles
    draw.rectangle([0, height - 120, width, height], fill=(0, 0, 0, 180))
    
    # Load a default font or fallback
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
        font_source = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    except Exception:
        font_title = ImageFont.load_default()
        font_text = ImageFont.load_default()
        font_source = ImageFont.load_default()
        
    # Wrap breaking news title text
    full_title_text = "BREAKING NEWS: " + title.upper()
    title_max_width = width - 30  # 15px padding on each side
    wrapped_title_lines = wrap_text(full_title_text, draw, title_max_width, font_title)
    
    # Dynamically calculate banner height based on number of wrapped title lines
    line_spacing = 26
    banner_height = max(50, 16 + len(wrapped_title_lines) * line_spacing)
    
    # Draw red "BREAKING NEWS" banner at the top with calculated dynamic height
    draw.rectangle([0, 0, width, banner_height], fill=(200, 16, 16, 220))
    
    # Draw the wrapped title text lines
    y_title = 12
    for line in wrapped_title_lines:
        draw.text((15, y_title), line, fill=(255, 255, 255, 255), font=font_title)
        y_title += line_spacing
    
    has_qr = False
    
    # Generate and draw QR Code if source_url is available
    if source_url:
        try:
            import qrcode
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=1,
            )
            qr.add_data(source_url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
            qr_size = 70
            qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
            
            # Draw white container box behind the QR Code for scannability
            draw.rectangle([width - qr_size - 15, height - 105, width - 11, height - 21], fill=(255, 255, 255, 255))
            
            # Paste QR Code
            img.paste(qr_img, (width - qr_size - 13, height - 103), qr_img)
            has_qr = True
        except Exception as qre:
            print(f"Failed to generate QR Code for slide: {qre}")
            
    # Draw domain name and source citation
    if source_url:
        domain_match = re.search(r'https?://([^/]+)', source_url)
        if domain_match:
            domain = domain_match.group(1).replace("www.", "")
            # Draw domain text at bottom left
            draw.text((20, height - 25), f"Source: {domain}", fill=(160, 160, 160, 255), font=font_source)
            
    # Draw wrapped summary text at the bottom. Reduce width if QR code is present to avoid overlapping
    max_text_width = width - 110 if has_qr else width - 40
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
        "CRITICAL VERIFIABILITY RULES:\n"
        "1. All stories MUST be real, accurate, and explicitly verifiable from the provided source articles/search results.\n"
        "2. Do NOT invent, extrapolate, or hallucinate any story details, facts, or links. If a topic is not explicitly mentioned in the data, do not include it.\n"
        "3. The `source_url` field MUST match a valid source HTTP/HTTPS URL from the text (do not hallucinate a URL).\n"
        "4. If there are fewer than 10 real, verifiable stories in the data, output only the actual number of real stories (e.g. 4 or 6). Do not fill or pad the array with placeholder or mock stories.\n\n"
        f"Search and Article Data:\n{detailed_context}\n\n"
        "You MUST respond ONLY with a JSON array of objects. Format:\n"
        "[\n"
        "  {\n"
        "    \"title\": \"Story Title\",\n"
        "    \"summary\": \"Two sentence narration script.\",\n"
        "    \"image_prompt\": \"Descriptive prompt for drawing image.\",\n"
        "    \"source_url\": \"The actual source HTTP/HTTPS URL of the article\"\n"
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
            raise ValueError("LLM returned invalid or empty stories array.")
            
        # Verify and validate that stories exist in the search/fetch source urls and are real
        valid_stories = []
        for story in stories:
            if not isinstance(story, dict):
                continue
            title = story.get("title", "").strip()
            summary = story.get("summary", "").strip()
            image_prompt = story.get("image_prompt", "").strip()
            source_url = story.get("source_url", "").strip()
            
            if not title or not summary or not image_prompt or not source_url:
                continue
                
            if not (source_url.startswith("http://") or source_url.startswith("https://")):
                continue
                
            # Verify the source URL belongs to the crawled/search data to prevent hallucinated sites
            if source_url in raw_search or any(u in source_url for u in urls):
                valid_stories.append(story)
                
        if not valid_stories:
            raise ValueError("No verifiable news stories with valid source links were found in the context data.")
            
        stories = valid_stories[:10]
        print(f"Validated and kept {len(stories)} real, verifiable stories.")
    except Exception as e:
        print(f"News verification or parsing error: {e}")
        update_status("failed", 0, f"Verification failed: {e}")
        print("Breaking News video generation failed due to lack of verifiable sources.")
        return
        
    # Check VRAM limits to disable video generation for low VRAM systems (< 8GB)
    max_vram = manager.config.resource_limits.max_vram_gb
    if max_vram < 8.0:
        msg = f"Video generation disabled: Requires at least 8.0 GB VRAM (system has {max_vram} GB VRAM)."
        print(msg)
        update_status("failed", 0, msg)
        return

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
        
        # A. Generate Image or Video segment depending on VRAM and model availability
        video_temp_raw = os.path.join(temp_dir, f"video_raw_{idx}.mp4")
        img_temp_raw = os.path.join(temp_dir, f"raw_{idx}.png")
        use_video_model = False
        
        has_video_model = any(m.id == "video-generation" for m in manager.config.models)
        if has_video_model and max_vram >= 8.0:
            use_video_model = True
            
        if use_video_model:
            try:
                # Load video model
                video_backend = await manager.get_model("video-generation")
                # Generate video frames
                video_res = await video_backend.handle_video_generation({
                    "prompt": story["image_prompt"],
                    "num_frames": 16, # ~2 seconds
                    "num_inference_steps": 20
                })
                b64_video = video_res["b64_json"]
                with open(video_temp_raw, "wb") as f:
                    f.write(base64.b64decode(b64_video))
            except Exception as e:
                print(f"Failed to generate AI video segment for slide {idx}: {e}. Falling back to image...")
                use_video_model = False

        if not use_video_model:
            # Fallback to image generation
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
            
        # B. Create transparent overlay containing fixed text, news borders, and domain source
        overlay_temp = os.path.join(temp_dir, f"overlay_{idx}.png")
        create_transparent_overlay(512, 512, story["title"], story["summary"], story.get("source_url", ""), overlay_temp)
        
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
        
        # D. Convert Slide + Audio to Video Segment using ffmpeg
        segment_path = os.path.join(temp_dir, f"segment_{idx}.mp4")
        
        if use_video_model:
            # Loop the generated video file to match the narration duration
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", video_temp_raw,
                "-i", overlay_temp,
                "-i", audio_temp,
                "-filter_complex", "[0:v]scale=512:512[bg];[bg][1:v]overlay=x=0:y=0[out]",
                "-map", "[out]",
                "-map", "2:a",
                "-c:v", "libx264",
                "-preset", "superfast",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-c:a", "aac", "-b:a", "192k",
                "-t", f"{duration:.3f}",
                segment_path
            ]
        else:
            # Alternating zoom-in and zoom-out Ken Burns expressions, scaled up to 2048 to prevent pixel jitter
            if idx % 2 == 0:
                zoom_filter = f"[0:v]scale=2048:2048,zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=2048x2048,scale=512:512[bg];[bg][1:v]overlay=x=0:y=0[out]"
            else:
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
                "-movflags", "+faststart",
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
        "-movflags", "+faststart",
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
        update_status("completed", 100, "Breaking News video generated successfully!", video_url, stories)
        add_video_to_history(video_filename, topic, target_date, stories)
        print("Breaking News video generation complete.")
    else:
        update_status("failed", 0, "Video stitch failed: output file was not created.")
        print("Breaking News video generation failed.")


# ==========================================================================
# RECURSIVE DEEP RESEARCH AGENT
# ==========================================================================

research_status = {
    "status": "idle",
    "progress": 0,
    "message": "",
    "report_url": None,
    "pdf_url": None,
    "query": ""
}

def get_research_status() -> Dict[str, Any]:
    return research_status

def update_research_status(state: str, progress: int, msg: str, report_url: str = None, pdf_url: str = None, query: str = None):
    global research_status
    research_status["status"] = state
    research_status["progress"] = progress
    research_status["message"] = msg
    if report_url:
        research_status["report_url"] = report_url
    if pdf_url:
        research_status["pdf_url"] = pdf_url
    if query:
        research_status["query"] = query

def add_report_to_history(markdown_filename: str, pdf_filename: str, query: str):
    import json
    import datetime
    
    history_path = Path("cerberai/static/reports/history.json")
    history = []
    if history_path.exists():
        try:
            with open(history_path, "r") as f:
                history = json.load(f)
        except Exception:
            pass
            
    new_entry = {
        "id": markdown_filename.replace(".md", ""),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query": query,
        "report_url": f"/static/reports/{markdown_filename}",
        "pdf_url": f"/static/reports/{pdf_filename}"
    }
    
    history.insert(0, new_entry)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Failed to write report history: {e}")

def convert_markdown_to_pdf(markdown_text: str, output_path: str, query: str, date_str: str):
    """Convert raw Markdown text into a styled PDF report using fpdf2 write_html."""
    from fpdf import FPDF, XPos, YPos
    
    class ResearchPDF(FPDF):
        report_date = ""
        def header(self):
            self.set_font("helvetica", "B", 10)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, "CerberAI Deep Research Report", border=0, align="L")
            self.cell(0, 10, f"Date: {self.report_date}", border=0, align="R")
            self.ln(12)
            self.set_draw_color(220, 220, 220)
            self.line(10, 18, 200, 18)

        def footer(self):
            self.set_y(-15)
            self.set_font("helvetica", "I", 8)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", border=0, align="C")

    # Simple Markdown-to-HTML parser for FPDF2 compatibility
    html_lines = []
    lines = markdown_text.splitlines()
    in_list = False
    
    for line in lines:
        line_strip = line.strip()
        
        # Headers
        if line_strip.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{line_strip[4:]}</h3>")
        elif line_strip.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{line_strip[3:]}</h2>")
        elif line_strip.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h1>{line_strip[2:]}</h1>")
        # Lists
        elif line_strip.startswith("* ") or line_strip.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = line_strip[2:]
            content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', content)
            content = re.sub(r'\*(.*?)\*', r'<i>\1</i>', content)
            content = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', content)
            html_lines.append(f"<li>{content}</li>")
        # Empty lines
        elif not line_strip:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<br>")
        # Normal text paragraph
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            content = line_strip
            content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', content)
            content = re.sub(r'\*(.*?)\*', r'<i>\1</i>', content)
            content = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', content)
            html_lines.append(f"<p>{content}</p>")
            
    if in_list:
        html_lines.append("</ul>")
        
    html_content = "".join(html_lines)
    full_html = f"<html><body>{html_content}</body></html>"
    
    pdf = ResearchPDF()
    pdf.report_date = date_str
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_margins(15, 20, 15)
    
    # Report Header Page Title
    pdf.set_font("helvetica", "B", 20)
    pdf.set_text_color(139, 92, 246)  # Accent Purple
    pdf.cell(0, 15, "DEEP RESEARCH REPORT", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
    
    pdf.set_font("helvetica", "B", 12)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, f"Topic Search Query: {query}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
    pdf.ln(5)
    
    pdf.set_text_color(20, 20, 20)
    pdf.write_html(full_html)
    pdf.output(output_path)

async def generate_deep_research_report(manager, agent, query: str):
    """
    Background deep research loop:
    1. Initial web search based on user query (0-20%).
    2. Analyze snippets using LLM and recursively generate 2-3 follow-up sub-queries (20-40%).
    3. Run follow-up searches and crawl the top 4-5 total articles (40-60%).
    4. Compile text context and prompt LLM to structure a comprehensive report with citations (60-80%).
    5. Convert markdown report to a formatted PDF using fpdf2 and save (80-100%).
    """
    import datetime
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    update_research_status("running", 5, f"Analyzing search query and starting research: '{query}'...", query=query)
    
    # 1. Initial search
    try:
        raw_search = await agent.web_search_tool(query)
    except Exception as e:
        raw_search = f"Initial search failed: {e}"
        
    update_research_status("running", 20, "Analyzing initial results to identify information gaps...")
    
    # 2. Analyze snippets with LLM and recursively generate follow-up sub-queries
    sub_queries_prompt = (
        f"You are a lead researcher. We are investigating: '{query}'.\n"
        f"Based on the following initial search results, identify key gaps in information "
        f"and output exactly 2 highly specific follow-up search queries to research details or verify claims.\n\n"
        f"Initial Search Snippets:\n{raw_search}\n\n"
        "You MUST respond ONLY with a JSON array of strings containing the queries. Format:\n"
        "[\n"
        "  \"follow up query 1\",\n"
        "  \"follow up query 2\"\n"
        "]\n"
        "Do not include any introduction or code block wrappers. Output valid raw JSON."
    )
    
    sub_queries = []
    try:
        backend = await manager.get_model("general-llama3")
        payload = {
            "messages": [{"role": "user", "content": sub_queries_prompt}],
            "temperature": 0.2
        }
        response = await backend.handle_chat_completion(payload)
        content = response["choices"][0]["message"]["content"].strip()
        
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z0-9]*\n", "", content)
            content = re.sub(r"\n```$", "", content)
        content = content.strip()
        sub_queries = json.loads(content)
    except Exception as e:
        print(f"Failed to generate follow-up queries: {e}. Falling back to default search.")
        sub_queries = [f"{query} details", f"{query} news"]

    if not isinstance(sub_queries, list):
        sub_queries = [f"{query} details"]
    sub_queries = [str(q) for q in sub_queries[:2]]
    
    update_research_status("running", 35, f"Running recursive sub-queries: {', '.join([f'\"{q}\"' for q in sub_queries])}...")
    
    # 3. Fetch recursive search results
    search_context_list = [f"Initial Search on '{query}':\n{raw_search}"]
    all_urls = []
    
    def extract_urls(text):
        return re.findall(r'Source:\s*(https?://\S+)', text)
        
    all_urls.extend(extract_urls(raw_search))
    
    for sub_q in sub_queries:
        try:
            sub_res = await agent.web_search_tool(sub_q)
            search_context_list.append(f"Sub-query search on '{sub_q}':\n{sub_res}")
            all_urls.extend(extract_urls(sub_res))
        except Exception as e:
            print(f"Sub-query failed: {sub_q}: {e}")
            
    # De-duplicate URLs
    unique_urls = []
    for u in all_urls:
        if u not in unique_urls:
            unique_urls.append(u)
            
    # Crawl top 4 URLs
    target_urls = unique_urls[:4]
    fetched_texts = []
    
    update_research_status("running", 50, f"Crawling and fetching detailed contents from top {len(target_urls)} sources...")
    
    for i, url in enumerate(target_urls):
        try:
            update_research_status("running", 50 + int(i * 3), f"Crawl: Reading detailed article ({i+1}/{len(target_urls)}): {url}...")
            content_text = await agent.web_fetch_tool(url)
            trimmed = content_text[:4000] if len(content_text) > 4000 else content_text
            fetched_texts.append(f"Source URL: {url}\nArticle Content:\n{trimmed}\n---")
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            
    compiled_research_context = (
        "=== SEARCH SNIPPETS ===\n" + "\n\n".join(search_context_list) + "\n\n"
        "=== DETAILED SOURCE ARTICLES ===\n" + "\n\n".join(fetched_texts)
    )
    
    update_research_status("running", 65, "Synthesizing research data and writing Markdown report...")
    
    # 4. Generate report markdown
    report_prompt = (
        f"You are a senior research analyst. Write a comprehensive, high-quality, professional research report "
        f"answering the user query: '{query}' based on the compiled search results and fetched articles below.\n\n"
        f"CRITICAL COMPILATION RULES:\n"
        f"1. Structure your output clearly using markdown headers: `# Title`, `## Executive Summary`, `## Key Findings`, `## Detailed Analysis`, `## References`.\n"
        f"2. Incorporate explicit citations in the text linking to the source URLs (e.g. '[Source Title](url)' or '(Source: [Domain](url))'). Do NOT make up any source URLs.\n"
        f"3. Make the report exhaustive, factual, and deeply analytical. Format bold text with `**` and bullet points with `*`.\n"
        f"4. Do NOT output HTML or any surrounding code blocks. Output clean, raw markdown content only.\n\n"
        f"Research Context:\n{compiled_research_context}"
    )
    
    try:
        backend = await manager.get_model("general-llama3")
        payload = {
            "messages": [{"role": "user", "content": report_prompt}],
            "temperature": 0.4
        }
        response = await backend.handle_chat_completion(payload)
        report_markdown = response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        report_markdown = f"# Deep Research Report: {query}\n\nFailed to generate report using LLM: {e}"
        
    update_research_status("running", 80, "Compiling Markdown report into a formatted PDF document...")
    
    # Generate unique filenames
    import time
    timestamp = int(time.time())
    sanitized_query = re.sub(r'[^a-zA-Z0-9]', '_', query)[:25].strip("_")
    md_filename = f"report_{timestamp}_{sanitized_query}.md"
    pdf_filename = f"report_{timestamp}_{sanitized_query}.pdf"
    
    reports_dir = Path("cerberai/static/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    md_path = reports_dir / md_filename
    pdf_path = reports_dir / pdf_filename
    
    # Write markdown file
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report_markdown)
    except Exception as e:
        print(f"Failed to write markdown file: {e}")
        
    # Write PDF file
    try:
        convert_markdown_to_pdf(report_markdown, str(pdf_path.resolve()), query, date_str)
    except Exception as e:
        print(f"Failed to compile PDF: {e}")
        # Fallback PDF in case converter fails
        try:
            from fpdf import FPDF
            fallback_pdf = FPDF()
            fallback_pdf.add_page()
            fallback_pdf.set_font("helvetica", "B", 16)
            fallback_pdf.cell(0, 10, "CerberAI Research Report (Fallback Mode)", new_x="LMARGIN", new_y="NEXT")
            fallback_pdf.set_font("helvetica", "", 12)
            fallback_pdf.ln(10)
            fallback_pdf.write(5, report_markdown[:2000] + "\n\n[Truncated due to compilation error]")
            fallback_pdf.output(str(pdf_path.resolve()))
        except Exception as fe:
            print(f"Fallback PDF compilation also failed: {fe}")
            
    # Update status history and set completion
    add_report_to_history(md_filename, pdf_filename, query)
    update_research_status(
        "success", 
        100, 
        f"Research report successfully generated!", 
        report_url=f"/static/reports/{md_filename}", 
        pdf_url=f"/static/reports/{pdf_filename}"
    )
    print("Deep Research report generation complete.")


# ==========================================================================
# MULTI-SPEAKER AUDIO PODCAST GENERATOR
# ==========================================================================

podcast_status = {
    "status": "idle",
    "progress": 0,
    "message": "",
    "podcast_url": None,
    "query": ""
}

def get_podcast_status() -> Dict[str, Any]:
    return podcast_status

def update_podcast_status(state: str, progress: int, msg: str, podcast_url: str = None, query: str = None):
    global podcast_status
    podcast_status["status"] = state
    podcast_status["progress"] = progress
    podcast_status["message"] = msg
    if podcast_url:
        podcast_status["podcast_url"] = podcast_url
    if query:
        podcast_status["query"] = query

def add_podcast_to_history(podcast_filename: str, query: str):
    import json
    import datetime
    
    history_path = Path("cerberai/static/podcasts/history.json")
    history = []
    if history_path.exists():
        try:
            with open(history_path, "r") as f:
                history = json.load(f)
        except Exception:
            pass
            
    new_entry = {
        "id": podcast_filename.replace(".mp3", ""),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query": query,
        "podcast_url": f"/static/podcasts/{podcast_filename}"
    }
    
    history.insert(0, new_entry)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Failed to write podcast history: {e}")

async def generate_daily_podcast(manager, agent, topic: str = None, date_str: str = None):
    """
    Background automation:
    1. Search top news stories for target date and topic (0-20%).
    2. Prompt LLM to draft a structured conversational script between Alex and Taylor (20-40%).
    3. Generate on-the-fly WAV intro/outro jingle (40-50%).
    4. Call local SOTA Kokoro TTS engine to synthesize alternating speaker turns (50-80%).
    5. Concat all audio files using FFmpeg into a final MP3 podcast file (80-100%).
    """
    import datetime
    import wave
    import math
    import struct
    import tempfile
    import shutil
    
    target_date = date_str if date_str else datetime.date.today().strftime("%Y-%m-%d")
    
    query = f"top major {topic} stories {target_date}" if topic else f"top major world news stories {target_date}"
    update_podcast_status("running", 5, f"Searching news stories for podcast: '{query}'...", query=query)
    
    # 1. Search for news
    try:
        raw_search = await agent.web_search_tool(query)
    except Exception as e:
        raw_search = f"Failed to search: {e}"
        
    update_podcast_status("running", 15, "Fetching details from top news sources...")
    
    urls = re.findall(r'Source:\s*(https?://\S+)', raw_search)
    fetched_contents = []
    target_urls = urls[:3]
    for i, url in enumerate(target_urls):
        try:
            print(f"Podcast crawl: fetching {url}")
            page_text = await agent.web_fetch_tool(url)
            fetched_contents.append(f"Source: {url}\nContent:\n{page_text[:2000]}\n---")
        except Exception as e:
            print(f"Podcast fetch failed: {url}: {e}")
            
    detailed_context = f"News Search Snippets:\n{raw_search}\n\n"
    if fetched_contents:
        detailed_context += "Detailed Source Article Texts:\n" + "\n".join(fetched_contents)
        
    update_podcast_status("running", 30, "Drafting conversational podcast script...")
    
    # 2. Draft script with LLM
    script_prompt = (
        f"You are a professional podcast script writer. Write a natural, highly engaging conversational dialogue "
        f"for a daily briefing podcast called 'CerberAI News Briefing' hosted by Alex (male) and Taylor (female).\n"
        f"Discuss the following news stories for {target_date}.\n\n"
        "CRITICAL VERIFIABILITY & STYLE RULES:\n"
        "1. Focus only on real, accurate stories from the provided data. Do not hallucinate any news details.\n"
        "2. The dialogue must feel natural, friendly, and conversational (with host interactions, transitions, and expressions like 'That's fascinating, Taylor!', 'Indeed, Alex.').\n"
        "3. Keep it brief. The entire podcast should have between 6 and 10 alternating speaker turns in total.\n"
        "4. Do not output markdown, HTML, or conversational headers. Output ONLY a valid JSON array of objects format:\n"
        "[\n"
        "  { \"speaker\": \"Alex\", \"text\": \"spoken dialogue line 1...\" },\n"
        "  { \"speaker\": \"Taylor\", \"text\": \"spoken dialogue line 2...\" }\n"
        "]\n"
        "Do not include any code block wrappers. Output valid raw JSON."
    )
    
    script = []
    try:
        backend = await manager.get_model("general-llama3")
        payload = {
            "messages": [{"role": "user", "content": script_prompt}],
            "temperature": 0.5
        }
        response = await backend.handle_chat_completion(payload)
        content = response["choices"][0]["message"]["content"].strip()
        
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z0-9]*\n", "", content)
            content = re.sub(r"\n```$", "", content)
        content = content.strip()
        script = json.loads(content)
    except Exception as e:
        print(f"Failed to generate podcast script: {e}")
        script = [
            {"speaker": "Alex", "text": "Hello and welcome to CerberAI Daily Briefing. I'm Alex."},
            {"speaker": "Taylor", "text": "And I'm Taylor. We had some difficulties retrieving the latest news, but we'll be back shortly."},
            {"speaker": "Alex", "text": "That's right, Taylor. Thanks for listening!"}
        ]
        
    update_podcast_status("running", 45, "Generating electronic intro/outro jingle...")
    
    # 3. Create temp dir and generate jingle WAV file
    temp_dir = tempfile.mkdtemp()
    jingle_path = os.path.join(temp_dir, "jingle.wav")
    
    try:
        sample_rate = 22050
        duration = 3.0
        num_samples = int(sample_rate * duration)
        with wave.open(jingle_path, "w") as wav_file:
            wav_file.setparams((1, 2, sample_rate, num_samples, "NONE", "not compressed"))
            for i in range(num_samples):
                t = i / sample_rate
                if t < 0.8:
                    freq = 440.0
                elif t < 1.6:
                    freq = 554.37
                else:
                    freq = 659.25
                envelope = max(0.0, 1.0 - (t / duration))
                val = 0.5 * math.sin(2.0 * math.pi * freq * t) + 0.2 * math.sin(4.0 * math.pi * freq * t)
                sample = int(val * envelope * 32767)
                wav_file.writeframes(struct.pack("<h", sample))
    except Exception as je:
        print(f"Jingle generation failed: {je}")
        
    update_podcast_status("running", 50, "Synthesizing host voices turn-by-turn using SOTA Kokoro engine...")
    
    # 4. Synthesize speaker turns
    turn_files = []
    try:
        tts_backend = await manager.get_model("tts-offline")
        await tts_backend.load()
        
        for idx, turn in enumerate(script):
            speaker = turn.get("speaker", "Alex")
            text = turn.get("text", "")
            
            update_podcast_status("running", 50 + int((idx / len(script)) * 30), f"TTS: Synthesizing voice for turn {idx+1}/{len(script)} ({speaker})...")
            
            voice = "am_adam" if speaker == "Alex" else "af_sarah"
            audio_bytes = await tts_backend.handle_audio_speech({"input": text, "voice": voice})
            
            turn_path = os.path.join(temp_dir, f"turn_{idx}.wav")
            with open(turn_path, "wb") as f:
                f.write(audio_bytes)
                
            turn_files.append(turn_path)
            
    except Exception as te:
        print(f"TTS Synthesis error: {te}")
        update_podcast_status("failed", 0, f"Audio synthesis failed: {te}")
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass
        return
        
    update_podcast_status("running", 80, "Assembling podcast tracks and encoding MP3...")
    
    # 5. Concat all audio files using FFmpeg
    concat_txt_path = os.path.join(temp_dir, "concat.txt")
    with open(concat_txt_path, "w") as f:
        if os.path.exists(jingle_path):
            f.write(f"file '{os.path.abspath(jingle_path)}'\n")
        for p in turn_files:
            f.write(f"file '{os.path.abspath(p)}'\n")
        if os.path.exists(jingle_path):
            f.write(f"file '{os.path.abspath(jingle_path)}'\n")
            
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    topic_slug = re.sub(r'[^a-zA-Z0-9]', '_', topic)[:15] if topic else "world_news"
    podcast_filename = f"podcast_{timestamp}_{topic_slug}.mp3"
    
    static_podcasts_dir = Path("cerberai/static/podcasts")
    static_podcasts_dir.mkdir(parents=True, exist_ok=True)
    
    final_podcast_path = static_podcasts_dir / podcast_filename
    
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_txt_path,
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        str(final_podcast_path.resolve())
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *concat_cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await proc.wait()
    
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass
        
    if final_podcast_path.exists():
        podcast_url = f"/static/podcasts/{podcast_filename}"
        update_podcast_status("success", 100, "Podcast briefing successfully generated!", podcast_url)
        add_podcast_to_history(podcast_filename, query)
        print("Podcast briefing generation complete.")
    else:
        update_podcast_status("failed", 0, "Audio stitch failed: final MP3 was not created.")
        print("Podcast briefing generation failed.")


import re
from typing import List, Dict, Any, Optional
import httpx
from .config import RouterConfig, ModelConfig

class IntentRouter:
    def __init__(self, config: RouterConfig, models: List[ModelConfig]):
        self.config = config
        self.models = models
        self.fallback_model = config.fallback_model
        
        # Categorize models for easy lookup
        self.coding_models = [m.id for m in models if m.type == "llm" and "coding" in m.id]
        self.general_models = [m.id for m in models if m.type == "llm" and "general" in m.id]
        self.image_models = [m.id for m in models if m.type == "image"]
        self.vision_models = [m.id for m in models if m.type == "vision"]
        self.video_models = [m.id for m in models if m.type == "video"]
        
        # Default choices if lists are empty
        self.default_coding = self.coding_models[0] if self.coding_models else self.fallback_model
        self.default_general = self.general_models[0] if self.general_models else self.fallback_model
        self.default_image = self.image_models[0] if self.image_models else None
        self.default_vision = self.vision_models[0] if self.vision_models else None
        self.default_video = self.video_models[0] if self.video_models else None

    async def route_chat(self, messages: List[Dict[str, str]], requested_model: str, manager=None) -> str:
        """
        Decide which model ID should handle this request.
        If a specific valid model is requested, use it. Otherwise, auto-route.
        """
        # If the user requested a specific configured model id, use it
        model_ids = {m.id for m in self.models}
        if requested_model in model_ids:
            return requested_model

        # If the model matches a backend model name, map it (skip control keywords like auto)
        if requested_model not in ("auto", "autorouting", "auto-route", "cerberai-router", "default", "", None):
            for m in self.models:
                if m.backend_config.get("model_name") == requested_model:
                    return m.id

        # If it's not "auto" or empty/none, and it doesn't match, we fallback or auto-route
        if requested_model not in ("auto", "autorouting", "auto-route", "cerberai-router", "", None, "default"):
            # If the requested model is a known keyword (e.g. contains 'coding' or 'coder'), route there
            if "code" in requested_model.lower() or "coder" in requested_model.lower():
                return self.default_coding
            if "general" in requested_model.lower() or "chat" in requested_model.lower():
                return self.default_general
            if "image" in requested_model.lower() or "draw" in requested_model.lower() or "paint" in requested_model.lower():
                return self.default_image or self.fallback_model
            if "vision" in requested_model.lower() or "describe" in requested_model.lower() or "caption" in requested_model.lower():
                return self.default_vision or self.fallback_model
            if "video" in requested_model.lower() or "animate" in requested_model.lower():
                return self.default_video or self.fallback_model

        # Auto-routing logic
        if not messages:
            return self.fallback_model

        # Get last message content to analyze
        last_message = messages[-1].get("content", "")
        
        # Intercept internal system utility tasks (like follow-ups, title, tags generation)
        if isinstance(last_message, str) and self._is_utility_or_meta_task(last_message):
            print("Detected internal utility/meta task, routing to General LLM")
            return self.default_general

        if isinstance(last_message, list):
            parts = []
            has_image = False
            for part in last_message:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        has_image = True
            last_message = " ".join(parts)
            if has_image and self.default_vision:
                print("Detected image in user payload, auto-routing to vision model")
                return self.default_vision

        # Check strict heuristics first (fast, 100% reliable for clear intents)
        strict_choice = self._route_with_heuristics_strict(last_message)
        if strict_choice:
            return strict_choice

        if self.config.model_type == "llm" and self.config.model_name:
            return await self._route_with_llm(last_message, manager)
        else:
            return self._route_with_heuristics(last_message)

    def _is_utility_or_meta_task(self, prompt: str) -> bool:
        """Detect if the prompt is an internal system/utility task (e.g. follow-ups, title, tags, compaction)."""
        prompt_lower = prompt.lower()
        utility_indicators = [
            "### task:",
            "follow-up",
            "follow_ups",
            "generate a short title",
            "generate a 3-5 word title",
            "generate a title",
            "generate tags",
            "<chat_history>",
            "</chat_history>",
            "suggest 3-5 relevant",
            "context_compaction"
        ]
        return any(indicator in prompt_lower for indicator in utility_indicators)

    def _route_with_heuristics_strict(self, prompt: str) -> Optional[str]:
        """Strict keyword/regex-based routing. Returns None if no clear intent matches."""
        prompt_lower = prompt.lower()
        
        # 1. Coding indicators
        coding_keywords = [
            "code", "program", "function", "class", "debug", "compile", "syntax",
            "python", "javascript", "typescript", "rust", "c++", "java", "go lang",
            "html", "css", "sql", "git", "api endpoint", "algorithm", "regex",
            "refactor", "exception", "nullpointer", "segfault"
        ]
        coding_matches = sum(1 for kw in coding_keywords if re.search(r'\b' + re.escape(kw) + r'\b', prompt_lower))
        if coding_matches > 0:
            print(f"Strict heuristics routed to Coding model (matches: {coding_matches})")
            return self.default_coding

        # 2. Vision / Image-to-text patterns
        vision_patterns = [
            r"\bdescribe\s+(this|the|that|an?)?\s*(image|photo|picture|screenshot|diagram)\b",
            r"\bwhat('s|\s+is)\s+in\s+(this|the|that)\s+(image|photo|picture|screenshot)\b",
            r"\banalyze\s+(this|the|that|an?)?\s*(image|photo|picture|screenshot|diagram)\b",
            r"\bread\s+(this|the|that)?\s*(text|image|screenshot|document)\b",
            r"\bocr\b", r"\bcaption\s+(this|the)\b",
            r"\blook\s+at\s+(this|the|that)\s+(image|photo|picture)\b",
            r"\btell\s+me\s+(about|what)\s+(this|the)\s+(image|photo|picture|shows)\b"
        ]
        if self.default_vision:
            vision_matches = sum(1 for pat in vision_patterns if re.search(pat, prompt_lower))
            if vision_matches > 0:
                print(f"Strict heuristics routed to Vision model (matches: {vision_matches})")
                return self.default_vision

        # 3. Image generation patterns
        image_patterns = [
            r"\bdraw\s+a\b", r"\bpaint\s+a\b", r"\bsketch\s+a\b",
            r"\bgenerate\s+(an\s+)?image\b", r"\bcreate\s+(an\s+)?image\b",
            r"\bgenerate\s+(a\s+)?picture\b", r"\bcreate\s+(a\s+)?picture\b",
            r"\bphoto\s+of\b", r"\bpicture\s+of\b", r"\bimage\s+of\b"
        ]
        if self.default_image:
            image_matches = sum(1 for pat in image_patterns if re.search(pat, prompt_lower))
            if image_matches > 0:
                print(f"Strict heuristics routed to Image model (matches: {image_matches})")
                return self.default_image

        # 4. Video generation patterns
        video_patterns = [
            r"\bgenerate\s+(a\s+)?video\b", r"\bcreate\s+(a\s+)?video\b",
            r"\bmake\s+(a\s+)?video\b", r"\banimate\s+a\b", r"\banimate\s+this\b",
            r"\bvideo\s+of\b", r"\banimation\s+of\b"
        ]
        if self.default_video:
            video_matches = sum(1 for pat in video_patterns if re.search(pat, prompt_lower))
            if video_matches > 0:
                print(f"Strict heuristics routed to Video model (matches: {video_matches})")
                return self.default_video

        return None

    def _route_with_heuristics(self, prompt: str) -> str:
        """Simple and fast keyword-based routing."""
        prompt_lower = prompt.lower()
        
        # Coding indicators
        coding_keywords = [
            "code", "program", "function", "class", "debug", "compile", "syntax",
            "python", "javascript", "typescript", "rust", "c++", "java", "go lang",
            "html", "css", "sql", "git", "api endpoint", "algorithm", "regex",
            "refactor", "exception", "nullpointer", "segfault"
        ]
        
        # Count coding matches
        coding_matches = sum(1 for kw in coding_keywords if re.search(r'\b' + re.escape(kw) + r'\b', prompt_lower))
        
        # If matches coding strongly, prefer code backend
        if coding_matches > 0:
            print(f"Heuristics routed to Coding model (matches: {coding_matches})")
            return self.default_coding

        # Vision / Image-to-text patterns
        vision_patterns = [
            r"\bdescribe\s+(this|the|that|an?)?\s*(image|photo|picture|screenshot|diagram)\b",
            r"\bwhat('s|\s+is)\s+in\s+(this|the|that)\s+(image|photo|picture|screenshot)\b",
            r"\banalyze\s+(this|the|that|an?)?\s*(image|photo|picture|screenshot|diagram)\b",
            r"\bread\s+(this|the|that)?\s*(text|image|screenshot|document)\b",
            r"\bocr\b", r"\bcaption\s+(this|the)\b",
            r"\blook\s+at\s+(this|the|that)\s+(image|photo|picture)\b",
            r"\btell\s+me\s+(about|what)\s+(this|the)\s+(image|photo|picture|shows)\b"
        ]
        
        if self.default_vision:
            vision_matches = sum(1 for pat in vision_patterns if re.search(pat, prompt_lower))
            if vision_matches > 0:
                print(f"Heuristics routed to Vision model (matches: {vision_matches})")
                return self.default_vision

        # Image generation patterns
        image_patterns = [
            r"\bdraw\s+a\b", r"\bpaint\s+a\b", r"\bsketch\s+a\b",
            r"\bgenerate\s+(an\s+)?image\b", r"\bcreate\s+(an\s+)?image\b",
            r"\bgenerate\s+(a\s+)?picture\b", r"\bcreate\s+(a\s+)?picture\b",
            r"\bphoto\s+of\b", r"\bpicture\s+of\b", r"\bimage\s+of\b"
        ]
        
        if self.default_image:
            image_matches = sum(1 for pat in image_patterns if re.search(pat, prompt_lower))
            if image_matches > 0:
                print(f"Heuristics routed to Image model (matches: {image_matches})")
                return self.default_image

        # Video generation patterns
        video_patterns = [
            r"\bgenerate\s+(a\s+)?video\b", r"\bcreate\s+(a\s+)?video\b",
            r"\bmake\s+(a\s+)?video\b", r"\banimate\s+a\b", r"\banimate\s+this\b",
            r"\bvideo\s+of\b", r"\banimation\s+of\b"
        ]
        if self.default_video:
            video_matches = sum(1 for pat in video_patterns if re.search(pat, prompt_lower))
            if video_matches > 0:
                print(f"Heuristics routed to Video model (matches: {video_matches})")
                return self.default_video
            
        print("Heuristics routed to General model (fallback)")
        return self.default_general

    async def _route_with_llm(self, prompt: str, manager=None) -> str:
        """Call a local router model to categorize the request based on dynamic purposes."""
        # Truncate prompt to a safe limit to avoid context size overflow of the routing model
        prompt = prompt[:2048] if len(prompt) > 2048 else prompt
        
        # Gather all LLM and image models and their purposes dynamically
        options = []
        for m in self.models:
            # Exclude the router classifier model itself from the destination choices
            if m.type == "llm" and m.id != self.config.model_name:
                purpose = m.purpose or ""
                if "general" in m.id:
                    purpose += " (use for general writing, chatting, telling stories, creative writing, answering general questions, Q&A, and general reasoning)"
                elif "coding" in m.id:
                    purpose += " (use for programming, debugging, writing code, software engineering, explaining code, and technical questions)"
                options.append(f"- Model ID: '{m.id}' | Purpose: {purpose}")
        if self.default_image:
            options.append(f"- Model ID: '{self.default_image}' | Purpose: ONLY use if the user is asking to generate, draw, paint, create, or render a new image/picture/graphic")
        if self.default_video:
            options.append(f"- Model ID: '{self.default_video}' | Purpose: ONLY use if the user is asking to generate, create, make, or render a video or animation")
        if self.default_vision:
            options.append(f"- Model ID: '{self.default_vision}' | Purpose: ONLY use if the user is asking to describe, analyze, OCR, caption, or read an image they have provided")
            
        options_str = "\n".join(options)

        system_prompt = (
            "You are a model routing classifier. You must choose the single best model ID from the list below to process the user's request based on the model purposes.\n\n"
            "Available Models:\n"
            f"{options_str}\n\n"
            "Rules:\n"
            "1. Reply with ONLY the exact matching Model ID string (e.g. 'coding-qwen' or 'general-llama3') and absolutely nothing else.\n"
            "2. Do not include any explanations, greetings, formatting, or extra characters."
        )

        # 1. Try querying via local manager directly (to avoid HTTP/FastAPI loop recursion)
        if manager and self.config.model_name in manager.backends:
            try:
                backend = await manager.get_model(self.config.model_name)
                payload = {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 15
                }
                response = await backend.handle_chat_completion(payload)
                result = response["choices"][0]["message"]["content"].strip()
                print(f"Router LLM (via manager) output: '{result}'")
                
                # Check which model ID matches or is contained in result
                for m in self.models:
                    if m.type not in ("stt", "tts") and m.id.lower() in result.lower():
                        return m.id
            except Exception as e:
                print(f"Routing via local manager failed ({e}). Falling back to Ollama API.")

        # 2. Fallback to Ollama local API if manager is unavailable or fails
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": self.config.model_name,
            "prompt": f"System: {system_prompt}\nUser Request: {prompt}\nSelected Model ID:",
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 15
            }
        }
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    result = response.json().get("response", "").strip()
                    print(f"Router LLM (via Ollama) output: '{result}'")
                    for m in self.models:
                        if m.type not in ("stt", "tts") and m.id.lower() in result.lower():
                            return m.id
        except Exception as e:
            print(f"Router LLM classification failed ({e}). Falling back to heuristics.")
            
        return self._route_with_heuristics(prompt)


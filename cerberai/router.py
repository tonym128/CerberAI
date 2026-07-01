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
        
        # Default choices if lists are empty
        self.default_coding = self.coding_models[0] if self.coding_models else self.fallback_model
        self.default_general = self.general_models[0] if self.general_models else self.fallback_model
        self.default_image = self.image_models[0] if self.image_models else None

    async def route_chat(self, messages: List[Dict[str, str]], requested_model: str, manager=None) -> str:
        """
        Decide which model ID should handle this request.
        If a specific valid model is requested, use it. Otherwise, auto-route.
        """
        # If the user requested a specific configured model id, use it
        model_ids = {m.id for m in self.models}
        if requested_model in model_ids:
            return requested_model

        # If the model matches a backend model name, map it
        for m in self.models:
            if m.backend_config.get("model_name") == requested_model:
                return m.id

        # If it's not "auto" or empty/none, and it doesn't match, we fallback or auto-route
        if requested_model not in ("auto", "", None, "default"):
            # If the requested model is a known keyword (e.g. contains 'coding' or 'coder'), route there
            if "code" in requested_model.lower() or "coder" in requested_model.lower():
                return self.default_coding
            if "general" in requested_model.lower() or "chat" in requested_model.lower():
                return self.default_general
            if "image" in requested_model.lower() or "draw" in requested_model.lower() or "paint" in requested_model.lower():
                return self.default_image or self.fallback_model

        # Auto-routing logic
        if not messages:
            return self.fallback_model

        # Get last message content to analyze
        last_message = messages[-1].get("content", "")
        
        if self.config.model_type == "llm" and self.config.model_name:
            return await self._route_with_llm(last_message, manager)
        else:
            return self._route_with_heuristics(last_message)

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
            
        print("Heuristics routed to General model (fallback)")
        return self.default_general

    async def _route_with_llm(self, prompt: str, manager=None) -> str:
        """Call a local router model to categorize the request based on dynamic purposes."""
        # Gather all LLM and image models and their purposes dynamically
        options = []
        for m in self.models:
            if m.type == "llm":
                purpose = m.purpose or ("for general writing, chat, Q&A, and fallback reasoning" if "general" in m.id else "for programming, debugging, and software engineering")
                options.append(f"- Model ID: '{m.id}' | Purpose: {purpose}")
        if self.default_image:
            options.append(f"- Model ID: '{self.default_image}' | Purpose: for generating images, drawing, painting, or graphics")
            
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
                    if m.id.lower() in result.lower():
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
                        if m.id.lower() in result.lower():
                            return m.id
        except Exception as e:
            print(f"Router LLM classification failed ({e}). Falling back to heuristics.")
            
        return self._route_with_heuristics(prompt)


import httpx
from typing import Dict, Any, AsyncIterator
from .base import BaseBackend

class OllamaBackend(BaseBackend):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        super().__init__(model_id, config, vram_estimate_gb)
        self.base_url = config.get("base_url", "http://localhost:11434").rstrip("/")
        self.model_name = config.get("model_name")
        if not self.model_name:
            raise ValueError(f"Ollama model_name must be specified in backend_config for {model_id}")

    async def ensure_pulled(self) -> bool:
        """Verify model exists in Ollama, otherwise pull it."""
        show_url = f"{self.base_url}/api/show"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(show_url, json={"name": self.model_name})
                if response.status_code == 200:
                    return True
        except Exception:
            pass

        # Try to pull model
        pull_url = f"{self.base_url}/api/pull"
        print(f"Model '{self.model_name}' not found in Ollama locally. Pulling...")
        try:
            import json
            async with httpx.AsyncClient(timeout=1200.0) as client:
                async with client.stream("POST", pull_url, json={"name": self.model_name}) as response:
                    if response.status_code != 200:
                        print(f"Failed to start Ollama pull: HTTP {response.status_code}")
                        return False
                    
                    last_pct = -5.0
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                status = data.get("status", "")
                                completed = data.get("completed", 0)
                                total = data.get("total", 0)
                                if status == "downloading" and total > 0:
                                    pct = (completed / total) * 100
                                    if pct - last_pct >= 5.0 or completed == total:
                                        print(f"Ollama pull '{self.model_name}' progress: {pct:.1f}% ({completed/1024/1024:.1f}MB/{total/1024/1024:.1f}MB)")
                                        last_pct = pct
                                elif status and status != "downloading":
                                    print(f"Ollama pull status: {status}")
                            except Exception:
                                pass
            print(f"Ollama successfully pulled '{self.model_name}'")
            return True
        except Exception as e:
            print(f"Error pulling model '{self.model_name}' from Ollama: {e}")
            return False

    async def load(self) -> bool:
        """Tell Ollama to load the model into memory with a long keep_alive."""
        # Auto-pull if not available
        await self.ensure_pulled()

        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": "",
            "keep_alive": -1 # Keep loaded until explicitly unloaded
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    self._is_loaded = True
                    return True
        except Exception as e:
            # Logs can be added or stdout printed
            print(f"Failed to load Ollama model {self.model_name}: {e}")
        return False


    async def unload(self) -> bool:
        """Tell Ollama to unload the model from memory (set keep_alive to 0)."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": "",
            "keep_alive": 0 # Unload immediately
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    self._is_loaded = False
                    return True
        except Exception as e:
            print(f"Failed to unload Ollama model {self.model_name}: {e}")
        # Even if request failed, assume unloaded to avoid lockups
        self._is_loaded = False
        return False

    async def is_loaded(self) -> bool:
        """Check if the model is currently loaded in Ollama's memory."""
        url = f"{self.base_url}/api/ps"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    for m in models:
                        # Ollama names might have tags, e.g., "llama3:latest" or "llama3"
                        # We do a substring match or normalized compare
                        m_name = m.get("name", "")
                        if m_name == self.model_name or m_name.split(":")[0] == self.model_name.split(":")[0]:
                            self._is_loaded = True
                            return True
            self._is_loaded = False
            return False
        except Exception as e:
            print(f"Failed to check if Ollama model is loaded: {e}")
            return self._is_loaded

    async def handle_chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Forward the OpenAI compatible request to Ollama's OpenAI API endpoint."""
        url = f"{self.base_url}/v1/chat/completions"
        # Ensure the model name in payload matches what Ollama expects
        modified_payload = payload.copy()
        modified_payload["model"] = self.model_name

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(url, json=modified_payload)
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"Ollama returned error {response.status_code}: {response.text}")

    async def stream_chat_completion(self, payload: Dict[str, Any]) -> AsyncIterator[bytes]:
        """Forward the OpenAI compatible request and stream the response."""
        url = f"{self.base_url}/v1/chat/completions"
        modified_payload = payload.copy()
        modified_payload["model"] = self.model_name
        modified_payload["stream"] = True

        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream("POST", url, json=modified_payload) as response:
                if response.status_code != 200:
                    # Read the error content
                    err_content = await response.aread()
                    raise Exception(f"Ollama returned error {response.status_code}: {err_content.decode(errors='ignore')}")
                async for chunk in response.aiter_bytes():
                    yield chunk


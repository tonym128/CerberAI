import os
import asyncio
import subprocess
import httpx
from typing import Dict, Any, Optional, AsyncIterator
from .base import BaseBackend

class LlamaCppBackend(BaseBackend):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        super().__init__(model_id, config, vram_estimate_gb)
        self.repo_id = config.get("repo_id")
        self.filename = config.get("filename")
        self.model_path = config.get("model_path")
        self.llama_server_path = config.get("llama_server_path", "llama-server")
        self.port = config.get("port", 8081)
        self.host = config.get("host", "127.0.0.1")
        self.n_gpu_layers = config.get("n_gpu_layers", 0)
        self.ctx_size = config.get("ctx_size", 4096)
        self.additional_args = config.get("additional_args", [])
        self.mmproj_repo_id = config.get("mmproj_repo_id")
        self.mmproj_filename = config.get("mmproj_filename")
        self.mmproj_path = config.get("mmproj_path")
        
        if not self.model_path and not (self.repo_id and self.filename):
            raise ValueError(f"llama.cpp backend for {model_id} must specify either 'model_path' or both 'repo_id' and 'filename'")
            
        self.process: Optional[subprocess.Popen] = None


    async def load(self, progress_callback=None) -> bool:
        """Start the llama-server subprocess and wait for it to become healthy."""
        import shutil

        # Auto-download llama-server binary if missing
        if not shutil.which(self.llama_server_path) and not os.path.exists(self.llama_server_path):
            from ..downloader import ensure_llama_server
            try:
                self.llama_server_path = await ensure_llama_server()
            except Exception as e:
                print(f"Failed to auto-download llama-server binary: {e}")
                return False

        # Auto-download GGUF if missing
        if not self.model_path or not os.path.exists(self.model_path):
            if self.repo_id and self.filename:
                from ..downloader import ensure_gguf_model
                try:
                    self.model_path = await ensure_gguf_model(self.repo_id, self.filename, progress_callback)
                except Exception as e:
                    print(f"Failed to auto-download GGUF model: {e}")
                    return False
            else:
                print(f"Error: model_path '{self.model_path}' does not exist and no Hugging Face repo details are configured.")
                return False

        # Auto-download mmproj GGUF for vision models if missing
        if self.mmproj_filename and (not self.mmproj_path or not os.path.exists(self.mmproj_path)):
            if self.mmproj_repo_id and self.mmproj_filename:
                from ..downloader import ensure_gguf_model
                try:
                    self.mmproj_path = await ensure_gguf_model(self.mmproj_repo_id, self.mmproj_filename, progress_callback)
                except Exception as e:
                    print(f"Failed to auto-download mmproj model: {e}")
                    return False

        if self.process and self.process.poll() is None:
            # Process is already running
            self._is_loaded = True
            return True



        cmd = [
            self.llama_server_path,
            "-m", self.model_path,
            "--port", str(self.port),
            "--host", self.host,
            "-c", str(self.ctx_size),
            "-ngl", str(self.n_gpu_layers)
        ]

        # Add multimodal projector for vision models
        if self.mmproj_path and os.path.exists(self.mmproj_path):
            cmd.extend(["--mmproj", self.mmproj_path])
        
        # Add any additional arguments
        if isinstance(self.additional_args, list):
            cmd.extend(self.additional_args)
            
        # Prepare environment variables to include the dynamic libraries next to llama-server
        env = os.environ.copy()
        server_dir = os.path.dirname(self.llama_server_path)
        if server_dir:
            server_dir_abs = os.path.abspath(server_dir)
            current_ld = env.get("LD_LIBRARY_PATH", "")
            if current_ld:
                env["LD_LIBRARY_PATH"] = f"{server_dir_abs}:{current_ld}"
            else:
                env["LD_LIBRARY_PATH"] = server_dir_abs

        print(f"Starting llama.cpp server: {' '.join(cmd)}")
        try:
            # Run in a new process group or ignore stdin/stdout to avoid locking
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )

            
            # Wait for the server to be healthy
            health_url = f"http://{self.host}:{self.port}/health"
            async with httpx.AsyncClient() as client:
                for i in range(60): # Try for 60 seconds
                    await asyncio.sleep(1.0)
                    # Check if subprocess died early
                    if self.process.poll() is not None:
                        stdout, stderr = self.process.communicate()
                        print(f"llama-server exited with code {self.process.returncode}. Stderr: {stderr}")
                        self.process = None
                        return False
                    
                    try:
                        response = await client.get(health_url)
                        # llama-server returns status "ok" or 200 OK
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("status") == "ok" or data.get("status") == "healthy" or "status" not in data:
                                self._is_loaded = True
                                return True
                    except httpx.RequestError:
                        pass # Server not up yet
            
            # If we reached here, server didn't start in time. Kill it.
            await self.unload()
            return False
        except Exception as e:
            print(f"Failed to start llama.cpp server: {e}")
            if self.process:
                self.process.kill()
                self.process = None
            return False

    async def unload(self) -> bool:
        """Terminate the llama-server subprocess and wait for exit to release VRAM."""
        proc = self.process
        if not proc:
            self._is_loaded = False
            return True
            
        self.process = None
        self._is_loaded = False
        
        print(f"Terminating llama.cpp server on port {self.port}...")
        try:
            proc.terminate()
            # Wait up to 5 seconds for clean exit
            for _ in range(10):
                if proc.poll() is not None:
                    break
                await asyncio.sleep(0.5)
            
            if proc.poll() is None:
                print("Force killing llama.cpp server...")
                proc.kill()
                proc.wait()
        except Exception as e:
            print(f"Error terminating llama.cpp server: {e}")
        return True

    async def is_loaded(self) -> bool:
        """Check if subprocess is alive."""
        if self.process and self.process.poll() is None:
            self._is_loaded = True
            return True
        self._is_loaded = False
        return False

    async def handle_chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Forward request to the llama-server's OpenAI endpoint, with auto-restart on connection failure."""
        url = f"http://{self.host}:{self.port}/v1/chat/completions"
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    response = await client.post(url, json=payload)
                    if response.status_code == 200:
                        try:
                            return response.json()
                        except Exception as je:
                            print(f"Error: llama-server on port {self.port} returned 200 OK but content is not valid JSON!")
                            print(f"Content: {response.text}")
                            raise Exception(f"llama-server returned 200 OK but response is not valid JSON: {response.text}") from je
                    else:
                        raise Exception(f"llama-server returned error {response.status_code}: {response.text}")
            except (httpx.ConnectError, httpx.ConnectTimeout) as ce:
                print(f"Connection to llama-server on port {self.port} failed (attempt {attempt+1}/2): {ce}")
                if attempt == 0:
                    print("Attempting to restart llama-server...")
                    await self.unload()
                    success = await self.load()
                    if not success:
                        raise Exception(f"Failed to restart llama-server on port {self.port}: {ce}")
                else:
                    raise

    async def stream_chat_completion(self, payload: Dict[str, Any]) -> AsyncIterator[bytes]:
        """Forward the OpenAI compatible request and stream the response, with auto-restart on connection failure."""
        url = f"http://{self.host}:{self.port}/v1/chat/completions"
        modified_payload = payload.copy()
        modified_payload["stream"] = True
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    async with client.stream("POST", url, json=modified_payload) as response:
                        if response.status_code != 200:
                            err_content = await response.aread()
                            raise Exception(f"llama-server returned error {response.status_code}: {err_content.decode(errors='ignore')}")
                        async for chunk in response.aiter_bytes():
                            yield chunk
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as ce:
                print(f"Connection to llama-server on port {self.port} failed during stream (attempt {attempt+1}/2): {ce}")
                if attempt == 0:
                    print("Attempting to restart llama-server for stream...")
                    await self.unload()
                    success = await self.load()
                    if not success:
                        raise Exception(f"Failed to restart llama-server on port {self.port}: {ce}")
                else:
                    raise



import os
import asyncio
import subprocess
import httpx
import time
from typing import Dict, Any, Optional, AsyncIterator
from .base import BaseBackend

def get_exit_code_description(code: int) -> str:
    """Translates subprocess return codes to human-readable descriptions, handling platform differences."""
    if code is None:
        return "Still running"
        
    import platform
    if platform.system() == "Windows":
        unsigned_code = code & 0xFFFFFFFF
        status_map = {
            0x00000000: "Success",
            0xC0000005: "Access Violation (Segmentation Fault / SIGSEGV)",
            0xC00000FD: "Stack Overflow",
            0xC0000094: "Integer Division by Zero",
            0xC000001D: "Illegal Instruction (SIGILL)",
            0xC000013A: "Ctrl+C / Interrupted",
            0xC0000142: "DLL Initialization Failed",
            0xC0000409: "Security Check Failure (Stack Buffer Overrun)",
        }
        return status_map.get(unsigned_code, f"Windows Exit Code 0x{unsigned_code:08X} ({code})")
    else:
        if code < 0:
            sig = -code
            import signal
            try:
                sig_name = signal.Signals(sig).name
                return f"Killed by signal {sig} ({sig_name})"
            except ValueError:
                return f"Killed by signal {sig}"
        return f"Exit Code {code}"


class SubprocessManager:
    """Handles the raw OS subprocess management and execution of llama-server."""
    
    def __init__(self, model_id: str, config: Dict[str, Any], port: int, host: str):
        self.model_id = model_id
        self.config = config
        self.port = port
        self.host = host
        self.process: Optional[subprocess.Popen] = None

    async def start(self, progress_callback=None) -> bool:
        """Start the llama-server subprocess and wait for health checks."""
        import shutil
        import os
        import platform
        import psutil
        import time

        # Kill any orphaned process occupying this port to prevent binding crashes
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                for conn in proc.connections(kind='inet'):
                    if conn.laddr.port == self.port:
                        print(f"Port {self.port} is occupied by process {proc.info['name']} (PID: {proc.info['pid']}). Terminating orphaned engine process...")
                        if progress_callback:
                            progress_callback(f"[1/3] Terminating orphaned engine process on port {self.port}...")
                        try:
                            proc.terminate()
                            proc.wait(timeout=2.0)
                        except psutil.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=1.0)
                        except Exception as e:
                            print(f"Error killing process {proc.info['pid']}: {e}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        llama_server_path = self.config.get("llama_server_path", "llama-server")
        model_path = self.config.get("model_path")
        repo_id = self.config.get("repo_id")
        filename = self.config.get("filename")
        mmproj_repo_id = self.config.get("mmproj_repo_id")
        mmproj_filename = self.config.get("mmproj_filename")
        mmproj_path = self.config.get("mmproj_path")
        n_gpu_layers = self.config.get("n_gpu_layers", 0)
        ctx_size = self.config.get("ctx_size", 4096)
        additional_args = self.config.get("additional_args", [])

        # Auto-download llama-server binary if missing
        if not shutil.which(llama_server_path) and not os.path.exists(llama_server_path):
            if progress_callback:
                progress_callback("[2/3] Downloading llama-server binary...")
            from ..downloader import ensure_llama_server
            try:
                llama_server_path = await ensure_llama_server()
            except Exception as e:
                print(f"Failed to auto-download llama-server binary: {e}")
                return False

        # Auto-download GGUF if missing
        if not model_path or not os.path.exists(model_path):
            if repo_id and filename:
                if progress_callback:
                    progress_callback("[2/3] Downloading model GGUF checkpoints...")
                from ..downloader import ensure_gguf_model
                try:
                    model_path = await ensure_gguf_model(repo_id, filename, progress_callback)
                except Exception as e:
                    print(f"Failed to auto-download GGUF model: {e}")
                    return False
            else:
                print(f"Error: model_path '{model_path}' does not exist and no Hugging Face repo details are configured.")
                return False

        # Auto-download mmproj GGUF for vision models if missing
        if mmproj_filename and (not mmproj_path or not os.path.exists(mmproj_path)):
            if mmproj_repo_id and mmproj_filename:
                if progress_callback:
                    progress_callback("[2/3] Downloading vision projector GGUF checkpoints...")
                from ..downloader import ensure_gguf_model
                try:
                    mmproj_path = await ensure_gguf_model(mmproj_repo_id, mmproj_filename, progress_callback)
                except Exception as e:
                    print(f"Failed to auto-download mmproj model: {e}")
                    return False

        if self.process and self.process.poll() is None:
            return True

        cmd = [
            llama_server_path,
            "-m", model_path,
            "--port", str(self.port),
            "--host", self.host,
            "-c", str(ctx_size),
            "-ngl", str(n_gpu_layers),
            "--embedding"
        ]

        # Add multimodal projector for vision models
        if mmproj_path and os.path.exists(mmproj_path):
            cmd.extend(["--mmproj", mmproj_path])
        
        # Add any additional arguments
        if isinstance(additional_args, list):
            cmd.extend(additional_args)
            
        # Prepare environment variables
        env = os.environ.copy()
        server_dir = os.path.dirname(llama_server_path)
        if server_dir:
            server_dir_abs = os.path.abspath(server_dir)
            system = platform.system()
            if system == "Windows":
                current_path = env.get("PATH", "")
                env["PATH"] = f"{server_dir_abs};{current_path}" if current_path else server_dir_abs
            elif system == "Darwin":
                current_dyld = env.get("DYLD_LIBRARY_PATH", "")
                env["DYLD_LIBRARY_PATH"] = f"{server_dir_abs}:{current_dyld}" if current_dyld else server_dir_abs
            else:  # Linux
                current_ld = env.get("LD_LIBRARY_PATH", "")
                env["LD_LIBRARY_PATH"] = f"{server_dir_abs}:{current_ld}" if current_ld else server_dir_abs

        print(f"Starting llama.cpp server: {' '.join(cmd)}")
        if progress_callback:
            progress_callback(f"[3/3] Launching local engine server (port {self.port})...")
        try:
            popen_args = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "env": env
            }
            if platform.system() != "Windows":
                popen_args["preexec_fn"] = os.setsid
            else:
                popen_args["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

            self.process = subprocess.Popen(cmd, **popen_args)
            
            # Wait for health status
            health_url = f"http://{self.host}:{self.port}/health"
            async with httpx.AsyncClient() as client:
                for i in range(60): # 60 seconds timeout
                    if progress_callback:
                        progress_callback(f"[3/3] Warming up KV Cache (health check attempt {i+1}/60)...")
                    await asyncio.sleep(1.0)
                    if self.process.poll() is not None:
                        stdout, stderr = self.process.communicate()
                        exit_desc = get_exit_code_description(self.process.returncode)
                        print(f"llama-server exited early. Reason: {exit_desc}. Stderr: {stderr}")
                        self.process = None
                        return False
                    
                    try:
                        response = await client.get(health_url)
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("status") in ("ok", "healthy") or "status" not in data:
                                return True
                    except httpx.RequestError:
                        pass # Server still booting
            
            # Timeout reached, stop server
            await self.stop()
            return False
        except Exception as e:
            print(f"Failed to start llama.cpp server: {e}")
            if self.process:
                self.process.kill()
                self.process = None
            return False

    async def stop(self) -> bool:
        """Terminate the process cleanly."""
        proc = self.process
        if not proc:
            return True
            
        self.process = None
        print(f"Terminating llama.cpp server on port {self.port}...")
        try:
            proc.terminate()
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

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None


class LlamaCppBackend(BaseBackend):
    """Binds Process management (SubprocessManager) to the API handlers, tracking diagnostics."""
    
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        super().__init__(model_id, config, vram_estimate_gb)
        self.port = config.get("port", 8081)
        self.host = config.get("host", "127.0.0.1")
        
        self.subprocess_manager = SubprocessManager(model_id, config, self.port, self.host)

    async def load(self, progress_callback=None) -> bool:
        start_time = time.time()
        try:
            success = await self.subprocess_manager.start(progress_callback)
            self._is_loaded = success
            if success:
                self.load_time_seconds = time.time() - start_time
                self.last_active_timestamp = time.time()
            return success
        except Exception as e:
            self.last_error = str(e)
            self._is_loaded = False
            return False

    async def unload(self) -> bool:
        success = await self.subprocess_manager.stop()
        self._is_loaded = not success
        return success

    async def is_loaded(self) -> bool:
        alive = self.subprocess_manager.is_running()
        self._is_loaded = alive
        return alive

    async def handle_chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Forward request to the llama-server's OpenAI endpoint, with auto-restart on connection failure."""
        url = f"http://{self.host}:{self.port}/v1/chat/completions"
        self.calls_count += 1
        self.last_active_timestamp = time.time()
        
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    response = await client.post(url, json=payload)
                    if response.status_code == 200:
                        try:
                            return response.json()
                        except Exception as je:
                            print(f"Error: llama-server returned 200 OK but content is not valid JSON! {response.text}")
                            self.last_error = f"Invalid JSON returned: {response.text}"
                            raise Exception("Invalid JSON returned from llama-server.") from je
                    else:
                        self.last_error = f"Error {response.status_code}: {response.text}"
                        raise Exception(f"llama-server returned error {response.status_code}: {response.text}")
            except (httpx.ConnectError, httpx.ConnectTimeout) as ce:
                print(f"Connection to llama-server on port {self.port} failed (attempt {attempt+1}/2): {ce}")
                self.last_error = str(ce)
                if attempt == 0:
                    print("Attempting to restart llama-server...")
                    await self.unload()
                    success = await self.load()
                    if not success:
                        raise Exception(f"Failed to restart llama-server on port {self.port}: {ce}")
                else:
                    raise

    async def stream_chat_completion(self, payload: Dict[str, Any]) -> AsyncIterator[bytes]:
        """Forward request and stream responses, with auto-restart on connection failure."""
        url = f"http://{self.host}:{self.port}/v1/chat/completions"
        modified_payload = payload.copy()
        modified_payload["stream"] = True
        
        self.calls_count += 1
        self.last_active_timestamp = time.time()

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    async with client.stream("POST", url, json=modified_payload) as response:
                        if response.status_code != 200:
                            err_content = await response.aread()
                            self.last_error = f"Error {response.status_code}: {err_content.decode()}"
                            raise Exception(f"llama-server returned error {response.status_code}: {err_content.decode(errors='ignore')}")
                        async for chunk in response.aiter_bytes():
                            yield chunk
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as ce:
                print(f"Connection to llama-server on port {self.port} failed during stream (attempt {attempt+1}/2): {ce}")
                self.last_error = str(ce)
                if attempt == 0:
                    print("Attempting to restart llama-server for stream...")
                    await self.unload()
                    success = await self.load()
                    if not success:
                        raise Exception(f"Failed to restart llama-server on port {self.port}: {ce}")
                else:
                    raise

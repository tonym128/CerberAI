import os
import time
import base64
import random
import json
import asyncio
from subprocess import Popen, PIPE
from urllib.parse import urlparse
from pathlib import Path
from typing import Dict, Any, Optional
import httpx
import psutil
from .base import BaseBackend

class ComfyUIBackend(BaseBackend):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        super().__init__(model_id, config, vram_estimate_gb)
        self.server_url = config.get("server_url", "http://127.0.0.1:8188").rstrip("/")
        self.workflow_path = config.get("workflow_path", "")
        # Defaults to finding CLIPTextEncode, KSampler, etc. if not configured
        self.prompt_node_id = config.get("prompt_node_id", None)
        self.negative_prompt_node_id = config.get("negative_prompt_node_id", None)
        self.seed_node_id = config.get("seed_node_id", None)
        self.image_node_id = config.get("image_node_id", None)
        
        # Subprocess tracking
        self.process: Optional[Popen] = None
        self.started_by_us = False

    def _get_install_paths(self):
        install_dir = Path(os.path.expanduser("~/.cache/cerberai/comfyui"))
        venv_dir = install_dir / "venv"
        python_exe = venv_dir / "bin" / "python"
        pip_exe = venv_dir / "bin" / "pip"
        main_py = install_dir / "main.py"
        return install_dir, venv_dir, python_exe, pip_exe, main_py

    async def _run_command(self, cmd, cwd=None, env=None, progress_callback=None, progress_msg=""):
        if progress_callback:
            # Helper to check if callback is coroutine or normal function
            import inspect
            try:
                if inspect.iscoroutinefunction(progress_callback):
                    await progress_callback(progress_msg)
                else:
                    progress_callback(progress_msg)
            except Exception as ex:
                print(f"Warning: Failed calling installation progress callback: {ex}")
        print(f"Executing command: {cmd}")
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            err_output = stderr.decode('utf-8', errors='ignore')
            print(f"Command failed (exit {process.returncode}): {err_output}")
            raise RuntimeError(f"Command failed: {cmd}\nError: {err_output}")
        return stdout.decode('utf-8', errors='ignore')

    async def _ensure_installed(self, progress_callback=None) -> bool:
        install_dir, venv_dir, python_exe, pip_exe, main_py = self._get_install_paths()
        
        # Check if main.py and python_exe exist, and all core dependencies can be imported
        if main_py.exists() and python_exe.exists():
            try:
                # Run a quick check to verify the environment imports are working properly
                process = await asyncio.create_subprocess_shell(
                    f"{python_exe} -c 'import torch; import torchvision; import torchaudio; import sqlalchemy; import alembic; import PIL; import numpy'",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()
                if process.returncode == 0:
                    return True
                else:
                    print("ComfyUI dependencies are incomplete or broken. Repairing installation...")
                    if progress_callback:
                        import inspect
                        msg = "ComfyUI dependencies are incomplete or broken. Repairing installation..."
                        if inspect.iscoroutinefunction(progress_callback):
                            await progress_callback(msg)
                        else:
                            progress_callback(msg)
            except Exception:
                pass

        print("Installing ComfyUI locally...")
        if progress_callback:
            import inspect
            msg = "[2/3] Installing ComfyUI: Creating directory structure..."
            try:
                if inspect.iscoroutinefunction(progress_callback):
                    await progress_callback(msg)
                else:
                    progress_callback(msg)
            except Exception as ex:
                print(f"Warning: Failed calling installation progress callback: {ex}")
            
        install_dir.parent.mkdir(parents=True, exist_ok=True)
        
        # 1. Clone ComfyUI repo
        if not main_py.exists():
            await self._run_command(
                f"git clone https://github.com/comfyanonymous/ComfyUI.git {install_dir}",
                progress_callback=progress_callback,
                progress_msg="[2/3] Installing ComfyUI: Cloning ComfyUI repository..."
            )
            
        # 2. Create Virtual Environment
        if not venv_dir.exists():
            await self._run_command(
                f"python -m venv {venv_dir}",
                progress_callback=progress_callback,
                progress_msg="[2/3] Installing ComfyUI: Creating python virtual environment..."
            )
            
        # 3. Upgrade pip
        await self._run_command(
            f"{pip_exe} install --upgrade pip",
            progress_callback=progress_callback,
            progress_msg="[2/3] Installing ComfyUI: Upgrading pip inside virtual environment..."
        )

        # 4. Install PyTorch depending on environment
        import torch
        is_rocm = False
        rocm_version = ""
        index_url = ""
        if torch.cuda.is_available():
            hip_ver = getattr(torch.version, 'hip', None)
            if hip_ver:
                is_rocm = True
                parts = hip_ver.split(".")
                rocm_version = parts[0] + "." + parts[1] if len(parts) >= 2 else "6.1"
                index_url = f"https://download.pytorch.org/whl/rocm{rocm_version}"
            else:
                try:
                    device_name = torch.cuda.get_device_name(0).lower()
                    if "amd" in device_name or "radeon" in device_name:
                        is_rocm = True
                        rocm_version = "6.1"
                        index_url = "https://download.pytorch.org/whl/rocm6.1"
                except Exception:
                    pass

        if is_rocm:
            install_cmd = f"{pip_exe} install torch torchvision torchaudio --index-url {index_url}"
            msg = f"[2/3] Installing ComfyUI: Installing PyTorch for AMD ROCm {rocm_version}..."
        elif torch.cuda.is_available():
            install_cmd = f"{pip_exe} install torch torchvision torchaudio"
            msg = "[2/3] Installing ComfyUI: Installing PyTorch with CUDA support..."
        else:
            index_url = "https://download.pytorch.org/whl/cpu"
            install_cmd = f"{pip_exe} install torch torchvision torchaudio --index-url {index_url}"
            msg = "[2/3] Installing ComfyUI: Installing PyTorch (CPU fallback)..."

        await self._run_command(
            install_cmd,
            progress_callback=progress_callback,
            progress_msg=msg
        )

        # 5. Install ComfyUI requirements (adding ROCm/CPU index-url as extra-index-url to prevent overrides)
        extra_index_flag = ""
        if index_url:
            extra_index_flag = f"--extra-index-url {index_url}"
            
        await self._run_command(
            f"{pip_exe} install -r requirements.txt {extra_index_flag}",
            cwd=str(install_dir),
            progress_callback=progress_callback,
            progress_msg="[2/3] Installing ComfyUI: Installing remaining ComfyUI dependencies..."
        )
        
        print("ComfyUI installed successfully!")
        return True

    async def load(self, progress_callback=None) -> bool:
        """Verify ComfyUI server is running. If not, auto-install and start it as a subprocess."""
        # Parse host and port
        parsed = urlparse(self.server_url)
        port = parsed.port or 8188
        host = parsed.hostname or "127.0.0.1"
        is_local = host in ("127.0.0.1", "localhost", "0.0.0.0")

        # If it's local, we always terminate any running instance on that port to clean up rogue processes
        if is_local:
            print(f"Checking for pre-existing ComfyUI process on port {port}...")
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    for conn in proc.connections(kind='inet'):
                        if conn.laddr.port == port:
                            print(f"Port {port} is occupied by {proc.info['name']} (PID: {proc.info['pid']}). Terminating rogue ComfyUI process...")
                            if progress_callback:
                                import inspect
                                msg = f"[3/3] Terminating rogue ComfyUI process on port {port}..."
                                if inspect.iscoroutinefunction(progress_callback):
                                    await progress_callback(msg)
                                else:
                                    progress_callback(msg)
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
        else:
            # If remote, check if already running and responsive
            print(f"Connecting to remote ComfyUI server at {self.server_url}...")
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.get(f"{self.server_url}/system_stats")
                    if response.status_code == 200:
                        stats = response.json()
                        device_info = stats.get("devices", [{}])[0].get("type", "unknown")
                        print(f"Remote ComfyUI is already running. Device: {device_info}")
                        self._is_loaded = True
                        self.started_by_us = False
                        return True
            except Exception:
                pass

        # If not running locally, make sure it is installed
        await self._ensure_installed(progress_callback)

        # Start ComfyUI process
        install_dir, _, python_exe, _, main_py = self._get_install_paths()
        cmd = [
            str(python_exe),
            str(main_py),
            "--port", str(port),
            "--listen", host
        ]
        
        # Prepare environment variables
        env = os.environ.copy()
        import torch
        if torch.cuda.is_available():
            hip_ver = getattr(torch.version, 'hip', None)
            if hip_ver:
                # Enable HSA_ENABLE_SDMA=1 for faster model loading (set to 0 if hangs occur)
                env["HSA_ENABLE_SDMA"] = "1"

        print(f"Starting ComfyUI server: {' '.join(cmd)}")
        if progress_callback:
            import inspect
            msg = f"[3/3] Launching ComfyUI server (port {port})..."
            if inspect.iscoroutinefunction(progress_callback):
                await progress_callback(msg)
            else:
                progress_callback(msg)
            
        try:
            import platform
            log_path = Path(os.path.expanduser("~/.cache/cerberai/comfyui.log"))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_file = open(log_path, "a", encoding="utf-8")
            
            popen_args = {
                "stdout": self.log_file,
                "stderr": self.log_file,
                "text": True,
                "env": env,
                "cwd": str(install_dir)
            }
            if platform.system() != "Windows":
                popen_args["preexec_fn"] = os.setsid
            else:
                popen_args["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

            self.process = Popen(cmd, **popen_args)
            self.started_by_us = True
            
            # Wait for health status
            health_url = f"{self.server_url}/system_stats"
            async with httpx.AsyncClient() as client:
                for i in range(45): # 45 seconds timeout
                    if progress_callback:
                        import inspect
                        msg = f"[3/3] Waiting for ComfyUI to start (health check {i+1}/45)..."
                        if inspect.iscoroutinefunction(progress_callback):
                            await progress_callback(msg)
                        else:
                            progress_callback(msg)
                    await asyncio.sleep(1.0)
                    
                    if self.process.poll() is not None:
                        stdout, stderr = self.process.communicate()
                        print(f"ComfyUI server exited early. Stderr: {stderr}")
                        self.process = None
                        self.started_by_us = False
                        return False
                    
                    try:
                        response = await client.get(health_url)
                        if response.status_code == 200:
                            print("ComfyUI server started successfully.")
                            self._is_loaded = True
                            return True
                    except httpx.RequestError:
                        pass
            
            # Timeout reached, stop server
            await self.unload()
            return False
        except Exception as e:
            print(f"Failed to start ComfyUI server: {e}")
            if self.process:
                self.process.kill()
                self.process = None
            self.started_by_us = False
            return False

    async def unload(self) -> bool:
        """Stop the ComfyUI subprocess if we started it."""
        self._is_loaded = False
        proc = self.process
        if not proc:
            return True
            
        self.process = None
        if not self.started_by_us:
            return True
            
        print("Terminating ComfyUI server...")
        try:
            proc.terminate()
            for _ in range(10):
                if proc.poll() is not None:
                    break
                await asyncio.sleep(0.5)
            
            if proc.poll() is None:
                print("Force killing ComfyUI server...")
                proc.kill()
                proc.wait()
        except Exception as e:
            print(f"Error terminating ComfyUI: {e}")
            
        # Close log file if opened
        if hasattr(self, "log_file") and self.log_file:
            try:
                self.log_file.close()
            except Exception:
                pass
            self.log_file = None
            
        self.started_by_us = False
        return True

    def _replace_placeholders(self, workflow: Dict[str, Any], replacements: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively search and replace string values or keys in the workflow."""
        workflow_str = json.dumps(workflow)
        for placeholder, value in replacements.items():
            if value is not None:
                # If replacing a seed, we want to replace numerical or string versions
                if placeholder == "__SEED__":
                    workflow_str = workflow_str.replace(f'"{placeholder}"', str(value))
                    workflow_str = workflow_str.replace(placeholder, str(value))
                else:
                    workflow_str = workflow_str.replace(placeholder, str(value))
        return json.loads(workflow_str)

    def _apply_heuristics(self, workflow: Dict[str, Any], prompt: str, negative_prompt: str, seed: int, image_filename: Optional[str] = None):
        """Fallback to finding standard nodes if placeholders are not used."""
        clip_nodes = []
        sampler_nodes = []
        load_image_nodes = []
        
        for node_id, node in workflow.items():
            class_type = node.get("class_type", "")
            if class_type == "CLIPTextEncode":
                clip_nodes.append(node_id)
            elif class_type in ("KSampler", "KSamplerAdvanced", "KSamplerSelect"):
                sampler_nodes.append(node_id)
            elif class_type == "LoadImage":
                load_image_nodes.append(node_id)

        # 1. Update Prompt Node
        if self.prompt_node_id and str(self.prompt_node_id) in workflow:
            workflow[str(self.prompt_node_id)]["inputs"]["text"] = prompt
        elif clip_nodes:
            workflow[clip_nodes[0]]["inputs"]["text"] = prompt

        # 2. Update Negative Prompt Node
        if self.negative_prompt_node_id and str(self.negative_prompt_node_id) in workflow:
            workflow[str(self.negative_prompt_node_id)]["inputs"]["text"] = negative_prompt
        elif len(clip_nodes) > 1:
            workflow[clip_nodes[1]]["inputs"]["text"] = negative_prompt

        # 3. Update Seed Node
        if self.seed_node_id and str(self.seed_node_id) in workflow:
            node = workflow[str(self.seed_node_id)]
            for seed_key in ("seed", "noise_seed"):
                if seed_key in node.get("inputs", {}):
                    node["inputs"][seed_key] = seed
        elif sampler_nodes:
            for s_id in sampler_nodes:
                node = workflow[s_id]
                for seed_key in ("seed", "noise_seed"):
                    if seed_key in node.get("inputs", {}):
                        node["inputs"][seed_key] = seed

        # 4. Update LoadImage Node
        if image_filename:
            if self.image_node_id and str(self.image_node_id) in workflow:
                workflow[str(self.image_node_id)]["inputs"]["image"] = image_filename
            elif load_image_nodes:
                workflow[load_image_nodes[0]]["inputs"]["image"] = image_filename

    async def _upload_image(self, image_b64: str) -> str:
        """Upload a base64 encoded image to ComfyUI input directory."""
        image_data = base64.b64decode(image_b64)
        files = {"image": ("input_image.png", image_data, "image/png")}
        data = {"overwrite": "true"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{self.server_url}/upload/image", files=files, data=data)
            response.raise_for_status()
            res_json = response.json()
            return res_json["name"]

    async def _run_workflow(self, workflow: Dict[str, Any], progress_callback=None) -> bytes:
        """Queue the workflow, poll history until completion, and download the output file."""
        client_id = f"cerberai_{int(time.time())}"
        
        # Post the prompt
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    f"{self.server_url}/prompt",
                    json={"prompt": workflow, "client_id": client_id}
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                try:
                    err_json = e.response.json()
                    err_details = err_json.get("node_errors", err_json.get("error", err_json))
                    err_msg = f"ComfyUI validation error: {json.dumps(err_details)}"
                    print(err_msg)
                    raise ValueError(err_msg) from e
                except Exception:
                    raise e
            res_json = response.json()
            prompt_id = res_json["prompt_id"]

        # Poll history
        start_time = time.time()
        print(f"Queued ComfyUI prompt ID: {prompt_id}")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                hist_res = await client.get(f"{self.server_url}/history/{prompt_id}")
                if hist_res.status_code == 200:
                    history = hist_res.json()
                    if prompt_id in history:
                        execution = history[prompt_id]
                        break
                
                if progress_callback:
                    elapsed = int(time.time() - start_time)
                    import inspect
                    msg = f"⏳ Generating on ComfyUI... ({elapsed}s elapsed)"
                    try:
                        if inspect.iscoroutinefunction(progress_callback):
                            await progress_callback(msg)
                        else:
                            progress_callback(msg)
                    except Exception as ex:
                        print(f"Warning: Failed calling video progress callback: {ex}")
                
                await asyncio.sleep(2.0)

        # Retrieve outputs
        outputs = execution.get("outputs", {})
        if not outputs:
            raise RuntimeError("ComfyUI execution completed but returned no outputs.")

        # Find the generated file in outputs
        filename = None
        subfolder = ""
        folder_type = "output"
        
        for node_id, node_output in outputs.items():
            if "images" in node_output:
                for img in node_output["images"]:
                    if img.get("type") == "output" or img.get("type") == "temp":
                        filename = img["filename"]
                        subfolder = img.get("subfolder", "")
                        folder_type = img.get("type", "output")
                        break
            elif "gifs" in node_output:
                for gif in node_output["gifs"]:
                    filename = gif["filename"]
                    subfolder = gif.get("subfolder", "")
                    folder_type = gif.get("type", "output")
                    break
            
            if filename:
                break

        if not filename:
            raise RuntimeError(f"Could not find any output images or videos in ComfyUI history. Outputs: {outputs}")

        # Download the file
        print(f"Downloading output file '{filename}' from ComfyUI...")
        async with httpx.AsyncClient(timeout=120.0) as client:
            file_res = await client.get(
                f"{self.server_url}/view",
                params={"filename": filename, "subfolder": subfolder, "type": folder_type}
            )
            file_res.raise_for_status()
            return file_res.content

    async def handle_image_generation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generate image using ComfyUI."""
        if not self._is_loaded:
            await self.load()

        prompt = payload.get("prompt", "")
        negative_prompt = payload.get("negative_prompt", "")
        seed = payload.get("seed", random.randint(1, 1125899906842624))

        if not self.workflow_path:
            raise ValueError("workflow_path must be configured in config.yaml for ComfyUI backend.")

        if not os.path.exists(self.workflow_path):
            raise FileNotFoundError(f"Workflow path '{self.workflow_path}' does not exist.")

        with open(self.workflow_path, "r") as f:
            workflow = json.load(f)

        replacements = {
            "__PROMPT__": prompt,
            "__NEGATIVE_PROMPT__": negative_prompt,
            "__SEED__": seed
        }
        workflow = self._replace_placeholders(workflow, replacements)
        self._apply_heuristics(workflow, prompt, negative_prompt, seed)

        image_bytes = await self._run_workflow(workflow)
        b64_data = base64.b64encode(image_bytes).decode("utf-8")

        return {
            "created": int(time.time()),
            "data": [
                {
                    "b64_json": b64_data
                }
            ]
        }

    async def handle_video_generation(self, payload: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
        """Generate video using ComfyUI."""
        if not self._is_loaded:
            await self.load()

        prompt = payload.get("prompt", "")
        negative_prompt = payload.get("negative_prompt", "")
        image_b64 = payload.get("image", None)
        seed = payload.get("seed", random.randint(1, 1125899906842624))

        if not self.workflow_path:
            raise ValueError("workflow_path must be configured in config.yaml for ComfyUI backend.")

        if not os.path.exists(self.workflow_path):
            raise FileNotFoundError(f"Workflow path '{self.workflow_path}' does not exist.")

        with open(self.workflow_path, "r") as f:
            workflow = json.load(f)

        image_filename = None
        if image_b64:
            if progress_callback:
                import inspect
                msg = "📤 Uploading input image to ComfyUI..."
                if inspect.iscoroutinefunction(progress_callback):
                    await progress_callback(msg)
                else:
                    progress_callback(msg)
            image_filename = await self._upload_image(image_b64)

        replacements = {
            "__PROMPT__": prompt,
            "__NEGATIVE_PROMPT__": negative_prompt,
            "__SEED__": seed,
            "__IMAGE__": image_filename
        }
        workflow = self._replace_placeholders(workflow, replacements)
        self._apply_heuristics(workflow, prompt, negative_prompt, seed, image_filename)

        video_bytes = await self._run_workflow(workflow, progress_callback)
        b64_data = base64.b64encode(video_bytes).decode("utf-8")

        return {
            "created": int(time.time()),
            "b64_json": b64_data
        }

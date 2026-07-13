import os
import time
import tempfile
import base64
from typing import Dict, Any
from .base import BaseBackend

class VideoBackend(BaseBackend):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        super().__init__(model_id, config, vram_estimate_gb)
        self.model_name = config.get("model_name", "THUDM/CogVideoX-2b")
        self.current_model_name = None
        self.pipeline = None

    async def load_model(self, model_name: str, progress_callback=None) -> bool:
        """Dynamically load or switch the Video pipeline."""
        if self.pipeline and self.current_model_name == model_name:
            self._is_loaded = True
            return True

        if self.pipeline:
            await self.unload()

        print(f"Loading Video model '{model_name}'...")
        if progress_callback:
            progress_callback("[2/3] Loading PyTorch & Video frameworks...")
        try:
            import torch
            
            if torch.cuda.is_available():
                device = "cuda"
                torch_dtype = torch.float16
            elif hasattr(torch, "xpu") and torch.xpu.is_available():
                device = "xpu"
                torch_dtype = torch.float16
            else:
                device = "cpu"
                torch_dtype = torch.float32

            if progress_callback:
                progress_callback(f"[3/3] Initializing pipeline '{model_name}' on device...")
            if "svd" in model_name.lower() or "img2vid" in model_name.lower():
                from diffusers import StableVideoDiffusionPipeline
                self.pipeline = StableVideoDiffusionPipeline.from_pretrained(
                    model_name,
                    torch_dtype=torch_dtype
                )
            else:
                from diffusers import CogVideoXPipeline
                self.pipeline = CogVideoXPipeline.from_pretrained(
                    model_name,
                    torch_dtype=torch_dtype
                )
            
            # Detect AMD GPU (ROCm) and GPU VRAM capacity
            is_rocm = False
            device_vram_gb = 0.0
            if device == "cuda":
                if getattr(torch.version, "hip", None) is not None:
                    is_rocm = True
                else:
                    try:
                        device_name = torch.cuda.get_device_name(0).lower()
                        if "amd" in device_name or "radeon" in device_name:
                            is_rocm = True
                    except Exception:
                        pass
                try:
                    device_vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                except Exception:
                    pass

            if is_rocm:
                print(f"AMD ROCm GPU detected ({device_vram_gb:.1f} GB VRAM).")

            # Apply memory saving techniques for lower VRAM environments
            if device in ["cuda", "xpu"]:
                # Use actual GPU capacity (device_vram_gb) if detected, otherwise fall back to model estimate.
                effective_vram_gb = device_vram_gb if device_vram_gb > 0.0 else self.vram_estimate_gb
                
                # If we have at least 18GB VRAM (e.g. 24GB cards like RTX 3090/4090 or RX 7900 XTX),
                # we can load the entire model + activations directly into GPU memory.
                if effective_vram_gb >= 18.0:
                    print(f"GPU VRAM ({effective_vram_gb:.1f} GB) is sufficient. Loading model directly to GPU...")
                    self.pipeline.to(device)
                else:
                    if is_rocm:
                        # AMD ROCm requires HSA_ENABLE_SDMA=0 to prevent hangs during CPU offloading.
                        print(f"GPU VRAM ({effective_vram_gb:.1f} GB) is under 18GB. Enabling model-level CPU offloading...")
                        print("Note: Sequential CPU offloading is disabled on ROCm to prevent driver hangs.")
                        self.pipeline.enable_model_cpu_offload()
                    else:
                        if effective_vram_gb <= 10.0:
                            print(f"GPU VRAM ({effective_vram_gb:.1f} GB) is very low. Enabling model offloading & sequential offloading...")
                            self.pipeline.enable_model_cpu_offload()
                            try:
                                self.pipeline.enable_sequential_cpu_offload()
                            except Exception:
                                pass
                        else:
                            print(f"GPU VRAM ({effective_vram_gb:.1f} GB) is under 18GB. Enabling model-level CPU offloading...")
                            self.pipeline.enable_model_cpu_offload()

                # Prevent GPU scheduling timeouts (TDR resets) by splitting VAE operations at pipeline level
                try:
                    if hasattr(self.pipeline, "enable_vae_tiling"):
                        print("Enabling pipeline VAE tiling...")
                        self.pipeline.enable_vae_tiling()
                except Exception as ex:
                    print(f"Warning: Could not enable VAE tiling: {ex}")
                try:
                    if hasattr(self.pipeline, "enable_vae_slicing"):
                        print("Enabling pipeline VAE slicing...")
                        self.pipeline.enable_vae_slicing()
                except Exception as ex:
                    print(f"Warning: Could not enable VAE slicing: {ex}")
            else:
                self.pipeline.to(device)
                
            self.current_model_name = model_name
            self._is_loaded = True
            return True
        except Exception as e:
            print(f"Failed to load Video model '{model_name}': {e}")
            return False

    async def load(self, progress_callback=None) -> bool:
        return await self.load_model(self.model_name, progress_callback)

    async def unload(self) -> bool:
        """Unload pipeline and release VRAM."""
        if not self.pipeline:
            self._is_loaded = False
            return True
            
        print(f"Unloading Video model '{self.current_model_name}'...")
        self.pipeline = None
        self.current_model_name = None
        self._is_loaded = False
        
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        return True

    async def handle_video_generation(self, payload: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
        """Generate video from text or image input, returning base64 encoded mp4 file."""
        async with self.lock:
            # Clear CUDA cache and run GC before allocating memory for pipeline
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                
            image_b64 = payload.get("image")
            
            # Helper to run callback in correct thread context
            import inspect
            async def run_callback(msg: str):
                if progress_callback:
                    try:
                        if inspect.iscoroutinefunction(progress_callback):
                            await progress_callback(msg)
                        else:
                            progress_callback(msg)
                    except Exception as ex:
                        print(f"Warning: Failed calling video progress callback: {ex}")

            if image_b64:
                # Image-to-Video (Stable Video Diffusion)
                model_to_load = "stabilityai/stable-video-diffusion-img2vid-xt"
                await self.load_model(model_to_load)
                
                from PIL import Image
                import io
                image_data = base64.b64decode(image_b64)
                image = Image.open(io.BytesIO(image_data)).convert("RGB").resize((512, 512))
                
                num_frames = payload.get("num_frames", 14)
                num_steps = payload.get("num_inference_steps", 20)
                
                await run_callback("⏳ Step 1: Running image-to-video denoising steps on GPU... Once denoising finishes, 3D VAE decoding will process spatial-temporal frames (runs silently and may take 1-2 minutes).\n")

                import asyncio
                loop = asyncio.get_running_loop()
                
                def run_svd():
                    output = self.pipeline(
                        image,
                        num_frames=num_frames,
                        num_inference_steps=num_steps,
                        decode_chunk_size=8
                    )
                    return output.frames[0]
                    
                video_frames = await loop.run_in_executor(None, run_svd)
            else:
                # Text-to-Video (CogVideoX)
                model_to_load = self.model_name
                await self.load_model(model_to_load)
                
                prompt = payload.get("prompt", "")
                if not prompt:
                    raise ValueError("Prompt is required for video generation.")

                num_frames = payload.get("num_frames", 16)
                num_steps = payload.get("num_inference_steps", 20)
                
                await run_callback("⏳ Step 1: Running text-to-video denoising steps on GPU... Once denoising finishes, 3D VAE decoding will process spatial-temporal frames (runs silently and may take 1-2 minutes).\n")

                import asyncio
                loop = asyncio.get_running_loop()
                
                def run_cogvideo():
                    output = self.pipeline(
                        prompt=prompt,
                        num_frames=num_frames,
                        num_inference_steps=num_steps,
                        guidance_scale=6.0
                    )
                    return output.frames[0]

                video_frames = await loop.run_in_executor(None, run_cogvideo)
            
            await run_callback("⚙️ Step 2: Denoising and VAE decoding complete! Compiling frames to MP4 video file...\n")

            # Export frames to a temporary MP4 file
            from diffusers.utils import export_to_video
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
                tmp_path = tmp_file.name
            
            web_path = None
            try:
                export_to_video(video_frames, tmp_path, fps=8)
                
                # Transcode video to ensure H.264 / yuv420p web-playback compatibility
                web_path = tmp_path + "_web.mp4"
                cmd = [
                    "ffmpeg", "-y",
                    "-i", tmp_path,
                    "-vcodec", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    web_path
                ]
                import subprocess
                try:
                    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    use_path = web_path
                except Exception as ex:
                    print(f"Warning: ffmpeg transcoding failed, falling back to raw export: {ex}")
                    use_path = tmp_path
                    
                with open(use_path, "rb") as f:
                    video_bytes = f.read()
                b64_data = base64.b64encode(video_bytes).decode("utf-8")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                if web_path and os.path.exists(web_path):
                    os.unlink(web_path)
            
            return {
                "created": int(time.time()),
                "b64_json": b64_data
            }

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

    async def load_model(self, model_name: str) -> bool:
        """Dynamically load or switch the Video pipeline."""
        if self.pipeline and self.current_model_name == model_name:
            self._is_loaded = True
            return True

        if self.pipeline:
            await self.unload()

        print(f"Loading Video model '{model_name}'...")
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
            
            # Apply memory saving techniques for lower VRAM environments
            if device in ["cuda", "xpu"]:
                if self.vram_estimate_gb <= 12.0:
                    print("Enabling CPU model offloading & sequential offloading for Video generation (saves VRAM)...")
                    self.pipeline.enable_model_cpu_offload()
                    try:
                        self.pipeline.enable_sequential_cpu_offload()
                    except Exception:
                        pass
                else:
                    self.pipeline.to(device)
            else:
                self.pipeline.to(device)
                
            self.current_model_name = model_name
            self._is_loaded = True
            return True
        except Exception as e:
            print(f"Failed to load Video model '{model_name}': {e}")
            return False

    async def load(self, progress_callback=None) -> bool:
        return await self.load_model(self.model_name)

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

    async def handle_video_generation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generate video from text or image input, returning base64 encoded mp4 file."""
        async with self.lock:
            image_b64 = payload.get("image")
            
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
            
            # Export frames to a temporary MP4 file
            from diffusers.utils import export_to_video
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
                tmp_path = tmp_file.name
            
            try:
                export_to_video(video_frames, tmp_path, fps=8)
                with open(tmp_path, "rb") as f:
                    video_bytes = f.read()
                b64_data = base64.b64encode(video_bytes).decode("utf-8")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            
            return {
                "created": int(time.time()),
                "b64_json": b64_data
            }

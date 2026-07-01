import os
import time
import base64
import io
from typing import Dict, Any
from .base import BaseBackend

class DiffusersBackend(BaseBackend):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        super().__init__(model_id, config, vram_estimate_gb)
        self.model_name = config.get("model_name", "Lykon/dreamshaper-8-lcm")
        self.pipeline = None

    async def load(self) -> bool:
        """Dynamically load the Stable Diffusion pipeline."""
        if self.pipeline:
            self._is_loaded = True
            return True

        print(f"Loading Diffusers image generation model '{self.model_name}'...")
        try:
            import torch
            from diffusers import AutoPipelineForText2Image
            
            device = "cuda" if torch.cuda.is_available() else "cpu"
            torch_dtype = torch.float16 if device == "cuda" else torch.float32
            
            self.pipeline = AutoPipelineForText2Image.from_pretrained(
                self.model_name,
                torch_dtype=torch_dtype,
                safety_checker=None,
                requires_safety_checker=False
            )

            self.pipeline.to(device)
            
            # Setup LCM scheduler if using a Latent Consistency Model for fast 4-step generation
            if "lcm" in self.model_name.lower():
                from diffusers import LCMScheduler
                self.pipeline.scheduler = LCMScheduler.from_config(self.pipeline.scheduler.config)

            self._is_loaded = True
            return True
        except Exception as e:
            print(f"Failed to load Diffusers model: {e}")
            return False

    async def unload(self) -> bool:
        """Unload pipeline and release VRAM."""
        if not self.pipeline:
            self._is_loaded = False
            return True
            
        print(f"Unloading Diffusers model '{self.model_name}'...")
        self.pipeline = None
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

    async def handle_image_generation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generate image from text prompt, returning OpenAI-compatible b64_json structure."""
        if not self.pipeline:
            await self.load()
            
        prompt = payload.get("prompt", "")
        if not prompt:
            raise ValueError("Prompt is required for image generation.")

        # Default to 4 steps for LCM, 20 steps otherwise
        is_lcm = "lcm" in self.model_name.lower()
        default_steps = 4 if is_lcm else 20
        steps = payload.get("num_inference_steps", default_steps)
        width = payload.get("width", 512)
        height = payload.get("height", 512)
        
        # Determine guidance scale (Sweet spot for LCM is 1.0 - 2.0. Standard SD uses 7.5)
        default_guidance = 1.5 if is_lcm else 7.5
        guidance = payload.get("guidance_scale", default_guidance)
        
        # Limit steps for local execution safety
        steps = min(steps, 50)
        
        print(f"Generating image prompt: '{prompt}' ({steps} steps, guidance: {guidance})...")
        
        # Run inference in the default executor (blocking call)
        import asyncio
        loop = asyncio.get_running_loop()
        
        def run_inference():
            return self.pipeline(
                prompt=prompt,
                num_inference_steps=steps,
                width=width,
                height=height,
                guidance_scale=guidance
            ).images[0]

            
        image = await loop.run_in_executor(None, run_inference)
        
        # Convert image to Base64 PNG bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_bytes = img_byte_arr.getvalue()
        
        b64_data = base64.b64encode(img_bytes).decode('utf-8')
        
        return {
            "created": int(time.time()),
            "data": [
                {
                    "b64_json": b64_data
                }
            ]
        }

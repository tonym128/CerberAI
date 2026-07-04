import unittest
from unittest.mock import AsyncMock, patch
import asyncio
from PIL import Image

class TestVideoBackend(unittest.TestCase):
    def test_video_backend_serialization(self):
        from cerberai.backends.video import VideoBackend
        
        # Setup backend
        backend = VideoBackend("video-generation", {"model_name": "mock-video"}, 8.0)
        
        # Mock pipeline call
        active_calls = 0
        max_concurrent_calls = 0
        
        def mock_pipeline_call(*args, **kwargs):
            nonlocal active_calls, max_concurrent_calls
            active_calls += 1
            max_concurrent_calls = max(max_concurrent_calls, active_calls)
            import time
            time.sleep(0.05) # Simulate inference time
            active_calls -= 1
            
            # Mock return frame structure
            mock_img = Image.new("RGB", (10, 10))
            class MockResult:
                frames = [[mock_img]] # CogVideoX pipeline frame array
            return MockResult()
            
        backend.pipeline = mock_pipeline_call
        backend.current_model_name = "mock-video"
        backend._is_loaded = True
        
        # Trigger multiple video calls concurrently
        async def run_test():
            # Mock the diffusers video export function
            with patch("diffusers.utils.export_to_video") as mock_export:
                await asyncio.gather(
                    backend.handle_video_generation({"prompt": "p1"}),
                    backend.handle_video_generation({"prompt": "p2"})
                )
                self.assertEqual(mock_export.call_count, 2)
            
        asyncio.run(run_test())
        
        # Since we use self.lock to serialize calls, max_concurrent_calls must be exactly 1
        self.assertEqual(max_concurrent_calls, 1)

    def test_video_backend_image_to_video(self):
        from cerberai.backends.video import VideoBackend
        
        # Setup backend
        backend = VideoBackend("video-generation", {"model_name": "mock-video"}, 8.0)
        
        # Mock pipeline call
        def mock_pipeline_call(*args, **kwargs):
            # SVD returns frames list
            mock_img = Image.new("RGB", (10, 10))
            class MockResult:
                frames = [[mock_img]]
            return MockResult()
            
        backend.pipeline = mock_pipeline_call
        backend.current_model_name = "stabilityai/stable-video-diffusion-img2vid-xt"
        backend._is_loaded = True
        
        # Mock base64 image (small 1x1 transparent png)
        # iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==
        mock_b64_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        
        async def run_test():
            with patch("diffusers.utils.export_to_video") as mock_export:
                res = await backend.handle_video_generation({
                    "image": mock_b64_png,
                    "num_frames": 14,
                    "num_inference_steps": 20
                })
                self.assertEqual(mock_export.call_count, 1)
                self.assertIn("b64_json", res)
            
        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()

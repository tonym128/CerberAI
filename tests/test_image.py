import warnings
warnings.filterwarnings("ignore")
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

# Mock the manager's backend initialization before importing app
with patch("cerberai.manager.DynamicModelManager._create_backend") as mock_init:
    from cerberai.main import app

class TestImageAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("cerberai.main.manager.get_model")
    def test_image_generations_endpoint(self, mock_get_model):
        mock_backend = AsyncMock()
        mock_backend.handle_image_generation.return_value = {
            "created": 1677600000,
            "data": [{"b64_json": "mock-base64-data"}]
        }
        mock_get_model.return_value = mock_backend

        payload = {
            "prompt": "An astronaut riding a horse on mars",
            "num_inference_steps": 4,
            "width": 512,
            "height": 512
        }

        response = self.client.post("/v1/images/generations", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"][0]["b64_json"], "mock-base64-data")
        mock_get_model.assert_called_once_with("image-lcm")

    def test_diffusers_backend_queues_calls(self):
        import asyncio
        from cerberai.backends.diffusers import DiffusersBackend
        
        # Setup backend
        backend = DiffusersBackend("image-lcm", {"model_name": "mock-lcm"}, 4.0)
        
        # Mock pipeline call with a slow function
        active_calls = 0
        max_concurrent_calls = 0
        
        def mock_pipeline_call(*args, **kwargs):
            nonlocal active_calls, max_concurrent_calls
            active_calls += 1
            max_concurrent_calls = max(max_concurrent_calls, active_calls)
            import time
            time.sleep(0.05) # Simulate inference time
            active_calls -= 1
            
            # Mock return image
            from PIL import Image
            mock_img = Image.new("RGB", (10, 10))
            class MockResult:
                images = [mock_img]
            return MockResult()
            
        backend.pipeline = mock_pipeline_call
        backend._is_loaded = True
        
        # Trigger multiple calls concurrently
        async def run_test():
            await asyncio.gather(
                backend.handle_image_generation({"prompt": "p1"}),
                backend.handle_image_generation({"prompt": "p2"}),
                backend.handle_image_generation({"prompt": "p3"})
            )
            
        asyncio.run(run_test())
        
        # Since we use self.lock to serialize calls, max_concurrent_calls must be exactly 1
        self.assertEqual(max_concurrent_calls, 1)

if __name__ == "__main__":
    unittest.main()

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

if __name__ == "__main__":
    unittest.main()

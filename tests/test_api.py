import warnings
warnings.filterwarnings("ignore")
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

# Mock the manager's backend initialization before importing app
with patch("cerberai.manager.DynamicModelManager._create_backend") as mock_init:
    mock_backend = AsyncMock()
    mock_backend.is_loaded = AsyncMock(return_value=False)
    mock_init.return_value = mock_backend
    from cerberai.main import app


class TestAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_status_endpoint(self):
        response = self.client.get("/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        from cerberai.main import config
        self.assertEqual(data["limits"]["max_vram_gb"], config.resource_limits.max_vram_gb)
        self.assertIn("active_models", data)
        self.assertIn("all_configured_models", data)
        self.assertIn("loading_status", data)
        self.assertTrue(all("n_ctx" in m for m in data["all_configured_models"]))

    def test_root_endpoint(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("CerberAI", response.text)



    def test_models_endpoint(self):
        response = self.client.get("/v1/models")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["object"], "list")
        self.assertTrue(any(model["id"] == "auto" for model in data["data"]))
        self.assertTrue(any(model["id"] == "general-llama3" for model in data["data"]))

    @patch("cerberai.main.manager.get_model")
    @patch("cerberai.main.router.route_chat")
    def test_chat_completions_endpoint(self, mock_route_chat, mock_get_model):
        # Mock routing and backend handling
        mock_route_chat.return_value = "general-llama3"
        mock_backend = AsyncMock()
        mock_backend.handle_chat_completion.return_value = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677600000,
            "model": "general-llama3",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! I am your general model."
                },
                "finish_reason": "stop"
            }]
        }
        mock_get_model.return_value = mock_backend

        payload = {
            "model": "auto",
            "messages": [{"role": "user", "content": "Hello!"}],
            "stream": False
        }
        
        response = self.client.post("/v1/chat/completions", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["model"], "general-llama3")
        self.assertEqual(data["choices"][0]["message"]["content"], "Hello! I am your general model.")
        
        # Verify routing and manager were called correctly
        mock_route_chat.assert_called_once_with([{"role": "user", "content": "Hello!"}], "auto", unittest.mock.ANY)
        mock_get_model.assert_called_once_with("general-llama3")

    def test_conversations_flow(self):
        # 1. Create a new conversation
        response = self.client.post("/api/conversations", json={"title": "Test Chat"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        conv_id = data["id"]
        self.assertEqual(data["title"], "Test Chat")
        
        # 2. Get list of conversations
        response = self.client.get("/api/conversations")
        self.assertEqual(response.status_code, 200)
        list_data = response.json()
        self.assertTrue(any(c["id"] == conv_id for c in list_data))
        
        # 3. Retrieve the created conversation
        response = self.client.get(f"/api/conversations/{conv_id}")
        self.assertEqual(response.status_code, 200)
        conv_data = response.json()
        self.assertEqual(conv_data["id"], conv_id)
        self.assertEqual(conv_data["title"], "Test Chat")
        self.assertEqual(conv_data["messages"], [])
        
        # 4. Save/Update conversation messages
        updated_payload = {
            "id": conv_id,
            "title": "Updated Title",
            "messages": [{"role": "user", "content": "Hi!"}, {"role": "assistant", "content": "Hello!"}]
        }
        response = self.client.post(f"/api/conversations/{conv_id}", json=updated_payload)
        self.assertEqual(response.status_code, 200)
        
        # Verify changes saved
        response = self.client.get(f"/api/conversations/{conv_id}")
        self.assertEqual(response.status_code, 200)
        conv_data = response.json()
        self.assertEqual(conv_data["title"], "Updated Title")
        self.assertEqual(len(conv_data["messages"]), 2)
        
        # 5. Delete conversation
        response = self.client.delete(f"/api/conversations/{conv_id}")
        self.assertEqual(response.status_code, 200)
        
        # Verify deleted
        response = self.client.get(f"/api/conversations/{conv_id}")
        self.assertEqual(response.status_code, 404)

if __name__ == "__main__":
    unittest.main()

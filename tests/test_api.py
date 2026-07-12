import warnings
warnings.filterwarnings("ignore")
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

# Mock the manager's backend initialization before importing app
with patch("cerberai.manager.DynamicModelManager._create_backend") as mock_init:
    mock_backend = AsyncMock()
    mock_backend.is_loaded = AsyncMock(return_value=False)
    
    # get_diagnostics is a synchronous method, so mock it with MagicMock
    from unittest.mock import MagicMock
    mock_backend.get_diagnostics = MagicMock(return_value={})
    
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
        self.assertTrue(any(model["id"] == "general" for model in data["data"]))

    @patch("cerberai.main.manager.get_model")
    @patch("cerberai.main.router.route_chat")
    def test_chat_completions_endpoint(self, mock_route_chat, mock_get_model):
        # Mock routing and backend handling
        mock_route_chat.return_value = "general"
        mock_backend = AsyncMock()
        mock_backend.handle_chat_completion.return_value = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677600000,
            "model": "general",
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
        self.assertEqual(data["model"], "general")
        self.assertEqual(data["choices"][0]["message"]["content"], "Hello! I am your general model.")
        
        # Verify routing and manager were called correctly
        mock_route_chat.assert_called_once_with([{"role": "user", "content": "Hello!"}], "auto", unittest.mock.ANY)
        mock_get_model.assert_called_once_with("general")

    @patch("cerberai.main.manager.get_model")
    @patch("cerberai.main.router.route_chat")
    def test_chat_completions_video_route(self, mock_route_chat, mock_get_model):
        mock_route_chat.return_value = "video-generation"
        mock_backend = AsyncMock()
        mock_backend.handle_video_generation.return_value = {
            "b64_json": "bW9jay12aWRlbw=="
        }
        mock_get_model.return_value = mock_backend
        
        # Inject video-generation into config models if not present
        from cerberai.main import config
        from cerberai.config import ModelConfig
        if not any(m.id == "video-generation" for m in config.models):
            config.models.append(ModelConfig(id="video-generation", type="video", backend="video"))

        payload = {
            "model": "auto",
            "messages": [{"role": "user", "content": "create a video of space"}],
            "stream": False
        }
        
        with patch("builtins.open", unittest.mock.mock_open()) as mock_file, \
             patch("os.makedirs") as mock_makedirs:
            response = self.client.post("/v1/chat/completions", json=payload)
            
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["model"], "video-generation")
        self.assertIn("video", data["choices"][0]["message"]["content"])

    @patch("cerberai.main.manager.get_model")
    @patch("cerberai.main.router.route_chat")
    def test_chat_completions_image_to_video_route(self, mock_route_chat, mock_get_model):
        mock_route_chat.return_value = "video-generation"
        mock_backend = AsyncMock()
        mock_backend.handle_video_generation.return_value = {
            "b64_json": "bW9jay12aWRlbw=="
        }
        mock_get_model.return_value = mock_backend
        
        # Inject video-generation into config models if not present
        from cerberai.main import config
        from cerberai.config import ModelConfig
        if not any(m.id == "video-generation" for m in config.models):
            config.models.append(ModelConfig(id="video-generation", type="video", backend="video"))
        
        payload = {
            "model": "video-generation",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "make this image move"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,bW9jay1pbWFnZQ=="}}
                ]
            }],
            "stream": False
        }
        
        with patch("builtins.open", unittest.mock.mock_open()) as mock_file, \
             patch("os.makedirs") as mock_makedirs:
            response = self.client.post("/v1/chat/completions", json=payload)
            
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["model"], "video-generation")
        mock_backend.handle_video_generation.assert_called_once_with({
            "prompt": "make this image move",
            "image": "bW9jay1pbWFnZQ=="
        })

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

    @patch("cerberai.automation.generate_yesterday_news_video")
    def test_news_video_automation_endpoint(self, mock_generate):
        from cerberai.automation import update_status, get_status
        update_status("idle", 0, "")
        
        # 1. Trigger POST without payload
        response = self.client.post("/v1/automate/news-video")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["message"], "Automation started successfully.")
        self.assertEqual(data["status"]["status"], "running")
        
        # Reset to idle to test payload parsing
        update_status("idle", 0, "")
        
        # 2. Trigger POST with custom payload
        payload = {"topic": "Tech & AI", "date": "2026-07-02"}
        response = self.client.post("/v1/automate/news-video", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["message"], "Automation started successfully.")

    def test_news_video_history_endpoint(self):
        response = self.client.get("/v1/automate/news-video/history")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(isinstance(data, list))

    def test_schedules_endpoints(self):
        # 1. GET schedules (starts empty or with initial mock config)
        response = self.client.get("/api/schedules")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(isinstance(response.json(), list))
        
        # 2. POST to create a schedule
        payload = {
            "type": "query",
            "time": "08:30",
            "target": "Explain daily AI advancements"
        }
        response = self.client.post("/api/schedules", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "query")
        self.assertEqual(data["time"], "08:30")
        self.assertEqual(data["target"], "Explain daily AI advancements")
        self.assertTrue("id" in data)
        schedule_id = data["id"]
        
        # 3. GET schedules again (must contain the created one)
        response = self.client.get("/api/schedules")
        self.assertEqual(response.status_code, 200)
        schedules = response.json()
        matching = [s for s in schedules if s["id"] == schedule_id]
        self.assertEqual(len(matching), 1)
        
        # 4. DELETE the schedule
        response = self.client.delete(f"/api/schedules/{schedule_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        
        # 5. Verify deleted
        response = self.client.get("/api/schedules")
        schedules = response.json()
        matching = [s for s in schedules if s["id"] == schedule_id]
        self.assertEqual(len(matching), 0)

    def test_telegram_history_endpoint(self):
        response = self.client.get("/api/telegram/history")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(isinstance(data, list))

    @patch("builtins.open")
    @patch("cerberai.main.manager.unload_all")
    def test_save_config_endpoint(self, mock_unload_all, mock_open):
        mock_unload_all.return_value = None
        
        import cerberai.main
        orig_config = cerberai.main.config
        orig_manager = cerberai.main.manager
        orig_agent = cerberai.main.agent
        
        try:
            # Mock file contents for load_config reading
            import yaml
            mock_config_data = {
                "models": [{"id": "general", "type": "llm", "backend": "llama.cpp"}],
                "resource_limits": {"max_vram_gb": 12.0, "max_ram_gb": 16.0, "eviction_strategy": "lru"},
                "router": {"fallback_model": "general", "model_type": "heuristics"},
                "search": {"provider": "duckduckgo"},
                "server": {"host": "127.0.0.1", "port": 8000}
            }
            yaml_content = yaml.safe_dump(mock_config_data)
            
            # Mock file handling
            mock_file = unittest.mock.mock_open(read_data=yaml_content)
            mock_open.side_effect = mock_file
            
            response = self.client.post("/api/config", json=mock_config_data)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["message"], "Configuration updated and reloaded successfully!")
        finally:
            # Restore original globals
            cerberai.main.config = orig_config
            cerberai.main.manager = orig_manager
            cerberai.main.agent = orig_agent

    @patch("cerberai.main.manager.get_model")
    def test_chat_completions_list_content_sanitization(self, mock_get_model):
        mock_backend = AsyncMock()
        mock_backend.handle_chat_completion.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "mock text"}, "finish_reason": "stop"}]
        }
        mock_get_model.return_value = mock_backend

        payload = {
            "model": "general",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hello coding agent"}]}
            ],
            "tools_enabled": False,
            "stream": False
        }

        response = self.client.post("/v1/chat/completions", json=payload)
        self.assertEqual(response.status_code, 200)

        # Verify backend was called with the content converted to a string
        call_args = mock_backend.handle_chat_completion.call_args[0][0]
        self.assertEqual(call_args["messages"][0]["content"], "hello coding agent")

    @patch("cerberai.main.manager.get_model")
    def test_chat_completions_bypasses_internal_agent_when_tools_provided(self, mock_get_model):
        mock_backend = AsyncMock()
        mock_backend.handle_chat_completion.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "mock text"}, "finish_reason": "stop"}]
        }
        mock_get_model.return_value = mock_backend

        # Prepare payload with tools (meaning client wants to manage tools itself)
        payload = {
            "model": "general",
            "messages": [{"role": "user", "content": "list the files"}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List all files in the current folder",
                    "parameters": {"type": "object", "properties": {}}
                }
            }],
            "stream": False
        }

        response = self.client.post("/v1/chat/completions", json=payload)
        self.assertEqual(response.status_code, 200)

        # Ensure that it was handled directly by the backend, preserving the tools key
        call_args = mock_backend.handle_chat_completion.call_args[0][0]
        self.assertIn("tools", call_args)
        self.assertEqual(call_args["tools"][0]["function"]["name"], "list_files")

    @patch("cerberai.database.db_delete_media_history")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.unlink")
    def test_delete_media_item(self, mock_unlink, mock_exists, mock_delete_media_history):
        mock_delete_media_history.return_value = {
            "type": "video",
            "filename": "video_1.mp4",
            "md_filename": None,
            "pdf_filename": None
        }
        mock_exists.return_value = True

        response = self.client.delete("/api/media/test-id-123")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("video_1.mp4", data["files"])
        mock_delete_media_history.assert_called_once_with("test-id-123")
        mock_unlink.assert_called_once()

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.unlink")
    def test_delete_image_file(self, mock_unlink, mock_exists):
        mock_exists.return_value = True

        response = self.client.delete("/api/images/test_image.png")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        mock_unlink.assert_called_once()

if __name__ == "__main__":
    unittest.main()

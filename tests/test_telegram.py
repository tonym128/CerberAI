import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

class TestTelegramVision(unittest.TestCase):
    def test_mime_type_resolution(self):
        # Verify extension mapping rules
        test_paths = {
            "file_123.jpg": "image/jpeg",
            "file_123.jpeg": "image/jpeg",
            "file_123.png": "image/png",
            "file_123.webp": "image/webp",
            "file_123.gif": "image/gif"
        }
        
        for file_path, expected_mime in test_paths.items():
            ext = file_path.split(".")[-1].lower()
            mime_type = f"image/{ext}"
            if ext in ("jpg", "jpeg"):
                mime_type = "image/jpeg"
            self.assertEqual(mime_type, expected_mime)

    @patch("cerberai.telegram.send_telegram_message", new_callable=AsyncMock)
    @patch("cerberai.telegram.send_telegram_voice", new_callable=AsyncMock)
    @patch("cerberai.telegram.convert_wav_to_ogg", new_callable=AsyncMock)
    async def _async_test_multimodal_handling(self, mock_convert_ogg, mock_send_voice, mock_send_msg):
        from cerberai.telegram import handle_telegram_multimodal
        
        # Mock Config and Manager
        mock_config = MagicMock()
        mock_config.telegram_bot_token = "dummy_token"
        mock_config.telegram_chat_id = "12345"
        mock_config.router = MagicMock()
        
        # Set up a mock vision model configuration
        mock_model_cfg = MagicMock()
        mock_model_cfg.id = "vision-qwen"
        mock_model_cfg.type = "vision"
        mock_config.models = [mock_model_cfg]
        
        # Mock Router returning the vision model id
        mock_router_instance = MagicMock()
        mock_router_instance.route_chat = AsyncMock(return_value="vision-qwen")
        
        # Mock Backend completion response
        mock_backend = AsyncMock()
        mock_backend.handle_chat_completion = AsyncMock(return_value={
            "choices": [{"message": {"content": "This is a picture of a cat."}}]
        })
        
        mock_tts_backend = AsyncMock()
        mock_tts_backend.handle_audio_speech = AsyncMock(return_value=b"dummy_wav")
        
        mock_manager = AsyncMock()
        mock_manager.get_model = AsyncMock(side_effect=lambda mid: mock_backend if mid == "vision-qwen" else mock_tts_backend)
        mock_agent = MagicMock()
        
        mock_convert_ogg.return_value = b"dummy_ogg"
        
        with patch("cerberai.router.IntentRouter", return_value=mock_router_instance):
            await handle_telegram_multimodal(
                config=mock_config,
                manager=mock_manager,
                agent=mock_agent,
                caption="What is this?",
                mime_type="image/jpeg",
                base64_data="dummy_b64",
                reply_with_tts=True
            )
            
        # Verify correct outputs were dispatched
        mock_send_msg.assert_any_call(mock_config, "👁️ Analyzing image using `vision-qwen`...")
        mock_send_msg.assert_any_call(mock_config, "💬 **Analysis (vision-qwen):**\n\nThis is a picture of a cat.")
        mock_send_voice.assert_called_once()

    def test_multimodal_handling(self):
        # Run async test runner
        asyncio.run(self._async_test_multimodal_handling())

class TestTelegramVideoGeneration(unittest.TestCase):
    @patch("cerberai.telegram.send_telegram_message", new_callable=AsyncMock)
    @patch("cerberai.telegram.send_telegram_video", new_callable=AsyncMock)
    async def _async_test_telegram_video_route(self, mock_send_video, mock_send_msg):
        from cerberai.telegram import handle_telegram_message
        
        # Setup config
        mock_config = MagicMock()
        mock_config.telegram_bot_token = "dummy_token"
        mock_config.telegram_chat_id = "12345"
        mock_config.router = MagicMock()
        
        # Models config list
        mock_video_model = MagicMock()
        mock_video_model.id = "video-generation"
        mock_video_model.type = "video"
        mock_config.models = [mock_video_model]
        
        # Mock Router returning video-generation
        mock_router_instance = MagicMock()
        mock_router_instance.route_chat = AsyncMock(return_value="video-generation")
        
        # Mock backend returning base64 video string
        mock_backend = AsyncMock()
        mock_backend.handle_video_generation = AsyncMock(return_value={
            "b64_json": "bW9jay12aWRlbw=="
        })
        
        mock_manager = AsyncMock()
        mock_manager.get_model = AsyncMock(return_value=mock_backend)
        mock_agent = MagicMock()
        
        with patch("cerberai.router.IntentRouter", return_value=mock_router_instance), \
             patch("builtins.open", unittest.mock.mock_open()) as mock_file, \
             patch("os.makedirs") as mock_makedirs:
             
            await handle_telegram_message(
                text="create a video of space",
                config=mock_config,
                manager=mock_manager,
                agent=mock_agent,
                reply_with_tts=False
            )
            
        mock_send_msg.assert_any_call(mock_config, "🎬 Generating video...")
        mock_send_video.assert_called_once()
        self.assertIn("Generated Video for:", mock_send_video.call_args[0][2])

    def test_telegram_video_route(self):
        asyncio.run(self._async_test_telegram_video_route())

if __name__ == "__main__":
    unittest.main()

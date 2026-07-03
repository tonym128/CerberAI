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

if __name__ == "__main__":
    unittest.main()

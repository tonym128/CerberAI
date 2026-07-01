import warnings
warnings.filterwarnings("ignore")
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

# Mock the manager's backend initialization before importing app
with patch("cerberai.manager.DynamicModelManager._create_backend") as mock_init:
    from cerberai.main import app

class TestAudioAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("cerberai.main.manager.get_model")
    def test_audio_speech_endpoint(self, mock_get_model):
        mock_backend = AsyncMock()
        mock_backend.handle_audio_speech.return_value = b"mock-audio-bytes"
        mock_get_model.return_value = mock_backend

        payload = {
            "model": "tts-1",
            "input": "Hello from CerberAI!",
            "voice": "alloy",
            "response_format": "mp3"
        }

        response = self.client.post("/v1/audio/speech", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"mock-audio-bytes")
        self.assertEqual(response.headers["content-type"], "audio/mpeg")
        mock_get_model.assert_called_once_with("tts-offline")

    @patch("cerberai.main.manager.get_model")
    def test_audio_transcriptions_endpoint(self, mock_get_model):
        mock_backend = AsyncMock()
        mock_backend.handle_audio_transcription.return_value = {"text": "Transcribed hello."}
        mock_get_model.return_value = mock_backend

        # Construct dummy file
        files = {
            "file": ("test.wav", b"fake-audio-payload", "audio/wav")
        }
        data = {
            "model": "whisper-1",
            "language": "en"
        }

        response = self.client.post("/v1/audio/transcriptions", files=files, data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"text": "Transcribed hello."})
        mock_get_model.assert_called_once_with("stt-whisper")

if __name__ == "__main__":
    unittest.main()

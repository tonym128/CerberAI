import unittest
import os
import shutil
import asyncio
import io
import tarfile
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

from cerberai.downloader import ensure_gguf_model, ensure_llama_server

class TestDownloader(unittest.TestCase):
    def setUp(self):
        # Create a temp cache dir for test isolation
        self.test_cache = Path("./test_model_cache")
        self.test_bin = Path("./test_bin_cache")
        self.test_cache.mkdir(exist_ok=True)
        self.test_bin.mkdir(exist_ok=True)
        
        self.patcher_cache = patch("cerberai.downloader.CACHE_DIR", self.test_cache)
        self.patcher_bin = patch("cerberai.downloader.BIN_DIR", self.test_bin)
        self.patcher_cache.start()
        self.patcher_bin.start()

    def tearDown(self):
        self.patcher_cache.stop()
        self.patcher_bin.stop()
        if self.test_cache.exists():
            shutil.rmtree(self.test_cache)
        if self.test_bin.exists():
            shutil.rmtree(self.test_bin)

    @patch("httpx.AsyncClient.stream")
    def test_ensure_gguf_model_downloads_successfully(self, mock_stream):
        # Set up mock response stream
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-length": "24"}
        
        async def aiter_bytes(*args, **kwargs):
            yield b"some binary gguf content"
            
        mock_response.aiter_bytes = aiter_bytes
        
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__.return_value = mock_response
        mock_stream.return_value = mock_stream_ctx

        repo_id = "test-repo/test-model"
        filename = "test-model.gguf"
        
        expected_path = self.test_cache / filename
        self.assertFalse(expected_path.exists())
        
        res_path = asyncio.run(ensure_gguf_model(repo_id, filename))
        
        self.assertEqual(res_path, str(expected_path.resolve()))
        self.assertTrue(expected_path.exists())
        with open(expected_path, "rb") as f:
            self.assertEqual(f.read(), b"some binary gguf content")

    @patch("httpx.AsyncClient.stream")
    def test_ensure_gguf_model_handles_failure(self, mock_stream):
        mock_response = MagicMock()
        mock_response.status_code = 404
        
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__.return_value = mock_response
        mock_stream.return_value = mock_stream_ctx

        repo_id = "test-repo/missing"
        filename = "missing.gguf"

        with self.assertRaises(RuntimeError):
            asyncio.run(ensure_gguf_model(repo_id, filename))
            
        temp_path = self.test_cache / f"{filename}.tmp"
        self.assertFalse(temp_path.exists())

    @patch("shutil.which")
    @patch("httpx.AsyncClient.stream")
    @patch("cerberai.downloader.get_latest_llama_tag")
    def test_ensure_llama_server_downloads_and_extracts(self, mock_get_tag, mock_stream, mock_which):
        # 1. Mock tag endpoint response
        mock_get_tag.return_value = "b3500"
        
        # 2. Force shutil.which to return None so it triggers download
        mock_which.return_value = None
        
        # 3. Build a valid in-memory tarball containing 'llama-server'
        tar_bytes_io = io.BytesIO()
        with tarfile.open(fileobj=tar_bytes_io, mode="w:gz") as tar:
            content = b"dummy-llama-server-binary"
            tarinfo = tarfile.TarInfo(name="llama-server")
            tarinfo.size = len(content)
            tar.addfile(tarinfo, io.BytesIO(content))
        tar_data = tar_bytes_io.getvalue()

        # 4. Setup HTTP mock responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-length": str(len(tar_data))}
        
        async def aiter_bytes(*args, **kwargs):
            yield tar_data
            
        mock_response.aiter_bytes = aiter_bytes
        
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__.return_value = mock_response
        mock_stream.return_value = mock_stream_ctx

        expected_bin = self.test_bin / "llama-server"
        self.assertFalse(expected_bin.exists())

        # Execute
        res_path = asyncio.run(ensure_llama_server())

        self.assertEqual(res_path, str(expected_bin.resolve()))
        self.assertTrue(expected_bin.exists())
        
        # Check content and execution permissions
        with open(expected_bin, "rb") as f:
            self.assertEqual(f.read(), b"dummy-llama-server-binary")
        self.assertTrue(os.access(expected_bin, os.X_OK))


if __name__ == "__main__":
    unittest.main()

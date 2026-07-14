import unittest
import os
import json
import base64
import time
import asyncio
import threading
from urllib.parse import urlparse
from unittest.mock import AsyncMock, patch, MagicMock
from http.server import HTTPServer, BaseHTTPRequestHandler
from cerberai.backends.comfyui import ComfyUIBackend

# Global state to control mock server behavior
SERVER_SHOULD_FAIL = False

class MockComfyUIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global SERVER_SHOULD_FAIL
        if SERVER_SHOULD_FAIL:
            self.send_response(503)
            self.end_headers()
            return
            
        if self.path == "/system_stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"devices": [{"type": "cuda"}]}).encode())
        elif "/history/" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            prompt_id = self.path.split("/")[-1]
            self.wfile.write(json.dumps({
                prompt_id: {
                    "outputs": {
                        "9": {
                            "images": [{"filename": "mock_output.png", "subfolder": "", "type": "output"}]
                        },
                        "7": {
                            "gifs": [{"filename": "mock_output.mp4", "subfolder": "", "type": "output"}]
                        }
                    }
                }
            }).encode())
        elif self.path.startswith("/view"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(b"mock_file_bytes")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global SERVER_SHOULD_FAIL
        if SERVER_SHOULD_FAIL:
            self.send_response(503)
            self.end_headers()
            return
            
        # Read the request body to prevent TCP resets
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            self.rfile.read(content_length)
            
        if self.path == "/prompt":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"prompt_id": "test_prompt_123"}).encode())
        elif self.path == "/upload/image":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"name": "uploaded_image.png"}).encode())
        else:
            self.send_response(404)
            self.end_headers()
            
    def log_message(self, format, *args):
        pass # Suppress logging to keep output clean

class TestComfyUIBackend(unittest.TestCase):
    mock_server = None
    server_thread = None

    @classmethod
    def setUpClass(cls):
        # We start the mock server on port 8199 to ensure we NEVER touch any live ComfyUI instance on port 8188
        cls.mock_server = HTTPServer(("127.0.0.1", 8199), MockComfyUIHandler)
        cls.server_thread = threading.Thread(target=cls.mock_server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        if cls.mock_server:
            cls.mock_server.shutdown()
            cls.mock_server.server_close()
            cls.server_thread.join()

    def setUp(self):
        global SERVER_SHOULD_FAIL
        SERVER_SHOULD_FAIL = False
        
        self.config = {
            "server_url": "http://127.0.0.1:8199",
            "workflow_path": "tests/mock_workflow.json"
        }
        self.backend = ComfyUIBackend("video-generation", self.config, 0.0)
        
        # Mock installer to avoid downloading things in tests
        self.backend._ensure_installed = AsyncMock(return_value=True)
        
        # Mock psutil to avoid real process table lookups
        self.psutil_patcher = patch("psutil.process_iter", return_value=[])
        self.psutil_patcher.start()
        
        # Mock Popen inside comfyui backend
        self.popen_patcher = patch("cerberai.backends.comfyui.Popen")
        self.mock_popen = self.popen_patcher.start()
        
        # Set up mock process behavior
        self.mock_process = MagicMock()
        self.mock_process.poll.return_value = None
        self.mock_process.communicate.return_value = ("stdout", "stderr")
        self.mock_popen.return_value = self.mock_process

        # Create a mock workflow file for testing
        self.mock_workflow = {
            "3": {
                "inputs": {
                    "seed": "__SEED__",
                    "positive": ["6", 0],
                    "negative": ["7", 0]
                },
                "class_type": "KSampler"
            },
            "6": {
                "inputs": {
                    "text": "__PROMPT__"
                },
                "class_type": "CLIPTextEncode"
            },
            "7": {
                "inputs": {
                    "text": "__NEGATIVE_PROMPT__"
                },
                "class_type": "CLIPTextEncode"
            },
            "10": {
                "inputs": {
                    "image": "__IMAGE__"
                },
                "class_type": "LoadImage"
            }
        }
        os.makedirs("tests", exist_ok=True)
        with open("tests/mock_workflow.json", "w") as f:
            json.dump(self.mock_workflow, f)

    def tearDown(self):
        self.psutil_patcher.stop()
        self.popen_patcher.stop()
        if os.path.exists("tests/mock_workflow.json"):
            os.unlink("tests/mock_workflow.json")

    @patch("httpx.AsyncClient.get")
    def test_load_comfyui_remote_already_running(self, mock_get):
        # Configure as a remote URL to test remote already running routing
        self.backend.server_url = "http://192.168.1.100:8199"
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "devices": [{"type": "cuda"}]
        }
        mock_get.return_value = mock_response

        async def run_test():
            success = await self.backend.load()
            self.assertTrue(success)
            self.assertTrue(await self.backend.is_loaded())
            self.assertFalse(self.backend.started_by_us)
            self.mock_popen.assert_not_called()
            
        asyncio.run(run_test())

    def test_load_comfyui_local_kills_rogue(self):
        # Configure as a local URL
        self.backend.server_url = "http://127.0.0.1:8199"
        
        # Set up a mock process occupying the port 8199
        mock_proc = MagicMock()
        mock_conn = MagicMock()
        mock_conn.laddr.port = 8199
        mock_proc.connections.return_value = [mock_conn]
        mock_proc.info = {"pid": 9999, "name": "comfy_rogue"}
        
        # Re-patch psutil.process_iter for this test to return the rogue process
        self.psutil_patcher.stop()
        self.psutil_patcher = patch("psutil.process_iter", return_value=[mock_proc])
        self.psutil_patcher.start()

        async def run_test():
            success = await self.backend.load()
            self.assertTrue(success)
            self.assertTrue(await self.backend.is_loaded())
            self.assertTrue(self.backend.started_by_us)
            
            # Verify the rogue process was terminated and Popen was called
            mock_proc.terminate.assert_called_once()
            mock_proc.wait.assert_called_once()
            self.mock_popen.assert_called_once()
            
        asyncio.run(run_test())

    def test_load_comfyui_failed_then_starts(self):
        global SERVER_SHOULD_FAIL
        SERVER_SHOULD_FAIL = True # Simulate not running initially

        # Start a thread to set SERVER_SHOULD_FAIL = False after 0.5s to simulate boot-up success
        def delayed_boot():
            time.sleep(0.5)
            global SERVER_SHOULD_FAIL
            SERVER_SHOULD_FAIL = False

        threading.Thread(target=delayed_boot, daemon=True).start()

        async def run_test():
            success = await self.backend.load()
            self.assertTrue(success)
            self.assertTrue(await self.backend.is_loaded())
            self.assertTrue(self.backend.started_by_us)
            self.mock_popen.assert_called_once()
            
            # Test unload/shutdown
            unloaded = await self.backend.unload()
            self.assertTrue(unloaded)
            self.assertFalse(await self.backend.is_loaded())
            self.mock_process.terminate.assert_called_once()

        asyncio.run(run_test())

    def test_image_generation_flow(self):
        self.backend._is_loaded = True

        async def run_test():
            payload = {
                "prompt": "a futuristic city",
                "negative_prompt": "blurry",
                "seed": 42
            }
            res = await self.backend.handle_image_generation(payload)
            self.assertIn("data", res)
            self.assertEqual(len(res["data"]), 1)
            b64_out = res["data"][0]["b64_json"]
            self.assertEqual(base64.b64decode(b64_out), b"mock_file_bytes")
            
        asyncio.run(run_test())

    def test_video_generation_flow(self):
        self.backend._is_loaded = True

        async def run_test():
            payload = {
                "prompt": "animate this car",
                "image": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "seed": 12345
            }
            
            progress_calls = []
            def progress_cb(msg):
                progress_calls.append(msg)
                
            res = await self.backend.handle_video_generation(payload, progress_callback=progress_cb)
            self.assertIn("b64_json", res)
            self.assertEqual(base64.b64decode(res["b64_json"]), b"mock_file_bytes")
            self.assertTrue(len(progress_calls) >= 1)
            
        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()

import unittest
import os
import shutil
import tempfile
import asyncio
from unittest.mock import MagicMock
from cerberai.agent import AgentExecutor
from cerberai.config import AppConfig

class TestAgentFilesystemTools(unittest.TestCase):
    def setUp(self):
        # Create a temp directory for sandbox filesystem testing
        self.temp_dir = tempfile.mkdtemp()
        
        # Safe dummy config
        self.config = MagicMock(spec=AppConfig)
        self.config.search = MagicMock()
        self.config.search.provider = "duckduckgo"
        self.executor = AgentExecutor(self.config)

    def tearDown(self):
        # Clean up temp directory
        shutil.rmtree(self.temp_dir)

    def test_list_directory_and_write_read_file(self):
        async def run_async_tests():
            # 1. Write file
            file_path = os.path.join(self.temp_dir, "test.txt")
            write_res = await self.executor.write_file_tool(file_path, "Hello, CerberAI Tools!")
            self.assertIn("Successfully wrote", write_res)
            self.assertTrue(os.path.exists(file_path))
            
            # 2. Read file
            read_res = await self.executor.read_file_tool(file_path)
            self.assertEqual(read_res, "Hello, CerberAI Tools!")
            
            # 3. List directory
            list_res = await self.executor.list_directory_tool(self.temp_dir)
            self.assertIn("test.txt", list_res)
            self.assertIn("[FILE]", list_res)
            
        asyncio.run(run_async_tests())

    def test_read_missing_file(self):
        async def run_async_tests():
            missing_path = os.path.join(self.temp_dir, "nonexistent.txt")
            read_res = await self.executor.read_file_tool(missing_path)
            self.assertIn("Error: File", read_res)
            self.assertIn("does not exist", read_res)
            
        asyncio.run(run_async_tests())

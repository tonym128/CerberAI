import unittest
import json
import sqlite3
import numpy as np
from unittest.mock import patch, MagicMock
from cerberai.memory import init_memory_db, save_memory, search_memories, get_embedding, extract_and_save_memories
from cerberai.database import DB_PATH

class TestSemanticMemory(unittest.TestCase):
    def setUp(self):
        # Initialize memory db table
        init_memory_db()
        
    def tearDown(self):
        # Clean up database records
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM semantic_memories")
        conn.commit()
        conn.close()

    def test_save_and_search_memories(self):
        # Create two sample vectors
        vec_cats = [1.0, 0.0, 0.0]
        vec_dogs = [0.0, 1.0, 0.0]
        
        save_memory("Cats are warm-blooded feline animals.", vec_cats, {"tag": "animals"})
        save_memory("Dogs are loyal canine pets.", vec_dogs, {"tag": "animals"})
        
        # Searching with a vector close to cats
        query_vec = [0.9, 0.1, 0.0]
        results = search_memories(query_vec, threshold=0.5, limit=5)
        
        self.assertTrue(len(results) >= 1)
        # The top result should be cats
        self.assertEqual(results[0]["content"], "Cats are warm-blooded feline animals.")
        self.assertEqual(results[0]["meta_data"]["tag"], "animals")
        
        # Verify the similarity is high
        self.assertTrue(results[0]["similarity"] > 0.8)

    @patch("httpx.AsyncClient.post")
    def test_get_embedding(self, mock_post):
        # Mock the manager and backend
        mock_backend = MagicMock()
        mock_backend.backend = "llamacpp"
        async def mock_is_loaded():
            return True
        mock_backend.is_loaded = mock_is_loaded
        mock_backend.server_url = "http://127.0.0.1:8181"
        
        mock_manager = MagicMock()
        mock_manager.backends = {"general": mock_backend}
        
        # Mock HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        mock_post.return_value = mock_response
        
        import asyncio
        async def run_test():
            emb = await get_embedding("Hello test", mock_manager)
            self.assertEqual(emb, [0.1, 0.2, 0.3])
            mock_post.assert_called_once_with(
                "http://127.0.0.1:8181/embedding",
                json={"content": "Hello test"}
            )
            
        asyncio.run(run_test())

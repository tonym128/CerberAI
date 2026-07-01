import unittest
import asyncio
from unittest.mock import patch
from typing import Dict, Any

from cerberai.config import load_config, AppConfig, RouterConfig, ModelConfig
from cerberai.router import IntentRouter
from cerberai.manager import DynamicModelManager
from cerberai.backends.base import BaseBackend

class TestConfig(unittest.TestCase):
    def test_default_config_fallback(self):
        # When config file doesn't exist, it should fallback gracefully
        cfg = load_config("nonexistent_config.yaml")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.router.fallback_model, "general-llama3")
        self.assertEqual(len(cfg.models), 1)

class TestRouter(unittest.TestCase):
    def setUp(self):
        self.router_cfg = RouterConfig(model_type="heuristics", fallback_model="general-model")
        self.models = [
            ModelConfig(id="general-model", type="llm", backend="ollama", vram_estimate_gb=4.0),
            ModelConfig(id="coding-model", type="llm", backend="ollama", vram_estimate_gb=4.0)
        ]
        self.router = IntentRouter(self.router_cfg, self.models)

    def test_routing_by_request(self):
        # Direct requested model
        res = asyncio.run(self.router.route_chat([], "coding-model"))
        self.assertEqual(res, "coding-model")

    def test_heuristics_coding_route(self):
        # Message prompting coding
        messages = [{"role": "user", "content": "Write a python script to sort a list."}]
        res = asyncio.run(self.router.route_chat(messages, "auto"))
        self.assertEqual(res, "coding-model")

    def test_heuristics_general_route(self):
        # General chat message
        messages = [{"role": "user", "content": "Hello, how is the weather?"}]
        res = asyncio.run(self.router.route_chat(messages, "auto"))
        self.assertEqual(res, "general-model")

class MockBackend(BaseBackend):
    def __init__(self, model_id: str, config: Dict[str, Any], vram_estimate_gb: float):
        super().__init__(model_id, config, vram_estimate_gb)
        self.unload_called_count = 0
        self.load_called_count = 0

    async def load(self) -> bool:
        self._is_loaded = True
        self.load_called_count += 1
        return True

    async def unload(self) -> bool:
        self._is_loaded = False
        self.unload_called_count += 1
        return True

class TestManager(unittest.TestCase):
    @patch("cerberai.manager.DynamicModelManager._create_backend")
    def test_lru_eviction(self, mock_create_backend):
        # Configure manager with 10GB limit
        # Add 3 models of 4GB each. Loading the third should evict the first.
        cfg = AppConfig(
            server={"host": "127.0.0.1", "port": 8000, "timeout_keep_alive": 300},
            resource_limits={"max_vram_gb": 10.0, "max_ram_gb": 16.0, "eviction_strategy": "lru"},
            router={"model_type": "heuristics", "fallback_model": "m1"},
            models=[
                ModelConfig(id="m1", type="llm", backend="ollama", vram_estimate_gb=4.0),
                ModelConfig(id="m2", type="llm", backend="ollama", vram_estimate_gb=4.0),
                ModelConfig(id="m3", type="llm", backend="ollama", vram_estimate_gb=4.0)
            ]
        )
        
        # Setup mocks using our MockBackend class
        backends = {}
        for m_cfg in cfg.models:
            backends[m_cfg.id] = MockBackend(m_cfg.id, m_cfg.backend_config, m_cfg.vram_estimate_gb)
            
        mock_create_backend.side_effect = lambda m_cfg: backends[m_cfg.id]
        
        manager = DynamicModelManager(cfg)
        
        async def run_scenario():
            # Load m1
            await manager.get_model("m1")
            self.assertTrue(await backends["m1"].is_loaded())
            
            # Load m2
            await manager.get_model("m2")
            self.assertTrue(await backends["m2"].is_loaded())
            
            # Both loaded, VRAM = 8GB / 10GB
            self.assertEqual(backends["m1"].unload_called_count, 0)
            self.assertEqual(backends["m2"].unload_called_count, 0)
            
            # Load m3, VRAM will exceed 10GB (needs 12GB total if all loaded).
            # Should evict m1 since m1 was loaded before m2.
            await manager.get_model("m3")
            
            self.assertEqual(backends["m1"].unload_called_count, 1)
            self.assertFalse(await backends["m1"].is_loaded())
            self.assertEqual(backends["m2"].unload_called_count, 0)
            self.assertTrue(await backends["m2"].is_loaded())
            self.assertTrue(await backends["m3"].is_loaded())

        asyncio.run(run_scenario())

if __name__ == "__main__":
    unittest.main()

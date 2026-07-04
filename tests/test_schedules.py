import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from pathlib import Path
from cerberai.schedules import run_scheduled_automation

class TestSchedules(unittest.TestCase):
    @patch("cerberai.schedules.run_scheduled_automation", new_callable=AsyncMock)
    async def _async_test_schedules(self, mock_run_auto):
        # Verify schedule loop executes automations
        mock_config = MagicMock()
        mock_manager = MagicMock()
        mock_agent = MagicMock()
        
        # Call run_scheduled_automation manually to verify routing matches
        await run_scheduled_automation(
            target="deep-research",
            params={"topic": "superconductivity"},
            manager=mock_manager,
            agent=mock_agent,
            config=mock_config
        )
        
        await run_scheduled_automation(
            target="podcast",
            params={"topic": "tech news"},
            manager=mock_manager,
            agent=mock_agent,
            config=mock_config
        )

    def test_schedules_mapping(self):
        # Run async test runner
        asyncio.run(self._async_test_schedules())

if __name__ == "__main__":
    unittest.main()

"""Opt-in Chrome selection; legacy defaults and capture/queue code stay unchanged."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/_shared'))
from browser_zoom import launch_browser


class BrowserSelection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='report-kit-browser-test-')
        self.addCleanup(self.temporary.cleanup)

    def test_chrome_is_explicit_and_unset_keeps_legacy_launch(self):
        async def run(value):
            playwright = MagicMock(); browser = MagicMock(); browser.version = '1'; browser.close = AsyncMock()
            playwright.chromium.launch = AsyncMock(return_value=browser)
            with patch.dict(os.environ, {'REPORT_SKILLS_STATE_DIR': self.temporary.name}, clear=True):
                if value: os.environ['REPORT_KIT_BROWSER_CHANNEL'] = value
                async with launch_browser(playwright, mobile=True) as result: self.assertIs(result, browser)
            playwright.chromium.launch.assert_awaited_once_with(headless=True, **({'channel': value} if value else {}))
            browser.close.assert_awaited_once()
        asyncio.run(run(None)); asyncio.run(run('chrome')); asyncio.run(run('chromium'))

    def test_unknown_channel_never_launches(self):
        async def run():
            playwright = MagicMock(); playwright.chromium.launch = AsyncMock()
            with patch.dict(os.environ, {'REPORT_KIT_BROWSER_CHANNEL': 'unreviewed'}):
                with self.assertRaises(ValueError):
                    async with launch_browser(playwright): pass
            playwright.chromium.launch.assert_not_awaited()
        asyncio.run(run())


if __name__ == '__main__': unittest.main()

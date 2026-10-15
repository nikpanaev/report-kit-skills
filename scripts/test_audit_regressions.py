"""Synthetic credential and post identity tests; no installed browser required."""
import asyncio
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/vk-stories-screenshot/scripts'))
import vk_stories
import ui_queue


class Timeout(Exception): pass


class Locator:
    @property
    def first(self): return self
    def filter(self, **kwargs): return self
    def locator(self, *args): return self
    async def wait_for(self, **kwargs): pass
    async def evaluate_all(self, *args): return True


class Page:
    def __init__(self, url): self.url = url
    async def goto(self, *args, **kwargs): return types.SimpleNamespace(ok=True)
    def locator(self, *args): return Locator()
    def get_by_role(self, *args):
        return types.SimpleNamespace(wait_for=AsyncMock(side_effect=Timeout()))


class AuditRegressions(unittest.TestCase):
    def test_windows_process_probe_never_terminates_and_denial_is_unknown(self):
        import ctypes
        api = MagicMock()
        api.OpenProcess.return_value = 42
        with patch.object(ctypes, 'WinDLL', return_value=api, create=True), \
             patch.object(ctypes, 'get_last_error', return_value=5, create=True) as error, \
             patch.object(ui_queue.os, 'name', 'nt'):
            for result, expected in ((0,False),(258,True),(0xffffffff,None)):
                api.WaitForSingleObject.return_value = result
                self.assertIs(ui_queue.process_alive(123), expected)
            api.OpenProcess.assert_called_with(0x00100000, False, 123)
            self.assertEqual(api.CloseHandle.call_count, 3)
            api.OpenProcess.return_value = 0
            self.assertIsNone(ui_queue.process_alive(123))
            error.return_value = 87
            self.assertIs(ui_queue.process_alive(123), False)
            self.assertFalse(api.TerminateProcess.called)

    def test_password_enrollment_refused_without_prompt_or_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials.json'
            with patch.object(vk_stories, 'AUTH', Path(directory) / 'vk'), patch.object(sys.stdin, 'isatty', return_value=True), \
                 patch('builtins.input') as prompt:
                with self.assertRaises(vk_stories.Failure):
                    vk_stories.run(types.SimpleNamespace(command='credentials', credentials=path))
                prompt.assert_not_called()
            self.assertFalse(path.exists())

    def test_threads_direct_identity_and_share_resolution(self):
        stub = types.ModuleType('playwright.async_api')
        stub.TimeoutError = Timeout; stub.async_playwright = lambda: None
        spec = importlib.util.spec_from_file_location('threads_audit', ROOT / 'skills/threads-post-screenshot/scripts/threads_post_screenshot.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'playwright': types.ModuleType('playwright'), 'playwright.async_api': stub}):
            spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'screenshot', new_callable=AsyncMock) as screenshot:
            page = Page('https://www.threads.com/@other/post/OTHER123')
            with self.assertRaisesRegex(RuntimeError, 'другой пост'):
                asyncio.run(module.capture(page, 'https://www.threads.com/@requested/post/REQUESTED123', Path(directory)))
            screenshot.assert_not_called()
            result = asyncio.run(module.capture(page, 'https://www.threads.com/share/ExampleShare/', Path(directory)))
            self.assertEqual(result.name, 'threads-OTHER123.png')
            self.assertEqual(page._threads_resolved_url, page.url)
            self.assertEqual(screenshot.await_count, 1)


if __name__ == '__main__':
    unittest.main()

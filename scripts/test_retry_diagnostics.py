"""Mock retry diagnostics only: no browser, network, session or screenshot evidence."""
import asyncio
from contextlib import asynccontextmanager, redirect_stderr
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/vk-post-screenshot/scripts"))
import playwright.async_api as api
import vk_post_screenshoter as capture


class Diagnostics(unittest.TestCase):
    def scenario(self, failed_stage, limited_first=False):
        navigations, rows, handlers = [], [], []
        failed = False
        canary = "synthetic customer text must not appear in retry logs"

        async def fail_once(stage):
            nonlocal failed
            if stage == failed_stage and not failed:
                failed = True
                raise api.TimeoutError(canary)

        async def goto(url, **kwargs):
            navigations.append(url)
            if not limited_first: await fail_once("navigation")
            status = 429 if limited_first or url.endswith("_11") else 200
            response = SimpleNamespace(status=status)
            for handler in handlers: handler(response)
            return response

        async def zoom(*args, **kwargs):
            await fail_once("browser_setup")
            return 100

        async def mocked_capture(page, post_id, destination, *args, **kwargs):
            await fail_once("capture")
            return destination  # Mock return only; no PNG is created or claimed as evidence.

        async def close(): pass
        async def invisible():
            await fail_once("preflight")
            return False
        async def sleep(*args): pass
        page = SimpleNamespace(goto=goto, close=close,
            on=lambda event, handler: handlers.append(handler),
            get_by_text=lambda *args: SimpleNamespace(first=SimpleNamespace(is_visible=invisible)))
        async def new_page(): return page
        context = SimpleNamespace(new_page=new_page, close=close)
        async def new_context(**kwargs): return context
        @asynccontextmanager
        async def launch(*args, **kwargs): yield SimpleNamespace(new_context=new_context)
        @asynccontextmanager
        async def playwright(): yield object()

        with tempfile.TemporaryDirectory() as folder:
            args = SimpleNamespace(urls=[f"https://vk.ru/wall-1_{n}" for n in (10, 11, 12)],
                login=False, cdp=None, state=Path(folder)/"absent.json", output=Path(folder),
                zoom=100, headed=False, timeout=300, retries=3, comments_only=False,
                visual_only=False, collapsed_text=False, all_visuals=False)
            # The real capture implementation alone supplies this metadata after a capture.
            page._vk_screenshot_theme = {"synthetic": True}
            stderr = io.StringIO()
            with patch.object(api, "async_playwright", playwright), patch.object(capture, "launch_browser", launch), \
                 patch.object(capture, "verify_zoom", zoom), patch.object(capture, "capture_post", mocked_capture), \
                 patch.object(capture, "emit", lambda **row: rows.append(row)), \
                 patch.object(capture.asyncio, "sleep", sleep), redirect_stderr(stderr):
                self.assertEqual(asyncio.run(capture.run(args)), 1)
            self.assertFalse(list(Path(folder).iterdir()))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["rate_limited"] for row in rows[int(not limited_first):]))
        self.assertEqual(len(navigations), 1 if limited_first else 2 if failed_stage == "preflight" else 3)
        self.assertNotIn(canary, stderr.getvalue())
        return stderr.getvalue()

    def test_navigation_retry_identifies_stage_without_customer_text(self):
        self.assertIn("stage=navigation, error_type=TimeoutError", self.scenario("navigation"))

    def test_preflight_retry_identifies_stage_without_customer_text(self):
        self.assertIn("stage=preflight, error_type=TimeoutError", self.scenario("preflight"))

    def test_browser_setup_retry_identifies_stage_without_customer_text(self):
        self.assertIn("stage=browser_setup, error_type=TimeoutError", self.scenario("browser_setup"))

    def test_capture_retry_identifies_stage_without_customer_text(self):
        self.assertIn("stage=capture, error_type=TimeoutError", self.scenario("capture"))

    def test_rate_limit_does_not_retry_or_log_customer_error(self):
        self.assertEqual(self.scenario("capture", limited_first=True), "")


if __name__ == "__main__": unittest.main()

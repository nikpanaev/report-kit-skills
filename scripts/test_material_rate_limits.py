"""Local Chromium fixtures only; every network request is intercepted."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/vk-post-screenshot/scripts"))
import vk_post_screenshoter as capture

SVG = "<svg xmlns='http://www.w3.org/2000/svg' width='240' height='120'><rect width='240' height='120' fill='purple'/></svg>"


class MaterialLimits(unittest.TestCase):
    def scenario(self, image_status):
        requests, rows, files = [], [], []
        limited = False
        original = capture.launch_browser

        @asynccontextmanager
        async def launch(*args, **kwargs):
            async with original(*args, **kwargs) as browser:
                new_context = browser.new_context

                async def context(**options):
                    result = await new_context(**options)

                    async def serve(route):
                        path = route.request.url.split("vk.ru")[-1]
                        requests.append((path, limited))
                        if path == "/deferred":
                            await route.fulfill(status=image_status, content_type="image/svg+xml", body=SVG if image_status == 200 else "not an image")
                        elif path == "/third":
                            await route.fulfill(status=200, content_type="image/svg+xml", body=SVG)
                        elif path.startswith("/wall"):
                            body = "<div class='post' id='post-1_10'>"
                            for number, source in enumerate(("data:image/svg+xml," + SVG.replace("<", "%3C").replace(">", "%3E").replace("'", "%27"), "/deferred", "/third"), 1):
                                body += (f"<div data-testid='primary-attachment-photo' style='margin-top:{15000 if number > 1 else 0}px'>"
                                         f"<a href='/photo-1_{number}'><img loading='lazy' width='240' height='120' src='{source}'></a></div>")
                            await route.fulfill(status=200, content_type="text/html", body=body + "</div>")
                        else:
                            await route.fulfill(status=204)

                    await result.route("**/*", serve)
                    new_page = result.new_page

                    async def page():
                        value = await new_page()

                        def response(res):
                            nonlocal limited
                            if res.status == 429:
                                limited = True

                        value.on("response", response)
                        return value

                    result.new_page = page
                    return result

                browser.new_context = context
                yield browser

        async def run():
            with tempfile.TemporaryDirectory() as folder:
                output = Path(folder)
                args = SimpleNamespace(urls=["https://vk.ru/wall-1_10"] + (["https://vk.ru/wall-1_11"] if image_status == 429 else []),
                    login=False, cdp=None, state=output / "absent.json", zoom=100, headed=False,
                    timeout=2000, retries=3, output=output, comments_only=False, visual_only=False,
                    collapsed_text=False, all_visuals=True)
                with patch.object(capture, "launch_browser", launch), patch.object(capture, "emit", lambda **row: rows.append(row)), patch.object(capture, "NAVIGATION_DELAY", 0):
                    status = await capture.run(args)
                for path in output.glob("*.png"):
                    data = path.read_bytes()
                    self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
                    files.append({"path": str(path), "sha256": hashlib.sha256(data).hexdigest()})
                self.assertEqual(len(files), rows[0]["obtained_count"])
            self.assertTrue(all(not Path(item["path"]).exists() for item in files))
            print(json.dumps({"status": image_status, "requests": requests, "rows": rows, "files": files, "files_removed": True}))
            return status

        status = asyncio.run(run())
        self.assertEqual(rows[0]["expected_count"], 3)
        return status, requests, rows

    def test_429_stops_later_material_and_post_preserving_first_png(self):
        status, requests, rows = self.scenario(429)
        self.assertEqual(status, 1)
        self.assertIn(("/deferred", False), requests)
        self.assertFalse(any(after_limit for _, after_limit in requests))
        self.assertEqual([path for path, _ in requests if path.startswith("/wall")], ["/wall-1_10"])
        self.assertEqual(rows[0]["obtained_count"], 1)
        self.assertTrue(rows[0]["materials"][0]["ok"])
        self.assertTrue(all(row["rate_limited"] and not row["ok"] for row in rows))
        self.assertEqual(len(rows), 2)

    def test_non_rate_image_failure_allows_third_material(self):
        status, requests, rows = self.scenario(503)
        self.assertEqual(status, 1)
        self.assertIn(("/third", False), requests)
        self.assertEqual(rows[0]["obtained_count"], 2)
        self.assertFalse(rows[0]["materials"][1]["ok"])
        self.assertNotIn("rate_limited", rows[0])

    def test_complete_album(self):
        status, _, rows = self.scenario(200)
        self.assertEqual(status, 0)
        self.assertTrue(rows[0]["ok"])
        self.assertEqual(rows[0]["obtained_count"], 3)


if __name__ == "__main__":
    unittest.main()

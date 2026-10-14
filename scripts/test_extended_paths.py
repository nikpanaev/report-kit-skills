"""Reject package writes before browser, session or image access; synthetic inputs only."""
import asyncio
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]


def module(skill, file):
    spec = importlib.util.spec_from_file_location(skill.replace("-", "_"), ROOT / "skills" / skill / "scripts" / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class RuntimePaths(unittest.TestCase):
    def test_instagram_rejects_package_session_before_login(self):
        ig = module("instagram-post-screenshot", "instagram_post_screenshot.py")
        state = ROOT / "forbidden-session.json"
        with patch.object(sys, "argv", ["capture", "--login", "--state", str(state)]), patch.object(ig, "run", new_callable=AsyncMock) as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ig.main(), 1)
            run.assert_not_called()
        self.assertFalse(state.exists())

    def test_instagram_defaults_use_external_selected_state(self):
        ig = module("instagram-post-screenshot", "instagram_post_screenshot.py")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"REPORT_SKILLS_STATE_DIR": directory}), patch.object(sys, "argv", ["capture", "--login"]), patch.object(ig, "run", new_callable=AsyncMock, return_value=0) as run:
            self.assertEqual(ig.main(), 0)
            args = run.call_args.args[0]
            self.assertEqual(args.state, Path(directory).resolve() / "instagram-session.json")
            self.assertTrue(args.output.is_relative_to(Path(directory).resolve()))

    def test_post_capture_rejects_package_output_before_navigation(self):
        threads = module("threads-post-screenshot", "threads_post_screenshot.py")
        tiktok = module("tiktok-post-screenshot", "tiktok_post_screenshoter.py")
        for call in [lambda: threads.capture(None, "synthetic", ROOT / "forbidden"), lambda: tiktok.capture_post(None, "synthetic", ROOT / "forbidden.png", 100)]:
            with self.assertRaisesRegex(ValueError, "Runtime data must be outside"):
                asyncio.run(call())
        self.assertFalse((ROOT / "forbidden.png").exists())

    def test_stitch_rejects_output_before_opening_images(self):
        stitch = module("max-post-screenshot", "stitch_post_screenshots.py")
        output = io.StringIO()
        args = ["stitch", "nonexistent.png", "--output", str(ROOT / "forbidden.png"), "--header", "0", "--match-left", "0", "--match-right", "10"]
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(output):
            self.assertEqual(stitch.main(), 1)
        self.assertIn("Runtime data must be outside", json.loads(output.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()

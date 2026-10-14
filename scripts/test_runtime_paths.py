"""Synthetic path containment and source import checks; no browser or credentials."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/_shared"))
from private_paths import outside_package


class RuntimePaths(unittest.TestCase):
    def test_package_and_ancestor_rejected(self):
        for value in [ROOT, ROOT / "outputs/run", ROOT.parent]:
            with self.assertRaises(ValueError):
                outside_package(value)

    def test_external_and_symlink_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(outside_package(root / "new/state"), (root / "new/state").resolve())
            (root / "link").symlink_to(ROOT, target_is_directory=True)
            with self.assertRaises(ValueError):
                outside_package(root / "link/state")

    def test_all_imports_and_common_state_outside_package(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, REPORT_SKILLS_STATE_DIR=folder, PYTHONDONTWRITEBYTECODE="1")
            env.pop("PERSONAL_UI_QUEUE_TOKEN", None)
            program = """import sys,json
from pathlib import Path
root=Path(sys.argv[1]); state=Path(sys.argv[2])
sys.path[:0]=[str(root/'skills'/name/'scripts') for name in ['vk-post-screenshot','vk-comment-screenshot','vk-stories-screenshot','vk-message-screenshot']]+[str(root/'skills/_shared')]
import vk_post_screenshoter, vk_comment_screenshoter, vk_stories, vk_messages, ui_queue
assert ui_queue.DATABASE==state/'queue.sqlite3'
assert vk_stories.AUTH==state/'vk'
assert vk_messages.shared is vk_stories
assert vk_comment_screenshoter.capture_post is vk_post_screenshoter.capture_post
print(json.dumps({'status':'PASS','imports':4,'single_state':True}))
"""
            result = subprocess.run([sys.executable, "-c", program, str(ROOT), folder], env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["imports"], 4)
            self.assertFalse(list(Path(folder).iterdir()), "Import must not create state or read accounts")


if __name__ == "__main__":
    unittest.main()

"""Private VK bootstrap/capture folders; no browser, real login or service access."""
import contextlib
import hashlib
import io
import json
import os
from argparse import Namespace
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'skills/vk-stories-screenshot/scripts'))
import vk_stories as stories
import ui_queue


class PrivateOutputs(unittest.TestCase):
    def test_bootstrap_orders_and_existing_permissions(self):
        for order in ('credentials-first', 'queue-first', 'existing-root'):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / 'state'
                unrelated = root / 'unrelated'
                unrelated.mkdir(mode=0o755)
                unrelated.chmod(0o755)
                previous_umask = os.umask(0o022)
                try:
                    with patch.object(stories, 'AUTH', state / 'vk'), \
                         patch.object(ui_queue, 'DATABASE', state / 'queue.sqlite3'), \
                         patch.object(stories, 'session') as browser, \
                         contextlib.redirect_stdout(io.StringIO()):
                        if order == 'queue-first':
                            ticket = ui_queue.operate(state / 'queue.sqlite3', 'enqueue', owner='fixture')
                            ui_queue.operate(state / 'queue.sqlite3', 'release', token=ticket['token'])
                        elif order == 'existing-root':
                            state.mkdir()
                            state.chmod(0o755)
                        args = Namespace(command='credentials', credentials=state / 'vk/credentials.json')
                        with patch.object(sys.stdin, 'isatty', return_value=True), \
                             patch('builtins.input', return_value='fixture-login'), \
                             patch.object(stories.getpass, 'getpass', return_value='fixture-secret'):
                            self.assertEqual(stories.run(args), 0)
                        self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
                        self.assertEqual(stat.S_IMODE(args.credentials.stat().st_mode), 0o600)
                        capture = Namespace(command='capture', url='https://vk.ru/fixture',
                            month='2026-08', timezone='Europe/Moscow', output=None,
                            ui=root / 'missing-ui.json')
                        self.assertEqual(stories.run(capture), 1)
                        self.assertEqual(stat.S_IMODE(capture.output.stat().st_mode), 0o700)
                        browser.assert_not_called()
                        self.assertEqual(stat.S_IMODE(unrelated.stat().st_mode), 0o755)
                finally:
                    os.umask(previous_umask)
                    for file in sorted(root.rglob('*')):
                        if file.is_file():
                            print(json.dumps({'temporary_path': str(file),
                                'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                                'result': 'Synthetic private-mode check; removed by temporary directory'}))

    def test_explicit_capture_folder_is_closed_before_failed_ui(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'capture'
            output.mkdir(mode=0o755)
            output.chmod(0o755)
            try:
                with patch.object(stories, 'AUTH', root / 'state/vk'), \
                     patch.object(ui_queue, 'DATABASE', root / 'state/queue.sqlite3'), \
                     patch.object(stories, 'session') as browser, \
                     contextlib.redirect_stdout(io.StringIO()):
                    args = Namespace(command='capture', url='https://vk.ru/fixture',
                        month='2026-08', timezone='Europe/Moscow', output=output,
                        ui=root / 'missing-ui.json')
                    self.assertEqual(stories.run(args), 1)
                    self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
                    browser.assert_not_called()
            finally:
                for file in sorted(root.rglob('*')):
                    if file.is_file():
                        print(json.dumps({'temporary_path': str(file),
                            'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                            'result': 'Synthetic private-mode check; removed by temporary directory'}))


if __name__ == '__main__':
    unittest.main()

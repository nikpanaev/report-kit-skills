"""Real process death and borrowed-owner checks; isolated local queue only."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import ui_queue as queue


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.03)
    raise AssertionError('Synthetic worker did not reach checkpoint')


def worker(database, directory, borrowed=False):
    directory = Path(directory)
    with queue.access('synthetic-worker', database=Path(database)):
        if borrowed:
            (directory / 'borrowed-ready').touch()
        else:
            child = subprocess.Popen([sys.executable, __file__, 'borrowed', database, str(directory)])
            (directory / 'child-pid').write_text(str(child.pid), encoding='utf-8')
            (directory / 'owner-ready').touch()
        while not (directory / 'finish').exists(): time.sleep(.03)


def checks():
    with tempfile.TemporaryDirectory(prefix='queue-recovery-') as temporary:
        root = Path(temporary); database = root / 'queue.sqlite3'
        env = dict(os.environ); env.pop(queue.TOKEN_ENV, None)
        parent = subprocess.Popen([sys.executable, __file__, 'owner', str(database), str(root)], env=env)
        child_pid = None
        try:
            wait_for(lambda: (root / 'borrowed-ready').exists())
            child_pid = int((root / 'child-pid').read_text(encoding='utf-8'))
            parent.kill(); parent.wait(timeout=5)
            contender = queue.operate(database, 'enqueue', owner='next')
            assert queue.operate(database, 'claim', token=contender['token'])['state'] == 'waiting', 'Borrowed child still holds UI'
            (root / 'finish').touch()
            wait_for(lambda: queue.operate(database, 'claim', token=contender['token'])['state'] == 'active')
            queue.operate(database, 'release', token=contender['token'])
            # No expiry for legacy/manual tickets or unknown process status.
            legacy = queue.operate(database, 'enqueue', owner='manual-owner')
            with patch.object(queue, 'process_alive', return_value=False):
                next_ticket = queue.operate(database, 'enqueue', owner='manual-next')
                assert queue.operate(database, 'claim', token=next_ticket['token'])['state'] == 'waiting'
            for ticket in (legacy,next_ticket): queue.operate(database,'release',token=ticket['token'])
            held = queue.operate(database,'enqueue',owner='managed',managed=True)
            with patch.object(queue,'process_alive',return_value=None):
                next_ticket = queue.operate(database,'enqueue',owner='unknown-next')
                assert queue.operate(database,'claim',token=next_ticket['token'])['state']=='waiting'
            for ticket in (held,next_ticket): queue.operate(database,'release',token=ticket['token'])
            unconfirmed = queue.operate(database,'enqueue',owner='missing-owner',managed=True)
            with sqlite3.connect(database) as db: db.execute('DELETE FROM lease_owners')
            next_ticket = queue.operate(database,'enqueue',owner='after-missing')
            assert queue.operate(database,'claim',token=next_ticket['token'])['state']=='waiting'
            for ticket in (unconfirmed,next_ticket): queue.operate(database,'release',token=ticket['token'])
            assert queue.operate(database,'status')['tickets']==[]
        finally:
            (root / 'finish').touch()
            if parent.poll() is None: parent.terminate();parent.wait(timeout=5)
            # Child gets an explicit end marker; never kill an unverified reused PID.
            if child_pid is not None: time.sleep(.2)
            files=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in root.iterdir() if p.is_file()]
            print(json.dumps({'temporary':files,'result':'isolated process recovery fixtures; cleanup follows'}))
    print('PASS dead parent recovery; live borrowed child preserved; manual/unknown ownership never expired')


if __name__ == '__main__':
    if len(sys.argv)>1: worker(sys.argv[2],sys.argv[3],borrowed=sys.argv[1]=='borrowed')
    else: checks()

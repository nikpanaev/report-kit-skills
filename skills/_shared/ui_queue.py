#!/usr/bin/env python3
"""One FIFO for personal UI skills; legacy Telegram tickets keep their order."""
import argparse
import asyncio
import functools
import json
import os
import secrets
import select
import signal
import socket
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from private_paths import outside_package
from support_events import emit as support_event, error_code

# One per-user store outside every package; do not migrate an existing UI queue without review.
DATABASE = Path(os.environ.get("REPORT_SKILLS_STATE_DIR", Path.home() / ".local/state/report-skills")) / "queue.sqlite3"
TOKEN_ENV = 'PERSONAL_UI_QUEUE_TOKEN'
CURRENT = ContextVar('personal_ui_lease', default=None)


def process_alive(pid):
    """False only for a proven dead local process; denial/unknown is never stale."""
    if type(pid) is not int or not 0 < pid <= 0xffffffff: return None
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x00100000, False, pid)
        if not handle: return False if ctypes.get_last_error() == 87 else None
        try:
            result = api.WaitForSingleObject(handle, 0)
            return {0: False, 258: True}.get(result)
        finally: api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError: return False
    except OSError: return None


def reap_dead(db):
    db.execute('DELETE FROM lease_owners WHERE token NOT IN (SELECT token FROM tickets)')
    for row in db.execute('SELECT token FROM tickets WHERE managed=1').fetchall():
        holders = db.execute('SELECT pid,host FROM lease_owners WHERE token=?', (row['token'],)).fetchall()
        if not holders: continue  # Missing ownership is not evidence of process death.
        for holder in holders:
            if holder['host'] == socket.gethostname() and process_alive(holder['pid']) is False:
                db.execute('DELETE FROM lease_owners WHERE token=? AND pid=? AND host=?',
                           (row['token'], holder['pid'], holder['host']))
        if not db.execute('SELECT 1 FROM lease_owners WHERE token=?', (row['token'],)).fetchone():
            db.execute('DELETE FROM tickets WHERE token=?', (row['token'],))


def operate(path, action, *, owner=None, token=None, managed=False):
    path = outside_package(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        os.chmod(path, 0o600)
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            owner TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'waiting')''')
        if 'managed' not in {row['name'] for row in db.execute('PRAGMA table_info(tickets)')}:
            db.execute('ALTER TABLE tickets ADD COLUMN managed INTEGER NOT NULL DEFAULT 0')
        db.execute('CREATE TABLE IF NOT EXISTS lease_owners (token TEXT, pid INTEGER, host TEXT, PRIMARY KEY(token,pid,host))')
        if action in ('enqueue', 'claim', 'check'): reap_dead(db)
        if action == 'enqueue':
            if not owner or not owner.strip():
                raise ValueError('Нужен владелец задачи')
            token = secrets.token_hex(16)
            row = db.execute('INSERT INTO tickets(token, owner,managed) VALUES (?, ?, ?)', (token, owner.strip(), int(managed)))
            if managed:
                db.execute('INSERT INTO lease_owners VALUES (?,?,?)', (token, os.getpid(), socket.gethostname()))
            result = dict(ok=True, id=row.lastrowid, token=token, state='waiting')
        elif action == 'status':
            result = dict(ok=True, tickets=[dict(row) for row in db.execute(
                'SELECT id, owner, state FROM tickets ORDER BY id')])
        elif action in ('claim', 'check', 'release', 'detach'):
            ticket = db.execute('SELECT * FROM tickets WHERE token = ?', (token,)).fetchone()
            if ticket is None:
                raise ValueError('Билет не найден; чужая очередь не изменена')
            if action in ('release', 'detach'):
                if managed:
                    removed = db.execute('DELETE FROM lease_owners WHERE token=? AND pid=? AND host=?', (token, os.getpid(), socket.gethostname())).rowcount
                    if removed and ticket['managed'] and not db.execute('SELECT 1 FROM lease_owners WHERE token=?', (token,)).fetchone():
                        db.execute('DELETE FROM tickets WHERE token=?', (token,))
                    reap_dead(db)
                else:
                    db.execute('DELETE FROM tickets WHERE token = ?', (token,))
                    db.execute('DELETE FROM lease_owners WHERE token = ?', (token,))
                result = dict(ok=True, id=ticket['id'], state='released')
            else:
                position = db.execute('SELECT COUNT(*) FROM tickets WHERE id <= ?', (ticket['id'],)).fetchone()[0]
                if action == 'check' and (position != 1 or ticket['state'] != 'active'):
                    raise ValueError('Унаследованный билет не активен; управление UI запрещено')
                if action == 'check' and managed and ticket['managed']:
                    db.execute('INSERT OR IGNORE INTO lease_owners VALUES (?,?,?)', (token, os.getpid(), socket.gethostname()))
                if action == 'claim' and position == 1:
                    db.execute("UPDATE tickets SET state = 'active' WHERE token = ?", (token,))
                result = dict(ok=True, id=ticket['id'], position=position,
                              state='active' if position == 1 else 'waiting')
        else:
            raise ValueError('Неизвестное действие')
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


class Lease:
    def __init__(self, owner, token, database):
        self.owner, self.token, self.database = owner, token, database
        self.borrowed = bool(token)

    def acquire(self):
        if self.borrowed:
            operate(self.database, 'check', token=self.token, managed=True)
        else:
            self.token = operate(self.database, 'enqueue', owner=self.owner, managed=True)['token']
            waiting = False
            while operate(self.database, 'claim', token=self.token)['state'] != 'active':
                if not waiting:
                    print('Ожидание общей очереди интерфейса: ' + self.owner, file=sys.stderr, flush=True)
                    waiting = True
                time.sleep(0.2)
        os.environ[TOKEN_ENV] = self.token

    def release(self):
        if self.token:
            operate(self.database, 'detach' if self.borrowed else 'release', token=self.token, managed=True)
            self.token = None
            os.environ.pop(TOKEN_ENV, None)

    @contextmanager
    def handoff(self):
        if self.borrowed:
            raise ValueError('Ручной вход: владелец должен освободить внешний билет; запустите login без PERSONAL_UI_QUEUE_TOKEN')
        self.release()
        try:
            yield
        finally:
            # Cleanup also touches UI, so reacquire even when input fails/cancels.
            self.acquire()


def current_lease():
    lease = CURRENT.get()
    if lease is None:
        raise ValueError('Нет доступа к общей очереди интерфейса')
    return lease


async def wait_for_enter(prompt):
    # Avoid an uncancellable input() thread surviving asyncio cancellation.
    with current_lease().handoff():
        print(prompt, file=sys.stderr, flush=True)
        while not select.select([sys.stdin], [], [], 0)[0]:
            await asyncio.sleep(0.2)
        if not sys.stdin.readline():
            raise EOFError('Manual login cancelled')


@contextmanager
def access(owner=None, *, token=None, database=None):
    existing = CURRENT.get()
    if existing is not None:
        if (database is not None and Path(database) != Path(existing.database)) or (token and token != existing.token):
            raise ValueError('Вложенный вызов должен использовать билет родителя')
        operate(existing.database, 'check', token=existing.token)
        yield existing
        return
    previous_env = os.environ.get(TOKEN_ENV)
    lease = Lease(owner or f'{Path(sys.argv[0]).name}:pid={os.getpid()}',
                  token or previous_env, database or DATABASE)
    previous_signal = None
    if threading.current_thread() is threading.main_thread():
        previous_signal = signal.getsignal(signal.SIGTERM)
        def cancel(signum, frame):
            raise KeyboardInterrupt('UI task cancelled')
        signal.signal(signal.SIGTERM, cancel)
    marker = CURRENT.set(lease)
    diagnostic = support_event('ui','queue','started')
    outcome, code = 'unknown', 'NONE'
    try:
        lease.acquire()
        yield lease
        outcome = 'success'
    except BaseException as error:
        outcome, code = 'failure', error_code(error)
        raise
    finally:
        try:
            lease.release()
        except BaseException as error:
            outcome, code = 'failure', error_code(error)
            raise
        finally:
            support_event('ui','queue','finished',outcome,code,operation=diagnostic)
            CURRENT.reset(marker)
            if previous_signal is not None:
                signal.signal(signal.SIGTERM, previous_signal)
            if previous_env is None:
                os.environ.pop(TOKEN_ENV, None)
            else:
                os.environ[TOKEN_ENV] = previous_env


def queued(function):
    @functools.wraps(function)
    async def asynchronous(*args, **kwargs):
        with access(function.__module__):
            return await function(*args, **kwargs)
    @functools.wraps(function)
    def synchronous(*args, **kwargs):
        with access(function.__module__):
            return function(*args, **kwargs)
    return asynchronous if asyncio.iscoroutinefunction(function) else synchronous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('enqueue').add_argument('--owner', required=True)
    sub.add_parser('status')
    for action in ('claim', 'check', 'release'):
        sub.add_parser(action).add_argument('token')
    args = parser.parse_args()
    try:
        result = operate(DATABASE, args.action, owner=getattr(args, 'owner', None),
                         token=getattr(args, 'token', None))
    except (OSError, sqlite3.Error, ValueError) as error:
        print(json.dumps(dict(ok=False, error=str(error)), ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

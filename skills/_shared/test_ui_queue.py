#!/usr/bin/env python3
"""Process-level FIFO, cancellation, handoff and nested ownership checks."""
import json
import asyncio
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ui_queue import DATABASE, TOKEN_ENV, access, operate, wait_for_enter


def wait_for(predicate):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError('Timed out waiting for worker')


def worker(database, name, mode, directory):
    database, directory = Path(database), Path(directory)
    with access(name, database=database) as lease:
        (directory / (name + '.active')).write_text(lease.token)
        if mode == 'nested':
            with access('nested-skill', database=database) as nested:
                assert nested is lease
                assert len(operate(database, 'status')['tickets']) == 1
            child = subprocess.run([sys.executable, __file__, 'worker', str(database),
                                    'child', 'borrowed', str(directory)], timeout=10)
            assert child.returncode == 0
            assert operate(database, 'check', token=lease.token)['state'] == 'active'
        elif mode == 'borrowed':
            assert lease.borrowed
            try:
                with lease.handoff():
                    raise AssertionError('Borrowed manual handoff allowed')
            except ValueError:
                pass
        elif mode == 'error':
            raise RuntimeError('intentional failure')
        elif mode == 'handoff':
            old = lease.token
            with lease.handoff():
                (directory / 'handoff.ready').touch()
                wait_for(lambda: (directory / 'login.done').exists())
            assert old != lease.token
            (directory / 'handoff.reacquired').touch()
        elif mode == 'hold':
            wait_for(lambda: (directory / (name + '.finish')).exists())


def checks():
    with tempfile.TemporaryDirectory(prefix='personal-ui-queue-') as temporary:
        directory = Path(temporary)
        database = directory / 'queue.sqlite3'
        children = []
        def spawn(name, mode):
            env = dict(os.environ)
            env.pop(TOKEN_ENV, None)
            process = subprocess.Popen([sys.executable, __file__, 'worker', str(database),
                                        name, mode, str(directory)], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children.append(process)
            return process
        def tickets():
            return operate(database, 'status')['tickets']
        def done(process, success=True):
            code = process.wait(timeout=15)
            assert (code == 0) == success, code
        try:
            first = spawn('VK', 'hold')
            wait_for(lambda: (directory / 'VK.active').exists())
            second = spawn('Telegram', 'hold')
            wait_for(lambda: len(tickets()) == 2)
            third = spawn('LiveDune', 'hold')
            wait_for(lambda: len(tickets()) == 3)
            assert [row['owner'] for row in tickets()] == ['VK', 'Telegram', 'LiveDune']
            assert [row['state'] for row in tickets()] == ['active', 'waiting', 'waiting']
            # Delayed holders are never expired by age or repeated claims.
            token = (directory / 'VK.active').read_text()
            for _ in range(3):
                assert operate(database, 'check', token=token)['state'] == 'active'
            (directory / 'VK.finish').touch(); done(first)
            wait_for(lambda: (directory / 'Telegram.active').exists())
            assert not (directory / 'LiveDune.active').exists()
            (directory / 'Telegram.finish').touch(); done(second)
            wait_for(lambda: (directory / 'LiveDune.active').exists())
            (directory / 'LiveDune.finish').touch(); done(third)
            assert tickets() == []

            first = spawn('holder', 'hold')
            wait_for(lambda: (directory / 'holder.active').exists())
            cancelled = spawn('cancelled-waiter', 'hold')
            wait_for(lambda: len(tickets()) == 2)
            cancelled.send_signal(signal.SIGTERM); done(cancelled, False)
            assert [row['owner'] for row in tickets()] == ['holder']
            first.send_signal(signal.SIGINT); done(first, False)
            assert tickets() == []
            active_cancel = spawn('active-cancel', 'hold')
            wait_for(lambda: (directory / 'active-cancel.active').exists())
            active_cancel.send_signal(signal.SIGTERM); done(active_cancel, False)
            assert tickets() == []
            error = spawn('error', 'error'); done(error, False)
            assert tickets() == []
            nested = spawn('parent', 'nested'); done(nested)
            assert tickets() == []

            manual = spawn('login', 'handoff')
            wait_for(lambda: (directory / 'handoff.ready').exists())
            assert tickets() == []
            other = spawn('MAX', 'hold')
            wait_for(lambda: (directory / 'MAX.active').exists())
            (directory / 'login.done').touch()
            wait_for(lambda: len(tickets()) == 2)
            assert [row['owner'] for row in tickets()] == ['MAX', 'login']
            assert not (directory / 'handoff.reacquired').exists()
            (directory / 'MAX.finish').touch(); done(other); done(manual)
            assert tickets() == []

            ticket = operate(database, 'enqueue', owner='waiting')
            for action in ('check', 'release'):
                try:
                    operate(database, action, token='wrong-token')
                    raise AssertionError('Unknown token accepted')
                except ValueError:
                    pass
            try:
                with access('invalid-inheritance', token=ticket['token'], database=database):
                    raise AssertionError('Waiting inherited ticket accepted')
            except ValueError:
                pass
            assert tickets()[0]['state'] == 'waiting'
            operate(database, 'release', token=ticket['token'])
            assert tickets() == []

            # Legacy schema and wrapper preserve the same database and ticket ordering.
            with sqlite3.connect(database) as db:
                db.execute("INSERT INTO tickets(token,owner,state) VALUES ('old','legacy','active')")
            new = operate(database, 'enqueue', owner='new-platform')
            assert operate(database, 'claim', token=new['token'])['position'] == 2
            operate(database, 'release', token='old')
            operate(database, 'release', token=new['token'])
            from unittest.mock import patch
            async def cancel_login():
                read_fd, write_fd = os.pipe()
                try:
                    with os.fdopen(read_fd) as reader, patch.object(sys, 'stdin', reader):
                        with access('async-login', database=database) as lease:
                            old = lease.token
                            task = asyncio.create_task(wait_for_enter('test manual login'))
                            await asyncio.sleep(0.05)
                            assert tickets() == []
                            task.cancel()
                            try:
                                await task
                                raise AssertionError('Login cancellation ignored')
                            except asyncio.CancelledError:
                                pass
                            assert old != lease.token
                            assert operate(database, 'check', token=lease.token)['state'] == 'active'
                finally:
                    os.close(write_fd)
            asyncio.run(cancel_login())
            assert tickets() == []
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=15)
    print(json.dumps(dict(ok=True, checks=[
        'multiprocess_cross_platform_FIFO', 'no_active_ticket_expiry',
        'waiting_SIGTERM', 'active_SIGINT_and_SIGTERM', 'error_release',
        'nested_context_and_subprocess', 'manual_handoff_rejoins_FIFO',
        'reject_unknown_and_waiting_tokens', 'legacy_schema_ordering',
        'async_manual_login_cancellation_without_input_thread']), ensure_ascii=False))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'worker':
        worker(*sys.argv[2:])
    else:
        checks()

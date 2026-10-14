#!/usr/bin/env python3
"""Проверка FIFO и двух независимых процессов, без Telegram и рабочей БД."""

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from telegram_queue import operate


def enqueue(path):
    return operate(path, 'enqueue', owner='test')


def claim(args):
    path, token = args
    return operate(path, 'claim', token=token)


def main():
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'queue.sqlite3'
        with ProcessPoolExecutor(max_workers=2) as pool:
            tickets = sorted(pool.map(enqueue, [path, path]), key=lambda row: row['id'])
            results = list(pool.map(claim, [(path, row['token']) for row in tickets]))
        assert [row['state'] for row in results] == ['active', 'waiting']
        assert [row['position'] for row in results] == [1, 2]
        assert operate(path, 'claim', token=tickets[0]['token'])['state'] == 'active'
        try:
            operate(path, 'release', token='wrong-owner-token')
        except ValueError:
            pass
        else:
            raise AssertionError('Чужой токен удалил билет')
        assert len(operate(path, 'status')['tickets']) == 2
        operate(path, 'release', token=tickets[0]['token'])
        assert operate(path, 'claim', token=tickets[1]['token'])['state'] == 'active'
        pending = operate(path, 'enqueue', owner='cancelled')
        operate(path, 'release', token=pending['token'])
        operate(path, 'release', token=tickets[1]['token'])
        assert operate(path, 'status')['tickets'] == []
    print('FIFO, parallel claims, ownership, cancellation: OK')


if __name__ == '__main__':
    main()

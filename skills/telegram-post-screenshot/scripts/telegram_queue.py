#!/usr/bin/env python3
"""Compatibility entry point; Telegram uses the global personal UI FIFO."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from ui_queue import DATABASE, main, operate

if __name__ == '__main__':
    raise SystemExit(main())

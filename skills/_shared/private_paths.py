"""Resolve runtime data paths outside the source/plugin package before writing."""
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def outside_package(value):
    path = Path(value).expanduser().resolve()
    root = PACKAGE_ROOT.resolve()
    if path.is_relative_to(root) or root.is_relative_to(path):
        raise ValueError("Runtime data must be outside the report-skills package")
    return path

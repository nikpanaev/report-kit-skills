#!/usr/bin/env python3
"""Скриншоты только загруженных комментариев к постам VK. stdout: JSON Lines."""

import sys
from pathlib import Path

# Общий браузер, авторизация и проверка ссылок из установленного vk-post-screenshot.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vk-post-screenshot" / "scripts"))
from vk_post_screenshoter import capture_post, main


async def capture_comments(page, post_id, destination, timeout):
    return await capture_post(page, post_id, destination, timeout, comments_only=True)


if __name__ == "__main__":
    sys.argv.insert(1, "--comments-only")
    sys.exit(main(description=__doc__))

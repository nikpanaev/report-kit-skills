"""Save the original Threads post card, excluding replies and login overlays."""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from ui_queue import queued
from private_paths import outside_package
from browser_zoom import add_zoom_argument, launch_browser, verify_zoom, screenshot
from urllib.parse import urlsplit

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


def check_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"threads.com", "www.threads.com"}
        or parsed.username
        or parsed.password
        or not (
            re.fullmatch(r"/share/[A-Za-z0-9_-]+/?", parsed.path)
            or re.fullmatch(r"/@[A-Za-z0-9_.]+/post/[A-Za-z0-9_-]+/?", parsed.path)
        )
    ):
        raise ValueError("Нужна ссылка на конкретный пост Threads")


async def capture(page, url: str, output: Path, *, zoom=None, headless=False) -> Path:
    output = outside_package(output)
    check_url(url)
    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    final = urlsplit(page.url)
    match = re.fullmatch(r"/@[A-Za-z0-9_.]+/post/([A-Za-z0-9_-]+)/?", final.path)
    if not response or not response.ok or final.hostname not in {"threads.com", "www.threads.com"} or not match:
        raise RuntimeError("Пост Threads не открылся")
    requested = re.fullmatch(r"/@[A-Za-z0-9_.]+/post/([A-Za-z0-9_-]+)/?", urlsplit(url).path)
    if requested and requested.group(1) != match.group(1):
        raise RuntimeError("Threads открыл другой пост; снимок не сохранён")
    page._threads_resolved_url = 'https://' + final.hostname + final.path
    if zoom is not None:
        await verify_zoom(page, zoom, headless=headless)

    post_id = match.group(1)
    permalink = page.locator(f'a[href*="/post/{post_id}"] time')
    post = page.locator('[data-pagelet^="threads_post_page_"]').filter(has=permalink).first
    await post.wait_for(state="visible", timeout=15000)

    dialog = page.get_by_role("dialog")
    try:
        await dialog.wait_for(state="visible", timeout=2000)
    except PlaywrightTimeoutError:
        pass
    else:
        await page.mouse.click(80, 80)
        await dialog.wait_for(state="hidden", timeout=5000)

    images = post.locator("img")
    loaded = await images.evaluate_all(
        "async els => { await Promise.all(els.map(img => img.decode().catch(() => {}))); "
        "return els.every(img => img.naturalWidth > 0) }"
    )
    if not loaded:
        raise RuntimeError("Изображения поста не загрузились")
    output.mkdir(parents=True, exist_ok=True)
    path = (output / f"threads-{post_id}.png").resolve()
    await screenshot(post, path=str(path))
    return path


@queued
async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("REPORT_SKILLS_STATE_DIR", Path.home() / ".local/state/report-skills")) / "outputs/threads-screenshots")
    parser.add_argument('--headed',action='store_true',help='Внешний браузер со штатным масштабом')
    add_zoom_argument(parser)
    args = parser.parse_args()
    args.output = outside_package(args.output)
    failed = False
    async with async_playwright() as playwright:
        async with launch_browser(playwright, zoom=args.zoom, headless=not args.headed) as browser:
            context = await browser.new_context(color_scheme="light",
                viewport={"width": 1280, "height": 900}, device_scale_factor=2, locale="ru-RU")
            page = await context.new_page()
            for url in args.urls:
                try:
                    path = await capture(page, url, args.output, zoom=args.zoom, headless=not args.headed)
                    actual_zoom = await verify_zoom(page,args.zoom,headless=not args.headed)
                    print(json.dumps({"ok": True, "url": url, "path": str(path),
                                      "resolved_url": page._threads_resolved_url,
                                      "browser_zoom": actual_zoom,
                                      "zoom_fallback":'native_headless_100' if actual_zoom != args.zoom else None}, ensure_ascii=False))
                except Exception as error:
                    failed = True
                    print(json.dumps({"ok": False, "url": url, "error": str(error)}, ensure_ascii=False))
            await context.close()

    return int(failed)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

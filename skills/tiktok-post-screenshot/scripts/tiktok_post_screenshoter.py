#!/usr/bin/env python3
"""Снимки видеопостов TikTok. stdout: один JSON-результат на ссылку."""

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


def parse_post_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value.strip() if "://" in value else "https://" + value.strip())
    if (parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}
            or parsed.username or parsed.password or parsed.port):
        raise ValueError("Нужна прямая ссылка на видеопост tiktok.com")
    match = re.fullmatch(r"/@[A-Za-z0-9._]+/video/([1-9]\d*)/?", parsed.path)
    if not match:
        raise ValueError("В ссылке должен быть видеопост: /@автор/video/ID")
    return f"https://www.tiktok.com{parsed.path.rstrip('/')}", match[1]


async def dismiss_overlays(page) -> None:
    await page.keyboard.press("Escape")
    for _ in range(3):
        # Варианты окна входа имеют разные data-e2e; Skip ищем в открытом окне.
        for mask in await page.locator('[class*="DivModalMask"]:visible').all():
            skip = mask.locator("..").get_by_text("Skip", exact=True).first
            if await skip.is_visible():
                await skip.click(timeout=5000)
        for locator in (
            page.get_by_role("button", name="Got it", exact=True),
            page.get_by_role("button", name="Decline optional cookies", exact=True),
        ):
            if await locator.is_visible():
                await locator.click(timeout=5000)
        await page.wait_for_timeout(300)
        await page.keyboard.press("Escape")
    if await page.locator('[class*="DivModalMask"]:visible').count():
        raise RuntimeError("Окно TikTok перекрывает пост; нужен ручной вход или закрытие окна в браузере")


async def expand_caption(post, timeout: int) -> None:
    more = post.get_by_text("more", exact=True)
    if await more.is_visible():
        await more.click(timeout=timeout)
    desc = post.locator('[data-e2e="video-desc"]')
    if not await desc.count():
        return  # У поста может не быть подписи.
    original = await desc.inner_text()
    # AI-сводка TikTok — отдельный сосед подписи, не текст автора.
    await desc.locator("..").locator(':scope > [class*="DivCustomTDKContainer"]').evaluate_all(
        "els => els.forEach(el => el.style.display = 'none')"
    )
    if await desc.inner_text() != original:
        raise RuntimeError("Текст автора изменился при подготовке снимка")
    # ponytail: длинный текст не обрезаем молча; увеличить viewport при таком запросе.
    if await desc.evaluate("""el => {
        const text = el.getBoundingClientRect();
        const post = el.closest('[data-e2e="recommend-list-item-container"]').getBoundingClientRect();
        return el.parentElement.scrollHeight > el.parentElement.clientHeight + 2 ||
               text.top < post.top - 2 || text.bottom > post.bottom + 2;
    }"""):
        raise RuntimeError("Полная подпись не помещается в область поста; нужен снимок с большей высотой")


async def capture_post(page, url: str, destination: Path, timeout: int, *, full_text=False, zoom=None, headless=False) -> Path:
    destination = outside_package(destination)
    response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    if response and response.status >= 400:
        raise RuntimeError(f"TikTok вернул HTTP {response.status}")
    if parse_post_url(page.url)[1] != parse_post_url(url)[1]:
        raise RuntimeError("TikTok открыл другой пост")
    if zoom is not None:
        await verify_zoom(page, zoom, headless=headless)

    post = page.locator('[data-e2e="recommend-list-item-container"]').first
    await post.wait_for(state="visible", timeout=timeout)
    video = post.locator("video").first
    await video.wait_for(state="attached", timeout=timeout)
    await page.wait_for_function(
        "() => { const v = document.querySelector('[data-e2e=\"recommend-list-item-container\"] video'); return v && v.readyState >= 2 && v.videoWidth > 0; }",
        timeout=timeout,
    )

    # Скриншот случайного кадра меняется от запуска к запуску.
    await video.evaluate("""async v => {
        v.pause();
        const second = Math.min(2, Math.max(0, v.duration - 0.1));
        if (Math.abs(v.currentTime - second) > 0.2) {
            v.currentTime = second;
            await Promise.race([
                new Promise(resolve => v.addEventListener('seeked', resolve, {once: true})),
                new Promise(resolve => setTimeout(resolve, 5000))
            ]);
        }
        v.pause();
    }""")
    await page.wait_for_function("""() => {
        const p = document.querySelector('[data-e2e="recommend-list-item-container"]');
        const v = p?.querySelector('video');
        return v && !v.seeking && v.readyState >= 2 &&
               Math.abs(v.currentTime - Math.min(2, Math.max(0, v.duration - 0.1))) < 0.2;
    }""", timeout=timeout)
    # Кадр бывает готов раньше автора и реакций; цифры 0 тоже допустимы.
    await page.wait_for_function("""() => {
        const p = document.querySelector('[data-e2e="recommend-list-item-container"]');
        const avatar = p?.querySelector('[data-e2e="video-author-avatar"] img');
        return avatar?.complete && avatar.naturalWidth > 0 &&
            ['like-count', 'comment-count', 'favorite-count', 'share-count'].every(
                key => p.querySelector(`[data-e2e="${key}"]`)?.innerText.trim().length > 0);
    }""", timeout=timeout)
    await dismiss_overlays(page)
    if full_text:
        await expand_caption(post, timeout)
    await post.evaluate("""async p => {
        await Promise.race([
            Promise.all([document.fonts.ready, ...[...p.querySelectorAll('img')]
                .map(img => img.decode().catch(() => {}))]),
            new Promise(resolve => setTimeout(resolve, 10000))
        ]);
    }""")
    await page.get_by_text("Saved!", exact=True).first.wait_for(state="hidden", timeout=7000)
    await dismiss_overlays(page)
    for overlay in (
        page.get_by_role("button", name="Got it", exact=True),
        page.get_by_role("button", name="Decline optional cookies", exact=True),
        page.locator('[data-e2e="login-modal"]'),
    ):
        if await overlay.is_visible():
            raise RuntimeError("Всплывающее окно TikTok перекрывает пост")
    if await video.evaluate("v => v.readyState < 2 || v.videoWidth === 0"):
        raise RuntimeError("Видео TikTok не загрузилось")
    await video.evaluate("v => v.pause()")

    image = await screenshot(post, type="png", animations="disabled", timeout=timeout)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image)
    return destination.resolve()


@queued
async def run(args) -> int:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

    requests = []
    failed = False
    for value in args.urls:
        try:
            url, post_id = parse_post_url(value)
            requests.append((value, url, post_id))
        except ValueError as error:
            print(json.dumps({"url": value, "ok": False, "error": str(error)}, ensure_ascii=False), flush=True)
            failed = True

    if requests:
        async with async_playwright() as playwright:
            async with launch_browser(playwright, zoom=args.zoom, headless=not args.headed) as browser:
                context = await browser.new_context(viewport={"width": 1280, "height": 900},
                                                    device_scale_factor=2, locale="en-US")
                page = await context.new_page()
                for original, url, post_id in requests:
                    try:
                        suffix = "_full_text" if args.full_text else ""
                        path = await capture_post(page, url, args.output / f"tiktok_{post_id}{suffix}.png",
                                                  args.timeout, full_text=args.full_text, zoom=args.zoom, headless=not args.headed)
                        actual_zoom = await verify_zoom(page,args.zoom,headless=not args.headed)
                        result = {"url": original, "post_id": post_id, "ok": True,
                                  "full_text": args.full_text, "path": str(path), "browser_zoom": actual_zoom,
                                  "zoom_fallback":'native_headless_100' if actual_zoom != args.zoom else None}
                    except Exception as error:
                        message = ("Пост, видео или данные TikTok не загрузились за отведённое время"
                                   if isinstance(error, PWTimeoutError) else str(error))
                        result = {"url": original, "post_id": post_id, "ok": False, "error": message}
                        failed = True
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                await context.close()

    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+", help="Прямые ссылки /@автор/video/ID")
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("REPORT_SKILLS_STATE_DIR", Path.home() / ".local/state/report-skills")) / "outputs/tiktok-screenshots")
    parser.add_argument("--timeout", type=int, default=30000, help="Таймаут в мс")
    parser.add_argument("--full-text", action="store_true", help="Раскрыть всю подпись автора и хэштеги")
    parser.add_argument('--headed',action='store_true',help='Внешний браузер со штатным масштабом')
    add_zoom_argument(parser)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout должен быть положительным")
    try:
        args.output = outside_package(args.output)
        return asyncio.run(run(args))
    except ImportError:
        print(json.dumps({"ok": False, "error": "Установите Playwright из requirements.txt"}), flush=True)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())

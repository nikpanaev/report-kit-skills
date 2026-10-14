#!/usr/bin/env python3
"""Мобильные снимки постов Instagram; stdout: JSON Lines по ссылкам."""
import argparse
import asyncio
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from ui_queue import queued, wait_for_enter
from private_paths import outside_package
from browser_zoom import add_zoom_argument, launch_browser, verify_zoom, screenshot
from urllib.parse import urlsplit

SKILL = Path(__file__).resolve().parents[1]
NEXT = re.compile(r"^(Далее|Next)$")


def parse_post_url(value):
    parsed = urlsplit(value.strip() if "://" in value else "https://" + value.strip())
    if (parsed.scheme not in {"http", "https"} or parsed.username or parsed.password
            or parsed.port or parsed.hostname not in
            {"instagram.com", "www.instagram.com", "m.instagram.com"}):
        raise ValueError("Нужна ссылка на пост instagram.com/p/ или instagram.com/reel/")
    match = re.fullmatch(r"/(p|reel)/([A-Za-z0-9_-]{1,64})/?", parsed.path)
    if not match:
        raise ValueError("Нужна ссылка на конкретный пост /p/SHORTCODE/ или /reel/SHORTCODE/")
    kind, code = match.groups()
    return f"https://www.instagram.com/{kind}/{code}/", kind, code


def frame_time(duration, requested):
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("Длительность видео недоступна")
    return min(requested, max(0, duration - 0.05))


async def dismiss_prompt(page):
    continuation = page.get_by_text(re.compile(r"^(Продолжить на сайте|Continue on web)$"))
    if await continuation.count() and await continuation.first.is_visible():
        await continuation.first.click()
    close = page.get_by_role("img", name=re.compile(r"^(Закрыть|Close)$"))
    if await close.count() and await close.first.is_visible():
        await close.first.click()


async def open_native(page, url, timeout):
    response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    if response and response.status >= 400:
        raise RuntimeError(f"Instagram вернул HTTP {response.status}")
    # Баннер приложения появляется после первого рендера страницы.
    await page.wait_for_timeout(1500)
    await dismiss_prompt(page)


async def ready_media(page, selector, timeout):
    await page.locator(selector).wait_for(state="visible", timeout=timeout)
    await page.wait_for_function("""selector => {
        const root = document.querySelector(selector);
        if (!root) return false;
        const bounds = root.getBoundingClientRect();
        const active = [...root.querySelectorAll('img, video')].filter(e => {
            const r = e.getBoundingClientRect(), center = r.x + r.width / 2;
            return r.width > 0 && r.height > 0 && center > bounds.x && center < bounds.right;
        });
        const media = active.filter(e => e.getBoundingClientRect().width > 150);
        return media.length > 0 && active.every(e => e.tagName === 'VIDEO'
            ? e.readyState >= 2 : e.complete && e.naturalWidth > 0);
    }""", arg=selector, timeout=timeout)
    await page.locator(selector).evaluate("""root => {
        const bounds = root.getBoundingClientRect();
        for (const v of root.querySelectorAll('video')) {
            v.removeAttribute('data-ig-active-video');
            const r = v.getBoundingClientRect(), center = r.x + r.width / 2;
            if (r.width > 150 && center > bounds.x && center < bounds.right)
                v.setAttribute('data-ig-active-video', '');
        }
    }""")
    await page.evaluate("() => document.fonts.ready")


async def seek_video(page, video, seconds, timeout):
    await page.wait_for_function("""() => [...document.querySelectorAll('[data-ig-active-video]')]
        .some(v => v.readyState >= 2 && Number.isFinite(v.duration) && v.duration > 0)
    """, timeout=timeout)
    target = frame_time(await video.evaluate("v => v.duration"), seconds)
    await video.evaluate("""async (v, target) => {
        v.muted = true;
        v.pause();
        if (Math.abs(v.currentTime - target) > 0.005) {
            await new Promise((resolve, reject) => {
                const timer = setTimeout(() => reject(new Error('Не удалось выбрать кадр видео')), 10000);
                v.addEventListener('seeked', () => {clearTimeout(timer);resolve();}, {once:true});
                v.currentTime = target;
            });
        }
        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
        if (v.seeking || v.readyState < 2 || Math.abs(v.currentTime - target) > 0.1)
            throw new Error('Кадр видео не готов');
    }""", target)
    return await video.evaluate("v => v.currentTime")


async def save(target, path, timeout, zoom=None):
    if zoom is not None:
        await verify_zoom(target.page, zoom, mobile=True)
    await target.evaluate("""target => {
        for (const e of document.body.querySelectorAll('*')) {
            if (!e.contains(target) && !target.contains(e) &&
                ['fixed', 'sticky'].includes(getComputedStyle(e).position))
                e.style.setProperty('visibility', 'hidden', 'important');
        }
    }""")
    await screenshot(target, path=str(path), animations="disabled", timeout=timeout)


async def open_embed(page, url, timeout):
    response = await page.goto(url + "embed/captioned/", wait_until="domcontentloaded", timeout=timeout)
    if response and response.status >= 400:
        raise RuntimeError(f"Встроенный вид Instagram вернул HTTP {response.status}")
    await page.locator(".Embed .Content").wait_for(state="visible", timeout=timeout)
    await page.evaluate("""() => {
        let meta = document.querySelector('meta[name="viewport"]');
        if (!meta) {meta = document.createElement('meta'); meta.name = 'viewport'; document.head.append(meta);}
        meta.content = 'width=device-width, initial-scale=1';
    }""")
    await page.add_style_tag(content="""
        .HeaderCta, .PrimaryCTA, .Footer, .CaptionComments, .HoverCard,
        .WatchOnInstagramContainer {display:none!important}
    """)


async def capture_reel(page, url, args, folder, prefix):
    await open_native(page, url, args.timeout)
    video = page.locator("video:visible").first
    await video.wait_for(timeout=args.timeout)
    await video.evaluate("v => v.setAttribute('data-ig-active-video', '')")
    seconds = await seek_video(page, video, args.video_seconds, args.timeout)
    if args.full_text:
        source = await video.evaluate("v => v.currentSrc")
        if not source.startswith("https://"):
            raise RuntimeError("Для полного Reel недоступен перенос видео в карточку; снимите обычный режим")
        await open_embed(page, url, args.timeout)
        # Реальная дорожка того же Reel: обложка embed не является кадром на нужной секунде.
        await page.locator(".EmbeddedMediaImage").first.evaluate("""(img, source) => {
            const v = document.createElement('video');
            v.src = source; v.muted = true; v.playsInline = true; v.preload = 'auto';
            v.setAttribute('data-ig-active-video', '');
            v.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:contain';
            img.replaceWith(v);
        }""", source)
        video = page.locator("[data-ig-active-video]")
        seconds = await seek_video(page, video, args.video_seconds, args.timeout)
        await video.evaluate("""v => {
            v.closest('.Content').style.paddingBottom = `${v.videoHeight / v.videoWidth * 100}%`;
        }""")
        target = page.locator(".Embed")
        await ready_media(page, ".Embed", args.timeout)
    else:
        signup = page.get_by_text(re.compile(r"^(Зарегистрируйтесь в Instagram|Sign up for Instagram)$"))
        if await signup.count():
            await signup.evaluate_all("es => es.forEach(e => e.style.setProperty('visibility','hidden','important'))")
        app_link = page.get_by_text(re.compile(r"^(Открыть приложение|Open app)$"))
        if await app_link.count():
            await app_link.first.evaluate("""e => {
                while (e.parentElement && e.parentElement !== document.body &&
                       !e.parentElement.querySelector('video')) e = e.parentElement;
                e.style.setProperty('visibility', 'hidden', 'important');
            }""")
        target = video.locator("..")
        await page.evaluate("() => document.fonts.ready")
    name = f"{prefix}_01.png"
    await save(target, folder / name, args.timeout, getattr(args, 'zoom', None))
    return [name], [seconds]


async def capture_post(page, url, args, folder, prefix):
    if args.full_text:
        await open_embed(page, url, args.timeout)
        if (await page.locator(".WatchOnInstagramContainer").count()
                and not await page.locator(".EmbedSidecar").count()):
            return await capture_reel(page, url, args, folder, prefix)
        selector = ".Embed"
    else:
        await open_native(page, url, args.timeout)
        selector = "article"
    target = page.locator(selector).first
    names, times = [], []
    # ponytail: guard against stuck Next; raise instead of returning an incomplete carousel.
    for number in range(1, 101):
        await dismiss_prompt(page)
        await ready_media(page, selector, args.timeout)
        video = target.locator("[data-ig-active-video]").first
        seconds = (await seek_video(page, video, args.video_seconds, args.timeout)
                   if await video.count() else None)
        if await target.locator(".WatchOnInstagramContainer").count() and seconds is None:
            raise RuntimeError("Встроенный вид содержит только обложку видео; снимите обычный режим")
        # Ссылки на обсуждение не являются текстом публикации.
        await target.get_by_text(re.compile(
            r"^(?:Посмотреть|Смотреть) все комментарии.*$|^View all .*comments$"
        )).evaluate_all("es => es.forEach(e => e.style.setProperty('display','none','important'))")
        await target.locator('li:has(a[href*="/c/"])').evaluate_all(
            "es => es.forEach(e => e.style.setProperty('display','none','important'))")
        name = f"{prefix}_{number:02}.png"
        await save(target, folder / name, args.timeout, getattr(args, 'zoom', None))
        names.append(name)
        times.append(seconds)
        next_button = target.get_by_role("button", name=NEXT, exact=True)
        if not args.all_images or not await next_button.count() or not await next_button.first.is_visible():
            return names, times
        if number == 100:
            raise RuntimeError("Карусель не завершилась; неполный пакет не сохранён")
        await next_button.first.click(timeout=args.timeout)
        await page.wait_for_timeout(600)


def emit(**result):
    print(json.dumps(result, ensure_ascii=False), flush=True)


@queued
async def run(args):
    args.state = outside_package(args.state)
    args.output = outside_package(args.output)
    from playwright.async_api import async_playwright

    requests, failed = [], False
    for original in args.urls:
        try:
            url, kind, code = parse_post_url(original)
            requests.append((original, url, kind, code))
        except ValueError as error:
            emit(url=original, ok=False, error=str(error))
            failed = True
    if not requests and not args.login:
        return 1
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else None
    async with async_playwright() as p:
        async with launch_browser(p, zoom=args.zoom, headless=not (args.headed or args.login), mobile=True) as browser:
            context = await browser.new_context(
                **{**p.devices["iPhone 13"], "viewport": {"width": 390, "height": 844},
                   "device_scale_factor": 2}, locale="ru-RU", color_scheme="light", storage_state=state)
            page = await context.new_page()
            if args.login:
                await page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
                await wait_for_enter('Войдите в открытом браузере, затем нажмите Enter здесь.')
                await page.reload(wait_until="domcontentloaded", timeout=args.timeout)
                if not any(cookie["name"] == "sessionid" for cookie in await context.cookies("https://www.instagram.com")):
                    raise RuntimeError("Вход Instagram не подтверждён после получения очереди")
                args.state.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", dir=args.state.parent,
                                                 encoding="utf-8", delete=False) as saved:
                    json.dump(await context.storage_state(indexed_db=True), saved)
                    saved_path = Path(saved.name)
                saved_path.chmod(0o600)
                os.replace(saved_path, args.state)
                emit(ok=True, state=str(args.state.resolve()))
            args.output.mkdir(parents=True, exist_ok=True)
            mode = ("carousel" if args.all_images else "preview") + ("_full" if args.full_text else "")
            for original, url, kind, code in requests:
                try:
                    prefix = f"ig_{code}_{mode}"
                    # Only publish files after every requested slide was captured.
                    with tempfile.TemporaryDirectory(prefix=".ig-", dir=args.output) as temporary:
                        capture = capture_reel if kind == "reel" else capture_post
                        names, times = await capture(page, url, args, Path(temporary), prefix)
                        actual_zoom = await verify_zoom(page, args.zoom, mobile=True)
                        paths = []
                        for name in names:
                            destination = args.output / name
                            os.replace(Path(temporary) / name, destination)
                            paths.append(str(destination.resolve()))
                    emit(url=original, post_id=code, ok=True, paths=paths, frame_times=times,
                         mode=mode, layout="instagram-embed" if args.full_text else "mobile-native",
                         browser_zoom=actual_zoom,
                         zoom_fallback='native_mobile_100' if actual_zoom != args.zoom else None)
                except Exception as error:
                    emit(url=original, ok=False, error=f"{error}. Проверьте доступ; может понадобиться --login")
                    failed = True
            await context.close()

    return int(failed)


def seconds(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("Нужно конечное неотрицательное число секунд")
    return number


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Нужно положительное число")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*")
    parser.add_argument("--all-images", action="store_true")
    parser.add_argument("--full-text", action="store_true")
    parser.add_argument("--video-seconds", type=seconds, default=4.0)
    state_root = Path(os.environ.get("REPORT_SKILLS_STATE_DIR", Path.home() / ".local/state/report-skills"))
    parser.add_argument("--output", type=Path, default=state_root / "outputs/instagram-screenshots")
    parser.add_argument("--state", type=Path, default=state_root / "instagram-session.json")
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--timeout", type=positive_int, default=30000)
    add_zoom_argument(parser)
    args = parser.parse_args()
    if not args.urls and not args.login:
        parser.error("Передайте ссылки на посты или --login")
    try:
        args.state = outside_package(args.state)
        args.output = outside_package(args.output)
        return asyncio.run(run(args))
    except Exception as error:
        emit(ok=False, error=str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

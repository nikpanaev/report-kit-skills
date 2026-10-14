#!/usr/bin/env python3
"""Снимки конкретных постов VK. stdout: один JSON-результат на ссылку."""

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from contextlib import AsyncExitStack
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from ui_queue import queued, wait_for_enter
from private_paths import outside_package
from browser_zoom import add_zoom_argument, launch_browser, verify_zoom, screenshot
from urllib.parse import parse_qs, urlsplit

VIDEO_ATTACHMENTS = '.VideoPrimaryAttachment, [data-testid="primary-attachment-video"], [data-testid^="clip-attachment-"]'
ATTACHMENT_ROOTS = '[data-testid="primary-attachment"], [data-testid="primary-attachment-photo"], ' + VIDEO_ATTACHMENTS + ', a.page_post_thumb_wrap'
NAVIGATION_DELAY = 5
RATE_LIMIT_MESSAGE = 'VK: Too many requests per second; пакет остановлен без повторов. Повторите позже.'


def parse_post_url(value: str, *, preserve_reply=False) -> tuple[str, str]:
    value = value.strip()
    parsed = urlsplit(value if "://" in value else "https://" + value)
    if (parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"vk.ru", "vk.com", "www.vk.ru", "www.vk.com",
                                       "m.vk.ru", "m.vk.com"}
            or parsed.username or parsed.password or parsed.port):
        raise ValueError("Нужна ссылка на пост vk.ru или vk.com")
    query = parse_qs(parsed.query)
    candidates = [query[key][0].split("/")[0] for key in ("w", "z") if key in query]
    candidates.append(parsed.path.strip("/"))
    for candidate in candidates:
        match = re.fullmatch(r"wall(-?[1-9]\d*_[1-9]\d*)", candidate)
        if match:
            post_id = match[1]
            canonical = f"https://vk.ru/wall{post_id}"
            reply = query.get('reply', []) if preserve_reply else []
            if reply and re.fullmatch(r'[1-9]\d*', reply[0]):
                canonical += '?reply=' + reply[0]
            return canonical, post_id
    raise ValueError("В ссылке должен быть ID поста: wall-1_2")


async def post_theme(post):
    return await post.evaluate("""post => {
        const rgb = value => value.match(/[\\d.]+/g)?.map(Number) || [];
        const foreground = rgb(getComputedStyle(post).color);
        let background;
        for (let el = post; el; el = el.parentElement) {
            const color = rgb(getComputedStyle(el).backgroundColor);
            if (color.length === 3 || color[3] === 1) { background = color; break; }
        }
        if (!background) {
            const dark = document.body.getAttribute('scheme') === 'vkcom_dark' ||
                getComputedStyle(document.documentElement).colorScheme === 'dark';
            background = dark ? [0, 0, 0] : [255, 255, 255];
        }
        const brightness = c => .2126*c[0] + .7152*c[1] + .0722*c[2];
        return {light: brightness(background) >= 180 &&
                brightness(background) - brightness(foreground) >= 80,
                background: background.slice(0, 3), foreground: foreground.slice(0, 3)};
    }""")


async def ensure_light_theme(post, timeout):
    proof = await post_theme(post)
    if proof['light']:
        return proof
    page = post.page
    await page.locator('[data-testid=header-profile-menu-button]').click(timeout=timeout)
    row = page.get_by_text(re.compile(r'^Тема:\s*(Системная|Тёмная|Темная|Светлая)$')).last
    await row.get_by_text(re.compile(r'^(Системная|Тёмная|Темная|Светлая)$')).click(timeout=timeout)
    await page.get_by_text('Светлая', exact=True).last.click(timeout=timeout)
    deadline = asyncio.get_running_loop().time() + timeout / 1000
    while True:
        proof = await post_theme(post)
        if proof['light']:
            return proof
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError('VK: светлая тема карточки не подтверждена; PNG не сохранён')
        await asyncio.sleep(.05)


async def screenshot_ready(post, target, timeout, style, *, verify_videos=True, video_attachments=None):
    await ensure_light_theme(post, timeout)
    guards = []
    try:
        attachments = (video_attachments if video_attachments is not None else
                       await post.locator(VIDEO_ATTACHMENTS).all() if verify_videos else [])
        for attachment in attachments:
            await attachment.scroll_into_view_if_needed(timeout=timeout)
            clip = await attachment.evaluate('el => el.matches("[data-testid^=clip-attachment-]")')
            video = attachment.locator('video' if clip else 'video.videoplayer_media_provider, video.player-media').first
            if not clip and not await video.count():
                await attachment.click(timeout=timeout)
            await video.wait_for(state="visible", timeout=timeout)
            guard = await video.evaluate_handle("""async (video, timeout) => {
                const stop = () => video.pause();
                const wait = event => Promise.race([
                    new Promise(resolve => video.addEventListener(event, resolve, {once: true})),
                    new Promise((_, reject) => setTimeout(() => reject(Error(`Видео: ${event} не наступил`)), timeout))
                ]);
                try {
                    if (video.readyState < 2) await wait('loadeddata');
                    // Metadata-only clips need their initial native playback to decode first.
                    video.addEventListener('play', stop);
                    if (!Number.isFinite(video.duration) || video.duration <= 0)
                        throw Error('Видео: длительность не определена');
                    const frameTime = video.duration > 3 ? 3 : video.duration > 2 ? 2 : video.duration / 2;
                    stop();
                    if (Math.abs(video.currentTime - frameTime) > 0.001 || video.seeking) {
                        const sought = wait('seeked');
                        video.currentTime = frameTime;
                        await sought;
                    }
                    stop();
                    if (video.readyState < 2 || !video.videoWidth || video.seeking || !video.paused ||
                        Math.abs(video.currentTime - frameTime) > 0.2) throw Error(`Видеокадр на ${frameTime} с не готов`);
                    const canvas = document.createElement('canvas');
                    canvas.width = canvas.height = 32;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(video, 0, 0, 32, 32);
                    const pixels = ctx.getImageData(0, 0, 32, 32).data;
                    if (!pixels.some((v, i) => i % 4 !== 3 && v > 8))
                        throw Error(`Видео: кадр на ${frameTime} с чёрный; снимок не сохранён`);
                    await new Promise(requestAnimationFrame);
                    return {video, stop};
                } catch (error) {
                    video.removeEventListener('play', stop);
                    throw error;
                }
            }""", timeout)
            guards.append(guard)
        # VK can insert a login banner after the player starts loading.
        await post.evaluate("""post => {
            for (const el of document.body.querySelectorAll('*')) {
                if (!el.contains(post) && !post.contains(el) &&
                    ['fixed', 'sticky'].includes(getComputedStyle(el).position)) {
                    el.setAttribute('data-vk-screenshot-overlay', '');
                }
            }
        }""")
        proof = await post_theme(post)
        if not proof['light']:
            raise RuntimeError('VK: тема карточки изменилась; PNG не сохранён')
        post.page._vk_screenshot_theme = proof
        return await screenshot(target, type="png", animations="disabled", timeout=timeout,
            style='.PageBottomBanner { visibility: hidden !important; } ' + style)
    finally:
        for guard in guards:
            await guard.evaluate('({video, stop}) => video.removeEventListener("play", stop)')
            await guard.dispose()


async def find_post(page, post_id, timeout):
    # Не выбираем первый .post: рядом может быть другой пост или репост.
    selector = (f'#post{post_id}:visible, .post[data-post-id="{post_id}"]:visible, '
                f'.post[data-postid="{post_id}"]:visible, '
                f'[data-testid="post"][data-post-id="{post_id}"]:visible')
    post = page.locator(selector).first
    await post.wait_for(state="visible", timeout=timeout)
    return post


async def capture_all_visuals(page, post_id, output, timeout):
    post = await find_post(page, post_id, timeout)
    # Only real attachment roots; avatars, emoji, previews and comments are not materials.
    roots = post.locator(ATTACHMENT_ROOTS)
    deadline = asyncio.get_running_loop().time() + timeout / 1000
    while True:
        indexes = await roots.evaluate_all("""(els, roots) => els.map((el, index) => ({el, index})).filter(({el}) => {
            if (el.parentElement.closest(roots)) return false;
            if (el.closest('.replies_wrap, .replies_list, [id^="replies_wrap"]')) return false;
            const post = el.closest('[data-testid="post"], .post');
            const date = post?.querySelector('[data-testid="post_date_block_preview"]');
            const footer = date && [...post.children].find(child => child.contains(date));
            for (let next = footer?.nextElementSibling; next; next = next.nextElementSibling)
                if (next.contains(el)) return false;
            return true;
        }).map(({index}) => index)""", ATTACHMENT_ROOTS)
        if indexes or asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(0.05)
    counter = post.locator('[data-testid="carousel-counter"]').first
    gallery = post.locator('[data-testid="gallery"]').first
    total = None
    if await counter.count():
        match = re.fullmatch(r'\s*(\d+)\s*/\s*(\d+)\s*', await counter.inner_text())
        if not match:
            raise RuntimeError('Не удалось прочитать число материалов карусели')
        total = int(match[2])
        if int(match[1]) != 1:
            raise RuntimeError('Карусель открыта не на первом материале')
    expected = total if total is not None else len(indexes)
    items = []
    seen = set()
    for order, index in enumerate(indexes, 1):
        material = roots.nth(index)
        item = dict(order=order, type=None, material_id=None, ok=False, path=None)
        try:
            info = await material.evaluate("""(el, selector) => {
                const video = el.matches(selector) ? el : el.querySelector(selector);
                const links = [el, ...el.querySelectorAll('a')].map(a => a.getAttribute('href') || '');
                const id = links.map(href => href.match(video ? /video(-?\\d+_\\d+)/ : /photo(-?\\d+_\\d+)/)).find(Boolean);
                const dataVideo = el.querySelector('[data-video]')?.getAttribute('data-video');
                const clip = video?.dataset.testid?.match(/^clip-attachment-(-?\\d+_\\d+)$/);
                return {type: video ? 'video' : 'photo', material_id: id ? (video ? 'video' : 'photo') + id[1] : clip ? 'video' + clip[1] : dataVideo ? 'video' + dataVideo : null};
            }""", VIDEO_ATTACHMENTS)
            item.update(info)
            if not info['material_id']:
                raise RuntimeError('Не определён VK ID материала; неподдерживаемый тип или разметка')
            if info['material_id'] in seen:
                raise RuntimeError('Повторный ID материала; дубликат не сохранён')
            seen.add(info['material_id'])
            if total is not None:
                if order > 1:
                    await gallery.locator('button[class*="arrowEnd"]').click(timeout=timeout)
                await counter.page.wait_for_function("""([postId, order, total]) => {
                    const post = [...document.querySelectorAll('[data-testid="post"], .post')]
                        .find(el => el.dataset.postId === postId || el.id === 'post' + postId);
                    return post?.querySelector('[data-testid="carousel-counter"]')?.textContent.trim() === `${order}/${total}`;
                }""", arg=[post_id, order, total], timeout=timeout)
            if info['type'] == 'video':
                target = material
                video_root = (material if await material.evaluate('(el, selector) => el.matches(selector)', VIDEO_ATTACHMENTS) else
                              material.locator(VIDEO_ATTACHMENTS).first)
                video_attachments = [video_root]
            else:
                image = material.locator('img').first
                target = image if await image.count() else material
                if await image.count():
                    await image.evaluate("async img => { img.loading = 'eager'; await img.decode(); }")
                else:
                    await material.evaluate(r"""async el => {
                        const match = getComputedStyle(el).backgroundImage.match(/^url\(["']?(.*?)["']?\)$/);
                        if (!match) throw Error('Изображение материала отсутствует');
                        const image = new Image(); image.src = match[1]; await image.decode();
                    }""")
                video_attachments = []
            await target.scroll_into_view_if_needed(timeout=timeout)
            png = await screenshot_ready(post, target, timeout,
                '[data-vk-screenshot-overlay] { visibility: hidden !important; } '
                '[data-testid="carousel-counter"], [class*="CarouselBase__arrow"] { visibility: hidden !important; }',
                video_attachments=video_attachments)
            destination = output / f'vk_visual_{post_id}_{order:02d}_{info["material_id"]}.png'
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(png)
            item.update(ok=True, path=str(destination.resolve()))
        except Exception as error:
            item['error'] = str(error).splitlines()[0]
        items.append(item)
    obtained = sum(item['ok'] for item in items)
    result = dict(expected_count=expected, obtained_count=obtained, materials=items,
                  ok=expected > 0 and expected == obtained == len(items))
    if not result['ok']:
        result['error'] = f'Неполная выгрузка: получено {obtained} из {expected}; обнаружено {len(items)} материалов'
    return result


async def capture_post(page, post_id: str, destination: Path, timeout: int, *,
                       expand_text=True, comments_only=False, visual_only=False) -> Path:
    post = await find_post(page, post_id, timeout)
    if visual_only:
        video_attachment = post.locator(VIDEO_ATTACHMENTS).first
        if await video_attachment.count():
            target = video_attachment
        else:
            images = post.locator('img')
            boxes = [(image, await image.bounding_box()) for image in await images.all()]
            candidates = [(image, box['width'] * box['height']) for image, box in boxes
                          if box and box['width'] >= 200 and box['height'] >= 100]
            if not candidates:
                raise RuntimeError('В посте нет видимого изображения или видео')
            target = max(candidates, key=lambda item: item[1])[0]
            if not await target.evaluate('img => img.complete && img.naturalWidth > 0'):
                await target.evaluate("""async img => {
                    img.loading = 'eager';
                    await img.decode();
                }""")
        await target.scroll_into_view_if_needed(timeout=timeout)
        image = await screenshot_ready(post, target, timeout,
                                        "[data-vk-screenshot-overlay] { visibility: hidden !important; }")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(image)
        return destination.resolve()
    if comments_only:
        from playwright.async_api import TimeoutError as PWTimeoutError

        try:
            if await post.evaluate("el => el.classList.contains('post')"):
                post = post.locator(f'#replies{post_id}, .replies_list').first
                await post.wait_for(state="attached", timeout=timeout)
                await post.locator('.reply:visible').first.wait_for(timeout=timeout)
            else:
                post = post.locator('[data-testid="wall_comments_layout_root"]').first
                await post.wait_for(state="visible", timeout=timeout)
                await post.locator('[data-testid="wall_comments_comment_root"], '
                                   '[data-testid="wall_comments_comment_in_thread"]').first.wait_for(timeout=timeout)
            await post.evaluate("el => el.scrollIntoView({block: 'start'})")
        except PWTimeoutError as error:
            raise RuntimeError("Нет отображённых комментариев: они отсутствуют, "
                               "не загрузились или недоступны без входа") from error
    elif await post.evaluate("el => !el.classList.contains('post')"):
        # SPA-версия VK кладёт комментарии отдельными соседями после футера поста.
        await post.locator('[data-testid="post_date_block_preview"]').first.wait_for(timeout=timeout)
        await post.evaluate("""post => {
            const date = post.querySelector('[data-testid="post_date_block_preview"]');
            const footer = [...post.children].find(child => child.contains(date));
            for (let el = footer.nextElementSibling; el; el = el.nextElementSibling) {
                el.setAttribute('data-vk-screenshot-comment', '');
            }
        }""")
    # В VK комментарии и форма ответа находятся внутри самого .post.
    await post.locator(
        ('.reply_box_wrap, .reply_fakebox_wrap, [id^="reply_box_wrap"], [id^="reply_fakebox_wrap"]'
         if comments_only else
         '.replies_wrap, .replies_list, .reply_box_wrap, .reply_fakebox_wrap, '
         '[id^="replies_wrap"], [id^="reply_box_wrap"], [id^="reply_fakebox_wrap"]')
    ).evaluate_all("els => els.forEach(el => el.setAttribute('data-vk-screenshot-comment', ''))")
    more = post.locator(".wall_post_more:not([data-vk-screenshot-comment] *)").first
    if expand_text and not comments_only and await more.is_visible():
        await more.click(timeout=timeout)
    await post.scroll_into_view_if_needed(timeout=timeout)
    ready = await post.evaluate("""async el => {
        const images = [...el.querySelectorAll('img')]
            .filter(img => !img.closest('[data-vk-screenshot-comment]'));
        images.forEach(img => img.loading = 'eager');
        await Promise.race([
            Promise.all([document.fonts.ready, ...images.map(img => img.decode().catch(() => {}))]),
            new Promise(resolve => setTimeout(resolve, 10000))
        ]);
        return images.every(img => img.complete && img.naturalWidth > 0);
    }""")
    if not ready:
        raise RuntimeError("Не все изображения поста загрузились; снимок не сохранён")
    hidden_comments = await post.evaluate_handle("""post =>
        [...post.querySelectorAll('[data-vk-screenshot-comment]')].map(el => {
            const style = el.getAttribute('style');
            el.style.setProperty('display', 'none', 'important');
            return [el, style];
        })
    """)
    collapsed_text = None
    try:
        if not expand_text:
            # По прямой ссылке текст уже раскрыт; свернуть только текст, до расчёта PNG bounds.
            collapsed_text = await post.evaluate_handle("""post =>
                [...post.querySelectorAll('.wall_post_text_wrapper, .wall_post_text, [data-testid="post_text"]')]
                .map(el => el.querySelector('.vkitInternalFeedShowMoreTextTextClamp') || el)
                .filter(el => !el.querySelector('img, video') &&
                              !el.closest('[data-vk-screenshot-comment]'))
                .map(el => {
                    const style = el.getAttribute('style');
                    el.style.setProperty('display', '-webkit-box', 'important');
                    el.style.setProperty('-webkit-box-orient', 'vertical', 'important');
                    el.style.setProperty('-webkit-line-clamp', '3', 'important');
                    el.style.setProperty('max-height', 'none', 'important');
                    el.style.setProperty('overflow', 'hidden', 'important');
                    return [el, style];
                })
            """)
        image = await screenshot_ready(post, post, timeout,
            verify_videos=not comments_only,
            style=("[data-vk-screenshot-overlay] { visibility: hidden !important; } "
                   + ("[data-testid='show_prev_comments'], [data-testid='show_next_comments'] "
                      "{ display: none !important; }" if comments_only else
                      "[data-testid='post'] > :has([data-testid='post_date_block_preview']) ~ * "
                      "{ display: none !important; }")),
        )
    finally:
        for handle in (hidden_comments, collapsed_text):
            if handle is not None:
                await handle.evaluate("""items => items.forEach(([el, style]) => {
                    if (style === null) el.removeAttribute('style');
                    else el.setAttribute('style', style);
                })""")
                await handle.dispose()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image)
    return destination.resolve()


def emit(**result):
    print(json.dumps(result, ensure_ascii=False), flush=True)


@queued
async def run(args) -> int:
    from playwright.async_api import async_playwright, Error, TimeoutError as PWTimeoutError

    failed = False
    requests = []
    for url in args.urls:
        try:
            canonical, post_id = parse_post_url(url, preserve_reply=args.comments_only)
            requests.append((url, canonical, post_id))
        except ValueError as error:
            emit(url=url, ok=False, error=str(error))
            failed = True
    if not requests and not args.login:
        return 1

    state = None
    if not args.cdp and args.state.exists():
        state = json.loads(args.state.read_text(encoding="utf-8"))
    async with async_playwright() as playwright:
        async with AsyncExitStack() as cleanup:
            if args.cdp:
                browser = await playwright.chromium.connect_over_cdp(args.cdp, no_defaults=True, timeout=args.timeout)
                if not browser.contexts:
                    raise RuntimeError('В сохранённом браузере нет доступного контекста')
                context = browser.contexts[0]
            else:
                browser = await cleanup.enter_async_context(launch_browser(
                    playwright, zoom=args.zoom, headless=not (args.headed or args.login)))
                context = await browser.new_context(
                    storage_state=state, viewport={"width": 1280, "height": 900},
                    locale="ru-RU", device_scale_factor=2, color_scheme="light",
                )
                cleanup.push_async_callback(context.close)
            page = await context.new_page()
            cleanup.push_async_callback(page.close)
            if args.cdp:
                await page.bring_to_front()
            rate_limited = False
            def note_response(response):
                nonlocal rate_limited
                if response.status == 429:
                    rate_limited = True
            page.on('response', note_response)
            async def limit_detected():
                nonlocal rate_limited
                rate_limited = rate_limited or await page.get_by_text(
                    re.compile('Too many requests per second', re.I)).first.is_visible()
                return rate_limited
            if args.login:
                await page.goto("https://vk.ru", wait_until="domcontentloaded", timeout=args.timeout)
                if await limit_detected():
                    raise RuntimeError(RATE_LIMIT_MESSAGE)
                await wait_for_enter('Войдите в VK в открытом браузере. Затем нажмите Enter здесь.')
                await page.reload(wait_until="domcontentloaded", timeout=args.timeout)
                await page.locator("[data-testid=header-profile-menu-button]").wait_for(state="visible", timeout=args.timeout)
                args.state.parent.mkdir(parents=True, exist_ok=True)
                # Сессия сохраняется атомарно, файл доступен только владельцу.
                with tempfile.NamedTemporaryFile(mode="w", dir=args.state.parent,
                                                 encoding="utf-8", delete=False) as saved:
                    json.dump(await context.storage_state(indexed_db=True), saved)
                os.replace(saved.name, args.state)
                emit(ok=True, state=str(args.state.resolve()))

            for original, url, post_id in requests:
                counts = dict(expected_count=None, obtained_count=0, materials=[]) if args.all_visuals else {}
                if rate_limited:
                    emit(url=original, post_id=post_id, ok=False, rate_limited=True,
                         error=RATE_LIMIT_MESSAGE, **counts)
                    failed = True
                    continue
                prefix = "vk_comments" if args.comments_only else "vk_visual" if args.visual_only else "vk"
                destination = args.output / f"{prefix}_{post_id}.png"
                for attempt in range(args.retries):
                    stage = "preflight"
                    try:
                        # Also space separate CLI launches, not only links within one batch.
                        await asyncio.sleep(NAVIGATION_DELAY)
                        if await limit_detected():
                            raise RuntimeError(RATE_LIMIT_MESSAGE)
                        stage = "navigation"
                        response = await page.goto(url, wait_until="domcontentloaded",
                                                   timeout=args.timeout)
                        if await limit_detected():
                            raise RuntimeError(RATE_LIMIT_MESSAGE)
                        if response and response.status >= 400:
                            raise RuntimeError(f"VK вернул HTTP {response.status}. "
                                               "Попробуйте --headed или вход через --login")
                        stage = "browser_setup"
                        if args.cdp:
                            await page.locator('[data-testid=header-profile-menu-button]').wait_for(
                                state='visible', timeout=min(args.timeout, 10000))
                        actual_zoom = await verify_zoom(page, args.zoom, headless=not (args.headed or args.login or args.cdp))
                        zoom_fallback = 'native_headless_100' if actual_zoom != args.zoom else None
                        stage = "capture"
                        if args.all_visuals:
                            result = await capture_all_visuals(page, post_id, args.output, args.timeout)
                            limit_info = dict(rate_limited=True) if await limit_detected() else {}
                            emit(url=original, post_id=post_id, browser_zoom=actual_zoom,
                                 zoom_fallback=zoom_fallback, theme=getattr(page, '_vk_screenshot_theme', None),
                                 **result, **limit_info)
                            failed = failed or not result['ok'] or rate_limited
                            break
                        path = await capture_post(page, post_id, destination, args.timeout,
                                                  expand_text=not args.collapsed_text,
                                                  comments_only=args.comments_only,
                                                  visual_only=args.visual_only)
                        limit_info = dict(rate_limited=True) if await limit_detected() else {}
                        emit(url=original, post_id=post_id, ok=True, path=str(path),
                             browser_zoom=actual_zoom, zoom_fallback=zoom_fallback,
                             theme=page._vk_screenshot_theme, **limit_info)
                        failed = failed or rate_limited
                        break
                    except (Error, RuntimeError, OSError) as error:
                        if await limit_detected():
                            emit(url=original, post_id=post_id, ok=False, rate_limited=True,
                                 error=RATE_LIMIT_MESSAGE, **counts)
                            failed = True
                            break
                        if attempt + 1 < args.retries:
                            print(f"{post_id}: повтор {attempt + 2}/{args.retries} "
                                  f"(stage={stage}, error_type={type(error).__name__})",
                                  file=sys.stderr, flush=True)
                            await asyncio.sleep(2)
                        else:
                            message = (f"Таймаут при съёмке {post_id}: {error}"
                                       if isinstance(error, PWTimeoutError) else str(error))
                            emit(url=original, post_id=post_id, ok=False, error=message, **counts)
                            failed = True

    return int(failed)


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Нужно положительное число")
    return number


def main(*, description=__doc__) -> int:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("urls", nargs="*", help="Ссылки wallOWNER_POST или ?w=wallOWNER_POST")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state", type=Path,
                        default=Path(os.environ.get("REPORT_SKILLS_STATE_DIR", Path.home() / ".local/state/report-skills")) / "vk-session.json",
                        help="Сессия Playwright; по умолчанию общая для этого skill")
    parser.add_argument("--login", action="store_true", help="Войти вручную и сохранить сессию")
    parser.add_argument("--headed", action="store_true", help="Показать окно браузера")
    parser.add_argument("--cdp", help="Использовать сохранённую авторизованную внешнюю VK-сессию по локальному CDP")
    parser.add_argument("--comments-only", action="store_true", help="Снять только загруженные комментарии")
    parser.add_argument("--visual-only", action="store_true", help="Снять только изображение или проверенный видеокадр")
    parser.add_argument("--all-visuals", action="store_true", help="Снять каждый материал поста отдельно, в исходном порядке")
    parser.add_argument("--collapsed-text", action="store_true",
                        help="Сохранить свернутый текст поста для отчётного макета")
    parser.add_argument("--timeout", type=positive_int, default=30000, help="Таймаут в мс")
    parser.add_argument("--retries", type=positive_int, default=3, help="Всего попыток на пост")
    add_zoom_argument(parser)
    args = parser.parse_args()
    if args.cdp:
        endpoint = urlsplit(args.cdp)
        if (endpoint.scheme not in {'http', 'ws'} or endpoint.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or endpoint.username or endpoint.password):
            parser.error('--cdp разрешён только для локального loopback endpoint')
        if args.login:
            parser.error('--login нельзя сочетать с --cdp; восстановите вход в сохранённом браузере вручную')
    if args.visual_only and (args.comments_only or args.collapsed_text):
        parser.error("--visual-only нельзя сочетать с --comments-only или --collapsed-text")
    if args.all_visuals and (args.visual_only or args.comments_only or args.collapsed_text):
        parser.error("--all-visuals нельзя сочетать с --visual-only, --comments-only или --collapsed-text")
    if args.output is None:
        folder = "vk-comment-screenshots" if args.comments_only else "vk-screenshots"
        args.output = Path(os.environ.get("REPORT_SKILLS_STATE_DIR", Path.home() / ".local/state/report-skills")) / "outputs" / folder
    if not args.urls and not args.login:
        parser.error("Передайте ссылки на посты или --login")
    try:
        outside_package(args.output)
        outside_package(args.state)
        return asyncio.run(run(args))
    except ImportError:
        emit(ok=False, error="Установите Playwright: python -m pip install -r requirements.txt")
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        emit(ok=False, error=str(error))
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""Запуск: python test_screenshoter.py. Реальный Chromium, без запросов к VK."""

import asyncio
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from playwright.async_api import async_playwright, TimeoutError
from vk_post_screenshoter import capture_post, capture_all_visuals, parse_post_url
import vk_post_screenshoter as screenshoter


async def check_rate_limits():
    original_launch, original_emit = screenshoter.launch_browser, screenshoter.emit
    interval = getattr(screenshoter, 'NAVIGATION_DELAY', 5)
    screenshoter.NAVIGATION_DELAY = .3
    try:
        for status, delayed, partial, all_visuals in [(429, False, False, False),
                (200, False, False, True), (200, True, False, False), (200, False, True, False),
                (429, False, True, True)]:
            navigations, results = [], []
            @asynccontextmanager
            async def routed_launch(*args, **kwargs):
                async with original_launch(*args, **kwargs) as browser:
                    original_context = browser.new_context
                    async def new_context(**options):
                        context = await original_context(**options)
                        async def serve(route):
                            path = route.request.url.split('vk.ru')[-1]
                            if path == '/deferred-limit':
                                return await route.fulfill(status=429, body='Too many requests per second')
                            if not path.startswith('/wall'):
                                return await route.fulfill(status=204)
                            navigations.append((path, time.monotonic()))
                            if partial and path.endswith('_10'):
                                body = '<div class="post" id="post-1_10" style="width:300px;height:80px">Готовый пост</div>'
                                if all_visuals:
                                    body = '''<div class="post" id="post-1_10">
                                      <div data-testid="primary-attachment-photo"><a href="/photo-1_91">
                                        <img width="240" height="120" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='120'%3E%3Crect width='240' height='120' fill='purple'/%3E%3C/svg%3E"></a></div>
                                      <div data-testid="primary-attachment-photo" style="margin-top:15000px">
                                        <a href="/photo-1_92"><img loading="lazy" width="240" height="120" src="/deferred-limit"></a></div></div>'''
                                return await route.fulfill(status=200, content_type='text/html', body=body)
                            body = 'Не удалось загрузить посты: Too many requests per second'
                            if delayed:
                                body = '<script>setTimeout(()=>document.body.textContent="Too many requests per second",20)</script>'
                            await route.fulfill(status=status, content_type='text/html', body=body)
                        await context.route('**/*', serve)
                        return context
                    browser.new_context = new_context
                    yield browser
            screenshoter.launch_browser = routed_launch
            screenshoter.emit = lambda **row: results.append(row)
            with tempfile.TemporaryDirectory() as folder:
                output = Path(folder)
                args = SimpleNamespace(urls=[f'https://vk.ru/wall-1_{n}' for n in (10, 11, 12)],
                    login=False, cdp=None, state=output/'absent.json', zoom=100, headed=False,
                    timeout=300, retries=3, output=output, comments_only=False, visual_only=False,
                    collapsed_text=False, all_visuals=all_visuals)
                assert await screenshoter.run(args) == 1
                assert len(navigations) == (2 if partial and not all_visuals else 1), navigations
                assert len(results) == 3, results
                assert all(not row['ok'] and row['rate_limited'] for row in results[int(partial):]), results
                if partial:
                    if all_visuals:
                        assert not results[0]['ok'] and results[0]['obtained_count'] == 1, results
                        assert Path(results[0]['materials'][0]['path']).exists()
                    else:
                        assert results[0]['ok'] and Path(results[0]['path']).exists()
                        assert navigations[1][1] - navigations[0][1] >= .3
                else:
                    assert not list(output.glob('*.png'))
                for png in output.rglob('*.png'):
                    print(json.dumps({'temporary_path': str(png), 'sha256': hashlib.sha256(png.read_bytes()).hexdigest(),
                                      'result': 'rate-limit fixture verified; removed with temporary directory'}))
    finally:
        screenshoter.launch_browser, screenshoter.emit = original_launch, original_emit
        screenshoter.NAVIGATION_DELAY = interval
    print('OK: rate limit429/DOM/delayed DOM; no retry or next navigation; pacing; successful posts/partial materials preserved')


async def load_video(page, color, duration_ms=4200):
    await page.locator('video').evaluate("""async (video, [color, duration]) => {
        const canvas = document.createElement('canvas');
        canvas.width = 240; canvas.height = 160;
        const ctx = canvas.getContext('2d');
        const draw = () => { ctx.fillStyle = color; ctx.fillRect(0, 0, 240, 160); };
        draw();
        const stream = canvas.captureStream(10);
        const recorder = new MediaRecorder(stream, {mimeType: 'video/webm;codecs=vp8'});
        const chunks = [];
        recorder.ondataavailable = event => chunks.push(event.data);
        const stopped = new Promise(resolve => recorder.onstop = resolve);
        const repaint = setInterval(draw, 100);
        recorder.start();
        await new Promise(resolve => setTimeout(resolve, duration));
        recorder.stop(); await stopped;
        clearInterval(repaint); stream.getTracks().forEach(track => track.stop());
        const loaded = new Promise(resolve => video.onloadeddata = resolve);
        video.src = URL.createObjectURL(new Blob(chunks, {type: 'video/webm'}));
        await loaded;
    }""", [color, duration_ms])


async def check():
    for url in (
        "https://vk.ru/wall-101_203",
        "https://m.vk.com/wall-101_203?from=feed",
        "vk.com/public101?w=wall-101_203%2Fall",
    ):
        assert parse_post_url(url) == ("https://vk.ru/wall-101_203", "-101_203")
    assert parse_post_url("https://vk.ru/wall-102_201?reply=202", preserve_reply=True) == (
        "https://vk.ru/wall-102_201?reply=202", "-102_201")
    for url in ("https://evil.test/wall-1_2", "https://vk.ru.evil.test/wall-1_2",
                "https://vk.ru/id123", "https://vk.ru/wall0_2", "https://vk.ru/wall-1_0",
                "https://" + "user@" + "vk.ru/wall-1_2", "file://vk.ru/wall-1_2",
                "https://vk.ru/story-101_203", "https://www.instagram.com/p/example/"):
        try:
            parse_post_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Недопустимая ссылка принята: {url}")

    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder)
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content('''<body scheme="vkcom_dark" style="background:#141414;color:white">
                    <div class="post" id="post-1_99" style="width:250px;background:white;color:black">Белая карточка</div>''')
                assert (await screenshoter.post_theme(page.locator('.post')))['light']
                await capture_post(page, '-1_99', output/'light-card.png', 1000)
                await page.set_content('''<body scheme="vkcom_dark" style="background:#141414;color:white">
                    <button data-testid="header-profile-menu-button" onclick="document.querySelector('#menu').hidden=false">Профиль</button>
                    <div id="menu" hidden><span>Тема: <span onclick="document.querySelector('#options').hidden=false">Тёмная</span></span></div>
                    <div id="options" hidden><button onclick="document.body.setAttribute('scheme','vkcom_light');document.body.style.background='white';document.body.style.color='black';this.parentNode.hidden=true">Светлая</button></div>
                    <div class="post" id="post-1_99" style="width:250px">Карточка</div>''')
                assert not (await screenshoter.post_theme(page.locator('.post')))['light']
                await capture_post(page, '-1_99', output/'switched-light.png', 1000)
                assert await page.locator('body').get_attribute('scheme') == 'vkcom_light'
                await page.set_content('<body style="background:#141414;color:white"><div class="post" id="post-1_99">Карточка</div>')
                try:
                    await capture_post(page, '-1_99', output/'unavailable-light.png', 300)
                except TimeoutError:
                    assert not (output/'unavailable-light.png').exists()
                else:
                    raise AssertionError('Тёмная карточка сохранена без переключения')
                print('OK: white card on dark page accepted; native theme menu switches to light; unavailable switch saves no PNG')
                html = '''<style>body{margin:0}.post{width:300px;height:120px;background:#eee}</style>
                    <div class="post" id="post-1_1">Другой пост</div>
                    <div class="post" id="post-101_203">Нужный текстовый пост
                      <a class="wall_post_more" onclick="this.parentNode.style.height='180px';this.remove()">
                        Показать полностью</a></div>'''
                await page.set_content(html)
                collapsed = await capture_post(page, "-101_203",
                                               output / "collapsed.png", 1000, expand_text=False)
                assert struct.unpack(">II", collapsed.read_bytes()[16:24]) == (300, 120), "Свернутый текст раскрыт"
                assert await page.locator('.wall_post_more').is_visible(), "Изменён свернутый пост"
                path = await capture_post(page, "-101_203", output / "post.png", 1000)
                png = path.read_bytes()
                assert png[:8] == b"\x89PNG\r\n\x1a\n"
                assert struct.unpack(">II", png[16:24]) == (300, 180), "Выбран другой пост или не раскрыт текст"
                await page.evaluate('''() => {
                    const overlay = document.createElement('div');
                    overlay.style = 'position:fixed;inset:0;background:red;z-index:999';
                    document.body.append(overlay);
                }''')
                clean = await capture_post(page, "-101_203", output / "clean.png", 1000)
                assert clean.read_bytes() == png, "Закреплённый баннер попал в снимок"
                await page.set_content('''<style>body{margin:0}.post{width:300px;background:#eee}</style>
                    <div class="post" id="post-1_2"><header style="height:40px">Аватарка и сообщество</header>
                    <article style="height:80px">Текст поста</article>
                    <footer style="height:30px">Лайки и дата</footer></div>''')
                baseline = await capture_post(page, "-1_2", output / "without-comments.png", 1000)
                expected = baseline.read_bytes()
                await page.locator('#post-1_2').evaluate('''post => {
                    post.insertAdjacentHTML('beforeend', '<div id="replies_wrap-1_2" class="replies_wrap" style="height:100px;display:block!important">Комментарии<a class="wall_post_more" onclick="document.body.dataset.commentExpanded=1">Показать полностью</a></div><div class="reply_box_wrap" style="height:40px">Написать комментарий</div>');
                }''')
                no_comments = await capture_post(page, "-1_2", output / "with-comments.png", 1000)
                assert no_comments.read_bytes() == expected, "Комментарии или форма ответа попали в снимок"
                assert await page.locator('.replies_wrap').is_visible(), "Комментарии скрыты после съёмки"
                assert await page.locator('body').get_attribute('data-comment-expanded') is None, "Раскрыт текст комментария вместо поста"
                await page.locator('.replies_wrap').evaluate('el => el.insertAdjacentHTML("beforeend", \'<img src="data:image/png;base64,broken">\')')
                no_avatars = await capture_post(page, "-1_2", output / "broken-comment-avatar.png", 1000)
                assert no_avatars.read_bytes() == expected, "Аватар комментария повлиял на снимок поста"
                await page.set_content('<style>body{margin:0}.wall_post_text_wrapper{font:14px/20px sans-serif}</style>'
                    '<div class="post" id="post-1_3" style="width:300px"><header style="height:40px">Сообщество</header>'
                    '<div class="photo" style="height:100px;background:purple">Изображение</div>'
                    '<div class="wall_post_text_wrapper">' + 'Длинный текст поста. ' * 80 +
                    '</div><footer style="height:30px">Дата и реакции</footer></div>')
                short = await capture_post(page, "-1_3", output / "already-expanded.png", 1000, expand_text=False)
                assert struct.unpack(">II", short.read_bytes()[16:24]) == (300, 230), "Прямой пост не свернут или потеряны изображение/дата"
                assert await page.locator('.wall_post_text_wrapper').evaluate('el => el.clientHeight') > 60, "Состояние текста изменено после съёмки"
                await page.set_content('''<style>body{margin:0}.post{width:300px}</style>
                    <div class="post" id="post-1_4"><header style="height:40px">Сообщество</header>
                    <div class="wall_post_cont"><img width="240" height="120" style="display:block"
                      src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='120'%3E%3Crect width='240' height='120' fill='purple'/%3E%3C/svg%3E"></div>
                    <div class="replies_wrap" style="height:80px">Комментарии</div></div>''')
                visual = await capture_post(page, "-1_4", output / "visual.png", 1000, visual_only=True)
                assert struct.unpack(">II", visual.read_bytes()[16:24]) == (240, 120), "Снята не визуальная часть"
                carousel = ''.join(f'''<div data-testid="primary-attachment" style="flex:none;width:240px">
                    <a href="/photo-1_{i}"><img width="240" height="120" style="display:block"
                    src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='120'%3E%3Crect width='240' height='120' fill='{color}'/%3E%3C/svg%3E"></a></div>'''
                    for i, color in enumerate(('red', 'green', 'blue', 'purple'), 1))
                await page.set_content('''<div data-testid="post" data-post-id="-1_8">
                    <div data-testid="carousel-counter">1/4</div>
                    <div data-testid="gallery" style="width:240px;overflow:hidden;position:relative">
                    <button class="vkuiCarouselBase__arrowEnd" style="position:fixed;right:0;top:0"
                      onclick="window.slide=(window.slide||0)+1; document.querySelector('#slides').style.transform=`translateX(${-240*window.slide}px)`; document.querySelector('[data-testid=carousel-counter]').textContent=(window.slide+1)+'/4'">Next</button>
                    <div id="slides" style="display:flex">''' + carousel + '''</div></div>
                    <div><span data-testid="post_date_block_preview">Дата</span></div>
                    <div><div data-testid="primary-attachment"><a href="/photo-1_99">Фото комментария</a></div></div></div>''')
                # VK can expose the post and carousel counter before mounting its attachments.
                await page.evaluate("""() => {
                    const slides = document.querySelector('#slides');
                    const html = slides.innerHTML; slides.innerHTML = '';
                    setTimeout(() => slides.innerHTML = html, 200);
                }""")
                album = await capture_all_visuals(page, '-1_8', output, 1000)
                assert album['ok'] and album['expected_count'] == album['obtained_count'] == 4, album
                assert [item['material_id'] for item in album['materials']] == [f'photo-1_{i}' for i in range(1, 5)]
                assert [item['order'] for item in album['materials']] == [1, 2, 3, 4]
                assert len({Path(item['path']).read_bytes() for item in album['materials']}) == 4, 'Повторён первый слайд'
                await page.evaluate("""() => {
                    document.querySelectorAll('[data-testid="primary-attachment"]').forEach(el => el.dataset.testid = 'primary-attachment-photo');
                    window.slide = 0; document.querySelector('#slides').style.transform = '';
                    document.querySelector('[data-testid="carousel-counter"]').textContent = '1/4';
                }""")
                new_markup = await capture_all_visuals(page, '-1_8', output / 'photo-markup', 1000)
                assert new_markup['ok'] and new_markup['obtained_count'] == 4, new_markup
                assert [m['material_id'] for m in new_markup['materials']] == [m['material_id'] for m in album['materials']]
                await page.evaluate("() => { window.slide=0; document.querySelector('#slides').style.transform=''; document.querySelector('[data-testid=carousel-counter]').textContent='1/5'; document.querySelector('button').onclick=()=>{window.slide++; document.querySelector('#slides').style.transform=`translateX(${-240*window.slide}px)`; document.querySelector('[data-testid=carousel-counter]').textContent=(window.slide+1)+'/5'}; }")
                partial = await capture_all_visuals(page, '-1_8', output / 'partial', 1000)
                assert not partial['ok'] and partial['expected_count'] == 5 and partial['obtained_count'] == 4, partial
                await page.set_content('''<div class="post" id="post-1_5"><header>Сообщество</header>
                    <div class="VideoPrimaryAttachment" style="width:240px;height:160px;background:purple">
                      <a href="/video-1_7"></a><video class="videoplayer_media_provider" style="width:240px;height:160px"></video></div>
                    <div class="replies_wrap">Комментарии</div></div>''')
                await load_video(page, 'purple')
                visual_video = await capture_post(page, "-1_5", output / "visual-video.png", 5000, visual_only=True)
                assert struct.unpack(">II", visual_video.read_bytes()[16:24]) == (240, 160)
                assert await page.locator('video').evaluate('v => v.currentTime') == 3, "Видео снято не на третьей секунде"
                video_album = await capture_all_visuals(page, '-1_5', output / 'video-album', 5000)
                assert video_album['ok'] and video_album['materials'][0]['material_id'] == 'video-1_7', video_album
                assert await page.locator('video').evaluate('v => v.currentTime') == 3
                await page.locator('.VideoPrimaryAttachment').evaluate('el => {el.dataset.testid="primary-attachment-video"; el.className=""}')
                await page.locator('video').evaluate('v => v.currentTime = 0')
                await page.locator('[data-testid="primary-attachment-video"]').evaluate('el => {const video=el.querySelector("video"); video.className="player-media"; video.remove(); el.onclick=()=>{const host=document.createElement("media-test"); el.append(host); host.attachShadow({mode:"open"}).append(video)}}')
                await capture_post(page, "-1_5", output / "full-video.png", 5000)
                assert await page.locator('video').evaluate('v => v.currentTime') == 3, "Полный пост снят до готовности видео"
                for duration, expected_time in ((3, 2), (2, 1)):
                    await page.locator('video').evaluate("(v, d) => Object.defineProperty(v, 'duration', {value:d, configurable:true})", duration)
                    await capture_post(page, '-1_5', output / f'boundary-{duration}.png', 5000)
                    assert await page.locator('video').evaluate('v => v.currentTime') == expected_time
                await page.locator('video').evaluate("v => Object.defineProperty(v, 'duration', {value:NaN, configurable:true})")
                invalid_duration = output / 'invalid-duration.png'
                try:
                    await capture_post(page, '-1_5', invalid_duration, 5000)
                except Exception as error:
                    assert 'длительность не определена' in str(error), str(error)
                    assert not invalid_duration.exists()
                else:
                    raise AssertionError('Видео с неизвестной длительностью принято')
                await page.locator('video').evaluate('v => delete v.duration')
                for duration_ms in (2600, 1200):
                    await load_video(page, 'purple', duration_ms)
                    duration = await page.locator('video').evaluate('v => v.duration')
                    assert 0 < duration < 3
                    expected_time = 2 if duration > 2 else duration / 2
                    for visual_only in (False, True):
                        await capture_post(page, '-1_5', output / f'short-{duration_ms}-{visual_only}.png',
                                           5000, visual_only=visual_only)
                        actual = await page.locator('video').evaluate('v => v.currentTime')
                        assert abs(actual - expected_time) < .001 and actual < duration
                    short_album = await capture_all_visuals(page, '-1_5', output / f'short-album-{duration_ms}', 5000)
                    assert short_album['ok'], short_album
                    assert abs(await page.locator('video').evaluate('v => v.currentTime') - expected_time) < .001
                await load_video(page, 'black', 1200)
                short_black = await capture_all_visuals(page, '-1_5', output / 'short-black', 5000)
                assert not short_black['ok'] and short_black['obtained_count'] == 0
                assert 'чёрный' in short_black['materials'][0]['error']
                assert not list((output / 'short-black').glob('*.png'))
                await load_video(page, 'black')
                black_album = await capture_all_visuals(page, '-1_5', output / 'black-album', 5000)
                assert not black_album['ok'] and black_album['obtained_count'] == 0
                assert 'чёрный' in black_album['materials'][0]['error']
                assert not list((output / 'black-album').glob('*.png'))
                for visual_only in (False, True):
                    rejected = output / f'black-{visual_only}.png'
                    try:
                        await capture_post(page, "-1_5", rejected, 5000, visual_only=visual_only)
                    except Exception as error:
                        assert 'чёрный' in str(error), str(error)
                        assert not rejected.exists(), "Чёрный видеокадр сохранён как успешный"
                    else:
                        raise AssertionError("Чёрный видеокадр принят")
                await page.set_content('''<div class="post" id="post-1_9"><header>Автор</header>
                    <div data-testid="clip-attachment--1_90" style="width:240px;height:160px">
                      <video style="width:240px;height:160px"></video></div></div>''')
                await load_video(page, 'purple')
                for visual_only in (False, True):
                    await page.locator('video').evaluate('v => v.currentTime = 0')
                    await capture_post(page, '-1_9', output / f'clip-{visual_only}.png', 5000, visual_only=visual_only)
                    state = await page.locator('video').evaluate('v => ({time:v.currentTime,paused:v.paused})')
                    assert state == {'time': 3, 'paused': True}, state
                clip_album = await capture_all_visuals(page, '-1_9', output / 'clip-album', 5000)
                assert clip_album['ok'] and clip_album['materials'][0]['material_id'] == 'video-1_90', clip_album
                # Native metadata-only playback must decode before pause-on-play is armed.
                await page.locator('video').evaluate('''v => {
                    v.currentTime = 0;
                    Object.defineProperty(v, 'readyState', {value:1, configurable:true});
                    setTimeout(async () => {
                        await v.play();
                        setTimeout(() => {
                            if (!v.paused) { delete v.readyState; v.dispatchEvent(new Event('loadeddata')); }
                        }, 50);
                    }, 50);
                }''')
                await capture_post(page, '-1_9', output / 'clip-delayed-decode.png', 1000)
                assert await page.locator('video').evaluate('v => v.currentTime') == 3
                await load_video(page, 'black')
                for visual_only in (False, True):
                    rejected = output / f'clip-black-{visual_only}.png'
                    try:
                        await capture_post(page, '-1_9', rejected, 5000, visual_only=visual_only)
                    except Exception as error:
                        assert 'чёрный' in str(error), str(error)
                        assert not rejected.exists()
                    else:
                        raise AssertionError('Клип обошёл проверку чёрного кадра')
                clip_black_album = await capture_all_visuals(page, '-1_9', output / 'clip-black-album', 5000)
                assert not clip_black_album['ok'] and clip_black_album['obtained_count'] == 0
                await page.locator('video').evaluate("v => { v.pause(); v.removeAttribute('src'); v.load(); }")
                rejected = output / 'clip-undecoded.png'
                try:
                    await capture_post(page, '-1_9', rejected, 300)
                except Exception as error:
                    assert 'loadeddata' in str(error), str(error)
                    assert not rejected.exists()
                else:
                    raise AssertionError('Недекодированный клип принят')
                await page.set_content('''<style>body{margin:0}</style>
                    <div data-testid="post" data-post-id="-1_6" style="width:300px;background:white">
                      <div style="height:40px">Сообщество</div>
                      <div data-testid="post-content-container" style="height:120px">
                        <img width="240" height="120" style="display:block"
                          src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='120'%3E%3Crect width='240' height='120' fill='purple'/%3E%3C/svg%3E">
                      </div>
                      <div style="height:30px"><span data-testid="post_date_block_preview">1 авг</span></div>
                      <div style="height:80px">Комментарии</div>
                    </div>''')
                spa = await capture_post(page, "-1_6", output / "spa.png", 1000)
                assert struct.unpack(">II", spa.read_bytes()[16:24]) == (300, 190), "Комментарии SPA попали в снимок"
                assert await page.locator('[data-testid="post"]').get_by_text('Комментарии').is_visible()
                spa_visual = await capture_post(page, "-1_6", output / "spa-visual.png", 1000, visual_only=True)
                assert struct.unpack(">II", spa_visual.read_bytes()[16:24]) == (240, 120), "Не снято изображение SPA"
                await page.set_content('<a data-post-id="12_34">Автор</a><div class="post" data-post-id="12_34" style="width:250px;height:100px">Пост</div>')
                await capture_post(page, "12_34", output / "fallback.png", 1000)
                try:
                    await capture_post(page, "12_35", output / "missing.png", 300)
                except TimeoutError:
                    assert not (output / "missing.png").exists()
                else:
                    raise AssertionError("Вместо отсутствующего поста снят другой")

            finally:
                if browser.is_connected():
                    await browser.close()

        result = subprocess.run([sys.executable, str(Path(__file__).with_name("vk_post_screenshoter.py")),
                                 "https://evil.test/wall-1_2"], capture_output=True, text=True)
        assert result.returncode == 1
        assert json.loads(result.stdout)["ok"] is False
        for endpoint, flags in [('http://example.org:9222', []), ('http://127.0.0.1:9222', ['--login'])]:
            rejected_cdp = subprocess.run([sys.executable, str(Path(__file__).with_name('vk_post_screenshoter.py')),
                                           '--cdp', endpoint, *flags, 'https://vk.ru/wall-1_9'],
                                          capture_output=True, text=True)
            assert rejected_cdp.returncode == 2 and '--cdp' in rejected_cdp.stderr
    print("OK: URL/CDP validation, legacy/SPA/clip post, video3s/short2s/midpoint, delayed decode, black/undecoded clips rejected, expansion, overlays, comments excluded, fallback, missing post, CLI error")


if __name__ == "__main__":
    asyncio.run(check())
    asyncio.run(check_rate_limits())

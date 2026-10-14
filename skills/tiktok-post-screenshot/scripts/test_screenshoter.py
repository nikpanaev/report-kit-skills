"""Минимальные проверки границ ссылок и полного текста; живые PNG проверять отдельно."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright
from tiktok_post_screenshoter import dismiss_overlays, expand_caption, parse_post_url


def check_urls():
    url, post_id = parse_post_url('https://www.tiktok.com/@name/video/123?sender_device=pc')
    assert (url, post_id) == ('https://www.tiktok.com/@name/video/123', '123')
    for invalid in ('https://tiktok.com.evil.test/@name/video/123',
                    'https://' + 'name@' + 'tiktok.com/@name/video/123',
                    'https://tiktok.com:443/@name/video/123',
                    'https://tiktok.com/@name/photo/123',
                    'https://vt.tiktok.com/short', 'https://tiktok.com/@name'):
        try:
            parse_post_url(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Принята неподдерживаемая ссылка: {invalid}')
    result = subprocess.run([sys.executable, str(Path(__file__).with_name('tiktok_post_screenshoter.py')),
                             'https://example.com/post/123'], capture_output=True, text=True)
    assert result.returncode == 1 and json.loads(result.stdout)['ok'] is False


async def check_caption():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content('''<article data-e2e="recommend-list-item-container">
                <div id="caption"><div data-e2e="video-desc">Полный текст автора. <a>#хэштег</a></div>
                <div class="DivCustomTDKContainer">Платформенная AI-сводка</div></div>
                <strong data-e2e="like-count">0</strong></article>''')
            post = page.locator('article')
            await expand_caption(post, 1000)
            assert await post.locator('[data-e2e="video-desc"]').inner_text() == 'Полный текст автора. #хэштег'
            assert not await post.get_by_text('Платформенная AI-сводка').is_visible()
            assert await post.locator('[data-e2e="like-count"]').inner_text() == '0'
            await page.locator('#caption').evaluate("el => {el.style.height='5px';el.style.overflow='auto'}")
            try:
                await expand_caption(post, 1000)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Обрезанная подпись была принята как полная')
            await page.set_content('<div class="DivModalMask">Незакрытое окно</div>')
            try:
                await dismiss_overlays(page)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Незакрытое окно было пропущено')
            await page.set_content('''<div><div class="DivModalMask">Маска окна</div>
                <div onclick="this.parentElement.remove()">Skip</div></div>''')
            await dismiss_overlays(page)
            assert await page.get_by_text('Skip', exact=True).count() == 0
        finally:
            await browser.close()


if __name__ == '__main__':
    check_urls()
    asyncio.run(check_caption())
    print('OK: ссылки, сохранность подписи, исключение сводки, отказ при обрезке и перекрытии')

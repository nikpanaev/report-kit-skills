"""Локальная проверка без аккаунта и запросов к Instagram."""
import asyncio
import hashlib
import json
import math
import struct
import tempfile
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright, TimeoutError
from instagram_post_screenshot import frame_time, open_embed, parse_post_url, ready_media, save


def check_inputs():
    assert parse_post_url("https://instagram.com/p/Ab_-123/?utm_source=test") == (
        "https://www.instagram.com/p/Ab_-123/", "p", "Ab_-123")
    assert parse_post_url("m.instagram.com/reel/ABC/")[1:] == ("reel", "ABC")
    for bad in ("https://instagram.com.evil/p/ABC/", "https://" + "user@" + "instagram.com/p/ABC/",
                "https://instagram.com:443/p/ABC/", "https://instagram.com/stories/user/123/",
                "https://instagram.com/user/", "https://vk.ru/wall-1_2",
                "javascript://instagram.com/p/ABC/", "https://instagram.com/p/../../accounts/"):
        try:
            parse_post_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Принята посторонняя ссылка: {bad}")
    assert frame_time(10, 4) == 4
    assert abs(frame_time(2, 4) - 1.95) < 0.001
    for duration in (0, math.inf, math.nan):
        try:
            frame_time(duration, 4)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Принята недоступная длительность видео")


async def check_capture():
    svg = quote('<svg xmlns="http://www.w3.org/2000/svg" width="390" height="390"><rect width="390" height="390" fill="#2196f3"/></svg>')
    image = f'<img width="390" height="390" src="data:image/svg+xml,{svg}">'
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        await page.set_content('<article><img width="390" src="data:image/png,broken"></article>')
        try:
            await ready_media(page, "article", 200)
        except TimeoutError:
            pass
        else:
            raise AssertionError("Не загрузившееся медиа принято за готовый снимок")
        html = f'''<style>body{{margin:0}}.Embed{{width:390px}}</style>
            <div class="Embed"><div class="Header">Автор</div><div class="Content">{image}</div>
            <div class="Caption">Полная подпись — последняя строка<div class="CaptionComments">Секретный комментарий</div></div>
            <div class="Footer">Форма комментария</div></div>'''
        await page.route("https://www.instagram.com/p/fixture/embed/captioned/",
                         lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html))
        await open_embed(page, "https://www.instagram.com/p/fixture/", 5000)
        await ready_media(page, ".Embed", 5000)
        assert "последняя строка" in await page.locator(".Caption").inner_text()
        assert not await page.locator(".CaptionComments").is_visible()
        assert not await page.locator(".Footer").is_visible()
        assert await page.locator(".Header").is_visible()
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "post.png"
            await save(page.locator(".Embed"), file, 5000)
            width, height = struct.unpack(">II", file.read_bytes()[16:24])
            assert width == 780 and height > 780, (width, height)
            print(json.dumps({"temporary_file": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "result": "Synthetic PNG bounds and caption checks passed; cleanup follows"}))
        await browser.close()


if __name__ == "__main__":
    check_inputs()
    asyncio.run(check_capture())
    print("OK: ссылки, короткое видео, незагруженное медиа, полный текст без комментариев, PNG 780 px")

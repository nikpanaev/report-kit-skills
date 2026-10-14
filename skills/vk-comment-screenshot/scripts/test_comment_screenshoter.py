"""Запуск тем же Python, что и vk-post-screenshot. Проверка в локальном Chromium."""

import asyncio
import struct
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright
from vk_comment_screenshoter import capture_comments


async def check():
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder)
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content('''<style>body{margin:0}.replies_list{width:300px;background:#eee}</style>
                    <div class="post" id="post-9_1"><div class="replies_list"><div class="reply">Чужой комментарий</div></div></div>
                    <div class="post" id="post-1_2"><header style="height:40px">Сообщество</header>
                    <article style="height:100px">Публикация<img src="data:image/png;base64,broken"></article>
                    <footer style="height:30px">Реакции публикации</footer>
                    <div class="replies_wrap"><div class="replies_list" id="replies-1_2">
                    <div class="reply" style="height:60px">Автор комментария, дата, текст</div>
                    <div class="reply" style="height:100px">Второй комментарий
                      <div class="reply" style="height:40px">Вложенный ответ</div></div>
                    </div><div class="reply_fakebox_wrap">Внешняя форма</div></div></div>''')
                expected = await page.locator('#replies-1_2').screenshot(type='png')
                await page.locator('#replies-1_2').evaluate('''el => el.insertAdjacentHTML('beforeend',
                    '<div class="reply_box_wrap" style="height:50px;display:block!important">Написать ответ</div>')''')
                await page.evaluate('''() => {
                    const overlay=document.createElement('div');
                    overlay.style='position:fixed;inset:0;background:red;z-index:999';
                    document.body.append(overlay);
                }''')
                path = await capture_comments(page, '-1_2', output / 'comments.png', 1000)
                png = path.read_bytes()
                assert png == expected, 'В кадр попали пост, чужие комментарии, форма или баннер'
                assert struct.unpack('>II', png[16:24]) == (300, 160)
                assert await page.locator('#post-1_2 .reply_box_wrap').is_visible(), 'Форма не восстановлена'
                assert await page.locator('#post-1_2 header').is_visible(), 'Изменён исходный пост'

                await page.set_content('''<style>body{margin:0}[data-testid=post]{width:300px;background:white}</style>
                    <div data-testid="post" data-post-id="-1_3">
                      <header style="height:40px">Сообщество</header>
                      <article style="height:80px">Текст поста</article>
                      <footer style="height:30px"><span data-testid="post_date_block_preview">Дата поста</span></footer>
                      <div class="CommentsContainer__container"><div data-testid="wall_comments_layout_root" id="spa-comments">
                        <div data-testid="show_prev_comments" style="height:25px">Показать предыдущие</div>
                        <div data-testid="wall_comments_comment_root" style="height:60px"><a href="/id5">Автор</a> Комментарий</div>
                        <div data-testid="wall_comments_layout_thread" style="height:40px">
                          <div data-testid="wall_comments_comment_in_thread"><a href="/id6">Ответ</a> Вложенный ответ</div></div>
                      </div><div style="height:35px;overflow:hidden"><textarea>Написать комментарий</textarea></div></div>
                    </div>''')
                expected = await page.locator('#spa-comments').screenshot(type='png',
                    style='[data-testid="show_prev_comments"] { display:none!important }')
                path = await capture_comments(page, '-1_3', output / 'spa-comments.png', 1000)
                assert path.read_bytes() == expected, 'В SPA-снимок попали пост, форма или кнопка загрузки'
                assert await page.locator('textarea').is_visible(), 'Форма SPA не восстановлена'
                await page.locator('[data-testid="wall_comments_comment_root"], '
                                   '[data-testid="wall_comments_layout_thread"]').evaluate_all(
                    'elements => elements.forEach(el => el.remove())')
                try:
                    await capture_comments(page, '-1_3', output / 'spa-empty.png', 300)
                except RuntimeError as error:
                    assert 'Нет отображённых комментариев' in str(error)
                    assert not (output / 'spa-empty.png').exists()
                else:
                    raise AssertionError('Пустой SPA-список выдан как комментарии')

                for html in ('<div class="replies_list" id="replies-1_2">Нет комментариев</div>', ''):
                    await page.set_content(f'<div class="post" id="post-1_2">Текст поста{html}</div>')
                    try:
                        await capture_comments(page, '-1_2', output / 'empty.png', 300)
                    except RuntimeError as error:
                        assert 'Нет отображённых комментариев' in str(error)
                        assert not (output / 'empty.png').exists()
                    else:
                        raise AssertionError('Пустой список выдан как скриншот комментариев')
            finally:
                await browser.close()
    print('OK: comments and nested replies only; exact post; forms and overlays excluded; empty list rejected')


if __name__ == '__main__':
    asyncio.run(check())

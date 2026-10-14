"""Native 75/100%, fresh profiles, navigation, auth isolation and cleanup on failure."""
import asyncio
import json
import hashlib
import math
import struct
import tempfile
import sys
from pathlib import Path

from browser_zoom import checked_zoom, launch_browser, screenshot, temporary_zoom, verify_zoom, verify_zoom_sync
from ui_queue import access

HTML = '<meta charset="utf-8"><style>body{margin:0;background:white}#card{width:300px;height:120px;background:blue;color:white;border:4px solid red;box-sizing:border-box;font:18px sans-serif}</style><div id="card">Автор · 10 октября<br>Читаемый текст<br>Полный снимок</div>'


async def async_checks():
    from playwright.async_api import async_playwright
    records = []
    async with async_playwright() as p:
        for requested,headless in ((75,False), (100,False), (75,True)):
            percent = 100 if headless else requested
            browser = None
            try:
                async with launch_browser(p, zoom=requested, headless=headless) as browser:
                    state = {'cookies': [{'name':'fixture_auth','value':'kept','domain':'example.test',
                        'path':'/','expires':-1,'httpOnly':True,'secure':True,'sameSite':'Lax'}],
                        'origins':[{'origin':'https://example.test','localStorage':[{'name':'guard','value':'kept'}]}]}
                    context = await browser.new_context(storage_state=state,
                        viewport={'width':1280,'height':900},device_scale_factor=2)
                    page = await context.new_page()
                    assert sum(len(c.pages) for c in browser.contexts) == 1
                    await page.route('https://example.test/**',lambda route:route.fulfill(body=HTML,content_type='text/html'))
                    for route in ('first', 'second'):
                        await page.goto('https://example.test/'+route)
                        assert await verify_zoom(page,requested,headless=headless) == percent
                        assert await page.evaluate('localStorage.guard') == 'kept'
                    assert (await context.cookies('https://example.test'))[0]['value'] == 'kept'
                    with tempfile.TemporaryDirectory() as directory:
                        target = Path(directory)/'card.png'
                        proofs = []
                        def record_frame(case):
                            proofs.append({'case':case,'path':str(target),
                                'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'result':'geometry check passed'})
                            print(json.dumps({'temporary_file':proofs[-1]}),flush=True)
                        clean_png = await screenshot(page.locator('#card'))
                        await page.evaluate("document.body.insertAdjacentHTML('beforeend','<aside id=overlay style=\"position:fixed;inset:0;background:black\">Login overlay</aside>')")
                        overlay_style = await page.locator('#overlay').get_attribute('style')
                        await screenshot(page.locator('#card'),path=str(target))
                        assert await page.locator('#overlay').get_attribute('style') == overlay_style
                        if percent == 75:
                            assert target.read_bytes() == clean_png,'Unrelated overlay entered native75 PNG'
                        await page.locator('#overlay').evaluate('e=>e.remove()')
                        size = struct.unpack('>II',target.read_bytes()[16:24])
                        assert size == (round(600*percent/100),round(240*percent/100)),size
                        record_frame('short')
                        await page.locator('#card').evaluate("e=>{e.style.height='1700px';e.style.marginLeft='150px';e.style.marginTop='350px'}")
                        await screenshot(page.locator('#card'),path=str(target))
                        long_size = struct.unpack('>II',target.read_bytes()[16:24])
                        assert round(600*percent/100) <= long_size[0] <= round(600*percent/100)+4,long_size
                        assert round(3400*percent/100) <= long_size[1] <= round(3400*percent/100)+4,long_size
                        record_frame('long')
                        assert await verify_zoom(page,percent) == percent
                        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vk-post-screenshot/scripts'))
                        from vk_post_screenshoter import capture_post
                        await page.set_content('''<style>body{margin:0}.post{width:300px;background:white}</style>
                          <div class="post" id="post-1_2"><header style="height:40px">Автор</header>
                          <article style="height:80px">Текст</article><footer style="height:30px">Дата и реакции</footer>
                          <div class="replies_wrap" id="replies_wrap-1_2"><div class="replies_list" id="replies-1_2"><div class="reply" style="height:120px">Автор · комментарий · дата</div></div></div></div>''')
                        await capture_post(page,'-1_2',target,2000)
                        post_size = struct.unpack('>II',target.read_bytes()[16:24])
                        assert post_size[0] == round(600*percent/100),(percent,post_size)
                        assert round(300*percent/100) <= post_size[1] <= round(300*percent/100)+2,(percent,post_size)
                        record_frame('vk_post')
                        await capture_post(page,'-1_2',target,2000,comments_only=True)
                        comment_size = struct.unpack('>II',target.read_bytes()[16:24])
                        assert comment_size[0] == round(600*percent/100)
                        assert round(240*percent/100) <= comment_size[1] <= round(240*percent/100)+4,comment_size
                        record_frame('vk_comments')
                    records.append({'requested':requested,'percent':percent,'headless':headless,
                        'native_zoom_verified':True,'png_size':size,'temporary_frames':proofs})
                    mobile = await browser.new_context(**{**p.devices['iPhone 13'],'device_scale_factor':2})
                    phone = await mobile.new_page()
                    await phone.goto('data:text/html,<meta name="viewport" content="width=device-width">Phone')
                    assert await verify_zoom(phone,percent,mobile=True) == 100
                    await mobile.close()
                    raise RuntimeError('intentional capture error')
            except RuntimeError as error:
                assert str(error) == 'intentional capture error',str(error)
            assert browser is not None and not browser.is_connected()
        entered = asyncio.Event()
        owned = []
        async def cancelled():
            async with launch_browser(p) as browser:
                owned.append(browser)
                entered.set()
                await asyncio.Future()
        task = asyncio.create_task(cancelled())
        await entered.wait()
        task.cancel()
        try:
            await task
            raise AssertionError('Cancellation lost')
        except asyncio.CancelledError:
            pass
        assert not owned[0].is_connected()
        async with launch_browser(p,mobile=True) as phone_browser:
            phone_context = await phone_browser.new_context(**p.devices['iPhone 13'])
            phone_page = await phone_context.new_page()
            await phone_page.goto('data:text/html,<meta name="viewport" content="width=device-width">Phone')
            assert await verify_zoom(phone_page,75,mobile=True) == 100
    return records


def sync_checks():
    from playwright.sync_api import sync_playwright
    proofs = []
    with sync_playwright() as p, tempfile.TemporaryDirectory() as profile:
        context = p.chromium.launch_persistent_context(profile,channel='chromium',headless=True)
        try:
            user_page = context.pages[0]
            user_page.goto('data:text/html,<h1>User tab guard</h1>')
            url = user_page.url
            context.add_cookies([{'name':'guard','value':'kept','domain':'example.test','path':'/'}])
            before = verify_zoom_sync(user_page,100)
            for error in (RuntimeError('intentional error'), KeyboardInterrupt()):
                try:
                    with temporary_zoom(context,75):
                        page = context.new_page()
                        try:
                            page.goto('data:text/html,<h1>Owned fixture</h1>')
                            assert verify_zoom_sync(page,75) == 75
                            sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vk-stories-screenshot/scripts'))
                            import vk_stories as stories
                            from test_vk_stories import HTML as story_html, UI
                            page.set_content(story_html)
                            page.locator('.card').first.click()
                            card = {'id':'a','date':stories.publication('2026-09-02T10:00:00+03:00',{'format':'iso'},'Europe/Moscow')}
                            with tempfile.TemporaryDirectory() as directory:
                                target = Path(directory)/'story.png'
                                stories.capture(page,card,UI,target,'Europe/Moscow')
                                assert struct.unpack('>II',target.read_bytes()[16:24]) == (270,480)
                                proofs.append({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                                    'result':'native75 VK story geometry check passed'})
                                print(json.dumps({'temporary_file':proofs[-1]}),flush=True)
                            raise error
                        finally:
                            page.close()
                except (RuntimeError,KeyboardInterrupt) as caught:
                    assert caught is error
                assert len(context.pages) == 1 and user_page.url == url
                assert verify_zoom_sync(user_page,before) == before
                assert context.cookies('https://example.test')[0]['value'] == 'kept'
        finally:
            context.close()
    return proofs


def main():
    assert checked_zoom(.75,75) == 75
    assert checked_zoom(1,75,mobile=True) == 100
    assert checked_zoom(1,75,headless=True) == 100
    for actual,expected in ((1,75),(.75,100),(math.nan,75),(.75,80)):
        try:
            checked_zoom(actual,expected)
            raise AssertionError('Invalid zoom accepted')
        except (RuntimeError,ValueError):
            pass
    with access('test-browser-zoom'):
        records = asyncio.run(async_checks())
        story_proofs = sync_checks()
    print(json.dumps({'ok':True,'runs':records,'error_cleanup':True,'cancel_cleanup':True,
                      'borrowed_tabs_auth_and_default_restored':True,'temporary_stories':story_proofs}))


if __name__ == '__main__':
    main()

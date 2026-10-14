"""Native Chromium zoom; no CSS zoom, pinch or PNG resizing."""
import json
import math
import tempfile
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

DEFAULT_ZOOM = 75


def add_zoom_argument(parser):
    parser.add_argument('--zoom', type=int, choices=(75, 100), default=DEFAULT_ZOOM,
                        help='Штатный масштаб; 100 для пересъёмки нечитаемого текста')


@asynccontextmanager
async def launch_browser(playwright, *, zoom=DEFAULT_ZOOM, headless=True, mobile=False):
    if zoom not in (75, 100):
        raise ValueError('Native zoom must be 75 or 100')
    if mobile or headless:
        # Full headless Chromium doubled fixture RSS; retain the existing shell at 100%.
        browser = await playwright.chromium.launch(headless=headless)
        try:
            yield browser
        finally:
            await browser.close()
        return
    # headless-shell ignores profile zoom; full Chromium inherits it into new_context.
    with tempfile.TemporaryDirectory(prefix='skill-native-zoom-') as profile:
        default = Path(profile) / 'Default'
        default.mkdir()
        (default / 'Preferences').write_text(json.dumps({'partition': {
            'default_zoom_level': {'x': math.log(zoom / 100) / math.log(1.2)}}}))
        context = await playwright.chromium.launch_persistent_context(
            profile, channel='chromium', headless=headless)
        try:
            for page in context.pages:
                await page.close()
            yield context.browser
        finally:
            await context.close()


def checked_zoom(actual, expected, mobile=False, headless=False):
    if expected not in (75, 100) or not math.isfinite(actual):
        raise ValueError('Native zoom must be 75 or 100')
    if (mobile or headless) and expected == 75 and math.isclose(actual, 1, abs_tol=.001):
        return 100  # shortcut: the retained shell/mobile route has no native zoom; disclose the fallback.
    if not math.isclose(actual, expected / 100, abs_tol=.001):
        raise RuntimeError(f'Штатный масштаб {actual * 100:.1f}%, нужен {expected}%. '
                           'Установите его меню браузера на целевой странице и повторите; '
                           'для читаемого исходного размера доступен --zoom 100')
    return expected


async def verify_zoom(page, expected, *, mobile=False, headless=False):
    session = await page.context.new_cdp_session(page)
    try:
        actual = (await session.send('Page.getLayoutMetrics'))['cssVisualViewport']['zoom']
        return checked_zoom(actual, expected, mobile, headless)
    finally:
        await session.detach()


async def screenshot(target, **options):
    """Playwright's locator clip is unscaled at native zoom; preserve the whole block."""
    page = target.page
    session = await page.context.new_cdp_session(page)
    try:
        zoom = (await session.send('Page.getLayoutMetrics'))['cssVisualViewport']['zoom']
    finally:
        await session.detach()
    if math.isclose(zoom, 1, abs_tol=.001):
        return await target.screenshot(**options)
    # Existing crop styles can remove comments and change the target's height.
    style = overlays = None
    try:
        style = await page.add_style_tag(content=options['style']) if options.get('style') else None
        overlays = await target.evaluate_handle('''target => [...document.body.querySelectorAll('*')]
          .filter(e=>!e.contains(target) && !target.contains(e) &&
            ['fixed','sticky'].includes(getComputedStyle(e).position)).map(e=>{
              const previous=e.getAttribute('style');e.style.setProperty('visibility','hidden','important');
              return [e,previous];
            })''')
        await page.evaluate('() => document.fonts.ready')
        await target.scroll_into_view_if_needed(timeout=options.get('timeout'))
        box = await target.bounding_box()
        if not box:
            raise RuntimeError('Screenshot target has no visible bounds')
        scroll = await page.evaluate('({x:scrollX,y:scrollY})')
        box['x'] += scroll['x']
        box['y'] += scroll['y']
        left, top = math.floor(box['x'] * zoom), math.floor(box['y'] * zoom)
        # Outward rounding retains the last pixel at fractional native-zoom boundaries.
        clip = {'x':left, 'y':top,
                'width':math.ceil((box['x'] + box['width']) * zoom) - left,
                'height':math.ceil((box['y'] + box['height']) * zoom) - top}
        return await page.screenshot(full_page=True, clip=clip, **options)
    finally:
        try:
            if overlays is not None:
                await overlays.evaluate("rows=>rows.forEach(([e,s])=>s===null?e.removeAttribute('style'):e.setAttribute('style',s))")
        finally:
            try:
                if style is not None:
                    await style.evaluate('e=>e.remove()')
            finally:
                if overlays is not None:
                    await overlays.dispose()


def verify_zoom_sync(page, expected):
    session = page.context.new_cdp_session(page)
    try:
        actual = session.send('Page.getLayoutMetrics')['cssVisualViewport']['zoom']
        return checked_zoom(actual, expected)
    finally:
        session.detach()


@contextmanager
def temporary_zoom(context, percent):
    """Borrowed normal Chrome: restore the native default, including on error/cancel."""
    if percent not in (75, 100):
        raise ValueError('Native zoom must be 75 or 100')
    settings = context.new_page()
    original = None
    try:
        settings.goto('chrome://settings/appearance', wait_until='domcontentloaded')
        control = settings.locator('select#zoomLevel')
        control.wait_for(state='visible')
        original = control.input_value()
        control.select_option(f'{percent / 100:g}')
        if control.input_value() != f'{percent / 100:g}':
            raise RuntimeError('Native browser zoom setting was not applied')
        yield
    finally:
        try:
            if original is not None and control.input_value() == f'{percent / 100:g}':
                # A manual handoff may let the user change the default; preserve that change.
                control.select_option(original)
        finally:
            settings.close()

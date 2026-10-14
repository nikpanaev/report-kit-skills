#!/usr/bin/env python3
"""VK stories via external Playwright browser. stdout is JSON Lines."""
import argparse
import getpass
import json
import os
import re
import select
import stat
import sys
import tempfile
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from ui_queue import access, current_lease
from private_paths import outside_package
from browser_zoom import add_zoom_argument, temporary_zoom, verify_zoom_sync
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
AUTH = Path(os.environ.get("REPORT_SKILLS_STATE_DIR", Path.home() / ".local/state/report-skills")) / "vk"
SHARED_CDP = 'http://127.0.0.1:9222'


class Failure(RuntimeError):
    """Only deliberate, secret-free messages may reach stdout."""


def check_zoom(page, args):
    if getattr(args, 'zoom', None) is not None:
        try:
            return verify_zoom_sync(page, args.zoom)
        except RuntimeError as error:
            raise Failure(str(error)) from None


def emit(**data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def private_dir(path):
    path = outside_package(path)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise Failure('Unsafe private directory')
    os.chmod(path, 0o700)


def save_json(path, data, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if private:
        private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def credentials(path):
    login, password = os.environ.get('VK_LOGIN'), os.environ.get('VK_PASSWORD')
    if login or password:
        if not login or not password:
            raise Failure('Set both VK_LOGIN and VK_PASSWORD')
        return {'login': login, 'password': password}
    if not path.exists():
        return None
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise Failure('Credentials require owner-only permissions (chmod 600)')
    data = json.loads(path.read_text())
    if not all(isinstance(data.get(k), str) and data[k] for k in ('login', 'password')):
        raise Failure('Credentials file requires login and password')
    return {k: data[k] for k in ('login', 'password')}


def source_url(value):
    p = urlsplit(value)
    if (p.scheme != 'https' or p.hostname not in
            {'vk.ru', 'vk.com', 'www.vk.ru', 'www.vk.com', 'm.vk.ru', 'm.vk.com'}
            or p.username or p.password or p.port):
        raise Failure('Use an HTTPS VK section URL')
    return value


def month_bounds(value, tz):
    if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', value):
        raise Failure('Month must be YYYY-MM, including the year')
    year, month = map(int, value.split('-'))
    start = datetime(year, month, 1, tzinfo=ZoneInfo(tz))
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=start.tzinfo)
    return start, end


def publication(raw, spec, tz):
    """Only formats observed on VK; never infer a missing year."""
    fmt = spec['format']
    if fmt in ('unix_s', 'unix_ms'):
        value = datetime.fromtimestamp(float(raw) / (1000 if fmt == 'unix_ms' else 1), timezone.utc)
    elif fmt == 'iso':
        if not re.match(r'^\d{4}-\d{2}-\d{2}', raw):
            raise Failure('Publication date lacks an explicit year')
        value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    else:
        if '%Y' not in fmt:
            raise Failure('Observed date format must include %Y')
        value = datetime.strptime(raw, fmt)
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(spec.get('source_timezone', tz)))
    return value.astimezone(ZoneInfo(tz))


def stable_identity(expected, actual):
    if not expected or actual != expected:
        raise Failure('Story identity changed or cannot be confirmed')


class Exhaustion:
    """An idle scroll alone never proves exhaustion."""
    def __init__(self):
        self.seen = set()
        self.quiet = 0

    def observe(self, ids, terminal, loading, next_page):
        fresh = set(ids) - self.seen
        self.seen.update(ids)
        self.quiet = 0 if fresh or loading or next_page else self.quiet + 1
        return terminal and not loading and not next_page and self.quiet >= 3


@contextmanager
def session(args):
    with access('vk-stories-screenshot:session'):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            if args.cdp:
                u = urlsplit(args.cdp)
                if u.scheme not in ('http', 'ws') or u.hostname not in ('127.0.0.1', 'localhost', '::1') or u.username or u.password:
                    raise Failure('CDP must be a local loopback endpoint')
                try:
                    browser = p.chromium.connect_over_cdp(args.cdp, timeout=args.timeout, no_defaults=True)
                except Exception:
                    raise Failure('Local CDP unavailable; reopen the external browser with its saved profile. '
                                  'No new profile or login was started') from None
                if not browser.contexts:
                    raise Failure('CDP browser has no usable context')
                context = browser.contexts[0]
                page = context.new_page()
                try:
                    page.set_default_timeout(args.timeout)
                    with temporary_zoom(context, args.zoom) if hasattr(args, 'zoom') else nullcontext():
                        yield page
                finally:
                    # Only our new tab; never browser.close()/context.close() on CDP.
                    page.close()
            else:
                private_dir(args.profile)
                context = p.chromium.launch_persistent_context(
                    str(args.profile), channel=args.channel, headless=False,
                    viewport={'width': 1280, 'height': 1000}, locale='ru-RU',
                )
                try:
                    page = context.new_page()
                    page.set_default_timeout(args.timeout)
                    with temporary_zoom(context, args.zoom) if hasattr(args, 'zoom') else nullcontext():
                        yield page
                finally:
                    context.close()


def inspect(page, destination):
    """Local evidence, excluding input values, scripts, cookies and tokens."""
    private_dir(destination)
    data = {'url': page.url, 'title': page.title(), 'frames': []}
    for frame in page.frames:
        data['frames'].append(frame.evaluate('''() => ({
          url:location.origin+location.pathname, text:document.body?.innerText.slice(0,20000),
          elements:[...document.querySelectorAll('a,button,input,[role],[data-testid],time,video,img')]
          .filter(e=>e.getBoundingClientRect().width && e.getBoundingClientRect().height)
          .slice(0,600).map(e=>({tag:e.tagName, id:e.id, class:e.className,
            text:e.tagName==='INPUT'?'':(e.innerText||'').slice(0,150),
            attrs:Object.fromEntries([...e.attributes].filter(a=>
              ['role','aria-label','data-testid','name','type','datetime','href','placeholder'].includes(a.name))
              .map(a=>[a.name,a.value]))}))
        })'''))
    save_json(destination / 'page.json', data, private=True)
    page.screenshot(path=str(destination / 'page.png'), full_page=False)
    os.chmod(destination / 'page.png', 0o600)
    emit(ok=True, kind='inspection', path=str((destination / 'page.png').resolve()),
         evidence=str((destination / 'page.json').resolve()))


def read_value(root, spec):
    loc = root.locator(spec['selector']) if spec.get('selector') else root
    if spec.get('source') == 'active_story':
        story = loc.evaluate('''e => {
          const index=Number(e.getAttribute('data-active-story-index'));
          if(!e.hasAttribute('data-active-story-index')) return null;
          let fiber=e[Object.keys(e).find(k=>k.startsWith('__reactFiber'))];
          for(let i=0;fiber&&i<20;i++,fiber=fiber.return){
            const pack=fiber.memoizedProps?.pack;
            if(pack?.stories){const s=pack.stories[index];
              return s ? {id:s.owner_id+'_'+s.id,date:s.date,type:s.type} : null;}
          }return null;
        }''')
        if not story or story.get(spec['field']) is None:
            raise Failure('Active story metadata is unavailable; re-observe VK UI')
        return str(story[spec['field']])
    if loc.count() != 1:
        raise Failure('Observed selector is absent or ambiguous')
    raw = loc.get_attribute(spec['attribute']) if spec.get('attribute') else loc.inner_text()
    if raw is None:
        raise Failure('Observed attribute is absent')
    raw = raw.strip()
    if spec.get('regex'):
        match = re.search(spec['regex'], raw)
        if not match:
            raise Failure('Observed value format changed')
        raw = match.group(1)
    if spec.get('source') == 'archive_date':
        data = getattr(root.page, '_vk_archive', {}).get('items', {}).get(raw)
        if not data:
            raise Failure('Archive card has no matching server publication date')
        return str(data['date'])
    return raw


def watch_archive(page, ui):
    """Observe responses caused by the real UI; never call private APIs directly."""
    arc = ui['archive']
    state = {'items': {}, 'count': None, 'groups': set(), 'screen_names': {},
             'errors': [], 'pending': set()}
    page._vk_archive = state
    def relevant(request):
        return urlsplit(request.url).path == arc['api_path']
    def requested(request):
        if relevant(request):
            state['pending'].add(request)
    def failed(request):
        if relevant(request):
            state['pending'].discard(request)
            state['errors'].append('Archive network request failed')
    def received(response):
        if not relevant(response.request):
            return
        try:
            body = response.json()
            data = body.get('response')
            if response.status != 200 or not isinstance(data, dict):
                raise Failure('Archive API returned an error; access/completeness unconfirmed')
            count = data['count']
            if not isinstance(count, int) or count < 0:
                raise Failure('Archive count format changed')
            if state['count'] is not None and state['count'] != count:
                raise Failure('Archive count changed during traversal')
            state['count'] = count
            state['groups'].update(g['id'] for g in data.get('groups', []))
            for group in data.get('groups', []):
                if group.get('screen_name'):
                    state['screen_names'][group['id']] = group['screen_name']
            for item in data['items']:
                if item['owner_id'] != int(arc['owner_id']):
                    raise Failure('Archive response belongs to a different community')
                ident = str(item['owner_id']) + '_' + str(item['id'])
                record = {key: item[key] for key in ('owner_id', 'id', 'date', 'type')}
                if ident in state['items'] and state['items'][ident] != record:
                    raise Failure('Archive metadata changed for one story')
                state['items'][ident] = record
        except Exception as error:
            state['errors'].append(safe_error(error))
        finally:
            state['pending'].discard(response.request)
    page.on('request', requested)
    page.on('requestfailed', failed)
    page.on('response', received)
    return state


def visible(root, selector):
    return bool(selector) and any(loc.is_visible() for loc in root.locator(selector).all())


def actions(page, recipe, secrets=None):
    for step in recipe:
        frame = page.frame_locator(step['frame']) if step.get('frame') else page
        target = frame.locator(step['selector'])
        if step.get('optional') and not target.is_visible():
            continue
        if step['action'] == 'click':
            target.click()
        elif step['action'] == 'fill':
            if not secrets or step.get('credential') not in ('login', 'password'):
                raise Failure('Login recipe must use credential references')
            # Prevent accidentally sending credentials to unrelated origins.
            url = target.evaluate('e => e.ownerDocument.location.href')
            if urlsplit(url).hostname not in ('vk.ru', 'vk.com', 'id.vk.ru', 'id.vk.com'):
                raise Failure('Credential field is outside VK')
            target.fill(secrets[step['credential']])
        elif step['action'] == 'hover':
            target.hover()
        elif step['action'] == 'hold':
            target.hover()
            page.mouse.down()
        elif step['action'] == 'press':
            target.press(step['key'])
        else:
            raise Failure('Unsupported observed action')


def authenticate(page, args, ui, force=False):
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    auth = ui.get('auth', {})
    if not force and auth.get('ready'):
        try:
            page.locator(auth['ready']).first.wait_for(state='visible', timeout=min(args.timeout, 10000))
            return
        except PlaywrightTimeout:
            pass
    creds = credentials(args.credentials)
    for attempt in range(2):
        if auth.get('url'):
            page.goto(source_url(auth['url']), wait_until='domcontentloaded')
        if creds and auth.get('steps'):
            try:
                actions(page, auth['steps'], creds)
            except Failure:
                raise
            except Exception:
                print('Автовход остановлен: интерфейс изменился или нужна проверка.', file=sys.stderr)
        if auth.get('ready') and visible(page, auth['ready']):
            return
        if not sys.stdin.isatty():
            raise Failure('Manual login requires an interactive terminal; release the outer ticket and run login without PERSONAL_UI_QUEUE_TOKEN')
        with current_lease().handoff():
            print('Пройдите вход/код/CAPTCHA и нажмите Enter в терминале. '
                  f'Очередь освобождена; ожидание {args.login_wait} с.', file=sys.stderr, flush=True)
            ready, _, _ = select.select([sys.stdin], [], [], args.login_wait)
            if not ready or not sys.stdin.readline():
                raise Failure('Manual login confirmation timed out or cancelled')
        # The user/another task may have changed the interface during handoff.
        source_url(page.url)
        if not auth.get('ready'):
            raise Failure('Inspect authenticated UI and record an auth.ready selector')
        try:
            page.locator(auth['ready']).first.wait_for(state='visible', timeout=min(args.timeout, 10000))
            return
        except PlaywrightTimeout:
            pass
    raise Failure('Login not confirmed within two bounded attempts')


def capture(page, card, ui, destination, tz, approved_missing_avatars=()):
    cfg = ui['viewer']
    region = page.locator(cfg['region'])
    region.wait_for(state='visible')
    actions(page, cfg['pause'])
    region.locator(cfg['paused']).wait_for(state='visible')
    held = any(step['action'] == 'hold' for step in cfg['pause'])
    try:
        if not visible(region, cfg['paused']):
            raise Failure('Story auto-advance pause is not confirmed')
        def verify():
            stable_identity(card['id'], read_value(region, cfg['identity']))
            date = publication(read_value(region, cfg['date']), cfg['date'], tz)
            if date != card['date']:
                raise Failure('Opened story publication date differs from archive card')
            author = region.locator(cfg['author'])
            if author.count() != 1 or not author.is_visible() or not author.inner_text().strip():
                avatar_selector = cfg.get('author_avatar')
                owner = int(card['id'].split('_', 1)[0])
                archive = getattr(page, '_vk_archive', {})
                name = archive.get('screen_names', {}).get(abs(owner))
                avatar = region.locator(avatar_selector) if avatar_selector else None
                if not name or avatar is None:
                    raise Failure('Story author is not visible or does not match archive owner')
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if (avatar.count() == 1 and avatar.is_visible() and
                        avatar.get_attribute('href') == '/' + name and
                        avatar.evaluate('e => {const i=e.querySelector("img"); return !!i && i.complete && i.naturalWidth>0}')):
                        if 'author_verification' in card:
                            card['author_verification']['avatar_loaded'] = True
                        break
                    page.wait_for_timeout(100)
                else:
                    item = archive.get('items', {}).get(card['id'], {})
                    if not (card['id'] in approved_missing_avatars and
                            ui['archive'].get('owner_id') == owner and
                            abs(owner) in archive.get('groups', set()) and
                            item.get('owner_id') == owner and
                            str(item.get('id')) == card['id'].split('_', 1)[1] and
                            item.get('date') == int(date.timestamp()) and
                            avatar.count() == 1 and avatar.is_visible() and
                            avatar.get_attribute('href') in ('/', '/' + name) and
                            not avatar.evaluate('e => {const i=e.querySelector("img"); return !!i && i.complete && i.naturalWidth>0}')):
                        raise Failure('Story author is not visible or does not match archive owner')
                    card['author_verification'] = {
                        'source': 'archive_owner_and_active_story_id',
                        'owner_id': owner, 'screen_name': name,
                        'manual_approval': True, 'avatar_loaded': False,
                        'note': 'Missing avatar manually approved; ownership checked independently; native screenshot preserved'}
            shown_date = region.locator(cfg['visible_date'])
            if shown_date.count() != 1 or not shown_date.is_visible() or not shown_date.inner_text().strip():
                raise Failure('Story publication date is not visible in screenshot region')
            if not visible(region, cfg['paused']):
                raise Failure('Story auto-advance resumed')
        verify()
        media_spec = cfg['media']
        if isinstance(media_spec, dict):
            deadline = time.monotonic() + 10
            candidates = []
            while time.monotonic() < deadline:
                candidates = []
                for item in region.locator(media_spec['selector']).all():
                    box = item.bounding_box()
                    if box and box['width'] >= media_spec['min_width'] and box['height'] >= media_spec['min_height']:
                        width = item.evaluate('e=>e.naturalWidth || e.videoWidth || 0')
                        if width >= media_spec['min_natural_width']:
                            candidates.append(item)
                if len(candidates) == 1:
                    break
                page.wait_for_timeout(100)
            if len(candidates) != 1:
                raise Failure('Full story media is absent or ambiguous')
            media = candidates[0]
        else:
            media = region.locator(media_spec)
        media.wait_for(state='visible')
        kind = media.evaluate('e => e.tagName.toLowerCase()')
        if kind not in ('img', 'video'):
            raise Failure('Story media selector must identify the full image or video')
        media.evaluate("e => {if(e.tagName==='IMG') e.loading='eager'; else e.pause()}")
        ready = media.evaluate('''async e => {
          const deadline=Date.now()+10000;
          while(Date.now()<deadline) {
            if(e.tagName==='IMG' && e.complete && e.naturalWidth>0) {await e.decode(); return true;}
            if(e.tagName==='VIDEO' && e.readyState>=2 && e.videoWidth>0 && !e.seeking) {
              e.pause(); return true;
            }
            await new Promise(r=>setTimeout(r,100));
          } return false;
        }''')
        if not ready:
            raise Failure('Story media failed to load')
        before = media.evaluate('e => e.currentTime || 0')
        page.wait_for_timeout(350)
        if kind == 'video' and abs(media.evaluate('e=>e.currentTime') - before) > .03:
            raise Failure('Video frame is unstable')
        verify()
        # CDP on a Chrome window moved between monitors may report a page DPR
        # different from the screenshot backing scale. Calibrate the clip so
        # the actual story, header and avatar are inside the saved PNG.
        probe = page.screenshot(type='png', clip={'x': 0, 'y': 0, 'width': 100, 'height': 100})
        backing_scale = int.from_bytes(probe[16:20], 'big') / 100
        ratio = page.evaluate('devicePixelRatio') / backing_scale
        if not .5 <= ratio <= 2:
            raise Failure('Browser screenshot scale is outside the supported range')
        box = region.bounding_box()
        if not box:
            raise Failure('Story region has no screenshot bounds')
        clip = {key: value * ratio for key, value in box.items()}
        png = page.screenshot(type='png', clip=clip, animations='allow',
                              style=cfg.get('screenshot_style'))
        verify()  # Discard bytes on auto-transition during screenshot.
        if kind == 'video' and abs(media.evaluate('e=>e.currentTime') - before) > .03:
            raise Failure('Video frame changed during screenshot')
        destination.write_bytes(png)
        destination.chmod(0o600)
        return 'video_frame' if kind == 'video' else 'image'
    finally:
        if held:
            page.mouse.up()


def require_access(page, ui):
    archive = ui['archive']
    if visible(page, archive.get('denied')):
        raise Failure('Community/archive access denied')
    if archive.get('api_path'):
        state = getattr(page, '_vk_archive', {})
        if state.get('errors'):
            raise Failure(state['errors'][0])
        if abs(int(archive['owner_id'])) not in state.get('groups', set()):
            raise Failure('Requested community is not confirmed by archive response')
    else:
        if not visible(page, ui['community']['selector']):
            raise Failure('Requested community is not confirmed')
        if read_value(page, ui['community']) != ui['community']['equals']:
            raise Failure('Unexpected community identity')
    if not visible(page, archive['ready']):
        raise Failure('Archive access is not confirmed')


def collect(page, args, ui, manifest, save):
    start, end = month_bounds(args.month, args.timezone)
    arc = ui['archive']
    traversal = Exhaustion()
    selected, processed = {}, set()
    day_badges = {}
    ordered_days = {}
    month_boundary = False
    if arc.get('descending_days'):
        if page.locator(arc['scroll']).evaluate('e=>e.scrollTop') != 0:
            raise Failure('Month traversal must start at the top of the archive')
    idle = 0
    renewals = 0
    for turn in range(args.max_scrolls):
        if visible(page, ui.get('auth', {}).get('required')):
            if renewals >= 1:
                raise Failure('Session expired again after one renewal; successful PNGs preserved')
            renewals += 1
            authenticate(page, args, ui, force=True)
            page.goto(args.url, wait_until='domcontentloaded')
            actions(page, arc.get('open', []))
            page.locator(arc['ready']).wait_for(state='visible')
            traversal.quiet = 0
            idle = 0
        require_access(page, ui)
        ids = []
        scan_days = []
        # Snapshot current cards before opening any viewer (which may rerender DOM).
        batch = []
        for index, element in enumerate(page.locator(arc['cards']).all()):
            try:
                ident = read_value(element, arc['identity'])
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', ident):
                    raise Failure('Story identifier is not safe or confirmed')
                raw_date = read_value(element, arc['date'])
                date = publication(raw_date, arc['date'], args.timezone)
                ids.append(ident)
                scan_days.append(date.date())
                ordered_days[ident] = date.date()
                if arc.get('descending_days') and date < start:
                    month_boundary = True
                    break
                badge_text = None
                if arc.get('preview_date'):
                    cfg = arc['preview_date']
                    badge = element.locator(cfg['selector'])
                    local_date = date.astimezone(ZoneInfo(cfg['timezone']))
                    day_key = local_date.date().isoformat()
                    if badge.count() == 1:
                        badge_text = ' '.join(badge.inner_text().split())
                        match = re.fullmatch(r'(\d{1,2})\s+(\S+)', badge_text)
                        month = cfg['months'].get(str(local_date.month))
                        if not match or int(match[1]) != local_date.day or (month and match[2] != month):
                            raise Failure('Preview date differs from publication date for the same story ID')
                        if month:
                            day_badges[day_key] = badge_text
                        else:
                            badge_text = None
                    else:
                        badge_text = day_badges.get(day_key)
                if not start <= date < end:
                    continue
                if arc.get('preview_date') and not badge_text:
                    raise Failure('Selected story date is not confirmed by a preview badge or same-day badge')
                if ident in selected and selected[ident] != date:
                    raise Failure('Conflicting dates for one story identifier')
                selected[ident] = date
                if ident not in processed:
                    batch.append({'id': ident, 'date': date, 'raw_date': raw_date,
                                  'preview_date': badge_text})
            except Exception as e:
                manifest['errors'].append({'stage': 'card', 'scan': turn, 'index': index,
                                            'error': safe_error(e)})
                save()
        if arc.get('descending_days') and scan_days != sorted(scan_days, reverse=True):
            raise Failure('Archive day order changed; month boundary cannot prove completeness')
        for card in batch:
            if card['id'] in processed:
                continue
            record = {'id': card['id'], 'date': card['date'].isoformat(),
                      'date_raw': card['raw_date'], 'preview_date': card.get('preview_date'),
                      'path': None, 'ok': False}
            try:
                # Locate by actual identity rather than a stale ordinal or day.
                matches = [el for el in page.locator(arc['cards']).all()
                           if read_value(el, arc['identity']) == card['id']]
                if len(matches) != 1:
                    raise Failure('Selected archive card disappeared or is ambiguous')
                matches[0].click()
                actual_zoom = check_zoom(page, args)
                destination = args.output / (card['date'].strftime('%Y-%m-%d') + '_'
                                              + card['id'] + '_' + time.strftime('%H%M%S')
                                              + '_' + os.urandom(3).hex() + '.png')
                record['kind'] = capture(page, card, ui, destination, args.timezone,
                                         getattr(args, 'approve_missing_avatar', ()))
                if 'author_verification' in card:
                    record['author_verification'] = card['author_verification']
                record.update(ok=True, path=str(destination.resolve()), browser_zoom=actual_zoom)
            except Exception as e:
                record['error'] = safe_error(e)
                manifest['errors'].append({'stage': 'capture', 'id': card['id'], 'error': record['error']})
            finally:
                processed.add(card['id'])
                manifest['stories'].append(record)
                save()
                emit(**record)
            # Closing must restore the same archive pagination/scroll position.
            if visible(page, ui['viewer']['region']):
                actions(page, ui['viewer']['close'])
            page.locator(arc['ready']).wait_for(state='visible')
        feed = getattr(page, '_vk_archive', None) if arc.get('api_path') else None
        loading = visible(page, arc.get('loading')) or bool(feed and feed['pending'])
        next_loc = page.locator(arc['next']) if arc.get('next') else None
        next_page = bool(next_loc is not None and next_loc.count() == 1
                         and next_loc.is_visible() and next_loc.is_enabled())
        terminal = visible(page, arc.get('end'))
        if terminal and feed is None:
            # The end marker may appear while a viewer is open. Include newly
            # loaded cards so they force another scan before declaring completion.
            ids.extend(read_value(el, arc['identity']) for el in page.locator(arc['cards']).all())
        if feed is not None:
            terminal = (feed['count'] is not None and len(traversal.seen | set(ids)) == feed['count']
                        and len(feed['items']) == feed['count'])
            if arc.get('descending_days') and month_boundary:
                known_month = {ident for ident, item in feed['items'].items()
                               if start <= publication(str(item['date']), arc['date'], args.timezone) < end}
                terminal = known_month <= processed
        old_count = len(traversal.seen)
        if traversal.observe(ids, terminal, loading, next_page):
            manifest['traversal_complete'] = True
            manifest['completion_evidence'] = {'end_selector': arc.get('end'),
                'stable_checks': traversal.quiet, 'unique_archive_ids': len(traversal.seen)}
            if feed is not None:
                manifest['completion_evidence'].update(server_count=feed['count'],
                    received_ids=len(feed['items']), api_path=arc['api_path'])
            if arc.get('descending_days') and month_boundary:
                manifest['completion_evidence'].update(method='descending_days_month_boundary',
                    boundary=min(day.isoformat() for day in ordered_days.values()),
                    scope='requested_month_only')
            break
        idle = idle + 1 if len(traversal.seen) == old_count and not loading else 0
        if idle >= args.stall_checks:
            raise Failure('Archive stalled without confirmed end; completeness unknown')
        if arc.get('descending_days') and month_boundary:
            pass  # Confirm a stable month boundary without scrolling into older history.
        elif next_page:
            next_loc.click()
            traversal.quiet = 0
        else:
            scroll = page.locator(arc['scroll'])
            if scroll.count() != 1:
                raise Failure('Archive scroll container is absent or ambiguous')
            scroll.evaluate('e => e.scrollBy(0, Math.max(200,e.clientHeight*.8))')
        page.wait_for_timeout(args.settle)
    else:
        raise Failure('Archive traversal reached max-scrolls; completeness unknown')
    manifest['complete'] = manifest['traversal_complete'] and not manifest['errors']
    save()


def safe_error(error):
    # Playwright call logs may contain typed credentials, tokens or page HTML.
    return str(error) if isinstance(error, Failure) else 'Operation failed: ' + type(error).__name__


def load_ui(path):
    if not path or not path.exists():
        raise Failure('Archive UI not yet observed: run inspect, then supply --ui (see references/ui.md)')
    ui = json.loads(path.read_text())
    if not ui.get('observed_at') or not ui.get('evidence'):
        raise Failure('UI map requires observation date and local evidence paths')
    return ui


def resolve_ui(ui, url):
    if not ui.get('archive', {}).get('api_path'):
        return ui
    section = parse_qs(urlsplit(url).query).get('w', [''])[0]
    match = re.fullmatch(r'stories(-?[1-9]\d*)', section)
    if not match:
        raise Failure('Observed archive UI requires a section URL with w=storiesOWNER')
    ui['archive']['owner_id'] = int(match[1])
    return ui


def run(args):
    private_dir(AUTH.parent)
    if args.command == 'credentials':
        if not sys.stdin.isatty():
            raise Failure('Run credentials in a local interactive terminal; never send password in chat')
        login = input('VK login: ').strip()
        password = getpass.getpass('VK password (hidden): ')
        if not login or not password:
            raise Failure('Empty credentials')
        save_json(args.credentials, {'login': login, 'password': password}, private=True)
        emit(ok=True, kind='credentials_saved')
        return 0
    with access('vk-stories-screenshot'):
        source_url(args.url)
        if args.command == 'capture':
            month_bounds(args.month, args.timezone)
            args.output = (args.output or AUTH.parent / 'outputs' / 'vk-stories' / args.month).resolve()
            private_dir(args.output)
            path = args.output / ('manifest-' + time.strftime('%Y%m%d-%H%M%S') + '-'
                                  + os.urandom(3).hex() + '.json')
            manifest = {'source': args.url, 'month': args.month, 'timezone': args.timezone,
                        'started_at': datetime.now(timezone.utc).isoformat(), 'complete': False,
                        'traversal_complete': False, 'stories': [], 'errors': [],
                        'approved_missing_avatars': getattr(args, 'approve_missing_avatar', [])}
            def save():
                save_json(path, manifest)
            save()
            try:
                ui = resolve_ui(load_ui(args.ui), args.url)
                with session(args) as page:
                    if ui['archive'].get('api_path'):
                        watch_archive(page, ui)
                    page.goto(args.url, wait_until='domcontentloaded')
                    already_authenticated = visible(page, ui.get('auth', {}).get('ready'))
                    authenticate(page, args, ui)
                    if not already_authenticated:
                        if ui['archive'].get('api_path'):
                            page._vk_archive['pending'].clear()
                        page.goto(args.url, wait_until='domcontentloaded')
                    actions(page, ui['archive'].get('open', []))
                    check_zoom(page, args)
                    page.locator(ui['archive']['ready']).wait_for(state='visible')
                    if ui['archive'].get('api_path'):
                        deadline = time.monotonic() + args.timeout / 1000
                        while page._vk_archive['count'] is None and time.monotonic() < deadline:
                            page.wait_for_timeout(200)
                    collect(page, args, ui, manifest, save)
            except BaseException as e:
                manifest['errors'].append({'stage': 'run', 'error': safe_error(e)})
                manifest['complete'] = False
            finally:
                save()
                emit(ok=manifest['complete'], kind='manifest', complete=manifest['complete'],
                     traversal_complete=manifest['traversal_complete'], path=str(path),
                     captured=sum(s['ok'] for s in manifest['stories']), errors=manifest['errors'])
            return 0 if manifest['complete'] else 1
        ui = load_ui(args.ui) if args.command == 'login' else (
            load_ui(args.ui) if args.ui and args.ui.exists() else {})
        with session(args) as page:
            page.goto(args.url, wait_until='domcontentloaded')
            if args.command == 'login':
                authenticate(page, args, ui, force=True)
                emit(ok=True, kind='login', authenticated=True)
            else:
                if args.wait:
                    page.wait_for_timeout(args.wait * 1000)
                check_zoom(page, args)
                inspect(page, args.output or AUTH / 'inspection')
        return 0


def positive(value):
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError('Use a positive integer')
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['credentials', 'inspect', 'login', 'capture'])
    parser.add_argument('url', nargs='?', default='https://vk.ru')
    parser.add_argument('--month')
    parser.add_argument('--timezone', default='Europe/Moscow')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--approve-missing-avatar', action='append', default=[], metavar='OWNER_ID_STORY_ID',
                        help='Explicit user approval for one verified story with an unloaded avatar; repeat per ID')
    connection = parser.add_mutually_exclusive_group()
    connection.add_argument('--cdp')
    connection.add_argument('--profile', type=Path)
    parser.add_argument('--channel', default='chrome', choices=['chrome', 'chromium', 'msedge'])
    parser.add_argument('--credentials', type=Path, default=AUTH / 'credentials.json')
    parser.add_argument('--ui', type=Path, default=AUTH / 'vk-ui.json')
    parser.add_argument('--timeout', type=positive, default=30000)
    parser.add_argument('--login-wait', type=positive, default=120)
    parser.add_argument('--max-scrolls', type=positive, default=300)
    parser.add_argument('--stall-checks', type=positive, default=8)
    parser.add_argument('--settle', type=positive, default=1200)
    parser.add_argument('--wait', type=int, default=5, help='inspect wait in seconds (0..120)')
    add_zoom_argument(parser)
    args = parser.parse_args()
    if args.profile is None:
        args.cdp = args.cdp or os.environ.get('VK_CDP_URL') or SHARED_CDP
    if args.command == 'capture' and not args.month:
        parser.error('capture requires --month YYYY-MM')
    if args.approve_missing_avatar and (args.command != 'capture' or any(
            not re.fullmatch(r'-?[1-9]\d*_[1-9]\d*', ident) for ident in args.approve_missing_avatar)):
        parser.error('--approve-missing-avatar requires capture and full numeric OWNER_ID_STORY_ID')
    if not 0 <= args.wait <= 120 or args.login_wait > 300 or args.stall_checks < 4:
        parser.error('wait must be 0..120, login-wait <=300, stall-checks >=4')
    try:
        outside_package(args.credentials)
        outside_package(args.ui)
        if args.profile:
            outside_package(args.profile)
        if args.output:
            outside_package(args.output)
        return run(args)
    except BaseException as e:
        emit(ok=False, error=safe_error(e))
        return 1


if __name__ == '__main__':
    sys.exit(main())

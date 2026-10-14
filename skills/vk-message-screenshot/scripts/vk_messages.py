#!/usr/bin/env python3
"""Capture community VK conversations through the existing external browser."""
import argparse
import base64
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from ui_queue import access
from private_paths import outside_package
from browser_zoom import add_zoom_argument
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STORIES = ROOT.parent / 'vk-stories-screenshot'
sys.path.insert(0, str(STORIES / 'scripts'))
import vk_stories as shared

MESSAGE = '''e => {
  let f=e[Object.keys(e).find(k=>k.startsWith('__reactFiber$'))];
  for(let i=0;f&&i<20;i++,f=f.return) {
    const m=f.memoizedProps?.message;
    if(m) return {cmid:m.cmid,peerId:m.peerId,sentAt:m.sentAt,
      authorId:m.authorId,isOut:m.isOut,kind:m.kind,updatedAt:m.updatedAt};
  } throw Error('Observed message props changed');
}'''
CONVERSATION = '''e => {
  let f=e[Object.keys(e).find(k=>k.startsWith('__reactFiber$'))],r={
    ident:e.getAttribute('data-peer-id'),name:(e.innerText||'').split('\\n')[0]};
  for(let i=0;f&&i<20;i++,f=f.return) {
    const p=f.memoizedProps;
    if(p?.convo)r.peer={id:p.convo.peerId,timestamp:p.convo.timestamp};
    if(p?.selectedOrganiser?.ids)r.list={ids:p.selectedOrganiser.ids,hasMore:p.selectedOrganiser.hasMore};
  } return r;
}'''


def period(since, until, tz):
    if not all(re.fullmatch(r'\d{4}-\d{2}-\d{2}', d or '') for d in (since, until)):
        raise shared.Failure('Use complete dates YYYY-MM-DD, including the year')
    zone = ZoneInfo(tz)
    start = datetime.fromisoformat(since).replace(tzinfo=zone)
    end = datetime.fromisoformat(until).replace(tzinfo=zone) + timedelta(days=1)
    if start >= end:
        raise shared.Failure('Period start must not follow its end')
    return start, end


def zoom_clip(box, zoom):
    if (not math.isfinite(zoom) or not 0 < zoom <= 5
            or any(not math.isfinite(box[k]) for k in ('x','y','width','height'))
            or min(box['width'], box['height']) <= 0):
        raise shared.Failure('Screenshot geometry is invalid')
    return {**{k: box[k] * zoom for k in ('x','y','width','height')}, 'scale':1}


def segments(height, page_height, overlap=48):
    if not math.isfinite(height) or height <= 0 or page_height <= overlap:
        raise shared.Failure('Screenshot page geometry is invalid')
    y = 0
    while y < height:
        size = min(page_height, height-y)
        yield y, size
        if y+size >= height:
            break
        y += page_height-overlap


def response_bodies(body):
    if not isinstance(body, dict):
        return
    if isinstance(body.get('response'), dict):
        yield body['response']
    for item in body.get('responses', []):
        if isinstance(item, dict):
            yield from response_bodies(item.get('body'))


class History:
    def __init__(self, peer):
        self.peer = peer
        self.count = None
        self.items = {}
        self.groups = {}
        self.pending = set()
        self.errors = []
        self.ordered = True

    def relevant(self, request):
        return urlsplit(request.url).path == '/method/messages.getHistory'

    def requested(self, request):
        if self.relevant(request):
            self.pending.add(request)

    def failed(self, request):
        if self.relevant(request):
            self.pending.discard(request)
            self.errors.append('History network request failed')

    def ingest(self, data):
        items = data['items']
        if any(item['peer_id'] != self.peer for item in items):
            return
        if type(data['count']) is not int or data['count'] < 0:
            raise shared.Failure('History count format changed')
        if self.count is not None and self.count != data['count']:
            raise shared.Failure('History changed during capture')
        self.count = data['count']
        for item in items:
            record = {k:item[k] for k in ('id','date','peer_id','from_id','out','conversation_message_id')}
            record['is_hidden'] = bool(item.get('is_hidden', False))
            cmid = record['conversation_message_id']
            if type(cmid) is not int or cmid <= 0 or type(record['date']) is not int:
                raise shared.Failure('History identity/date format changed')
            if cmid in self.items and self.items[cmid] != record:
                raise shared.Failure('One message changed during capture')
            self.items[cmid] = record
        self.groups.update({g['id']:g['name'] for g in data.get('groups', [])})
        dates = [item['date'] for _,item in sorted(self.items.items(),reverse=True)]
        self.ordered = dates == sorted(dates,reverse=True)

    def received(self, response):
        path = urlsplit(response.url).path
        if path not in ('/method/messages.getHistory','/method/batch.call'):
            return
        try:
            found = False
            for data in response_bodies(response.json()):
                items = data.get('items')
                if 'count' in data and isinstance(items,list) and (
                        path == '/method/messages.getHistory' or
                        (items and isinstance(items[0],dict) and 'conversation_message_id' in items[0])):
                    self.ingest(data)
                    found = True
            if path == '/method/messages.getHistory' and not found:
                raise shared.Failure('History API returned an error; access unconfirmed')
        except Exception as error:
            self.errors.append(shared.safe_error(error))
        finally:
            self.pending.discard(response.request)

    def attach(self, page):
        for event, callback in (('request',self.requested),('requestfailed',self.failed),('response',self.received)):
            page.on(event, callback)

    def detach(self, page):
        for event, callback in (('request',self.requested),('requestfailed',self.failed),('response',self.received)):
            page.remove_listener(event, callback)


def rows(page, peer, feed):
    result = []
    for node in page.locator('.ConvoHistory__messageBlock').all():
        data = node.evaluate('e=>{const d=('+MESSAGE+')(e);return {...d,render_text:e.textContent}}')
        server = feed.items.get(data['cmid'])
        if (data['peerId'] != peer or not server or server['date']*1000 != data['sentAt']
                or server['from_id'] != data['authorId'] or bool(server['out']) != data['isOut']):
            raise shared.Failure('DOM message does not match the received history')
        data['render_hash'] = hashlib.sha256((data.pop('render_text') or '').encode()).hexdigest()
        result.append((node,data,server))
    return result


def history_complete(feed, processed, start, end):
    expected = {cmid for cmid,item in feed.items.items() if start <= item['date'] < end}
    boundary = feed.ordered and any(item['date'] < start for item in feed.items.values())
    whole = feed.count is not None and len(feed.items) == feed.count
    return (whole or boundary) and not feed.pending and expected <= processed


def observed_dom(page, feed):
    """VK may display cached messages without requesting history; never infer a count."""
    for node in page.locator('.ConvoHistory__messageBlock').all():
        data=node.evaluate(MESSAGE)
        if (data['peerId'] != feed.peer or type(data['cmid']) is not int or data['cmid']<=0
                or type(data['sentAt']) is not int or data['sentAt'] % 1000
                or type(data['authorId']) is not int or type(data['isOut']) is not bool):
            raise shared.Failure('Cached DOM message identity/date is unconfirmed')
        feed.items[data['cmid']]={'id':None,'date':data['sentAt']//1000,'peer_id':feed.peer,
            'from_id':data['authorId'],'out':int(data['isOut']),
            'conversation_message_id':data['cmid'],'verification_source':'observed_dom'}


def capture_batch(page, args, group, peer, feed, start, end, scan, write):
    shared.check_zoom(page, args)
    page.mouse.move(1,1)
    page.wait_for_timeout(250)
    current = rows(page,peer,feed)
    wanted = [item for item in current if start <= item[2]['date'] < end]
    before = [data for _,data,_ in wanted]
    if not wanted:
        return set()
    css = None
    styles = None
    flow = page.locator('.ConvoHistory__flow')
    try:
        for node,_,server in current:
            if not start <= server['date'] < end:
                node.evaluate('e=>e.setAttribute("data-vk-message-excluded", "")')
        page.locator('.ConvoHistory__dateStack').evaluate_all('''els=>els.forEach(e=>{
          if(!e.querySelector('.ConvoHistory__messageBlock:not([data-vk-message-excluded])'))
            e.setAttribute('data-vk-message-excluded','');
        })''')
        css = page.add_style_tag(content='[data-vk-message-excluded] {display:none!important}')
        styles = flow.evaluate_handle('''e=>{
          const saved=[];
          for(let p=e;p&&p!==document.body;p=p.parentElement) {
            saved.push([p,p.getAttribute('style')]);
            if(p!==e)for(const [k,v]of Object.entries({overflow:'visible',height:'auto','min-height':'0','max-height':'none'}))
              p.style.setProperty(k,v,'important');
          }
          e.parentElement.style.setProperty('display','block','important');
          e.style.setProperty('justify-content','flex-start','important');
          return saved;
        }''')
        ready = flow.evaluate('''async e=>{
          const images=[...e.querySelectorAll('img')].filter(i=>i.getBoundingClientRect().height>0);
          images.forEach(i=>i.loading='eager');
          for(const v of e.querySelectorAll('video'))v.pause();
          await Promise.race([Promise.all([document.fonts.ready,...images.map(i=>i.decode().catch(()=>{}))]),
            new Promise(r=>setTimeout(r,10000))]);
          return images.every(i=>i.complete&&i.naturalWidth>0);
        }''')
        if not ready:
            raise shared.Failure('A visible image failed to load')
        light = flow.evaluate(r'''e=>{
          for(let p=e;p;p=p.parentElement){
            const c=getComputedStyle(p).backgroundColor.match(/[\d.]+/g)?.map(Number);
            if(c&&c.length>=3&&(c.length<4||c[3]>0))return .2126*c[0]+.7152*c[1]+.0722*c[2]>180;
          }return false;
        }''')
        if not light:
            raise shared.Failure('Light VK theme is unconfirmed; select the native light theme in the external browser')
        page.mouse.move(1,1)
        page.wait_for_timeout(250)
        box = flow.bounding_box()
        if not box or box['height'] > 100000:
            raise shared.Failure('Rendered history height is invalid or exceeds the limit')
        rects = {server['conversation_message_id']:node.bounding_box() for node,_,server in wanted}
        cdp = page.context.new_cdp_session(page)
        saved = []
        try:
            zoom = cdp.send('Page.getLayoutMetrics')['cssVisualViewport']['zoom']
            for part,(offset,height) in enumerate(segments(box['height'],args.page_height),1):
                rect = {**box,'y':box['y']+offset,'height':height}
                ids = sorted(cmid for cmid,r in rects.items() if r and
                    r['y'] < rect['y']+height and r['y']+r['height'] > rect['y'])
                if not ids:
                    continue
                response = cdp.send('Page.captureScreenshot', {'format':'png','captureBeyondViewport':True,
                    'clip':zoom_clip(rect,zoom)})
                saved.append((part,offset,ids,base64.b64decode(response['data'])))
        finally:
            cdp.detach()
        after = [data for _,data,server in rows(page,peer,feed) if start <= server['date'] < end]
        if before != after or urlsplit(page.url).path != f'/gim{group}/convo/{peer}':
            raise shared.Failure('Conversation changed during capture; PNG bytes discarded')
        for part,offset,ids,png in saved:
            filename = (f'vk_messages_{group}_{peer}_{args.since}_{args.until}_s{scan:03}_p{part:03}_'
                        + time.strftime('%H%M%S')+'_'+os.urandom(3).hex()+'.png')
            target = args.output/filename
            target.write_bytes(png)
            os.chmod(target,0o600)
            write({'path':str(target.resolve()),'message_ids':ids,'scan':scan,'part':part,
                   'top_offset':offset,'browser_zoom':zoom})
        return {item[2]['conversation_message_id'] for item in wanted}
    finally:
        if styles is not None:
            try:
                styles.evaluate('s=>s.forEach(([e,a])=>a===null?e.removeAttribute("style"):e.setAttribute("style",a))')
            finally:
                styles.dispose()
        if css is not None:
            css.evaluate('e=>e.remove()')
        page.locator('[data-vk-message-excluded]').evaluate_all('els=>els.forEach(e=>e.removeAttribute("data-vk-message-excluded"))')


def navigate(page, url, args):
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    page.goto(url,wait_until='domcontentloaded')
    try:
        page.locator('[data-testid=header-profile-menu-button]').wait_for(
            state='visible',timeout=min(args.timeout,10000))
    except PlaywrightTimeout:
        if args.renewals >= 1:
            raise shared.Failure('Session requires another login; successful PNGs preserved')
        args.renewals += 1
        ui = shared.load_ui(args.auth_ui)
        shared.authenticate(page,args,ui)
        page.goto(url,wait_until='domcontentloaded')
    shared.check_zoom(page, args)


def list_peers(page,args,start):
    peers = {}
    quiet = 0
    known = set()
    for scan in range(args.max_scrolls):
        previous = len(peers)
        nodes = page.locator('[data-testid=vkme_convo_list_item]').evaluate_all('els=>els.map('+CONVERSATION+')')
        if not nodes:
            return peers,False,'Conversation rows absent; empty list/access unconfirmed'
        for data in nodes:
            peer = data.get('peer',{})
            ident = data.get('ident')
            if str(peer.get('id')) != ident or type(peer.get('timestamp')) is not int:
                return peers,False,'Conversation list identity/date is unconfirmed'
            state = data.get('list',{})
            if type(state.get('hasMore')) is not bool:
                return peers,False,'Conversation list continuation is unconfirmed'
            known = {x['id'] for x in state['ids'] if x.get('kind') == 'convo'}
            peers[peer['id']] = peer
            peers[peer['id']]['name'] = data['name']
            if len(peers) > args.max_dialogs:
                return peers,False,'Conversation list reached max-dialogs; completeness unknown'
        quiet = quiet+1 if len(peers)==previous else 0
        if peers and not state['hasMore'] and known <= peers.keys() and quiet>=3:
            return peers,True,None
        if quiet>=8:
            return peers,False,'Conversation list stalled before a confirmed end'
        page.locator('.ConvoList__itemsWrapper').evaluate('e=>e.scrollBy(0,Math.max(200,e.clientHeight*.7))')
        page.wait_for_timeout(args.settle)
    return peers,False,'Conversation list reached max-scrolls; completeness unknown'


def collect_peer(page,args,group,peer,start,end,result,save):
    feed = History(peer)
    feed.attach(page)
    processed = set()
    quiet = 0
    seen = set()
    try:
        navigate(page,f'https://vk.ru/gim{group}/convo/{peer}',args)
        deadline = time.monotonic()+args.timeout/1000
        while feed.count is None and not feed.errors and time.monotonic()<deadline:
            page.wait_for_timeout(100)
        if feed.errors:
            raise shared.Failure(feed.errors[0])
        page.locator('.ConvoHeader').wait_for()
        result['peer_name'] = page.locator('.ConvoHeader').inner_text().splitlines()[0]
        def write(frame):
            result['screenshots'].append(frame)
            save()
            shared.emit(ok=True,kind='screenshot',peer_id=peer,**frame)
        if feed.count is None:
            observed_dom(page,feed)
            processed.update(capture_batch(page,args,group,peer,feed,start,end,0,write))
            raise shared.Failure('History count/period completeness unconfirmed; available in-period DOM screenshots preserved')
        for scan in range(args.max_scrolls):
            if feed.errors:
                raise shared.Failure(feed.errors[0])
            current = rows(page,peer,feed)
            fresh = {data['cmid'] for _,data,server in current if start <= server['date'] < end} - processed
            if fresh:
                covered = capture_batch(page,args,group,peer,feed,start,end,scan,write)
                processed.update(covered)
            all_ids = set(feed.items)
            quiet = quiet+1 if all_ids==seen and not feed.pending else 0
            seen = all_ids
            if history_complete(feed,processed,start,end) and quiet>=3:
                result.update(complete=True,completion_evidence={
                    'history_count':feed.count,'received_messages':len(feed.items),'stable_checks':quiet,
                    'method':'whole_history' if len(feed.items)==feed.count else 'older_than_period_boundary'})
                break
            if quiet>=8:
                raise shared.Failure('History stalled before confirmed period coverage; successful PNGs preserved')
            if not history_complete(feed,processed,start,end):
                page.locator('.ConvoHistory__scrollbar').evaluate('e=>e.scrollBy(0,-Math.max(200,e.clientHeight*.7))')
            page.wait_for_timeout(args.settle)
        else:
            raise shared.Failure('History reached max-scrolls; completeness unknown')
    finally:
        result['messages'] = [{**item,'date_iso':datetime.fromtimestamp(item['date'],timezone.utc)
            .astimezone(ZoneInfo(args.timezone)).isoformat(),'captured':cmid in processed}
            for cmid,item in sorted(feed.items.items()) if start <= item['date'] < end]
        result['screenshots'].sort(key=lambda f:(min(f['message_ids']),f['top_offset']))
        feed.detach(page)
        save()


def positive(value):
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError('Use a positive integer')
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--peer',type=positive,action='append')
    selection.add_argument('--all',action='store_true')
    parser.add_argument('--list-only',action='store_true')
    dates = parser.add_mutually_exclusive_group(required=True)
    dates.add_argument('--month')
    dates.add_argument('--from',dest='since')
    parser.add_argument('--to',dest='until')
    parser.add_argument('--timezone',default='Europe/Moscow')
    connection = parser.add_mutually_exclusive_group()
    connection.add_argument('--cdp')
    connection.add_argument('--profile',type=Path)
    parser.set_defaults(channel='chrome')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--page-height',type=positive,default=2200)
    parser.add_argument('--max-scrolls',type=positive,default=100)
    parser.add_argument('--max-dialogs',type=positive,default=500)
    parser.add_argument('--settle',type=positive,default=700)
    parser.add_argument('--timeout',type=positive,default=20000)
    parser.add_argument('--login-wait',type=positive,default=120)
    parser.add_argument('--credentials',type=Path,default=shared.AUTH/'credentials.json')
    parser.add_argument('--auth-ui',type=Path,default=shared.AUTH/'vk-ui.json')
    add_zoom_argument(parser)
    args = parser.parse_args()
    if args.profile is None:
        args.cdp = args.cdp or os.environ.get('VK_CDP_URL') or shared.SHARED_CDP
    try:
        outside_package(args.credentials)
        outside_package(args.auth_ui)
        if args.profile:
            outside_package(args.profile)
        if args.output:
            outside_package(args.output)
        shared.source_url(args.source)
        if args.list_only and not args.all:
            raise shared.Failure('--list-only requires --all')
        if args.month:
            if args.until:
                raise shared.Failure('Use either --month or --from/--to')
            first,last = shared.month_bounds(args.month,args.timezone)
            args.since,args.until = first.date().isoformat(),(last-timedelta(days=1)).date().isoformat()
        first,last = period(args.since,args.until,args.timezone)
        if not 300<=args.page_height<=10000 or args.login_wait>300:
            raise shared.Failure('page-height must be 300..10000; login-wait at most 300')
    except Exception as error:
        shared.emit(ok=False,error=shared.safe_error(error))
        return 1
    start,end = first.timestamp(),last.timestamp()
    args.output = (args.output or shared.AUTH.parent/'outputs/vk-message-screenshots'/f'{args.since}_{args.until}').resolve()
    shared.private_dir(args.output)
    args.renewals = 0
    manifest = {'source':args.source,'from':args.since,'to':args.until,'timezone':args.timezone,
        'theme':'light','scope':'all_dialogs' if args.all else 'explicit_peers',
        'operation':'list_peers' if args.list_only else 'capture',
        'created_at':datetime.now(timezone.utc).isoformat(),'complete':False,
        'conversation_list_complete':not args.all,'results':[],'errors':[]}
    path=args.output/('manifest-'+time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(3).hex()+'.json')
    def save():
        shared.save_json(path,manifest)
    save()
    with access('vk-message-screenshot'):
        try:
            with shared.session(args) as page:
                page.emulate_media(color_scheme='light')
                navigate(page,args.source,args)
                manage=page.locator('[data-testid=group_manage_menu_gim]')
                try:
                    manage.wait_for(state='visible')
                except Exception:
                    raise shared.Failure('Community inbox link absent; access unconfirmed') from None
                match=re.fullmatch(r'/gim([1-9]\d*)',manage.get_attribute('href') or '')
                if not match:
                    raise shared.Failure('Group inbox link/access is unconfirmed')
                group=int(match[1]);manifest['group_id']=group
                navigate(page, 'https://vk.ru' + match.group(0), args)
                page.locator('[data-testid=me_convo_list]').wait_for()
                manifest['group_name']=page.title().removeprefix('Мессенджер: ')
                peers=args.peer
                if args.all:
                    list_peers_result,complete,error=list_peers(page,args,start)
                    manifest['conversation_list_complete']=complete
                    manifest['listed_dialogs']=len(list_peers_result)
                    if error:
                        manifest['errors'].append({'stage':'list','error':error})
                    peers=[ident for ident,data in list_peers_result.items() if data['timestamp']>=start]
                    if args.list_only:
                        manifest['peers']=[{'peer_id':ident,'name':data['name'],'last_message_at':
                            datetime.fromtimestamp(data['timestamp'],timezone.utc).astimezone(ZoneInfo(args.timezone)).isoformat()}
                            for ident,data in list_peers_result.items() if data['timestamp']>=start]
                        for candidate in manifest['peers']:
                            shared.emit(kind='peer_candidate',**candidate)
                        peers=[]
                for peer in dict.fromkeys(peers):
                    result={'peer_id':peer,'complete':False,'screenshots':[],'messages':[],'errors':[]}
                    manifest['results'].append(result)
                    try:
                        collect_peer(page,args,group,peer,start,end,result,save)
                    except Exception as error:
                        result['errors'].append(shared.safe_error(error))
                        result['complete']=False
                        manifest['errors'].append({'stage':'peer','peer_id':peer,'error':shared.safe_error(error)})
                    finally:
                        save()
                        shared.emit(kind='peer',ok=result['complete'],peer_id=peer,
                            messages=len(result['messages']),screenshots=len(result['screenshots']),errors=result['errors'])
                manifest['complete']=manifest['conversation_list_complete'] and not manifest['errors'] and all(
                    r['complete'] for r in manifest['results'])
        except BaseException as error:
            manifest['errors'].append({'stage':'run','error':shared.safe_error(error)})
            manifest['complete']=False
        finally:
            save()
            shared.emit(kind='manifest',path=str(path),ok=manifest['complete'],complete=manifest['complete'],
                screenshots=sum(len(r['screenshots']) for r in manifest['results']),errors=manifest['errors'])
        return 0 if manifest['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

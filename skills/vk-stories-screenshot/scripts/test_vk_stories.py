#!/usr/bin/env python3
"""Offline checks. Synthetic DOM is not evidence about VK selectors or login."""
import json
import os
import tempfile
import socket
import subprocess
import sys
import contextlib
import io
import copy
from unittest.mock import patch
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import vk_stories as v
from playwright.sync_api import sync_playwright

HTML = '''<!doctype html><meta charset="utf-8">
<style>#viewer{width:360px;height:640px;background:#ccc}img{width:300px;height:400px}</style>
<div id="community" data-id="-103">Community</div>
<div id="archive" style="height:200px;overflow:auto"><div id="cards"></div><div style="height:600px"></div><span id="end" hidden>End</span></div>
<div id="viewer" hidden><span id="author">Community</span><time id="date"></time><button id="pause">Pause</button><span id="paused" hidden>Paused</span><img id="media"><button id="close">Close</button></div>
<script>
const source=[['a','2026-09-02T10:00:00+03:00'],['b','2026-09-02T11:00:00+03:00'],['c','2026-09-30T23:59:59+03:00']];
const pixel='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1sAAAAASUVORK5CYII=';
function add(i){const [id,date]=source[i];const el=document.createElement('button');el.className='card';el.dataset.id=id;el.dataset.date=date;el.textContent=id;el.onclick=()=>{
 document.querySelector('#archive').hidden=true; const view=document.querySelector('#viewer');view.hidden=false;view.dataset.id=id;
 const d=document.querySelector('#date');d.dateTime=date;d.textContent=date;
 document.querySelector('#paused').hidden=true;document.querySelector('#media').src=(window.failId===id)?'/missing.png':pixel;
 if(window.switchId===id)setTimeout(()=>view.dataset.id='neighbor',180);
};document.querySelector('#cards').append(el)}
add(0);add(1);
let scrolled=false;document.querySelector('#archive').onscroll=()=>{if(!scrolled){scrolled=true;setTimeout(()=>{add(2);document.querySelector('#end').hidden=false},350)}};
document.querySelector('#pause').onclick=()=>document.querySelector('#paused').hidden=false;
document.querySelector('#close').onclick=()=>{document.querySelector('#viewer').hidden=true;document.querySelector('#archive').hidden=false};
</script>'''

UI = {'community': {'selector': '#community', 'attribute': 'data-id', 'equals': '-103'},
      'archive': {'ready': '#archive', 'cards': '.card',
                  'identity': {'attribute': 'data-id'},
                  'date': {'attribute': 'data-date', 'format': 'iso'},
                  'end': '#end', 'scroll': '#archive', 'denied': '#denied'},
      'viewer': {'region': '#viewer', 'identity': {'attribute': 'data-id'},
                 'date': {'selector': '#date', 'attribute': 'datetime', 'format': 'iso'},
                 'visible_date': '#date', 'author': '#author', 'media': '#media',
                 'pause': [{'action': 'click', 'selector': '#pause'}], 'paused': '#paused',
                 'close': [{'action': 'click', 'selector': '#close'}]}}


def check():
    # CLI defaults share one CDP browser; a separate profile must be explicit.
    for options, environment, expected_cdp, expected_profile in (
        ([], {}, v.SHARED_CDP, None),
        ([], {'VK_CDP_URL':'http://localhost:9333'}, 'http://localhost:9333', None),
        (['--cdp','http://localhost:9444'], {'VK_CDP_URL':'http://localhost:9333'},
         'http://localhost:9444', None),
        (['--profile','/tmp/vk-explicit-profile'], {'VK_CDP_URL':'http://localhost:9333'},
         None, Path('/tmp/vk-explicit-profile')),
    ):
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(sys, 'argv', ['vk_stories.py','inspect']+options), \
             patch.object(v, 'run', return_value=0) as run:
            assert v.main()==0
            args=run.call_args.args[0]
            assert args.cdp==expected_cdp and args.profile==expected_profile
    start, end = v.month_bounds('2026-09', 'Europe/Moscow')
    dates = ['2026-08-31T20:59:59Z', '2026-08-31T21:00:00Z',
             '2026-09-30T20:59:59Z', '2026-09-30T21:00:00Z']
    assert [start <= v.publication(d, {'format': 'iso'}, 'Europe/Moscow') < end
            for d in dates] == [False, True, True, False]
    assert v.month_bounds('2024-02', 'UTC')[1].day == 1
    assert (v.month_bounds('2024-02', 'UTC')[1] - v.month_bounds('2024-02', 'UTC')[0]).days == 29
    assert v.month_bounds('2026-12', 'UTC')[1].year == 2027
    try:
        v.publication('02.09', {'format': '%d.%m'}, 'Europe/Moscow')
        assert False
    except v.Failure:
        pass
    state = v.Exhaustion()
    assert not state.observe(['a'], False, False, False)
    assert not state.observe(['a'], False, False, False)
    assert not state.observe(['a'], False, False, False)
    assert not state.observe(['a','b'], True, True, False)
    assert not state.observe(['a','b'], True, False, True)
    assert not state.observe(['a','b'], True, False, False)
    assert not state.observe(['a','b'], True, False, False)
    assert state.observe(['a','b'], True, False, False)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        missing = Namespace(command='capture',url='https://vk.ru/fixture-community?w=stories-103',
                            month='2026-09',timezone='Europe/Moscow',output=root/'missing-ui',
                            ui=root/'nonexistent.json')
        with contextlib.redirect_stdout(io.StringIO()):
            assert v.run(missing) == 1
        failed_manifest = json.loads(next(missing.output.glob('manifest-*.json')).read_text(encoding="utf-8"))
        assert failed_manifest['source'] == missing.url and failed_manifest['errors']
        assert not failed_manifest['complete'] and not failed_manifest['stories']
        marker = root / 'private-marker.json'
        v.save_json(marker, {'synthetic': True}, private=True)
        assert marker.stat().st_mode & 0o777 == 0o600
        try:
            v.run(Namespace(command='credentials'))
            assert False, 'Plaintext password enrollment must be refused'
        except v.Failure:
            pass
        with sync_playwright() as p:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0))
                port = sock.getsockname()[1]
            browser = p.chromium.launch(channel='chrome', headless=True,
                                        args=[f'--remote-debugging-port={port}'])
            page = browser.new_page()
            old_pages = len(browser.contexts[0].pages)
            # Separate process: sync Playwright contexts cannot be nested.
            cdp_check = subprocess.run([sys.executable, '-c',
                "from argparse import Namespace\nimport sys\nimport vk_stories as v\n"
                "with v.session(Namespace(cdp=sys.argv[1],timeout=3000)) as page:\n"
                "    page.set_content('<body>CDP fixture</body>')\n",
                f'http://127.0.0.1:{port}'], cwd=Path(__file__).parent,
                capture_output=True, text=True, timeout=15)
            assert cdp_check.returncode == 0, cdp_check.stderr
            assert browser.is_connected() and len(browser.contexts[0].pages) == old_pages
            with socket.socket() as unavailable:
                unavailable.bind(('127.0.0.1',0))
                failed=subprocess.run([sys.executable,str(v.ROOT/'scripts/vk_stories.py'),
                    'inspect','--cdp',f'http://127.0.0.1:{unavailable.getsockname()[1]}',
                    '--timeout','500'],capture_output=True,text=True,timeout=15)
                assert failed.returncode==1
                assert 'No new profile or login was started' in json.loads(failed.stdout)['error']
            page.set_default_timeout(1500)
            page.route('**/missing.png', lambda route: route.abort())
            page.route('https://vk.ru/**', lambda route: route.fulfill(body=HTML,content_type='text/html'))
            page.set_content('<body>Shared session fixture</body>')
            page.evaluate("setTimeout(()=>document.body.insertAdjacentHTML('beforeend',"
                          "'<span id=shared-auth>Authenticated</span>'),200)")
            with patch.object(sys.stdin, 'isatty', side_effect=AssertionError('Unexpected manual login')):
                v.authenticate(page, Namespace(timeout=1500), {'auth':{'ready':'#shared-auth'}})
            # VK starts in playing=false while mounting/loading. An optional
            # playing=true selector skips Space and mistakes startup for pause.
            # A public selector recipe is not an observed employee UI map.
            example = v.ROOT/'references/vk-ui.example.json'
            try:
                v.load_ui(example)
            except v.Failure:
                pass
            else:
                raise AssertionError('Unobserved public recipe accepted as live UI evidence')
            pause_step=json.loads(example.read_text(encoding="utf-8"))['viewer']['pause'][0]
            for resume in (False,True):
                page.goto('https://vk.ru/fixture')
                page.locator('.card').first.click()
                page.evaluate('''resume => {
                  const node=document.createElement('div');node.id='play';node.tabIndex=0;
                  node.textContent='Player';node.dataset.storyPlaying='false';
                  document.querySelector('#viewer').append(node);
                  node.addEventListener('keydown',e=>{if(e.code==='Space'){
                    node.dataset.storyPlaying='false';
                    if(resume)setTimeout(()=>node.dataset.storyPlaying='true',150);
                  }});
                  setTimeout(()=>node.dataset.storyPlaying='true',250);
                }''',resume)
                ui=copy.deepcopy(UI)
                ui['viewer']['pause']=[dict(pause_step,selector='#play[data-story-playing=true]')]
                ui['viewer']['paused']='#play[data-story-playing=false]'
                card={'id':'a','date':v.publication('2026-09-02T10:00:00+03:00',
                                                   {'format':'iso'},'Europe/Moscow')}
                target=root/('resumed.png' if resume else 'delayed-start.png')
                if resume:
                    try:
                        v.capture(page,card,ui,target,'Europe/Moscow')
                        assert False
                    except v.Failure as e:
                        assert 'auto-advance resumed' in str(e)
                    assert not target.exists()
                else:
                    assert v.capture(page,card,ui,target,'Europe/Moscow')=='image'
            for mode in ('success', 'access', 'autoadvance', 'partial'):
                page.goto('https://vk.ru/fixture')
                out = root / mode; out.mkdir()
                manifest = {'stories': [], 'errors': [], 'complete': False, 'traversal_complete': False}
                args = Namespace(month='2026-09',timezone='Europe/Moscow',output=out,
                                 max_scrolls=20,stall_checks=8,settle=100)
                if mode == 'access':
                    page.evaluate("document.querySelector('#archive').insertAdjacentHTML('beforeend','<div id=denied>Denied</div>')")
                    try:
                        v.collect(page,args,UI,manifest,lambda:None)
                        assert False
                    except v.Failure as e:
                        assert 'access denied' in str(e)
                    assert not list(out.glob('*.png'))
                    continue
                if mode == 'autoadvance':page.evaluate("window.switchId='a'")
                if mode == 'partial':page.evaluate("window.failId='b'")
                with contextlib.redirect_stdout(io.StringIO()):
                    v.collect(page,args,UI,manifest,lambda:v.save_json(out/'manifest.json',manifest))
                records = {r['id']: r for r in manifest['stories']}
                assert set(records) == {'a','b','c'}, (mode,manifest)
                assert records['c']['ok'], (mode,manifest)
                assert manifest['traversal_complete']
                if mode == 'success':
                    assert manifest['complete'] and len(list(out.glob('*.png'))) == 3
                    assert records['a']['date'][:10] == records['b']['date'][:10]
                else:
                    assert not manifest['complete'] and len(list(out.glob('*.png'))) == 2
                    failed_id = 'a' if mode == 'autoadvance' else 'b'
                    assert not records[failed_id]['ok'] and records[failed_id]['path'] is None
                    assert manifest['errors']
            # Real VK's observed ordering: newest day first, one left date badge
            # for several stories; stop at the month boundary, not archive end.
            page.goto('https://vk.ru/fixture')
            page.evaluate('''() => {
              document.querySelector('#cards').innerHTML='';
              source.splice(0,source.length,
                ['a','2026-09-30T11:00:00+03:00'],
                ['b','2026-09-30T10:00:00+03:00'],
                ['c','2026-09-02T10:00:00+03:00'],
                ['d','2026-08-31T10:00:00+03:00']);
              for(let i=0;i<4;i++)add(i);
              document.querySelectorAll('.card').forEach((e,i)=>{
                if(i!==1)e.insertAdjacentHTML('beforeend',
                  '<span class="badge">'+(i===0?'30 сен':i===2?'2 сен':'31 авг')+'</span>');
              });
            }''')
            ui = copy.deepcopy(UI)
            ui['archive'].update(api_path='/method/stories.getArchive',owner_id=-103,
                                 descending_days=True, preview_date={'selector':'.badge',
                                 'timezone':'Europe/Moscow','months':{'9':'сен'}})
            page._vk_archive = {'groups':{103},'errors':[],'pending':set(),
                'count':401,'items':{ident:{'date':date} for ident,date in page.evaluate('source')}}
            out=root/'month-boundary';out.mkdir()
            args.output=out
            manifest={'stories':[],'errors':[],'complete':False,'traversal_complete':False}
            with contextlib.redirect_stdout(io.StringIO()):
                v.collect(page,args,ui,manifest,lambda:None)
            assert manifest['complete'], manifest
            assert [r['id'] for r in manifest['stories']] == ['a','b','c']
            assert manifest['stories'][1]['preview_date'] == '30 сен'
            assert page.locator('#archive').evaluate('e=>e.scrollTop') == 0
            assert manifest['completion_evidence']['scope'] == 'requested_month_only'
            # Some VK communities show only a linked avatar, not text in the
            # header. It must resolve to the owner verified by archive metadata.
            page.goto('https://vk.ru/fixture')
            page.evaluate('''() => {
              source.splice(0,source.length,['-103_1','2026-09-02T10:00:00+03:00']);
              document.querySelector('#cards').innerHTML='';add(0);
              document.querySelector('#author').hidden=true;
              document.querySelector('#viewer').insertAdjacentHTML('afterbegin',
                '<a id="avatar" href="/fixture-community"><img src="'+pixel+'"></a>');
            }''')
            ui=copy.deepcopy(UI);ui['viewer']['author_avatar']='#avatar'
            page._vk_archive={'screen_names':{103:'fixture-community'}}
            page.locator('.card').click()
            card={'id':'-103_1','date':v.publication('2026-09-02T10:00:00+03:00',
                                                         {'format':'iso'},'Europe/Moscow')}
            assert v.capture(page,card,ui,root/'avatar-ok.png','Europe/Moscow')=='image'
            page.locator('#avatar').evaluate("e=>e.href='https://vk.ru/wrong-owner'")
            try:
                v.capture(page,card,ui,root/'avatar-wrong.png','Europe/Moscow')
                assert False
            except v.Failure as e:
                assert 'author' in str(e)
            assert not (root/'avatar-wrong.png').exists()
            # Manual approval only covers missing rendering, never conflicting
            # ownership, identity, date or a link to another account.
            ui['archive']['owner_id']=-103
            page._vk_archive.update(groups={103},items={card['id']:{
                'owner_id':-103,'id':1,'date':int(card['date'].timestamp())}})
            page.locator('#avatar').evaluate("e=>{e.href='/';e.innerHTML='';e.style='display:block;width:36px;height:36px'}")
            try:
                v.capture(page,card,ui,root/'unapproved.png','Europe/Moscow')
                assert False
            except v.Failure:
                pass
            assert not (root/'unapproved.png').exists()
            assert v.capture(page,card,ui,root/'approved.png','Europe/Moscow',[card['id']])=='image'
            assert card['author_verification']['manual_approval'] is True
            assert card['author_verification']['avatar_loaded'] is False
            for href,owner,date,active in [('/wrong-owner',-103,int(card['date'].timestamp()),card['id']),
                    ('/',-104,int(card['date'].timestamp()),card['id']),
                    ('/',-103,0,card['id']),
                    ('/',-103,int(card['date'].timestamp()),'-103_2')]:
                page.locator('#avatar').evaluate('(e,href)=>e.href=href',href)
                page._vk_archive['items'][card['id']].update(owner_id=owner,date=date)
                page.locator('#viewer').evaluate('(e,id)=>e.dataset.id=id',active)
                try:
                    v.capture(page,card,ui,root/'invalid-approval.png','Europe/Moscow',[card['id']])
                    assert False
                except v.Failure:
                    pass
                assert not (root/'invalid-approval.png').exists()
            # Password recipes are refused. Simulate manual input only on this routed fixture.
            page.route('https://vk.ru/login-fixture', lambda route: route.fulfill(
                body="<input id=l><input id=p type=password><button id=go onclick=\"this.id='ready'\">Login</button>",
                content_type='text/html'))
            page.goto('https://vk.ru/login-fixture')
            try:
                v.actions(page,[{'action':'fill','selector':'#p','credential':'password'}])
                assert False, 'Password recipe must not execute'
            except v.Failure:
                pass
            assert page.locator('#p').input_value() == ''
            page.locator('#l').fill('fixture-login')
            page.locator('#p').fill('fixture-secret')
            v.actions(page,[{'action':'click','selector':'#go'}])
            assert v.visible(page,'#ready')
            browser.close()
    print('PASS: month boundaries, same-day stories, delayed loading, denied access, '
          'auto-transition rejection, partial preservation, private file permissions, password recipe refusal '
          'CDP disconnect without closing the external browser, inherited left preview dates '
          'month boundary without older-history scrolling, verified owner avatar, '
          'delayed autoplay startup and rejection of resumed autoplay, '
          'shared CDP defaults and delayed authentication without login, '
          'manual missing-avatar approval with ownership/date/identity conflict rejection')


if __name__ == '__main__':
    check()

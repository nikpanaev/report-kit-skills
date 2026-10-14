#!/usr/bin/env python3
"""Local checks; synthetic pages do not certify VK authorization/selectors."""
import json
import os
import sys
import contextlib
import io
import tempfile
from unittest.mock import MagicMock, patch
from argparse import Namespace
from pathlib import Path

from playwright.sync_api import sync_playwright
import vk_messages as m
from ui_queue import TOKEN_ENV


def item(cmid, day=12):
    return dict(id=cmid, conversation_message_id=cmid, peer_id=10,
                date=int(m.period(f'2026-09-{day:02}',f'2026-09-{day:02}','Europe/Moscow')[0].timestamp()),
                from_id=10, out=0)


def fails(call):
    try:
        call()
    except m.shared.Failure:
        return
    raise AssertionError('Expected a confirmed failure')


def checks():
    with tempfile.TemporaryDirectory() as directory:
        for options, environment, expected_cdp, expected_profile in (
            ([],{},m.shared.SHARED_CDP,None),
            ([],{'VK_CDP_URL':'http://localhost:9333'},'http://localhost:9333',None),
            (['--cdp','http://localhost:9444'],{'VK_CDP_URL':'http://localhost:9333'},
             'http://localhost:9444',None),
            (['--profile','/tmp/vk-explicit-profile'],{'VK_CDP_URL':'http://localhost:9333'},
             None,Path('/tmp/vk-explicit-profile')),
        ):
            queue_environment = {TOKEN_ENV: os.environ[TOKEN_ENV]} if TOKEN_ENV in os.environ else {}
            with patch.dict(os.environ,{**queue_environment, **environment},clear=True), \
                 patch.object(sys,'argv',['vk_messages.py','https://vk.ru/fixture','--all',
                     '--list-only','--month','2026-09','--output',directory]+options), \
                 patch.object(m.shared,'session',side_effect=m.shared.Failure('Session selected')) as session, \
                 contextlib.redirect_stdout(io.StringIO()):
                assert m.main()==1
                args=session.call_args.args[0]
                assert args.cdp==expected_cdp and args.profile==expected_profile
                assert args.channel == 'chrome'
        for href, visible, error in (
            ('/gim123', True, None),
            ('/gim0', True, 'Group inbox link/access is unconfirmed'),
            ('https://example.com/gim123', True, 'Group inbox link/access is unconfirmed'),
            ('/gim123?extra=1', True, 'Group inbox link/access is unconfirmed'),
            ('/gim123', False, 'Community inbox link absent; access unconfirmed'),
        ):
            page = MagicMock()
            manage = page.locator.return_value
            manage.get_attribute.return_value = href
            page.title.return_value = 'Мессенджер: Fixture'
            if not visible:
                manage.wait_for.side_effect = RuntimeError('Fixture inbox link absent')
            output = io.StringIO()
            with patch.object(sys, 'argv', ['vk_messages.py', 'https://vk.ru/fixture',
                    '--all', '--list-only', '--month', '2026-09', '--output', directory]), \
                 patch.object(m.shared, 'session', return_value=contextlib.nullcontext(page)), \
                 patch.object(m, 'navigate') as navigate, \
                 patch.object(m, 'list_peers', return_value=({}, True, None)), \
                 contextlib.redirect_stdout(output):
                assert m.main() == (1 if error else 0)
                destinations = [call.args[1] for call in navigate.call_args_list]
                assert destinations == ['https://vk.ru/fixture'] + ([] if error else ['https://vk.ru/gim123'])
                manage.click.assert_not_called()
                if error:
                    assert json.loads(output.getvalue().splitlines()[-1])['errors'][0]['error'] == error
    start,end=m.period('2026-09-01','2026-09-30','Europe/Moscow')
    assert start.isoformat()=='2026-09-01T00:00:00+03:00'
    assert end.isoformat()=='2026-10-01T00:00:00+03:00'
    leap=m.shared.month_bounds('2024-02','Europe/Moscow')
    assert (leap[1]-leap[0]).days==29
    fails(lambda:m.period('09-01','2026-09-30','UTC'))
    fails(lambda:m.period('2026-09-30','2026-09-01','UTC'))
    one=m.period('2026-09-12','2026-09-12','Europe/Moscow')
    assert (one[1]-one[0]).total_seconds()==86400
    parts=list(m.segments(1300,400))
    assert parts[0][0]==0 and sum(parts[-1])==1300
    assert all(a+h>=b for (a,h),(b,_) in zip(parts,parts[1:]))
    assert m.zoom_clip(dict(x=80,y=100,width=592,height=1000),.75)==dict(x=60,y=75,width=444,height=750,scale=1)
    feed=m.History(10)
    feed.ingest(dict(count=2,items=[item(1),item(2)]))
    assert not m.history_complete(feed,{1},start.timestamp(),end.timestamp())
    assert m.history_complete(feed,{1,2},start.timestamp(),end.timestamp())
    fails(lambda:feed.ingest(dict(count=3,items=[])))
    unordered=m.History(10)
    old=item(3);old['date']=int(start.timestamp()-1)
    unordered.ingest(dict(count=4,items=[old,item(2)]))
    assert not unordered.ordered
    assert not m.history_complete(unordered,{2},start.timestamp(),end.timestamp())
    assert len(list(m.response_bodies({'responses':[{'body':{'response':{'count':0}}}]})))==1


HTML='''<html><style>body{background:white;margin:0;font:16px sans-serif}
.ConvoHistory__scrollbar{height:170px;overflow:auto;width:500px}
article{min-height:100px;padding:12px}.spacer{height:600px}</style>
<button data-testid="header-profile-menu-button">Signed fixture</button>
<div class="ConvoHeader">Synthetic counterpart</div>
<div class="ConvoHistory__scrollbar"><div class="ConvoHistory__content">
<div class="ConvoHistory__flow"></div></div></div>
<script>
const mode=MODE,flow=document.querySelector('.ConvoHistory__flow'),scroll=document.querySelector('.ConvoHistory__scrollbar');
function render(items,broken=false){
  const group=document.createElement('div');group.className='ConvoHistory__dateStack';
  group.innerHTML='<div>September publication date</div>';
  for(const m of items){const a=document.createElement('article');a.className='ConvoHistory__messageBlock';
    a.textContent='Synthetic author, message '+m.conversation_message_id;
    if(broken)a.innerHTML+='<img src="/broken.png" width="100" height="100">';
    a.__reactFiber$fixture={memoizedProps:{message:{cmid:m.conversation_message_id,peerId:m.peer_id,
      sentAt:m.date*1000,authorId:m.from_id,isOut:!!m.out,kind:'message',updatedAt:m.date*1000}}};group.append(a);}
  flow.prepend(group);
}
(async()=>{
 const response=mode==='cached'?{response:{items:CACHED}}:await(await fetch('/method/messages.getHistory')).json();
 if(!response.response)return;
 render(response.response.items);flow.insertAdjacentHTML('afterbegin','<div class="spacer"></div>');
 scroll.scrollTop=600;
 if(mode==='transition')document.addEventListener('mousemove',()=>{
   document.querySelector('article').__reactFiber$fixture.memoizedProps.message.peerId=11;},{once:true});
 let loading=false;
 scroll.addEventListener('scroll',()=>{if(mode==='transition'||mode==='cached'||loading||scroll.scrollTop>0||scroll.style.height==='auto')return;
   loading=true;setTimeout(async()=>{const data=await(await fetch('/method/messages.getHistory?older=1')).json();
     flow.querySelector('.spacer')?.remove();render(data.response.items,mode==='partial');},350);});
})();</script></html>'''


def browser_checks():
    with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context();page=context.new_page()
        page.route('**/*',lambda r:r.fulfill(content_type='text/html',body='''
            <script>setTimeout(()=>document.body.insertAdjacentHTML('beforeend',
            '<button data-testid="header-profile-menu-button">Signed fixture</button>'),3200)</script>'''))
        with patch.object(m.shared,'authenticate',side_effect=AssertionError('Unexpected login')):
            args=Namespace(timeout=5000,renewals=0)
            m.navigate(page,'https://vk.ru/fixture',args)
            assert args.renewals==0
        context.close()
        for mode in ('load','denied','transition','partial','cached'):
            context=browser.new_context()
            page=context.new_page();page.set_default_timeout(2500)
            def route(r):
                url=m.urlsplit(r.request.url)
                if url.path=='/method/messages.getHistory':
                    body={'error':{'error_code':7}} if mode=='denied' else {'response':{
                        'count':2 if mode=='transition' else 4,
                        'items':[item(1,7),item(2,7)] if url.query else [item(3),item(4)]}}
                    r.fulfill(json=body)
                elif url.path=='/broken.png':r.abort()
                else:r.fulfill(content_type='text/html',body=HTML.replace('MODE',json.dumps(mode)).replace('CACHED',json.dumps([item(3),item(4)])))
            page.route('**/*',route)
            args=Namespace(timeout=2500,renewals=0,max_scrolls=30,settle=100,page_height=400,
                since='2026-09-01',until='2026-09-30',timezone='Europe/Moscow',output=Path(directory)/mode)
            args.output.mkdir()
            result={'screenshots':[],'messages':[],'complete':False}
            a,b=m.period(args.since,args.until,args.timezone)
            try:
                m.collect_peer(page,args,1,10,a.timestamp(),b.timestamp(),result,lambda:None)
                assert mode=='load' and result['complete']
                assert {i['conversation_message_id'] for i in result['messages'] if i['captured']}=={1,2,3,4}
            except m.shared.Failure:
                assert mode!='load' and not result['complete']
                if mode in ('partial','cached'):assert result['screenshots'] and any(args.output.glob('*.png'))
                else:assert not list(args.output.glob('*.png'))
                if mode=='cached':assert all(i['verification_source']=='observed_dom' and i['id'] is None for i in result['messages'])
            context.close()
        for stalled in (False,True):
            context=browser.new_context();page=context.new_page()
            page.set_content('''<div class="ConvoList__itemsWrapper" style="height:100px;overflow:auto"></div>''')
            page.evaluate('''stalled=>{
              const e=document.querySelector('div'),state={ids:[],hasMore:true};
              function add(id){state.ids.push({kind:'convo',id});const b=document.createElement('button');
                b.style.height='180px';b.dataset.testid='vkme_convo_list_item';b.dataset.peerId=id;b.textContent='Fixture '+id;
                b.__reactFiber$fixture={memoizedProps:{convo:{peerId:id,timestamp:1788206400},selectedOrganiser:state}};e.append(b);}
              add(1);add(2);let loaded=false;e.onscroll=()=>{if(!stalled&&!loaded){loaded=true;setTimeout(()=>{add(3);state.hasMore=false;},350);}};
            }''',stalled)
            peers,complete,error=m.list_peers(page,Namespace(max_scrolls=30,max_dialogs=10,settle=100),0)
            assert complete== (not stalled)
            assert len(peers)==(2 if stalled else 3)
            assert bool(error)==stalled
            context.close()
        browser.close()


if __name__=='__main__':
    checks();browser_checks()
    print(json.dumps({'ok':True,'checks':['period','multiple_messages_per_day','zoom','split_pages',
        'delayed_history','delayed_dialog_list','access_denied','conversation_transition','partial_failure','cached_dom','unconfirmed_end',
        'shared_session_defaults','delayed_authentication_without_login',
        'validated_inbox_navigation','absent_inbox_link']}))

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {validateRequest,makeGuard,normalizePostMapping} from './mcp-run.mjs';
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'livedune-check-'));
const maxAccount='00000001-0000-4000-8000-000000000001',maxPost='mid.11111111111111111111111111111111';
const maxPath='/accounts/'+maxAccount+'/posts/'+maxPost;
try {
  for(const [u,o] of [['https://evil.test/info',{}],['https://api.livedune.com/accounts',{method:'POST'}],['https://api.livedune.com/posting/1',{}],['https://api.livedune.com/info?access_token=synthetic',{}],['https://api.livedune.com/info?date_from=2026-02-31',{}],['https://api.livedune.com/search?url=https://evil.test',{}]]) assert.throws(()=>validateRequest(u,o));
  validateRequest('https://api.livedune.com/accounts/uuid-1/history?date_from=2024-02-29&date_to=2024-02-29');
  assert.throws(()=>validateRequest('https://api.livedune.com/info?date_from=2026-07-01&date_to=2026-06-30'));
  const maxDir=path.join(dir,'max-post');fs.mkdirSync(maxDir);let maxKeys=0,maxRequests=0;
  const maxGuard=makeGuard({runDir:maxDir,cap:1,credential:()=>{maxKeys++;return Buffer.from('synthetic-key');},fetcher:async u=>{maxRequests++;assert.equal(u.pathname,maxPath);return new Response(JSON.stringify({response:{post_id:maxPost}}));}});
  for(const id of ['mid.bad','mid.'+'f'.repeat(31),'mid.'+'g'.repeat(32),'mid.'+'f'.repeat(32)+'/extra','mid%2E'+'f'.repeat(32),'mid%2F..%2Finfo','..%2F..%2Finfo']) await assert.rejects(()=>maxGuard.fetch('https://api.livedune.com/accounts/'+maxAccount+'/posts/'+id),/ENDPOINT_DENIED/);
  assert.equal(maxGuard.used,0);assert.equal(maxKeys,0);assert.equal(maxRequests,0);
  await maxGuard.fetch('https://api.livedune.com'+maxPath);
  assert.equal(JSON.parse(fs.readFileSync(maxGuard.last.artifact)).response.post_id,maxPost);
  await assert.rejects(()=>maxGuard.fetch('https://api.livedune.com'+maxPath),/PILOT_CAP_REACHED/);
  assert.equal(maxKeys,1);assert.equal(maxRequests,1);assert.equal(maxGuard.used,1);
  console.log('PASS MAX mid.hex32 selected post guard; malformed/encoded/traversal paths denied before key/HTTP');
  let calls=0;
  const body={response:Array.from({length:100},(_,id)=>({id,text:'x'.repeat(600)})),after:'next'};
  const guard=makeGuard({runDir:dir,cap:1,credential:()=>Buffer.from('synthetic-key'),fetcher:async(u,o)=>{calls++;assert.equal(u.searchParams.get('access_token'),'synthetic-key');assert.equal(o.redirect,'error');return new Response(JSON.stringify(body),{headers:{'content-type':'application/json'}});}});
  await guard.fetch('https://api.livedune.com/accounts/123/posts');
  assert.equal(JSON.parse(fs.readFileSync(guard.last.artifact)).response.length,100);
  await assert.rejects(()=>guard.fetch('https://api.livedune.com/info'),/PILOT_CAP_REACHED/);
  const resumed=makeGuard({runDir:dir,cap:1,credential:()=>{throw Error('must not run');}});
  await assert.rejects(()=>resumed.fetch('https://api.livedune.com/info'),/PILOT_CAP_REACHED/);
  assert.equal(calls,1);assert(!fs.readFileSync(path.join(dir,'requests.jsonl'),'utf8').includes('synthetic-key'));
  const failedDir=path.join(dir,'failed');fs.mkdirSync(failedDir);
  const reflected=makeGuard({runDir:failedDir,cap:1,credential:()=>Buffer.from('synthetic-key'),fetcher:async()=>new Response('{"error":"synthetic-key"}')});
  await assert.rejects(()=>reflected.fetch('https://api.livedune.com/info'));
  assert.equal(reflected.last.status,'FAILED_OR_UNCERTAIN');
  assert(!fs.existsSync(path.join(failedDir,'001.json')));
  assert(!fs.readFileSync(path.join(failedDir,'requests.jsonl'),'utf8').includes('synthetic-key'));
  console.log('PASS origin/method/secret/date/cap/restart/lossless archive');
  for(const cap of [100,200]) {
    const capDir=path.join(dir,'cap-'+cap);fs.mkdirSync(capDir);
    const ledger=path.join(capDir,'requests.jsonl');
    const prior=Array.from({length:cap-1},(_,i)=>JSON.stringify({id:String(i+1).padStart(3,'0'),status:'STARTED'})).join('\n')+'\n';
    fs.writeFileSync(ledger,prior);let keys=0,requests=0;
    const options={runDir:capDir,cap,credential:()=>{keys++;return Buffer.from('synthetic-key');},fetcher:async()=>{requests++;return new Response('{"response":[]}');}};
    const boundary=makeGuard(options);assert.equal(boundary.used,cap-1);
    await boundary.fetch('https://api.livedune.com/info');assert.equal(boundary.used,cap);assert.equal(boundary.last.id,String(cap));
    await assert.rejects(()=>boundary.fetch('https://api.livedune.com/info'),/PILOT_CAP_REACHED/);
    await assert.rejects(()=>makeGuard(options).fetch('https://api.livedune.com/info'),/PILOT_CAP_REACHED/);
    assert.equal(keys,1);assert.equal(requests,1);
    const saved=fs.readFileSync(ledger,'utf8');assert(saved.startsWith(prior));
    assert.equal(saved.trim().split('\n').map(JSON.parse).filter(r=>r.status==='STARTED').length,cap);
  }
  for(const cap of [201,0,-1,1.5,NaN,Infinity,'200',undefined]) assert.throws(()=>makeGuard({runDir:dir,cap}),/CAP_INVALID/);
  console.log('PASS cap100/200 persisted boundary/restart: next attempt blocked before credential/HTTP; invalid caps rejected');
  if(process.argv[2]) {
    const require=createRequire(path.resolve(process.argv[2],'package.json'));
    const base=path.dirname(require.resolve('mcp-openapi'));
    const {createServer}=await import(pathToFileURL(path.join(base,'server.js')));
    const {buildRequest}=await import(pathToFileURL(path.join(base,'executor/request-builder.js')));
    const {tools,server}=await createServer({spec:path.resolve(process.argv[2],'openapi.json'),include:['post'],noDocWarnings:true});
    const before=buildRequest({accountId:123,postId:'456'},tools[0].endpointRef).url;
    assert.throws(()=>validateRequest(before));
    normalizePostMapping(tools);
    const after=buildRequest({accountId:123,postId:'456'},tools[0].endpointRef).url;
    assert.equal(after,'https://api.livedune.com/accounts/123/posts/456');
    validateRequest(after);
    const maxURL=buildRequest({accountId:maxAccount,postId:maxPost},tools[0].endpointRef).url;
    assert.equal(maxURL,'https://api.livedune.com'+maxPath);validateRequest(maxURL);await server.close();
    console.log('PASS ready MCP + exact spec: broken post mapping → valid URL');
    const {executeRequest}=await import(pathToFileURL(path.join(base,'executor/http-client.js')));
    const savedFetch=globalThis.fetch;let attempted=0;
    try {
      globalThis.fetch=async()=>{attempted++;return new Response('{"error":"limited"}',{status:429,headers:{'content-type':'application/json'}});};
      assert.equal((await executeRequest({url:'https://api.livedune.com/info',method:'GET',headers:{}},{maxRetries:0,timeout:1000})).status,429);
      assert.equal(attempted,1);console.log('PASS ready backend 429: one attempt, no hidden retries');
    } finally {globalThis.fetch=savedFetch;}
    const changedRuntime=path.join(dir,'changed-spec');fs.mkdirSync(changedRuntime);
    fs.copyFileSync(path.resolve(process.argv[2],'package.json'),path.join(changedRuntime,'package.json'));
    fs.symlinkSync(path.resolve(process.argv[2],'node_modules'),path.join(changedRuntime,'node_modules'),'dir');
    fs.writeFileSync(path.join(changedRuntime,'openapi.json'),fs.readFileSync(path.resolve(process.argv[2],'openapi.json'),'utf8')+'\n');
    const changed=spawnSync(process.execPath,[path.join(path.dirname(fileURLToPath(import.meta.url)),'mcp-run.mjs'),'--runtime',changedRuntime,'--list','true'],{encoding:'utf8',timeout:10000});
    assert.equal(changed.status,1);assert(!changed.stdout);console.log('PASS changed spec stops before tools/credentials/HTTP');
    const listPreload=path.join(dir,'list-only.cjs');
    fs.writeFileSync(listPreload,"require('node:child_process').execFileSync=()=>{throw Error('unexpected credential read');};require('node:module').syncBuiltinESMExports();globalThis.fetch=async()=>{throw Error('unexpected HTTP');};");
    for(const name of ['entry-ascii','entry space','проверка','percent%','symlink']) {
      const entryDir=path.join(dir,name);fs.mkdirSync(entryDir);
      const cli=path.join(entryDir,'mcp-run.mjs');
      const adapter=fileURLToPath(new URL('./mcp-run.mjs',import.meta.url));
      if(name==='symlink') fs.symlinkSync(adapter,cli);else fs.copyFileSync(adapter,cli);
      const listed=spawnSync(process.execPath,['--require',listPreload,cli,'--runtime',path.resolve(process.argv[2]),'--list','true'],{encoding:'utf8',timeout:10000});
      assert.equal(listed.status,0,name+': CLI exit');assert.match(listed.stdout,/\S/,name+': CLI dispatched');
      assert.equal(JSON.parse(listed.stdout).length,13,name+': tool inventory');
    }
    console.log('PASS CLI dispatch in ASCII/space/Cyrillic/percent/symlink paths; no credentials/HTTP');
    // Exercise the actual CLI/SDK/backend without Keychain or external HTTP.
    for(const scenario of [
      {name:'http500',status:500,body:{error:'synthetic failure'}},
      {name:'http429',status:429,body:{error:'synthetic limit'}},
      {name:'redirect-response',status:302,body:{error:'synthetic redirect'}},
      {name:'provider-error',body:{error:'synthetic pending'}},
      {name:'html-response',raw:'<html>synthetic error</html>'},
      {name:'scalar-response',body:'synthetic scalar'},
      {name:'credential-denied',denied:true},
      {name:'credential-missing',missing:true},
      {name:'timeout',timeout:true},
      {name:'repeated-cursor',body:{response:[{id:1}],after:123},pages:true,attempts:2},
      {name:'page-schema',body:{response:null,after:123},pages:true},
      {name:'cap',body:{response:[],after:123},pages:true,cap:1},
      {name:'default-cap200',prior:199,omitCap:true,body:{response:[]},calls:[{tool:'info',arguments:{}},{tool:'info',arguments:{}}]},
      {name:'invalid-args',calls:[{tool:'info',arguments:{access_token:'synthetic'}}],attempts:0},
      {name:'success',body:{response:[],after:0},pages:true,exit:0},
      {name:'max-selected-post',tool:'post',args:{accountId:maxAccount,postId:maxPost},body:{response:{post_id:maxPost}},expectedPath:maxPath,exit:0},
      {name:'audience-cursor',tool:'audience',args:{accountId:123,mode:'all'},bodies:[{response:[{date:'2026-09-01'}],after:123},{response:[],after:0}],pages:true,attempts:2,exit:0}
    ]) {
      const testDir=path.join(dir,scenario.name);fs.mkdirSync(testDir);
      const preload=path.join(testDir,'mock.cjs'),callsFile=path.join(testDir,'calls.json');
      const payload=scenario.bodies ? `${JSON.stringify(scenario.bodies.map(v=>JSON.stringify(v)))}[Math.min(n++,${scenario.bodies.length-1})]` : JSON.stringify(scenario.raw ?? JSON.stringify(scenario.body ?? {}));
      fs.writeFileSync(preload,`const cp=require('node:child_process');cp.execFileSync=()=>{${scenario.denied ? "throw Error('synthetic denied');" : scenario.missing ? "return Buffer.alloc(0);" : "return Buffer.from('synthetic-key');"}};require('node:module').syncBuiltinESMExports();let n=0;globalThis.fetch=async u=>{${scenario.expectedPath ? `require('node:assert/strict').equal(u.pathname,${JSON.stringify(scenario.expectedPath)});` : ''}${scenario.timeout ? "throw new DOMException('synthetic timeout','TimeoutError');" : `return new Response(${payload},{status:${scenario.status ?? 200},headers:{'content-type':'application/json'}});`}};`);
      fs.writeFileSync(callsFile,JSON.stringify(scenario.calls ?? [{tool:scenario.tool ?? (scenario.pages?'posts':'info'),arguments:scenario.args ?? (scenario.pages?{accountId:123}:{}),paginate:!!scenario.pages}]));
      const runDir=path.join(testDir,'run');let prior='';
      if(scenario.prior) {fs.mkdirSync(runDir);prior=Array.from({length:scenario.prior},(_,i)=>JSON.stringify({id:String(i+1).padStart(3,'0'),status:'STARTED'})).join('\n')+'\n';fs.writeFileSync(path.join(runDir,'requests.jsonl'),prior);}
      const result=spawnSync(process.execPath,['--require',preload,path.join(path.dirname(fileURLToPath(import.meta.url)),'mcp-run.mjs'),'--runtime',path.resolve(process.argv[2]),'--run-dir',runDir,'--calls',callsFile,...(scenario.omitCap?[]:['--cap',String(scenario.cap ?? 3)])],{encoding:'utf8',timeout:10000});
      assert.equal(result.status,scenario.exit ?? 1,scenario.name+': CLI exit');
      const ledger=path.join(testDir,'run','requests.jsonl');
      const attempts=fs.existsSync(ledger)?fs.readFileSync(ledger,'utf8').trim().split('\n').map(JSON.parse).filter(r=>r.status==='STARTED').length:0;
      assert.equal(attempts,(scenario.prior ?? 0)+(scenario.attempts ?? 1),scenario.name+': no hidden attempts');
      if(scenario.prior) {assert(fs.readFileSync(ledger,'utf8').startsWith(prior));assert(fs.existsSync(path.join(runDir,'200.json')));}
      if(scenario.expectedPath) assert.equal(JSON.parse(fs.readFileSync(ledger,'utf8').split('\n')[0]).path,scenario.expectedPath);
      assert(!(result.stdout+result.stderr).includes('synthetic-key'));
    }
    console.log('PASS CLI failure/timeout/credential/cursor/schema/cap stop; success exit0; default200 persisted boundary');
  }
} finally {fs.rmSync(dir,{recursive:true,force:true});}

// Fake HTTP and private fixture only; existing ledger stays intact and outside support output.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {makeGuard} from '../skills/livedune/scripts/mcp-run.mjs';
import {supportEvent,supportErrorCode} from '../skills/_shared/support-events.mjs';

const base=fs.mkdtempSync(path.join(os.tmpdir(),'support-api-fixture-'));
process.env.REPORT_SKILLS_STATE_DIR=path.join(base,'state');
try{
  const run=path.join(base,'api');fs.mkdirSync(run);
  const forbidden='CANARY_PRIVATE_CLIENT_AND_PROVIDER_TEXT';
  assert.equal(supportErrorCode(Error(forbidden)),'UNKNOWN');
  assert.equal(supportErrorCode(Error('PILOT_CAP_REACHED')),'BUDGET_EXHAUSTED');
  assert.equal(supportErrorCode(Error('CREDENTIAL_UNAVAILABLE')),'ACCESS_DENIED');
  const guard=makeGuard({runDir:run,cap:2,credential:()=>Buffer.from('test-only-credential'),
    fetcher:async()=>new Response(JSON.stringify({error:forbidden}),{status:503})});
  await guard.fetch('https://api.livedune.com/accounts/private-account/posts?after=PRIVATE_CURSOR');
  assert.equal(guard.used,1);
  const original=fs.readFileSync(path.join(run,'requests.jsonl'),'utf8');assert(original.includes('private-account'));
  assert(original.includes(forbidden));
  const failed=makeGuard({runDir:run,cap:2,credential:()=>{throw Error(forbidden);}});
  await assert.rejects(()=>failed.fetch('https://api.livedune.com/info'),/REQUEST_FAILED_OR_UNCERTAIN/);
  const ledger=fs.readFileSync(path.join(run,'requests.jsonl'),'utf8');assert.equal(ledger.split('"STARTED"').length-1,2);
  const events=path.join(base,'state/support-v1/events');
  const rows=fs.readdirSync(events).map(f=>JSON.parse(fs.readFileSync(path.join(events,f),'utf8'))).sort((a,b)=>a.sequence-b.sequence);
  assert.deepEqual(rows.map(x=>x.result),['unknown','failure','unknown','unknown']);
  assert.equal(rows[1].error,'PROVIDER_ERROR');assert.equal(rows[3].error,'ACTION_UNCERTAIN');
  assert.equal(rows[0].operation,rows[1].operation);
  const text=JSON.stringify(rows);
  for(const token of [forbidden,'private-account','PRIVATE_CURSOR','test-only-credential',base,os.hostname(),os.userInfo().username])
    if(token.length>2)assert(!text.includes(token));
  assert.equal(fs.readFileSync(path.join(run,'requests.jsonl'),'utf8'),ledger);
  // Exact OpenAPI1.0.10 declares a root array only for /accounts/tags.
  const shapes=[['/accounts/tags',[],false],['/accounts/tags',[{id:1}],false],
    ['/accounts/tags',{},true],['/accounts/tags',null,true],['/info',[],true],
    ['/info',{total:0},false],['/search?url=https%3A%2F%2Fvk.ru%2Fexample',{id:1},false],['/projects',{response:[]},false]];
  for(const [index,[endpoint,body,rejected]] of shapes.entries()){
    const folder=path.join(base,'shape-'+index);fs.mkdirSync(folder);
    const candidate=makeGuard({runDir:folder,cap:1,credential:()=>Buffer.from('test-only-credential'),
      fetcher:async()=>new Response(JSON.stringify(body))});
    await candidate.fetch('https://api.livedune.com'+endpoint);
    assert.equal(candidate.last.schemaError,rejected,endpoint);assert.equal(candidate.used,1);
    if(endpoint==='/accounts/tags'&&!rejected)assert.equal(candidate.last.rows,body.length);
    await assert.rejects(()=>candidate.fetch('https://api.livedune.com/info'),/PILOT_CAP_REACHED/);
  }
  const startup=spawnSync(process.execPath,['skills/livedune/scripts/mcp-run.mjs','--runtime',path.join(base,'missing-runtime')],{encoding:'utf8',env:process.env});
  assert.equal(startup.status,1);
  const startupRows=fs.readdirSync(events).map(f=>JSON.parse(fs.readFileSync(path.join(events,f),'utf8')));
  assert(startupRows.some(e=>e.component==='livedune'&&e.error==='MISSING_TOOL'));
  const python=process.env.REPORT_KIT_TEST_PYTHON;
  assert(python,'Set the existing test Python explicitly; no install or executable guessing');
  const collector=path.resolve('skills/_shared/support_events.py');
  const collected=spawnSync(python,['-B',collector],{encoding:'utf8',env:process.env,cwd:process.cwd()});
  assert.equal(collected.status,0,collected.stderr);
  const bundles=fs.readdirSync(path.join(base,'state/support-v1/bundles'));assert.equal(bundles.length,1);
  console.log('PASS fake API sequence/provider exclusion/uncertain result, unchanged request budget and Python export of Node records');
}finally{
  const inventory=[];
  function visit(folder){for(const name of fs.readdirSync(folder)){const file=path.join(folder,name);if(fs.statSync(file).isDirectory())visit(file);else inventory.push({path:file,sha256:createHash('sha256').update(fs.readFileSync(file)).digest('hex')});}}
  visit(base);console.log(JSON.stringify({temporary_files:inventory,result:'Synthetic records checked; cleanup follows'}));
  fs.rmSync(base,{recursive:true,force:true});
}

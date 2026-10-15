import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {acquireRunLock,recoverRunLock,makeGuard} from './mcp-run.mjs';

const directory=fs.mkdtempSync(path.join(os.tmpdir(),'report-lock-'));
try {
  const ledger=path.join(directory,'requests.jsonl');
  const prior=JSON.stringify({id:'001',status:'STARTED'})+'\n';fs.writeFileSync(ledger,prior);
  acquireRunLock(directory);
  assert.throws(()=>recoverRunLock(directory),/LOCK_OWNER_LIVE_OR_UNKNOWN/);
  fs.unlinkSync(path.join(directory,'.lock/owner.json'));fs.rmdirSync(path.join(directory,'.lock'));
  const child=spawnSync(process.execPath,['--input-type=module','-e',
    `import {acquireRunLock} from ${JSON.stringify(new URL('./mcp-run.mjs',import.meta.url).href)};acquireRunLock(process.argv[1]);`,directory],{encoding:'utf8',timeout:10000});
  assert.equal(child.status,0,child.stderr);
  const ownerFile=path.join(directory,'.lock/owner.json'),owner=JSON.parse(fs.readFileSync(ownerFile));
  fs.writeFileSync(ownerFile,JSON.stringify({...owner,host:'not-this-machine'}));
  assert.throws(()=>recoverRunLock(directory),/LOCK_OWNER_UNCONFIRMED/);
  fs.writeFileSync(ownerFile,JSON.stringify(owner));
  assert.equal(recoverRunLock(directory).requests_replayed,false);
  assert.equal(fs.readFileSync(ledger,'utf8'),prior);
  await assert.rejects(()=>makeGuard({runDir:directory,cap:1,credential:()=>{throw Error('must not read');}}).fetch('https://api.livedune.com/info'),/PILOT_CAP_REACHED/);
  fs.mkdirSync(path.join(directory,'.lock'));
  assert.throws(()=>recoverRunLock(directory));
  console.log('PASS live/foreign/legacy lock refusal; exited owner recovery; unchanged STARTED ledger/cap; no credential or HTTP');
} finally {
  console.log(JSON.stringify({temporary:directory,files:fs.readdirSync(directory).filter(f=>fs.statSync(path.join(directory,f)).isFile()).map(f=>({name:f,sha256:createHash('sha256').update(fs.readFileSync(path.join(directory,f))).digest('hex')})),result:'synthetic lock checks; cleanup follows'}));
  fs.rmSync(directory,{recursive:true,force:true});
}

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {readCredential,preparePrivateDirectory,verifyPrivateFile,WINDOWS_CREDENTIAL_TARGET} from './platform-access.mjs';

let macCalls=0;
const mac=readCredential({platform:'darwin',service:'test-service',user:'test-user',execute:(command,args)=>{
  macCalls++;assert.equal(command,'/usr/bin/security');
  assert.deepEqual(args,['find-generic-password','-s','test-service','-a','test-user','-w']);
  return Buffer.from('synthetic-key');
}});
assert.equal(mac.toString(),'synthetic-key');mac.fill(0);assert.equal(macCalls,1);

let windowsCalls=0;
const encoded=Buffer.from('RK_CREDENTIAL:'+Buffer.from('synthetic-key').toString('base64'));
const win=readCredential({platform:'win32',systemRoot:'C:\\Windows',execute:(command,args,options)=>{
  windowsCalls++;assert.equal(command,'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe');
  assert.deepEqual(args,['-NoLogo','-NoProfile','-NonInteractive','-Command','-']);
  assert(!args.some(v=>v.includes('synthetic-key')));assert(!options.input.includes('synthetic-key'));
  return encoded;
}});
assert.equal(win.toString(),'synthetic-key');win.fill(0);assert.equal(windowsCalls,1);
assert(encoded.every(v=>v===0));
console.log('PASS macOS contract and Windows credential dispatch with synthetic transport; no native Windows execution');

const decodedRequest=options=>JSON.parse(Buffer.from(options.input.match(/\$ReportKitInput='([A-Za-z0-9+/=]+)'/)[1],'base64'));
readCredential({platform:'win32',execute:(_command,_args,options)=>{
  assert.deepEqual(decodedRequest(options),{action:'credential',target:WINDOWS_CREDENTIAL_TARGET});
  assert(!options.input.includes('Set-ExecutionPolicy'));assert.equal(options.windowsHide,true);
  return Buffer.from('RK_CREDENTIAL:c3ludGhldGlj');
}}).fill(0);
const injected="name'; Write-Output dangerous\n";
readCredential({platform:'win32',service:injected,execute:(_command,args,options)=>{
  assert(!args.join(' ').includes(injected));assert(!options.input.includes(injected));
  assert.equal(decodedRequest(options).target,injected);return Buffer.from('RK_CREDENTIAL:c3ludGhldGlj');
}}).fill(0);
for(const output of ['', 'RK_CREDENTIAL:', 'RK_CREDENTIAL:!!!', 'RK_CREDENTIAL:YQ', 'RK_CREDENTIAL:AA==', 'debug\nRK_CREDENTIAL:YQ==', 'RK_CREDENTIAL:IA==']) {
  assert.throws(()=>readCredential({platform:'win32',execute:()=>Buffer.from(output)}),/^Error: CREDENTIAL_UNAVAILABLE$/);
}
assert.throws(()=>readCredential({platform:'win32',execute:()=>Buffer.from([0xd2,...Buffer.from('K_CREDENTIAL:YQ==')])}),/^Error: CREDENTIAL_UNAVAILABLE$/);
for(const platform of ['darwin','win32']) {
  assert.throws(()=>readCredential({platform,execute:()=>{throw new Error('synthetic-key must never be exposed');}}),/^Error: CREDENTIAL_UNAVAILABLE$/);
}
let unexpected=0;
assert.throws(()=>readCredential({platform:'linux',execute:()=>unexpected++}),/^Error: CREDENTIAL_UNAVAILABLE$/);
assert.equal(unexpected,0);
console.log('PASS encoded input, strict reply, missing/denied credential, unknown platform and sanitized failures');

const privateExecute=action=>(_command,_args,options)=>{
  assert.deepEqual(decodedRequest(options),{action,path:'C:\\Users\\Synthetic\\private'});
  return Buffer.from('RK_PRIVATE_OK');
};
preparePrivateDirectory('C:\\Users\\Synthetic\\private',{platform:'win32',execute:privateExecute('prepare')});
verifyPrivateFile('C:\\Users\\Synthetic\\private',{platform:'win32',execute:privateExecute('check')});
for(const target of ['\\\\server\\share','relative','/tmp/not-windows']) {
  assert.throws(()=>preparePrivateDirectory(target,{platform:'win32',execute:()=>unexpected++}),/PRIVATE_DIRECTORY_UNAVAILABLE/);
  assert.throws(()=>verifyPrivateFile(target,{platform:'win32',execute:()=>unexpected++}),/PRIVATE_FILE_UNAVAILABLE/);
}
assert.equal(unexpected,0);
for(const execute of [()=>{throw Error('raw sensitive details');},()=>Buffer.from('not confirmed')]) {
  assert.throws(()=>preparePrivateDirectory('C:\\private',{platform:'win32',execute}),/^Error: PRIVATE_DIRECTORY_UNAVAILABLE$/);
  assert.throws(()=>verifyPrivateFile('C:\\private\\calls.json',{platform:'win32',execute}),/^Error: PRIVATE_FILE_UNAVAILABLE$/);
}
assert.throws(()=>readCredential({platform:'win32',systemRoot:'\\\\remote\\Windows',execute:()=>unexpected++}),/CREDENTIAL_UNAVAILABLE/);
assert.throws(()=>preparePrivateDirectory('/unused',{platform:'linux',execute:()=>unexpected++}),/PRIVATE_DIRECTORY_UNAVAILABLE/);
assert.equal(unexpected,0);
console.log('PASS private-directory/file dispatch, ACL refusal, local paths and unsupported platform stop before execution');

const dir=fs.mkdtempSync(path.join(os.tmpdir(),'report-kit-platform-'));
try {
  const privateDir=path.join(dir,'private');preparePrivateDirectory(privateDir,{platform:'darwin'});
  assert(fs.statSync(privateDir).isDirectory());
  if(process.platform!=='win32') assert.equal(fs.statSync(privateDir).mode & 0o777,0o700);
  if(process.platform!=='win32') {
    const probe=spawnSync(process.execPath,[fileURLToPath(new URL('./check-windows.mjs',import.meta.url)),'--run-dir',path.join(dir,'must-not-exist')],{encoding:'utf8'});
    assert.equal(probe.status,2);assert.equal(JSON.parse(probe.stdout).status,'WINDOWS_REQUIRED');
    assert(!fs.existsSync(path.join(dir,'must-not-exist')));
    const entry=fileURLToPath(new URL('./mcp-run.mjs',import.meta.url));
    const preload=path.join(dir,'credentials-mock.cjs');
    fs.writeFileSync(preload,"require('node:child_process').execFileSync=()=>Buffer.from('synthetic-key');require('node:module').syncBuiltinESMExports();globalThis.fetch=()=>{throw Error('HTTP not allowed');};");
    const prepared=spawnSync(process.execPath,['--require',preload,entry,'--prepare-private-dir',path.join(dir,'cli-private')],{encoding:'utf8'});
    assert.equal(prepared.status,0);assert.deepEqual(JSON.parse(prepared.stdout),{private_directory_ready:true});
    assert.equal(fs.statSync(path.join(dir,'cli-private')).mode & 0o777,0o700);
    const checked=spawnSync(process.execPath,['--require',preload,entry,'--check-credential','true'],{encoding:'utf8'});
    assert.equal(checked.status,0);assert.deepEqual(JSON.parse(checked.stdout),{credential_available:true});
    assert(!(checked.stdout+checked.stderr).includes('synthetic-key'));
    for(const response of ["throw Error('synthetic-key')","return Buffer.alloc(0)"]) {
      fs.writeFileSync(preload,"require('node:child_process').execFileSync=()=>{"+response+"};require('node:module').syncBuiltinESMExports();globalThis.fetch=()=>{throw Error('HTTP not allowed');};");
      const failed=spawnSync(process.execPath,['--require',preload,entry,'--check-credential','true'],{encoding:'utf8'});
      assert.equal(failed.status,1);assert(!failed.stdout);assert(!(failed.stdout+failed.stderr).includes('synthetic-key'));
    }
    const invalid=spawnSync(process.execPath,[entry,'--prepare-private-dir',path.join(dir,'invalid'),'--runtime','unused'],{encoding:'utf8'});
    assert.equal(invalid.status,1);assert(!fs.existsSync(path.join(dir,'invalid')));
  }
} finally {fs.rmSync(dir,{recursive:true,force:true});}
console.log('PASS private macOS directory and non-Windows native-probe refusal; no network or system credentials used');

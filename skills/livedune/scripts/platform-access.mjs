import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

export const WINDOWS_CREDENTIAL_TARGET='ReportKit/LiveDune';

function windowsAccess(request,{execute=execFileSync,systemRoot=process.env.SystemRoot ?? 'C:\\Windows'}={}) {
  if(!/^[A-Za-z]:\\/.test(systemRoot) || /[\r\n\0]/.test(systemRoot) || systemRoot.split(/[\\/]/).includes('..')) throw new Error('WINDOWS_ACCESS_UNAVAILABLE');
  const executable=path.win32.join(systemRoot,'System32','WindowsPowerShell','v1.0','powershell.exe');
  const input="$ReportKitInput='"+Buffer.from(JSON.stringify(request)).toString('base64')+"'\n"+fs.readFileSync(new URL('./windows-access.ps1',import.meta.url),'utf8');
  let output;
  try {
    output=execute(executable,['-NoLogo','-NoProfile','-NonInteractive','-Command','-'],{
      input:'& {\n'+input+'\n}\n\n',stdio:['pipe','pipe','pipe'],timeout:15000,windowsHide:true,maxBuffer:16384
    });
    if(!Buffer.isBuffer(output) || output.some(byte=>byte>127)) throw new Error('WINDOWS_REPLY_INVALID');
    return output.toString('ascii').trim();
  } catch {throw new Error('WINDOWS_ACCESS_UNAVAILABLE');}
  finally {if(Buffer.isBuffer(output)) output.fill(0);}
}

export function readCredential({platform=process.platform, execute=execFileSync, service, user=process.env.USER, systemRoot}={}) {
  let value;
  try {
    if(platform==='darwin') value=execute('/usr/bin/security',['find-generic-password','-s',service ?? 'livedune-api-key','-a',user,'-w'],{stdio:['ignore','pipe','pipe'],timeout:10000});
    else if(platform==='win32') {
      const reply=windowsAccess({action:'credential',target:service ?? WINDOWS_CREDENTIAL_TARGET},{execute,systemRoot});
      if(!/^RK_CREDENTIAL:[A-Za-z0-9+/]+={0,2}$/.test(reply)) throw new Error('WINDOWS_REPLY_INVALID');
      const encoded=reply.slice('RK_CREDENTIAL:'.length);value=Buffer.from(encoded,'base64');
      if(value.toString('base64')!==encoded || value.includes(0)) throw new Error('WINDOWS_REPLY_INVALID');
    } else throw new Error('PLATFORM_NOT_SUPPORTED');
    if(!Buffer.isBuffer(value) || !value.toString('utf8').trim()) throw new Error('CREDENTIAL_UNAVAILABLE');
    return value;
  } catch {if(Buffer.isBuffer(value)) value.fill(0);throw new Error('CREDENTIAL_UNAVAILABLE');}
}

export function preparePrivateDirectory(directory,{platform=process.platform,...options}={}) {
  try {
    if(platform==='win32') {
      if(!/^[A-Za-z]:\\/.test(directory)) throw new Error('LOCAL_WINDOWS_PATH_REQUIRED');
      if(windowsAccess({action:'prepare',path:directory},options)!=='RK_PRIVATE_OK') throw new Error('WINDOWS_REPLY_INVALID');
    } else if(platform==='darwin') {
      fs.mkdirSync(directory,{recursive:true,mode:0o700});fs.chmodSync(directory,0o700);
    } else throw new Error('PLATFORM_NOT_SUPPORTED');
  } catch {throw new Error('PRIVATE_DIRECTORY_UNAVAILABLE');}
}

export function verifyPrivateFile(file,{platform=process.platform,...options}={}) {
  if(platform==='win32') {
    try {
      if(!/^[A-Za-z]:\\/.test(file) || windowsAccess({action:'check',path:file},options)!=='RK_PRIVATE_OK') throw new Error('WINDOWS_REPLY_INVALID');
    } catch {throw new Error('PRIVATE_FILE_UNAVAILABLE');}
  }
}

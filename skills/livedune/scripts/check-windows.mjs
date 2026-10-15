// User-run native check; no HTTP, credential writes or policy changes.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {outsidePackage} from './mcp-run.mjs';
import {readCredential,preparePrivateDirectory,verifyPrivateFile,WINDOWS_CREDENTIAL_TARGET} from './platform-access.mjs';

if(process.platform!=='win32') {
  console.log(JSON.stringify({status:'WINDOWS_REQUIRED',native_checks:'NOT_RUN'}));process.exitCode=2;
} else {
  const report={schema_version:1,kind:'USER_RUN_WINDOWS_LOCAL_CHECK',os_release:os.release(),arch:process.arch,node:process.version,
    at:new Date().toISOString(),checks:{},api:'NOT_RUN',browser:'NOT_RUN',restart:'NOT_RUN',windows_support:'PENDING_USER_ACCEPTANCE'};
  let runDir,file,fileHash,created=false;
  try {
    const args=process.argv.slice(2),options={};
    for(let i=0;i<args.length;i+=2) {
      if(!['--run-dir','--check-credential'].includes(args[i]) || args[i+1]===undefined || Object.hasOwn(options,args[i])) throw Error('ARGUMENTS_INVALID');
      options[args[i]]=args[i+1];
    }
    if(!options['--run-dir'] || (options['--check-credential']!==undefined && options['--check-credential']!=='true')) throw Error('ARGUMENTS_INVALID');
    runDir=outsidePackage(options['--run-dir']);preparePrivateDirectory(runDir);
    report.checks.private_directory='PASS';
    file=path.join(runDir,'synthetic-'+randomUUID()+'.json');const raw=Buffer.from('{"synthetic":true}\n');
    const descriptor=fs.openSync(file,'wx',0o600);created=true;
    try {fs.writeFileSync(descriptor,raw);} finally {fs.closeSync(descriptor);}
    fileHash=createHash('sha256').update(raw).digest('hex');
    verifyPrivateFile(file);report.checks.inherited_file_access='PASS';
    preparePrivateDirectory(runDir);report.checks.existing_private_directory='PASS';
    let stopped=false;
    try {const value=readCredential({service:WINDOWS_CREDENTIAL_TARGET+'/missing-'+randomUUID()});value.fill(0);} catch {stopped=true;}
    if(!stopped) throw Error('MISSING_CREDENTIAL_NOT_STOPPED');
    report.checks.missing_credential='STOPPED; positive store check required separately';
    if(options['--check-credential']==='true') {
      const value=readCredential();value.fill(0);report.checks.existing_credential='PASS';
    } else report.checks.existing_credential='NOT_RUN';
    report.status='NATIVE_LOCAL_CHECKS_COMPLETED';
  } catch {
    report.status='WINDOWS_LOCAL_CHECK_STOPPED';process.exitCode=1;
  } finally {
    if(created && fs.existsSync(file)) {
      try {fileHash=createHash('sha256').update(fs.readFileSync(file)).digest('hex');}
      catch {report.status='WINDOWS_LOCAL_CHECK_STOPPED';process.exitCode=1;}
      report.temporary={name:path.basename(file),sha256:fileHash,result:report.status};
    }
    if(report.checks.private_directory==='PASS') {
      const receipt=path.join(runDir,'windows-local-check-'+randomUUID()+'.json');
      try {
        fs.writeFileSync(receipt,JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});
        report.receipt=path.basename(receipt);
      } catch {report.receipt='NOT_SAVED';process.exitCode=1;}
    }
    if(created && fileHash && fs.existsSync(file)) {
      try {fs.unlinkSync(file);report.temporary.removed=true;}
      catch {report.temporary.removed=false;process.exitCode=1;}
    }
    console.log(JSON.stringify(report));
  }
}

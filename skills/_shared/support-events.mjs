// Safe projection only. Original request ledger/provider replies are never copied here.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';

const policy=JSON.parse(fs.readFileSync(new URL('./support-policy.json',import.meta.url),'utf8'));
const packageRoot=path.resolve(fileURLToPath(new URL('../..',import.meta.url)));
const run=randomUUID();let sequence=0,warned=false;
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const version=/^\d{1,6}\.\d{1,6}(?:\.\d{1,6}){0,2}(?:-(?:dev|alpha|beta|rc)\.\d{1,6})?$/;

export function supportErrorCode(error){
  const native={'MODULE_NOT_FOUND':'MISSING_TOOL','ERR_MODULE_NOT_FOUND':'MISSING_TOOL','ENOENT':'MISSING_TOOL','EACCES':'ACCESS_DENIED','EPERM':'ACCESS_DENIED'};
  const known={'PILOT_CAP_REACHED':'BUDGET_EXHAUSTED','CREDENTIAL_UNAVAILABLE':'ACCESS_DENIED','PRIVATE_DIRECTORY_UNAVAILABLE':'ACCESS_DENIED',
    'MCP_VERSION_MISMATCH':'INCOMPATIBLE','SPEC_CHANGED_REVIEW_REQUIRED':'INCOMPATIBLE','TOOL_ARGUMENTS_INVALID':'INVALID_INPUT',
    'ARGUMENTS_INVALID':'INVALID_INPUT','DATE_INVALID':'INVALID_INPUT','ENDPOINT_DENIED':'INVALID_INPUT'};
  return (Object.hasOwn(native,error?.code)?native[error.code]:null) ?? (Object.hasOwn(known,error?.message)?known[error.message]:null) ?? 'UNKNOWN';
}

function directory(){
  const selected=process.env.REPORT_SKILLS_STATE_DIR ?? path.join(os.homedir(),'.local/state/report-skills');
  if(selected.startsWith('//')||selected.startsWith('\\\\')||selected.includes('://')||/[\r\n\0]/.test(selected))throw Error('LOCAL_SUPPORT_PATH_REQUIRED');
  const requested=path.resolve(selected);
  let parent=requested;while(!fs.existsSync(parent))parent=path.dirname(parent);
  const base=path.join(fs.realpathSync(parent),path.relative(parent,requested));
  const inside=(a,b)=>{const r=path.relative(a,b);return !r||(!r.startsWith('..'+path.sep)&&r!=='..'&&!path.isAbsolute(r));};
  const root=path.join(base,'support-v1');
  if(inside(packageRoot,root)||inside(root,packageRoot))throw Error('SUPPORT_PATH_BOUNDARY');
  if(fs.existsSync(root)&&fs.lstatSync(root).isSymbolicLink())throw Error('SUPPORT_PATH_BOUNDARY');
  fs.mkdirSync(root,{recursive:true,mode:0o700});
  const marker=path.join(root,'owner.json');
  if(!fs.existsSync(marker)){
    if(fs.readdirSync(root).length)throw Error('SUPPORT_STORE_UNRECOGNIZED');
    fs.writeFileSync(marker,JSON.stringify({owner:'Report Kit support',schema_version:1}),{flag:'wx',mode:0o600});
  }
  if(fs.lstatSync(marker).isSymbolicLink()||fs.statSync(marker).size>256)throw Error('SUPPORT_STORE_UNRECOGNIZED');
  const owner=JSON.parse(fs.readFileSync(marker,'utf8'));
  if(owner.owner!=='Report Kit support'||owner.schema_version!==1||Object.keys(owner).length!==2)throw Error('SUPPORT_STORE_UNRECOGNIZED');
  const events=path.join(root,'events');
  if(fs.existsSync(events)&&fs.lstatSync(events).isSymbolicLink())throw Error('SUPPORT_PATH_BOUNDARY');
  fs.mkdirSync(events,{recursive:true,mode:0o700});return events;
}

function pruneFolder(folder,pattern,days,limit,maxBytes){
  if(!fs.existsSync(folder)||fs.lstatSync(folder).isSymbolicLink())return;
  const files=[];
  for(const name of fs.readdirSync(folder).filter(n=>pattern.test(n))){
    const file=path.join(folder,name);try{const stat=fs.lstatSync(file);if(stat.isFile()&&!stat.isSymbolicLink())files.push({file,stat});}catch(e){if(e.code!=='ENOENT')throw e;}
  }
  files.sort((a,b)=>b.stat.mtimeMs-a.stat.mtimeMs);
  let bytes=0;files.forEach((x,i)=>{bytes+=x.stat.size;if(i>=limit||bytes>maxBytes||x.stat.mtimeMs<Date.now()-days*86400000){try{fs.unlinkSync(x.file);}catch(e){if(e.code!=='ENOENT')throw e;}}});
}

export function supportEvent(stage,kind,result='unknown',error='NONE',{operation=randomUUID(),http=0,programVersions={}}={}){
  try{
    if(!uuid.test(operation))operation=randomUUID();
    const supplied=process.env.REPORT_KIT_SUPPORT_RUN_ID;
    const observed=fs.readFileSync(new URL('../../VERSION',import.meta.url),'utf8').trim();
    const versions={node:process.versions.node};if(version.test(observed))versions['report-kit-skills']=observed;
    for(const [name,value] of Object.entries(programVersions))if(policy.programs.includes(name)&&typeof value==='string'&&version.test(value))versions[name]=value;
    const event={schema_version:1,at:new Date().toISOString(),run:uuid.test(supplied??'')?supplied:run,
      operation,event:randomUUID(),sequence:++sequence,component:'livedune',stage:policy.stages.includes(stage)?stage:'unknown',
      kind:policy.kinds.includes(kind)?kind:'check',result:policy.results.includes(result)?result:'unknown',
      error:policy.errors.includes(error)?error:'UNKNOWN',http:Number.isInteger(http)&&policy.http.includes(http)?http:0,versions};
    const raw=JSON.stringify(event);if(Buffer.byteLength(raw)>policy.event_max_bytes)throw Error('EVENT_TOO_LARGE');
    const folder=directory(),file=path.join(folder,'e-'+event.event+'.json');
    const fd=fs.openSync(file,'wx',0o600);try{fs.writeFileSync(fd,raw);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
    pruneFolder(folder,/^e-[0-9a-f-]{36}\.json$/,policy.retention_days,policy.event_limit,policy.event_bytes_limit);
    pruneFolder(path.join(path.dirname(folder),'bundles'),/^Report-Kit-support-\d{8}-[0-9a-f-]{36}\.zip$/,policy.bundle_days,policy.bundle_limit,policy.bundle_limit*policy.bundle_max_bytes);
  }catch{
    if(!warned){console.error('REPORT_KIT_SUPPORT_EVENT_NOT_SAVED');warned=true;}
  }
  return operation;
}

// Ready mcp-openapi backend; this adapter bounds access and archives provider replies.
import { createRequire } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';

export const SPEC_HASH = '3998516d4bcf19f5299763257e76b44830905066c61638e77f4e94e51ffc6b47';
export function normalizePostMapping(tools) {
  // 1.0.10 /post references mismatched names; PostID is also marked query.
  for(const t of tools.filter(t=>t.endpointRef.path==='/accounts/{account_id}/posts/{post_id}'))
    for(const m of t.endpointRef.parameterMap.filter(m=>['accountId','postId'].includes(m.toolParamName))) {
      m.source='path';m.originalName=({accountId:'account_id',postId:'post_id'})[m.toolParamName];
    }
}
export function validateRequest(input, init = {}) {
  const u = new URL(input);
  if (u.origin !== 'https://api.livedune.com' || u.username || u.password || u.hash || (init.method ?? 'GET').toUpperCase() !== 'GET' || init.body)
    throw new Error('READ_ONLY_ORIGIN_DENIED');
  if (!/^\/(info|search|projects|accounts(?:\/tags)?|accounts\/[A-Za-z0-9-]+\/(history|analytics|posts(?:\/(?:[A-Za-z0-9_-]+|mid\.[a-f0-9]{32}))?|stories|video(?:\/[A-Za-z0-9_-]+)?|audience\/[A-Za-z0-9_-]+))$/.test(u.pathname))
    throw new Error('ENDPOINT_DENIED');
  for (const [k,v] of u.searchParams) {
    if (!['url','date_from','date_to','after','project_id','type'].includes(k) || v.length > 2048)
      throw new Error('PARAMETER_DENIED');
    if (k.startsWith('date_') && (!/^\d{4}-\d{2}-\d{2}$/.test(v) || Number.isNaN(Date.parse(v)) || new Date(v).toISOString().slice(0,10) !== v))
      throw new Error('DATE_INVALID');
  }
  if (u.searchParams.has('date_from') && u.searchParams.has('date_to') && u.searchParams.get('date_from') > u.searchParams.get('date_to')) throw new Error('DATE_RANGE_INVALID');
  if (u.pathname === '/search') {
    const a = new URL(u.searchParams.get('url'));
    if (a.protocol !== 'https:' || a.username || a.password || !['vk.com','vk.ru','t.me','instagram.com','www.instagram.com','youtube.com','www.youtube.com','max.ru','rutube.ru','dzen.ru','facebook.com','www.facebook.com','x.com'].includes(a.hostname))
      throw new Error('SOCIAL_URL_DENIED');
  }
  return u;
}

export function makeGuard({runDir,cap,credential,fetcher=fetch}) {
  if (!Number.isInteger(cap) || cap < 1 || cap > 200) throw new Error('CAP_INVALID');
  const ledger = path.join(runDir,'requests.jsonl');
  const prior = fs.existsSync(ledger) ? fs.readFileSync(ledger,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
  let used = prior.filter(r=>r.status === 'STARTED').length;
  let last;
  const append = r=>fs.appendFileSync(ledger,JSON.stringify(r)+'\n',{mode:0o600});
  return {get last(){return last;},get used(){return used;},async fetch(input,init={}) {
    const u=validateRequest(input,init);
    if (used >= cap) throw new Error('PILOT_CAP_REACHED');
    const id=String(++used).padStart(3,'0');
    const rec={id,path:u.pathname,params:Object.fromEntries(u.searchParams),at:new Date().toISOString()};
    append({...rec,status:'STARTED'});
    let secret;
    try {
      secret=credential();
      if (!secret?.length) throw new Error('CREDENTIAL_UNAVAILABLE');
      u.searchParams.set('access_token',secret.toString('utf8').trim());
      const res=await fetcher(u,{...init,redirect:'error'});
      const raw=Buffer.from(await res.clone().arrayBuffer());
      if (raw.includes(Buffer.from(secret.toString('utf8').trim()))) throw new Error('CREDENTIAL_REFLECTED');
      const artifact=path.join(runDir,id+'.json');
      fs.writeFileSync(artifact,raw,{flag:'wx',mode:0o600});
      let b;try{b=JSON.parse(raw);}catch{}
      last={...rec,status:'RECEIVED',http:res.status,artifact,bytes:raw.length,sha256:createHash('sha256').update(raw).digest('hex'),count:b?.count,rows:Array.isArray(b?.response)?b.response.length:null,after:b?.after ?? null,providerError:b?.error ?? null,schemaError:!b || typeof b!=='object' || Array.isArray(b)};
      append(last);
      return res;
    } catch {
      last={...rec,status:'FAILED_OR_UNCERTAIN'};append(last);
      throw new Error('REQUEST_FAILED_OR_UNCERTAIN; inspect sanitized ledger before retry');
    } finally {secret?.fill(0);u.searchParams.delete('access_token');}
  }};
}

export function outsidePackage(value) {
  const requested = path.resolve(value);
  let parent = requested;
  while (!fs.existsSync(parent)) parent = path.dirname(parent);
  const resolved = path.join(fs.realpathSync(parent), path.relative(parent, requested));
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
  const inside = (base, candidate) => { const r = path.relative(base, candidate); return !r || (!r.startsWith('..' + path.sep) && r !== '..' && !path.isAbsolute(r)); };
  if (inside(root, resolved) || inside(resolved, root)) throw new Error('RUNTIME_PATH_INSIDE_PACKAGE');
  return resolved;
}

async function main() {
  const argv=process.argv.slice(2);
  const opt={};for(let i=0;i<argv.length;i+=2) {if(!argv[i]?.startsWith('--') || argv[i+1]===undefined) throw new Error('ARGUMENTS_INVALID');opt[argv[i].slice(2)]=argv[i+1];}
  const runtime=path.resolve(opt.runtime);
  const require=createRequire(path.join(runtime,'package.json'));
  const entry=require.resolve('mcp-openapi');
  const pkg=JSON.parse(fs.readFileSync(path.resolve(path.dirname(entry),'../../package.json')));
  if (pkg.version !== '0.3.0') throw new Error('MCP_VERSION_MISMATCH');
  const spec=path.join(runtime,'openapi.json');
  if(createHash('sha256').update(fs.readFileSync(spec)).digest('hex') !== SPEC_HASH) throw new Error('SPEC_CHANGED_REVIEW_REQUIRED');
  const {createServer}=await import(pathToFileURL(path.join(path.dirname(entry),'server.js')));
  const {server,tools}=await createServer({spec,include:['info','projects','accounts','tags','searchAccountByUrl','history','analytics','audience','posts','post','stories','videos','video'],maxRetries:0,timeout:45000,dynamicDiscovery:false,noDocWarnings:true});
  normalizePostMapping(tools);
  if(opt.list === 'true'){console.log(JSON.stringify(tools.map(t=>({name:t.name,method:t.endpointRef.method,path:t.endpointRef.path,schema:t.inputSchema}))));return;}
  const runDir=outsidePackage(opt['run-dir']);
  opt.calls=outsidePackage(opt.calls);
  fs.mkdirSync(runDir,{recursive:true,mode:0o700});
  fs.chmodSync(runDir,0o700);
  const lock=path.join(runDir,'.lock');fs.mkdirSync(lock);
  const originalFetch=globalThis.fetch;
  let client;
  try {
    const calls=JSON.parse(fs.readFileSync(opt.calls,'utf8'));
    const cap=Number(opt.cap ?? 200);
    const guard=makeGuard({runDir,cap,credential:()=>{
      try{return execFileSync('/usr/bin/security',['find-generic-password','-s',opt['credential-service'] ?? 'livedune-api-key','-a',process.env.USER,'-w'],{stdio:['ignore','pipe','pipe'],timeout:10000});}
      catch{throw new Error('CREDENTIAL_UNAVAILABLE');}
    }});
    // Only the ready backend performs HTTP; no endpoint-specific HTTP client here.
    globalThis.fetch=guard.fetch;
    const sdkRequire=createRequire(entry);
    const {Client}=await import(pathToFileURL(sdkRequire.resolve('@modelcontextprotocol/sdk/client/index.js')));
    const {InMemoryTransport}=await import(pathToFileURL(sdkRequire.resolve('@modelcontextprotocol/sdk/inMemory.js')));
    const [ct,st]=InMemoryTransport.createLinkedPair();
    client=new Client({name:'report-skills-livedune',version:fs.readFileSync(new URL('../../../VERSION',import.meta.url),'utf8').trim()},{capabilities:{}});
    await server.connect(st);await client.connect(ct);
    const inventory=(await client.listTools()).tools;
    for (const c of calls) {
      const cursors=new Set();
      if(c.paginate && !['posts','history','stories','videos','audience'].includes(c.tool)) throw new Error('PAGINATION_TOOL_INVALID');
      do {
      const t=inventory.find(t=>t.name===c.tool);
      if(!t || Object.keys(c.arguments ?? {}).some(k=>!Object.hasOwn(t.inputSchema.properties,k)) || (t.inputSchema.required ?? []).some(k=>!Object.hasOwn(c.arguments ?? {},k))) throw new Error('TOOL_ARGUMENTS_INVALID');
      const before=guard.used;
      const result=await client.callTool({name:c.tool,arguments:c.arguments ?? {}},undefined,{timeout:55000});
      const rec={tool:c.tool,previewOnly:true,isError:!!result.isError,request:guard.used > before ? guard.last : null};
      fs.appendFileSync(path.join(runDir,'mcp-results.jsonl'),JSON.stringify(rec)+'\n',{mode:0o600});
      console.log(JSON.stringify(rec));
      if(result.isError || !rec.request || rec.request.status!=='RECEIVED' || rec.request.http!==200 || rec.request.providerError || rec.request.schemaError) throw new Error('MCP_REQUEST_STOPPED; inspect sanitized receipts');
      if(!c.paginate) break;
      const body=JSON.parse(fs.readFileSync(rec.request.artifact));
      if(!Array.isArray(body.response)) throw new Error('PAGE_SCHEMA_INVALID');
      if(!body.after) break;
      if(cursors.has(String(body.after))) throw new Error('REPEATED_CURSOR');
      cursors.add(String(body.after));
      c.arguments={...c.arguments,after:body.after};
      } while(true);
    }
  } finally {globalThis.fetch=originalFetch;await client?.close();await server.close();fs.rmdirSync(lock);}
}
if (process.argv[1] && fs.realpathSync(process.argv[1])===fileURLToPath(import.meta.url)) main().catch(()=>{console.error('LIVEDUNE_RUN_STOPPED; inspect sanitized receipts, do not print raw errors');process.exitCode=1;});

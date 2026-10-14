import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {outsidePackage} from '../skills/livedune/scripts/mcp-run.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
for(const value of [root,path.join(root,'outputs/run'),path.dirname(root)])
  assert.throws(()=>outsidePackage(value),/RUNTIME_PATH_INSIDE_PACKAGE/);
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'report-paths-'));
try {
  assert.equal(outsidePackage(path.join(temp,'new/run')),path.join(fs.realpathSync(temp),'new/run'));
  fs.symlinkSync(root,path.join(temp,'package-link'),'dir');
  assert.throws(()=>outsidePackage(path.join(temp,'package-link/new/run')),/RUNTIME_PATH_INSIDE_PACKAGE/);
  console.log('PASS external/symlink/package/ancestor path boundaries; no credential or HTTP access');
} finally {fs.rmSync(temp,{recursive:true,force:true});}

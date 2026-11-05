import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { detectPython } from './python.mjs';
export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const web = path.join(root, 'apps/web');
export const backend = path.join(root, 'services/local');
export const venvPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
export function fail(message) { console.error(message); process.exit(1); }
export function run(command, args, options = {}) {
 const r = spawnSync(command,args,{cwd:root,stdio:'inherit',...options});
 if(r.error) fail(`${command} kon niet starten: ${r.error.message}`);
 if(r.status!==0) process.exit(r.status??1);
}
export function pythonCommand() {
 try { return detectPython({venvPath:venvPython}); }
 catch(error) { fail(error.message); }
}
export function requireSetup(){if(!existsSync(venvPython)||!existsSync(path.join(web,'node_modules/vite')))fail('Voer eerst npm run setup uit.');}
export function npmRun(args, options={}) {
 if(process.env.npm_execpath?.endsWith('.js'))return run(process.execPath,[process.env.npm_execpath,...args],{cwd:web,...options});
 return run(process.platform==='win32'?'npm.cmd':'npm',args,{cwd:web,shell:process.platform==='win32',...options});
}
export function loadEnvironment(){const p=path.join(root,'.env');if(existsSync(p))process.loadEnvFile(p);}

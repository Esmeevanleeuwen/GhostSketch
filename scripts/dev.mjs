import {spawn} from 'node:child_process';
import path from 'node:path';
import {web,backend,venvPython,requireSetup,loadEnvironment} from './common.mjs';
requireSetup();loadEnvironment();
const children=[spawn(venvPython,['-m','ghostsketch'],{cwd:backend,stdio:'inherit',env:process.env}),spawn(process.execPath,[path.join(web,'node_modules/vite/bin/vite.js'),'--host','127.0.0.1'],{cwd:web,stdio:'inherit',env:process.env})];
let stopping=false;
function stop(code=0){if(stopping)return;stopping=true;for(const child of children)child.kill('SIGTERM');process.exitCode=code;}
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>stop());
for(const child of children){child.on('error',error=>{console.error(error.message);stop(1);});child.on('exit',code=>{if(!stopping)stop(code??1);});}
console.log('Ontwikkelen: http://127.0.0.1:5173 — lokale API: http://127.0.0.1:8000');

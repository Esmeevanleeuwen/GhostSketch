import {spawn} from 'node:child_process';
import {backend,venvPython,requireSetup,npmRun,loadEnvironment} from './common.mjs';
requireSetup();loadEnvironment();npmRun(['run','build']);
const child=spawn(venvPython,['-m','ghostsketch'],{cwd:backend,stdio:'inherit',env:process.env});
console.log('GhostSketch wordt gestart op http://127.0.0.1:8000');
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>child.kill(signal));
child.on('error',error=>{console.error(error.message);process.exitCode=1;});
child.on('exit',code=>{process.exitCode=code??0;});

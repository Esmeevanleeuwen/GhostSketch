import {backend,venvPython,requireSetup,run,npmRun} from './common.mjs';
run(process.execPath,['--test','scripts/python.test.mjs']);
requireSetup();run(venvPython,['-m','pytest','-q'],{cwd:backend});npmRun(['run','test','--','--run']);

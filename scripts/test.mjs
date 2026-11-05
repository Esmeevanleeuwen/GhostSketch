import {backend,venvPython,requireSetup,run,npmRun} from './common.mjs';
requireSetup();run(venvPython,['-m','pytest','-q'],{cwd:backend});npmRun(['run','test','--','--run']);

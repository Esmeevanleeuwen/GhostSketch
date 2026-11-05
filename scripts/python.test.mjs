import test from 'node:test';
import assert from 'node:assert/strict';
import { detectPython } from './python.mjs';

const output = (version = [3, 12, 0], modules = true) => ({status:version[0]>3||version[0]===3&&version[1]>=11 ? 0 : 1,stdout:JSON.stringify({version,modules,executable:'C:\\Python\\python.exe'})});
function fixture(answers, options = {}) {
 const calls=[];
 const spawn=(command,args,settings)=>{
  const candidate=[command,...args.slice(0,args.indexOf('-I'))];calls.push({candidate,args,settings});
  return answers[JSON.stringify(candidate)] ?? {status:null,error:{code:'ENOENT'},stdout:''};
 };
 return {calls, options:{platform:'win32',env:{},exists:()=>false,spawn,...options}};
}
const key = (...command) => JSON.stringify(command);

test('selects installed 3.12 even when the default launcher uses 3.10',()=>{
 const f=fixture({[key('py','-3')]:output([3,10,9]),[key('py','-3.12')]:output()});
 assert.deepEqual(detectPython(f.options),['py','-3.12']);
});
test('reuses a working venv without requiring global Python',()=>{
 const venv='C:\\Users\\esmee\\GhostSketch\\.venv\\Scripts\\python.exe';
 const f=fixture({[key(venv)]:output()},{venvPath:venv,exists:p=>p===venv});
 assert.deepEqual(detectPython(f.options),[venv]);assert.equal(f.calls.length,1);
});
test('rejects an empty successful Store alias and falls back to python3',()=>{
 const f=fixture({[key('python')]:{status:0,stdout:''},[key('python3')]:output()});
 assert.deepEqual(detectPython(f.options),['python3']);
});
test('rejects malformed or unsupported JSON even with exit code zero',()=>{
 const f=fixture({[key('py','-3.12')]:{status:0,stdout:'not python'},[key('py','-3.11')]:{status:0,stdout:JSON.stringify({version:[3,10,1],executable:'x',modules:true})},[key('py','-3')]:output([3,13,1])});
 assert.deepEqual(detectPython(f.options),['py','-3']);
});
test('timeout falls through and every probe is bounded without a shell',()=>{
 const f=fixture({[key('py','-3.12')]:{status:null,error:{code:'ETIMEDOUT'}},[key('py','-3.11')]:output([3,11,9])});
 assert.deepEqual(detectPython(f.options),['py','-3.11']);
 for(const call of f.calls){assert.equal(call.settings.shell,false);assert.equal(call.settings.windowsHide,true);assert.ok(call.settings.timeout<=5000);}
});
test('an old Python produces actionable Windows recovery instructions',()=>{
 const f=fixture({[key('py','-3')]:output([3,10,11])});
 assert.throws(()=>detectPython(f.options),error=>error.message.includes('Python 3.10.11')&&error.message.includes('winget install --exact --id Python.Python.3.12')&&error.message.includes('PowerShell'));
});
test('an explicit executable containing spaces is passed as one argument',()=>{
 const executable='C:\\Program Files\\Python312\\python.exe';
 const f=fixture({[key(executable)]:output()},{env:{GHOSTSKETCH_PYTHON:executable}});
 assert.deepEqual(detectPython(f.options),[executable]);assert.equal(f.calls[0].candidate[0],executable);assert.equal(f.calls[0].settings.shell,false);
});
test('does not silently ignore an invalid explicit interpreter',()=>{
 const f=fixture({[key('python')]:output()},{env:{GHOSTSKETCH_PYTHON:'missing.exe'}});
 assert.throws(()=>detectPython(f.options),/GHOSTSKETCH_PYTHON/);assert.equal(f.calls.length,1);
});
test('a broken existing venv is explained and not removed or bypassed',()=>{
 const venv='C:\\GhostSketch\\.venv\\Scripts\\python.exe';
 const f=fixture({[key(venv)]:output([3,10,0]),[key('python')]:output()},{venvPath:venv,exists:()=>true});
 assert.throws(()=>detectPython(f.options),/\.venv-backup/);assert.equal(f.calls.length,1);
});
test('finds a per-user official installation that is not on PATH',()=>{
 const appdata='C:\\Users\\esmee\\AppData\\Local';const exe=appdata+'\\Programs\\Python\\Python312\\python.exe';
 const f=fixture({[key(exe)]:output()},{env:{LOCALAPPDATA:appdata},exists:p=>p===exe});
 assert.deepEqual(detectPython(f.options),[exe]);
});
test('Linux still selects python3 and requires venv and ensurepip',()=>{
 const f=fixture({[key('python3')]:output([3,12,0],false),[key('python')]:output([3,11,9])},{platform:'linux'});
 assert.deepEqual(detectPython(f.options),['python']);
});

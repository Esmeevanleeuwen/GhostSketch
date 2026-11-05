import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';

const probeCode = [
 'import json,sys,importlib.util',
 'modules=all(importlib.util.find_spec(name) is not None for name in ("venv","ensurepip"))',
 'print(json.dumps({"version":list(sys.version_info[:3]),"executable":sys.executable,"modules":modules}))',
 'sys.exit(0 if sys.version_info >= (3,11) and modules else 1)',
].join(';');

function recovery(platform) {
 if (platform === 'win32') return [
  'GhostSketch wordt getest met Python 3.12.',
  'Installeer indien nodig in PowerShell:',
  '  winget install --exact --id Python.Python.3.12',
  'Sluit en heropen daarna PowerShell en controleer:',
  '  py -3.12 --version',
  'Voer vervolgens npm run setup opnieuw uit. Start de app pas als setup is geslaagd.',
  'Geen winget? Gebruik https://www.python.org/downloads/windows/',
 ].join('\n');
 return 'Installeer Python 3.11 of nieuwer met de modules venv en ensurepip. Op Debian/Ubuntu is doorgaans ook python3-venv nodig. Voer daarna npm run setup opnieuw uit.';
}

/** Finds the actual executable used by setup; never runs an installer or a shell. */
export function detectPython({
 platform = process.platform, env = process.env, venvPath,
 spawn = spawnSync, exists = existsSync,
} = {}) {
 const attempts = [];
 const probe = (command) => {
  let result;
  try {
   result = spawn(command[0], [...command.slice(1), '-I', '-c', probeCode], {
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 3500,
    windowsHide: true, shell: false, maxBuffer: 16384,
   });
  } catch { result = { status: null }; }
  let data;
  try { data = JSON.parse((result.stdout ?? '').trim()); } catch { /* A Store alias is not a Python interpreter. */ }
  const version = data?.version;
  const versionValid = Array.isArray(version) && version.length >= 2 && version.every(Number.isInteger);
  const supported = versionValid && (version[0] > 3 || (version[0] === 3 && version[1] >= 11));
  if (result.status === 0 && supported && data.modules === true && typeof data.executable === 'string' && data.executable.trim()) return true;
  if (versionValid) attempts.push(`Python ${version.join('.')} via ${command.join(' ')}${!data.modules ? ' (venv of ensurepip ontbreekt)' : ''}`);
  else if (result.error?.code === 'ETIMEDOUT') attempts.push(`Geen tijdige reactie van ${command.join(' ')}`);
  return false;
 };
 const explain = (reason) => new Error([reason, ...attempts, recovery(platform)].join('\n'));
 // setup always reuses .venv when it exists; validate that exact interpreter first.
 if (venvPath && exists(venvPath)) {
  if (probe([venvPath])) return [venvPath];
  throw explain('De bestaande Python-omgeving (.venv) is niet bruikbaar. Hernoem de map .venv naar .venv-backup en voer setup opnieuw uit. Er wordt niets automatisch verwijderd.');
 }
 const override = env.GHOSTSKETCH_PYTHON?.trim();
 if (override) {
  if (probe([override])) return [override];
  throw explain('GHOSTSKETCH_PYTHON verwijst niet naar een bruikbare Python 3.11 of nieuwer. Gebruik alleen het pad naar python.exe, zonder extra argumenten.');
 }
 const candidates = platform === 'win32'
  ? [['py', '-3.12'], ['py', '-3.11'], ['py', '-3'], ['python'], ['python3']]
  : [['python3'], ['python']];
 if (platform === 'win32' && env.LOCALAPPDATA) {
  for (const version of ['Python312', 'Python311']) {
   const executable = path.win32.join(env.LOCALAPPDATA, 'Programs', 'Python', version, 'python.exe');
   if (exists(executable)) candidates.push([executable]);
  }
 }
 for (const command of candidates) if (probe(command)) return command;
 throw explain('Geen bruikbare Python 3.11 of nieuwer gevonden. Python ontbreekt, is te oud of is niet bereikbaar via de huidige PowerShell.');
}

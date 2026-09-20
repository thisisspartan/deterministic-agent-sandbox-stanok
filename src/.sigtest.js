'use strict';
// TEMP: verify animation under a pseudo-TTY and clean SIGINT handling (deleted after use).
const { spawn, execSync } = require('node:child_process');
const path = require('node:path');

let out = '';
const p = spawn('script', ['-qec', 'node src/fire.js', '/dev/null'], {
  cwd: path.join(__dirname, '..'),
  stdio: ['ignore', 'pipe', 'pipe'],
});
p.stdout.on('data', (d) => { out += d; });
p.stderr.on('data', (d) => { out += d; });

const t = setTimeout(() => {
  const r = execSync('pidof node', { encoding: 'utf8' });
  const pids = r.trim().split(/\s+/).filter((s) => +s !== process.pid);
  console.error('node pids:', pids.join(' '));
  for (const pid of pids) {
    try { process.kill(Number(pid), 'SIGINT'); } catch (e) { console.error('kill', pid, e.code); }
  }
}, 1500);

p.on('exit', (code, signal) => {
  clearTimeout(t);
  const frames = (out.match(/\x1b\[2J/g) || []).length;
  console.log('exit code:', code, 'signal:', signal);
  console.log('frames emitted:', frames);
  console.log('cursor restored:', out.includes('\x1b[?25h'));
  console.log('ansi reset:', out.includes('\x1b[0m'));
  console.log('cursor hidden first:', out.indexOf('\x1b[?25l') === 0);
  process.exit(code === 0 && frames > 10 ? 0 : 1);
});
setTimeout(() => { console.log('TIMEOUT - process did not exit'); process.exit(1); }, 12000);

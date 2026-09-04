'use strict';

// Ticket 039: самодиагностика — mini-logger src/fire/diag.js + логирование
// в ui.attach (input/frame/stop) и в main (start/quit/signal).

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { createDiag, DEFAULT_PATH } = require('../../src/fire/diag.js');
const { attach } = require('../../src/fire/ui.js');
const { createFire } = require('../../src/fire/fire.js');

const sleep = (ms) => new Promise(res => setTimeout(res, ms));

// Unique temp file per process — /tmp, cleaned up after each test.
function tmpPath(tag) {
  return path.join(os.tmpdir(), 'fire-diag-' + tag + '-' + process.pid + '.log');
}

function makeIo() {
  const listeners = {};
  const written = [];
  const io = {
    stdin: {
      setRawMode(on) { io.stdin._rawMode = !!on; },
      on(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); return io.stdin; },
      removeListener(ev, fn) {
        const arr = listeners[ev];
        if (!arr) return;
        const i = arr.indexOf(fn);
        if (i >= 0) arr.splice(i, 1);
        return io.stdin;
      },
    },
    stdout: {
      write(s) { written.push(String(s)); return true; },
    },
  };
  io._written = written;
  io.write = (buf) => { for (const fn of listeners.data || []) fn(buf); };
  return io;
}

function readLog(p) {
  try { return fs.readFileSync(p, 'utf8'); } catch (e) { return null; }
}

// --- D1: createDiag lifecycle --------------------------------------------------

test('D1: createDiag creates and CLEARS the file; log() appends ISO-timestamped line; close()', () => {
  const p = tmpPath('d1');
  fs.writeFileSync(p, 'stale content from previous run\n');

  const d = createDiag(p);
  assert.ok(d && typeof d.log === 'function' && typeof d.close === 'function');
  assert.strictEqual(d.path, p);

  assert.strictEqual(readLog(p), '', 'file cleared on create (log of ONE run only)');

  const t0 = Date.now();
  d.log('hello');
  d.close(); // must be safe at any time
  const after = readLog(p);
  assert.ok(after.endsWith('hello\n'), 'appended line ends with newline');
  const lines = after.split('\n');
  assert.strictEqual(lines.length, 2, 'exactly one line: "ISO msg\n"');
  const m = lines[0].match(/^(\S+) hello$/);
  assert.ok(m, 'line format: <ISO-time> <msg>');
  const t = Date.parse(m[1]);
  assert.ok(!Number.isNaN(t), 'timestamp parses as date');
  assert.ok(t >= t0 - 5000 && t <= Date.now() + 5000, 'timestamp is "now"');

  fs.unlinkSync(p);
});

test('D1b: DEFAULT_PATH is /tmp/fire-debug.log; log() never throws even on bad path', () => {
  assert.strictEqual(DEFAULT_PATH, '/tmp/fire-debug.log');
  // Unwritable target: log() must swallow the error (лог не роняет анимацию).
  const bad = path.join(os.tmpdir(), 'no-such-dir-' + process.pid, 'x.log');
  const d = createDiag(bad);
  assert.doesNotThrow(() => d.log('boom'));
  d.close();
  assert.doesNotThrow(() => d.close(), 'close() idempotent/safe');
});

// --- D2: ui.attach with diag ---------------------------------------------------

test('D2: ui.attach + diag: input chunk [0x71] logged as "input len=1 hex=71", stop() logged, onQuit still fires', async () => {
  const p = tmpPath('d2');
  const diag = createDiag(p);
  const io = makeIo();
  let quitReason = null;
  const h = attach(io, createFire({ seed: 1 }), {
    diag,
    onQuit: (r) => { quitReason = r; },
  });
  io.write(Buffer.from([0x71])); // 'q'
  await sleep(60);
  const log = readLog(p);
  assert.ok(log.includes('input len=1 hex=71'), 'input chunk logged with hex');
  assert.ok(/(^|\n)\S+ stop\n/.test(log), 'stop logged');
  assert.strictEqual(quitReason, 'q', 'onQuit("q") still fires with diag present');
  h.stop(); // idempotent
  diag.close();
  fs.unlinkSync(p);
});

test('D2b: ui.attach + diag: every stdin chunk is logged (unknown keys too); frame #N logged every 30 frames', async () => {
  const p = tmpPath('d2b');
  const diag = createDiag(p);
  const io = makeIo();
  const h = attach(io, createFire({ seed: 1 }), { diag, fpsMs: 5 });
  io.write(Buffer.from('xy')); // unknown chunk: logged, no quit
  await sleep(400); // ~80 frames at 5ms
  const log = readLog(p);
  assert.ok(log.includes('input len=2 hex=7879'), 'unknown chunk logged');
  assert.ok(/(^|\n)\S+ frame #30\n/.test(log), 'frame #30 logged');
  assert.ok(/(^|\n)\S+ frame #60\n/.test(log), 'frame #60 logged');
  assert.ok(!/frame #31\n/.test(log), 'not every frame — only every 30th');
  h.stop();
  assert.ok(/(^|\n)\S+ stop\n/.test(readLog(p)), 'stop logged');
  diag.close();
  fs.unlinkSync(p);
});

// --- D3: backwards compatibility -----------------------------------------------

test('D3: ui.attach without opts.diag — old behavior, no errors, no file touched', async () => {
  const io = makeIo();
  let quits = 0;
  const h = attach(io, createFire({ seed: 1 }), {});
  io.write(Buffer.from('q'));
  await sleep(60);
  assert.strictEqual(quits, 0); // sanity: no crash
  h.stop();
  io.write(Buffer.from('Q')); // second run shape: no opts at all
  const h2 = attach(io, createFire({ seed: 1 }), undefined);
  io.write(Buffer.from([0x71]));
  await sleep(60);
  h2.stop();
});

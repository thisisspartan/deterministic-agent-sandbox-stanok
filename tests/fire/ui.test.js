'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { attach } = require('../../src/fire/ui.js');
const { createFire } = require('../../src/fire/fire.js');

const sleep = (ms) => new Promise(res => setTimeout(res, ms));

function makeIo(hook) {
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
  if (hook) hook(io);
  return io;
}

function makeFire() {
  return createFire({ seed: 1 });
}

// --- attach lifecycle ---------------------------------------------------------

test('attach: raw-mode on, alt-screen + hide cursor at start, frames rendered, stop() restores', async () => {
  const io = makeIo();
  const fire = makeFire();
  const h = attach(io, fire, {});
  assert.ok(h && typeof h.stop === 'function');
  assert.strictEqual(io.stdin._rawMode, true, 'raw mode enabled');
  const start = io._written.join('');
  assert.ok(start.includes('\u001b[?1049h'), 'alt screen entered');
  assert.ok(start.includes('\u001b[?25l'), 'cursor hidden');

  await sleep(120);
  const all = io._written.join('');
  assert.ok(all.length > 0, 'frames written');

  h.stop();
  assert.strictEqual(io.stdin._rawMode, false, 'raw mode off after stop');
  const after = io._written.join('');
  assert.ok(after.includes('\u001b[?25h'), 'cursor restored');
  assert.ok(after.includes('\u001b[?1049l'), 'alt screen left');
  const n = io._written.length;
  await sleep(100);
  assert.strictEqual(io._written.length, n, 'loop halted after stop');
});

// --- quit keys ------------------------------------------------------------------

test('quit: q stops the loop and restores terminal', async () => {
  const io = makeIo();
  let quits = 0;
  const h = attach(io, makeFire(), { onQuit: () => { quits++; } });
  io.write(Buffer.from('q'));
  await sleep(60);
  assert.strictEqual(quits, 1, 'onQuit fired');
  assert.strictEqual(io.stdin._rawMode, false, 'raw mode off');
  assert.ok(io._written.join('').includes('\u001b[?1049l'), 'alt screen left after q');
  h.stop(); // idempotent
});

test('quit: Q also quits', async () => {
  const io = makeIo();
  let quits = 0;
  const h = attach(io, makeFire(), { onQuit: () => { quits++; } });
  io.write(Buffer.from('Q'));
  await sleep(60);
  assert.strictEqual(quits, 1);
  assert.strictEqual(io.stdin._rawMode, false);
  h.stop();
});

test('quit: ESC quits', async () => {
  const io = makeIo();
  let quits = 0;
  const h = attach(io, makeFire(), { onQuit: () => { quits++; } });
  io.write(Buffer.from('\u001b'));
  await sleep(60);
  assert.strictEqual(quits, 1, 'lone ESC quits');
  assert.strictEqual(io.stdin._rawMode, false);
  h.stop();
});

test('quit: Ctrl+C (0x03) quits', async () => {
  const io = makeIo();
  let quits = 0;
  const h = attach(io, makeFire(), { onQuit: () => { quits++; } });
  io.write(Buffer.from([0x03]));
  await sleep(60);
  assert.strictEqual(quits, 1, 'Ctrl+C quits');
  assert.strictEqual(io.stdin._rawMode, false);
  h.stop();
});

test('stop() without any key input still restores cursor and leaves alt screen', async () => {
  const io = makeIo();
  const h = attach(io, makeFire(), {});
  h.stop();
  const out = io._written.join('');
  assert.ok(out.includes('\u001b[?1049h') && out.includes('\u001b[?1049l'), 'alt in/out');
  assert.ok(out.includes('\u001b[?25l') && out.includes('\u001b[?25h'), 'cursor hide/show');
});

test('unknown keys do not quit', async () => {
  const io = makeIo();
  let quits = 0;
  const h = attach(io, makeFire(), { onQuit: () => { quits++; } });
  io.write(Buffer.from('x'));
  io.write(Buffer.from(' '));
  await sleep(60);
  assert.strictEqual(quits, 0, 'x / space must not quit');
  assert.strictEqual(io.stdin._rawMode, true, 'still running');
  h.stop();
  assert.strictEqual(io.stdin._rawMode, false, 'stop() restores terminal');
  assert.strictEqual(quits, 0, 'plain stop() does not fire onQuit (only keys do)');
});

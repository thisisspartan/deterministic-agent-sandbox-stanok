'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { attach, ROT_STEP } = require('../../src/fire3d/ui.js');
const { create } = require('../../src/fire3d/fire3d.js');

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
  return create({ seed: 1, W: 16, H: 10, D: 16 });
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

test('quit: q stops the loop and restores the terminal', async () => {
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

test('quit: Q / ESC / Ctrl+C also quit, with their reasons', async () => {
  for (const [bytes, expected] of [
    [[0x51], 'Q'],
    [[0x1b], 'esc'],
    [[0x03], 'ctrl-c'],
  ]) {
    const io = makeIo();
    let reason = null;
    const h = attach(io, makeFire(), { onQuit: (r) => { reason = r; } });
    io.write(Buffer.from(bytes));
    await sleep(60);
    assert.strictEqual(reason, expected, `onQuit reason for ${JSON.stringify(bytes)}`);
    assert.strictEqual(io.stdin._rawMode, false, 'raw mode off');
    h.stop();
  }
});

test('stop() without any key input still restores cursor and leaves alt screen', async () => {
  const io = makeIo();
  const h = attach(io, makeFire(), {});
  h.stop();
  const out = io._written.join('');
  assert.ok(out.includes('\u001b[?1049h') && out.includes('\u001b[?1049l'), 'alt in/out');
  assert.ok(out.includes('\u001b[?25l') && out.includes('\u001b[?25h'), 'cursor hide/show');
});

// --- arrow keys: rotation, no quit ------------------------------------------------

test('arrow: CSI \\u001b[D (left) decreases fire.angle and does NOT quit', async () => {
  const io = makeIo();
  const fire = makeFire();
  let quits = 0;
  const h = attach(io, fire, { onQuit: () => { quits++; } });
  const before = fire.angle;
  io.write(Buffer.from([0x1b, 0x5b, 0x44])); // \u001b[D — left arrow
  await sleep(60);
  assert.strictEqual(quits, 0, 'left arrow must not quit');
  assert.strictEqual(fire.angle, before - ROT_STEP, 'angle decreased by ROT_STEP');
  assert.strictEqual(io.stdin._rawMode, true, 'still running');
  h.stop();
});

test('arrow: CSI \\u001b[C (right) increases fire.angle and does NOT quit', async () => {
  const io = makeIo();
  const fire = makeFire();
  let quits = 0;
  const h = attach(io, fire, { onQuit: () => { quits++; } });
  const before = fire.angle;
  io.write(Buffer.from([0x1b, 0x5b, 0x43])); // \u001b[C — right arrow
  await sleep(60);
  assert.strictEqual(quits, 0, 'right arrow must not quit');
  assert.strictEqual(fire.angle, before + ROT_STEP, 'angle increased by ROT_STEP');
  assert.strictEqual(io.stdin._rawMode, true, 'still running');
  h.stop();
});

test('arrows held: repeated CSI chunks rotate continuously, no quit', async () => {
  const io = makeIo();
  const fire = makeFire();
  let quits = 0;
  const h = attach(io, fire, { onQuit: () => { quits++; } });
  for (let i = 0; i < 5; i++) io.write(Buffer.from([0x1b, 0x5b, 0x44]));
  io.write(Buffer.from([0x1b, 0x5b, 0x43]));
  await sleep(80);
  assert.strictEqual(quits, 0, 'auto-repeat must not quit');
  // Net rotation 4*ROT_STEP left (tolerance: repeated +- on floats).
  assert.ok(Math.abs(fire.angle + 4 * ROT_STEP) < 1e-9,
    `net angle ${fire.angle} ≈ -4*ROT_STEP (${-4 * ROT_STEP})`);
  h.stop();
});

test('other CSI sequences (F-keys, up arrow, paste) are ignored, no quit', async () => {
  const io = makeIo();
  const fire = makeFire();
  let quits = 0;
  const h = attach(io, fire, { onQuit: () => { quits++; } });
  io.write(Buffer.from([0x1b, 0x5b, 0x41]));            // up arrow
  io.write(Buffer.from([0x1b, 0x5b, 0x31, 0x3b, 0x35, 0x7e])); // F5
  io.write(Buffer.from([0x1b, 0x5b, 0x32, 0x30, 0x30, 0x62])); // bracketed paste start
  await sleep(150);
  assert.strictEqual(quits, 0, 'other CSI must not quit');
  assert.strictEqual(fire.angle, 0, 'angle untouched');
  assert.strictEqual(io.stdin._rawMode, true, 'still running');
  const n = io._written.length;
  await sleep(100);
  assert.ok(io._written.length > n, 'frame loop continued');
  h.stop();
});

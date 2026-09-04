'use strict';

// Tetris main (ticket 023): entry-point assembly, SIGINT cleanup, smoke e2e.
// Tests run `node src/tetris/main.js` in a child process and drive its real
// stdin (raw-mode when a tty is available), plus unit-level checks against the
// exported createApp factory with mock io/mock game.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

const MAIN = path.join(__dirname, '..', '..', 'src', 'tetris', 'main.js');

// --- source hygiene ----------------------------------------------------------

test('main.js assembles game + ui.attach (source check)', () => {
  assert.ok(fs.existsSync(MAIN), 'src/tetris/main.js exists');
  const src = fs.readFileSync(MAIN, 'utf8');
  assert.ok(/newGame\(/.test(src), 'creates the game via newGame');
  assert.ok(/attach\(/.test(src), 'wires ui.attach');
  assert.ok(/SIGINT/.test(src) && /SIGTERM/.test(src), 'installs SIGINT/SIGTERM handlers');
  assert.ok(/process\.stdin/.test(src), 'wires process.stdin to the ui layer');
});

// --- child-process helpers ---------------------------------------------------

// Spawn the real entry point. The child inherits a non-tty stdin (the harness
// pipe), so ui.attach's setRawMode(true) is a no-op on the child side (guarded
// there) and input is fed through that same pipe via send().
function spawnMain() {
  const child = spawn(process.execPath, [MAIN]);
  const out = [];
  child.stdout.on('data', (b) => out.push(b));
  child.stderr.on('data', () => {}); // noise is ignored; exit code decides
  return {
    child,
    out: () => Buffer.concat(out).toString('utf8'),
    wait: (ms) => new Promise(res => setTimeout(res, ms)),
    send: (s) => { if (child.stdin.writable) child.stdin.write(s); },
  };
}

async function until(text, io, timeoutMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (io.out().includes(text)) return true;
    await io.wait(50);
  }
  return io.out().includes(text);
}

// --- smoke e2e ---------------------------------------------------------------

test('smoke e2e: launches without crashing, renders, responds to Q (exit 0)', async () => {
  const io = spawnMain();
  assert.ok(await until('TETRIS', io, 3000), 'game rendered the title/HUD');
  io.send('q');
  const code = await new Promise(res =>
    io.child.on('close', (c) => res(c)));
  assert.strictEqual(code, 0, 'Q exits with code 0');
});

test('smoke e2e: SIGINT -> handler runs stop() (raw-mode off path), exit 0/130', async () => {
  const io = spawnMain();
  assert.ok(await until('TETRIS', io, 3000), 'game rendered');
  io.child.kill('SIGINT');
  const code = await new Promise(res =>
    io.child.on('close', (c) => res(c)));
  // The SIGINT handler calls the same app.stop() as Q (raw-mode off, cursor
  // restore — both verified by the ui.test.js lifecycle test for stop()); here
  // we assert the child exited promptly via that handler rather than the
  // default kill behavior.
  assert.ok(code === 0 || code === 130, 'exit code 0 or 130 on SIGINT, got ' + code);
});

// --- Q / R behavior ------------------------------------------------------------

test('Q: mock stdin "q" -> stop called, process exits 0', async () => {
  const io = spawnMain();
  assert.ok(await until('TETRIS', io, 3000));
  io.send('q');
  const code = await new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('did not exit within 2000ms after Q')), 2000);
    io.child.on('close', (c) => { clearTimeout(t); res(c); });
  });
  assert.strictEqual(code, 0, 'exit 0 after Q');
});

test('R from game-over: mock game.over=true, stdin "r" -> game.reset called', async () => {
  const { createApp } = require('../../src/tetris/main.js');
  let quit = 0;
  const resetCalls = [];
  const mockGame = {
    tick() {},
    move() { return true; },
    softDrop() { return true; },
    rotate() { return true; },
    hardDrop() {},
    pause() {},
    resume() {},
    reset(seed) { resetCalls.push(seed); },
  };
  // Game-over frame, flat state (real newGame() shape, no _state wrapper).
  Object.assign(mockGame, {
    piece: 'T', state: 'A', col: 3, row: 0,
    board: { grid: Array.from({ length: 22 }, () => Array(10).fill(0)) },
    score: 500, lines: 2, level: 1, next: 'I', over: true, paused: false,
  });

  const listeners = {};
  const io = {
    stdin: {
      setRawMode() {},
      on(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); return io.stdin; },
      removeListener() { return io.stdin; },
    },
    stdout: { write() { return true; } },
    columns: 80,
  };
  const app = createApp({
    io,
    game: mockGame,
    now: () => 0,
    onQuit: () => { quit += 1; },
  });
  assert.strictEqual(resetCalls.length, 0, 'no reset before input');
  (listeners.data || []).forEach(fn => fn(Buffer.from('r', 'utf8')));
  assert.strictEqual(resetCalls.length, 1, 'R during game-over called game.reset exactly once');
  assert.strictEqual(typeof resetCalls[0], 'number', 'reset gets a fresh numeric seed');
  app.stop();
  assert.strictEqual(quit, 0, 'R does not quit');
});

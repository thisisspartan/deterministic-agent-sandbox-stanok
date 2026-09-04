'use strict';

// Ticket 045 — application cursor key mode (DECCKM) arrows, clean exit,
// diagnostics/robustness regression of main.js.

const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const { parseInput, attach, ROT_STEP } = require('../../src/fire3d/ui.js');
const { create, FLAME_GLYPHS } = require('../../src/fire3d/fire3d.js');

function makeFire() {
  return create({ seed: 1, W: 16, H: 10, D: 16 });
}

// --- C5.1–C5.6: parseInput — application-mode (SS3) arrows + regression ----

// C5.1: application-mode right arrow \u001bOC — rotates, does not quit.
test('keys: application-mode \\u001bOC (right) increases fire.angle by ROT_STEP, returns null', () => {
  const fire = makeFire();
  const before = fire.angle;
  const r = parseInput(Buffer.from([0x1b, 0x4f, 0x43]), fire);
  assert.strictEqual(r, null, 'application right arrow must not quit');
  assert.strictEqual(fire.angle, before + ROT_STEP, 'angle += ROT_STEP');
});

// C5.2: application-mode left arrow \u001bOD — rotates, does not quit.
test('keys: application-mode \\u001bOD (left) decreases fire.angle by ROT_STEP', () => {
  const fire = makeFire();
  const before = fire.angle;
  const r = parseInput(Buffer.from([0x1b, 0x4f, 0x44]), fire);
  assert.strictEqual(r, null, 'application left arrow must not quit');
  assert.strictEqual(fire.angle, before - ROT_STEP, 'angle -= ROT_STEP');
});

// C5.3: application-mode up arrow \u001bOA — ignored, angle unchanged.
test('keys: application-mode \\u001bOA (up) is ignored, angle unchanged', () => {
  const fire = makeFire();
  const before = fire.angle;
  assert.strictEqual(parseInput(Buffer.from([0x1b, 0x4f, 0x41]), fire), null);
  assert.strictEqual(fire.angle, before, 'up arrow must not rotate');
});

// C5.4: other application-mode sequence \u001bOX — ignored, angle unchanged.
test('keys: other application-mode \\u001bOX is ignored, angle unchanged', () => {
  const fire = makeFire();
  const before = fire.angle;
  assert.strictEqual(parseInput(Buffer.from([0x1b, 0x4f, 0x58]), fire), null);
  assert.strictEqual(fire.angle, before, 'unknown ESC O x must not rotate');
});

// C5.5: CSI right arrow \u001b[C — regression, same as before (+ROT_STEP).
test('keys: CSI \\u001b[C (right) still increases fire.angle (regression)', () => {
  const fire = makeFire();
  const before = fire.angle;
  assert.strictEqual(parseInput(Buffer.from([0x1b, 0x5b, 0x43]), fire), null);
  assert.strictEqual(fire.angle, before + ROT_STEP, 'angle += ROT_STEP');
});

// C5.6: lone ESC — still quits with reason 'esc' (not broken by ESC O support).
test('keys: lone \\u001b still quits with reason \'esc\' (regression)', () => {
  const fire = makeFire();
  assert.strictEqual(parseInput(Buffer.from([0x1b]), fire), 'esc');
});

// --- C5.7: stop() clears the frame area before restoring the terminal --------

function makeIo() {
  const listeners = {};
  const written = [];
  const io = {
    columns: 20, // > W=16 -> cols = min(W, floor(20)) = 16
    rows: 12,    // rows_screen = min(H=10, max(2, 11)) = 10 (not compact)
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
  return io;
}

test('stop(): clears the frame area (CURSOR_HOME + blank lines) BEFORE CURSOR_SHOW + ALT_OFF', () => {
  const io = makeIo();
  const fire = makeFire(); // W = 16, H = 10
  const h = attach(io, fire, {});
  h.stop();
  const last = io._written[io._written.length - 1];
  const cols = 16;          // min(W, floor(columns))
  const rowsScreen = 10;    // min(H, max(2, rows - 1))
  const blank = ' '.repeat(cols);
  assert.ok(last.startsWith('\u001b[H'), 'stop output starts with CURSOR_HOME');
  const body = last.slice(0, last.indexOf('\u001b[?25h'));
  const lines = body.split('\n');
  assert.strictEqual(lines.length, rowsScreen + 1, 'rows_screen blank lines + tail line');
  assert.ok(lines[0] === '\u001b[H' + blank, 'first line: CURSOR_HOME + full-width spaces');
  for (let i = 1; i < rowsScreen; i++) {
    assert.strictEqual(lines[i], blank, 'line ' + i + ' is `cols` spaces');
  }
  assert.ok(lines[rowsScreen].startsWith('\u001b[J'),
    'CLEAR_TAIL after the blank area (rows_screen != rows-1)');
  assert.ok(last.includes('\u001b[?25h'), 'cursor shown after the clear');
  assert.ok(last.includes('\u001b[?1049l'), 'alt screen left after the clear');
  assert.ok(last.indexOf('\u001b[H') < last.indexOf('\u001b[?25h'),
    'frame-area clear happens BEFORE cursor show + alt off');
  assert.strictEqual(io.stdin._rawMode, false, 'raw mode off after stop');
});

// --- C5.8: main.js --frame regression (CC-044) ---------------------------------

test('main.js --frame (regression from CC-044): exit 0 and visible flame glyphs in stdout', () => {
  const main = path.join(__dirname, '..', '..', 'src', 'fire3d', 'main.js');
  const res = spawnSync(process.execPath, [main, '--frame'], { encoding: 'utf8' });
  assert.ok(!res.error, 'spawn failed: ' + (res.error && res.error.message));
  assert.strictEqual(res.status, 0, '--frame must exit with code 0');
  assert.ok(res.stdout.length > 0, 'stdout is not empty');
  const glyphs = new Set([...FLAME_GLYPHS].filter((g) => g !== ' '));
  const plain = res.stdout.replace(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
  assert.ok([...plain].some((ch) => glyphs.has(ch)),
    'frame contains visible flame glyphs (not only spaces)');
});

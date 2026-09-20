'use strict';
// tests/fire.test.js — reference contract for src/fire.js (terminal fire).
const test = require('node:test');
const assert = require('node:assert');

const fire = require('../src/fire.js');

function makeFrame(seed, ticks, cols, rows) {
  const f = fire.createFire(cols, rows, seed);
  for (let i = 0; i < ticks; i++) fire.step(f);
  return { f, frame: fire.render(f) };
}

test('determinism: same seed produces identical rendered frame strings', () => {
  const a = makeFrame(42, 8, 40, 32);
  const b = makeFrame(42, 8, 40, 32);
  assert.strictEqual(a.frame, b.frame, 'same seed must render identically');
  const c = makeFrame(43, 8, 40, 32);
  assert.notStrictEqual(a.frame, c.frame, 'different seed should differ');
});

test('heat field: all values in [0,1] and the field changes between two ticks', () => {
  const f = fire.createFire(30, 24, 7);
  fire.step(f);
  for (let i = 0; i < f.heat.length; i++) {
    assert.ok(f.heat[i] >= 0 && f.heat[i] <= 1, `heat out of [0,1]: ${f.heat[i]}`);
  }
  const before = f.heat; // step() replaces f.heat with a fresh array
  fire.step(f);
  const after = f.heat;
  assert.notDeepEqual(before, after, 'heat field must change between ticks');
});

test('palette: RGB in 0-255, hot core brighter than cool edge, zero heat -> empty cell', () => {
  for (const t of [0.0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 0.9, 1.0]) {
    const c = fire.palette(t);
    if (c !== null) {
      for (const v of [c.r, c.g, c.b]) {
        assert.ok(Number.isInteger(v) && v >= 0 && v <= 255,
          `palette(${t}) component out of range: ${v}`);
      }
    }
  }
  const hot = fire.palette(0.9);
  const cool = fire.palette(0.2);
  assert.ok(hot.r + hot.g + hot.b > cool.r + cool.g + cool.b,
    'hot core must map brighter than cool edge');
  assert.strictEqual(fire.palette(0), null, 'zero heat must map to an empty cell');
});

test('renderer: frame contains ANSI escapes and its dimensions match the grid', () => {
  const { f, frame } = makeFrame(99, 10, 40, 32);
  assert.ok(frame.includes('\x1b['), 'frame must contain ANSI escape sequences');
  const lines = frame.split('\n');
  // rows/2 terminal lines; each cell is two half-block chars (top + bottom)
  assert.strictEqual(lines.length, f.rows / 2, 'frame height must match grid');
  for (const line of lines) {
    const plain = line.replace(/\x1b\[[0-9;]*m/g, '');
    assert.strictEqual(plain.length, f.cols * 2, 'frame width must match grid');
  }
});

test('renderer: a zero-heat grid renders a fully empty frame (no escapes)', () => {
  const cols = 16, rows = 8;
  const f = {
    cols,
    rows,
    heat: new Float64Array(cols * rows),
    smoke: new Float64Array(cols * rows),
  };
  const frame = fire.render(f);
  assert.ok(!frame.includes('\x1b'), 'zero heat must emit no escape sequences');
  const lines = frame.split('\n');
  assert.strictEqual(lines.length, rows / 2);
  for (const line of lines) {
    assert.strictEqual(line, ' '.repeat(cols * 2));
  }
});

test('smoke: values stay in [0,1] and smoke is present above the flame', () => {
  const f = fire.createFire(40, 32, 5);
  for (let i = 0; i < 40; i++) fire.step(f);
  for (let i = 0; i < f.smoke.length; i++) {
    assert.ok(f.smoke[i] >= 0 && f.smoke[i] <= 1, `smoke out of [0,1]: ${f.smoke[i]}`);
  }
  assert.ok(f.smoke.some((v) => v > 0), 'smoke should be present after 40 ticks');
});

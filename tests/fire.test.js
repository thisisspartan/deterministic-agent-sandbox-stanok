'use strict';
// Test contract for src/fire.js (see docs/fire.md).
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  createPRNG,
  createSim,
  tick,
  palette,
  renderFrame,
} = require('../src/fire.js');

const stripAnsi = (s) => s.replace(/\x1b\[[0-9;]*m/g, '');
const brightness = (c) => c[0] + c[1] + c[2];

test('determinism: same seed -> identical rendered frame string', () => {
  const a = createSim({ width: 24, height: 16, seed: 42 });
  const b = createSim({ width: 24, height: 16, seed: 42 });
  for (let i = 0; i < 12; i++) {
    tick(a);
    tick(b);
  }
  const fa = renderFrame(a);
  const fb = renderFrame(b);
  assert.equal(typeof fa, 'string');
  assert.ok(fa.length > 0);
  assert.strictEqual(fa, fb, 'same seed must produce identical frames');

  const c = createSim({ width: 24, height: 16, seed: 43 });
  for (let i = 0; i < 12; i++) tick(c);
  assert.notStrictEqual(renderFrame(c), fa, 'different seed must diverge');
});

test('heat field: values in [0,1] and the field changes between ticks', () => {
  const sim = createSim({ width: 20, height: 12, seed: 7 });
  for (let i = 0; i < 10; i++) tick(sim);
  for (const row of sim.heat) {
    for (const v of row) {
      assert.ok(Number.isFinite(v) && v >= 0 && v <= 1, `heat out of [0,1]: ${v}`);
    }
  }
  let max = 0;
  for (const row of sim.heat) for (const v of row) max = Math.max(max, v);
  assert.ok(max > 0.5, 'flame must actually burn after 10 ticks');

  const before = JSON.stringify(sim.heat);
  tick(sim);
  const after = JSON.stringify(sim.heat);
  assert.notStrictEqual(after, before, 'field must evolve between ticks');
});

test('palette: 0-255 components, hot core brighter than cool edge, zero -> empty', () => {
  for (const t of [0.02, 0.1, 0.25, 0.5, 0.75, 0.95, 1]) {
    const c = palette(t);
    assert.ok(Array.isArray(c) && c.length === 3, `palette(${t}) must be [r,g,b]`);
    for (const v of c) {
      assert.ok(Number.isInteger(v) && v >= 0 && v <= 255, `component out of range: ${v}`);
    }
  }
  assert.ok(brightness(palette(0.95)) > brightness(palette(0.2)),
    'hot core must be brighter than a cool edge');
  assert.ok(brightness(palette(1)) >= brightness(palette(0.95)),
    'gradient must not darken towards the white-hot core');
  assert.strictEqual(palette(0), null, 'zero heat must be an empty cell');
});

test('renderer: frame contains ANSI escapes and matches grid dimensions', () => {
  const sim = createSim({ width: 21, height: 15, seed: 99 });
  for (let i = 0; i < 8; i++) tick(sim);
  const frame = renderFrame(sim);
  assert.ok(frame.includes('\x1b[38;2;'), 'frame must contain 24-bit truecolor escapes');
  const plain = stripAnsi(frame);
  const lines = plain.split('\n');
  assert.strictEqual(lines.length, Math.ceil(sim.height / 2),
    'frame rows must be ceil(grid height / 2) half-block rows');
  for (const line of lines) {
    assert.strictEqual(line.length, sim.width, 'frame width must equal grid width');
    for (const ch of line) {
      assert.ok(ch === ' ' || ch === '\u2580', `unexpected glyph: ${ch}`);
    }
  }
});

test('smoke: faint particles rise above the flame', () => {
  const sim = createSim({ width: 24, height: 20, seed: 7 });
  for (let i = 0; i < 40; i++) tick(sim);
  let smokeMass = 0;
  for (const row of sim.smoke) for (const v of row) smokeMass += v;
  assert.ok(smokeMass > 0, 'smoke particles must exist after 40 ticks');
  for (const row of sim.smoke) {
    for (const v of row) assert.ok(v >= 0 && v <= 1, `smoke out of [0,1]: ${v}`);
  }
});

test('module loads headless: exports present, PRNG deterministic, no animation started', () => {
  const m = require('../src/fire.js');
  for (const fn of ['createPRNG', 'createSim', 'tick', 'palette', 'renderFrame']) {
    assert.equal(typeof m[fn], 'function', `missing export: ${fn}`);
  }
  const p1 = m.createPRNG(1);
  const p2 = m.createPRNG(1);
  assert.strictEqual(p1(), p2(), 'PRNG must be seeded/deterministic');
});

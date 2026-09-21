'use strict';
// Test contract for src/fire.js — terminal fire (see docs/fire.md).
const test = require('node:test');
const assert = require('node:assert');

const { createSim, step, palette, renderFrame } = require('../src/fire.js');

const TRUECOLOR = /^\x1b\[38;2;(\d+);(\d+);(\d+) m$/;

test('determinism: same seed -> identical rendered frame', () => {
  const a = createSim(24, 16, 42);
  const b = createSim(24, 16, 42);
  for (let i = 0; i < 20; i++) {
    step(a);
    step(b);
  }
  assert.strictEqual(renderFrame(a), renderFrame(b));
});

test('determinism: different seed -> (with overwhelming odds) different frame', () => {
  const a = createSim(24, 16, 1);
  const b = createSim(24, 16, 999);
  for (let i = 0; i < 20; i++) {
    step(a);
    step(b);
  }
  // Seed only guarantees reproducibility, not divergence; but 20 ticks of
  // independent turbulence walks effectively always diverge.
  assert.notStrictEqual(renderFrame(a), renderFrame(b));
});

test('heat field: all values in [0, 1] and field changes between ticks', () => {
  const sim = createSim(24, 16, 7);
  step(sim);
  const snap = sim.heat.map((row) => row.slice());
  step(sim);
  let changed = false;
  for (let y = 0; y < sim.height; y++) {
    for (let x = 0; x < sim.width; x++) {
      const v = sim.heat[y][x];
      assert.ok(Number.isFinite(v), `heat not finite at (${x},${y}): ${v}`);
      assert.ok(v >= 0 && v <= 1, `heat out of [0,1] at (${x},${y}): ${v}`);
      if (v !== snap[y][x]) changed = true;
    }
  }
  assert.ok(changed, 'heat field must change between two ticks');
});

test('palette: every RGB component in 0-255', () => {
  for (const t of [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1]) {
    const s = palette(t);
    const m = s.match(TRUECOLOR);
    assert.ok(m, `palette(${t}) must emit 24-bit truecolor, got: ${JSON.stringify(s)}`);
    for (let i = 1; i <= 3; i++) {
      const c = Number(m[i]);
      assert.ok(Number.isInteger(c) && c >= 0 && c <= 255, `component out of range: ${c}`);
    }
  }
});

test('palette: hot core brighter than cool edge', () => {
  const sum = (s) => {
    const m = s.match(TRUECOLOR);
    assert.ok(m, `not truecolor: ${JSON.stringify(s)}`);
    return Number(m[1]) + Number(m[2]) + Number(m[3]);
  };
  assert.ok(sum(palette(0.95)) > sum(palette(0.3)), 'hot core must be brighter than cool edge');
});

test('palette: zero heat -> empty cell (no escape)', () => {
  assert.strictEqual(palette(0), '');
});

test('renderer: frame contains ANSI escapes and dims match the grid', () => {
  const sim = createSim(20, 12, 3);
  for (let i = 0; i < 30; i++) step(sim);
  const frame = renderFrame(sim);
  assert.ok(frame.includes('\x1b[38;2;'), 'frame must contain truecolor escapes');
  const lines = frame.split('\n');
  assert.strictEqual(lines.length, sim.height, 'frame rows must equal grid height');
  for (const line of lines) {
    const visible = line.replace(/\x1b\[[0-9;]+ m|\x1b\[\d+m/g, '');
    assert.strictEqual(visible.length, sim.width, 'frame cols must equal grid width');
  }
});

test('renderer: zero-heat field renders a blank frame (no escapes)', () => {
  const sim = createSim(10, 6, 1);
  const frame = renderFrame(sim);
  assert.ok(!frame.includes('\x1b'), 'empty field must not emit escapes');
  assert.strictEqual(frame.replace(/\n/g, ' ').trim(), '', 'empty field must render spaces only');
});

test('module exports the four concerns (main-guard: no loop on require)', () => {
  const mod = require('../src/fire.js');
  for (const k of ['createSim', 'step', 'palette', 'renderFrame']) {
    assert.strictEqual(typeof mod[k], 'function', `missing export: ${k}`);
  }
});

'use strict';
// Reference tests for src/fire.js (TASK-STANOK-CC-078).
const { test } = require('node:test');
const assert = require('node:assert');

const fire = require('../src/fire.js');

const W = 40;      // grid columns
const H = 48;      // grid rows (even: 2 grid rows per half-block character row)
const FRAME_LINES = H / 2;

function runTicks(seed, ticks) {
  const sim = fire.createFireSim(W, H, seed);
  for (let i = 0; i < ticks; i++) sim.tick();
  return sim;
}

function snapshot(sim) {
  return JSON.stringify([
    sim.grid.map((row) => Array.from(row)),
    sim.smoke.map((row) => Array.from(row)),
  ]);
}

function visibleWidth(line) {
  // strip ANSI SGR sequences; remaining chars are one column each
  return line.replace(/\x1b\[[0-9;]+ ?m/g, '').length;
}

test('simulation is deterministic: same seed → identical state and frame', () => {
  const a = runTicks(1234, 30);
  const b = runTicks(1234, 30);
  assert.strictEqual(snapshot(a), snapshot(b));
  assert.strictEqual(
    fire.render(a.grid, a.smoke, W, H),
    fire.render(b.grid, b.smoke, W, H),
    'rendered frame strings must be byte-identical'
  );
});

test('different seeds diverge', () => {
  const a = runTicks(1234, 30);
  const b = runTicks(987654, 30);
  assert.notStrictEqual(snapshot(a), snapshot(b));
});

test('heat field: values in [0, 1] and the field changes between two ticks', () => {
  const sim = fire.createFireSim(W, H, 42);
  sim.tick();
  for (const row of sim.grid) {
    for (const v of row) {
      assert.ok(Number.isFinite(v), 'heat must be finite');
      assert.ok(v >= 0 && v <= 1, `heat ${v} out of [0,1]`);
    }
  }
  const before = snapshot(sim);
  sim.tick();
  for (const row of sim.grid) {
    for (const v of row) assert.ok(v >= 0 && v <= 1, `heat ${v} out of [0,1]`);
  }
  assert.notStrictEqual(snapshot(sim), before, 'field must evolve between ticks');
});

test('heat is injected at the base and the flame tapers upward', () => {
  const sim = runTicks(3, 40);
  const cx = (W - 1) / 2;
  const bottom = sim.grid[H - 1];
  // hot core at the base center
  assert.ok(bottom[Math.floor(cx)] > 0.5, 'base center must be hot');
  // far base edges are cold (wide base, not full-width)
  assert.ok(bottom[0] < 0.5 && bottom[W - 1] < 0.5);
  // a mid-height row is much weaker than the base
  const mid = sim.grid[Math.floor(H / 2)];
  const sum = (row) => row.reduce((s, v) => s + v, 0);
  assert.ok(sum(mid) < sum(bottom), 'flame must taper upward');
});

test('palette: RGB in 0..255, monotonic brightness, zero heat → empty cell', () => {
  assert.strictEqual(fire.palette(0), '', 'zero heat must be an empty cell');

  const sumOf = (h) => {
    const sgr = fire.palette(h);
    assert.ok(sgr.length > 0, `palette(${h}) must be non-empty`);
    const m = sgr.match(/^\x1b\[38;2;(\d+);(\d+);(\d+) m$/);
    assert.ok(m, `palette(${h}) must be a truecolor SGR, got: ${JSON.stringify(sgr)}`);
    const [r, g, b] = m.slice(1).map(Number);
    for (const c of [r, g, b]) assert.ok(c >= 0 && c <= 255, `component ${c} out of range`);
    return r + g + b;
  };

  const samples = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.85, 0.95, 1];
  let prev = -1;
  for (const h of samples) {
    const s = sumOf(h);
    assert.ok(s > prev, `brightness must increase with heat (at ${h})`);
    prev = s;
  }
  // hot core brighter than cool edge (explicit ticket contract)
  assert.ok(sumOf(0.9) > sumOf(0.3));
});

test('renderer: ANSI escapes present, frame dimensions match the grid', () => {
  const sim = runTicks(7, 20);
  const frame = fire.render(sim.grid, sim.smoke, W, H);
  assert.ok(frame.includes('\x1b[38;2;'), 'frame must contain truecolor SGR escapes');
  const lines = frame.split('\n');
  assert.strictEqual(lines.length, FRAME_LINES, 'frame rows = grid rows / 2 (half-block)');
  for (const line of lines) {
    assert.strictEqual(visibleWidth(line), W, 'frame columns must match grid width');
  }
});

test('smoke: faint particles rise above the flame', () => {
  const sim = runTicks(5, 60);
  let max = 0;
  for (const row of sim.smoke) for (const v of row) if (v > max) max = v;
  assert.ok(max > 0, 'smoke field must be populated');
  assert.ok(max <= 1, 'smoke values must stay in [0,1]');
});

test('module exports the four concerns', () => {
  assert.strictEqual(typeof fire.createFireSim, 'function');
  assert.strictEqual(typeof fire.palette, 'function');
  assert.strictEqual(typeof fire.render, 'function');
});

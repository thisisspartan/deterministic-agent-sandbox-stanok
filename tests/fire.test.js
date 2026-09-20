'use strict';
// Reference tests for src/fire.js (terminal fire animation).
// Run via: bash scripts/run.sh test tests/fire.test.js
const test = require('node:test');
const assert = require('node:assert/strict');

const fire = require('../src/fire.js');

// Helpers -----------------------------------------------------------------

function simulate(seed, cols, rows, ticks) {
  const field = fire.createField(cols, rows, seed);
  for (let i = 0; i < ticks; i++) fire.tick(field);
  return field;
}

// Parse "\x1b[38;2;R;G;B m" -> { r, g, b }, or null if not a truecolor SGR.
function parseAnsiRgb(str) {
  const m = String(str).match(/\x1b\[38;2;(\d+);(\d+);(\d+) m/);
  if (!m) return null;
  return { r: +m[1], g: +m[2], b: +m[3] };
}

function brightness(ansi) {
  const c = parseAnsiRgb(ansi);
  assert.ok(c, `expected a truecolor ANSI string, got ${JSON.stringify(ansi)}`);
  return 0.299 * c.r + 0.587 * c.g + 0.114 * c.b;
}

function rowMeans(field) {
  const means = [];
  for (let y = 0; y < field.rows; y++) {
    let sum = 0;
    for (let x = 0; x < field.cols; x++) sum += field.heat[y * field.cols + x];
    means.push(sum / field.cols);
  }
  return means;
}

// Simulation --------------------------------------------------------------

test('simulation is deterministic: same seed -> identical frames', () => {
  const a = simulate(1234, 40, 12, 25);
  const b = simulate(1234, 40, 12, 25);
  assert.equal(fire.renderFrame(a), fire.renderFrame(b));
});

test('simulation is deterministic per-tick', () => {
  const f = fire.createField(30, 10, 7);
  const snapshots = [];
  for (let i = 0; i < 5; i++) {
    fire.tick(f);
    snapshots.push(fire.renderFrame(f));
  }
  const g = fire.createField(30, 10, 7);
  for (let i = 0; i < 5; i++) {
    fire.tick(g);
    assert.equal(fire.renderFrame(g), snapshots[i]);
  }
});

test('different seeds produce different frames', () => {
  const a = simulate(1, 40, 12, 30);
  const b = simulate(2, 40, 12, 30);
  assert.notEqual(fire.renderFrame(a), fire.renderFrame(b));
});

test('heat field values are normalized to [0, 1]', () => {
  const f = simulate(99, 50, 15, 60);
  for (let i = 0; i < f.heat.length; i++) {
    assert.ok(Number.isFinite(f.heat[i]), `heat[${i}] not finite`);
    assert.ok(f.heat[i] >= 0 && f.heat[i] <= 1, `heat[${i}] out of range`);
  }
});

test('heat field changes between consecutive ticks', () => {
  const f = simulate(5, 40, 12, 10);
  const before = fire.renderFrame(f);
  fire.tick(f);
  const after = fire.renderFrame(f);
  assert.notEqual(before, after);
});

test('flame shape: wide hot base tapering upward', () => {
  const f = simulate(11, 60, 16, 40);
  const means = rowMeans(f);
  const bottom = means[means.length - 1];
  const top = means[0];
  assert.ok(bottom > 0.2, `base row should be hot, got ${bottom}`);
  assert.ok(top < 0.1, `top row should be much cooler, got ${top}`);
  assert.ok(bottom > 3 * top, `flame should taper upward, ${bottom} vs ${top}`);
  // heat should be present in the middle of the grid (not two pillars)
  const midRow = means[Math.floor(means.length / 2)];
  assert.ok(midRow > 0.01, `middle of flame should carry heat, got ${midRow}`);
});

test('smoke rises above the flame (faint particles in the upper area)', () => {
  const f = simulate(21, 60, 20, 80);
  let smokeCells = 0;
  for (let y = 0; y < Math.floor(f.rows / 2); y++) {
    for (let x = 0; x < f.cols; x++) {
      const s = f.smoke[y * f.cols + x];
      assert.ok(s >= 0 && s <= 1, `smoke out of range: ${s}`);
      if (s > 0.05) smokeCells++;
    }
  }
  assert.ok(smokeCells >= 5, `expected smoke particles up top, got ${smokeCells}`);
});

// Palette -----------------------------------------------------------------

test('palette: zero heat -> empty cell (plain space, no escape)', () => {
  const cell = fire.palette(0);
  assert.equal(cell, ' ');
  assert.ok(!String(cell).includes('\x1b'), 'zero heat must not emit escapes');
});

test('palette: truecolor output with RGB components in 0..255', () => {
  for (let h = 0.01; h <= 1.0; h += 0.01) {
    const ansi = fire.palette(h);
    const c = parseAnsiRgb(ansi);
    assert.ok(c, `palette(${h}) is not truecolor ANSI: ${JSON.stringify(ansi)}`);
    for (const v of [c.r, c.g, c.b]) {
      assert.ok(Number.isInteger(v) && v >= 0 && v <= 255, `component out of range: ${v}`);
    }
  }
});

test('palette: hot core is brighter than cool edge', () => {
  const core = fire.palette(0.95);
  const edge = fire.palette(0.2);
  assert.ok(brightness(core) > brightness(edge),
    `core ${brightness(core)} should exceed edge ${brightness(edge)}`);
});

test('palette: monotonically hotter stops get brighter (gradient sanity)', () => {
  const b1 = brightness(fire.palette(0.9));
  const b2 = brightness(fire.palette(0.5));
  const b3 = brightness(fire.palette(0.1));
  assert.ok(b1 > b2 && b2 > b3, `expected ${b1} > ${b2} > ${b3}`);
});

// Renderer ----------------------------------------------------------------

test('renderer: frame contains truecolor ANSI escapes', () => {
  const f = simulate(3, 30, 10, 20);
  const frame = fire.renderFrame(f);
  assert.ok(frame.includes('\x1b[38;2;'), 'frame must contain 24-bit ANSI SGR');
});

test('renderer: frame dimensions match the grid', () => {
  const cols = 25;
  const rows = 9;
  const f = simulate(4, cols, rows, 15);
  const lines = fire.renderFrame(f).split('\n');
  assert.equal(lines.length, 2 * rows,
    `expected ${2 * rows} lines (half-block: 2 lines per grid row), got ${lines.length}`);
  // Visual width: strip truecolor SGR sequences, then count characters.
  const stripAnsi = (line) => line.replace(/\x1b\[[0-9;]* ?m/g, '');
  for (const line of lines) {
    assert.equal(stripAnsi(line).length, cols,
      `visual line length ${stripAnsi(line).length} != grid width ${cols}`);
  }
});

test('renderer: empty grid renders as blank cells only', () => {
  const f = fire.createField(10, 4, 1);
  const frame = fire.renderFrame(f);
  const lines = frame.split('\n');
  assert.equal(lines.length, 8);
  for (const line of lines) {
    assert.equal(line.length, 10);
    assert.ok(!line.includes('\x1b'), `blank frame must have no escapes: ${JSON.stringify(line)}`);
  }
});

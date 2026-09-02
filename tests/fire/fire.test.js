'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { createFire, render, colorIndex, mulberry32 } = require('../../src/fire/fire.js');

// --- PRNG --------------------------------------------------------------------

test('mulberry32: deterministic, outputs in [0,1)', () => {
  const r1 = mulberry32(9);
  const r2 = mulberry32(9);
  const a = [r1(), r1(), r1()];
  const b = [r2(), r2(), r2()];
  assert.deepStrictEqual(a, b, 'same seed -> same stream');
  for (let i = 0; i < 1000; i++) {
    const v = r1();
    assert.ok(v >= 0 && v < 1, 'value in [0,1): ' + v);
  }
  const r3 = mulberry32(10);
  const diff = [r3(), r3(), r3()];
  assert.notDeepStrictEqual(a, diff, 'different seed -> different stream');
});

// --- physics ------------------------------------------------------------------

test('createFire: defaults 80x24, cold grid, step/sparks present', () => {
  const f = createFire({ seed: 1 });
  assert.strictEqual(f.W, 80);
  assert.strictEqual(f.H, 24);
  assert.strictEqual(f.heat.length, 24);
  assert.strictEqual(f.heat[0].length, 80);
  assert.ok(f.heat.every(row => row.every(v => v === 0)), 'grid starts cold');
  assert.strictEqual(typeof f.step, 'function');
  assert.ok(Array.isArray(f.sparks) && f.sparks.length > 0, 'sparks present');
});

test('createFire: custom size from opts', () => {
  const f = createFire({ W: 40, H: 10, seed: 2 });
  assert.strictEqual(f.W, 40);
  assert.strictEqual(f.H, 10);
  assert.strictEqual(f.heat.length, 10);
  assert.strictEqual(f.heat[0].length, 40);
});

test('heat rises from the bottom: base row hot, upper rows cooler, values in [0..1]', () => {
  const f = createFire({ seed: 7 });
  // Run enough steps for the base heat to propagate up through all rows
  // (heat climbs one row per step), so the gradient, not the noise floor,
  // is what gets compared.
  for (let i = 0; i < 40; i++) f.step();
  const avg = (r) => f.heat[r].reduce((a, b) => a + b, 0) / f.heat[r].length;
  assert.ok(avg(f.H - 1) > 0.8, 'bottom base row ~1.0, got ' + avg(f.H - 1));
  assert.ok(avg(0) < avg(f.H - 1), 'top row cooler than bottom');
  assert.ok(avg(2) < avg(10), 'heat decays upward (row 2 < row 10)');
  assert.ok(f.heat.every(row => row.every(v => v >= 0 && v <= 1)), 'heat clamped to [0..1]');
});

test('determinism: two runs with the same seed produce identical frames', () => {
  const a = createFire({ seed: 42 });
  const b = createFire({ seed: 42 });
  for (let i = 0; i < 30; i++) { a.step(); b.step(); }
  assert.deepStrictEqual(a.heat, b.heat, 'heat identical');
  assert.deepStrictEqual(a.sparks, b.sparks, 'sparks identical');
});

test('different seeds produce different fields', () => {
  const a = createFire({ seed: 1 });
  const b = createFire({ seed: 2 });
  for (let i = 0; i < 30; i++) { a.step(); b.step(); }
  assert.notDeepStrictEqual(a.heat, b.heat);
});

// --- palette ------------------------------------------------------------------

test('colorIndex: 0 -> null, mid ~orange 202, hot core white 231, monotone', () => {
  assert.strictEqual(colorIndex(0), null);
  assert.strictEqual(colorIndex(0.5), 202);
  assert.strictEqual(colorIndex(0.99), 231);
  assert.ok(colorIndex(0.3) < colorIndex(0.6), 'hotter -> brighter index');
  assert.ok(colorIndex(0.6) < colorIndex(0.95), 'hotter -> brighter index');
});

// --- sparks -------------------------------------------------------------------

test('sparks: fields present, rise (vy<0), life always in (0,1] over long run (respawn works)', () => {
  const f = createFire({ seed: 5 });
  for (let i = 0; i < 200; i++) {
    f.step();
    for (const s of f.sparks) {
      assert.ok(s.life > 0 && s.life <= 1, 'life in (0,1]: ' + s.life);
      assert.ok(s.y >= 0 && s.y < f.H, 'spark kept on screen (resumed at base)');
      assert.ok(s.x >= 0 && s.x < f.W, 'spark x in bounds');
      assert.ok(s.vy < 0, 'spark rises');
    }
  }
});

// --- render -------------------------------------------------------------------

test('render: pure frame string — cursor home, 256-color codes, H rows, spark pixel', () => {
  const f = createFire({ seed: 3 });
  for (let i = 0; i < 5; i++) f.step();
  const out = render(f);
  assert.strictEqual(typeof out, 'string');
  assert.ok(out.startsWith('\u001b[H'), 'cursor to home first');
  assert.match(out, /\u001b\[38;5;\d+m/, '256-color codes present');
  assert.strictEqual(out.split('\n').length, f.H + 1, 'H visual rows + tail line');
  assert.ok(out.includes('\u2726'), 'spark pixel drawn');
  assert.ok(out.endsWith('\u001b[J'), 'tail cleared');
});

test('render with custom width clamps columns and stays a string', () => {
  const f = createFire({ W: 80, H: 10, seed: 3 });
  f.step();
  let out;
  assert.doesNotThrow(() => { out = render(f, 40); });
  assert.strictEqual(typeof out, 'string');
  assert.strictEqual(out.split('\n').length, 11, '10 rows + tail line');
});

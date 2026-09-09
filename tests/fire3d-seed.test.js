'use strict';

// Ticket CC-048: fire3d — флаг --seed N (воспроизводимый прогон)
// + общий PRNG из src/rng.js вместо встроенного в fire3d.js.

const { test } = require('node:test');
const assert = require('node:assert');

const { parseSeed, renderStatic } = require('../src/fire3d/main.js');
const { create } = require('../src/fire3d/fire3d.js');
const { mulberry32 } = require('../src/rng.js');

// C4.1 — --seed 42 → 42
test('parseSeed: --seed 42 → 42', () => {
  assert.strictEqual(parseSeed(['node', 'fire3d', '--seed', '42']), 42);
});

// C4.2 — флаг отсутствует → undefined
test('parseSeed: без флага → undefined', () => {
  assert.strictEqual(parseSeed(['node', 'fire3d']), undefined);
});

// C4.3 — --seed 0 → 0
test('parseSeed: --seed 0 → 0', () => {
  assert.strictEqual(parseSeed(['node', 'fire3d', '--seed', '0']), 0);
});

// C4.4 — --seed без значения → RangeError
test('parseSeed: --seed без значения → RangeError', () => {
  assert.throws(() => parseSeed(['node', 'fire3d', '--seed']), RangeError);
});

// C4.5 — нечисловое значение → RangeError
test('parseSeed: --seed abc → RangeError', () => {
  assert.throws(() => parseSeed(['node', 'fire3d', '--seed', 'abc']), RangeError);
});

// C4.6 — отрицательное значение → RangeError
test('parseSeed: --seed -5 → RangeError', () => {
  assert.throws(() => parseSeed(['node', 'fire3d', '--seed', '-5']), RangeError);
});

// C4.7 — нецелое значение → RangeError
test('parseSeed: --seed 1.5 → RangeError', () => {
  assert.throws(() => parseSeed(['node', 'fire3d', '--seed', '1.5']), RangeError);
});

// C4.8 — детерминизм: одинаковый seed → идентичный heat после 100 step
test('create({ seed: 42 }) детерминирован после 100 step', () => {
  const a = create({ W: 12, H: 8, D: 12, seed: 42 });
  const b = create({ W: 12, H: 8, D: 12, seed: 42 });
  for (let i = 0; i < 100; i++) { a.step(); b.step(); }
  for (let i = 0; i < a.heat.length; i++) {
    assert.strictEqual(a.heat[i], b.heat[i], 'heat[' + i + '] differs');
  }
});

// C4.9 — разные seed → разный heat после 50 step
test('create({ seed: 42 }) и create({ seed: 43 }) дают разный heat', () => {
  const a = create({ W: 12, H: 8, D: 12, seed: 42 });
  const b = create({ W: 12, H: 8, D: 12, seed: 43 });
  for (let i = 0; i < 50; i++) { a.step(); b.step(); }
  let diff = false;
  for (let i = 0; i < a.heat.length; i++) {
    if (a.heat[i] !== b.heat[i]) { diff = true; break; }
  }
  assert.ok(diff, 'heat must differ for different seeds');
});

// C4.10 — PRNG из create({ seed }) идентичен mulberry32(seed) из src/rng.js
test('create({ seed: 42 }).rng совпадает с mulberry32(42) из src/rng.js', () => {
  const f = create({ W: 12, H: 8, D: 12, seed: 42 });
  const g = mulberry32(42);
  for (let i = 0; i < 100; i++) {
    assert.strictEqual(f.rng(), g(), 'value #' + i + ' differs');
  }
});

// C4.11 — renderStatic детерминирован по seed (фейковый stdout)
test('renderStatic с тем же seed выдаёт идентичный вывод', () => {
  let out1 = '';
  let out2 = '';
  const fake1 = { columns: 60, write: (s) => { out1 += s; } };
  const fake2 = { columns: 60, write: (s) => { out2 += s; } };
  renderStatic(fake1, 5, { seed: 7 });
  renderStatic(fake2, 5, { seed: 7 });
  assert.strictEqual(out1, out2);
  assert.ok(out1.length > 0, 'output must not be empty');
});

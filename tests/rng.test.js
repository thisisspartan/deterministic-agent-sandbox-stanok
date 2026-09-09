'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const { mulberry32, randInt, pick, shuffle } = require('../src/rng.js');

test('C5.1: mulberry32(seed) returns a function', () => {
  const r = mulberry32(1);
  assert.strictEqual(typeof r, 'function');
});

test('C5.2: determinism — same seed gives identical sequences', () => {
  const a = mulberry32(12345);
  const b = mulberry32(12345);
  for (let i = 0; i < 100; i++) {
    assert.strictEqual(a(), b());
  }
});

test('C5.3: 10000 calls of mulberry32(1) all in [0, 1)', () => {
  const r = mulberry32(1);
  for (let i = 0; i < 10000; i++) {
    const x = r();
    assert.ok(Number.isFinite(x), 'value must be finite: ' + x);
    assert.ok(x >= 0 && x < 1, 'value out of range: ' + x);
  }
});

test('C5.4: spread — not a constant: min < 0.05 and max > 0.95', () => {
  const r = mulberry32(1);
  let min = Infinity, max = -Infinity;
  for (let i = 0; i < 10000; i++) {
    const x = r();
    if (x < min) min = x;
    if (x > max) max = x;
  }
  assert.ok(min < 0.05, 'min too high: ' + min);
  assert.ok(max > 0.95, 'max too low: ' + max);
});

test('C5.5: different seeds give different sequences', () => {
  const a = mulberry32(1);
  const b = mulberry32(2);
  let same = true;
  for (let i = 0; i < 100; i++) {
    if (a() !== b()) { same = false; break; }
  }
  assert.ok(!same, 'sequences for seeds 1 and 2 must differ');
});

test('C5.6: randInt(rng, 1, 6) — 1000 calls all integers in [1,6], >=4 distinct', () => {
  const rng = mulberry32(42);
  const seen = new Set();
  for (let i = 0; i < 1000; i++) {
    const x = randInt(rng, 1, 6);
    assert.ok(Number.isInteger(x), 'not an integer: ' + x);
    assert.ok(x >= 1 && x <= 6, 'out of range: ' + x);
    seen.add(x);
  }
  assert.ok(seen.size >= 4, 'too few distinct values: ' + seen.size);
});

test('C5.7: randInt(rng, 5, 5) is always 5', () => {
  const rng = mulberry32(0);
  for (let i = 0; i < 100; i++) {
    assert.strictEqual(randInt(rng, 5, 5), 5);
  }
});

test('C5.8: randInt(rng, 3, 1) throws RangeError', () => {
  const rng = mulberry32(0);
  assert.throws(() => randInt(rng, 3, 1), RangeError);
});

test('C5.9: pick(rng, [\'a\',\'b\',\'c\']) — 1000 calls all from array, >=2 distinct', () => {
  const rng = mulberry32(7);
  const arr = ['a', 'b', 'c'];
  const seen = new Set();
  for (let i = 0; i < 1000; i++) {
    const x = pick(rng, arr);
    assert.ok(arr.includes(x), 'unexpected value: ' + x);
    seen.add(x);
  }
  assert.ok(seen.size >= 2, 'too few distinct picks: ' + seen.size);
});

test('C5.10: pick(rng, []) throws RangeError', () => {
  const rng = mulberry32(0);
  assert.throws(() => pick(rng, []), RangeError);
});

test('C5.11: shuffle — same ref, permutation, deterministic', () => {
  const rng = mulberry32(99);
  const a = [1, 2, 3, 4, 5];
  const out = shuffle(rng, a);
  assert.strictEqual(out, a, 'shuffle must return the same array reference');
  assert.deepStrictEqual([...a].sort((x, y) => x - y), [1, 2, 3, 4, 5]);

  const r1 = mulberry32(99);
  const r2 = mulberry32(99);
  const b = [1, 2, 3, 4, 5];
  const c = [1, 2, 3, 4, 5];
  shuffle(r1, b);
  shuffle(r2, c);
  assert.deepStrictEqual(b, c, 'same seed must give same permutation');
});

test('C5.12: shuffle on [] and [7] keeps content/order', () => {
  const rng = mulberry32(1);
  assert.deepStrictEqual(shuffle(rng, []), []);
  assert.deepStrictEqual(shuffle(rng, [7]), [7]);
});

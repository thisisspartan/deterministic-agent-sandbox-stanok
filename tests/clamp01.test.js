'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { clamp, lerp, invLerp } = require('../src/clamp01.js');

// --- clamp ---

test('clamp(5, 0, 10) -> 5 (in range)', () => {
  assert.strictEqual(clamp(5, 0, 10), 5);
});

test('clamp(-1, 0, 10) -> 0 (below min)', () => {
  assert.strictEqual(clamp(-1, 0, 10), 0);
});

test('clamp(11, 0, 10) -> 10 (above max)', () => {
  assert.strictEqual(clamp(11, 0, 10), 10);
});

test('clamp boundaries returned unchanged', () => {
  assert.strictEqual(clamp(0, 0, 10), 0);
  assert.strictEqual(clamp(10, 0, 10), 10);
});

test('clamp works with negative range', () => {
  assert.strictEqual(clamp(-5, -10, -1), -5);
  assert.strictEqual(clamp(-20, -10, -1), -10);
  assert.strictEqual(clamp(1, -10, -1), -1);
});

test('clamp throws RangeError "lo > hi" when lo > hi', () => {
  assert.throws(() => clamp(5, 10, 0), (e) =>
    e instanceof RangeError && e.message === 'lo > hi'
  );
});

test('clamp throws TypeError when v is not a number ("v" in message)', () => {
  assert.throws(() => clamp('5', 0, 10), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('clamp throws TypeError when v is NaN ("v" in message)', () => {
  assert.throws(() => clamp(NaN, 0, 10), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('clamp throws TypeError when v is Infinity ("v" in message)', () => {
  assert.throws(() => clamp(Infinity, 0, 10), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('clamp throws TypeError when lo is not a number ("lo" in message)', () => {
  assert.throws(() => clamp(5, '0', 10), (e) => e instanceof TypeError && /lo/.test(e.message));
});

test('clamp throws TypeError when lo is NaN ("lo" in message)', () => {
  assert.throws(() => clamp(5, NaN, 10), (e) => e instanceof TypeError && /lo/.test(e.message));
});

test('clamp throws TypeError when lo is Infinity ("lo" in message)', () => {
  assert.throws(() => clamp(5, Infinity, 10), (e) => e instanceof TypeError && /lo/.test(e.message));
});

test('clamp throws TypeError when hi is not a number ("hi" in message)', () => {
  assert.throws(() => clamp(5, 0, '10'), (e) => e instanceof TypeError && /hi/.test(e.message));
});

test('clamp throws TypeError when hi is NaN ("hi" in message)', () => {
  assert.throws(() => clamp(5, 0, NaN), (e) => e instanceof TypeError && /hi/.test(e.message));
});

test('clamp throws TypeError when hi is Infinity ("hi" in message)', () => {
  assert.throws(() => clamp(5, 0, Infinity), (e) => e instanceof TypeError && /hi/.test(e.message));
});

// --- lerp ---

test('lerp(0, 10, 0.5) -> 5', () => {
  assert.strictEqual(lerp(0, 10, 0.5), 5);
});

test('lerp(10, 0, 0.5) -> 5', () => {
  assert.strictEqual(lerp(10, 0, 0.5), 5);
});

test('lerp(0, 10, 0) -> 0', () => {
  assert.strictEqual(lerp(0, 10, 0), 0);
});

test('lerp(0, 10, 1) -> 10', () => {
  assert.strictEqual(lerp(0, 10, 1), 10);
});

test('lerp extrapolates when t is out of [0, 1]', () => {
  assert.strictEqual(lerp(0, 10, 2), 20);
  assert.strictEqual(lerp(0, 10, -1), -10);
});

test('lerp throws TypeError when a is not a number ("a" in message)', () => {
  assert.throws(() => lerp('0', 10, 0.5), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('lerp throws TypeError when a is NaN ("a" in message)', () => {
  assert.throws(() => lerp(NaN, 10, 0.5), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('lerp throws TypeError when a is Infinity ("a" in message)', () => {
  assert.throws(() => lerp(Infinity, 10, 0.5), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('lerp throws TypeError when b is not a number ("b" in message)', () => {
  assert.throws(() => lerp(0, '10', 0.5), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('lerp throws TypeError when b is NaN ("b" in message)', () => {
  assert.throws(() => lerp(0, NaN, 0.5), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('lerp throws TypeError when b is Infinity ("b" in message)', () => {
  assert.throws(() => lerp(0, Infinity, 0.5), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('lerp throws TypeError when t is not a number ("t" in message)', () => {
  assert.throws(() => lerp(0, 10, '0.5'), (e) => e instanceof TypeError && /t/.test(e.message));
});

test('lerp throws TypeError when t is NaN ("t" in message)', () => {
  assert.throws(() => lerp(0, 10, NaN), (e) => e instanceof TypeError && /t/.test(e.message));
});

test('lerp throws TypeError when t is Infinity ("t" in message)', () => {
  assert.throws(() => lerp(0, 10, Infinity), (e) => e instanceof TypeError && /t/.test(e.message));
});

// --- invLerp ---

test('invLerp(0, 10, 5) -> 0.5', () => {
  assert.strictEqual(invLerp(0, 10, 5), 0.5);
});

test('invLerp(0, 10, 0) -> 0', () => {
  assert.strictEqual(invLerp(0, 10, 0), 0);
});

test('invLerp(0, 10, 10) -> 1', () => {
  assert.strictEqual(invLerp(0, 10, 10), 1);
});

test('invLerp allows extrapolation outside [a, b]', () => {
  assert.strictEqual(invLerp(0, 10, 20), 2);
  assert.strictEqual(invLerp(0, 10, -5), -0.5);
});

test('invLerp throws RangeError "a === b" when a === b', () => {
  assert.throws(() => invLerp(5, 5, 5), (e) =>
    e instanceof RangeError && e.message === 'a === b'
  );
});

test('invLerp throws TypeError when a is not a number ("a" in message)', () => {
  assert.throws(() => invLerp('0', 10, 5), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('invLerp throws TypeError when a is NaN ("a" in message)', () => {
  assert.throws(() => invLerp(NaN, 10, 5), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('invLerp throws TypeError when a is Infinity ("a" in message)', () => {
  assert.throws(() => invLerp(Infinity, 10, 5), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('invLerp throws TypeError when b is not a number ("b" in message)', () => {
  assert.throws(() => invLerp(0, '10', 5), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('invLerp throws TypeError when b is NaN ("b" in message)', () => {
  assert.throws(() => invLerp(0, NaN, 5), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('invLerp throws TypeError when b is Infinity ("b" in message)', () => {
  assert.throws(() => invLerp(0, Infinity, 5), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('invLerp throws TypeError when v is not a number ("v" in message)', () => {
  assert.throws(() => invLerp(0, 10, '5'), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('invLerp throws TypeError when v is NaN ("v" in message)', () => {
  assert.throws(() => invLerp(0, 10, NaN), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('invLerp throws TypeError when v is Infinity ("v" in message)', () => {
  assert.throws(() => invLerp(0, 10, Infinity), (e) => e instanceof TypeError && /v/.test(e.message));
});

// --- invariant: lerp(a, b, invLerp(a, b, v)) === v ---

test('lerp(a, b, invLerp(a, b, v)) === v for v in range', () => {
  for (const v of [0, 2.5, 5, 7.75, 10]) {
    assert.strictEqual(lerp(0, 10, invLerp(0, 10, v)), v);
  }
  for (const v of [-8, -3, 4, 9.5]) {
    assert.strictEqual(lerp(-10, 5, invLerp(-10, 5, v)), v);
  }
});

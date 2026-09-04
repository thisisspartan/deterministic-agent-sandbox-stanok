'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { clamp, lerp, invLerp } = require('../src/lerp.js');

// --- clamp ---

test('clamp(5, 0, 1) -> 1', () => {
  assert.strictEqual(clamp(5, 0, 1), 1);
});

test('clamp(-1, 0, 1) -> 0', () => {
  assert.strictEqual(clamp(-1, 0, 1), 0);
});

test('clamp(0.5, 0, 1) -> 0.5', () => {
  assert.strictEqual(clamp(0.5, 0, 1), 0.5);
});

test('clamp boundary: lo and hi returned unchanged', () => {
  assert.strictEqual(clamp(0, 0, 1), 0);
  assert.strictEqual(clamp(1, 0, 1), 1);
});

test('clamp throws RangeError "lo > hi" when lo > hi', () => {
  assert.throws(() => clamp(0.5, 1, 0), (e) =>
    e instanceof RangeError && e.message === 'lo > hi'
  );
});

test('clamp throws TypeError when v is not a number ("v" in message)', () => {
  assert.throws(() => clamp('0.5', 0, 1), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('clamp throws TypeError when v is NaN ("v" in message)', () => {
  assert.throws(() => clamp(NaN, 0, 1), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('clamp throws TypeError when lo is not a number ("lo" in message)', () => {
  assert.throws(() => clamp(0.5, '0', 1), (e) => e instanceof TypeError && /lo/.test(e.message));
});

test('clamp throws TypeError when lo is NaN ("lo" in message)', () => {
  assert.throws(() => clamp(0.5, NaN, 1), (e) => e instanceof TypeError && /lo/.test(e.message));
});

test('clamp throws TypeError when hi is not a number ("hi" in message)', () => {
  assert.throws(() => clamp(0.5, 0, '1'), (e) => e instanceof TypeError && /hi/.test(e.message));
});

test('clamp throws TypeError when hi is NaN ("hi" in message)', () => {
  assert.throws(() => clamp(0.5, 0, NaN), (e) => e instanceof TypeError && /hi/.test(e.message));
});

// --- lerp ---

test('lerp(0, 10, 0.5) -> 5', () => {
  assert.strictEqual(lerp(0, 10, 0.5), 5);
});

test('lerp(10, 0, 0.5) -> 5', () => {
  assert.strictEqual(lerp(10, 0, 0.5), 5);
});

test('lerp endpoints: t=0 -> a, t=1 -> b', () => {
  assert.strictEqual(lerp(0, 10, 0), 0);
  assert.strictEqual(lerp(0, 10, 1), 10);
});

test('lerp extrapolates when t outside [0, 1] (not an error)', () => {
  assert.strictEqual(lerp(0, 10, -0.5), -5);
  assert.strictEqual(lerp(0, 10, 1.5), 15);
});

test('lerp throws TypeError when a is not a number ("a" in message)', () => {
  assert.throws(() => lerp('0', 10, 0.5), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('lerp throws TypeError when a is NaN ("a" in message)', () => {
  assert.throws(() => lerp(NaN, 10, 0.5), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('lerp throws TypeError when b is not a number ("b" in message)', () => {
  assert.throws(() => lerp(0, '10', 0.5), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('lerp throws TypeError when b is NaN ("b" in message)', () => {
  assert.throws(() => lerp(0, NaN, 0.5), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('lerp throws TypeError when t is not a number ("t" in message)', () => {
  assert.throws(() => lerp(0, 10, '0.5'), (e) => e instanceof TypeError && /t/.test(e.message));
});

test('lerp throws TypeError when t is NaN ("t" in message)', () => {
  assert.throws(() => lerp(0, 10, NaN), (e) => e instanceof TypeError && /t/.test(e.message));
});

// --- invLerp ---

test('invLerp(0, 10, 5) -> 0.5', () => {
  assert.strictEqual(invLerp(0, 10, 5), 0.5);
});

test('invLerp(0, 10, 10) -> 1', () => {
  assert.strictEqual(invLerp(0, 10, 10), 1);
});

test('invLerp(0, 10, 0) -> 0', () => {
  assert.strictEqual(invLerp(0, 10, 0), 0);
});

test('invLerp extrapolates when v outside [a, b] (not an error)', () => {
  assert.strictEqual(invLerp(0, 10, -5), -0.5);
  assert.strictEqual(invLerp(0, 10, 15), 1.5);
});

test('invLerp throws RangeError "a === b" when a === b', () => {
  assert.throws(() => invLerp(5, 5, 3), (e) =>
    e instanceof RangeError && e.message === 'a === b'
  );
});

test('invLerp throws TypeError when a is not a number ("a" in message)', () => {
  assert.throws(() => invLerp('0', 10, 5), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('invLerp throws TypeError when a is NaN ("a" in message)', () => {
  assert.throws(() => invLerp(NaN, 10, 5), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('invLerp throws TypeError when b is not a number ("b" in message)', () => {
  assert.throws(() => invLerp(0, '10', 5), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('invLerp throws TypeError when b is NaN ("b" in message)', () => {
  assert.throws(() => invLerp(0, NaN, 5), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('invLerp throws TypeError when v is not a number ("v" in message)', () => {
  assert.throws(() => invLerp(0, 10, '5'), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('invLerp throws TypeError when v is NaN ("v" in message)', () => {
  assert.throws(() => invLerp(0, 10, NaN), (e) => e instanceof TypeError && /v/.test(e.message));
});

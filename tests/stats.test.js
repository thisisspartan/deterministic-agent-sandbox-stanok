'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { sum, mean, median, variance } = require('../src/stats.js');

const EPS = 1e-9;

function close(a, b) {
  return Math.abs(a - b) < EPS;
}

// --- sum ---

test('sum([1,2,3]) -> 6', () => {
  assert.strictEqual(sum([1, 2, 3]), 6);
});

test('sum([]) -> 0', () => {
  assert.strictEqual(sum([]), 0);
});

test('sum([5]) -> 5 (single element)', () => {
  assert.strictEqual(sum([5]), 5);
});

test('sum handles negatives and floats', () => {
  assert.strictEqual(sum([-1, 2.5, -1.5]), 0);
});

test('sum does not mutate input', () => {
  const a = [1, 2, 3];
  sum(a);
  assert.deepStrictEqual(a, [1, 2, 3]);
});

test('sum throws TypeError for non-array ("a" in message)', () => {
  assert.throws(() => sum({ 0: 1, length: 1 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
  assert.throws(() => sum(42), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('sum throws TypeError for non-number element with index in message', () => {
  assert.throws(() => sum([1, 2, 'x', 4]), (e) =>
    e instanceof TypeError && /a\[2\]/.test(e.message)
  );
  assert.throws(() => sum([1, NaN]), (e) =>
    e instanceof TypeError && /a\[1\]/.test(e.message)
  );
  assert.throws(() => sum([1, Infinity]), (e) =>
    e instanceof TypeError && /a\[1\]/.test(e.message)
  );
});

// --- mean ---

test('mean([1,2,3,4]) -> 2.5', () => {
  assert.ok(close(mean([1, 2, 3, 4]), 2.5));
});

test('mean of single element is the element', () => {
  assert.ok(close(mean([7]), 7));
});

test('mean throws RangeError "empty array" on empty array', () => {
  assert.throws(() => mean([]), (e) =>
    e instanceof RangeError && e.message === 'empty array'
  );
});

test('mean throws TypeError for non-array ("a" in message)', () => {
  assert.throws(() => mean(null), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('mean throws TypeError for non-number element with index in message', () => {
  assert.throws(() => mean([1, 'x', 3]), (e) =>
    e instanceof TypeError && /a\[1\]/.test(e.message)
  );
});

// --- median ---

test('median([3,1,2]) -> 2 (odd length)', () => {
  assert.strictEqual(median([3, 1, 2]), 2);
});

test('median([4,1,3,2]) -> 2.5 (even length)', () => {
  assert.ok(close(median([4, 1, 3, 2]), 2.5));
});

test('median of single element is the element', () => {
  assert.strictEqual(median([42]), 42);
});

test('median throws RangeError "empty array" on empty array', () => {
  assert.throws(() => median([]), (e) =>
    e instanceof RangeError && e.message === 'empty array'
  );
});

test('median does not mutate input array', () => {
  const a = [3, 1, 2];
  median(a);
  assert.deepStrictEqual(a, [3, 1, 2]);
});

test('median throws TypeError for non-array ("a" in message)', () => {
  assert.throws(() => median('12'), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('median throws TypeError for non-number element with index in message', () => {
  assert.throws(() => median([1, null, 3]), (e) =>
    e instanceof TypeError && /a\[1\]/.test(e.message)
  );
  assert.throws(() => median([1, -Infinity]), (e) =>
    e instanceof TypeError && /a\[1\]/.test(e.message)
  );
});

// --- variance ---

test('variance([2,4,4,4,5,5,7,9]) -> 4 (population)', () => {
  assert.ok(close(variance([2, 4, 4, 4, 5, 5, 7, 9]), 4));
});

test('variance of constant array is 0', () => {
  assert.ok(close(variance([3, 3, 3]), 0));
});

test('variance([2,4]) -> 1 (two-element case)', () => {
  // mean = 3; (1^2 + 1^2) / 2 = 1
  assert.ok(close(variance([2, 4]), 1));
});

test('variance throws RangeError "need >= 2" for empty array', () => {
  assert.throws(() => variance([]), (e) =>
    e instanceof RangeError && e.message === 'need >= 2'
  );
});

test('variance throws RangeError "need >= 2" for single element', () => {
  assert.throws(() => variance([1]), (e) =>
    e instanceof RangeError && e.message === 'need >= 2'
  );
});

test('variance throws TypeError for non-array ("a" in message)', () => {
  assert.throws(() => variance(undefined), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('variance throws TypeError for non-number element with index in message', () => {
  assert.throws(() => variance([1, 2, NaN, 4]), (e) =>
    e instanceof TypeError && /a\[2\]/.test(e.message)
  );
});

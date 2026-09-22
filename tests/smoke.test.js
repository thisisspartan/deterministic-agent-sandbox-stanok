// tests/smoke.test.js — harness smoke for src/smoke.js (node:test stack).
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { add } = require('../src/smoke.js');

test('add(2, 3) === 5', () => {
  assert.strictEqual(add(2, 3), 5);
});

test('add(-1, 1) === 0', () => {
  assert.strictEqual(add(-1, 1), 0);
});

test('add(0, 0) === 0', () => {
  assert.strictEqual(add(0, 0), 0);
});

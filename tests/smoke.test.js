'use strict';
// Reference tests for src/smoke.js (TASK-STANOK-SMOKE-01).
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { add } = require('../src/smoke.js');

test('add sums two numbers: add(2, 3) === 5', () => {
  assert.strictEqual(add(2, 3), 5);
});

test('add handles negatives: add(-1, 1) === 0', () => {
  assert.strictEqual(add(-1, 1), 0);
});

test('add of zeros: add(0, 0) === 0', () => {
  assert.strictEqual(add(0, 0), 0);
});

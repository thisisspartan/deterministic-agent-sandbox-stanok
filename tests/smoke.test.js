'use strict';
// Reference tests for src/smoke.js (TASK-STANOK-SMOKE-01).
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { add } = require('../src/smoke.js');

test('add sums two numbers', () => {
  assert.strictEqual(add(2, 3), 5);
});

test('add handles negative values', () => {
  assert.strictEqual(add(-1, 1), 0);
});

test('add handles zero', () => {
  assert.strictEqual(add(0, 0), 0);
});

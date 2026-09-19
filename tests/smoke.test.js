'use strict';
// Reference tests for src/smoke.js (TASK-STANOK-SMOKE-01).
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { add } = require('../src/smoke.js');

test('add returns the numeric sum', () => {
  assert.strictEqual(add(2, 3), 5);
  assert.strictEqual(add(-1, 1), 0);
  assert.strictEqual(add(0, 0), 0);
});

test('add works with floating point and negative operands', () => {
  assert.strictEqual(add(-2.5, 1.5), -1);
  assert.strictEqual(add(-4, -4), -8);
});

test('add returns a number', () => {
  assert.strictEqual(typeof add(1, 2), 'number');
});

'use strict';
// Reference tests for src/smoke.js (TASK-STANOK-SMOKE-01).
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { add } = require('../src/smoke.js');

test('add(2, 3) === 5', () => {
  assert.equal(add(2, 3), 5);
});

test('add(-1, 1) === 0', () => {
  assert.equal(add(-1, 1), 0);
});

test('add(0, 0) === 0', () => {
  assert.equal(add(0, 0), 0);
});

test('add returns the numeric sum for floats and negatives', () => {
  assert.equal(add(0.1, 0.2), 0.1 + 0.2);
  assert.equal(add(-4, -6), -10);
});

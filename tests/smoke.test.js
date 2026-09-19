'use strict';
// Reference tests for src/smoke.js (TASK-STANOK-SMOKE-01).
const { test } = require('node:test');
const assert = require('node:assert/strict');

const smoke = require('../src/smoke.js');

test('add(2, 3) === 5', () => {
  assert.strictEqual(smoke.add(2, 3), 5);
});

test('add(-1, 1) === 0', () => {
  assert.strictEqual(smoke.add(-1, 1), 0);
});

test('add(0, 0) === 0', () => {
  assert.strictEqual(smoke.add(0, 0), 0);
});

test('add returns a number', () => {
  assert.strictEqual(typeof smoke.add(1, 2), 'number');
});

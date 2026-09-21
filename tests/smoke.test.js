'use strict';
// Test contract for src/smoke.js (see docs/smoke.md).
const test = require('node:test');
const assert = require('node:assert/strict');

const { add } = require('../src/smoke.js');

test('add: numeric sums', () => {
  assert.equal(add(2, 3), 5);
  assert.equal(add(-1, 1), 0);
  assert.equal(add(0, 0), 0);
});

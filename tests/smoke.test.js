'use strict';

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

test('add returns a number', () => {
  assert.equal(typeof add(1, 2), 'number');
});

test('add works with floats', () => {
  assert.equal(add(0.1, 0.2), 0.1 + 0.2);
});

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

test('add returns a number and is commutative', () => {
  assert.equal(typeof add(1, 2), 'number');
  assert.equal(add(3, 7), add(7, 3));
});

test('add supports non-integer operands', () => {
  assert.equal(add(0.5, 0.25), 0.75);
});

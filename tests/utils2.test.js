'use strict';

const test = require('node:test');
const assert = require('node:assert');

// Реализация появится в src/utils2.js (см. TASK-STANOK-CC-010).
// require ниже выполняется в ленивой инициализации node:test, поэтому
// модуль должен существовать к моменту запуска тестов.
let formatPosPrefixed;
try {
  ({ formatPosPrefixed } = require('../src/utils2.js'));
} catch {
  formatPosPrefixed = undefined;
}

test('base case: formatPosPrefixed("pos ", 1, 2) -> "pos x=1 y=2"', () => {
  assert.strictEqual(formatPosPrefixed('pos ', 1, 2), 'pos x=1 y=2');
});

test('negative coordinates: formatPosPrefixed("p", -1.005, -0.001) -> "px=-1.01 y=-0.01"', () => {
  assert.strictEqual(formatPosPrefixed('p', -1.005, -0.001), 'px=-1.01 y=-0.01');
});

test('TypeError when prefix is not a string', () => {
  assert.throws(() => formatPosPrefixed(123, 1, 2), TypeError);
});

test('TypeError when x is NaN', () => {
  assert.throws(() => formatPosPrefixed('p', NaN, 2), TypeError);
});

test("TypeError when y is not a number ('2')", () => {
  assert.throws(() => formatPosPrefixed('p', 1, '2'), TypeError);
});

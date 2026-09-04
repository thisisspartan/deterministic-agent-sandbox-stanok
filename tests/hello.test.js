const { test } = require('node:test');
const assert = require('node:assert/strict');

const { greet } = require('../src/hello.js');

test('C2.1: greet("World") returns "Hello, World!"', () => {
  assert.equal(greet('World'), 'Hello, World!');
});

test('C2.2: greet("Алиса") returns "Hello, Алиса!"', () => {
  assert.equal(greet('Алиса'), 'Hello, Алиса!');
});

test('C2.3: greet("") throws TypeError', () => {
  assert.throws(() => greet(''), TypeError);
});

test('C2.4: greet(42) throws TypeError', () => {
  assert.throws(() => greet(42), TypeError);
});

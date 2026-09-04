'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { length, normalize, add } = require('../src/vec2.js');

// --- length ---

test('length(3, 4) -> 5', () => {
  assert.strictEqual(length(3, 4), 5);
});

test('length(0, 0) -> 0', () => {
  assert.strictEqual(length(0, 0), 0);
});

test('length(-3, -4) -> 5 (negative components)', () => {
  assert.strictEqual(length(-3, -4), 5);
});

test('length throws TypeError when x is not a number ("x" in message)', () => {
  assert.throws(() => length('3', 4), (e) => e instanceof TypeError && /x/.test(e.message));
});

test('length throws TypeError when x is NaN ("x" in message)', () => {
  assert.throws(() => length(NaN, 4), (e) => e instanceof TypeError && /x/.test(e.message));
});

test('length throws TypeError when y is not a number ("y" in message)', () => {
  assert.throws(() => length(3, '4'), (e) => e instanceof TypeError && /y/.test(e.message));
});

test('length throws TypeError when y is NaN ("y" in message)', () => {
  assert.throws(() => length(3, NaN), (e) => e instanceof TypeError && /y/.test(e.message));
});

// --- normalize ---

test('normalize(3, 4) -> { x: 0.6, y: 0.8 }', () => {
  assert.deepStrictEqual(normalize(3, 4), { x: 0.6, y: 0.8 });
});

test('normalize(0, 0) throws Error "normalize: zero vector"', () => {
  assert.throws(() => normalize(0, 0), (e) =>
    e instanceof Error && e.message === 'normalize: zero vector'
  );
});

test('normalize throws TypeError when x is not a number ("x" in message)', () => {
  assert.throws(() => normalize('3', 4), (e) => e instanceof TypeError && /x/.test(e.message));
});

test('normalize throws TypeError when x is NaN ("x" in message)', () => {
  assert.throws(() => normalize(NaN, 4), (e) => e instanceof TypeError && /x/.test(e.message));
});

test('normalize throws TypeError when y is not a number ("y" in message)', () => {
  assert.throws(() => normalize(3, '4'), (e) => e instanceof TypeError && /y/.test(e.message));
});

test('normalize throws TypeError when y is NaN ("y" in message)', () => {
  assert.throws(() => normalize(3, NaN), (e) => e instanceof TypeError && /y/.test(e.message));
});

// --- add ---

test('add({x:1,y:2}, {x:3,y:4}) -> {x:4,y:6}', () => {
  assert.deepStrictEqual(add({ x: 1, y: 2 }, { x: 3, y: 4 }), { x: 4, y: 6 });
});

test('add handles negative components', () => {
  assert.deepStrictEqual(add({ x: -1, y: 2 }, { x: 1, y: -2 }), { x: 0, y: 0 });
});

test('add does not mutate arguments (pure)', () => {
  const a = { x: 1, y: 2 };
  const b = { x: 3, y: 4 };
  add(a, b);
  assert.deepStrictEqual(a, { x: 1, y: 2 });
  assert.deepStrictEqual(b, { x: 3, y: 4 });
});

test('add throws TypeError when a is not an object ("a" in message)', () => {
  assert.throws(() => add(null, { x: 1, y: 2 }), (e) => e instanceof TypeError && /a/.test(e.message));
  assert.throws(() => add(5, { x: 1, y: 2 }), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('add throws TypeError when a.x is NaN ("a" in message)', () => {
  assert.throws(() => add({ x: NaN, y: 1 }, { x: 1, y: 2 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('add throws TypeError when a.y is not a number ("a" in message)', () => {
  assert.throws(() => add({ x: 1, y: '2' }, { x: 1, y: 2 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('add throws TypeError when b is not an object ("b" in message)', () => {
  assert.throws(() => add({ x: 1, y: 2 }, null), (e) => e instanceof TypeError && /b/.test(e.message));
  assert.throws(() => add({ x: 1, y: 2 }, undefined), (e) =>
    e instanceof TypeError && /b/.test(e.message)
  );
});

test('add throws TypeError when b.y is NaN ("b" in message)', () => {
  assert.throws(() => add({ x: 1, y: 2 }, { x: 1, y: NaN }), (e) =>
    e instanceof TypeError && /b/.test(e.message)
  );
});

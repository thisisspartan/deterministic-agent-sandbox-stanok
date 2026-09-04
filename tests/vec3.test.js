'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { add, sub, scale, dot, cross, length, normalize } = require('../src/vec3.js');

// --- add ---

test('add({x:1,y:2,z:3}, {x:4,y:5,z:6}) -> {x:5, y:7, z:9}', () => {
  assert.deepStrictEqual(add({ x: 1, y: 2, z: 3 }, { x: 4, y: 5, z: 6 }), { x: 5, y: 7, z: 9 });
});

test('add handles negative components', () => {
  assert.deepStrictEqual(add({ x: -1, y: 2, z: -3 }, { x: 1, y: -2, z: 3 }), { x: 0, y: 0, z: 0 });
});

test('add does not mutate arguments (pure)', () => {
  const a = { x: 1, y: 2, z: 3 };
  const b = { x: 4, y: 5, z: 6 };
  add(a, b);
  assert.deepStrictEqual(a, { x: 1, y: 2, z: 3 });
  assert.deepStrictEqual(b, { x: 4, y: 5, z: 6 });
});

test('add throws TypeError when a is not an object ("a" in message)', () => {
  assert.throws(() => add(null, { x: 1, y: 2, z: 3 }), (e) => e instanceof TypeError && /a/.test(e.message));
  assert.throws(() => add(5, { x: 1, y: 2, z: 3 }), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('add throws TypeError when a.x is not a number ("a" in message)', () => {
  assert.throws(() => add({ x: '1', y: 2, z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('add throws TypeError when a.y is NaN ("a" in message)', () => {
  assert.throws(() => add({ x: 1, y: NaN, z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('add throws TypeError when a.z is not a number ("a" in message)', () => {
  assert.throws(() => add({ x: 1, y: 2, z: null }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('add throws TypeError when b is not an object ("b" in message)', () => {
  assert.throws(() => add({ x: 1, y: 2, z: 3 }, undefined), (e) => e instanceof TypeError && /b/.test(e.message));
  assert.throws(() => add({ x: 1, y: 2, z: 3 }, 'v'), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('add throws TypeError when b.x is NaN ("b" in message)', () => {
  assert.throws(() => add({ x: 1, y: 2, z: 3 }, { x: NaN, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

test('add throws TypeError when b.y is not a number ("b" in message)', () => {
  assert.throws(() => add({ x: 1, y: 2, z: 3 }, { x: 1, y: '2', z: 3 }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

test('add throws TypeError when b.z is not a number ("b" in message)', () => {
  assert.throws(() => add({ x: 1, y: 2, z: 3 }, { x: 1, y: 2, z: undefined }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

// --- sub ---

test('sub({x:5,y:7,z:9}, {x:1,y:2,z:3}) -> {x:4, y:5, z:6}', () => {
  assert.deepStrictEqual(sub({ x: 5, y: 7, z: 9 }, { x: 1, y: 2, z: 3 }), { x: 4, y: 5, z: 6 });
});

test('sub handles negative components', () => {
  assert.deepStrictEqual(sub({ x: 0, y: -1, z: 2 }, { x: -1, y: -1, z: 5 }), { x: 1, y: 0, z: -3 });
});

test('sub does not mutate arguments (pure)', () => {
  const a = { x: 5, y: 7, z: 9 };
  const b = { x: 1, y: 2, z: 3 };
  sub(a, b);
  assert.deepStrictEqual(a, { x: 5, y: 7, z: 9 });
  assert.deepStrictEqual(b, { x: 1, y: 2, z: 3 });
});

test('sub throws TypeError when a is not an object ("a" in message)', () => {
  assert.throws(() => sub(null, { x: 1, y: 2, z: 3 }), (e) => e instanceof TypeError && /a/.test(e.message));
  assert.throws(() => sub('v', { x: 1, y: 2, z: 3 }), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('sub throws TypeError when a.x is not a number ("a" in message)', () => {
  assert.throws(() => sub({ x: NaN, y: 2, z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('sub throws TypeError when a.y is NaN ("a" in message)', () => {
  assert.throws(() => sub({ x: 1, y: '2', z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('sub throws TypeError when a.z is not a number ("a" in message)', () => {
  assert.throws(() => sub({ x: 1, y: 2, z: undefined }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('sub throws TypeError when b is not an object ("b" in message)', () => {
  assert.throws(() => sub({ x: 1, y: 2, z: 3 }, null), (e) => e instanceof TypeError && /b/.test(e.message));
  assert.throws(() => sub({ x: 1, y: 2, z: 3 }, 42), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('sub throws TypeError when b.x is not a number ("b" in message)', () => {
  assert.throws(() => sub({ x: 1, y: 2, z: 3 }, { x: '1', y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

test('sub throws TypeError when b.y is NaN ("b" in message)', () => {
  assert.throws(() => sub({ x: 1, y: 2, z: 3 }, { x: 1, y: NaN, z: 3 }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

test('sub throws TypeError when b.z is not a number ("b" in message)', () => {
  assert.throws(() => sub({ x: 1, y: 2, z: 3 }, { x: 1, y: 2, z: null }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

// --- scale ---

test('scale({x:1,y:2,z:3}, 2) -> {x:2, y:4, z:6}', () => {
  assert.deepStrictEqual(scale({ x: 1, y: 2, z: 3 }, 2), { x: 2, y: 4, z: 6 });
});

test('scale({x:2,y:3,z:4}, 0) -> {x:0, y:0, z:0}', () => {
  assert.deepStrictEqual(scale({ x: 2, y: 3, z: 4 }, 0), { x: 0, y: 0, z: 0 });
});

test('scale handles negative scalar', () => {
  assert.deepStrictEqual(scale({ x: 1, y: -2, z: 3 }, -1), { x: -1, y: 2, z: -3 });
});

test('scale handles fractional scalar', () => {
  assert.deepStrictEqual(scale({ x: 2, y: 4, z: 6 }, 0.5), { x: 1, y: 2, z: 3 });
});

test('scale does not mutate argument (pure)', () => {
  const v = { x: 1, y: 2, z: 3 };
  scale(v, 2);
  assert.deepStrictEqual(v, { x: 1, y: 2, z: 3 });
});

test('scale throws TypeError when v is not an object ("v" in message)', () => {
  assert.throws(() => scale(null, 2), (e) => e instanceof TypeError && /v/.test(e.message));
  assert.throws(() => scale(5, 2), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('scale throws TypeError when v.x is NaN ("v" in message)', () => {
  assert.throws(() => scale({ x: NaN, y: 2, z: 3 }, 2), (e) =>
    e instanceof TypeError && /v/.test(e.message));
});

test('scale throws TypeError when v.y is not a number ("v" in message)', () => {
  assert.throws(() => scale({ x: 1, y: '2', z: 3 }, 2), (e) =>
    e instanceof TypeError && /v/.test(e.message));
});

test('scale throws TypeError when v.z is not a number ("v" in message)', () => {
  assert.throws(() => scale({ x: 1, y: 2, z: undefined }, 2), (e) =>
    e instanceof TypeError && /v/.test(e.message));
});

test('scale throws TypeError when s is not a number ("s" in message)', () => {
  assert.throws(() => scale({ x: 1, y: 2, z: 3 }, '2'), (e) =>
    e instanceof TypeError && /s/.test(e.message));
});

test('scale throws TypeError when s is NaN ("s" in message)', () => {
  assert.throws(() => scale({ x: 1, y: 2, z: 3 }, NaN), (e) =>
    e instanceof TypeError && /s/.test(e.message));
});

test('scale throws TypeError when s is null ("s" in message)', () => {
  assert.throws(() => scale({ x: 1, y: 2, z: 3 }, null), (e) =>
    e instanceof TypeError && /s/.test(e.message));
});

// --- dot ---

test('dot({x:1,y:0,z:0}, {x:0,y:1,z:0}) -> 0', () => {
  assert.strictEqual(dot({ x: 1, y: 0, z: 0 }, { x: 0, y: 1, z: 0 }), 0);
});

test('dot({x:1,y:2,z:3}, {x:4,y:5,z:6}) -> 32', () => {
  assert.strictEqual(dot({ x: 1, y: 2, z: 3 }, { x: 4, y: 5, z: 6 }), 32);
});

test('dot({x:2,y:-3,z:4}, {x:3,y:1,z:-2}) -> -5', () => {
  assert.strictEqual(dot({ x: 2, y: -3, z: 4 }, { x: 3, y: 1, z: -2 }), -5);
});

test('dot of zero vector -> 0', () => {
  assert.strictEqual(dot({ x: 0, y: 0, z: 0 }, { x: 1, y: 2, z: 3 }), 0);
});

test('dot throws TypeError when a is not an object ("a" in message)', () => {
  assert.throws(() => dot(null, { x: 1, y: 2, z: 3 }), (e) => e instanceof TypeError && /a/.test(e.message));
  assert.throws(() => dot('v', { x: 1, y: 2, z: 3 }), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('dot throws TypeError when a.x is NaN ("a" in message)', () => {
  assert.throws(() => dot({ x: NaN, y: 2, z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('dot throws TypeError when a.y is not a number ("a" in message)', () => {
  assert.throws(() => dot({ x: 1, y: null, z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('dot throws TypeError when a.z is not a number ("a" in message)', () => {
  assert.throws(() => dot({ x: 1, y: 2, z: undefined }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('dot throws TypeError when b is not an object ("b" in message)', () => {
  assert.throws(() => dot({ x: 1, y: 2, z: 3 }, null), (e) => e instanceof TypeError && /b/.test(e.message));
  assert.throws(() => dot({ x: 1, y: 2, z: 3 }, undefined), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

test('dot throws TypeError when b.x is not a number ("b" in message)', () => {
  assert.throws(() => dot({ x: 1, y: 2, z: 3 }, { x: '1', y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

test('dot throws TypeError when b.y is NaN ("b" in message)', () => {
  assert.throws(() => dot({ x: 1, y: 2, z: 3 }, { x: 1, y: NaN, z: 3 }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

test('dot throws TypeError when b.z is not a number ("b" in message)', () => {
  assert.throws(() => dot({ x: 1, y: 2, z: 3 }, { x: 1, y: 2, z: null }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

// --- cross ---

test('cross({x:1,y:0,z:0}, {x:0,y:1,z:0}) -> {x:0, y:0, z:1}', () => {
  assert.deepStrictEqual(cross({ x: 1, y: 0, z: 0 }, { x: 0, y: 1, z: 0 }), { x: 0, y: 0, z: 1 });
});

test('cross({x:0,y:1,z:0}, {x:0,y:0,z:1}) -> {x:1, y:0, z:0}', () => {
  assert.deepStrictEqual(cross({ x: 0, y: 1, z: 0 }, { x: 0, y: 0, z: 1 }), { x: 1, y: 0, z: 0 });
});

test('cross({x:0,y:0,z:1}, {x:1,y:0,z:0}) -> {x:0, y:1, z:0}', () => {
  assert.deepStrictEqual(cross({ x: 0, y: 0, z: 1 }, { x: 1, y: 0, z: 0 }), { x: 0, y: 1, z: 0 });
});

test('cross({x:1,y:2,z:3}, {x:4,y:5,z:6}) -> {x:-3, y:6, z:-3}', () => {
  assert.deepStrictEqual(cross({ x: 1, y: 2, z: 3 }, { x: 4, y: 5, z: 6 }), { x: -3, y: 6, z: -3 });
});

test('cross is antisymmetric: cross(a, a) -> {x:0, y:0, z:0}', () => {
  assert.deepStrictEqual(cross({ x: 2, y: -1, z: 4 }, { x: 2, y: -1, z: 4 }), { x: 0, y: 0, z: 0 });
});

test('cross does not mutate arguments (pure)', () => {
  const a = { x: 1, y: 2, z: 3 };
  const b = { x: 4, y: 5, z: 6 };
  cross(a, b);
  assert.deepStrictEqual(a, { x: 1, y: 2, z: 3 });
  assert.deepStrictEqual(b, { x: 4, y: 5, z: 6 });
});

test('cross throws TypeError when a is not an object ("a" in message)', () => {
  assert.throws(() => cross(null, { x: 1, y: 2, z: 3 }), (e) => e instanceof TypeError && /a/.test(e.message));
  assert.throws(() => cross(5, { x: 1, y: 2, z: 3 }), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('cross throws TypeError when a.x is not a number ("a" in message)', () => {
  assert.throws(() => cross({ x: '1', y: 2, z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('cross throws TypeError when a.y is NaN ("a" in message)', () => {
  assert.throws(() => cross({ x: 1, y: NaN, z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('cross throws TypeError when a.z is not a number ("a" in message)', () => {
  assert.throws(() => cross({ x: 1, y: 2, z: undefined }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message));
});

test('cross throws TypeError when b is not an object ("b" in message)', () => {
  assert.throws(() => cross({ x: 1, y: 2, z: 3 }, null), (e) => e instanceof TypeError && /b/.test(e.message));
  assert.throws(() => cross({ x: 1, y: 2, z: 3 }, 'v'), (e) => e instanceof TypeError && /b/.test(e.message));
});

test('cross throws TypeError when b.x is NaN ("b" in message)', () => {
  assert.throws(() => cross({ x: 1, y: 2, z: 3 }, { x: NaN, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

test('cross throws TypeError when b.y is not a number ("b" in message)', () => {
  assert.throws(() => cross({ x: 1, y: 2, z: 3 }, { x: 1, y: null, z: 3 }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

test('cross throws TypeError when b.z is not a number ("b" in message)', () => {
  assert.throws(() => cross({ x: 1, y: 2, z: 3 }, { x: 1, y: 2, z: '3' }), (e) =>
    e instanceof TypeError && /b/.test(e.message));
});

// --- length ---

test('length({x:3, y:4, z:0}) -> 5', () => {
  assert.strictEqual(length({ x: 3, y: 4, z: 0 }), 5);
});

test('length({x:2, y:3, z:6}) -> 7', () => {
  assert.strictEqual(length({ x: 2, y: 3, z: 6 }), 7);
});

test('length of zero vector -> 0', () => {
  assert.strictEqual(length({ x: 0, y: 0, z: 0 }), 0);
});

test('length handles negative components', () => {
  assert.strictEqual(length({ x: -3, y: 0, z: 4 }), 5);
});

test('length does not mutate argument (pure)', () => {
  const v = { x: 3, y: 4, z: 5 };
  length(v);
  assert.deepStrictEqual(v, { x: 3, y: 4, z: 5 });
});

test('length throws TypeError when v is not an object ("v" in message)', () => {
  assert.throws(() => length(null), (e) => e instanceof TypeError && /v/.test(e.message));
  assert.throws(() => length(5), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('length throws TypeError when v.x is NaN ("v" in message)', () => {
  assert.throws(() => length({ x: NaN, y: 4, z: 0 }), (e) =>
    e instanceof TypeError && /v/.test(e.message));
});

test('length throws TypeError when v.y is not a number ("v" in message)', () => {
  assert.throws(() => length({ x: 3, y: '4', z: 0 }), (e) =>
    e instanceof TypeError && /v/.test(e.message));
});

test('length throws TypeError when v.z is not a number ("v" in message)', () => {
  assert.throws(() => length({ x: 3, y: 4, z: undefined }), (e) =>
    e instanceof TypeError && /v/.test(e.message));
});

// --- normalize ---

test('normalize({x:0, y:0, z:5}) -> {x:0, y:0, z:1}', () => {
  assert.deepStrictEqual(normalize({ x: 0, y: 0, z: 5 }), { x: 0, y: 0, z: 1 });
});

test('normalize({x:3, y:4, z:0}) -> {x:0.6, y:0.8, z:0}', () => {
  const r = normalize({ x: 3, y: 4, z: 0 });
  // Дробный результат scale: 3/5 = 0.6000000000000001, сравниваем по eps
  assert.ok(Math.abs(r.x - 0.6) < 1e-9);
  assert.ok(Math.abs(r.y - 0.8) < 1e-9);
  assert.strictEqual(r.z, 0);
});

test('normalize({x:-1, y:0, z:0}) -> {x:-1, y:0, z:0}', () => {
  assert.deepStrictEqual(normalize({ x: -1, y: 0, z: 0 }), { x: -1, y: 0, z: 0 });
});

test('normalize of zero vector throws RangeError "zero vector"', () => {
  assert.throws(() => normalize({ x: 0, y: 0, z: 0 }), (e) =>
    e instanceof RangeError && e.message === 'zero vector');
});

test('normalize does not mutate argument (pure)', () => {
  const v = { x: 3, y: 4, z: 0 };
  normalize(v);
  assert.deepStrictEqual(v, { x: 3, y: 4, z: 0 });
});

test('normalize throws TypeError when v is not an object ("v" in message)', () => {
  assert.throws(() => normalize(null), (e) => e instanceof TypeError && /v/.test(e.message));
  assert.throws(() => normalize('v'), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('normalize throws TypeError when v.x is not a number ("v" in message)', () => {
  assert.throws(() => normalize({ x: '3', y: 4, z: 0 }), (e) =>
    e instanceof TypeError && /v/.test(e.message));
});

test('normalize throws TypeError when v.y is NaN ("v" in message)', () => {
  assert.throws(() => normalize({ x: 3, y: NaN, z: 0 }), (e) =>
    e instanceof TypeError && /v/.test(e.message));
});

test('normalize throws TypeError when v.z is not a number ("v" in message)', () => {
  assert.throws(() => normalize({ x: 3, y: 4, z: null }), (e) =>
    e instanceof TypeError && /v/.test(e.message));
});

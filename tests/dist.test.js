'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { dist2d, dist3d, arcLength } = require('../src/dist.js');

// --- dist2d ---

test('dist2d({x:0,y:0}, {x:3,y:4}) -> 5', () => {
  assert.strictEqual(dist2d({ x: 0, y: 0 }, { x: 3, y: 4 }), 5);
});

test('dist2d({x:1,y:1}, {x:1,y:1}) -> 0', () => {
  assert.strictEqual(dist2d({ x: 1, y: 1 }, { x: 1, y: 1 }), 0);
});

test('dist2d fractional result (a.b.c: hypot with fractions) within 1e-9', () => {
  const actual = dist2d({ x: 0.5, y: 1.25 }, { x: 2.5, y: 3.75 });
  assert.ok(Math.abs(actual - Math.hypot(2, 2.5)) < 1e-9);
});

test('dist2d handles negative coordinates', () => {
  const actual = dist2d({ x: -1, y: -1 }, { x: 2, y: 2 });
  assert.ok(Math.abs(actual - Math.hypot(3, 3)) < 1e-9);
});

test('dist2d throws TypeError when a is not an object ("a" in message)', () => {
  assert.throws(() => dist2d(null, { x: 1, y: 2 }), (e) => e instanceof TypeError && /a/.test(e.message));
  assert.throws(() => dist2d(5, { x: 1, y: 2 }), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('dist2d throws TypeError when a.x is not a number ("a" in message)', () => {
  assert.throws(() => dist2d({ x: '1', y: 2 }, { x: 1, y: 2 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('dist2d throws TypeError when a.x is NaN ("a" in message)', () => {
  assert.throws(() => dist2d({ x: NaN, y: 2 }, { x: 1, y: 2 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('dist2d throws TypeError when a.y is not a number ("a" in message)', () => {
  assert.throws(() => dist2d({ x: 1, y: '2' }, { x: 1, y: 2 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('dist2d throws TypeError when a.y is NaN ("a" in message)', () => {
  assert.throws(() => dist2d({ x: 1, y: NaN }, { x: 1, y: 2 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('dist2d throws TypeError when b is not an object ("b" in message)', () => {
  assert.throws(() => dist2d({ x: 1, y: 2 }, null), (e) => e instanceof TypeError && /b/.test(e.message));
  assert.throws(() => dist2d({ x: 1, y: 2 }, undefined), (e) =>
    e instanceof TypeError && /b/.test(e.message)
  );
});

test('dist2d throws TypeError when b.x is NaN ("b" in message)', () => {
  assert.throws(() => dist2d({ x: 1, y: 2 }, { x: NaN, y: 2 }), (e) =>
    e instanceof TypeError && /b/.test(e.message)
  );
});

test('dist2d throws TypeError when b.y is not a number ("b" in message)', () => {
  assert.throws(() => dist2d({ x: 1, y: 2 }, { x: 1, y: '2' }), (e) =>
    e instanceof TypeError && /b/.test(e.message)
  );
});

// --- dist3d ---

test('dist3d({x:0,y:0,z:0}, {x:2,y:3,z:6}) -> 7', () => {
  assert.strictEqual(dist3d({ x: 0, y: 0, z: 0 }, { x: 2, y: 3, z: 6 }), 7);
});

test('dist3d same point -> 0', () => {
  assert.strictEqual(dist3d({ x: 4, y: -1, z: 2.5 }, { x: 4, y: -1, z: 2.5 }), 0);
});

test('dist3d fractional result within 1e-9', () => {
  const actual = dist3d({ x: 0.5, y: -1.5, z: 0.25 }, { x: 1.75, y: 2.25, z: -0.75 });
  assert.ok(Math.abs(actual - Math.hypot(1.25, 3.75, -1)) < 1e-9);
});

test('dist3d throws TypeError when a is not an object ("a" in message)', () => {
  assert.throws(() => dist3d(null, { x: 1, y: 2, z: 3 }), (e) => e instanceof TypeError && /a/.test(e.message));
  assert.throws(() => dist3d('pt', { x: 1, y: 2, z: 3 }), (e) => e instanceof TypeError && /a/.test(e.message));
});

test('dist3d throws TypeError when a.x is not a number ("a" in message)', () => {
  assert.throws(() => dist3d({ x: '1', y: 2, z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('dist3d throws TypeError when a.x is NaN ("a" in message)', () => {
  assert.throws(() => dist3d({ x: NaN, y: 2, z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('dist3d throws TypeError when a.y is not a number ("a" in message)', () => {
  assert.throws(() => dist3d({ x: 1, y: '2', z: 3 }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('dist3d throws TypeError when a.z is NaN ("a" in message)', () => {
  assert.throws(() => dist3d({ x: 1, y: 2, z: NaN }, { x: 1, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /a/.test(e.message)
  );
});

test('dist3d throws TypeError when b is not an object ("b" in message)', () => {
  assert.throws(() => dist3d({ x: 1, y: 2, z: 3 }, null), (e) => e instanceof TypeError && /b/.test(e.message));
  assert.throws(() => dist3d({ x: 1, y: 2, z: 3 }, 42), (e) =>
    e instanceof TypeError && /b/.test(e.message)
  );
});

test('dist3d throws TypeError when b.x is NaN ("b" in message)', () => {
  assert.throws(() => dist3d({ x: 1, y: 2, z: 3 }, { x: NaN, y: 2, z: 3 }), (e) =>
    e instanceof TypeError && /b/.test(e.message)
  );
});

test('dist3d throws TypeError when b.y is not a number ("b" in message)', () => {
  assert.throws(() => dist3d({ x: 1, y: 2, z: 3 }, { x: 1, y: '2', z: 3 }), (e) =>
    e instanceof TypeError && /b/.test(e.message)
  );
});

test('dist3d throws TypeError when b.z is NaN ("b" in message)', () => {
  assert.throws(() => dist3d({ x: 1, y: 2, z: 3 }, { x: 1, y: 2, z: NaN }), (e) =>
    e instanceof TypeError && /b/.test(e.message)
  );
});

// --- arcLength ---

test('arcLength(1, Math.PI) -> Math.PI', () => {
  assert.ok(Math.abs(arcLength(1, Math.PI) - Math.PI) < 1e-9);
});

test('arcLength(2, Math.PI / 2) -> Math.PI', () => {
  assert.ok(Math.abs(arcLength(2, Math.PI / 2) - Math.PI) < 1e-9);
});

test('arcLength(3, 0) -> 0', () => {
  assert.strictEqual(arcLength(3, 0), 0);
});

test('arcLength(0, Math.PI) -> 0', () => {
  assert.strictEqual(arcLength(0, Math.PI), 0);
});

test('arcLength throws RangeError "negative radius" for r < 0', () => {
  assert.throws(() => arcLength(-1, Math.PI), (e) =>
    e instanceof RangeError && e.message === 'negative radius'
  );
});

test('arcLength throws RangeError "negative angle" for theta < 0', () => {
  assert.throws(() => arcLength(2, -Math.PI / 2), (e) =>
    e instanceof RangeError && e.message === 'negative angle'
  );
});

test('arcLength RangeError thrown before angle check (r < 0 and theta < 0 -> "negative radius")', () => {
  assert.throws(() => arcLength(-1, -1), (e) =>
    e instanceof RangeError && e.message === 'negative radius'
  );
});

test('arcLength throws TypeError when r is not a number ("r" in message)', () => {
  assert.throws(() => arcLength('1', Math.PI), (e) => e instanceof TypeError && /r/.test(e.message));
});

test('arcLength throws TypeError when r is NaN ("r" in message)', () => {
  assert.throws(() => arcLength(NaN, Math.PI), (e) => e instanceof TypeError && /r/.test(e.message));
});

test('arcLength throws TypeError when theta is not a number ("theta" in message)', () => {
  assert.throws(() => arcLength(1, 'PI'), (e) => e instanceof TypeError && /theta/.test(e.message));
});

test('arcLength throws TypeError when theta is NaN ("theta" in message)', () => {
  assert.throws(() => arcLength(1, NaN), (e) => e instanceof TypeError && /theta/.test(e.message));
});

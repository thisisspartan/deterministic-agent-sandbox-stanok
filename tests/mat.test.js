'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { identity, mul, mulVec, det, transpose } = require('../src/mat.js');

const M = { a: 1, b: 2, c: 3, d: 4 };
const N = { a: 5, b: 6, c: 7, d: 8 };

// --- identity ---

test('identity() -> {a: 1, b: 0, c: 0, d: 1}', () => {
  assert.deepStrictEqual(identity(), { a: 1, b: 0, c: 0, d: 1 });
});

test('identity() returns a fresh object each call (pure)', () => {
  const i1 = identity();
  const i2 = identity();
  assert.notStrictEqual(i1, i2);
  assert.deepStrictEqual(i1, { a: 1, b: 0, c: 0, d: 1 });
  assert.deepStrictEqual(i2, { a: 1, b: 0, c: 0, d: 1 });
});

// --- mul ---

test('mul({1,2,3,4}, {5,6,7,8}) -> {19, 22, 43, 50}', () => {
  assert.deepStrictEqual(mul(M, N), { a: 19, b: 22, c: 43, d: 50 });
});

test('mul(identity(), m) -> m (left identity)', () => {
  const m = { a: -2, b: 3.5, c: 7, d: -0.5 };
  assert.deepStrictEqual(mul(identity(), m), m);
});

test('mul(m, identity()) -> m (right identity)', () => {
  const m = { a: -2, b: 3.5, c: 7, d: -0.5 };
  assert.deepStrictEqual(mul(m, identity()), m);
});

test('mul handles negative components', () => {
  const x = { a: -1, b: 2, c: 3, d: -4 };
  const y = { a: 1, b: -1, c: 0, d: 1 };
  // a: -1*1 + 2*0 = -1; b: -1*-1 + 2*1 = 3
  // c: 3*1 + -4*0 = 3; d: 3*-1 + -4*1 = -7
  assert.deepStrictEqual(mul(x, y), { a: -1, b: 3, c: 3, d: -7 });
});

test('mul does not mutate arguments (pure)', () => {
  const m = { a: 1, b: 2, c: 3, d: 4 };
  const n = { a: 5, b: 6, c: 7, d: 8 };
  mul(m, n);
  assert.deepStrictEqual(m, { a: 1, b: 2, c: 3, d: 4 });
  assert.deepStrictEqual(n, { a: 5, b: 6, c: 7, d: 8 });
});

test('mul throws TypeError when m is not an object ("m" in message)', () => {
  assert.throws(() => mul(null, N), (e) => e instanceof TypeError && /m/.test(e.message));
  assert.throws(() => mul(5, N), (e) => e instanceof TypeError && /m/.test(e.message));
});

test('mul throws TypeError for each non-numeric/NaN component of m (component name in message)', () => {
  for (const comp of ['a', 'b', 'c', 'd']) {
    const bad = { a: 1, b: 2, c: 3, d: 4 };
    bad[comp] = 'oops';
    assert.throws(() => mul(bad, N), (e) => e instanceof TypeError && e.message.includes(comp));
  }
  for (const comp of ['a', 'b', 'c', 'd']) {
    const bad = { a: 1, b: 2, c: 3, d: 4 };
    bad[comp] = NaN;
    assert.throws(() => mul(bad, N), (e) => e instanceof TypeError && e.message.includes(comp));
  }
});

test('mul throws TypeError for each non-numeric/NaN component of n (component name in message)', () => {
  for (const comp of ['a', 'b', 'c', 'd']) {
    const bad = { a: 5, b: 6, c: 7, d: 8 };
    bad[comp] = 'oops';
    assert.throws(() => mul(M, bad), (e) => e instanceof TypeError && e.message.includes(comp));
  }
  for (const comp of ['a', 'b', 'c', 'd']) {
    const bad = { a: 5, b: 6, c: 7, d: 8 };
    bad[comp] = NaN;
    assert.throws(() => mul(M, bad), (e) => e instanceof TypeError && e.message.includes(comp));
  }
});

// --- mulVec ---

test('mulVec(identity(), {x: 3, y: 4}) -> {x: 3, y: 4}', () => {
  assert.deepStrictEqual(mulVec(identity(), { x: 3, y: 4 }), { x: 3, y: 4 });
});

test('mulVec({1,2,3,4}, {x: 5, y: 6}) -> {x: 17, y: 39}', () => {
  // x: 1*5 + 2*6 = 17; y: 3*5 + 4*6 = 39
  assert.deepStrictEqual(mulVec(M, { x: 5, y: 6 }), { x: 17, y: 39 });
});

test('mulVec handles negative components', () => {
  assert.deepStrictEqual(mulVec({ a: -1, b: 2, c: 3, d: -4 }, { x: 1, y: -1 }), {
    x: -1 - 2,
    y: 3 + 4,
  });
});

test('mulVec does not mutate arguments (pure)', () => {
  const m = { a: 1, b: 2, c: 3, d: 4 };
  const v = { x: 5, y: 6 };
  mulVec(m, v);
  assert.deepStrictEqual(m, { a: 1, b: 2, c: 3, d: 4 });
  assert.deepStrictEqual(v, { x: 5, y: 6 });
});

test('mulVec throws TypeError when m is not an object ("m" in message)', () => {
  assert.throws(() => mulVec(null, { x: 1, y: 2 }), (e) => e instanceof TypeError && /m/.test(e.message));
  assert.throws(() => mulVec(7, { x: 1, y: 2 }), (e) => e instanceof TypeError && /m/.test(e.message));
});

test('mulVec throws TypeError for each non-numeric/NaN component of m (component name in message)', () => {
  for (const comp of ['a', 'b', 'c', 'd']) {
    const bad = { a: 1, b: 2, c: 3, d: 4 };
    bad[comp] = 'oops';
    assert.throws(() => mulVec(bad, { x: 1, y: 2 }), (e) =>
      e instanceof TypeError && e.message.includes(comp)
    );
  }
  for (const comp of ['a', 'b', 'c', 'd']) {
    const bad = { a: 1, b: 2, c: 3, d: 4 };
    bad[comp] = NaN;
    assert.throws(() => mulVec(bad, { x: 1, y: 2 }), (e) =>
      e instanceof TypeError && e.message.includes(comp)
    );
  }
});

test('mulVec throws TypeError when v is not an object ("v" in message)', () => {
  assert.throws(() => mulVec(M, null), (e) => e instanceof TypeError && /v/.test(e.message));
  assert.throws(() => mulVec(M, 5), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('mulVec throws TypeError for each non-numeric/NaN component of v (component name in message)', () => {
  assert.throws(() => mulVec(M, { x: 'oops', y: 1 }), (e) =>
    e instanceof TypeError && e.message.includes('x')
  );
  assert.throws(() => mulVec(M, { x: NaN, y: 1 }), (e) =>
    e instanceof TypeError && e.message.includes('x')
  );
  assert.throws(() => mulVec(M, { x: 1, y: 'oops' }), (e) =>
    e instanceof TypeError && e.message.includes('y')
  );
  assert.throws(() => mulVec(M, { x: 1, y: NaN }), (e) =>
    e instanceof TypeError && e.message.includes('y')
  );
});

// --- det ---

test('det({1, 2, 3, 4}) -> -2', () => {
  assert.strictEqual(det(M), -2);
});

test('det(identity()) -> 1', () => {
  assert.strictEqual(det(identity()), 1);
});

test('det({1, 0, 0, 1} scaled) -> a*d for diagonal matrix', () => {
  assert.strictEqual(det({ a: 3, b: 0, c: 0, d: 4 }), 12);
});

test('det throws TypeError when m is not an object ("m" in message)', () => {
  assert.throws(() => det(null), (e) => e instanceof TypeError && /m/.test(e.message));
  assert.throws(() => det(5), (e) => e instanceof TypeError && /m/.test(e.message));
});

test('det throws TypeError for each non-numeric/NaN component (component name in message)', () => {
  for (const comp of ['a', 'b', 'c', 'd']) {
    const bad = { a: 1, b: 2, c: 3, d: 4 };
    bad[comp] = 'oops';
    assert.throws(() => det(bad), (e) => e instanceof TypeError && e.message.includes(comp));
  }
  for (const comp of ['a', 'b', 'c', 'd']) {
    const bad = { a: 1, b: 2, c: 3, d: 4 };
    bad[comp] = NaN;
    assert.throws(() => det(bad), (e) => e instanceof TypeError && e.message.includes(comp));
  }
});

// --- transpose ---

test('transpose({1, 2, 3, 4}) -> {a: 1, b: 3, c: 2, d: 4}', () => {
  assert.deepStrictEqual(transpose(M), { a: 1, b: 3, c: 2, d: 4 });
});

test('transpose(identity()) -> identity', () => {
  assert.deepStrictEqual(transpose(identity()), { a: 1, b: 0, c: 0, d: 1 });
});

test('transpose is its own inverse for symmetric matrix', () => {
  const s = { a: 1, b: 2, c: 2, d: 9 };
  assert.deepStrictEqual(transpose(s), s);
});

test('transpose does not mutate the argument (pure)', () => {
  const m = { a: 1, b: 2, c: 3, d: 4 };
  transpose(m);
  assert.deepStrictEqual(m, { a: 1, b: 2, c: 3, d: 4 });
});

test('transpose throws TypeError when m is not an object ("m" in message)', () => {
  assert.throws(() => transpose(null), (e) => e instanceof TypeError && /m/.test(e.message));
  assert.throws(() => transpose(5), (e) => e instanceof TypeError && /m/.test(e.message));
});

test('transpose throws TypeError for each non-numeric/NaN component (component name in message)', () => {
  for (const comp of ['a', 'b', 'c', 'd']) {
    const bad = { a: 1, b: 2, c: 3, d: 4 };
    bad[comp] = 'oops';
    assert.throws(() => transpose(bad), (e) => e instanceof TypeError && e.message.includes(comp));
  }
  for (const comp of ['a', 'b', 'c', 'd']) {
    const bad = { a: 1, b: 2, c: 3, d: 4 };
    bad[comp] = NaN;
    assert.throws(() => transpose(bad), (e) => e instanceof TypeError && e.message.includes(comp));
  }
});

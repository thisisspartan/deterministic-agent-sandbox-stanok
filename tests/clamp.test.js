'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { clamp, clamp01, clampVec } = require('../src/clamp.js');

// --- clamp ---

test('clamp(5, 0, 10) -> 5 (in range)', () => {
  assert.strictEqual(clamp(5, 0, 10), 5);
});

test('clamp(-3, 0, 10) -> 0 (below min)', () => {
  assert.strictEqual(clamp(-3, 0, 10), 0);
});

test('clamp(42, 0, 10) -> 10 (above max)', () => {
  assert.strictEqual(clamp(42, 0, 10), 10);
});

test('clamp(0.5, 0, 1) -> 0.5', () => {
  assert.strictEqual(clamp(0.5, 0, 1), 0.5);
});

test('clamp boundaries returned unchanged', () => {
  assert.strictEqual(clamp(0, 0, 10), 0);
  assert.strictEqual(clamp(10, 0, 10), 10);
});

test('clamp works with negative range', () => {
  assert.strictEqual(clamp(-5, -10, -1), -5);
  assert.strictEqual(clamp(-20, -10, -1), -10);
  assert.strictEqual(clamp(1, -10, -1), -1);
});

test('clamp throws RangeError "min > max" when min > max', () => {
  assert.throws(() => clamp(5, 10, 0), (e) =>
    e instanceof RangeError && e.message === 'min > max'
  );
});

test('clamp throws TypeError when v is not a number ("v" in message)', () => {
  assert.throws(() => clamp('5', 0, 10), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('clamp throws TypeError when v is NaN ("v" in message)', () => {
  assert.throws(() => clamp(NaN, 0, 10), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('clamp throws TypeError when min is not a number ("min" in message)', () => {
  assert.throws(() => clamp(5, '0', 10), (e) => e instanceof TypeError && /min/.test(e.message));
});

test('clamp throws TypeError when min is NaN ("min" in message)', () => {
  assert.throws(() => clamp(5, NaN, 10), (e) => e instanceof TypeError && /min/.test(e.message));
});

test('clamp throws TypeError when max is not a number ("max" in message)', () => {
  assert.throws(() => clamp(5, 0, '10'), (e) => e instanceof TypeError && /max/.test(e.message));
});

test('clamp throws TypeError when max is NaN ("max" in message)', () => {
  assert.throws(() => clamp(5, 0, NaN), (e) => e instanceof TypeError && /max/.test(e.message));
});

// --- clamp01 ---

test('clamp01(-1) -> 0', () => {
  assert.strictEqual(clamp01(-1), 0);
});

test('clamp01(2) -> 1', () => {
  assert.strictEqual(clamp01(2), 1);
});

test('clamp01(0.25) -> 0.25 (in range)', () => {
  assert.strictEqual(clamp01(0.25), 0.25);
});

test('clamp01 boundaries returned unchanged', () => {
  assert.strictEqual(clamp01(0), 0);
  assert.strictEqual(clamp01(1), 1);
});

test('clamp01 throws TypeError when v is not a number ("v" in message)', () => {
  assert.throws(() => clamp01('0.5'), (e) => e instanceof TypeError && /v/.test(e.message));
});

test('clamp01 throws TypeError when v is NaN ("v" in message)', () => {
  assert.throws(() => clamp01(NaN), (e) => e instanceof TypeError && /v/.test(e.message));
});

// --- clampVec ---

test('clampVec({x:-1,y:5}, {x:0,y:0}, {x:1,y:1}) -> {x:0,y:1}', () => {
  assert.deepStrictEqual(
    clampVec({ x: -1, y: 5 }, { x: 0, y: 0 }, { x: 1, y: 1 }),
    { x: 0, y: 1 }
  );
});

test('clampVec keeps components within range unchanged', () => {
  assert.deepStrictEqual(
    clampVec({ x: 0.25, y: 0.75 }, { x: 0, y: 0 }, { x: 1, y: 1 }),
    { x: 0.25, y: 0.75 }
  );
});

test('clampVec clamps each component independently', () => {
  assert.deepStrictEqual(
    clampVec({ x: -5, y: 0.5 }, { x: 0, y: 0 }, { x: 1, y: 1 }),
    { x: 0, y: 0.5 }
  );
  assert.deepStrictEqual(
    clampVec({ x: 0.5, y: 5 }, { x: 0, y: 0 }, { x: 1, y: 1 }),
    { x: 0.5, y: 1 }
  );
});

test('clampVec throws RangeError "min > max" for any component', () => {
  assert.throws(() => clampVec({ x: 0.5, y: 0.5 }, { x: 1, y: 0 }, { x: 0, y: 1 }), (e) =>
    e instanceof RangeError && e.message === 'min > max'
  );
  assert.throws(() => clampVec({ x: 0.5, y: 0.5 }, { x: 0, y: 1 }, { x: 1, y: 0 }), (e) =>
    e instanceof RangeError && e.message === 'min > max'
  );
});

test('clampVec throws TypeError when v is not an object', () => {
  assert.throws(() => clampVec(5, { x: 0, y: 0 }, { x: 1, y: 1 }), (e) =>
    e instanceof TypeError
  );
});

test('clampVec throws TypeError when min is not an object', () => {
  assert.throws(() => clampVec({ x: 0.5, y: 0.5 }, 0, { x: 1, y: 1 }), (e) =>
    e instanceof TypeError
  );
});

test('clampVec throws TypeError when max is not an object', () => {
  assert.throws(() => clampVec({ x: 0.5, y: 0.5 }, { x: 0, y: 0 }, 1), (e) =>
    e instanceof TypeError
  );
});

test('clampVec throws TypeError when v.x is not a number ("x" in message)', () => {
  assert.throws(() => clampVec({ x: '0.5', y: 0.5 }, { x: 0, y: 0 }, { x: 1, y: 1 }), (e) =>
    e instanceof TypeError && /x/.test(e.message)
  );
});

test('clampVec throws TypeError when v.x is NaN ("x" in message)', () => {
  assert.throws(() => clampVec({ x: NaN, y: 0.5 }, { x: 0, y: 0 }, { x: 1, y: 1 }), (e) =>
    e instanceof TypeError && /x/.test(e.message)
  );
});

test('clampVec throws TypeError when v.y is not a number ("y" in message)', () => {
  assert.throws(() => clampVec({ x: 0.5, y: '0.5' }, { x: 0, y: 0 }, { x: 1, y: 1 }), (e) =>
    e instanceof TypeError && /y/.test(e.message)
  );
});

test('clampVec throws TypeError when v.y is NaN ("y" in message)', () => {
  assert.throws(() => clampVec({ x: 0.5, y: NaN }, { x: 0, y: 0 }, { x: 1, y: 1 }), (e) =>
    e instanceof TypeError && /y/.test(e.message)
  );
});

test('clampVec throws TypeError when min.x is not a number ("x" in message)', () => {
  assert.throws(() => clampVec({ x: 0.5, y: 0.5 }, { x: '0', y: 0 }, { x: 1, y: 1 }), (e) =>
    e instanceof TypeError && /x/.test(e.message)
  );
});

test('clampVec throws TypeError when max.y is NaN ("y" in message)', () => {
  assert.throws(() => clampVec({ x: 0.5, y: 0.5 }, { x: 0, y: 0 }, { x: 1, y: NaN }), (e) =>
    e instanceof TypeError && /y/.test(e.message)
  );
});

'use strict';

const test = require('node:test');
const assert = require('node:assert');

const grid = require('../src/grid.js');

// --- create ---

test('create(2, 3, 0) -> [[0,0,0],[0,0,0]]', () => {
  assert.deepStrictEqual(grid.create(2, 3, 0), [[0, 0, 0], [0, 0, 0]]);
});

test('create fills with object value by reference', () => {
  const obj = { a: 1 };
  const g = grid.create(1, 2, obj);
  assert.strictEqual(g[0][0], obj);
  assert.strictEqual(g[0][1], obj);
});

test('create throws RangeError "invalid dimensions" for zero rows', () => {
  assert.throws(() => grid.create(0, 3, 0), (e) =>
    e instanceof RangeError && e.message === 'invalid dimensions'
  );
});

test('create throws RangeError "invalid dimensions" for zero cols', () => {
  assert.throws(() => grid.create(2, 0, 0), (e) =>
    e instanceof RangeError && e.message === 'invalid dimensions'
  );
});

test('create throws RangeError "invalid dimensions" for negative dims', () => {
  assert.throws(() => grid.create(-1, 3, 0), (e) =>
    e instanceof RangeError && e.message === 'invalid dimensions'
  );
});

test('create throws TypeError "rows" when rows is not a number', () => {
  assert.throws(() => grid.create('2', 3, 0), (e) =>
    e instanceof TypeError && /rows/.test(e.message)
  );
});

test('create throws TypeError "rows" when rows is NaN', () => {
  assert.throws(() => grid.create(NaN, 3, 0), (e) =>
    e instanceof TypeError && /rows/.test(e.message)
  );
});

test('create throws TypeError "rows" when rows is fractional', () => {
  assert.throws(() => grid.create(2.5, 3, 0), (e) =>
    e instanceof TypeError && /rows/.test(e.message)
  );
});

test('create throws TypeError "cols" when cols is not a number', () => {
  assert.throws(() => grid.create(2, '3', 0), (e) =>
    e instanceof TypeError && /cols/.test(e.message)
  );
});

test('create throws TypeError "cols" when cols is fractional', () => {
  assert.throws(() => grid.create(2, 3.5, 0), (e) =>
    e instanceof TypeError && /cols/.test(e.message)
  );
});

// --- at ---

test('at(create(2, 3, 7), 1, 2) -> 7', () => {
  assert.strictEqual(grid.at(grid.create(2, 3, 7), 1, 2), 7);
});

test('at works at corners', () => {
  const g = grid.create(2, 3, 0);
  grid.set(g, 0, 0, 1);
  grid.set(g, 0, 2, 2);
  grid.set(g, 1, 0, 3);
  grid.set(g, 1, 2, 4);
  assert.strictEqual(grid.at(g, 0, 0), 1);
  assert.strictEqual(grid.at(g, 0, 2), 2);
  assert.strictEqual(grid.at(g, 1, 0), 3);
  assert.strictEqual(grid.at(g, 1, 2), 4);
});

test('at throws RangeError "out of bounds" for row too large', () => {
  assert.throws(() => grid.at(grid.create(2, 3, 0), 2, 0), (e) =>
    e instanceof RangeError && e.message === 'out of bounds'
  );
});

test('at throws RangeError "out of bounds" for row negative', () => {
  assert.throws(() => grid.at(grid.create(2, 3, 0), -1, 0), (e) =>
    e instanceof RangeError && e.message === 'out of bounds'
  );
});

test('at throws RangeError "out of bounds" for col too large', () => {
  assert.throws(() => grid.at(grid.create(2, 3, 0), 0, 3), (e) =>
    e instanceof RangeError && e.message === 'out of bounds'
  );
});

test('at throws RangeError "out of bounds" for col negative', () => {
  assert.throws(() => grid.at(grid.create(2, 3, 0), 0, -1), (e) =>
    e instanceof RangeError && e.message === 'out of bounds'
  );
});

test('at throws TypeError "r" when r is not a number', () => {
  assert.throws(() => grid.at(grid.create(2, 3, 0), '0', 0), (e) =>
    e instanceof TypeError && /r/.test(e.message)
  );
});

test('at throws TypeError "r" when r is fractional', () => {
  assert.throws(() => grid.at(grid.create(2, 3, 0), 0.5, 0), (e) =>
    e instanceof TypeError && /r/.test(e.message)
  );
});

test('at throws TypeError "c" when c is not a number', () => {
  assert.throws(() => grid.at(grid.create(2, 3, 0), 0, '1'), (e) =>
    e instanceof TypeError && /c/.test(e.message)
  );
});

test('at throws TypeError "c" when c is fractional', () => {
  assert.throws(() => grid.at(grid.create(2, 3, 0), 0, 1.5), (e) =>
    e instanceof TypeError && /c/.test(e.message)
  );
});

test('at throws TypeError "grid" when grid is not an array', () => {
  assert.throws(() => grid.at({ rows: [] }, 0, 0), (e) =>
    e instanceof TypeError && /grid/.test(e.message)
  );
});

// --- set ---

test('set mutates cell and returns the grid', () => {
  const g = grid.create(2, 3, 0);
  const result = grid.set(g, 1, 2, 42);
  assert.strictEqual(result, g);
  assert.strictEqual(grid.at(g, 1, 2), 42);
});

test('set throws RangeError "out of bounds" for row too large', () => {
  assert.throws(() => grid.set(grid.create(2, 3, 0), 2, 0, 1), (e) =>
    e instanceof RangeError && e.message === 'out of bounds'
  );
});

test('set throws RangeError "out of bounds" for col negative', () => {
  assert.throws(() => grid.set(grid.create(2, 3, 0), 0, -1, 1), (e) =>
    e instanceof RangeError && e.message === 'out of bounds'
  );
});

test('set throws TypeError "r" when r is fractional', () => {
  assert.throws(() => grid.set(grid.create(2, 3, 0), 0.5, 0, 1), (e) =>
    e instanceof TypeError && /r/.test(e.message)
  );
});

test('set throws TypeError "c" when c is not a number', () => {
  assert.throws(() => grid.set(grid.create(2, 3, 0), 0, '1', 1), (e) =>
    e instanceof TypeError && /c/.test(e.message)
  );
});

test('set throws TypeError "grid" when grid is not an array', () => {
  assert.throws(() => grid.set(null, 0, 0, 1), (e) =>
    e instanceof TypeError && /grid/.test(e.message)
  );
});

// --- width / height ---

test('width(create(2, 3, 0)) -> 3', () => {
  assert.strictEqual(grid.width(grid.create(2, 3, 0)), 3);
});

test('height(create(2, 3, 0)) -> 2', () => {
  assert.strictEqual(grid.height(grid.create(2, 3, 0)), 2);
});

test('width throws TypeError "grid" when grid is not an array', () => {
  assert.throws(() => grid.width(5), (e) =>
    e instanceof TypeError && /grid/.test(e.message)
  );
});

test('height throws TypeError "grid" when grid is not an array', () => {
  assert.throws(() => grid.height(null), (e) =>
    e instanceof TypeError && /grid/.test(e.message)
  );
});

// --- inBounds ---

test('inBounds(create(2, 3, 0), 1, 2) -> true', () => {
  assert.strictEqual(grid.inBounds(grid.create(2, 3, 0), 1, 2), true);
});

test('inBounds(create(2, 3, 0), 2, 0) -> false', () => {
  assert.strictEqual(grid.inBounds(grid.create(2, 3, 0), 2, 0), false);
});

test('inBounds returns false for negative indices without throwing', () => {
  const g = grid.create(2, 3, 0);
  assert.strictEqual(grid.inBounds(g, -1, 0), false);
  assert.strictEqual(grid.inBounds(g, 0, -1), false);
});

test('inBounds throws TypeError "r" when r is not an integer', () => {
  assert.throws(() => grid.inBounds(grid.create(2, 3, 0), 0.5, 0), (e) =>
    e instanceof TypeError && /r/.test(e.message)
  );
});

test('inBounds throws TypeError "c" when c is not a number', () => {
  assert.throws(() => grid.inBounds(grid.create(2, 3, 0), 0, '1'), (e) =>
    e instanceof TypeError && /c/.test(e.message)
  );
});

// --- clone ---

test('clone returns a new grid with new rows and copied values', () => {
  const g = grid.create(2, 3, 0);
  const c = grid.clone(g);
  assert.notStrictEqual(c, g);
  assert.notStrictEqual(c[0], g[0]);
  assert.strictEqual(c[0][0], g[0][0]);
  assert.deepStrictEqual(c, g);
});

test('clone is independent: mutating clone does not affect original', () => {
  const g = grid.create(2, 3, 1);
  const c = grid.clone(g);
  grid.set(c, 0, 0, 99);
  assert.strictEqual(grid.at(g, 0, 0), 1);
});

test('clone copies object cells by reference', () => {
  const obj = { a: 1 };
  const g = grid.create(1, 1, obj);
  const c = grid.clone(g);
  assert.strictEqual(c[0][0], obj);
});

test('clone throws TypeError "grid" when grid is not an array', () => {
  assert.throws(() => grid.clone('nope'), (e) =>
    e instanceof TypeError && /grid/.test(e.message)
  );
});

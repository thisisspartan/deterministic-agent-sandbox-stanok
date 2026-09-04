'use strict';

const test = require('node:test');
const assert = require('node:assert');

const EPS = 1e-9;

let vecops;
try {
  vecops = require('../src/vecops.js');
} catch (err) {
  // Красная фаза: модуль ещё не существует.
  test('module src/vecops.js exists', () => {
    assert.fail('src/vecops.js not found: ' + err.message);
  });
  return;
}

function close(a, b) {
  return Math.abs(a - b) < EPS;
}

// ---------- dist ----------

test('dist: origin to {3,4} is 5', () => {
  assert.ok(close(vecops.dist({ x: 0, y: 0 }, { x: 3, y: 4 }), 5));
});

test('dist: symmetric', () => {
  assert.ok(
    close(
      vecops.dist({ x: 1, y: 2 }, { x: 4, y: 6 }),
      vecops.dist({ x: 4, y: 6 }, { x: 1, y: 2 })
    )
  );
});

test('dist: same point is 0', () => {
  assert.strictEqual(vecops.dist({ x: 2, y: -2 }, { x: 2, y: -2 }), 0);
});

// ---------- mid ----------

test('mid: {0,0} and {2,4} -> {1,2}', () => {
  const m = vecops.mid({ x: 0, y: 0 }, { x: 2, y: 4 });
  assert.ok(close(m.x, 1));
  assert.ok(close(m.y, 2));
});

test('mid: negative coordinates', () => {
  const m = vecops.mid({ x: -3, y: 1 }, { x: 1, y: 3 });
  assert.ok(close(m.x, -1));
  assert.ok(close(m.y, 2));
});

// ---------- normalize2 ----------

test('normalize2: {3,4} -> {0.6, 0.8}', () => {
  const n = vecops.normalize2({ x: 3, y: 4 });
  assert.ok(close(n.x, 0.6));
  assert.ok(close(n.y, 0.8));
});

test('normalize2: unit vector unchanged', () => {
  const n = vecops.normalize2({ x: 1, y: 0 });
  assert.ok(close(n.x, 1));
  assert.ok(close(n.y, 0));
});

test('normalize2: zero vector throws RangeError "zero vector"', () => {
  assert.throws(
    () => vecops.normalize2({ x: 0, y: 0 }),
    (e) => e instanceof RangeError && e.message === 'zero vector'
  );
});

// ---------- project ----------

test('project: {1,1} onto {1,0} -> {1,0}', () => {
  const p = vecops.project({ x: 1, y: 1 }, { x: 1, y: 0 });
  assert.ok(close(p.x, 1));
  assert.ok(close(p.y, 0));
});

test('project: {1,1} onto {0,1} -> {0,1}', () => {
  const p = vecops.project({ x: 1, y: 1 }, { x: 0, y: 1 });
  assert.ok(close(p.x, 0));
  assert.ok(close(p.y, 1));
});

test('project: orthogonal vector projects to zero', () => {
  const p = vecops.project({ x: 1, y: 0 }, { x: 0, y: 5 });
  assert.ok(close(p.x, 0));
  assert.ok(close(p.y, 0));
});

test('project: zero basis throws RangeError "zero basis"', () => {
  assert.throws(
    () => vecops.project({ x: 1, y: 1 }, { x: 0, y: 0 }),
    (e) => e instanceof RangeError && e.message === 'zero basis'
  );
});

// ---------- валидация аргументов ----------

const vecCases = [
  ['dist', (v) => vecops.dist(v, { x: 1, y: 1 })],
  ['dist.b', (v) => vecops.dist({ x: 1, y: 1 }, v)],
  ['mid.a', (v) => vecops.mid(v, { x: 1, y: 1 })],
  ['mid.b', (v) => vecops.mid({ x: 1, y: 1 }, v)],
  ['normalize2', (v) => vecops.normalize2(v)],
  ['project.a', (v) => vecops.project(v, { x: 1, y: 1 })],
  ['project.b', (v) => vecops.project({ x: 1, y: 1 }, v)]
];

for (const [label, call] of vecCases) {
  test(`vecops ${label}: non-numeric x -> TypeError naming "x"`, () => {
    assert.throws(
      () => call({ x: 'oops', y: 1 }),
      (e) => e instanceof TypeError && /x/.test(e.message)
    );
  });

  test(`vecops ${label}: non-numeric y -> TypeError naming "y"`, () => {
    assert.throws(
      () => call({ x: 1, y: null }),
      (e) => e instanceof TypeError && /y/.test(e.message)
    );
  });

  test(`vecops ${label}: NaN x -> TypeError`, () => {
    assert.throws(
      () => call({ x: NaN, y: 1 }),
      (e) => e instanceof TypeError && /x/.test(e.message)
    );
  });

  test(`vecops ${label}: missing component -> TypeError`, () => {
    assert.throws(
      () => call({}),
      (e) =>
        e instanceof TypeError && /x/.test(e.message) && /y/.test(e.message)
    );
  });

  test(`vecops ${label}: null argument -> TypeError`, () => {
    assert.throws(() => call(null), (e) => e instanceof TypeError);
  });
}

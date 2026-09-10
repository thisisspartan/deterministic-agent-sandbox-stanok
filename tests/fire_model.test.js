'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createFireModel } = require('../src/fire_model.js');

/** Assert every cell is a number within [0, maxHeat] and grid has h rows of w cells. */
function assertInRange(model) {
  const { w, h, grid, maxHeat } = model;
  assert.equal(grid.length, h, `grid should have ${h} rows`);
  for (let y = 0; y < h; y++) {
    assert.equal(grid[y].length, w, `row ${y} should have ${w} cells`);
    for (let x = 0; x < w; x++) {
      const v = grid[y][x];
      assert.equal(typeof v, 'number', `grid[${y}][${x}] should be a number`);
      assert.ok(
        Number.isFinite(v) && v >= 0 && v <= maxHeat,
        `grid[${y}][${x}] = ${v} out of range [0, ${maxHeat}]`
      );
    }
  }
}

function rowAvg(model, y) {
  let sum = 0;
  for (let x = 0; x < model.w; x++) sum += model.grid[y][x];
  return sum / model.w;
}

test('createFireModel(80, 24): grid has 24 rows of 80 numbers in [0, 255]', () => {
  const m = createFireModel(80, 24);
  assert.equal(m.w, 80);
  assert.equal(m.h, 24);
  assert.equal(m.maxHeat, 255);
  assertInRange(m);
});

test('range invariant: after 100 steps on 200x60, all values stay in [0, maxHeat]', () => {
  const m = createFireModel(200, 60, { seed: 7 });
  for (let i = 0; i < 100; i++) m.step();
  assertInRange(m);
});

test('bottom row after step(): values in [0.7*maxHeat, maxHeat], at least two distinct', () => {
  const m = createFireModel(80, 24, { seed: 11 });
  m.step();
  const bottom = m.grid[m.h - 1];
  for (let x = 0; x < m.w; x++) {
    assert.ok(
      bottom[x] >= 0.7 * m.maxHeat && bottom[x] <= m.maxHeat,
      `bottom[${x}] = ${bottom[x]} not in [${0.7 * m.maxHeat}, ${m.maxHeat}]`
    );
  }
  assert.equal(new Set(bottom).size >= 2, true, 'bottom row should have >= 2 distinct values');
});

test('heat cannot exceed the row below after step()', () => {
  const m = createFireModel(80, 24, { seed: 3 });
  m.step();
  for (let y = 0; y < m.h - 1; y++) {
    const belowMax = Math.max(...m.grid[y + 1]);
    for (let x = 0; x < m.w; x++) {
      assert.ok(
        m.grid[y][x] <= belowMax,
        `grid[${y}][${x}] = ${m.grid[y][x]} exceeds max of row below (${belowMax})`
      );
    }
  }
});

test('monotonic decay: with fixed seed, row averages strictly decrease from bottom to top', () => {
  const m = createFireModel(80, 24, { seed: 42 });
  for (let i = 0; i < 200; i++) m.step();
  for (let y = 0; y < m.h - 1; y++) {
    assert.ok(
      rowAvg(m, y) < rowAvg(m, y + 1),
      `row ${y} avg (${rowAvg(m, y)}) should be < row ${y + 1} avg (${rowAvg(m, y + 1)})`
    );
  }
});

test('stochasticity: different seeds give different grids; consecutive steps change the grid', () => {
  const a = createFireModel(40, 16, { seed: 1 });
  const b = createFireModel(40, 16, { seed: 2 });
  for (let i = 0; i < 10; i++) {
    a.step();
    b.step();
  }
  assert.notDeepStrictEqual(a.grid, b.grid, 'different seeds should produce different grids');

  const c = createFireModel(40, 16, { seed: 5 });
  c.step();
  const before = JSON.stringify(c.grid);
  c.step();
  assert.notEqual(JSON.stringify(c.grid), before, 'consecutive step() calls should change the grid');
});

test('determinism: same seed produces identical grids after 50 steps', () => {
  const a = createFireModel(32, 12, { seed: 1234 });
  const b = createFireModel(32, 12, { seed: 1234 });
  for (let i = 0; i < 50; i++) {
    a.step();
    b.step();
  }
  assert.deepStrictEqual(a.grid, b.grid);
});

test('custom maxHeat (100): all values stay in [0, 100]', () => {
  const m = createFireModel(50, 20, { maxHeat: 100, seed: 99 });
  assert.equal(m.maxHeat, 100);
  for (let i = 0; i < 50; i++) m.step();
  assertInRange(m);
  const bottom = m.grid[m.h - 1];
  for (let x = 0; x < m.w; x++) {
    assert.ok(bottom[x] >= 70 && bottom[x] <= 100, `bottom[${x}] = ${bottom[x]}`);
  }
});

test('boundaries: 3x3, 200x60 and 1x1 grids step without error and stay in range', () => {
  const m1 = createFireModel(3, 3, { seed: 1 });
  for (let i = 0; i < 20; i++) m1.step();
  assertInRange(m1);

  const m2 = createFireModel(200, 60, { seed: 2 });
  for (let i = 0; i < 10; i++) m2.step();
  assertInRange(m2);

  const m3 = createFireModel(1, 1, { seed: 3 });
  for (let i = 0; i < 20; i++) m3.step();
  assertInRange(m3);
});

test('legacy identity (default opts): 1 step matches inline reference implementation', () => {
  const W = 5, H = 5, MAX = 255, SEED = 1, DECAY = 0.08;

  function refXorshift32(seed) {
    let s = (seed >>> 0) || 0x1234567;
    return function () {
      s ^= s << 13;
      s ^= s >>> 17;
      s ^= s << 5;
      return (s >>> 0) / 4294967296;
    };
  }

  const rand = refXorshift32(SEED);
  const DX = [-1, 0, 1];
  const ref = [];
  for (let y = 0; y < H; y++) {
    const row = new Array(W);
    for (let x = 0; x < W; x++) row[x] = 0;
    ref.push(row);
  }

  // One step of the legacy algorithm (double-buffered, old-state reads).
  {
    const next = [];
    for (let y = 0; y < H; y++) {
      const row = new Array(W);
      for (let x = 0; x < W; x++) row[x] = 0;
      next.push(row);
    }
    for (let x = 0; x < W; x++) next[H - 1][x] = MAX * (0.7 + 0.3 * rand());
    for (let y = H - 2; y >= 0; y--) {
      const belowRow = ref[y + 1];
      for (let x = 0; x < W; x++) {
        const dx = DX[Math.floor(rand() * 3)];
        let nx = x + dx;
        if (nx < 0) nx = 0;
        else if (nx > W - 1) nx = W - 1;
        const below = belowRow[nx];
        let v = below - DECAY * rand() * MAX;
        if (v < 0) v = 0;
        else if (v > MAX) v = MAX;
        next[y][x] = v;
      }
    }
    for (let y = 0; y < H; y++) ref[y] = next[y];
  }

  const m = createFireModel(W, H, { seed: SEED });
  m.step();
  assert.deepStrictEqual(m.grid, ref);
});

test('determinism with new opts: same seed + opts give identical grids after 50 steps', () => {
  const a = createFireModel(24, 16, { seed: 2024, inertia: 0.5, turbulence: 0.5 });
  const b = createFireModel(24, 16, { seed: 2024, inertia: 0.5, turbulence: 0.5 });
  for (let i = 0; i < 50; i++) {
    a.step();
    b.step();
  }
  assert.deepStrictEqual(a.grid, b.grid);
});

test('range with new opts: all values stay in [0, maxHeat] after 100 steps', () => {
  const m = createFireModel(24, 16, { seed: 31, inertia: 0.5, turbulence: 0.5 });
  for (let i = 0; i < 100; i++) m.step();
  assertInRange(m);
});

test('inertia smooths frame-to-frame change', () => {
  function meanDelta(model, warmup, frames) {
    for (let i = 0; i < warmup; i++) model.step();
    const W = model.w, H = model.h;
    let total = 0, count = 0;
    let prev = model.grid.map((r) => r.slice());
    for (let i = 0; i < frames; i++) {
      model.step();
      const cur = model.grid;
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          total += Math.abs(cur[y][x] - prev[y][x]);
          count++;
        }
      }
      prev = cur.map((r) => r.slice());
    }
    return total / count;
  }
  const a = createFireModel(40, 24, { seed: 123, inertia: 0, turbulence: 0 });
  const b = createFireModel(40, 24, { seed: 123, inertia: 0.5, turbulence: 0 });
  const dA = meanDelta(a, 200, 50);
  const dB = meanDelta(b, 200, 50);
  assert.ok(dB < dA, `meanDelta(B)=${dB} should be < meanDelta(A)=${dA}`);
});

test('turbulence extends the flame upward', () => {
  function topThirdMax(model) {
    const { grid, w, h } = model;
    const top = Math.floor(h / 3);
    let max = 0;
    for (let y = 0; y < top; y++) {
      for (let x = 0; x < w; x++) {
        if (grid[y][x] > max) max = grid[y][x];
      }
    }
    return max;
  }
  const a = createFireModel(40, 24, { seed: 77, turbulence: 0, inertia: 0 });
  const b = createFireModel(40, 24, { seed: 77, turbulence: 0.5, inertia: 0 });
  for (let i = 0; i < 200; i++) {
    a.step();
    b.step();
  }
  const mA = topThirdMax(a);
  const mB = topThirdMax(b);
  assert.ok(mB > mA, `topThirdMax(B)=${mB} should be > topThirdMax(A)=${mA}`);
  assert.ok(mB > 0, `topThirdMax(B)=${mB} should be > 0`);
});

test('invalid inertia/turbulence opts throw TypeError', () => {
  const bad = [
    { inertia: 1.0 },
    { inertia: -0.1 },
    { inertia: 'x' },
    { turbulence: 1.5 },
    { turbulence: -0.1 },
    { turbulence: null },
  ];
  for (const o of bad) {
    assert.throws(
      () => createFireModel(10, 10, o),
      TypeError,
      `opts ${JSON.stringify(o)} should throw TypeError`
    );
  }
});

test('throws TypeError for invalid w or h', () => {
  const bad = [
    [0, 24],
    [80, 0],
    [-5, 24],
    [80.5, 24],
    ['80', 24],
    [null, 24],
    [undefined, 24],
  ];
  for (const [w, h] of bad) {
    assert.throws(
      () => createFireModel(w, h),
      TypeError,
      `createFireModel(${String(w)}, ${String(h)}) should throw TypeError`
    );
  }
});

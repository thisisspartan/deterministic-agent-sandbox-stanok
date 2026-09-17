'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');

const { createModel, step, renderFrame, MAX_HEAT } = require('../src/fire.js');

test('createModel returns grid of zeros with correct shape', () => {
  const model = createModel(10, 6, 42);
  assert.equal(model.cols, 10);
  assert.equal(model.rows, 6);
  assert.equal(model.grid.length, 6);
  for (const row of model.grid) {
    assert.equal(row.length, 10);
    for (const cell of row) assert.equal(cell, 0);
  }
  assert.equal(typeof model.rand, 'function');
});

test('determinism: same seed gives identical grids after 5 steps', () => {
  const a = createModel(12, 8, 7);
  const b = createModel(12, 8, 7);
  for (let i = 0; i < 5; i++) {
    step(a);
    step(b);
  }
  assert.deepEqual(a.grid, b.grid);
});

test('different seeds produce different grids', () => {
  const a = createModel(12, 8, 1);
  const b = createModel(12, 8, 2);
  for (let i = 0; i < 5; i++) {
    step(a);
    step(b);
  }
  assert.notDeepEqual(a.grid, b.grid);
});

test('clamp: after 50 steps every cell is an integer in 0..255', () => {
  const model = createModel(15, 10, 99);
  for (let i = 0; i < 50; i++) step(model);
  for (const row of model.grid) {
    for (const cell of row) {
      assert.equal(Number.isInteger(cell), true);
      assert.ok(cell >= 0 && cell <= MAX_HEAT, `cell ${cell} out of range`);
    }
  }
});

test('decay: an isolated hot cell cools toward 0', () => {
  const model = createModel(9, 9, 123);
  model.grid[4][4] = 255; // interior hot cell
  const seen = [];
  for (let i = 0; i < 10; i++) {
    step(model);
    // isolate the tracked cell: zero all other cells (including the
    // refilled bottom row) so only the cell's own heat carries forward
    for (let y = 0; y < model.rows; y++) {
      for (let x = 0; x < model.cols; x++) {
        if (!(y === 4 && x === 4)) model.grid[y][x] = 0;
      }
    }
    seen.push(model.grid[4][4]);
  }
  assert.ok(seen[0] < 255, `first step must cool the cell: ${seen[0]}`);
  for (let i = 1; i < seen.length; i++) {
    assert.ok(seen[i] <= seen[i - 1], `heat must not rise: ${seen.join(',')}`);
  }
  assert.equal(seen[seen.length - 1], 0, `heat must reach 0: ${seen.join(',')}`);
});

test('bottom row is refilled with rand() each step', () => {
  const model = createModel(6, 4, 5);
  step(model);
  for (let x = 0; x < 6; x++) {
    assert.ok(Number.isInteger(model.grid[3][x]) && model.grid[3][x] >= 0 && model.grid[3][x] <= 255);
  }
});

test('renderer: rows strings, each exactly cols cells of \\x1b[38;5;<n>m█', () => {
  const model = createModel(10, 5, 42);
  for (let i = 0; i < 3; i++) step(model);
  const frame = renderFrame(model);
  assert.ok(Array.isArray(frame));
  assert.equal(frame.length, 5);
  for (const line of frame) {
    assert.equal(typeof line, 'string');
    assert.equal(line.includes('\n'), false, 'no trailing/inner newlines');
    const cells = line.match(/\x1b\[38;5;\d+m█/g);
    assert.ok(cells, 'no cells matched');
    assert.equal(cells.length, 10);
    // every character belongs to a valid cell
    assert.equal(line.replace(/\x1b\[38;5;\d+m█/g, ''), '', `stray chars: ${JSON.stringify(line)}`);
    for (const cell of cells) {
      assert.match(cell, /^\x1b\[38;5;\d+m█$/);
      const idx = parseInt(cell.match(/^\x1b\[38;5;(\d+)m█$/)[1], 10);
      assert.ok(idx >= 0 && idx <= 255, `color index ${idx} out of range`);
    }
  }
});

test('renderer: heat 0 maps to color 0, monotonic mapping covers full ramp', () => {
  const model = createModel(4, 4, 42);
  const cellIdx = (line) =>
    line.match(/\x1b\[38;5;(\d+)m█/g).map((c) => parseInt(c.match(/^\x1b\[38;5;(\d+)m█$/)[1], 10));

  const cold = renderFrame(model);
  assert.deepEqual(cellIdx(cold[0]), [0, 0, 0, 0]);

  const hot = createModel(4, 4, 42);
  for (const row of hot.grid) row.fill(255);
  const hotFrame = renderFrame(hot);
  assert.equal(cellIdx(hotFrame[0])[0], 255);

  // monotonic: build a ramp grid and verify non-decreasing indices
  const rampModel = createModel(8, 1, 42);
  for (let x = 0; x < 8; x++) rampModel.grid[0][x] = x * 32; // 0..224
  const rampFrame = renderFrame(rampModel);
  const rampIdx = cellIdx(rampFrame[0]);
  for (let x = 1; x < 8; x++) {
    assert.ok(rampIdx[x] >= rampIdx[x - 1], `not monotonic at ${x}: ${rampIdx.join(',')}`);
  }
  assert.ok(rampIdx[7] > rampIdx[0], 'ramp does not spread across colors');
});

test('step: heat rises above bottom row over time (fire spreads upward)', () => {
  const model = createModel(8, 8, 42);
  for (let i = 0; i < 15; i++) step(model);
  // at least one cell above the bottom row should be lit
  let lit = false;
  for (let y = 0; y < model.rows - 1; y++) {
    if (model.grid[y].some((c) => c > 0)) lit = true;
  }
  assert.ok(lit, 'no heat above the bottom row');
});

'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { newBoard, inBounds, isFullRow, lock, clearLines } = require('../../src/tetris/board.js');

// --- newBoard ---

test('newBoard: 22 rows x 10 cols, all zeros', () => {
  const { grid } = newBoard();
  assert.strictEqual(grid.length, 22);
  for (const row of grid) {
    assert.strictEqual(row.length, 10);
    for (const v of row) assert.strictEqual(v, 0);
  }
});

test('newBoard: rows are independent (no shared references)', () => {
  const { grid } = newBoard();
  grid[0][0] = 7;
  assert.strictEqual(grid[1][0], 0);
});

// --- inBounds ---

test('inBounds: out-of-bounds corners are false', () => {
  assert.strictEqual(inBounds(-1, 0), false);
  assert.strictEqual(inBounds(10, 0), false);
  assert.strictEqual(inBounds(0, -1), false);
  assert.strictEqual(inBounds(0, 22), false);
  assert.strictEqual(inBounds(9, -1), false);
  assert.strictEqual(inBounds(9, 22), false);
});

test('inBounds: valid corners are true', () => {
  assert.strictEqual(inBounds(0, 0), true);
  assert.strictEqual(inBounds(9, 21), true);
  assert.strictEqual(inBounds(5, 10), true);
});

// --- isFullRow ---

test('isFullRow: empty row is false', () => {
  const { grid } = newBoard();
  assert.strictEqual(isFullRow(grid, 0), false);
});

test('isFullRow: partially filled row is false', () => {
  const { grid } = newBoard();
  grid[5].fill(1);
  grid[5][3] = 0;
  assert.strictEqual(isFullRow(grid, 5), false);
});

test('isFullRow: fully occupied row is true', () => {
  const { grid } = newBoard();
  grid[5].fill(2);
  assert.strictEqual(isFullRow(grid, 5), true);
});

// --- clearLines ---

test('clearLines: no full rows -> n=0, board unchanged', () => {
  const { grid } = newBoard();
  grid[21].fill(1);
  grid[21][4] = 0;
  const before = grid.map(r => r.slice());
  const { board, n } = clearLines(grid);
  assert.strictEqual(n, 0);
  assert.deepStrictEqual(board, before);
});

test('clearLines: four full rows (tetris) -> n=4, board empties', () => {
  const { grid } = newBoard();
  for (const r of [18, 19, 20, 21]) grid[r].fill(3);
  const { board, n } = clearLines(grid);
  assert.strictEqual(n, 4);
  for (const row of board) assert.ok(row.every(v => v === 0));
});

test('clearLines: cells above a cleared row shift down by n', () => {
  const { grid } = newBoard();
  grid[19].fill(1); // full row
  grid[17][2] = 5; // cell above
  const { board, n } = clearLines(grid);
  assert.strictEqual(n, 1);
  // old row 17 becomes row 18
  assert.strictEqual(board[18][2], 5);
  // nothing is left at the old position
  assert.strictEqual(board[17][2], 0);
});

test('clearLines: does not mutate the input grid', () => {
  const { grid } = newBoard();
  grid[21].fill(4);
  const before = grid.map(r => r.slice());
  clearLines(grid);
  assert.deepStrictEqual(grid, before);
});

// --- lock ---

test('lock: piece at bottom writes its cells into the grid', () => {
  const { grid } = newBoard();
  // O state A anchored at (0,20): absolute cells (1,20),(2,20),(1,21),(2,21)
  const { board, clearedRows } = lock(grid, 'O', 'A', 0, 20);
  assert.strictEqual(clearedRows, 0);
  assert.deepStrictEqual(board[20].slice(0, 3), [0, 2, 2]);
  assert.deepStrictEqual(board[21].slice(0, 3), [0, 2, 2]);
  const expected = grid.map(r => r.slice());
  for (const [c, r] of [[1, 20], [2, 20], [1, 21], [2, 21]]) expected[r][c] = 2;
  assert.deepStrictEqual(board, expected);
});

test('lock: full row is cleared, clearedRows=1, top row empty after clear', () => {
  const { grid } = newBoard();
  // row 21 has cols 4 and 5 free (the O's landing cells)
  for (const c of [0, 1, 2, 3, 6, 7, 8, 9]) grid[21][c] = 2;
  // O state A anchored at (3,20): cells (4,20),(5,20),(4,21),(5,21)
  // -> completes row 21 (fills free cols 4,5), the row clears
  const { board, clearedRows } = lock(grid, 'O', 'A', 3, 20);
  assert.strictEqual(clearedRows, 1);
  assert.strictEqual(board[0].every(v => v === 0), true, 'top row must be empty after clear');
  assert.ok(board[0].every(v => v === 0), 'top row must stay empty');
  // O top half sat on old row 20 -> shifts down to row 21
  assert.strictEqual(board[21][4], 2);
  assert.strictEqual(board[21][5], 2);
  assert.ok(board[20].every(v => v === 0));
});

test('lock: lock-out — piece locked in rows 0-1 lands those cells in grid', () => {
  const { grid } = newBoard();
  // T state A anchored at (0,0): absolute cells (1,0),(0,1),(1,1),(2,1)
  const { board, clearedRows } = lock(grid, 'T', 'A', 0, 0);
  assert.strictEqual(clearedRows, 0);
  assert.strictEqual(board[0][1], 3);
  assert.strictEqual(board[1][0], 3);
  assert.strictEqual(board[1][1], 3);
  assert.strictEqual(board[1][2], 3);
});

test('lock: cells above a cleared row shift down by n', () => {
  const { grid } = newBoard();
  grid[19].fill(1); // full row
  grid[17][2] = 5; // cell above
  // O state A anchored at (3,17): cells (4,17),(5,17),(4,18),(5,18)
  const { board, clearedRows } = lock(grid, 'O', 'A', 3, 17);
  assert.strictEqual(clearedRows, 1);
  // old row 17 content lands on row 18
  assert.strictEqual(board[18][2], 5);
  assert.strictEqual(board[18][4], 2);
  assert.strictEqual(board[18][5], 2);
  assert.strictEqual(board[17][2], 0);
  assert.strictEqual(board[17][4], 0);
});

test('lock: does not mutate the input grid', () => {
  const { grid } = newBoard();
  const before = grid.map(r => r.slice());
  lock(grid, 'O', 'A', 0, 20);
  assert.deepStrictEqual(grid, before);
});

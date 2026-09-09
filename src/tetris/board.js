'use strict';

// Tetris board: 10x22 cell grid, line clearing, piece locking. Pure module
// (no IO, no timers, no Date, no import of pieces.js — the layout table is
// duplicated here on purpose so the board depends on no other module).
//
// Grid convention: grid[row][col], row 0 = top (hidden), row 21 = bottom;
// 0 = empty, >0 = occupied (value = piece id, used for color).

const ROWS = 22;
const COLS = 10;

// Cell layouts relative to the piece anchor [col, row], col+ = right,
// row+ = down. Same data as pieces.js (state A pinned to the spec absolute
// cells, anchor offset (3,0)); kept local so board.js imports nothing.
const PIECES = {
  I: {
    A: [[0, 0], [1, 0], [2, 0], [3, 0]],
    R: [[1, -1], [1, 0], [1, 1], [1, 2]],
    D: [[-1, 1], [0, 1], [1, 1], [2, 1]],
    L: [[1, -1], [1, 0], [1, 1], [1, 2]],
  },
  O: {
    A: [[1, 0], [2, 0], [1, 1], [2, 1]],
    R: [[1, 0], [2, 0], [1, 1], [2, 1]],
    D: [[1, 0], [2, 0], [1, 1], [2, 1]],
    L: [[1, 0], [2, 0], [1, 1], [2, 1]],
  },
  T: {
    A: [[0, 1], [1, 1], [2, 1], [1, 0]],
    R: [[1, 0], [1, 1], [1, 2], [0, 1]],
    D: [[0, 0], [1, 0], [2, 0], [1, 1]],
    L: [[1, 0], [1, 1], [1, 2], [2, 1]],
  },
  S: {
    A: [[0, 0], [1, 0], [1, 1], [2, 1]],
    R: [[1, -1], [1, 0], [2, 0], [2, 1]],
    D: [[0, 0], [1, 0], [1, -1], [2, -1]],
    L: [[-1, 0], [0, 0], [0, 1], [1, 1]],
  },
  Z: {
    A: [[1, 0], [2, 0], [0, 1], [1, 1]],
    R: [[0, -1], [0, 0], [1, 0], [1, 1]],
    D: [[-1, 0], [0, 0], [0, 1], [1, 1]],
    L: [[0, 0], [1, 0], [1, 1], [2, 1]],
  },
  J: {
    A: [[0, 0], [0, 1], [1, 1], [2, 1]],
    R: [[1, -1], [1, 0], [1, 1], [0, 1]],
    D: [[0, 0], [1, 0], [2, 0], [0, 1]],
    L: [[0, -1], [0, 0], [1, 0], [2, 0]],
  },
  L: {
    A: [[2, 0], [0, 1], [1, 1], [2, 1]],
    R: [[0, -1], [1, -1], [1, 0], [1, 1]],
    D: [[-1, 1], [0, 1], [1, 1], [2, 1]],
    L: [[0, 0], [0, 1], [0, 2], [1, 2]],
  },
};

// Fresh board: 22 rows x 10 cols, all 0, independent row arrays.
function newBoard() {
  const grid = Array.from({ length: ROWS }, () => Array(COLS).fill(0));
  return { grid };
}

// Board bounds: 0 <= col < 10 and 0 <= row < 22.
function inBounds(col, row) {
  return col >= 0 && col < COLS && row >= 0 && row < ROWS;
}

// A row is full when all 10 cells are occupied (non-zero).
function isFullRow(grid, row) {
  const r = grid[row];
  for (let c = 0; c < COLS; c++) {
    if (!r[c]) return false;
  }
  return true;
}

// Absolute [col, row] cells of a placement; hidden rows (row < 0) are
// excluded — they do not exist in the grid.
function cellsOf(piece, state, col, row) {
  const out = [];
  for (const [dc, dr] of PIECES[piece][state]) {
    const c = col + dc;
    const r = row + dr;
    if (r >= 0) out.push([c, r]);
  }
  return out;
}

// Remove every full row, drop the rows above them down, pad the top with
// empty rows. Pure: returns a new grid, input untouched.
function clearLines(grid) {
  let n = 0;
  for (let r = 0; r < ROWS; r++) {
    if (isFullRow(grid, r)) n++;
  }
  if (n === 0) return { board: grid, n: 0 };
  const kept = [];
  for (let r = 0; r < ROWS; r++) {
    if (!isFullRow(grid, r)) kept.push(grid[r]);
  }
  const board = Array.from({ length: n }, () => Array(COLS).fill(0)).concat(kept);
  return { board, n };
}

// Piece name -> numeric id (canonical ordering, used for color).
const PIECE_ID = { I: 1, O: 2, T: 3, S: 4, Z: 5, J: 6, L: 7 };

// Freeze a piece into the grid (cell value = piece id), then clear full
// rows. Returns { board, clearedRows }; a new grid, input untouched.
// Score/level/lines are not touched (that is game.js, ticket 021).
function lock(grid, piece, state, col, row) {
  const next = grid.map(r => r.slice());
  const id = PIECE_ID[piece];
  for (const [c, r] of cellsOf(piece, state, col, row)) {
    next[r][c] = id;
  }
  const { board, n } = clearLines(next);
  return { board, clearedRows: n };
}

module.exports = { newBoard, inBounds, isFullRow, clearLines, lock, ROWS, COLS };

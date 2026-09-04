'use strict';

// Tetris pieces: 7 tetrominoes, SRS states, SRS kick tables, collision and
// rotation with wall kicks. Pure module (no IO, no timers, no Date).
//
// Cell coordinates are relative to the piece anchor: [col, row], col+ = right,
// row+ = down. Board is 10 columns wide (col 0..9), 22 visible rows (row 0..21);
// rows above 0 (row < 0) are hidden spawn rows and never collide.

// Spawn state A is pinned to the spec absolute cells; the anchor offset for A
// is (3,0) for every piece, so relative A cells are absolute - (3,0).
// R/D/L are the canonical SRS rotations of the same tetromino.
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

// Spawn positions: SPAWN[p].col/.row are the anchor offset applied to state A
// so that the absolute cells match the spec (spawn row 0, board columns 0..9).
const SPAWN = {
  I: { piece: 'I', col: 3, row: 0 },
  O: { piece: 'O', col: 3, row: 0 },
  T: { piece: 'T', col: 3, row: 0 },
  S: { piece: 'S', col: 3, row: 0 },
  Z: { piece: 'Z', col: 3, row: 0 },
  J: { piece: 'J', col: 3, row: 0 },
  L: { piece: 'L', col: 3, row: 0 },
};

// SRS kick tables as plain numbers [dCol, dRow], in trial order.
const KICKS = {
  JLSTZ: {
    A: {
      R: [[0, 0], [0, -1], [-1, 0], [0, 2], [0, 3]],
      L: [[0, 0], [1, 0], [1, -1], [0, 2], [0, 3]],
      D: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
    },
    R: {
      A: [[0, 0], [0, 1], [1, 0], [0, 2], [0, 3]],
      L: [[0, 0], [0, 1], [1, 0], [0, -2], [0, -3]],
      D: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
    },
    D: {
      A: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
      R: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
      L: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
    },
    L: {
      A: [[0, 0], [-1, 0], [-1, 1], [0, 2], [0, 3]],
      R: [[0, 0], [0, -1], [-1, 0], [0, 2], [0, 3]],
      D: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
    },
  },
  I: {
    A: {
      R: [[0, 0], [-1, 0], [-1, 1], [-1, -2], [-1, 0]],
      D: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
      L: [[0, 0], [1, 0], [1, -1], [1, 2], [1, 0]],
    },
    R: {
      A: [[0, 0], [1, 0], [1, -1], [1, 2], [1, 0]],
      D: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
      L: [[0, 0], [-1, 0], [-1, -1], [-1, 2], [-1, 0]],
    },
    D: {
      A: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
      R: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
      L: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
    },
    L: {
      A: [[0, 0], [-1, 0], [-1, 1], [-1, -2], [-1, 0]],
      R: [[0, 0], [1, 0], [1, -1], [1, 2], [1, 0]],
      D: [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]],
    },
  },
  O: {
    A: { R: [[0, 0]], D: [[0, 0]], L: [[0, 0]] },
    R: { A: [[0, 0]], D: [[0, 0]], L: [[0, 0]] },
    D: { A: [[0, 0]], R: [[0, 0]], L: [[0, 0]] },
    L: { A: [[0, 0]], R: [[0, 0]], D: [[0, 0]] },
  },
};

const STATES = ['A', 'R', 'D', 'L'];

// O rotation is a no-op; make KICKS.O lookup total (all 16 from/to pairs
// including the diagonal) so every transition reads (0,0).
for (const s of STATES) {
  KICKS.O[s][s] = [[0, 0]];
}

const CW = { A: 'R', R: 'D', D: 'L', L: 'A' };
const CCW = { A: 'L', L: 'D', D: 'R', R: 'A' };

// True if any cell of (piece,state) placed at anchor (col,row) is out of bounds
// (col < 0, col > 9, row > 21) or on an occupied cell. row < 0 is allowed
// (hidden rows above the board).
function collides(board, piece, state, col, row) {
  const cells = PIECES[piece][state];
  for (const [dc, dr] of cells) {
    const c = col + dc;
    const r = row + dr;
    if (c < 0 || c > 9 || r > 21) return true;
    if (r >= 0 && board[r] && board[r][c]) return true;
  }
  return false;
}

// Rotate a piece CW or CCW around its anchor, trying the SRS kick table in
// order. Returns { piece, state, col, row, kick } or null when every kick
// candidate collides. The O piece is a no-op: state unchanged, kick (0,0).
function rotate(piece, fromState, dir, board, col, row) {
  if (piece === 'O') {
    // O is a 2x2 square: rotation is a no-op, state unchanged, kick (0,0).
    return { piece: 'O', state: fromState, col, row, kick: [0, 0] };
  }
  const newState = dir === 'CW' ? CW[fromState] : CCW[fromState];
  const table = piece === 'I' ? KICKS.I : KICKS.JLSTZ;
  const kicks = table[fromState][newState];
  for (const kick of kicks) {
    const nc = col + kick[0];
    const nr = row + kick[1];
    if (!collides(board, piece, newState, nc, nr)) {
      return { piece, state: newState, col: nc, row: nr, kick };
    }
  }
  return null;
}

module.exports = { PIECES, SPAWN, KICKS, collides, rotate };

'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { PIECES, SPAWN, KICKS, collides, rotate } = require('../../src/tetris/pieces.js');

const NAMES = ['I', 'O', 'T', 'S', 'Z', 'J', 'L'];
const STATES = ['A', 'R', 'D', 'L'];

// Absolute cells of the spawn state A for every piece (spec п.3).
const EXPECTED_SPAWN = {
  I: [[3, 0], [4, 0], [5, 0], [6, 0]],
  O: [[4, 0], [5, 0], [4, 1], [5, 1]],
  T: [[3, 1], [4, 1], [5, 1], [4, 0]],
  S: [[3, 0], [4, 0], [4, 1], [5, 1]],
  Z: [[4, 0], [5, 0], [3, 1], [4, 1]],
  J: [[3, 0], [3, 1], [4, 1], [5, 1]],
  L: [[5, 0], [3, 1], [4, 1], [5, 1]],
};

function emptyBoard() {
  // 22 rows x 10 cols, 0 = empty
  return Array.from({ length: 22 }, () => Array(10).fill(0));
}

function cells(pieceName, state) {
  return PIECES[pieceName][state].map(([c, r]) => [c, r]);
}

// --- PIECES structure ---

test('PIECES has exactly the 7 tetrominoes', () => {
  assert.deepStrictEqual(Object.keys(PIECES).sort(), [...NAMES].sort());
});

test('every piece has 4 SRS states with 4 cells each', () => {
  for (const name of NAMES) {
    for (const state of STATES) {
      const cs = PIECES[name][state];
      assert.strictEqual(cs.length, 4, `${name}.${state} must have 4 cells`);
      for (const cell of cs) {
        assert.strictEqual(cell.length, 2, `${name}.${state} cell arity`);
        assert.ok(Number.isInteger(cell[0]) && Number.isInteger(cell[1]),
          `${name}.${state} cell must be integer [col,row]`);
      }
    }
  }
});

test('every state has unique cells within reasonable bounds (col -2..9, row -1..8)', () => {
  for (const name of NAMES) {
    for (const state of STATES) {
      const seen = new Set();
      for (const [c, r] of PIECES[name][state]) {
        assert.ok(c >= -2 && c <= 9 && r >= -1 && r <= 8,
          `${name}.${state} cell [${c},${r}] out of reasonable bounds`);
        const key = `${c},${r}`;
        assert.ok(!seen.has(key), `${name}.${state} duplicate cell [${c},${r}]`);
        seen.add(key);
      }
    }
  }
});

// --- Spawn: SPAWN + PIECES[p].A must give exactly the absolute cells of п.3 ---

test('SPAWN[p] + PIECES[p].A gives exactly the spec absolute cells for all 7 pieces', () => {
  for (const name of NAMES) {
    const abs = cells(name, 'A')
      .map(([c, r]) => [c + SPAWN[name].col, r + SPAWN[name].row])
      .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const expected = [...EXPECTED_SPAWN[name]].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    assert.deepStrictEqual(abs, expected, `spawn cells mismatch for ${name}`);
  }
});

// --- collides ---

test('collides: empty board, free position -> false', () => {
  assert.strictEqual(collides(emptyBoard(), 'T', 'A', 3, 0), false);
});

test('collides: left wall (col < 0) -> true', () => {
  assert.strictEqual(collides(emptyBoard(), 'T', 'A', 1, 0), true);
});

test('collides: right wall (col > 9) -> true', () => {
  assert.strictEqual(collides(emptyBoard(), 'T', 'A', 6, 0), true);
});

test('collides: floor (row > 21) -> true', () => {
  assert.strictEqual(collides(emptyBoard(), 'T', 'A', 3, 21), true);
});

test('collides: occupied cell -> true', () => {
  const board = emptyBoard();
  board[2][4] = 'T';
  assert.strictEqual(collides(board, 'T', 'A', 3, 0), true);
});

test('collides: hidden rows above the grid (row < 0) -> false', () => {
  assert.strictEqual(collides(emptyBoard(), 'I', 'A', 3, -2), false);
  assert.strictEqual(collides(emptyBoard(), 'I', 'A', 3, -1), false);
});

// --- rotate: CW cycle A->R->D->L->A (empty board, no kicks needed) ---

test('rotate CW on T cycles A->R->D->L->A', () => {
  let r = rotate('T', 'A', 'CW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'R');
  r = rotate('T', 'R', 'CW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'D');
  r = rotate('T', 'D', 'CW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'L');
  r = rotate('T', 'L', 'CW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'A');
});

test('rotate CW on I cycles A->R->D->L->A', () => {
  let r = rotate('I', 'A', 'CW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'R');
  r = rotate('I', 'R', 'CW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'D');
  r = rotate('I', 'D', 'CW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'L');
  r = rotate('I', 'L', 'CW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'A');
});

test('rotate CCW on T cycles A->L->D->R->A', () => {
  let r = rotate('T', 'A', 'CCW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'L');
  r = rotate('T', 'L', 'CCW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'D');
  r = rotate('T', 'D', 'CCW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'R');
  r = rotate('T', 'R', 'CCW', emptyBoard(), 3, 0);
  assert.strictEqual(r.state, 'A');
});

// --- rotate: wall-kick ---

test('rotate wall-kick: T at the left wall A->R applies a non-(0,0) kick', () => {
  // T A at anchor (1,0): absolute cells (4,1),(5,1),(6,1),(5,0).
  // T R (JLSTZ relative cells (0,-1),(0,0),(0,1),(-1,0)) at anchor (1,0)
  // would put a cell at col -1 -> out of bounds, so (0,0) collides.
  const board = emptyBoard();
  board[0][5] = 'X'; // block the +1 column kick
  const res = rotate('T', 'A', 'CW', board, 1, 0);
  assert.ok(res !== null, 'rotation should succeed via a wall kick');
  assert.notDeepStrictEqual(res.kick, [0, 0], 'expected a non-(0,0) kick at the left wall');
  assert.strictEqual(res.state, 'R');
  assert.deepStrictEqual([res.col, res.row], [1 + res.kick[0], 0 + res.kick[1]]);
});

// --- rotate: rejected when every kick collides ---

test('rotate is rejected (null) when the piece sits in a hole where every kick collides', () => {
  // T A anchored at (5,20): absolute cells (8,21),(9,21),(10,21),(9,20) — col 10 is OOB,
  // so no valid anchor exists, and a rotation from here must be rejected.
  const board = emptyBoard();
  for (const col of [8, 9, 10, 11, 12]) board[21][col] = 'X';
  assert.strictEqual(rotate('T', 'A', 'CW', board, 5, 20), null);
});

// --- rotate: O is a no-op ---

test('rotate on O keeps the state and applies kick (0,0)', () => {
  const res = rotate('O', 'A', 'CW', emptyBoard(), 4, 0);
  assert.strictEqual(res.state, 'A');
  assert.deepStrictEqual(res.kick, [0, 0]);
  assert.strictEqual(res.piece, 'O');
  assert.strictEqual(res.col, 4);
  assert.strictEqual(res.row, 0);
});

// --- KICKS tables ---

test('KICKS.O is only (0,0) for all transitions', () => {
  for (const from of STATES) {
    for (const to of STATES) {
      assert.deepStrictEqual(KICKS.O[from][to], [[0, 0]]);
    }
  }
});

test('KICKS.I is the standard SRS I-piece table (not JLSTZ)', () => {
  assert.deepStrictEqual(KICKS.I.A.R, [[0, 0], [-1, 0], [-1, 1], [-1, -2], [-1, 0]]);
  assert.deepStrictEqual(KICKS.I.R.A, [[0, 0], [1, 0], [1, -1], [1, 2], [1, 0]]);
  assert.deepStrictEqual(KICKS.I.A.L, [[0, 0], [1, 0], [1, -1], [1, 2], [1, 0]]);
  assert.deepStrictEqual(KICKS.I.L.A, [[0, 0], [-1, 0], [-1, 1], [-1, -2], [-1, 0]]);
  assert.notDeepStrictEqual(KICKS.I, KICKS.JLSTZ);
});

test('KICKS.JLSTZ is the standard JLSTZ SRS table', () => {
  assert.deepStrictEqual(KICKS.JLSTZ.A.R, [[0, 0], [0, -1], [-1, 0], [0, 2], [0, 3]]);
  assert.deepStrictEqual(KICKS.JLSTZ.R.A, [[0, 0], [0, 1], [1, 0], [0, 2], [0, 3]]);
  assert.deepStrictEqual(KICKS.JLSTZ.R.L, [[0, 0], [0, 1], [1, 0], [0, -2], [0, -3]]);
  assert.deepStrictEqual(KICKS.JLSTZ.L.R, [[0, 0], [0, -1], [-1, 0], [0, 2], [0, 3]]);
});

test('I rotation uses the I kick table (kick ordering observable via rejection)', () => {
  // I in state R (vertical bar, relative cells (1,-1)..(1,2)) anchored at col 0:
  // absolute column 1 — valid, wall to the left. Rotate CW R->D with the I table.
  // KICKS.I.R.D = [0,0],[-2,0],[-1,0],[-2,1],[-2,-2]; D bar has min rel col -1.
  // [0,0] collides (cell at col -1), [-2,0] collides (cell at col -3), [-1,0] valid.
  // The (wrong) JLSTZ R->D table [0,0],[0,-1],[1,0],[0,-2],[0,-3] would instead
  // apply [0,-1] — so the applied kick proves the I table was used.
  const board = emptyBoard();
  const res = rotate('I', 'R', 'CW', board, 0, 5);
  assert.ok(res !== null);
  assert.deepStrictEqual(res.kick, [-1, 0]);
  assert.strictEqual(res.state, 'D');
});

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
    const abs = PIECES[name].A
      .map(([c, r]) => [c + SPAWN[name].col, r + SPAWN[name].row])
      .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const expected = [...EXPECTED_SPAWN[name]].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    assert.deepStrictEqual(abs, expected, `spawn cells mismatch for ${name}`);
  }
});

// --- SRS rotation states (relative cells, canonical SRS per tetris.wiki) ---

test('I piece SRS states match canonical SRS geometry', () => {
  assert.deepStrictEqual(PIECES.I.A, [[0, 0], [1, 0], [2, 0], [3, 0]]);
  assert.deepStrictEqual(PIECES.I.R, [[1, -1], [1, 0], [1, 1], [1, 2]]);
  assert.deepStrictEqual(PIECES.I.D, [[-1, 1], [0, 1], [1, 1], [2, 1]]);
  assert.deepStrictEqual(PIECES.I.L, [[1, -1], [1, 0], [1, 1], [1, 2]]);
});

test('T piece SRS states match canonical SRS geometry', () => {
  assert.deepStrictEqual(PIECES.T.A, [[0, 1], [1, 1], [2, 1], [1, 0]]);
  assert.deepStrictEqual(PIECES.T.R, [[1, 0], [1, 1], [1, 2], [0, 1]]);
  assert.deepStrictEqual(PIECES.T.D, [[0, 0], [1, 0], [2, 0], [1, 1]]);
  assert.deepStrictEqual(PIECES.T.L, [[1, 0], [1, 1], [1, 2], [2, 1]]);
});

test('O piece is a fixed 2x2 square in all four states', () => {
  for (const state of STATES) {
    assert.deepStrictEqual(PIECES.O[state], [[1, 0], [2, 0], [1, 1], [2, 1]]);
  }
});

// --- collides ---

test('collides: empty board, free position -> false', () => {
  assert.strictEqual(collides(emptyBoard(), 'T', 'A', 3, 0), false);
});

test('collides: left wall (col < 0) -> true', () => {
  assert.strictEqual(collides(emptyBoard(), 'T', 'A', -1, 0), true);
});

test('collides: right wall (col > 9) -> true', () => {
  assert.strictEqual(collides(emptyBoard(), 'T', 'A', 8, 0), true);
});

test('collides: floor (row > 21) -> true', () => {
  assert.strictEqual(collides(emptyBoard(), 'T', 'A', 3, 21), true);
});

test('collides: occupied cell -> true', () => {
  const board = emptyBoard();
  board[1][4] = 'T';
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
  // T A anchored at (0,0): absolute cells (0,1),(1,1),(2,1),(1,0) — touching the
  // left wall, all in bounds, so the spawn position itself is valid.
  // T R relative cells (1,0),(1,1),(1,2),(0,1): at anchor (0,0) all in bounds,
  // but board[1][1] is occupied below -> (0,0) collides; the JLSTZ A->R table
  // then applies the first non-zero kick that clears it.
  const board = emptyBoard();
  board[1][1] = 'X'; // block the (0,0) candidate cell (anchor col + rel col 1)
  const res = rotate('T', 'A', 'CW', board, 0, 0);
  assert.ok(res !== null, 'rotation should succeed via a wall kick');
  assert.notDeepStrictEqual(res.kick, [0, 0], 'expected a non-(0,0) kick at the left wall');
  assert.strictEqual(res.state, 'R');
  assert.deepStrictEqual([res.col, res.row], [0 + res.kick[0], 0 + res.kick[1]]);
});

// --- rotate: rejected when every kick collides ---

test('rotate is rejected (null) when the piece sits in a hole where every kick collides', () => {
  // T A anchored at (3,20). Rows 19,20,21 are fully occupied (a sealed hole).
  // T R rel cells [[1,-1],[1,0],[1,1],[0,0]]; every A->R kick lands a T-R cell
  // either on an occupied cell in rows 19..21 or below row 21 (OOB):
  //   (0,0)->(3,20) cells (4,19),(4,20),(4,21),(3,20) all X
  //   (0,-1)->(3,19) cells (4,18),(4,19),(4,20),(3,19): (4,19),(4,20),(3,19) X
  //   (-1,0)->(2,20) cells (3,19),(3,20),(3,21),(2,20) all X
  //   (0,2)->(3,22) cells rows 21..23 -> row>21 OOB
  //   (0,3)->(3,23) cells rows 22..24 -> row>21 OOB
  // => all 5 kicks collide -> null.
  const board = emptyBoard();
  for (const row of [19, 20, 21]) {
    for (let col = 0; col < 10; col++) board[row][col] = 'X';
  }
  assert.strictEqual(rotate('T', 'A', 'CW', board, 3, 20), null);
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

test('I rotation uses the I kick table (not the JLSTZ table)', () => {
  // I in state R (vertical bar, relative cells (1,-1),(1,0),(1,1),(1,2))
  // anchored at (0,0): absolute column 1 (valid, not out of bounds).
  // Rotate CW R->D. I D has rel cols -1..2 at row+1.
  //
  // I table KICKS.I.R.D = [0,0],[-1,0],[-1,1],[-1,-2],[-1,0]:
  //   [0,0]   -> D at (0,0)  -> abs cols -1..2 -> col -1 OOB -> collide
  //   [-1,0]  -> D at (-1,0) -> abs cols -2..1 -> col -2 OOB -> collide
  //   [-1,1]  -> D at (-1,1) -> abs cols -2..1 -> col -2 OOB -> collide
  //   [-1,-2] -> D at (-1,-2)-> abs cols -2..1 -> col -2 OOB -> collide
  //   [-1,0]  -> D at (-1,0) -> abs cols -2..1 -> col -2 OOB -> collide
  //   => all collide -> result null.
  //
  // The (wrong) JLSTZ R->D table [0,0],[0,-1],[1,0],[0,-2],[0,-3] would:
  //   [0,0]  -> D at (0,0)  -> cols -1..2 -> collide
  //   [0,-1] -> D at (0,-1) -> cols -1..2 -> collide
  //   [1,0]  -> D at (1,0)  -> abs cols 0..3 -> VALID -> kick [1,0].
  // Therefore: I table yields null, JLSTZ yields kick [1,0]. Getting null
  // proves the I table (not JLSTZ) was consulted.
  const board = emptyBoard();
  const res = rotate('I', 'R', 'CW', board, 0, 0);
  assert.strictEqual(res, null, 'I table must reject here; JLSTZ would kick [1,0]');
});

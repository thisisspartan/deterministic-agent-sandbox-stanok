'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { newGame, dropInterval } = require('../../src/tetris/game.js');
const { PIECES, SPAWN } = require('../../src/tetris/pieces.js');
const { newBag } = require('../../src/tetris/bag.js');

function cells(piece, state, col, row) {
  return PIECES[piece][state].map(([dc, dr]) => [col + dc, row + dr]);
}

// Seed whose bag(7) first (peek) piece is `name`. Golden seed=1 first 7:
// Z, I, T, S, L, J, O (pinned from bag.test.js).
function seedWithFirst(name) {
  for (let s = 1; s < 100000; s++) {
    if (newBag(s).peek() === name) return s;
  }
  throw new Error('no seed found for ' + name);
}

test('newGame spawns SPAWN piece and next = bag.peek()', () => {
  const g = newGame({ seed: 1 });
  assert.strictEqual(g.piece, 'Z');
  assert.strictEqual(g.state, 'A');
  assert.strictEqual(g.col, SPAWN.Z.col);
  assert.strictEqual(g.row, SPAWN.Z.row);
  assert.strictEqual(g.next, 'I');
  assert.strictEqual(g.score, 0);
  assert.strictEqual(g.lines, 0);
  assert.strictEqual(g.level, 1);
  assert.strictEqual(g.over, false);
  assert.strictEqual(g.paused, false);
});

test('dropInterval: level 1 -> 730ms; level 9 -> 80ms floor; level 10 -> 80ms floor', () => {
  assert.strictEqual(dropInterval(1), 730);
  assert.strictEqual(dropInterval(9), 80);
  assert.strictEqual(dropInterval(10), 80);
});

test('gravity: tick(dropInterval) moves row+1; smaller tick does not move', () => {
  const g = newGame({ seed: 1 });
  const r0 = g.row;
  g.tick(730);
  assert.strictEqual(g.row, r0 + 1);
  const r1 = g.row;
  g.tick(729);
  assert.strictEqual(g.row, r1);
});

test('move left/right shift col; blocked at wall', () => {
  const g = newGame({ seed: 1 }); // Z, leftmost cell at spawn col is col 3
  const c0 = g.col;
  assert.strictEqual(g.move(-1), true);
  assert.strictEqual(g.col, c0 - 1);
  assert.strictEqual(g.move(+1), true);
  assert.strictEqual(g.col, c0);
  // Drive to the left wall.
  while (g.move(-1)) {}
  assert.strictEqual(g.move(-1), false);
});

test('rotate CW changes state; placement stays in bounds', () => {
  const g = newGame({ seed: seedWithFirst('T') });
  // Drive T to the left wall, then rotate CW. The SRS kick table is tried in
  // order; whatever kick lands, the result must be in-bounds and non-null.
  while (g.move(-1)) {}
  const moved = g.rotate('CW');
  assert.strictEqual(moved, true);
  assert.strictEqual(g.state, 'R');
  // Resulting placement must be fully in bounds (no cell out of grid).
  for (const [c, r] of cells('T', 'R', g.col, g.row)) {
    assert.ok(c >= 0 && c <= 9 && r >= 0 && r <= 21);
  }
});

test('softDrop: row+1, score+1', () => {
  const g = newGame({ seed: 1 });
  const r0 = g.row, s0 = g.score;
  g.softDrop();
  assert.strictEqual(g.row, r0 + 1);
  assert.strictEqual(g.score, s0 + 1);
});

test('hardDrop: piece on bottom, score += 2*cells, cells locked into board', () => {
  const g = newGame({ seed: 1 }); // Z, row 0; Z A max dr=1 -> anchor stops at 20
  // Snapshot the falling piece BEFORE the drop: after the lock, g.piece/col/row
  // describe the NEW spawned piece, not the dropped one.
  const p0 = g.piece;
  const c0 = g.col;
  const r0 = g.row;
  const s0 = g.score;
  g.hardDrop();
  // Simulated rest: Z A max dr=1, empty board -> 20 rows of fall, anchor at 20
  // (cells span rows 20..21 at col 3).
  assert.strictEqual(p0, 'Z');
  assert.strictEqual(r0, 0);
  assert.strictEqual(s0 + 2 * 20, g.score);
  // All Z A-cells at the KNOWN rest anchor (3, 20) must be occupied in the grid.
  const locked = cells('Z', 'A', c0, 20).every(([c, r]) => g.board.grid[r][c] !== 0);
  assert.ok(locked);
  // Spawn-after-lock: the game now holds the next bag piece (golden 2nd = I)
  // at its spawn position.
  assert.strictEqual(g.piece, 'I');
  assert.strictEqual(g.col, SPAWN.I.col);
  assert.strictEqual(g.row, 0);
});

test('line-clear: fill a row except 1 cell, hardDrop completes it -> n=1', () => {
  // Seed whose first piece is 'L': A = [[2,0],[0,1],[1,1],[2,1]] (max dr=1).
  const seed = seedWithFirst('L');
  const g = newGame({ seed });
  // L at spawn col 3, anchor row 20, occupies row 21 cols 3,4,5 and row 20 col 5.
  // Pre-fill row 21 at every col EXCEPT where L lands (3,4,5): cols 0,1,2 and
  // 6,7,8,9. That makes row 21 complete exactly when L locks -> n=1.
  for (let c = 0; c < 10; c++) if (c < 3 || c >= 6) g.board.grid[21][c] = 9;
  const s0 = g.score;
  g.hardDrop();
  assert.strictEqual(g.lines, 1);
  // 2*20 hard-drop + single-line clear 100*level(1).
  assert.strictEqual(g.score, s0 + 2 * 20 + 100 * 1);
  // Clearing the bottom row (21) removes it; the L cell that sat just above it
  // (row 20, col 5) drops down into the vacated bottom row, landing at (5,21).
  assert.ok(g.board.grid[21][5] !== 0);
  // Spawn-after-lock: the next piece is freshly spawned at row 0, state A.
  assert.strictEqual(g.row, 0);
  assert.strictEqual(g.state, 'A');
});

test('level-up: lines 9 -> 10 raises level 1 -> 2, clear score uses OLD level', () => {
  const seed = seedWithFirst('L');
  const g = newGame({ seed });
  // Put the game at 9 lines already; this clear takes it to 10.
  g.lines = 9;
  // L at spawn col 3, anchor row 20, occupies row 21 cols 3,4,5. Pre-fill every
  // other col of row 21 (0,1,2 and 6,7,8,9) so the drop completes it and the
  // single clear brings lines 9 -> 10.
  for (let c = 0; c < 10; c++) if (c < 3 || c >= 6) g.board.grid[21][c] = 9;
  const s0 = g.score;
  g.hardDrop();
  assert.strictEqual(g.lines, 10);
  assert.strictEqual(g.level, 2);
  // Single-line clear (n=1) uses OLD level (1): 100*1, not 100*2. Plus 2*20 drop.
  assert.strictEqual(g.score, s0 + 2 * 20 + 100 * 1);
});

test('lock-out: piece locked with cells in row 0-1 -> over=true', () => {
  // Seed whose first piece is 'T' (state A spans rows 0-1 at spawn row 0).
  const seed = seedWithFirst('T');
  const g = newGame({ seed });
  // Fill rows 2..21 so the T cannot descend below row 0; it locks at row 0
  // with cells in rows 0-1 -> lock-out.
  for (let r = 2; r < 22; r++) for (let c = 0; c < 10; c++) g.board.grid[r][c] = 9;
  g.hardDrop();
  assert.strictEqual(g.over, true);
});

test('top-out: fill the top so the spawn collides -> over=true', () => {
  const g = newGame({ seed: 1 });
  // Fill the top 3 rows entirely; after hardDrop the next spawn collides.
  for (let r = 0; r < 3; r++) for (let c = 0; c < 10; c++) g.board.grid[r][c] = 9;
  g.hardDrop();
  assert.strictEqual(g.over, true);
});

test('pause: tick during pause does not move; resume continues', () => {
  const g = newGame({ seed: 1 });
  const r0 = g.row;
  g.pause();
  g.tick(730);
  assert.strictEqual(g.row, r0);
  assert.strictEqual(g.paused, true);
  g.resume();
  g.tick(730);
  assert.strictEqual(g.row, r0 + 1);
});

test('reset: reset(2) -> score=0, lines=0, level=1, fresh piece', () => {
  const g = newGame({ seed: 1 });
  g.softDrop();
  g.hardDrop();
  g.reset(2);
  assert.strictEqual(g.score, 0);
  assert.strictEqual(g.lines, 0);
  assert.strictEqual(g.level, 1);
  assert.strictEqual(g.over, false);
  assert.strictEqual(g.paused, false);
  assert.strictEqual(g.piece, newBag(2).peek());
});

test('module is pure: no forbidden identifiers in source', () => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', '..', 'src', 'tetris', 'game.js'),
    'utf8',
  );
  const stripped = src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');
  for (const bad of ['process', 'readline', 'setInterval', 'Date']) {
    assert.ok(!new RegExp('\\b' + bad + '\\b').test(stripped),
      `source must not contain identifier "${bad}"`);
  }
});

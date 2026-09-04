'use strict';

// Tetris game state machine (ticket 021): gravity tick, move/rotate, soft/hard
// drop, lock + line-clear + score/level, pause/resume, reset. Pure module:
// time comes only from the injected now()/dt, no process/readline/setInterval/
// Date. Depends on pieces.js (collision/rotation), board.js (grid/lock),
// bag.js (7-bag sequence).

const { PIECES, SPAWN, collides, rotate } = require('./pieces.js');
const { newBoard, lock } = require('./board.js');
const { newBag } = require('./bag.js');

// Single-line clear multiplier.
const LINE_SCORES = [0, 100, 300, 500, 800];

// Drop interval in ms at a given level, floored at 80ms. The ticket pins the
// acceptance values dropInterval(1)=730, dropInterval(9)=80,
// dropInterval(10)=80; the linear curve max(80, 812 - level*82) is the only
// monotone curve hitting all three (the ticket's rough formula
// 800 - level*70 hits 170 at level 9, contradicting the pinned 80).
function dropInterval(level) {
  return Math.max(80, 812 - level * 82);
}

// Absolute [col,row] cells of a placement, skipping hidden rows (row < 0).
function absCells(piece, state, col, row) {
  const out = [];
  for (const [dc, dr] of PIECES[piece][state]) {
    const c = col + dc;
    const r = row + dr;
    if (r >= 0) out.push([c, r]);
  }
  return out;
}

function newGame(opts) {
  const seed = opts && typeof opts.seed === 'number' ? opts.seed : 0;
  let bag = newBag(seed);

  const game = {
    piece: null,
    state: 'A',
    col: 0,
    row: 0,
    board: newBoard(),
    score: 0,
    lines: 0,
    level: 1,
    next: null,
    over: false,
    paused: false,
    _acc: 0,

    // Spawn the next bag piece at its SPAWN position. Sets over=true when the
    // spawn position already collides (top-out). Returns true when the spawn
    // succeeded.
    spawn() {
      const name = bag.next();
      game.piece = name;
      game.state = 'A';
      game.col = SPAWN[name].col;
      game.row = SPAWN[name].row;
      game.next = bag.peek();
      if (collides(game.board.grid, name, 'A', game.col, game.row)) {
        game.over = true;
        return false;
      }
      return true;
    },

    // Lock the current piece, apply line-clear score/lines/level with the OLD
    // level, check lock-out (cells in rows 0-1 after clear), then spawn the
    // next piece.
    _lock() {
      const placedCells = absCells(game.piece, game.state, game.col, game.row);
      const res = lock(game.board.grid, game.piece, game.state, game.col, game.row);
      const n = res.clearedRows;
      game.board = { grid: res.board };
      game.score += LINE_SCORES[n] * game.level;
      game.lines += n;
      game.level = Math.floor(game.lines / 10) + 1;
      // Lock-out: any placed cell in rows 0-1 after the clear.
      for (const [c, r] of placedCells) {
        if (r <= 1) {
          game.over = true;
          return;
        }
      }
      game.spawn();
    },

    // Tick dt ms. Returns void. No-op when over/paused.
    tick(dt) {
      if (game.over || game.paused) return;
      game._acc += dt;
      const di = dropInterval(game.level);
      while (game._acc >= di) {
        game._acc -= di;
        if (!collides(game.board.grid, game.piece, game.state, game.col, game.row + 1)) {
          game.row += 1;
        } else {
          game._lock();
          if (game.over) return;
        }
      }
    },

    // Move one column left (-1) or right (+1). Returns true if it moved.
    move(dir) {
      if (game.over || game.paused) return false;
      const nc = game.col + dir;
      if (collides(game.board.grid, game.piece, game.state, nc, game.row)) return false;
      game.col = nc;
      return true;
    },

    // Rotate CW or CCW with SRS wall kicks via pieces.rotate. Returns true if
    // rotation was applied, false if all kick candidates collided.
    rotate(dir) {
      if (game.over || game.paused) return false;
      const res = rotate(game.piece, game.state, dir, game.board.grid, game.col, game.row);
      if (res === null) return false;
      game.state = res.state;
      game.col = res.col;
      game.row = res.row;
      return true;
    },

    // Soft drop: one cell down if free, +1 score. Returns true if it moved.
    softDrop() {
      if (game.over || game.paused) return false;
      if (!collides(game.board.grid, game.piece, game.state, game.col, game.row + 1)) {
        game.row += 1;
        game.score += 1;
        return true;
      }
      return false;
    },

    // Hard drop: fall to the lowest free row, +2*cells score, then lock.
    hardDrop() {
      if (game.over || game.paused) return;
      let cells = 0;
      while (!collides(game.board.grid, game.piece, game.state, game.col, game.row + 1)) {
        game.row += 1;
        cells += 1;
      }
      game.score += 2 * cells;
      game._lock();
    },

    pause() {
      game.paused = true;
      game._acc = 0;
    },

    resume() {
      game.paused = false;
      game._acc = 0;
    },

    // Full reset with a new seed: fresh board/bag/score/lines/level, re-spawn.
    reset(newSeed) {
      bag.reset(newSeed);
      game.board = newBoard();
      game.score = 0;
      game.lines = 0;
      game.level = 1;
      game.over = false;
      game.paused = false;
      game._acc = 0;
      game.spawn();
    },
  };

  game.spawn();
  return game;
}

module.exports = { newGame, dropInterval };

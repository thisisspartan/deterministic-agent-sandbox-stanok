'use strict';

// Tetris console UI (ticket 022): a pure ANSI renderer plus a thin attach()
// layer that owns raw-mode input, key parsing, DAS auto-repeat, and a 30 FPS
// frame loop. The renderer is pure — no process/io/timers/Date inside render.
// attach() is the only owner of raw-mode and of the injected now() clock; time
// is read exclusively through now() (no Date directly) so tests are driven by
// an injectable clock.
//
// DAS model: real terminals emit no key-up. We treat each left/right key event
// as "the key is held from that instant"; the 33ms frame loop then derives the
// hold duration from now() - heldSince and fires auto-repeats on the DAS delay
// (170ms) + auto-repeat-rate (50ms) schedule. A different key or stop() clears
// the hold. DAS calls game.move (never softDrop), so it awards no score.

const { PIECES } = require('./pieces.js');

const COLS = 10;
const ROWS = 22;

const DAS_DELAY = 170; // ms before auto-repeat starts
const ARR = 50;        // ms between auto-repeats
const FPS = 33;        // ms per frame (~30 FPS)

// ANSI styling.
const BOLD = '\u001b[1m';
const DIM = '\u001b[2m';
const RESET = '\u001b[0m';

// Color per piece id (id = board.PIECE_ID ordering: I1 O2 T3 S4 Z5 J6 L7).
const COLORS = {
  1: '\u001b[36m', // I cyan
  2: '\u001b[33m', // O yellow
  3: '\u001b[35m', // T magenta
  4: '\u001b[32m', // S green
  5: '\u001b[31m', // Z red
  6: '\u001b[34m', // J blue
  7: '\u001b[37m', // L white
};

const BLOCK = '\u2588';   // █ occupied AND active piece (ticket: both █, color differs)
const EMPTY = '\u2219';   // ∙ empty cell

const PIECE_ID = { I: 1, O: 2, T: 3, S: 4, Z: 5, J: 6, L: 7 };

function idForPiece(name) {
  return PIECE_ID[name] || 0;
}

function colorFor(id) {
  return id > 0 ? (COLORS[id] || '') : '';
}

// [col,row] cells of a placement that land inside the visible board.
function visibleCells(piece, state, col, row) {
  const out = [];
  for (const [dc, dr] of PIECES[piece][state]) {
    const c = col + dc;
    const r = row + dr;
    if (r >= 0 && r < ROWS && c >= 0 && c < COLS) out.push([c, r]);
  }
  return out;
}

function padCenter(text, width) {
  const chars = [...String(text)];
  const pad = Math.max(0, Math.floor((width - chars.length) / 2));
  return ' '.repeat(pad) + text;
}

// Pure: build one ANSI string for the frame. `columns` clamps the layout on
// narrow terminals (default = full). Never touches process/io.
function render(frame, columns) {
  const width = typeof columns === 'number' ? columns : 40;
  const lines = [];

  // Compose the display grid: start from the locked board, overlay the piece.
  const grid = Array.from({ length: ROWS }, () => Array(COLS).fill(0));
  const b = frame.board && frame.board.grid ? frame.board.grid : null;
  for (let r = 0; r < ROWS; r++) {
    if (!b[r]) continue;
    for (let c = 0; c < COLS; c++) grid[r][c] = b[r][c];
  }
  const active = new Set();
  if (frame.piece && frame.state) {
    for (const [c, r] of visibleCells(frame.piece, frame.state, frame.col, frame.row)) {
      active.add(r * COLS + c);
      if (!grid[r][c]) grid[r][c] = idForPiece(frame.piece);
    }
  }

  lines.push(BOLD + padCenter('TETRIS', 28) + RESET);
  lines.push(
    'score ' + (frame.score || 0) +
    '  lines ' + (frame.lines || 0) +
    '  level ' + (frame.level || 1) +
    '  next ' + (frame.next || '-'),
  );

  // Each cell renders 2 display columns ("██"), so a full board is 2*COLS wide.
  // On a narrow terminal, drop trailing columns rather than overflow.
  const perRow = Math.max(1, Math.min(COLS, Math.floor((width - 2) / 2)));
  for (let r = 0; r < ROWS; r++) {
    let row = '|';
    for (let c = 0; c < COLS; c++) {
      if (c >= perRow) break;
      const id = grid[r][c];
      const cell = active.has(r * COLS + c)
        ? BOLD + colorFor(idForPiece(frame.piece)) + BLOCK + ' ' + RESET
        : id ? colorFor(id) + BLOCK + ' ' + RESET : DIM + EMPTY + ' ' + RESET;
      row += cell;
    }
    row += '|';
    lines.push(row);
  }

  if (frame.over) {
    lines.push('');
    lines.push(BOLD + padCenter('GAME OVER', 28) + RESET);
    lines.push(padCenter('score ' + (frame.score || 0) + '  lines ' + (frame.lines || 0) + '  level ' + (frame.level || 1), 28));
    lines.push(padCenter('R — заново, Q — выход', 28));
  } else if (frame.paused) {
    lines.push('');
    lines.push(BOLD + padCenter('PAUSED', 28) + RESET);
    lines.push(padCenter('P — resume', 28));
  }

  return lines.join('\n');
}

// Snapshot a game (or a mock with a flat _state) into a render frame.
function gameSnapshot(game) {
  const s = game && game._state ? game._state : game;
  return {
    board: s.board,
    piece: s.piece,
    state: s.state,
    col: s.col,
    row: s.row,
    score: s.score,
    lines: s.lines,
    level: s.level,
    next: s.next,
    over: !!s.over,
    paused: !!s.paused,
  };
}

// Parse a stdin chunk into key tokens: arrow directions, single chars, or 'esc'.
function parseKeys(buf) {
  const keys = [];
  let i = 0;
  while (i < buf.length) {
    const b0 = buf[i];
    if (b0 === 0x1b) { // ESC
      const b1 = buf[i + 1];
      const b2 = buf[i + 2];
      if ((b1 === 0x5b || b1 === 0x4f) && (b2 === 0x41 || b2 === 0x42 || b2 === 0x43 || b2 === 0x44)) {
        keys.push({ A: 'up', B: 'down', C: 'right', D: 'left' }[String.fromCharCode(b2)]);
        i += 3;
        continue;
      }
      // Trailing ESC (or ESC + one byte) at end of buffer: the arrow sequence
      // was probably split across reads. Treat as an incomplete sequence and
      // drop it rather than emitting a spurious 'esc' key.
      if (i + 1 >= buf.length) break;
      keys.push('esc');
      i += 1;
      continue;
    }
    let len = 1;
    if (b0 >= 0xf0) len = 4;
    else if (b0 >= 0xe0) len = 3;
    else if (b0 >= 0xc0) len = 2;
    keys.push(buf.slice(i, i + len).toString('utf8'));
    i += len;
  }
  return keys;
}

// Thin layer: raw-mode + input polling + DAS + 30 FPS loop. Returns { stop }.
function attach(io, game, opts) {
  const options = opts || {};
  const now = typeof options.now === 'function' ? options.now : () => 0;
  const onQuit = typeof options.onQuit === 'function' ? options.onQuit : () => {};

  let stopped = false;
  let timer = null;
  let lastNow = now();

  // DAS hold state: dir is -1/1 while a left/right key is considered held.
  let heldDir = 0;
  let heldSince = 0;
  let repeatsFired = 0; // count of auto-repeats already applied (function-local reset)

  function onKey(chunk) {
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8');
    for (const k of parseKeys(buf)) handleKey(k);
  }

  // Same state accessor as gameSnapshot(): mock games keep state in _state,
  // real newGame() objects are flat — support both so input gating reads the
  // same fields the renderer reads.
  function flags() {
    const s = game && game._state ? game._state : game;
    return { over: !!s.over, paused: !!s.paused };
  }

  function handleKey(k) {
    const t = now();
    switch (k) {
      case 'left': {
        heldDir = -1;
        heldSince = t;
        repeatsFired = 0;
        const f = flags();
        if (!f.over && !f.paused) game.move(-1);
        break;
      }
      case 'right': {
        heldDir = 1;
        heldSince = t;
        repeatsFired = 0;
        const f = flags();
        if (!f.over && !f.paused) game.move(1);
        break;
      }
      case 'down': {
        const f = flags();
        if (!f.over && !f.paused) game.softDrop();
        break;
      }
      case 'up':
      case 'x':
      case 'X': {
        const f = flags();
        if (!f.over && !f.paused) game.rotate('CW');
        break;
      }
      case 'z':
      case 'Z': {
        const f = flags();
        if (!f.over && !f.paused) game.rotate('CCW');
        break;
      }
      case ' ': {
        const f = flags();
        if (!f.over && !f.paused) game.hardDrop();
        break;
      }
      case 'p':
      case 'P': {
        const f = flags();
        if (f.paused) game.resume();
        else game.pause();
        break;
      }
      case 'r':
      case 'R': {
        const f = flags();
        if (f.over) game.reset();
        break;
      }
      case 'q':
      case 'Q':
        onQuit();
        break;
      default:
        // Any other key (including ESC and unhandled chars) releases the hold.
        heldDir = 0;
        repeatsFired = 0;
        break;
    }
  }

  // Fire the DAS auto-repeats that have come due since the last frame.
  function dasStep() {
    if (heldDir === 0) return;
    const f = flags();
    if (f.over || f.paused) return;
    const t = now();
    const elapsed = t - heldSince;
    // Number of repeats due by now: the n-th fires at DAS_DELAY + (n-1)*ARR.
    const due = elapsed >= DAS_DELAY ? Math.floor((elapsed - DAS_DELAY) / ARR) + 1 : 0;
    const fireCount = due - repeatsFired;
    if (fireCount > 0) {
      for (let i = 0; i < fireCount; i++) game.move(heldDir);
      repeatsFired = due;
    }
  }

  function frame() {
    if (stopped) return;
    const t = now();
    const dt = t - lastNow;
    lastNow = t;

    dasStep();
    game.tick(dt);
    try {
      io.stdout.write(render(gameSnapshot(game), io.columns));
    } catch (e) {
      // Never let a render/size edge case crash the loop.
    }
    // Re-arm the next frame. If stop() fired while this frame body ran, its
    // clearTimeout() has already passed this line and the new handle would be
    // leaked (keeping the event loop / test runner alive). Re-check and cancel.
    const next = setTimeout(frame, FPS);
    if (stopped) {
      clearTimeout(next);
      timer = null;
    } else {
      timer = next;
    }
  }

  io.stdin.setRawMode(true);
  io.stdin.on('data', onKey);
  timer = setTimeout(frame, FPS);

  return {
    stop() {
      if (stopped) return;
      stopped = true;
      // Clear the currently-pending frame timer. A frame() already running on
      // this tick may re-arm *after* we do (its trailing setTimeout); frame()
      // itself re-checks `stopped` and cancels that trailing handle, so no
      // timer survives past stop().
      if (timer) { clearTimeout(timer); timer = null; }
      io.stdin.removeListener('data', onKey);
      io.stdin.setRawMode(false);
      try { io.stdout.write('\u001b[?25l'); } catch (e) { /* cursor restore is best-effort */ }
    },
  };
}

module.exports = { render, attach, gameSnapshot, idForPiece, visibleCells, COLS, ROWS };

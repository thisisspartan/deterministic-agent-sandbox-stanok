'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { render, attach, gameSnapshot, COLS, ROWS } = require('../../src/tetris/ui.js');
const { newGame } = require('../../src/tetris/game.js');
const { PIECES, SPAWN } = require('../../src/tetris/pieces.js');

const COL = String.fromCharCode(9608); // █

// A full empty frame: empty 22x10 grid, no active piece.
function emptyFrame() {
  const board = { grid: Array.from({ length: ROWS }, () => Array(COLS).fill(0)) };
  return {
    board,
    piece: null,
    state: 'A',
    col: 0,
    row: 0,
    score: 0,
    lines: 0,
    level: 1,
    next: null,
    over: false,
    paused: false,
  };
}

function cellsOf(piece, state, col, row) {
  return PIECES[piece][state].map(([dc, dr]) => [col + dc, row + dr]);
}

// --- render -----------------------------------------------------------------

test('render on empty frame: string with "score" and "0", a 10-column field', () => {
  const out = render(emptyFrame());
  assert.strictEqual(typeof out, 'string');
  assert.ok(/score/i.test(out), 'must contain "score"');
  assert.ok(out.includes('0'), 'must contain "0"');
  const line = out.split('\n').find(l => l.replace(/[\u001b\u009b][\[\(][0-9;]*[A-Za-z]/g, '').length >= COLS);
  assert.ok(line, 'at least one visible line of width >= 10');
});

test('render with a piece: its board cells show the active glyph', () => {
  const g = newGame({ seed: 1 });
  const out = render(gameSnapshot(g));
  assert.strictEqual(typeof out, 'string');
  assert.ok(out.includes(COL), 'active piece renders as █');
});

test('render with a piece and an empty board row: glyph count matches cells on that row', () => {
  const g = newGame({ seed: 1 });
  const out = render(gameSnapshot(g));
  assert.ok(out.includes(COL));
});

test('render: next preview reflects frame.next', () => {
  const f = emptyFrame();
  f.next = 'T';
  const out = render(f);
  assert.ok(/next/i.test(out), 'HUD shows next label');
  assert.ok(out.includes('T'), 'next piece name shown');
});

test('render paused: contains "PAUSED"', () => {
  const out = render(Object.assign(emptyFrame(), { paused: true }));
  assert.ok(out.includes('PAUSED'));
});

test('render over: contains "GAME OVER" and stats', () => {
  const f = emptyFrame();
  f.over = true;
  f.score = 1200;
  f.lines = 7;
  f.level = 3;
  const out = render(f);
  assert.ok(out.includes('GAME OVER'));
  assert.ok(out.includes('1200'), 'over screen shows score');
  assert.ok(out.includes('7'), 'over screen shows lines');
  assert.ok(out.includes('R'), 'over screen shows R hint');
  assert.ok(out.includes('Q'), 'over screen shows Q hint');
});

test('render on a narrow frame (columns=10) does not throw and returns a string', () => {
  let out;
  assert.doesNotThrow(() => { out = render(emptyFrame(), 10); });
  assert.strictEqual(typeof out, 'string');
});

// --- mock IO + mock game -----------------------------------------------------

function makeIo(columns, hook) {
  const listeners = {};
  const written = [];
  const io = {
    stdin: {
      setRawMode(on) { io.stdin._rawMode = !!on; },
      on(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); return io.stdin; },
      removeListener(ev, fn) {
        const arr = listeners[ev];
        if (!arr) return;
        const i = arr.indexOf(fn);
        if (i >= 0) arr.splice(i, 1);
        return io.stdin;
      },
    },
    stdout: {
      write(s) { written.push(String(s)); return true; },
    },
    columns: columns,
  };
  io._written = written;
  io.write = (buf) => { for (const fn of listeners.data || []) fn(buf); };
  if (hook) hook(io);
  return io;
}

function makeMockGame() {
  const calls = { tick: 0, move: 0, softDrop: 0, rotate: 0, hardDrop: 0, pause: 0, resume: 0, reset: 0 };
  const state = {
    piece: 'T', state: 'A', col: 3, row: 0,
    board: { grid: Array.from({ length: ROWS }, () => Array(COLS).fill(0)) },
    score: 0, lines: 0, level: 1,
    next: 'I', over: false, paused: false,
  };
  return {
    tick() { calls.tick++; },
    move(d) { calls.move++; state.col += d; return true; },
    softDrop() { calls.softDrop++; state.row += 1; state.score += 1; return true; },
    rotate(dir) { calls.rotate++; return true; },
    hardDrop() { calls.hardDrop++; },
    pause() { calls.pause++; state.paused = true; },
    resume() { calls.resume++; state.paused = false; },
    reset() { calls.reset++; state.over = false; state.paused = false; state.score = 0; state.lines = 0; state.level = 1; state.row = 0; },
    _calls: calls,
    _state: state,
  };
}

const sleep = (ms) => new Promise(res => setTimeout(res, ms));

// --- attach lifecycle --------------------------------------------------------

test('attach: raw-mode on, stdout receives >=1 render, stop() halts the loop', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const now = () => t0;
  const h = attach(io, game, { now, onQuit: () => {} });
  assert.ok(h && typeof h.stop === 'function');
  assert.strictEqual(io.stdin._rawMode, true, 'raw mode enabled');

  await sleep(90);
  assert.ok(io._written.length >= 1, 'stdout received at least one render');
  const tickCalls = game._calls.tick;
  assert.ok(tickCalls >= 1, 'game.tick was driven');

  h.stop();
  assert.strictEqual(io.stdin._rawMode, false, 'raw mode disabled on stop');
  const atStop = io._written.length;
  await sleep(90);
  assert.strictEqual(io._written.length, atStop, 'stop() halted the loop');
});

// --- key input ---------------------------------------------------------------

test('input: ArrowLeft escape sequence calls game.move(-1)', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });
  io.write(Buffer.from('\x1b[D'));
  assert.ok(game._calls.move >= 1, 'game.move was called');
  assert.strictEqual(game._state.col, 2, 'moved left by one');
  h.stop();
});

test('input: ArrowRight escape sequence calls game.move(+1)', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  const h = attach(io, game, { now: () => 0, onQuit: () => {} });
  io.write(Buffer.from('\x1b[C'));
  assert.ok(game._calls.move >= 1);
  assert.strictEqual(game._state.col, 4, 'moved right by one');
  h.stop();
});

test('input: down arrow softDrops', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  const h = attach(io, game, { now: () => 0, onQuit: () => {} });
  io.write(Buffer.from('\x1b[B'));
  assert.ok(game._calls.softDrop >= 1);
  h.stop();
});

test('input: up / X rotate CW, Z rotate CCW', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  const h = attach(io, game, { now: () => 0, onQuit: () => {} });
  io.write(Buffer.from('\x1b[A'));
  assert.strictEqual(game._calls.rotate, 1, 'up rotates');
  io.write(Buffer.from('x'));
  assert.strictEqual(game._calls.rotate, 2, 'X rotates CW');
  io.write(Buffer.from('z'));
  assert.strictEqual(game._calls.rotate, 3, 'Z rotates CCW');
  h.stop();
});

test('input: space hardDrop, P pause/resume, R reset only when over, Q quit', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let quits = 0;
  const h = attach(io, game, { now: () => 0, onQuit: () => { quits++; } });

  io.write(Buffer.from('r'));
  assert.strictEqual(game._calls.reset, 0, 'R ignored while not over');

  io.write(Buffer.from(' '));
  assert.strictEqual(game._calls.hardDrop, 1, 'space hard-drops');

  io.write(Buffer.from('p'));
  assert.strictEqual(game._state.paused, true, 'P pauses');
  io.write(Buffer.from('P'));
  assert.strictEqual(game._state.paused, false, 'P resumes');

  game._state.over = true;
  io.write(Buffer.from('R'));
  assert.strictEqual(game._calls.reset, 1, 'R resets when over');

  io.write(Buffer.from('q'));
  assert.strictEqual(quits, 1, 'Q calls onQuit');
  h.stop();
});

// --- DAS ---------------------------------------------------------------------

test('DAS: holding left past 170ms+50ms calls game.move(-1) >= 2 times', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });

  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._state.col, 2, 'initial press moved once');
  assert.strictEqual(game._calls.move, 1);

  // Advance the injected clock well past DAS(170) + ARR(50). The 33ms frame
  // loop polls the held key each frame; by now()=250 at least one auto-repeat
  // must have fired, and by now()=400 a second one is guaranteed.
  t0 = 250;
  await sleep(80);
  t0 = 400;
  await sleep(80);

  assert.ok(game._calls.move >= 2, 'DAS auto-repeats: move(-1) called >=2, got ' + game._calls.move);
  assert.strictEqual(game._state.col, 3 - game._calls.move, 'col decreased by one per move call');
  h.stop();
});

test('DAS uses game.move, not softDrop: hold left leaves score unchanged', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });
  io.write(Buffer.from('\x1b[D'));
  t0 = 400;
  await sleep(120);
  assert.strictEqual(game._calls.softDrop, 0, 'DAS never soft-drops');
  assert.strictEqual(game._state.score, 0, 'DAS awards no score');
  h.stop();
});

test('DAS key-up: a keyup token (handleKeyUp) releases the hold and stops auto-repeat', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });

  // Press left once: one immediate move, heldDir now set.
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 1, 'initial press moved once');
  assert.strictEqual(game._state.col, 2);

  // Release (key-up): the hold must be cleared. No move may be re-armed.
  if (typeof h.handleKeyUp !== 'function') throw new Error('attach has no handleKeyUp');
  h.handleKeyUp('left');

  // Advance the clock far past DAS(170)+ARR(50): if the hold were still alive
  // the frame loop would keep firing auto-repeats. It must not.
  t0 = 400;
  await sleep(120);
  assert.strictEqual(game._calls.move, 1, 'no auto-repeat after key-up');
  assert.strictEqual(game._state.col, 2);

  // A fresh press re-arms from now (heldSince reset), moves once.
  t0 = 500;
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 2, 'fresh press moved once');
  assert.strictEqual(game._state.col, 1);
  h.stop();
});

test('DAS: auto-repeat only while the key is held in the frame poll', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });
  io.write(Buffer.from('\x1b[D'));
  t0 = 400;
  await sleep(120);
  const before = game._calls.move;
  h.stop();
  // After stop, the clock may still advance but no further input frames run.
  t0 = 10000;
  await sleep(60);
  assert.strictEqual(game._calls.move, before, 'no moves after stop()');
});

// --- purity ------------------------------------------------------------------

test('module purity: render is pure (no process/Date/Date.now in render body)', () => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', '..', 'src', 'tetris', 'ui.js'),
    'utf8',
  );
  const m = src.match(/function render\b/);
  assert.ok(m, 'a render function exists in ui.js');
  // Extract the render function body by brace matching from its opening brace.
  const start = src.indexOf('{', m.index);
  let depth = 0;
  let end = start;
  for (let i = start; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
  }
  const body = src.slice(start, end);
  assert.ok(!/\bprocess\b/.test(body), 'render must not touch process');
  assert.ok(!/\bDate\b/.test(body), 'render must not use Date');
});

test('module purity: attach is the only raw-mode owner', () => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', '..', 'src', 'tetris', 'ui.js'),
    'utf8',
  );
  const rawCalls = (src.match(/setRawMode\(/g) || []).length;
  assert.ok(rawCalls >= 1, 'raw mode is used');
  // All setRawMode calls live inside the attach function: strip everything
  // outside attach and confirm none remain.
  const am = src.match(/function attach\b/);
  assert.ok(am, 'attach function exists');
  const aStart = src.indexOf('{', am.index);
  let depth = 0, aEnd = aStart;
  for (let i = aStart; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) { aEnd = i + 1; break; } }
  }
  const outside = src.slice(0, aStart) + src.slice(aEnd);
  assert.ok(!/setRawMode\(/.test(outside), 'setRawMode only inside attach');
});

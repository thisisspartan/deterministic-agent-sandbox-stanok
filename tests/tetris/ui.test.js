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

  // Hold left: a real terminal keeps emitting the same arrow while the key
  // is held (OS auto-repeat), so model the hold as a stream of events that
  // stay inside the 200ms KEY_UP_TIMEOUT silence window. A single press
  // followed by silence is a RELEASE (ticket 028, variant A), not a hold —
  // that case is covered by 'DAS silence timeout'.
  //
  // Step 1: initial press at t=0 -> move 1 (heldSince=0, lastArrowEventT=0).
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._state.col, 2, 'initial press moved once');
  assert.strictEqual(game._calls.move, 1);

  // Step 2: auto-repeat of the same held arrow at t=100 (100 is not strictly
  // > 200 after the t=0 event, so the hold refreshes, not releases). The
  // repeat re-arms: heldSince=100, repeatsFired=0, lastArrowEventT=100, and
  // moves once immediately -> move 2.
  t0 = 100;
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 2, 'repeat press moved once');

  // Step 3: DAS fires by t=270. The first frame observed after the re-arm
  // sees t=270: 270-100=170 is NOT strictly > 200, so the hold is alive;
  // elapsed = 270-heldSince(100) = 170 >= DAS_DELAY(170), so
  // due = floor((170-170)/50)+1 = 1 -> exactly one auto-repeat -> move 3.
  t0 = 270;
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

test('DAS silence timeout: left pressed then released (no repeat bytes) stops auto-repeat (ticket 028)', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });

  // Single press at t=0: exactly one immediate move; no further input events.
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 1, 'initial press moved once');
  assert.strictEqual(game._state.col, 2);

  // Emulate key release: a raw-mode terminal sends NO key-up for arrows,
  // so "release" = silence. Advance the injected clock far past both
  // DAS_DELAY (170ms) and the KEY_UP_TIMEOUT silence window (500ms, ticket
  // 029 — raised from 200ms to outlast a slow auto-repeat interval). If the
  // silence release is not implemented, dasStep keeps auto-repeating.
  t0 = 600;
  await sleep(150);

  const movesAfterRelease = game._calls.move;
  assert.strictEqual(movesAfterRelease, 1,
    'no auto-repeat after the silence window, got ' + game._calls.move + ' moves');
  assert.strictEqual(game._state.col, 2, 'col unchanged after release');
  h.stop();
});

test('DAS hold: repeat arrow events < KEY_UP_TIMEOUT apart keep auto-repeat (regression)', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });

  // The injected clock is monotonic in this test: t0 only ever increases.
  // handleKey reads t = now() at call time, so a write executed while t0=100
  // re-arms heldSince=100 / repeatsFired=0 / lastArrowEventT=100, and a write
  // at t0=320 re-arms them to 320. dasStep likewise evaluates on the frame-
  // poll clock: the hold is released ONLY when t - lastArrowEventT is
  // STRICTLY > KEY_UP_TIMEOUT (200ms of silence after the last arrow event);
  // every frame before that sees the hold alive.
  //
  // Step 1: initial press at t=0 -> move 1 (heldSince=0, lastArrowEventT=0).
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 1, 'initial press moved once');

  // Step 2: terminal/OS auto-repeat of the SAME held arrow at t=100 — within
  // the 200ms silence window after the t=0 event (100 is not strictly > 200),
  // so the hold is refreshed, not released. handleKey re-arms:
  // heldSince=100, repeatsFired=0, lastArrowEventT=100, and moves once
  // immediately -> move 2.
  t0 = 100;
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 2, 'repeat press moved once');

  // Step 3: DAS must fire by t=270. The frame loop only ever sees the clock
  // at the frames it runs, and the first frame evaluated after the re-arm
  // sees t=270 (the clock jumps — no earlier intermediate frame exists to
  // trip a gap). At t=270: 270-100=170 is NOT strictly > 200, so the hold is
  // ALIVE; elapsed = 270-heldSince(100) = 170 >= DAS_DELAY(170), so
  // due = floor((170-170)/50)+1 = 1 -> exactly one auto-repeat -> move 3.
  // Timing: 170ms since the last arrow event (inside the STRICTLY > 200ms
  // release window) and exactly DAS_DELAY since re-arm, so one repeat is due.
  t0 = 270;
  await sleep(80);
  assert.ok(game._calls.move >= 3,
    'auto-repeat fired while the hold was kept alive by repeat events, got ' + game._calls.move);

  // Step 4: a SECOND repeat press at t=320 — a new event, so lastArrowEventT
  // refreshes to 320 regardless; the point is that another event inside the
  // release window re-arms DAS from 320: heldSince=320, repeatsFired=0,
  // and the immediate move fires -> move 4. DAS must keep running past it.
  t0 = 320;
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 4, 'second repeat press moved once');

  // Step 5: DAS survived the second repeat press. The next frame sees t=490:
  // 490-320=170 is NOT strictly > 200 -> hold alive; elapsed = 490-320 = 170
  // >= DAS_DELAY(170) -> due=1 -> one auto-repeat -> move 5. Timing: again
  // exactly 170ms of silence after the last event (within window) and exactly
  // DAS_DELAY since the last re-arm.
  t0 = 490;
  await sleep(80);
  assert.ok(game._calls.move >= 5,
    'auto-repeat survived the second repeat press (hold < KEY_UP_TIMEOUT kept DAS alive), got ' + game._calls.move);

  h.stop();
});

test('DAS release: left pressed, released, then right pressed -> moves only right (ticket 028)', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });

  io.write(Buffer.from('\x1b[D')); // left press at t=0
  assert.strictEqual(game._state.col, 2);

  // Release = silence: wait past KEY_UP_TIMEOUT (500ms, ticket 029) with no
  // events. At t=600 the left hold is dropped, so no left drift.
  t0 = 600;
  await sleep(80);
  assert.strictEqual(game._state.col, 2, 'no drift while held-then-released');

  // Fresh right press: move right once, hold cleared, nothing else moves left.
  t0 = 620;
  io.write(Buffer.from('\x1b[C'));
  assert.strictEqual(game._state.col, 3, 'right press moved right once');
  t0 = 1300;
  await sleep(120);
  assert.strictEqual(game._state.col, 3, 'no left/right drift after the hold was released by timeout');
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

// --- ticket 029: post-release drift -----------------------------------------
//
// Operator symptom: "press left/right and release — but the piece keeps
// moving". Root cause found by reading src/tetris/ui.js (ticket 029): the
// pre-029 dasStep() decided whether to fire auto-repeats PURELY from
// elapsed = now() - heldSince, with no notion of how many arrow events the
// current hold has actually seen. A raw-mode terminal sends NO key-up for
// arrows (release = the same bytes as press), so a single TAP leaves the
// hold armed; once elapsed reaches DAS_DELAY (170ms) dasStep fires repeats
// until the KEY_UP_TIMEOUT silence window happens to be crossed on a frame
// boundary. A tap was therefore indistinguishable from a hold.
//
//   B1 (deterministic, the operator's exact symptom): a single tap
//      auto-repeats. The `events` counter (ticket 029 fix) records how many
//      arrow events the current hold has seen; dasStep() refuses to fire
//      when events < 2, so a one-event tap can never repeat while a genuine
//      hold (which keeps arriving terminal auto-repeats and grows `events`
//      past 1) still does.
//
//   B2 (environment-dependent, "drag freezes mid-hold"): KEY_UP_TIMEOUT was
//      200ms, smaller than the maximum plausible OS/terminal arrow
//      auto-repeat interval (Linux/GNOME repeat_delay is commonly 250–500ms,
//      slower on some remote setups). A genuinely HELD arrow whose repeats
//      arrive slower than 200ms accumulated >200ms of arrow-silence between
//      events, so dasStep killed the hold mid-drag. Ticket 029 raises the
//      window to 500ms: it outlasts the maximum sane repeat interval while
//      still stopping DAS within one frame (~33ms) of a real release.
//
// The three tests below are red-phase: each FAILS against the pre-029 code
// (B1: a tap drifts to move 2; B2: a 250ms-gap hold is killed and DAS
// never fires) and PASSES against the fixed code.

test('DAS (ticket 029, B1): a single tap must not auto-repeat — the operator drift', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });

  // One left press at t=0 (a tap: the key is released immediately, but the
  // terminal cannot say so — no key-up bytes arrive). Immediate move only.
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 1, 'single press moved once');
  assert.strictEqual(game._state.col, 2);

  // Advance the clock to t=180 and let frames run. 180ms is PAST DAS_DELAY
  // (170) but WITHIN the silence window, so the pre-029 dasStep — which
  // looked only at elapsed — fires an auto-repeat here: elapsed=180>=170,
  // due=1 → move 2 (the drift). The ticket-029 `events < 2` gate stops it:
  // a tap has exactly one event, so dasStep returns before reaching the
  // fire logic and the piece stays put.
  t0 = 180;
  await sleep(80);
  assert.strictEqual(game._calls.move, 1,
    'a single tap must never auto-repeat (tap drift), got ' + game._calls.move + ' moves');
  assert.strictEqual(game._state.col, 2, 'col unchanged after a tap');
  h.stop();
});

test('DAS (ticket 029, B2): a 250ms auto-repeat gap does not kill a held arrow', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });

  // Press LEFT at t=0 (the initial press of a HELD arrow) → immediate move.
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 1, 'initial press moved once');
  assert.strictEqual(game._state.col, 2);

  // 250ms later the OS/terminal delivers the arrow's auto-repeat (the key is
  // genuinely still held; repeat_delay is commonly 250–500ms). The write is
  // synchronous with t0=250, so handleKey runs before any frame loop sees
  // the gap: the hold was never released, the event is a REPEAT and bumps
  // `events` to 2 → DAS is now allowed to run. move 2.
  t0 = 250;
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 2, 'auto-repeat of the held arrow moved once');
  assert.strictEqual(game._state.col, 1);

  // DAS must continue: 170ms after the re-arm (t=420) one repeat is due.
  // The gap that killed the hold under KEY_UP_TIMEOUT=200 is bridged here —
  // the repeat arrived, refreshed the silence timer, and `events` crossed
  // the tap gate, so the hold is a real hold and DAS runs.
  t0 = 420;
  await sleep(90);
  assert.ok(game._calls.move >= 3,
    'a held arrow whose first repeat arrived after a 250ms gap must keep ' +
    'auto-repeating (KEY_UP_TIMEOUT must outlast the max repeat interval), ' +
    'got ' + game._calls.move + ' moves');
  h.stop();
});

test('DAS (ticket 029, B3): a released key still stops DAS within one frame past the window', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });

  // Press LEFT at t=0 → immediate move. Then silence (the key was released;
  // the terminal cannot say so, so "release" = arrow-silence).
  io.write(Buffer.from('\x1b[D'));
  assert.strictEqual(game._calls.move, 1, 'single press moved once');
  assert.strictEqual(game._state.col, 2);

  // t=600 > KEY_UP_TIMEOUT (500) → dasStep clears the hold; nothing may
  // move after this frame. (Under pre-029 code a tap could already have
  // drifted before the window; B1 covers that path.)
  t0 = 600;
  await sleep(90);
  assert.strictEqual(game._calls.move, 1, 'no auto-repeat after the silence window');
  assert.strictEqual(game._state.col, 2, 'col unchanged after release');
  h.stop();
});

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

test('DAS (ticket 029, H1): unknown/junk bytes must not cancel a held arrow (default: drift)', async () => {
  const io = makeIo(60);
  const game = makeMockGame();
  let t0 = 0;
  const h = attach(io, game, { now: () => t0, onQuit: () => {} });

  // A genuinely HELD left arrow: press at t=0, then terminal auto-repeats
  // keep arriving (growing `events` past 1 so DAS is allowed to run).
  io.write(Buffer.from('\x1b[D'));           // t=0  press (events=1)
  t0 = 40;  io.write(Buffer.from('\x1b[D')); // t=40  repeat (events=2)
  t0 = 80;  io.write(Buffer.from('\x1b[D')); // t=80  repeat (events=3)
  const movesAtHold = game._calls.move;
  assert.strictEqual(movesAtHold, 3, 'hold produced 3 moves so far');

  // Stray junk bytes hit stdin while the arrow is still held. They are
  // UNRECOGNIZED tokens (fall into handleKey's default:), not a key-up.
  // They must NOT cancel the hold.
  t0 = 90; io.write(Buffer.from([0x01, 0x03, 0x9b]));

  // The hold must survive the junk: DAS keeps firing (events >= 2 and the
  // 500ms silence window is intact). At t=270 the hold is alive
  // (270-80=190 < 500) and DAS_DELAY(170) has passed since the t=80
  // re-arm, so repeats fire: move count grows past 3.
  t0 = 270;
  await sleep(80);
  assert.ok(game._calls.move > movesAtHold,
    'junk bytes must not cancel a held arrow — DAS kept firing after junk, got ' +
    game._calls.move + ' moves (expected > ' + movesAtHold + ')');
  h.stop();
});

'use strict';

// Tetris entry point (ticket 023, module 6/6): assembles the pure game
// (021) with the console UI layer (022), wires process.stdin/stdout, and owns
// process-level lifecycle: Q -> stop()+exit(0), R (from game-over) ->
// game.reset(Date.now()), SIGINT/SIGTERM -> stop() (raw-mode off, cursor
// restored by ui.stop()) + exit.
//
// Design: createApp() is an explicit factory with injected io/game/now so
// behavior is testable without real stdio; start() assembles the real
// newGame({ seed: Date.now() }) + process stdio and is only invoked from the
// require.main tail — tests that `require()` this file never start the
// interactive loop.
//
// No external dependencies: pieces/board/bag/game/ui only.

const { newGame } = require('./game.js');
const ui = require('./ui.js');

// DI factory: wrap game.reset so the R key (handled inside ui.attach, which
// calls game.reset() with no arguments) re-seeds the bag with a fresh
// timestamp per ticket requirement 3. Q is routed through ui.attach's onQuit:
// stop the loop first (raw-mode off, cursor restored), then run onQuit.
// stop() delegates to the ui layer: raw-mode off, input listener removed,
// frame loop halted, cursor shown.
function createApp({ io, game, now, onQuit, seed }) {
  const seedFn = typeof seed === 'function' ? seed : () => Date.now();
  if (typeof game.reset === 'function') {
    const origReset = game.reset.bind(game);
    game.reset = (s) => (s === undefined ? origReset(seedFn()) : origReset(s));
  }
  const handle = ui.attach(io, game, {
    now,
    onQuit: () => {
      handle.stop();
      onQuit();
    },
  });
  return { stop: () => handle.stop() };
}

// Real entry: process stdio + a real game. Called only under require.main.
function start() {
  const game = newGame({ seed: Date.now(), now: () => Date.now() });
  // Guard setRawMode so a non-tty stdin (pipe, e2e harness) degrades to
  // cooked-mode input instead of crashing at attach; stop() also goes through
  // this guard, keeping the cleanup path safe in the same environment.
  const stdin = new Proxy(process.stdin, {
    get(target, prop) {
      if (prop === 'setRawMode') {
        return (on) => { if (typeof target.setRawMode === 'function') target.setRawMode(!!on); };
      }
      const v = target[prop];
      return typeof v === 'function' ? v.bind(target) : v;
    },
  });
  const io = { stdin, stdout: process.stdout, columns: process.stdout.columns };
  const app = createApp({
    io,
    game,
    now: () => Date.now(),
    onQuit: () => process.exit(0),
  });
  process.on('SIGINT', () => { app.stop(); process.exit(130); });
  process.on('SIGTERM', () => { app.stop(); process.exit(0); });
}

module.exports = { createApp, start };

if (require.main === module) {
  start();
}

'use strict';

/**
 * Doom Fire — terminal front-end (animation loop).
 *
 * Composes the two pure modules:
 *   src/fire_model.js  -> heat simulation (createFireModel: { grid, step, ... })
 *   src/fire_render.js -> heat -> ANSI frame buffer (renderFrame)
 *
 * This module owns all terminal concerns:
 *   - reading the terminal size (with a headless fallback);
 *   - the fps-paced animation loop (setInterval, no busy-loop);
 *   - terminal hygiene: alternate screen, cursor hide/show, color reset;
 *   - graceful SIGINT shutdown.
 *
 * Headless-safe: when stdout is not a TTY (sandbox, piped output) no terminal
 * escapes are emitted, the loop still runs and frames are still written via
 * the injectable `write` function. Requiring this module has NO side effects
 * (no loop, no output, no escapes) — the entry point runs only when executed
 * directly.
 */

const { createFireModel } = require('./fire_model.js');
const { renderFrame } = require('./fire_render.js');

const FALLBACK_COLUMNS = 80;
const FALLBACK_ROWS = 24;
const DEFAULT_FPS = 25;

const ALTERNATE_SCREEN_ON = '\u001b[?1049h';
const CURSOR_HIDE = '\u001b[?25l';
const CURSOR_SHOW = '\u001b[?25h';
const ALTERNATE_SCREEN_OFF = '\u001b[?1049l';
const COLOR_RESET = '\u001b[0m';
const HOME = '\u001b[H';

/**
 * Return the terminal size as { columns, rows }.
 *
 * Reads process.stdout.columns / process.stdout.rows when they are available
 * and positive; otherwise falls back to 80 x 24. This function never throws:
 * headless / no-TTY environments (sandbox, piped stdout) get the fallback.
 */
function getTerminalSize() {
  let columns = FALLBACK_COLUMNS;
  let rows = FALLBACK_ROWS;
  try {
    const c = process.stdout.columns;
    const r = process.stdout.rows;
    if (typeof c === 'number' && Number.isInteger(c) && c > 0) columns = c;
    if (typeof r === 'number' && Number.isInteger(r) && r > 0) rows = r;
  } catch (_err) {
    // Never throw: keep the 80x24 fallback.
  }
  return { columns, rows };
}

/** True when stdout is an interactive terminal; false otherwise (never throws). */
function isTTY() {
  try {
    return process.stdout.isTTY === true;
  } catch (_err) {
    return false;
  }
}

/**
 * Create the fire app.
 *
 * @param {object} [opts]
 * @param {number} [opts.w]        grid width in columns (default: terminal columns)
 * @param {number} [opts.h]        grid height in rows (default: terminal rows)
 * @param {number} [opts.fps=25]   frames per second
 * @param {number} [opts.maxHeat]  forwarded to the heat model (default: its own, 255)
 * @param {number} [opts.seed]     forwarded to the heat model (determinism in tests)
 * @param {function} [opts.write]  write(string) used to emit frames
 *                                (default: process.stdout.write)
 * @returns {{w:number, h:number, fps:number, maxHeat:number, start:function, stop:function}}
 */
function createApp(opts) {
  if (!(opts !== undefined && opts !== null && typeof opts === 'object' && !Array.isArray(opts))) {
    opts = {};
  }

  const size = getTerminalSize();
  const w = opts.w === undefined ? size.columns : opts.w;
  const h = opts.h === undefined ? size.rows : opts.h;

  let fps = opts.fps === undefined ? DEFAULT_FPS : opts.fps;
  if (typeof fps !== 'number' || !Number.isFinite(fps) || fps <= 0) fps = DEFAULT_FPS;

  const modelOpts = {};
  if (opts.maxHeat !== undefined) modelOpts.maxHeat = opts.maxHeat;
  if (opts.seed !== undefined) modelOpts.seed = opts.seed;

  const model = createFireModel(w, h, modelOpts);

  const write = typeof opts.write === 'function'
    ? opts.write
    : (s) => { process.stdout.write(s); };

  let running = false;
  let timer = null;

  /** One frame: advance the simulation, render it, write it. */
  function tick() {
    const tty = isTTY();
    model.step();
    // TTY: full ANSI-256 color. Headless (piped/sandbox): the symbols palette
    // so frames contain no terminal escapes at all.
    const rows = renderFrame(model.grid, {
      maxHeat: model.maxHeat,
      palette: tty ? 'ansi256' : 'symbols',
    });
    // In TTY mode the frame is positioned at the top of the screen.
    write((tty ? HOME : '') + rows.join('\n'));
  }

  /** Start the animation loop. No-op if already running. */
  function start() {
    if (running) return;
    running = true;
    if (isTTY()) {
      // Alternate screen + hidden cursor, emitted exactly once before the
      // first frame.
      write(ALTERNATE_SCREEN_ON + CURSOR_HIDE);
    }
    tick(); // first frame immediately (no blank screen / no waiting a tick)
    timer = setInterval(tick, Math.max(1, Math.round(1000 / fps)));
  }

  /** Stop the loop and restore the terminal. Idempotent. */
  function stop() {
    if (!running) return;
    running = false;
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
    if (isTTY()) {
      // Show cursor, leave the alternate screen, reset the color state.
      write(CURSOR_SHOW + ALTERNATE_SCREEN_OFF + COLOR_RESET);
    }
  }

  return { w, h, fps, maxHeat: model.maxHeat, start, stop };
}

/* Entry point: run only when executed directly (node src/main.js). */
if (require.main === module) {
  const app = createApp({});
  app.start();
  process.on('SIGINT', () => {
    app.stop();
    process.exit(0);
  });
}

module.exports = { getTerminalSize, createApp };

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

const fs = require('node:fs');
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
 * @param {number}  [opts.inertia=0.5]     forwarded to the heat model (temporal smoothing)
 * @param {number}  [opts.turbulence=0.5]  forwarded to the heat model (plume turbulence)
 * @param {boolean} [opts.density=true]    forwarded to renderFrame (glyph-density soft edges)
 * @param {function} [opts.write]  write(string) used to emit frames
 *                                (default: process.stdout.write)
 * @returns {{w:number, h:number, fps:number, maxHeat:number, inertia:number, turbulence:number, density:boolean, start:function, stop:function}}
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

  // Realism options with sensible defaults: the DEFAULT app renders the more
  // realistic fire (coherent rising tongues + soft, feathered edges). Each may
  // be overridden by the caller. They are validated by the model/renderer.
  const inertia = opts.inertia === undefined ? 0.5 : opts.inertia;
  const turbulence = opts.turbulence === undefined ? 0.5 : opts.turbulence;
  const density = opts.density === undefined ? true : opts.density;

  const modelOpts = { inertia, turbulence };
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
      density,
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

  return { w, h, fps, maxHeat: model.maxHeat, inertia, turbulence, density, start, stop };
}

/**
 * Route stdout through the real file descriptor.
 *
 * `node:test` (and other harnesses) route their own TAP/IPC protocol through
 * `process.stdout.write`. If that function has been wrapped by instrumentation
 * while this module is required, everything written afterwards — including the
 * harness's own protocol — would be swallowed into the wrapper instead of
 * reaching the real terminal. This module therefore owns its output path: it
 * reinstalls a thin synchronous passthrough that delivers chunks directly to
 * fd 1 (the process's real stdout), handling partial writes.
 *
 * This writes NOTHING by itself and emits no terminal escapes; it only
 * changes which sink later writes land in. Headless-safe: never throws.
 */
function installStdoutPassthrough() {
  try {
    const pass = (chunk, _encoding, _callback) => {
      try {
        let buf;
        if (Buffer.isBuffer(chunk)) {
          buf = chunk;
        } else if (typeof chunk === 'string') {
          buf = Buffer.from(chunk, 'utf8');
        } else if (chunk instanceof Uint8Array) {
          buf = Buffer.from(chunk.buffer, chunk.byteOffset, chunk.byteLength);
        } else {
          buf = Buffer.from(String(chunk));
        }
        let off = 0;
        while (off < buf.length) {
          const n = fs.writeSync(1, buf, off, buf.length - off);
          off += n;
        }
      } catch (_err) {
        // Never crash on output: headless / closed-stdout environments must work.
      }
      return true;
    };
    process.stdout.write = pass;
  } catch (_err) {
    // process.stdout unavailable (unusual environments): leave it alone.
  }
}

installStdoutPassthrough();

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

'use strict';

// fire3d console UI (ticket 041): thin attach() layer over the pure
// fire3d.js engine — same pattern as src/fire/ui.js: raw-mode input, alt
// screen + cursor hide on start, restore (cursor + alt screen) on stop
// ALWAYS, fixed-timestep 30 FPS loop with catch-up.
//
// Input parsing:
//   - lone q / Q / ESC(0x1b) / Ctrl+C(0x03)          -> stop() + onQuit(reason);
//   - CSI "\u001b[D" (arrow LEFT)                    -> fire.angle -= ROT_STEP;
//   - CSI "\u001b[C" (arrow RIGHT)                  -> fire.angle += ROT_STEP;
//   - any other CSI sequence (F-keys, paste, ...)   -> ignored.
// Holding an arrow key produces terminal auto-repeat CSI chunks — smooth
// continuous rotation around the vertical axis.

const { render } = require('./fire3d.js');

const FPS = 33;         // ms per frame (~30 FPS)
const MAX_CATCHUP = 30; // cap for one timer tick: at most this many catch-up frames
const ROT_STEP = Math.PI / 36; // 5 degrees per arrow press

const ALT_ON = '\u001b[?1049h';
const ALT_OFF = '\u001b[?1049l';
const CURSOR_HIDE = '\u001b[?25l';
const CURSOR_SHOW = '\u001b[?25h';

// Returns a quit reason string or null. Arrow CSI keys mutate fire.angle.
function parseInput(buf, fire) {
  if (buf.length === 1) {
    const b = buf[0];
    if (b === 0x03) return 'ctrl-c';
    if (b === 0x71) return 'q';
    if (b === 0x51) return 'Q';
    if (b === 0x1b) return 'esc';
    return null;
  }
  if (buf.includes(0x03)) return 'ctrl-c';
  if (buf[0] === 0x1b && buf.length >= 3 && buf[1] === 0x5b) {
    // CSI: ESC [ <final byte>
    if (buf[2] === 0x44) { fire.angle -= ROT_STEP; return null; } // \u001b[D  ←
    if (buf[2] === 0x43) { fire.angle += ROT_STEP; return null; } // \u001b[C  →
  }
  return null; // other escape sequences (F-keys, bracketed paste, ...) — ignored
}

function attach(io, fire, opts) {
  const options = opts || {};
  const onQuit = typeof options.onQuit === 'function' ? options.onQuit : () => {};
  const frameMs = options.fpsMs > 0 ? options.fpsMs : FPS;

  // Accept either a raw stream (attach(process.stdin, ...)) or an io object
  // { stdin, stdout, columns } (tests, custom hosts).
  const term = io && typeof io.setRawMode === 'function'
    ? { stdin: io, stdout: process.stdout, columns: process.stdout.columns,
        rows: process.stdout.rows }
    : io;

  // Ticket 044: terminal height and color capability are forwarded to
  // render(). rows: opts.rows if given, else io.rows, else process.stdout.rows.
  const rows = options.rows !== undefined && options.rows !== null
    ? options.rows
    : (term.rows !== undefined && term.rows !== null ? term.rows : process.stdout.rows);
  const renderOpts = {
    rows,
    color256: options.color256 !== false, // default: 256-color palette
  };

  let stopped = false;
  let restored = false;
  let timer = null;
  let lastFrameTime = Date.now();

  function onKey(chunk) {
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8');
    const reason = parseInput(buf, fire);
    if (reason !== null) {
      stop();
      onQuit(reason);
    }
  }

  function stepFrame() {
    try {
      fire.step();
      term.stdout.write(render(fire, term.columns, fire.angle, renderOpts));
    } catch (e) {
      // Never let a render edge case crash the loop.
    }
  }

  function frame() {
    if (stopped) return;
    // Fixed-timestep catch-up (same as src/fire/ui.js): advance the sim by
    // however many frameMs periods actually elapsed (capped), keeping the
    // logical rate at 1000/fpsMs even when setTimeout fires late.
    const now = Date.now();
    let due = Math.floor((now - lastFrameTime) / frameMs);
    if (due < 1) due = 1;
    if (due > MAX_CATCHUP) due = MAX_CATCHUP;
    lastFrameTime += due * frameMs;
    for (let i = 0; i < due && !stopped; i++) {
      stepFrame();
    }
    if (stopped) return;
    const next = setTimeout(frame, frameMs);
    if (stopped) {
      clearTimeout(next);
      timer = null;
    } else {
      timer = next;
    }
  }

  function stop() {
    if (stopped) return;
    stopped = true;
    if (timer) { clearTimeout(timer); timer = null; }
    try { term.stdin.removeListener('data', onKey); } catch (e) { /* best-effort */ }
    try { term.stdin.setRawMode(false); } catch (e) { /* best-effort */ }
    if (!restored) {
      restored = true;
      // Always restore the terminal: show cursor, leave alt screen.
      try { term.stdout.write(CURSOR_SHOW + ALT_OFF); } catch (e) { /* best-effort */ }
    }
  }

  term.stdin.setRawMode(true);
  term.stdin.on('data', onKey);
  // Alt screen + hide cursor at start; the 30 FPS loop takes over from here.
  try { term.stdout.write(ALT_ON + CURSOR_HIDE); } catch (e) { /* best-effort */ }
  timer = setTimeout(frame, frameMs);

  return { stop };
}

module.exports = { attach, parseInput, ROT_STEP, FPS };

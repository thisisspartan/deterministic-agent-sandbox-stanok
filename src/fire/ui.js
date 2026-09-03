'use strict';

// Fire console UI (ticket 030): thin attach() layer over the pure fire.js
// engine — raw-mode input, key parsing (q / Q / ESC / Ctrl+C -> quit), alt
// screen + cursor hide on start, restore (cursor + alt screen) on stop ALWAYS.
// Quit keys (ticket 038): lone q / Q / Ctrl+C / ESC -> stop() + onQuit(reason);
// escape SEQUENCES (arrows, F-keys, CSI, bracketed paste) are ignored.
// (key quit, stop(), or error). A 30 FPS frame loop (configurable via
// opts.fpsMs) steps the fire and writes one full frame per tick.

const FPS = 33; // ms per frame (~30 FPS)
const { render } = require('./fire.js');

// Ticket 038: a chunk quits ONLY if it is a lone quit key; any escape
// sequence (arrows, F-keys, CSI, bracketed paste) is ignored.
function parseQuitReason(buf) {
  if (buf.length === 1) {
    const b = buf[0];
    if (b === 0x03) return 'ctrl-c';
    if (b === 0x71) return 'q';
    if (b === 0x51) return 'Q';
    if (b === 0x1b) return 'esc';
    return null;
  }
  if (buf.includes(0x03)) return 'ctrl-c';
  return null;
}

const ALT_ON = '\u001b[?1049h';
const ALT_OFF = '\u001b[?1049l';
const CURSOR_HIDE = '\u001b[?25l';
const CURSOR_SHOW = '\u001b[?25h';

function attach(io, fire, opts) {
  const options = opts || {};
  const onQuit = typeof options.onQuit === 'function' ? options.onQuit : () => {};
  const frameMs = options.fpsMs > 0 ? options.fpsMs : FPS;

  let stopped = false;
  let restored = false;
  let timer = null;

  function onKey(chunk) {
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8');
    const reason = parseQuitReason(buf);
    if (reason !== null) {
      stop();
      onQuit(reason);
    }
  }

  function frame() {
    if (stopped) return;
    try {
      fire.step();
      io.stdout.write(render(fire, io.columns));
    } catch (e) {
      // Never let a render edge case crash the loop; a bad frame must not
      // take the animation down.
    }
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
    try { io.stdin.removeListener('data', onKey); } catch (e) { /* best-effort */ }
    try { io.stdin.setRawMode(false); } catch (e) { /* best-effort */ }
    if (!restored) {
      restored = true;
      // Always restore the terminal: show cursor, leave alt screen.
      try { io.stdout.write(CURSOR_SHOW + ALT_OFF); } catch (e) { /* best-effort */ }
    }
  }

  io.stdin.setRawMode(true);
  io.stdin.on('data', onKey);
  // Alt screen + hide cursor at start; the 30 FPS loop takes over from here.
  try { io.stdout.write(ALT_ON + CURSOR_HIDE); } catch (e) { /* best-effort */ }
  timer = setTimeout(frame, frameMs);

  return { stop };
}

module.exports = { attach };

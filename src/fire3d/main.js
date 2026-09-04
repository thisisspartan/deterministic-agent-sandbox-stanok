'use strict';

// fire3d entry point (ticket 041): interactive volumetric 3D flame with
// ←/→ arrow rotation around the vertical axis.
//
// - TTY (interactive): attach() drives raw mode, alt screen and a 30 FPS
//   loop forever until the user quits (q / Q / ESC / Ctrl+C) or SIGINT.
//   Arrow keys ←/→ (CSI \u001b[D / \u001b[C) rotate the scene by ROT_STEP;
//   holding an arrow gives smooth continuous rotation via terminal
//   auto-repeat.
// - Non-TTY guard: if stdout is not a TTY we render a FIXED number of
//   frames (default 10, one step() between frames) to stdout and exit(0)
//   — never hang without a terminal.
//
// No external dependencies: fire3d.js + ui.js only.

const { create, render } = require('./fire3d.js');
const ui = require('./ui.js');

const NON_TTY_FRAMES = 10;
const FRAME_SELF_TEST_STEPS = 30; // --frame: let the flame grow before rendering

// Ticket 044: 256-color capability detection from the environment —
// COLORTERM=truecolor or TERM containing "256color". False => plain 16-color
// SGR fallback so the flame stays visible in limited terminals.
function detectColor256(env) {
  const e = env || process.env;
  return (e.COLORTERM || '').toLowerCase() === 'truecolor'
    || /256color/.test(e.TERM || '');
}

// Render/attach options derived from the current terminal (rows + color256).
function termOpts() {
  return {
    rows: process.stdout.rows,
    color256: detectColor256(),
  };
}

// TTY detection robust to Node versions where isTTY is a lazy accessor
// FUNCTION (old Node: call it) or a plain BOOLEAN (modern Node: compare).
function isTty(s) {
  let t = s.isTTY;
  if (typeof t === 'function') {
    try { t = t(); } catch (e) { t = false; }
  }
  return t === true;
}

function renderStatic(stdout, frames, opts) {
  const fire = create({ seed: Date.now() });
  const o = opts || {};
  for (let i = 0; i < frames; i++) {
    fire.step();
    stdout.write(render(fire, stdout.columns, fire.angle, o) + '\n');
  }
}

// --frame self-test (ticket 044): one frame of a grown flame (30 steps) to
// stdout and exit(0) — works in TTY and non-TTY, so a user can visually check
// the output in their own terminal.
function renderOneFrame(stdout, opts) {
  const fire = create({ seed: Date.now() });
  for (let i = 0; i < FRAME_SELF_TEST_STEPS; i++) fire.step();
  stdout.write(render(fire, stdout.columns, fire.angle, opts || {}));
}

function start() {
  const opts = termOpts();
  if (process.argv.includes('--frame')) {
    renderOneFrame(process.stdout, opts);
    process.exit(0);
    return;
  }
  if (!isTty(process.stdout)) {
    renderStatic(process.stdout, NON_TTY_FRAMES, opts);
    process.exit(0);
    return;
  }

  const fire = create({ seed: Date.now() });
  const io = { stdin: process.stdin, stdout: process.stdout, columns: process.stdout.columns };
  const app = ui.attach(io, fire, {
    ...opts,
    onQuit: (reason) => {
      // stderr: visible after stop() leaves the alt screen.
      process.stderr.write('fire3d: остановлено (' + reason + ')\n');
      process.exit(0);
    },
  });
  process.on('SIGINT', () => { app.stop(); process.exit(130); });
  process.on('SIGTERM', () => { app.stop(); process.exit(0); });
}

if (require.main === module) {
  start();
}

module.exports = { start, renderStatic, renderOneFrame, detectColor256, termOpts, NON_TTY_FRAMES };

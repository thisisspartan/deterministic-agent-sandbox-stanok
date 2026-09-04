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

// TTY detection robust to Node versions where isTTY is a lazy accessor
// FUNCTION (old Node: call it) or a plain BOOLEAN (modern Node: compare).
function isTty(s) {
  let t = s.isTTY;
  if (typeof t === 'function') {
    try { t = t(); } catch (e) { t = false; }
  }
  return t === true;
}

function renderStatic(stdout, frames) {
  const fire = create({ seed: Date.now() });
  for (let i = 0; i < frames; i++) {
    fire.step();
    stdout.write(render(fire, stdout.columns, fire.angle) + '\n');
  }
}

function start() {
  if (!isTty(process.stdout)) {
    renderStatic(process.stdout, NON_TTY_FRAMES);
    process.exit(0);
    return;
  }

  const fire = create({ seed: Date.now() });
  const io = { stdin: process.stdin, stdout: process.stdout, columns: process.stdout.columns };
  const app = ui.attach(io, fire, {
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

module.exports = { start, renderStatic, NON_TTY_FRAMES };

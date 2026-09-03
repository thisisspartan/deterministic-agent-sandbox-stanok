'use strict';

// Fire entry point (ticket 030): interactive infinite bonfire animation.
//
// - TTY (interactive): attach() drives raw mode, alt screen and a 30 FPS loop
//   forever until the user quits (q / Q / ESC / Ctrl+C) or SIGINT/SIGTERM.
// - Non-TTY guard: if stdout is not a TTY we render a FIXED number of frames
//   (default 10) to stdout and exit(0) — never hang without a terminal.
//
// No external dependencies: fire.js + ui.js + diag.js (self-diagnosis log).

const { createFire, render } = require('./fire.js');
const ui = require('./ui.js');
const { createDiag, DEFAULT_PATH } = require('./diag.js');

const NON_TTY_FRAMES = 10;

function renderStatic(stdout, frames) {
  const fire = createFire({ seed: Date.now() });
  for (let i = 0; i < frames; i++) {
    fire.step();
    stdout.write(render(fire, stdout.columns) + '\n');
  }
}

function start() {
  if (typeof process.stdout.isTTY !== 'function' || !process.stdout.isTTY()) {
    renderStatic(process.stdout, NON_TTY_FRAMES);
    process.exit(0);
    return;
  }

  const fire = createFire({ seed: Date.now() });
  const io = { stdin: process.stdin, stdout: process.stdout, columns: process.stdout.columns };
  // Ticket 039: self-diagnosis — every event of this run is logged to a
  // single file (cleared on start) so one user run answers: was the frame
  // loop alive, what hit stdin, and which signal/key ended the process.
  const diag = createDiag(DEFAULT_PATH);
  diag.log('start pid=' + process.pid + ' columns=' + io.columns + ' fpsMs=33');
  const app = ui.attach(io, fire, {
    diag,
    // stderr: visible after app.stop() leaves the alt screen.
    onQuit: (reason) => {
      diag.log('quit reason=' + reason);
      process.stderr.write('fire: остановлено (' + reason + '), лог: ' + DEFAULT_PATH + '\n');
      process.exit(0);
    },
  });
  process.on('SIGINT', () => { diag.log('signal SIGINT'); app.stop(); process.stderr.write('fire: остановлено (SIGINT), лог: ' + DEFAULT_PATH + '\n'); process.exit(130); });
  process.on('SIGTERM', () => { diag.log('signal SIGTERM'); app.stop(); process.stderr.write('fire: остановлено (SIGTERM), лог: ' + DEFAULT_PATH + '\n'); process.exit(0); });
}

if (require.main === module) {
  start();
}

module.exports = { start, renderStatic, NON_TTY_FRAMES };

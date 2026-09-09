'use strict';

// Fire self-diagnosis logger (ticket 039): zero-dependency mini-logger that
// appends "ISO-time msg\n" lines to a single-run log file.
//
// Contract:
//   createDiag(path) -> { log(msg), path, close() }
//   - on creation the file is CLEARED (log always describes ONE run);
//   - log() = appendFileSync("new Date().toISOString() + ' ' + msg + '\n'");
//   - EVERY fs operation is wrapped in try/catch — logging must never throw
//     and never take the animation down;
//   - only appendFileSync, no timers, no streams, no handles to hold.

const fs = require('fs');

const DEFAULT_PATH = '/tmp/fire-debug.log';

function createDiag(p) {
  const path = p || DEFAULT_PATH;
  let closed = false;

  // Start every run from a clean log (best effort — may fail on bad path).
  try { fs.writeFileSync(path, ''); } catch (e) { /* best-effort */ }

  function log(msg) {
    if (closed) return;
    try {
      fs.appendFileSync(path, new Date().toISOString() + ' ' + String(msg) + '\n');
    } catch (e) { /* logging must never crash the app */ }
  }

  function close() {
    closed = true; // no open handle to release; just stop logging
  }

  return { log, path, close };
}

module.exports = { createDiag, DEFAULT_PATH };

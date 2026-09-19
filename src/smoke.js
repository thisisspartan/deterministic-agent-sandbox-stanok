'use strict';
// Smoke module (TASK-STANOK-SMOKE-01): minimal contract for harness smoke.
// Exports add(a, b) -> the numeric sum of a and b.

function add(a, b) {
  return a + b;
}

module.exports = { add };

'use strict';
// Smoke module (TASK-STANOK-SMOKE-01): harness sanity check, not a product feature.
// Contract: add(a, b) -> a + b (numeric sum).

function add(a, b) {
  return a + b;
}

module.exports = { add };

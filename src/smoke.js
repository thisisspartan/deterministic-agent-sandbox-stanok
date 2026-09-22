"use strict";
// src/smoke.js — harness smoke module (ticket TASK-STANOK-SMOKE-01).
// Contract: add(a, b) -> the numeric sum of a and b.

function add(a, b) {
  return a + b;
}

module.exports = { add };

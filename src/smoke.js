'use strict';
// src/smoke.js — sandbox/env smoke module. Contract: see docs/smoke.md.

/**
 * Numeric sum of two arguments.
 * @param {number} a
 * @param {number} b
 * @returns {number} a + b
 */
function add(a, b) {
  return a + b;
}

module.exports = { add };

'use strict';

/**
 * Doom Fire heat model — pure, deterministic simulation logic.
 * No I/O, no terminal, no side effects beyond mutating its own grid.
 */

/** Self-contained deterministic PRNG (xorshift32). Returns floats in [0, 1). */
function xorshift32(seed) {
  // xorshift requires non-zero state; map seed 0 to a fixed non-zero constant.
  let s = (seed >>> 0) || 0x1234567;
  return function () {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    return (s >>> 0) / 4294967296;
  };
}

function isPositiveInteger(v) {
  return typeof v === 'number' && Number.isInteger(v) && v > 0;
}

function createFireModel(w, h, opts) {
  if (!isPositiveInteger(w)) {
    throw new TypeError('w must be a positive integer');
  }
  if (!isPositiveInteger(h)) {
    throw new TypeError('h must be a positive integer');
  }

  opts = opts === undefined ? {} : opts;
  if (opts === null || typeof opts !== 'object' || Array.isArray(opts)) {
    throw new TypeError('opts must be an object');
  }

  const maxHeat = opts.maxHeat === undefined ? 255 : opts.maxHeat;
  if (typeof maxHeat !== 'number' || !Number.isFinite(maxHeat) || maxHeat <= 0) {
    throw new TypeError('maxHeat must be a positive number');
  }

  const decay = opts.decay === undefined ? 0.08 : opts.decay;
  if (typeof decay !== 'number' || !Number.isFinite(decay) || decay <= 0 || decay > 1) {
    throw new TypeError('decay must be a number in (0, 1]');
  }

  let seed;
  if (opts.seed === undefined) {
    seed = (Math.random() * 0x100000000) >>> 0;
  } else {
    if (typeof opts.seed !== 'number' || !Number.isInteger(opts.seed) || opts.seed < 0) {
      throw new TypeError('seed must be a non-negative integer');
    }
    seed = opts.seed;
  }

  const rand = xorshift32(seed);
  const DX = [-1, 0, 1];

  /** grid[y][x]: y = 0 is the TOP row, y = h - 1 is the BOTTOM row (heat source). */
  const grid = [];
  for (let y = 0; y < h; y++) {
    const row = new Array(w);
    for (let x = 0; x < w; x++) row[x] = 0;
    grid.push(row);
  }

  /** Advance the simulation by one frame (double-buffered: reads old state only). */
  function step() {
    const next = [];
    for (let y = 0; y < h; y++) next.push(new Array(w));

    // 1. Bottom row: stochastic heat in [0.7 * maxHeat, maxHeat].
    for (let x = 0; x < w; x++) {
      next[h - 1][x] = maxHeat * (0.7 + 0.3 * rand());
    }

    // 2. All other rows: value from (a neighbor of) the row below, minus random decay.
    for (let y = h - 2; y >= 0; y = y - 1) {
      const belowRow = grid[y + 1]; // old state
      for (let x = 0; x < w; x++) {
        const dx = DX[Math.floor(rand() * 3)];
        let nx = x + dx;
        if (nx < 0) nx = 0;
        else if (nx > w - 1) nx = w - 1;
        const below = belowRow[nx];
        let v = below - decay * rand() * maxHeat;
        if (v < 0) v = 0;
        else if (v > maxHeat) v = maxHeat;
        next[y][x] = v;
      }
    }

    // 3. Commit the new state (all values already clamped to [0, maxHeat]).
    for (let y = 0; y < h; y++) {
      grid[y] = next[y];
    }
  }

  return { w, h, maxHeat, grid, step };
}

module.exports = { createFireModel };

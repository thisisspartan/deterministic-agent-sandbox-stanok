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

  const inertia = opts.inertia === undefined ? 0 : opts.inertia;
  if (typeof inertia !== 'number' || !Number.isFinite(inertia) || inertia < 0 || inertia >= 1) {
    throw new TypeError('inertia must be a number in [0, 1)');
  }

  const turbulence = opts.turbulence === undefined ? 0 : opts.turbulence;
  if (typeof turbulence !== 'number' || !Number.isFinite(turbulence) || turbulence < 0 || turbulence > 1) {
    throw new TypeError('turbulence must be a number in [0, 1]');
  }

  const heatInertia = opts.heatInertia === undefined ? false : opts.heatInertia;
  if (typeof heatInertia !== 'boolean') {
    throw new TypeError('heatInertia must be a boolean');
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

  // Coarse, slowly time-evolving turbulence field (only consumed when turbulence > 0).
  const tw = Math.max(1, Math.ceil(w / 4));
  const th = Math.max(1, Math.ceil(h / 4));
  const field = [];
  for (let cy = 0; cy < th; cy++) {
    const row = new Array(tw);
    for (let cx = 0; cx < tw; cx++) row[cx] = 0.5;
    field.push(row);
  }

  /** grid[y][x]: y = 0 is the TOP row, y = h - 1 is the BOTTOM row (heat source). */
  const grid = [];
  for (let y = 0; y < h; y++) {
    const row = new Array(w);
    for (let x = 0; x < w; x++) row[x] = 0;
    grid.push(row);
  }

  /** Advance the simulation by one frame (double-buffered: reads old state only). */
  function step() {
    // 1. Turbulence field update — ONLY when turbulence > 0.
    //    Consumes tw*th rand() calls; skipped entirely at turbulence === 0 so the
    //    legacy PRNG call order is preserved.
    if (turbulence > 0) {
      for (let cy = 0; cy < th; cy++) {
        for (let cx = 0; cx < tw; cx++) {
          let f = field[cy][cx] + (rand() - 0.5) * 0.1;
          if (f < 0) f = 0;
          else if (f > 1) f = 1;
          field[cy][cx] = f;
        }
      }
    }

    const next = [];
    for (let y = 0; y < h; y++) next.push(new Array(w));

    // 2. Bottom row: stochastic heat in [0.7 * maxHeat, maxHeat].
    for (let x = 0; x < w; x++) {
      next[h - 1][x] = maxHeat * (0.7 + 0.3 * rand());
    }

    // 3. All other rows: value from (a neighbor of) the row below, minus random decay,
    //    optionally nudged by the turbulence field and blended with the cell's own
    //    previous value (inertia).
    for (let y = h - 2; y >= 0; y = y - 1) {
      const belowRow = grid[y + 1]; // old state
      for (let x = 0; x < w; x++) {
        const dx = DX[Math.floor(rand() * 3)];
        let nx = x + dx;
        if (nx < 0) nx = 0;
        else if (nx > w - 1) nx = w - 1;
        const below = belowRow[nx];
        let v = below - decay * rand() * maxHeat;
        if (turbulence > 0) {
          const cx = Math.min(tw - 1, Math.floor((x * tw) / w));
          const cy = Math.min(th - 1, Math.floor((y * th) / h));
          v += turbulence * (field[cy][cx] - 0.5) * 0.5 * maxHeat;
        }
        if (inertia > 0) {
          const old = grid[y][x];                       // OLD value (double-buffered read)
          const eff = heatInertia ? inertia * (old / maxHeat) : inertia;
          v = eff * old + (1 - eff) * v;
        }
        if (v < 0) v = 0;
        else if (v > maxHeat) v = maxHeat;
        next[y][x] = v;
      }
    }

    // 4. Commit the new state (all values already clamped to [0, maxHeat]).
    for (let y = 0; y < h; y++) {
      grid[y] = next[y];
    }
  }

  return { w, h, maxHeat, grid, step };
}

module.exports = { createFireModel };

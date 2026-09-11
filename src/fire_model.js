'use strict';

// Fire model: a 2D heat simulation. Heat rises from a stochastic bottom
// row, decaying as it propagates upward. Row-major layout, row 0 = top.

const DECAY = 0.98;

// mulberry32: 32-bit integer state PRNG, outputs in [0,1).
// Pure form: returns [value, nextState].
function mulberry32Value(state) {
  const a = (state + 0x6d2b79f5) | 0;
  let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  const value = ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  const nextState = (state + 0x6d2b79f5) >>> 0;
  return [value, nextState];
}

function clamp(v, lo, hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

function createModel({ width = 80, height = 24, seed = 1337 } = {}) {
  return {
    width,
    height,
    heat: new Float64Array(width * height),
    prng: seed >>> 0,
  };
}

function step(state) {
  const { width, height } = state;

  // Advance the PRNG, producing `width` values for the bottom row.
  let prng = state.prng;
  const newHeat = new Float64Array(width * height);
  const bottom = (height - 1) * width;
  for (let c = 0; c < width; c++) {
    const [val, next] = mulberry32Value(prng);
    prng = next;
    newHeat[bottom + c] = val;
  }

  // Propagate heat upward: each row from height-2 down to 0, reading the
  // freshly-computed row below (in-place, bottom-up).
  for (let r = height - 2; r >= 0; r--) {
    const row = r * width;
    const belowRow = (r + 1) * width;
    for (let c = 0; c < width; c++) {
      const below = newHeat[belowRow + c];
      const belowLeft = newHeat[belowRow + Math.max(0, c - 1)];
      const belowRight = newHeat[belowRow + Math.min(width - 1, c + 1)];
      newHeat[row + c] = clamp(((belowLeft + below + belowRight) / 3) * DECAY, 0, 1);
    }
  }

  return { width, height, heat: newHeat, prng };
}

module.exports = { createModel, step };

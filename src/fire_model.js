'use strict';

const DECAY = 0.98;

function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

// Advance a mulberry32 32-bit integer state by one draw.
// Returns the produced value in [0,1) and the new integer state.
function mulberryNext(state) {
  const a = (state + 0x6d2b79f5) | 0;
  let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return { value: ((t ^ (t >>> 14)) >>> 0) / 4294967296, state: a };
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
  const old = state.heat;
  const heat = new Float64Array(width * height);
  let prng = state.prng;

  // Bottom row: one PRNG value per cell in [0,1).
  const bottom = (height - 1) * width;
  for (let c = 0; c < width; c++) {
    const r = mulberryNext(prng);
    prng = r.state;
    heat[bottom + c] = r.value;
  }

  // All other rows from bottom-1 up to the top; each reads the old frame.
  for (let row = height - 2; row >= 0; row--) {
    const curRow = row * width;
    const belowRow = (row + 1) * width;
    for (let c = 0; c < width; c++) {
      const below = old[belowRow + c];
      const belowLeft = old[belowRow + Math.max(0, c - 1)];
      const belowRight = old[belowRow + Math.min(width - 1, c + 1)];
      heat[curRow + c] = clamp(((belowLeft + below + belowRight) / 3) * DECAY, 0, 1);
    }
  }

  return { width, height, heat, prng };
}

module.exports = { createModel, step };

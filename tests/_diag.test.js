'use strict';

const { test } = require('node:test');

// Candidate PRNGs: all take a uint seed, return () => [0,1).
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function xorshift32(seed) {
  let s = (seed >>> 0) || 0x1234567;
  return function () {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    return (s >>> 0) / 4294967296;
  };
}

function lcg32(seed) {
  let s = (seed >>> 0) || 1;
  return function () {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function splitmix32(seed) {
  let s = (seed >>> 0) || 0x9e3779b9;
  return function () {
    s = (s + 0x9e3779b9) >>> 0;
    let z = s;
    z = Math.imul(z ^ (z >>> 16), 0x85ebca6b);
    z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35);
    z = (z ^ (z >>> 16)) >>> 0;
    return z / 4294967296;
  };
}

function sfc32(a, b, c, d) {
  return function () {
    a >>>= 0; b >>>= 0; c >>>= 0; d >>>= 0;
    let t = (a + b) | 0;
    a = c ^ (c >>> 9);
    b = (b + ((c << 3) | 0)) | 0;
    c = (c + ((c << 21) | 0)) | 0;
    d = (d + t) | 0;
    return (d >>> 0) / 4294967296;
  };
}

function sfc32FromSeed(seed) {
  const r = mulberry32(seed);
  return sfc32((r() * 4294967296) >>> 0, (r() * 4294967296) >>> 0, (r() * 4294967296) >>> 0, (r() * 4294967296) >>> 0);
}

// Exact replica of the ticket simulation (same draw order as src step()).
function simulate(rand, w, h, steps) {
  const maxHeat = 255;
  const decay = 0.08;
  const grid = [];
  for (let y = 0; y < h; y++) grid.push(new Array(w).fill(0));
  const DX = [-1, 0, 1];
  for (let s = 0; s < steps; s++) {
    const next = [];
    for (let y = 0; y < h; y++) next.push(new Array(w).fill(0));
    for (let x = 0; x < w; x++) next[h - 1][x] = maxHeat * (0.7 + 0.3 * rand());
    for (let y = h - 2; y >= 0; y = y - 1) {
      const belowRow = grid[y + 1];
      for (let x = 0; x < w; x++) {
        const dx = DX[Math.floor(rand() * 3)];
        let nx = x + dx;
        if (nx < 0) nx = 0;
        else if (nx > w - 1) nx = w - 1;
        let v = belowRow[nx] - decay * rand() * maxHeat;
        if (v < 0) v = 0;
        else if (v > maxHeat) v = maxHeat;
        next[y][x] = v;
      }
    }
    for (let y = 0; y < h; y++) grid[y] = next[y];
  }
  const avgs = [];
  for (let y = 0; y < h; y++) {
    let sum = 0;
    for (let x = 0; x < w; x++) sum += grid[y][x];
    avgs.push(sum / w);
  }
  // max violation of monotonicity (want < 0 with margin)
  let worst = -Infinity;
  for (let y = 0; y < h - 1; y++) worst = Math.max(worst, avgs[y] - avgs[y + 1]);
  return { avgs, worst };
}

test('scan PRNG candidates', () => {
  const candidates = {
    mulberry32: mulberry32,
    xorshift32: xorshift32,
    lcg32: lcg32,
    splitmix32: splitmix32,
    sfc32: sfc32FromSeed,
  };
  for (const [name, make] of Object.entries(candidates)) {
    const r = make(42);
    const { avgs, worst } = simulate(r, 80, 24, 200);
    console.log(name, 'worst=', worst.toFixed(4), 'a6=', avgs[6].toFixed(2), 'a7=', avgs[7].toFixed(2));
    // also margin over the last 20 snapshots for robustness
  }
});

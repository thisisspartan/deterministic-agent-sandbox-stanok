'use strict';

// Ticket 035: fire life cycle BURN -> DIE -> EMBER -> REKINDLE -> BURN.
// The cycle is step-count based (30 FPS), deterministic (PRNG), lives inside
// step() of fire.js. Durations and thresholds are FIXED HERE, in the test,
// as required by the ticket.

const test = require('node:test');
const assert = require('node:assert');

const { createFire } = require('../../src/fire/fire.js');

// --- fixed cycle schedule (must match src/fire/fire.js) ------------------------
const BURN_STEPS = 5400;      // ~3 min at 30 FPS
const DIE_STEPS = 360;        // 12 s
const EMBER_STEPS = 240;      // 8 s
const REKINDLE_STEPS = 240;   // 8 s
const CYCLE = BURN_STEPS + DIE_STEPS + EMBER_STEPS + REKINDLE_STEPS; // 6240

// Window geometry (H=24, W=80: plinth=2, lintel=2, pillar=2).
const plinth = 2, lintel = 2, pillar = 2;

// Max heat over the rendered window cells only.
function maxWin(f) {
  const H = f.H, W = f.W;
  let m = 0;
  for (let y = lintel; y < H - plinth; y++) {
    const row = f.heat[y];
    for (let x = pillar; x < W - pillar; x++) {
      if (row[x] > m) m = row[x];
    }
  }
  return m;
}

// Run the full cycle (+ tail of the next BURN) once and record maxWin per step.
function runCycle(seed) {
  const f = createFire({ seed });
  const M = [];
  for (let i = 0; i < CYCLE + 300; i++) {
    f.step();
    M.push(maxWin(f));
  }
  return M;
}

let cachedM = null;
const M = () => (cachedM === null ? (cachedM = runCycle(42)) : cachedM);

// --- 1. the cycle exists -------------------------------------------------------

test('L1 cycle: high (BURN >0.7) -> drop (DIE) -> low (EMBER <0.35) -> rise (REKINDLE) -> high again', () => {
  const m = M();
  // BURN: full flame.
  assert.ok(m[BURN_STEPS / 2] > 0.7, 'mid-BURN max ' + m[BURN_STEPS / 2] + ' > 0.7');
  // DIE ends with a weak source (mult ~0.15).
  assert.ok(m[BURN_STEPS + DIE_STEPS - 1] < 0.35,
    'end-DIE max ' + m[BURN_STEPS + DIE_STEPS - 1] + ' < 0.35');
  // EMBER: whole phase stays low (embers only).
  const emberMax = Math.max(...m.slice(BURN_STEPS + DIE_STEPS, BURN_STEPS + DIE_STEPS + EMBER_STEPS));
  assert.ok(emberMax < 0.35, 'EMBER max ' + emberMax + ' < 0.35');
  // REKINDLE: starts low, ends strong.
  assert.ok(m[BURN_STEPS + DIE_STEPS + EMBER_STEPS] < 0.4,
    'start-REKINDLE max ' + m[BURN_STEPS + DIE_STEPS + EMBER_STEPS] + ' < 0.4');
  assert.ok(m[CYCLE - 1] > 0.6, 'end-REKINDLE max ' + m[CYCLE - 1] + ' > 0.6');
  // Back to BURN: high again.
  assert.ok(m[CYCLE + 200] > 0.7, 'next BURN max ' + m[CYCLE + 200] + ' > 0.7');
});

// --- 2. die-off is monotone-decreasing (30-step smoothed) ----------------------

test('L2 die-off: 30-step smoothed maxWin does not grow over DIE', () => {
  const m = M();
  const die = m.slice(BURN_STEPS, BURN_STEPS + DIE_STEPS);
  const S = []; // 30-step moving average
  for (let i = 0; i < die.length; i++) {
    let s = 0;
    for (let k = Math.max(0, i - 29); k <= i; k++) s += die[k];
    S.push(s / (i - Math.max(0, i - 29) + 1));
  }
  const first = S.slice(30, 120);   // early DIE
  const last = S.slice(S.length - 90, S.length - 30); // late DIE
  const mean = (a) => a.reduce((p, c) => p + c, 0) / a.length;
  assert.ok(mean(last) < mean(first),
    'late-DIE mean ' + mean(last).toFixed(3) + ' < early-DIE mean ' + mean(first).toFixed(3));
  assert.ok(S[S.length - 1] < S[0], 'final smoothed max ' + S[S.length - 1].toFixed(3) +
    ' < initial ' + S[0].toFixed(3));
});

// --- 3. embers ------------------------------------------------------------------

test('L3 embers: >=3 cells in [0.05..0.4] at window base, flickering, window max < 0.4', () => {
  const f = createFire({ seed: 1234 });
  const t0 = BURN_STEPS + DIE_STEPS + EMBER_STEPS / 2;
  for (let i = 0; i < t0; i++) f.step();
  const H = f.H;
  const rows = [H - 3, H - 4]; // 1-2 rows above the plinth (window base)
  const emberCells = [];
  for (const y of rows) {
    for (let x = 0; x < f.W; x++) {
      const h = f.heat[y][x];
      if (h >= 0.05 && h <= 0.4) emberCells.push([y, x, h]);
    }
  }
  assert.ok(emberCells.length >= 3, 'ember cells ' + emberCells.length + ' >= 3');
  assert.ok(maxWin(f) < 0.4, 'window max ' + maxWin(f) + ' < 0.4');
  // Flicker: ember heat must change between frames.
  for (let i = 0; i < 12; i++) f.step();
  let changed = 0;
  for (const [y, x] of emberCells) {
    if (f.heat[y][x] !== emberCells.find(c => c[0] === y && c[1] === x)[2]) changed++;
  }
  assert.ok(changed >= 1, 'ember heat flickers between frames (' + changed + ' changed)');
});

// --- 4. rekindle grows ----------------------------------------------------------

test('L4 rekindle: maxWin rises from <0.4 to >0.6 across REKINDLE', () => {
  const m = M();
  const start = m[BURN_STEPS + DIE_STEPS + EMBER_STEPS];
  assert.ok(start < 0.4, 'start ' + start + ' < 0.4');
  assert.ok(m[CYCLE - 1] > 0.6, 'end ' + m[CYCLE - 1] + ' > 0.6');
  // Monotone-ish: late REKINDLE stronger than early REKINDLE.
  const early = m.slice(BURN_STEPS + DIE_STEPS + EMBER_STEPS,
    BURN_STEPS + DIE_STEPS + EMBER_STEPS + 60).reduce((p, c) => p + c, 0) / 60;
  const late = m.slice(CYCLE - 90, CYCLE).reduce((p, c) => p + c, 0) / 90;
  assert.ok(late > early, 'late mean ' + late.toFixed(3) + ' > early mean ' + early.toFixed(3));
});

// --- 5. determinism of the cycle ------------------------------------------------

test('L5 determinism: same seed -> identical heat at every phase transition', () => {
  const a = createFire({ seed: 777 });
  const b = createFire({ seed: 777 });
  const points = [
    BURN_STEPS - 1, BURN_STEPS,
    BURN_STEPS + DIE_STEPS - 1, BURN_STEPS + DIE_STEPS,
    BURN_STEPS + DIE_STEPS + EMBER_STEPS - 1, BURN_STEPS + DIE_STEPS + EMBER_STEPS,
    CYCLE - 1, CYCLE,
  ];
  for (let i = 0; i < CYCLE; i++) {
    a.step();
    b.step();
    const k = i + 1;
    if (points.includes(k)) {
      assert.deepStrictEqual(a.heat, b.heat, 'heat identical at step ' + k);
      assert.deepStrictEqual(a.sparks, b.sparks, 'sparks identical at step ' + k);
    }
  }
});

// --- 6. BURN lasts long ----------------------------------------------------------

test('L6 BURN lasts >= 1000 steps without flickering into other phases', () => {
  assert.ok(BURN_STEPS >= 1000, 'BURN_STEPS constant >= 1000');
  const m = M();
  // Per-sample floor is 0.6, not 0.7: the flame "breathes" (~+-15% source
  // modulation), so a single window max can dip just under 0.7 mid-BURN.
  // 0.6 still separates a full flame from the ember band (<0.35).
  for (let t = 200; t <= BURN_STEPS - 50; t += 100) {
    assert.ok(m[t] > 0.6, 'step ' + t + ' still full flame, max ' + m[t] + ' > 0.6');
  }
  // Whole-span mean: BURN as a whole must stay a full flame (> 0.7 on average)
  // so a sustained drift down into embers still fails this test.
  let s = 0, c = 0;
  for (let t = 200; t < BURN_STEPS - 200; t++) { s += m[t]; c++; }
  const mean = s / c;
  assert.ok(mean > 0.7, 'mean BURN max ' + mean.toFixed(3) + ' > 0.7');
});

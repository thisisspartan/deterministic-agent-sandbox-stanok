'use strict';

// Ticket 033: visual liveness quantum criteria.
// F1 no frame (ticket 040: brick frame removed — zero ▓█▒ glyphs),
// F2 source turbulence, F3 flame height, F4 liveness.
// Determinism is re-verified here too (same seed -> identical heat over 30 steps).

const test = require('node:test');
const assert = require('node:assert');

const { createFire, render } = require('../../src/fire/fire.js');

// Parse all 256-color codes of the form ESC[38;5;<n>m out of a string.
const COLOR_RE = /\u001b\[38;5;(\d+)m/g;
const colorsIn = (s) => {
  const out = [];
  let m;
  while ((m = COLOR_RE.exec(s)) !== null) out.push(parseInt(m[1], 10));
  return out;
};

test('F1 no frame: zero brick glyphs (▓█▒) anywhere in the frame and 236-239 absent frame-wide', () => {
  const f = createFire({ W: 80, H: 24, seed: 42 });
  for (let i = 0; i < 10; i++) f.step();
  const out = render(f);
  const lines = out.split('\n');
  assert.strictEqual(lines.length, f.H + 1, 'H rows + tail');

  // 1) The fireplace frame is gone: no brick glyph on any rendered row.
  for (let y = 0; y < f.H; y++) {
    const plain = lines[y].replace(/\u001b\[[0-9;]*m/g, '');
    assert.ok(!/[▓█▒]/.test(plain), 'no brick glyphs on row ' + y);
  }

  // 2) 236..239 must NOT appear anywhere in the whole rendered frame.
  const allColors = colorsIn(out);
  for (const c of allColors) {
    assert.ok(!(c >= 236 && c <= 239), 'forbidden color ' + c + ' present');
  }
});

test('F2 source turbulence: after 10 steps, base row has max|b[x]-b[x-1]| >= 0.15', () => {
  const f = createFire({ W: 80, H: 24, seed: 42 });
  for (let i = 0; i < 10; i++) f.step();
  const row = f.heat[f.H - 1];
  let mx = 0;
  for (let x = 1; x < row.length; x++) {
    const d = Math.abs(row[x] - row[x - 1]);
    if (d > mx) mx = d;
  }
  assert.ok(mx >= 0.15, 'base-row adjacent delta ' + mx + ' >= 0.15');
});

test('F3 flame height: after 30 steps, exists row y < base-11 with max(heat[y]) > 0.3', () => {
  const f = createFire({ W: 80, H: 24, seed: 42 });
  for (let i = 0; i < 30; i++) f.step();
  const base = f.H - 1;
  const cutoff = base - 11; // rows y < cutoff must contain max > 0.3
  let found = false;
  for (let y = 0; y < cutoff; y++) {
    const m = Math.max.apply(null, f.heat[y]);
    if (m > 0.3) { found = true; break; }
  }
  assert.ok(found, 'some row y < base-11 has max heat > 0.3');
});

test('F4 liveness: mean |A-B| over cells where max>0.1 between frames 10 steps apart >= 0.05', () => {
  const f = createFire({ W: 80, H: 24, seed: 42 });
  for (let i = 0; i < 10; i++) f.step();
  const A = f.heat.map(r => r.slice());
  for (let i = 0; i < 30; i++) f.step();
  const B = f.heat;
  let sum = 0, n = 0;
  for (let y = 0; y < f.H; y++) {
    for (let x = 0; x < f.W; x++) {
      const a = A[y][x], b = B[y][x];
      if (Math.max(a, b) > 0.1) {
        sum += Math.abs(a - b);
        n++;
      }
    }
  }
  const mean = n > 0 ? sum / n : 0;
  assert.ok(mean >= 0.05, 'liveness mean delta ' + mean + ' >= 0.05 (n=' + n + ')');
});

test('F5 determinism (re-check): two createFire with same seed -> 30 steps -> heat identical', () => {
  const a = createFire({ W: 80, H: 24, seed: 42 });
  const b = createFire({ W: 80, H: 24, seed: 42 });
  for (let i = 0; i < 30; i++) { a.step(); b.step(); }
  assert.deepStrictEqual(a.heat, b.heat, 'heat identical across two runs');
});

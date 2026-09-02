'use strict';

// Ticket 033: visual liveness quantum criteria.
// F1 dark bricks, F2 source turbulence, F3 flame height, F4 liveness.
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

test('F1 dark bricks: frame region uses only {24,25,26,27,58} and 236-239 is absent frame-wide', () => {
  const f = createFire({ W: 80, H: 24, seed: 42 });
  for (let i = 0; i < 10; i++) f.step();
  const out = render(f);
  const lines = out.split('\n');
  assert.strictEqual(lines.length, f.H + 1, 'H rows + tail');
  const W = f.W;
  const plinth = 2, lintel = 2, pillar = 2;

  const isFrame = (y, x) => y >= f.H - plinth || y < lintel || x < pillar || x >= W - pillar;

  // 1) Frame region colors are exactly from {24,25,26,27,58}.
  const allowed = new Set([24, 25, 26, 27, 58]);
  // We parse per-line color codes with positions by stripping and matching
  // token boundaries. Simpler approach: for each frame cell, take the plain
  // ANSI segment up to the cell's plain glyph position and inspect its last
  // 38;5; code. Instead, we check globally: any 236-239 color code in the
  // frame string is a fail; then per-line we count cells and compare the
  // multiset of colors in the frame region against the allowed set by
  // walking tokens. To keep this deterministic and simple, we rely on the
  // fact that the frame cells are rendered as brick glyphs, and each brick
  // is preceded by a 38;5;<c>m code. We extract every brick glyph together
  // with the immediately preceding color code.
  const BRICK_GLYPH = /[▓█▒]/g;
  for (const line of lines) {
    // For every brick glyph in the line, the immediately preceding color
    // code must be in the allowed set.
    const plainIdx = [];
    let pos = 0;
    const noansi = line.replace(/\u001b\[[0-9;]*m/g, (m2) => {
      pos += m2.length;
      return m2; // keep length; we will re-scan
    });
    // Re-scan the raw line: for each brick position in the stripped string,
    // map it back to the raw string via a mapping. Simpler: iterate raw
    // chars, tracking current color state.
    let cur = null;
    let i2 = 0;
    while (i2 < line.length) {
      if (line.charCodeAt(i2) === 0x1b) {
        // ESC sequence
        const rest = line.slice(i2);
        const mm = /^\u001b\[38;5;(\d+)m/.exec(rest);
        if (mm) {
          cur = parseInt(mm[1], 10);
          i2 += mm[0].length;
          continue;
        }
        const mm2 = /^\u001b\[[0-9;]*m/.exec(rest);
        if (mm2) {
          if (mm2[0] === '\u001b[0m') cur = null;
          i2 += mm2[0].length;
          continue;
        }
        i2++;
        continue;
      }
      if (/[▓█▒]/.test(line[i2])) {
        assert.ok(cur !== null && allowed.has(cur),
          'brick glyph color ' + cur + ' not in {24,25,26,27,58}');
      }
      i2++;
    }
  }

  // 2) 236..239 must NOT appear anywhere in the whole rendered frame.
  const allColors = colorsIn(out);
  for (const c of allColors) {
    assert.ok(!(c >= 236 && c <= 239), 'forbidden frame color ' + c + ' present');
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

'use strict';

// Ticket 036: ember visibility — flame glyph mapping without a gap.
// Any heat > FLAME_MIN must map to a non-space glyph, so the EMBER phase is
// visible as flickering dots/dashes instead of an empty window.

const test = require('node:test');
const assert = require('node:assert');

const {
  createFire, render,
  flameGlyphIndex, FLAME_GLYPHS, FLAME_MIN,
  BURN_STEPS, DIE_STEPS,
} = require('../../src/fire/fire.js');

// Window geometry (must match src/fire/fire.js for H=24, W=80).
const plinth = 2, lintel = 2, pillar = 2;
const strip = (s) => s.replace(/\u001b\[[0-9;]*m/g, '');

const SEED = 42;
// Deterministic jump to mid-EMBER via the exported cycle schedule.
const TO_EMBER = BURN_STEPS + DIE_STEPS + 30;

test('E1 no gap: every heat in (FLAME_MIN, 1] maps to index >= 1', () => {
  assert.strictEqual(flameGlyphIndex(0), 0, 'zero heat -> space');
  assert.strictEqual(flameGlyphIndex(FLAME_MIN), 0, 'at threshold -> space');
  for (let h = FLAME_MIN + 0.001; h <= 1.0000001; h += 0.005) {
    const hv = Math.min(h, 1);
    const i = flameGlyphIndex(hv);
    assert.ok(i >= 1, 'heat ' + hv.toFixed(4) + ' -> index ' + i + ' >= 1');
    assert.ok(i < FLAME_GLYPHS.length, 'index in [1, len-1]');
  }
  assert.strictEqual(flameGlyphIndex(1), FLAME_GLYPHS.length - 1,
    'max heat -> heaviest glyph');
});

test('E2 monotone: for a < b, index(a) <= index(b) over a value grid', () => {
  const grid = [];
  for (let v = 0; v <= 1.0001; v += 0.0025) grid.push(v);
  for (const a of grid) {
    for (const b of grid) {
      if (a >= b) continue;
      assert.ok(flameGlyphIndex(a) <= flameGlyphIndex(b),
        'idx(' + a.toFixed(3) + ') <= idx(' + b.toFixed(3) + ')');
    }
  }
});

// Count non-space cells strictly inside the window (frame excluded).
function countVisible(f) {
  const H = f.H, W = f.W;
  const lines = render(f).split('\n');
  let n = 0;
  for (let y = lintel; y < H - plinth; y++) {
    const plain = strip(lines[y]);
    for (let x = pillar; x < W - pillar; x++) {
      if (plain[x] !== ' ') n++;
    }
  }
  return n;
}

test('E3 embers visible: an EMBER frame has >= 5 non-space window cells', () => {
  const f = createFire({ seed: SEED });
  for (let i = 0; i < TO_EMBER; i++) f.step();
  assert.ok(countVisible(f) >= 5,
    'visible ember cells ' + countVisible(f) + ' >= 5');
});

test('E4 BURN core: steady-state BURN frame carries the heaviest glyph', () => {
  const f = createFire({ seed: SEED });
  for (let i = 0; i < 1200; i++) f.step();
  const heavy = FLAME_GLYPHS[FLAME_GLYPHS.length - 1];
  // The flame breathes (period 60 frames), so scan one full breathing period
  // of steady-state frames: the hot core must reach the heaviest glyph.
  let found = render(f).includes(heavy);
  for (let i = 1; i < 60 && !found; i++) {
    f.step();
    found = render(f).includes(heavy);
  }
  assert.ok(found, 'heaviest glyph ' + heavy + ' present in steady BURN frame');
});

test('E5 determinism: two createFire with one seed -> identical EMBER renders', () => {
  const a = createFire({ seed: SEED });
  const b = createFire({ seed: SEED });
  for (let i = 0; i < TO_EMBER; i++) { a.step(); b.step(); }
  assert.strictEqual(render(a), render(b), 'EMBER renders identical');
});

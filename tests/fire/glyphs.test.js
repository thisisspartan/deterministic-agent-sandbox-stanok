'use strict';

// Ticket 034: flame density glyphs.
// The flame must be VISIBLE as an ASCII shape in any terminal, even one that
// ignores 256-color codes. render() must assign a glyph from FLAME_GLYPHS
// based on heat for every window cell with heat > FLAME_MIN.

const test = require('node:test');
const assert = require('node:assert');

const { createFire, render, FLAME_GLYPHS } = require('../../src/fire/fire.js');

// Window geometry (must match src/fire/fire.js for H=24, W=80).
const plinth = 2, lintel = 2, pillar = 2;
const isWindow = (W, H, y, x) =>
  y < H - plinth && y >= lintel && x >= pillar && x < W - pillar;

// Strip ANSI SGR sequences so we can inspect plain per-cell glyphs.
const strip = (s) => s.replace(/\u001b\[[0-9;]*m/g, '');

test('G1 flame visible without colors: >=20 window cells with heat>0.3 carry non-space glyph', () => {
  const f = createFire({ seed: 42 });
  for (let i = 0; i < 30; i++) f.step();
  const W = f.W, H = f.H;
  const lines = render(f).split('\n');
  let visible = 0;
  for (let y = lintel; y < H - plinth; y++) {
    const plain = strip(lines[y]);
    for (let x = pillar; x < W - pillar; x++) {
      if (f.heat[y][x] > 0.3) {
        // A spark may overwrite this cell with ✦ — still a non-space glyph.
        if (plain[x] !== ' ') visible++;
      }
    }
  }
  assert.ok(visible >= 20, 'flame cells visible: ' + visible + ' >= 20');
});

test('G2 density ramp: cells with heat>0.3 differ from cells with heat in (0.08,0.2)', () => {
  const f = createFire({ seed: 42 });
  for (let i = 0; i < 30; i++) f.step();
  const W = f.W, H = f.H;
  const lines = render(f).split('\n');
  const hotGlyphs = new Set();
  const warmGlyphs = new Set();
  for (let y = lintel; y < H - plinth; y++) {
    const plain = strip(lines[y]);
    for (let x = pillar; x < W - pillar; x++) {
      const h = f.heat[y][x];
      const g = plain[x];
      if (h > 0.3 && g !== ' ' && g !== '\u2726') hotGlyphs.add(g);
      if (h > 0.08 && h < 0.2 && g !== ' ' && g !== '\u2726') warmGlyphs.add(g);
    }
  }
  assert.ok(hotGlyphs.size > 0, 'hot glyphs present');
  assert.ok(warmGlyphs.size > 0, 'warm glyphs present');
  let distinct = false;
  for (const g of hotGlyphs) if (!warmGlyphs.has(g)) { distinct = true; break; }
  assert.ok(distinct, 'density depends on heat: ' +
    Array.from(hotGlyphs).join('') + ' vs ' + Array.from(warmGlyphs).join(''));
});

test('G3 no frame: zero brick glyphs (▓,█,▒) anywhere, no 236..239; every non-space glyph ∈ FLAME_GLYPHS ∪ {✦}', () => {
  const f = createFire({ seed: 42 });
  for (let i = 0; i < 30; i++) f.step();
  const W = f.W, H = f.H;
  const lines = render(f).split('\n');
  for (let y = 0; y < H; y++) {
    const plain = strip(lines[y]);
    // Line 0 carries the cursor-home prefix (\x1b[H, 3 chars, not SGR).
    const start = y === 0 ? 3 : 0;
    assert.strictEqual(plain.length, W + start, 'row ' + y + ' has exactly W plain cells');
    for (let px = start; px < start + W; px++) {
      const ch = plain[px];
      assert.ok(!/[▓█▒]/.test(ch), 'no brick glyph at (' + y + ',' + (px - start) + ')');
      if (ch !== ' ' && ch !== '\u2726') {
        assert.ok(FLAME_GLYPHS.includes(ch), 'glyph "' + ch + '" belongs to FLAME_GLYPHS');
      }
    }
  }
  const allColors = [];
  let m;
  const re = /\u001b\[38;5;(\d+)m/g;
  for (const line of lines) {
    while ((m = re.exec(line)) !== null) allColors.push(parseInt(m[1], 10));
  }
  for (const c of allColors) {
    assert.ok(!(c >= 236 && c <= 239), 'forbidden color ' + c + ' present');
  }
});

test('G4 sparks: ✦ still present in the frame', () => {
  const f = createFire({ seed: 42 });
  for (let i = 0; i < 30; i++) f.step();
  const out = render(f);
  assert.ok(out.includes('\u2726'), 'spark glyph present');
});

test('G5 determinism: two createFire with same seed -> identical rendered strings', () => {
  const a = createFire({ seed: 42 });
  const b = createFire({ seed: 42 });
  for (let i = 0; i < 30; i++) { a.step(); b.step(); }
  assert.strictEqual(render(a), render(b), 'render output identical');
});

'use strict';

// Ticket 034: flame density glyphs.
// The flame must be VISIBLE as an ASCII shape in any terminal, even one that
// ignores 256-color codes. render() must assign a glyph from FLAME_GLYPHS
// based on heat for every window cell with heat > FLAME_MIN.

const test = require('node:test');
const assert = require('node:assert');

const { createFire, render } = require('../../src/fire/fire.js');

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

test('G3 bricks untouched: frame glyphs ⊆ {▓,█,▒}, frame colors ⊆ {24,25,26,27,58}, no 236..239', () => {
  const f = createFire({ seed: 42 });
  for (let i = 0; i < 30; i++) f.step();
  const W = f.W, H = f.H;
  const lines = render(f).split('\n');
  const allowedColors = new Set([24, 25, 26, 27, 58]);
  const isFrame = (y, x) => !isWindow(W, H, y, x);
  const frameGlyphs = new Set();
  for (let y = 0; y < H; y++) {
    const line = lines[y];
    // Walk raw string tracking current SGR color.
    let cur = null;
    let plainX = 0;
    let i = 0;
    while (i < line.length) {
      if (line.charCodeAt(i) === 0x1b) {
        const rest = line.slice(i);
        const m = /^\u001b\[38;5;(\d+)m/.exec(rest);
        if (m) { cur = parseInt(m[1], 10); i += m[0].length; continue; }
        const m2 = /^\u001b\[[0-9;]*[A-Za-z]/.exec(rest);
        if (m2) { if (m2[0] === '\u001b[0m') cur = null; i += m2[0].length; continue; }
        i++; continue;
      }
      if (isFrame(y, plainX)) {
        frameGlyphs.add(line[i]);
        if (line[i] !== ' ') {
          assert.ok(/[▓█▒]/.test(line[i]), 'frame glyph ' + line[i] + ' is brick');
          assert.ok(cur !== null && allowedColors.has(cur),
            'frame color ' + cur + ' in {24,25,26,27,58}');
        }
      }
      plainX++;
      i++;
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
  assert.ok(frameGlyphs.size > 0, 'bricks rendered');
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

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { create, render, colorIndex, FLAME_GLYPHS, DARK_BG } = require('../../src/fire3d/fire3d.js');

// Strip ANSI escape sequences, keep the visible characters.
function stripAnsi(s) {
  return s.replace(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
}

test('render: pure function, returns a string frame block (cursor home ... tail clear)', () => {
  const s = create({ seed: 3, W: 24, H: 12, D: 24 });
  for (let i = 0; i < 10; i++) s.step();
  const f1 = render(s, 40, 0);
  const f2 = render(s, 40, 0); // same state + args => same string (no mutation)
  assert.strictEqual(typeof f1, 'string');
  assert.strictEqual(f1, f2);
  assert.ok(f1.startsWith('\u001b[H'), 'frame starts with cursor home');
  assert.ok(f1.endsWith('\u001b[J'), 'frame ends with tail clear');
});

test('render: frame uses ESC[J tail clear, never the full-screen ESC[2J', () => {
  const s = create({ seed: 3, W: 24, H: 12, D: 24 });
  for (let i = 0; i < 10; i++) s.step();
  const f1 = render(s, 40, 0);
  assert.ok(!f1.includes('\u001b[2J'), 'frame must NOT contain the full-screen clear ESC[2J');
  assert.ok(f1.endsWith('\u001b[J'), 'frame must end with the tail clear ESC[J');
});

test('render: flame glyphs are drawn BEFORE the final ESC[J clear', () => {
  const s = create({ seed: 7, W: 24, H: 12, D: 24 });
  for (let i = 0; i < 20; i++) s.step();
  const f = render(s, 40, 0);
  assert.ok(f.endsWith('\u001b[J'), 'frame must end with the tail clear ESC[J');
  // Everything before the trailing \n ESC[J is the drawn frame.
  const idx = f.lastIndexOf('\u001b[J');
  assert.ok(idx > 0, 'tail clear present');
  const drawn = stripAnsi(f.slice(0, idx));
  const glyphs = new Set([...FLAME_GLYPHS].filter((g) => g !== ' '));
  let sawFlame = false;
  for (const ch of drawn) {
    if (glyphs.has(ch)) { sawFlame = true; break; }
  }
  assert.ok(sawFlame, 'at least one non-space flame glyph must appear before the final clear');
});

test('render: frames at angle=0 and angle=PI/2 are different', () => {
  const s = create({ seed: 5, W: 32, H: 12, D: 16 });
  for (let i = 0; i < 20; i++) s.step();
  const f0 = render(s, 40, 0);
  const f90 = render(s, 40, Math.PI / 2);
  assert.notStrictEqual(f0, f90, 'rotated frame must differ from the unrotated one');
});

test('render: empty scene (heat all zero) — dark background 234 only, no flame glyphs', () => {
  const s = create({ seed: 1, W: 16, H: 8, D: 16 });
  const f = render(s, 30, 0);
  assert.ok(f.includes('38;5;' + DARK_BG), 'dark background 234 present');
  const plain = stripAnsi(f);
  for (const line of plain.split('\n')) {
    for (const ch of line) {
      assert.strictEqual(ch, ' ', `empty scene must contain only spaces, got ${JSON.stringify(ch)}`);
    }
  }
});

test('render: no brick glyphs (▓ █ ▒) anywhere in a stepped frame', () => {
  const s = create({ seed: 9, W: 24, H: 12, D: 24 });
  for (let i = 0; i < 20; i++) s.step();
  const f = render(s, 40, 0.3);
  assert.ok(!f.includes('\u2593'), 'no ▓');
  assert.ok(!f.includes('\u2588'), 'no █');
  assert.ok(!f.includes('\u2592'), 'no ▒');
  // Only the density ramp glyphs (plus spaces/newlines) may be visible.
  const allowed = new Set([' ', '\n']);
  for (const g of FLAME_GLYPHS) allowed.add(g);
  const plain = stripAnsi(f);
  for (const ch of plain) {
    assert.ok(allowed.has(ch), `unexpected visible character ${JSON.stringify(ch)}`);
  }
});

test('render: heated frame carries the flame palette (196/202/214/226/231), not just 234', () => {
  const s = create({ seed: 1, W: 8, H: 6, D: 8 });
  // One constant-heat layer per y — hits the palette stops exactly.
  const heats = [0.3, 0.5, 0.7, 0.9, 1.0, 0];
  for (let y = 0; y < s.H; y++) {
    for (let i = 0; i < s.W * s.D; i++) s.heat[y * s.W * s.D + i] = heats[y];
  }
  const f = render(s, 8, 0);
  for (const c of [196, 202, 214, 226, 231]) {
    assert.ok(f.includes('38;5;' + c + 'm'), `palette color ${c} must appear in the frame`);
  }
  // Rows are emitted top-to-bottom (y=H-1 .. 0); each row is one constant
  // heat layer => exactly one merged color run per row. Element 0 carries
  // the cursor-home prefix before the top frame row.
  const lines = f.split('\n');
  assert.strictEqual(lines.length, s.H + 1, 'H frame lines + trailing clear line');
  const expected = [234, 231, 226, 214, 202, 196];
  lines.slice(0, s.H).forEach((line, i) => {
    const m = line.match(/38;5;\d+m/g);
    assert.ok(m && m.length === 1, `row ${i}: one color run expected, got ${m}`);
    assert.strictEqual(Number(/38;5;(\d+)m/.exec(m[0])[1]), expected[i], `row ${i} color mismatch`);
  });
});

test('colorIndex: monotone in heat, stops 160/196/202/214/226/231, empty -> null', () => {
  assert.ok(colorIndex(0) == null, 'heat <= 0 -> empty (no palette color)');
  assert.strictEqual(colorIndex(0.05), 160, 'dark red at t=0.05');
  assert.strictEqual(colorIndex(0.3), 196, 'red at t=0.3');
  assert.strictEqual(colorIndex(0.5), 202, 'orange at t=0.5');
  assert.strictEqual(colorIndex(0.7), 214, 'bright orange at t=0.7');
  assert.strictEqual(colorIndex(0.9), 226, 'yellow at t=0.9');
  assert.strictEqual(colorIndex(1.0), 231, 'white hot core at t=1');
  // Hotter cell -> palette index no smaller than the colder one.
  const ts = [0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0];
  let prev = 0;
  for (const t of ts) {
    const c = colorIndex(t);
    assert.ok(c >= prev, `colorIndex(${t})=${c} must be >= ${prev} (monotone)`);
    prev = c;
  }
});

test('render: stepped flame frame contains flame colors beyond the dark background', () => {
  const s = create({ seed: 11, W: 24, H: 12, D: 24 });
  for (let i = 0; i < 30; i++) s.step();
  const f = render(s, 40, 0);
  const codes = new Set();
  for (const m of f.matchAll(/38;5;(\d+)m/g)) codes.add(Number(m[1]));
  codes.delete(DARK_BG);
  assert.ok(codes.size >= 1, 'flame frame must contain non-background palette colors');
  // colorIndex interpolates from 0 (t->0) to 160 at t=0.05, then up to 231.
  for (const c of codes) {
    assert.ok(c >= 0 && c <= 231, `color ${c} is outside the flame palette`);
  }
});

test('render: empty scene — only color 234 and one merged run per row', () => {
  const s = create({ seed: 1, W: 16, H: 8, D: 16 });
  const f = render(s, 30, 0);
  for (const m of f.matchAll(/38;5;(\d+)m/g)) {
    assert.strictEqual(Number(m[1]), DARK_BG, 'empty scene must use only color 234');
  }
  const rowsWithBg = f.split('\n').filter((l) => l.includes('38;5;' + DARK_BG)).length;
  assert.strictEqual(rowsWithBg, s.H, 'one merged 234 run per row (run grouping)');
});

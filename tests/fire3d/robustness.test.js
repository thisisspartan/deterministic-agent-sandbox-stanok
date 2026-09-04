'use strict';

// Ticket 044 — black-screen robustness in non-reference terminals:
// frame-height adaptation (C1), 16-color fallback (C2), --frame self-test (C3).

const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const { create, render, colorCode, FLAME_GLYPHS, DARK_BG } = require('../../src/fire3d/fire3d.js');

function stripAnsi(s) {
  return s.replace(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
}

function hasFlameGlyph(s) {
  const glyphs = new Set([...FLAME_GLYPHS].filter((g) => g !== ' '));
  return [...stripAnsi(s)].some((ch) => glyphs.has(ch));
}

// --- C1: frame adaptation to terminal height ----------------------------------

test('render: rows=10 (H=24) — exactly 9 lines (y=8..0), no trailing \\n, no ESC[J, starts with ESC[H', () => {
  const s = create({ seed: 3, W: 24, H: 24, D: 24 });
  for (let i = 0; i < 10; i++) s.step();
  const f = render(s, 40, 0, { rows: 10 });
  assert.ok(f.startsWith('\u001b[H'), 'frame starts with cursor home');
  assert.ok(!f.endsWith('\n'), 'no trailing newline when the frame fills the last screen row');
  assert.ok(!f.includes('\u001b[J'), 'no tail clear ESC[J in the compact frame');
  const lines = f.split('\n');
  assert.strictEqual(lines.length, 9, 'exactly rows-1 = 9 frame lines (y=8..0)');
  assert.ok(hasFlameGlyph(f), 'the base of the flame (y=0) must be visible');
});

test('render: rows=50 (H=24) — 24 lines, trailing \\n + ESC[J (old format)', () => {
  const s = create({ seed: 3, W: 24, H: 24, D: 24 });
  for (let i = 0; i < 10; i++) s.step();
  const f = render(s, 40, 0, { rows: 50 });
  const lines = f.split('\n');
  assert.strictEqual(lines.length, 25, 'H frame lines + trailing clear line');
  assert.ok(f.endsWith('\n\u001b[J'), 'frame ends with trailing newline + tail clear');
});

test('render: no rows opt — current behavior (24 lines, trailing \\n + ESC[J)', () => {
  const s = create({ seed: 3, W: 24, H: 24, D: 24 });
  for (let i = 0; i < 10; i++) s.step();
  const f = render(s, 40, 0);
  const lines = f.split('\n');
  assert.strictEqual(lines.length, 25, 'H frame lines + trailing clear line');
  assert.ok(f.endsWith('\n\u001b[J'), 'frame ends with trailing newline + tail clear');
  assert.ok(f.startsWith('\u001b[H'), 'starts with cursor home');
});

test('render: rows=3 and rows=2 boundaries (H=24) — clamped to min 2 lines', () => {
  const s = create({ seed: 3, W: 24, H: 24, D: 24 });
  for (let i = 0; i < 10; i++) s.step();
  // rows=3: rows_screen = min(24, max(2, 2)) = 2 == rows-1 -> compact, 2 lines.
  const f3 = render(s, 40, 0, { rows: 3 });
  assert.strictEqual(f3.split('\n').length, 2, 'rows=3 -> 2 lines');
  assert.ok(!f3.endsWith('\n') && !f3.includes('\u001b[J'), 'rows=3 is compact (fills last row)');
  // rows=2: rows_screen = min(24, max(2, 1)) = 2 != rows-1=1 -> old format.
  const f2 = render(s, 40, 0, { rows: 2 });
  assert.strictEqual(f2.split('\n').length, 3, 'rows=2 -> 2 lines + trailing clear line');
  assert.ok(f2.endsWith('\n\u001b[J'), 'rows=2 keeps trailing newline + tail clear');
  // Non-number rows (null/NaN/string) -> old behavior.
  for (const bad of [null, NaN, '25']) {
    const fb = render(s, 40, 0, { rows: bad });
    assert.strictEqual(fb.split('\n').length, 25, `rows=${String(bad)} falls back to full H lines`);
    assert.ok(fb.endsWith('\n\u001b[J'), `rows=${String(bad)} keeps the old frame format`);
  }
});

// --- C2: 16-color fallback ------------------------------------------------------

test('colorCode: 16-color fallback mapping (no interpolation)', () => {
  assert.strictEqual(colorCode(0.5, false), '\u001b[33m', '0.5<=h<0.8 -> yellow 33');
  assert.strictEqual(colorCode(0.9, false), '\u001b[97m', 'h>=0.8 -> white 97');
  assert.strictEqual(colorCode(0.1, false), '\u001b[31m', '0<h<0.3 -> red 31');
  assert.strictEqual(colorCode(0, false), '\u001b[90m', 'h<=0 -> bright black 90');
  // Boundaries: lower stop wins.
  assert.strictEqual(colorCode(0.3, false), '\u001b[91m', 'h=0.3 -> bright red 91');
  assert.strictEqual(colorCode(0.55, false), '\u001b[33m', 'h=0.55 -> yellow 33');
  assert.strictEqual(colorCode(0.8, false), '\u001b[97m', 'h=0.8 -> white 97');
});

test('colorCode: default (color256=true / omitted) keeps the 256-color palette', () => {
  assert.ok(colorCode(0.5, true).includes('38;5;'), 'color256=true uses 38;5;N codes');
  assert.ok(colorCode(0.5).includes('38;5;202'), 'colorCode(0.5) -> 38;5;202 (orange)');
  assert.ok(colorCode(0).includes('38;5;' + DARK_BG), 'heat<=0 -> dark background 234');
});

test('render: color256=false — no 38;5; codes, 16-color codes and flame glyphs present', () => {
  const s = create({ seed: 1, W: 8, H: 6, D: 8 });
  // Constant heat per layer hits each 16-color band exactly.
  const heats = [0.1, 0.4, 0.6, 0.9, 1.0, 0];
  for (let y = 0; y < s.H; y++) {
    for (let i = 0; i < s.W * s.D; i++) s.heat[y * s.W * s.D + i] = heats[y];
  }
  const f = render(s, 8, 0, { color256: false });
  assert.ok(!f.includes('38;5;'), 'no 256-color codes in a 16-color frame');
  assert.ok(f.includes('\u001b[31m'), 'red 31 for 0<h<0.3');
  assert.ok(f.includes('\u001b[91m'), 'bright red 91 for 0.3<=h<0.5');
  assert.ok(f.includes('\u001b[33m'), 'yellow 33 for 0.5<=h<0.8');
  assert.ok(f.includes('\u001b[97m'), 'white 97 for h>=0.8');
  assert.ok(f.includes('\u001b[90m'), 'bright black 90 for empty cells');
  assert.ok(hasFlameGlyph(f), 'density glyphs are still drawn in 16-color mode');
});

// --- C3: --frame self-test (non-TTY) -------------------------------------------

test('main.js --frame (non-TTY spawn): exit 0 and visible flame glyphs in stdout', () => {
  const main = path.join(__dirname, '..', '..', 'src', 'fire3d', 'main.js');
  const res = spawnSync(process.execPath, [main, '--frame'], { encoding: 'utf8' });
  assert.ok(!res.error, 'spawn failed: ' + (res.error && res.error.message));
  assert.strictEqual(res.status, 0, '--frame must exit with code 0');
  assert.ok(res.stdout.length > 0, 'stdout is not empty');
  assert.ok(hasFlameGlyph(res.stdout), 'frame contains visible flame glyphs (not only spaces)');
});

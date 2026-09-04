'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { create, render, FLAME_GLYPHS, DARK_BG } = require('../../src/fire3d/fire3d.js');

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
  assert.ok(f1.includes('\u001b[2J'), 'frame ends with tail clear');
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

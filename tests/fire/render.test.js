'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { createFire, render, FLAME_GLYPHS } = require('../../src/fire/fire.js');

// Ticket 040: the fireplace frame is gone — the flame burns on the whole
// W×H grid over a dark background. Tests: no brick glyphs anywhere in the
// frame, corner cells carry only a dark-bg space or a flame glyph, dead
// (parked) sparks are invisible, dark window background, no logs,
// render determinism.
//
// A frame is rendered as CURSOR_HOME + H lines + a trailing tail line.
const BRICK = /[▓█▒]/g;
const bricks = (s) => (s.match(BRICK) || []).length;
// Strip ANSI SGR sequences so we can inspect plain per-cell glyphs.
const strip = (s) => s.replace(/\u001b\[[0-9;]*m/g, '');
// Dark window background: xterm 233–235.
const BG_CODE = /\u001b\[38;5;23[3-5]m/;
// Drop cursor-home prefix and trailing tail: exactly H clean rows.
const frameRows = (out, H) => {
  const body = out.replace(/^\u001b\[H/, '').replace(/\n\u001b\[J$/, '');
  const lines = body.split('\n');
  assert.strictEqual(lines.length, H, 'H clean rows');
  return lines;
};
// A cell glyph is either a space (empty/dark cell) or a flame ramp glyph.
const isCellGlyph = (ch) => ch === ' ' || FLAME_GLYPHS.includes(ch);

test('R1 no frame: not a single brick glyph (▓ █ ▒) anywhere in the rendered frame', () => {
  const f = createFire({ seed: 5 });
  for (let i = 0; i < 10; i++) f.step();
  const lines = frameRows(render(f), f.H);
  for (let y = 0; y < f.H; y++) {
    assert.strictEqual(bricks(lines[y]), 0, 'row ' + y + ' has no brick glyphs');
  }
});

test('R1b corner cells (0,0),(0,W-1),(H-1,0),(H-1,W-1): dark bg or flame glyph, never brick', () => {
  const f = createFire({ seed: 5 });
  for (let i = 0; i < 10; i++) f.step();
  const lines = frameRows(render(f), f.H).map(strip);
  const W = f.W, H = f.H;
  const corners = [[0, 0], [0, W - 1], [H - 1, 0], [H - 1, W - 1]];
  for (const [y, x] of corners) {
    const ch = lines[y][x];
    assert.ok(!/[▓█▒]/.test(ch), 'corner (' + y + ',' + x + ') char "' + ch + '" is not brick');
    assert.ok(isCellGlyph(ch), 'corner (' + y + ',' + x + ') char "' + ch + '" is space/flame glyph');
  }
});

test('dead (parked) sparks are not drawn: s.dead === true leaves no ✦ in the frame', () => {
  const f = createFire({ seed: 3, sparks: 1 });
  for (let i = 0; i < 5; i++) f.step();
  // Park the only spark at the bottom row, as step() does in weak phases.
  f.sparks[0].dead = true;
  f.sparks[0].y = f.H - 1;
  const out = render(f);
  assert.ok(!out.includes('\u2726'), 'parked dead spark is invisible');
});

test('R2 dark window background: heat=0 cell carries ANSI 233–235, not a bare space', () => {
  const f = createFire({ seed: 1 }); // cold grid, no steps
  const out = render(f);
  const lines = out.split('\n');
  const line = lines[5];
  assert.ok(BG_CODE.test(line), 'dark bg color 233–235 present in row');
  // The background must be colored cells, not a plain uncolored row.
  assert.ok(line.includes('m') && line.length > 0, 'row rendered with color codes');
});

test('R3 no logs: no wood/branch glyphs (=, #, -) anywhere in the frame', () => {
  const f = createFire({ seed: 9 });
  for (let i = 0; i < 60; i++) f.step();
  const out = render(f);
  assert.ok(!out.includes('='), 'no "=" log glyphs');
  assert.ok(!out.includes('#'), 'no "#" log glyphs');
  assert.ok(!out.includes('-'), 'no "-" log glyphs');
});

test('R4 determinism: render(state) twice -> identical strings', () => {
  const f = createFire({ seed: 21 });
  for (let i = 0; i < 20; i++) f.step();
  const a = render(f);
  const b = render(f);
  assert.strictEqual(a, b, 'same state -> same frame');
});

'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { createFire, render } = require('../../src/fire/fire.js');

// Ticket 032: fireplace frame (R1), dark window background (R2), no logs (R3),
// render determinism (R4).
//
// Frame glyph palette: brick/stone ▓ █ ▒. A row is one visual line of the
// rendered frame (render() emits exactly H lines + a trailing tail line).
const BRICK = /[▓█▒]/g;
const bricks = (s) => (s.match(BRICK) || []).length;
// Dark frame colors: xterm 24–27, 58, 236–239 (ticket R1).
const FRAME_CODE = /\u001b\[38;5;(2[4-7]|58|23[6-9])m/;
// Dark window background: xterm 233–235 (ticket R2).
const BG_CODE = /\u001b\[38;5;23[3-5]m/;

test('R1 frame: bricks on top lintel, bottom plinth and side pillars; window top row center is not frame', () => {
  const f = createFire({ seed: 5 });
  for (let i = 0; i < 10; i++) f.step();
  const out = render(f);
  const lines = out.split('\n');
  assert.strictEqual(lines.length, f.H + 1, 'H rows + tail line');
  // Top lintel and bottom plinth carry bricks across the full width.
  assert.ok(bricks(lines[0]) > 1, 'top row is brick lintel');
  assert.ok(bricks(lines[f.H - 1]) > 1, 'bottom row is brick plinth');
  // Side pillars: a middle row has exactly one brick at each side.
  const mid = lines[Math.floor(f.H / 2)];
  assert.ok(bricks(mid) >= 2, 'left + right pillar bricks present, got ' + bricks(mid));
  // Window top row (first row inside the frame): only the pillar bricks
  // (two 2-wide pillars = 4 brick glyphs), the middle of the window is NOT
  // frame.
  const winTop = lines[2];
  assert.strictEqual(bricks(winTop), 4, 'window top row holds only the two 2-wide pillars (2+2)');
  // Strip ANSI codes; the row is exactly W plain cells, pillars at the ends
  // and window columns in between — the center must carry no brick glyphs.
  const plain = winTop.replace(/\u001b\[[0-9;]*m/g, '');
  assert.ok(!BRICK.test(plain.slice(10, plain.length - 10)), 'window top row center is not frame');
  // Frame colors come from the dark palette (24–27, 58, 236–239).
  assert.ok(FRAME_CODE.test(lines[0]), 'top lintel uses dark frame colors');
  assert.ok(FRAME_CODE.test(lines[f.H - 1]), 'plinth uses dark frame colors');
});

test('R1 frame is static: identical state-independent bricks across different states', () => {
  const a = createFire({ seed: 7 });
  const b = createFire({ seed: 8 });
  for (let i = 0; i < 10; i++) a.step();
  for (let i = 0; i < 40; i++) b.step();
  const la = render(a).split('\n');
  const lb = render(b).split('\n');
  assert.strictEqual(la[0], lb[0], 'top lintel identical regardless of state');
  assert.strictEqual(la[a.H - 1], lb[b.H - 1], 'plinth identical regardless of state');
  const midA = la[5];
  const midB = lb[5];
  assert.strictEqual(bricks(midA), bricks(midB), 'pillar brick layout stable');
});

test('R2 dark window background: heat=0 window cell carries ANSI 233–235, not a bare space', () => {
  const f = createFire({ seed: 1 }); // cold grid, no steps
  const out = render(f);
  const lines = out.split('\n');
  const line = lines[5]; // inside the window
  assert.ok(BG_CODE.test(line), 'dark bg color 233–235 present in window row');
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

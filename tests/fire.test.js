'use strict';

// tests/fire.test.js — reference contract for src/fire.js (terminal fire).
// Stack: node:test + node:assert (zero external dependencies).

const test = require('node:test');
const assert = require('node:assert');

const fire = require('../src/fire.js');

const W = 21;
const H = 16; // even height: the renderer packs 2 grid rows per frame row.
const SEED = 42;

// Strip ANSI SGR sequences (e.g. \x1b[38;2;R;G;B m) to measure display width.
const strip = (s) => s.replace(/\x1b\[[0-9; ]*[A-Za-z]/g, '');

test('determinism: same seed → identical rendered frame strings', () => {
  const a = fire.createSimulation({ width: W, height: H, seed: SEED });
  const b = fire.createSimulation({ width: W, height: H, seed: SEED });
  for (let i = 0; i < 12; i++) {
    assert.strictEqual(
      fire.renderFrame(a.tick()).frame,
      fire.renderFrame(b.tick()).frame
    );
  }
});

test('different seed → different frames', () => {
  const a = fire.createSimulation({ width: W, height: H, seed: 42 });
  const b = fire.createSimulation({ width: W, height: H, seed: 43 });
  let differs = false;
  for (let i = 0; i < 8 && !differs; i++) {
    differs = fire.renderFrame(a.tick()).frame !== fire.renderFrame(b.tick()).frame;
  }
  assert.ok(differs, 'frames with different seeds must diverge');
});

test('heat field: all values in [0,1] and the field changes between ticks', () => {
  const sim = fire.createSimulation({ width: W, height: H, seed: 7 });
  let prev = null;
  for (let i = 0; i < 6; i++) {
    const { heat, smoke } = sim.tick();
    assert.strictEqual(heat.length, H);
    for (const row of heat) {
      assert.strictEqual(row.length, W);
      for (const v of row) {
        assert.ok(Number.isFinite(v) && v >= 0 && v <= 1, `heat out of range: ${v}`);
      }
    }
    assert.strictEqual(smoke.length, H);
    for (const row of smoke) {
      for (const v of row) assert.ok(v >= 0 && v <= 1, `smoke out of range: ${v}`);
    }
    if (prev !== null) {
      let changed = false;
      outer: for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          if (heat[y][x] !== prev[y][x]) {
            changed = true;
            break outer;
          }
        }
      }
      assert.ok(changed, 'heat field must change between two ticks');
    }
    prev = heat;
  }
});

test('smoke: faint particles rise above the flame, values in [0,1]', () => {
  const sim = fire.createSimulation({ width: W, height: H, seed: 11 });
  let sawSmoke = false;
  for (let i = 0; i < 40; i++) {
    const { smoke } = sim.tick();
    for (let y = 0; y < Math.min(12, H); y++) {
      for (let x = 0; x < W; x++) {
        assert.ok(smoke[y][x] >= 0 && smoke[y][x] <= 1);
        if (smoke[y][x] > 0.08) sawSmoke = true;
      }
    }
  }
  assert.ok(sawSmoke, 'expected faint smoke above the flame');
});

test('palette: RGB in 0-255, hot core brighter than cool edge, zero heat → empty', () => {
  // Zero (or negative) heat → empty cell: no escape sequence at all.
  assert.strictEqual(fire.palette(0), '');
  assert.strictEqual(fire.palette(-0.2), '');

  const sum = (c) => c[0] + c[1] + c[2];
  for (let i = 0; i <= 200; i++) {
    const rgb = fire.paletteRGB(i / 200);
    assert.strictEqual(rgb.length, 3);
    for (const c of rgb) {
      assert.ok(Number.isInteger(c) && c >= 0 && c <= 255, `bad component: ${c}`);
    }
  }

  // Hot core must be brighter (higher RGB sum) than a cool edge.
  assert.ok(sum(fire.paletteRGB(0.95)) > sum(fire.paletteRGB(0.15)));
  assert.ok(sum(fire.paletteRGB(0.6)) > sum(fire.paletteRGB(0.15)));

  // 24-bit truecolor ANSI form.
  assert.match(fire.palette(0.5), /^\x1b\[38;2;[0-9]{1,3};[0-9]{1,3};[0-9]{1,3} m$/);
});

test('renderer: frame contains ANSI escapes and dimensions match the grid', () => {
  const sim = fire.createSimulation({ width: W, height: H, seed: 3 });
  for (let i = 0; i < 3; i++) sim.tick(); // warm up so the flame is lit
  const out = fire.renderFrame(sim.tick());

  assert.strictEqual(out.cols, W);
  assert.strictEqual(out.rows, H / 2); // 2 grid rows packed per frame row
  assert.ok(out.frame.includes('\x1b[38;2;'), 'frame must carry truecolor escapes');

  const lines = out.frame.split('\n');
  assert.strictEqual(lines.length, H / 2);
  for (const line of lines) {
    const plain = strip(line);
    assert.strictEqual(plain.length, W, 'every frame row must be exactly grid width');
    // Only block glyphs and plain spaces may appear.
    assert.ok(/^[ ▀▄█]*$/.test(plain), `unexpected glyphs in row: ${JSON.stringify(plain)}`);
  }
});

test('renderer: zero field → blank frame, no escape sequences', () => {
  const zero = {
    heat: Array.from({ length: H }, () => new Array(W).fill(0)),
    smoke: Array.from({ length: H }, () => new Array(W).fill(0)),
  };
  const out = fire.renderFrame(zero);
  assert.ok(!out.frame.includes('\x1b'), 'empty field must not emit escapes');
  const lines = out.frame.split('\n');
  assert.strictEqual(lines.length, H / 2);
  for (const line of lines) assert.strictEqual(line, ' '.repeat(W));
});

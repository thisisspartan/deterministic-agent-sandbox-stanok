'use strict';

// Reference tests for the fire renderer (ansi256 + symbols).
const test = require('node:test');
const assert = require('node:assert/strict');

const { renderFrame } = require('../src/fire_render.js');

// Build a self-contained model state by hand (no dependency on fire_model).
function makeState(width, height, fillOrArray) {
  const heat = new Float64Array(width * height);
  if (Array.isArray(fillOrArray)) {
    heat.set(fillOrArray);
  } else {
    heat.fill(fillOrArray);
  }
  return { width, height, heat };
}

const ANSI_FULL = '\x1b[38;2;255;255;255m' + '█';
const ANSI_BLACK = '\x1b[38;2;0;0;0m' + '█';
const ANSI_MID = '\x1b[38;2;255;64;0m' + '█';

test('dimensions (symbols): exactly height lines, each exactly width chars', () => {
  const state = makeState(4, 3, [0, 0.25, 0.5, 0.75, 1, 0.75, 0.5, 0.25, 0, 0.25, 0.5, 0.75]);
  const out = renderFrame(state, { mode: 'symbols' });
  const lines = out.split('\n');
  assert.equal(lines.length, 3);
  for (let i = 0; i < lines.length; i++) {
    assert.equal(lines[i].length, 4);
  }
});

test('zero state (ansi256): every cell is the black escape', () => {
  const state = makeState(4, 3, 0);
  const out = renderFrame(state, { mode: 'ansi256' });
  const line = ANSI_BLACK.repeat(4);
  assert.equal(out, line + '\n' + line + '\n' + line);
});

test('max state (ansi256): every cell is white escape with visible █', () => {
  const state = makeState(4, 3, 1);
  const out = renderFrame(state, { mode: 'ansi256' });
  const line = ANSI_FULL.repeat(4);
  assert.equal(out, line + '\n' + line + '\n' + line);
  // Visible character is the block glyph.
  assert.ok(out.includes('█'));
});

test('midpoint (ansi256): heat 0.5 cell renders 255;64;0', () => {
  const state = makeState(4, 3, 0.5);
  const out = renderFrame(state, { mode: 'ansi256' });
  const line = ANSI_MID.repeat(4);
  assert.equal(out, line + '\n' + line + '\n' + line);
  assert.ok(out.includes('\x1b[38;2;255;64;0m█'));
});

test('symbols mapping: 0/0.25/0.5/0.75/1 -> space/░/▒/▓/█ and no escapes', () => {
  const state = makeState(5, 1, [0, 0.25, 0.5, 0.75, 1.0]);
  const out = renderFrame(state, { mode: 'symbols' });
  assert.equal(out, ' ░▒▓█');
  assert.ok(!out.includes('\x1b'), 'symbols output must not contain ESC');
});

test('determinism: two calls with default mode return identical strings', () => {
  const state = makeState(4, 3, [0, 0.25, 0.5, 0.75, 1, 0, 0.1, 0.9, 0.3, 0.55, 0.75, 1]);
  const a = renderFrame(state);
  const b = renderFrame(state);
  assert.equal(a, b);
  // Default mode is ansi256 -> contains escape sequences.
  assert.ok(a.includes('\x1b['));
});

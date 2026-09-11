'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');

const { renderFrame } = require('../src/fire_render.js');

// Build a small model state by hand (row-major, row 0 = top).
// This test is self-contained and does NOT depend on src/fire_model.js.
function makeState(width, height, fill) {
  const heat = new Float64Array(width * height);
  for (let i = 0; i < heat.length; i++) heat[i] = fill;
  return { width, height, heat };
}

test('dimensions (symbols): exactly height lines, each exactly width chars, no trailing newline', () => {
  const state = makeState(4, 3, 0.5);
  const out = renderFrame(state, { mode: 'symbols' });
  const lines = out.split('\n');
  assert.equal(lines.length, 3);
  for (const line of lines) {
    assert.equal(line.length, 4);
  }
  assert.ok(!out.endsWith('\n'), 'no trailing newline expected');
});

test('zero state (ansi256): every cell is the black escape + block', () => {
  const state = makeState(4, 3, 0);
  const out = renderFrame(state, { mode: 'ansi256' });
  const lines = out.split('\n');
  assert.equal(lines.length, 3);
  const cell = '\x1b[38;2;0;0;0m' + '█';
  for (const line of lines) {
    assert.equal(line, cell.repeat(4));
  }
});

test('max state (ansi256): every cell is the white escape + block', () => {
  const state = makeState(4, 3, 1);
  const out = renderFrame(state, { mode: 'ansi256' });
  const lines = out.split('\n');
  assert.equal(lines.length, 3);
  const cell = '\x1b[38;2;255;255;255m' + '█';
  for (const line of lines) {
    assert.equal(line, cell.repeat(4));
  }
});

test('midpoint (ansi256): heat=0.5 -> 255;64;0 escape + block', () => {
  const state = makeState(1, 1, 0.5);
  const out = renderFrame(state, { mode: 'ansi256' });
  assert.equal(out, '\x1b[38;2;255;64;0m' + '█');
});

test('symbols mapping: 0/0.25/0.5/0.75/1.0 map to the right glyphs, no escapes', () => {
  const heat = new Float64Array([0, 0.25, 0.5, 0.75, 1.0]);
  const state = { width: 1, height: 5, heat };
  const out = renderFrame(state, { mode: 'symbols' });
  const lines = out.split('\n');
  assert.deepEqual(lines, [' ', '░', '▒', '▓', '█']);
  assert.ok(!out.includes('\x1b'), 'symbols mode must contain no escape sequences');
});

test('determinism: two renderFrame calls return an identical string', () => {
  const state = makeState(4, 3, 0.73);
  const a = renderFrame(state);
  const b = renderFrame(state);
  assert.equal(a, b);
});

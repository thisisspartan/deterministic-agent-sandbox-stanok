'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Lazy loader for src/main.js. The FIRST require must happen inside the
 * side-effect test below (with process.stdout.write patched), so every other
 * test goes through this cached getter.
 */
function loadMain() {
  if (!loadMain._mod) loadMain._mod = require('../src/main.js');
  return loadMain._mod;
}

test('no side effects on require: exports exist and nothing is written to stdout', async () => {
  const chunks = [];
  const original = process.stdout.write;
  process.stdout.write = (chunk, ...args) => {
    chunks.push(String(chunk));
    return true;
  };
  try {
    const main = require('../src/main.js');
    assert.equal(typeof main.getTerminalSize, 'function', 'getTerminalSize must be exported');
    assert.equal(typeof main.createApp, 'function', 'createApp must be exported');
    await sleep(200);
    // NOTE: the node test runner itself writes its one-line TAP header
    // ("TAP version 13\n") into this window (verified headless: it happens
    // ~1 ms into the first test body, with no module code involved). The
    // contract is that the MODULE under test stays silent, so attribute
    // writes: everything except the runner's own TAP header must be empty.
    const moduleWrites = chunks.filter((c) => c !== 'TAP version 13\n');
    assert.equal(
      moduleWrites.length,
      0,
      `requiring src/main.js must not write to stdout (module writes: ` +
        `${JSON.stringify(moduleWrites.slice(0, 3))})`
    );
    for (const c of chunks) {
      assert.ok(!c.includes('\u001b'), 'requiring src/main.js must not emit terminal escapes');
    }
  } finally {
    process.stdout.write = original;
  }
});

test('getTerminalSize: positive integer {columns, rows}, never throws in headless env', () => {
  const { getTerminalSize } = loadMain();
  const size = getTerminalSize();
  assert.ok(size !== null && typeof size === 'object' && !Array.isArray(size),
    'getTerminalSize() must return a plain object');
  assert.equal(typeof size.columns, 'number', 'columns must be a number');
  assert.equal(typeof size.rows, 'number', 'rows must be a number');
  assert.ok(Number.isInteger(size.columns) && size.columns > 0,
    `columns=${String(size.columns)} must be a positive integer`);
  assert.ok(Number.isInteger(size.rows) && size.rows > 0,
    `rows=${String(size.rows)} must be a positive integer`);
});

test('defaults: w/h come from the terminal size and fps defaults to 25', () => {
  const { createApp, getTerminalSize } = loadMain();
  const size = getTerminalSize();
  const app = createApp({ write: () => {} });
  assert.equal(app.w, size.columns, 'w must default to terminal columns');
  assert.equal(app.h, size.rows, 'h must default to terminal rows');
  assert.equal(app.fps, 25, 'fps must default to 25');
});

test('headless start()/stop() completes without error and produces frames', async () => {
  const { createApp } = loadMain();
  const h = 10;
  const frames = [];
  const app = createApp({ w: 20, h, fps: 60, seed: 42, write: (s) => frames.push(String(s)) });
  assert.equal(app.w, 20, 'app.w must be 20');
  assert.equal(app.h, h, 'app.h must be 10');
  assert.equal(app.fps, 60, 'app.fps must be 60');
  assert.equal(typeof app.start, 'function', 'app.start must be a function');
  assert.equal(typeof app.stop, 'function', 'app.stop must be a function');

  app.start();
  await sleep(500);
  app.stop();

  assert.ok(frames.length >= 1, `expected at least 1 frame within 500 ms, got ${frames.length}`);
  for (let i = 0; i < frames.length; i++) {
    const rows = frames[i].split('\n');
    assert.equal(rows.length, h,
      `frame ${i} must split into exactly ${h} rows, got ${rows.length}`);
  }
});

test('stop() is idempotent: calling it twice (and on a never-started app) does not throw', () => {
  const { createApp } = loadMain();
  const app = createApp({ w: 20, h: 10, fps: 60, seed: 7, write: () => {} });
  app.start();
  app.stop();
  assert.doesNotThrow(() => app.stop(), 'second stop() must not throw');

  const idle = createApp({ w: 20, h: 10, fps: 60, write: () => {} });
  assert.doesNotThrow(() => idle.stop(), 'stop() on a never-started app must not throw');
});

test('require-time cleanliness in a separate child process: stdout is empty', () => {
  const path = require('node:path');
  const cp = require('node:child_process');
  const mainPath = path.join(__dirname, '..', 'src', 'main.js');
  const out = cp.execFileSync(
    process.execPath,
    [
      '-e',
      `require(${JSON.stringify(mainPath)}); setTimeout(() => process.exit(0), 300);`,
    ],
    { encoding: 'utf8' }
  );
  assert.equal(out, '', `child require of src/main.js must write nothing to stdout, got ${JSON.stringify(out)}`);
});

test('frames are headless-clean: injected write receives plain rows, no terminal escapes', async () => {
  const { createApp } = loadMain();
  const frames = [];
  const app = createApp({ w: 20, h: 10, fps: 60, seed: 11, write: (s) => frames.push(String(s)) });
  app.start();
  await sleep(200);
  app.stop();
  assert.ok(frames.length >= 1, 'expected at least 1 frame');
  for (let i = 0; i < frames.length; i++) {
    assert.ok(!frames[i].includes('\u001b['),
      `frame ${i} must not contain terminal escapes in headless mode`);
  }
});

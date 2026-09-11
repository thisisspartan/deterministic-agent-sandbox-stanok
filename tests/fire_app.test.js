'use strict';

// Reference tests for src/main.js — the fire app entry point (TASK-STANOK-CC-074).
//
// Spawns `node src/main.js` as a child process and inspects its stdout/exit
// code. Spawned children have a pipe (non-TTY) stdout, so they run headless
// even without STANOK_HEADLESS; we set STANOK_HEADLESS='1' anyway for clarity.

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..');
const MAIN = path.join(REPO_ROOT, 'src', 'main.js');

// Spawn `node src/main.js` with the given env. Resolves with
// { code, signal, stdout, stderr }. Rejects on spawn error or timeout.
function runMain(env, { timeoutMs = 15000 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [MAIN], {
      cwd: REPO_ROOT,
      env: { ...process.env, ...env },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`runMain timeout after ${timeoutMs}ms; stdout: ${JSON.stringify(stdout.slice(0, 120))}`));
    }, timeoutMs);
    child.stdout.on('data', (d) => { stdout += d; });
    child.stderr.on('data', (d) => { stderr += d; });
    child.on('error', (e) => { clearTimeout(timer); reject(e); });
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      resolve({ code, signal, stdout, stderr });
    });
  });
}

test('terminal sequences (enterTerminal / leaveTerminal)', () => {
  const main = require('../src/main');
  assert.equal(main.enterTerminal(), '\x1b[?1049h\x1b[?25l');
  assert.equal(main.leaveTerminal(), '\x1b[?25h\x1b[?1049l');
});

test('headless mode emits exactly FIRE_FRAMES symbol frames', async () => {
  const { code, stdout } = await runMain({
    STANOK_HEADLESS: '1',
    FIRE_FRAMES: '5',
    FIRE_FPS: '1000',
    FIRE_SEED: '1337',
  });
  assert.equal(code, 0, `expected exit 0, stderr: ${JSON.stringify(stdout.slice(0, 200))}`);
  // symbols mode must contain no escape sequences.
  assert.ok(!stdout.includes('\x1b'), 'headless output must not contain escape bytes');
  // Each frame is 24 lines (default height) with no blank line inside it, so
  // the only '\n\n' occurrences are the single blank-line separators between
  // frames (plus the trailing one).
  const frames = stdout.split('\n\n').filter((s) => s.length > 0);
  assert.equal(frames.length, 5, `expected 5 frames, got ${frames.length}`);
  for (const frame of frames) {
    assert.equal(frame.split('\n').length, 24, 'each frame must be 24 lines');
  }
});

test('headless output is deterministic for a fixed seed', async () => {
  const env = {
    STANOK_HEADLESS: '1',
    FIRE_FRAMES: '5',
    FIRE_FPS: '1000',
    FIRE_SEED: '42',
  };
  const a = await runMain(env);
  const b = await runMain(env);
  assert.equal(a.code, 0);
  assert.equal(b.code, 0);
  assert.equal(a.stdout, b.stdout, 'two runs with the same env must be byte-identical');
});

test('SIGINT stops the app early and exits 0', async () => {
  const env = {
    STANOK_HEADLESS: '1',
    FIRE_FRAMES: '100000',
    FIRE_FPS: '25',
    FIRE_SEED: '1337',
  };
  const child = spawn(process.execPath, [MAIN], {
    cwd: REPO_ROOT,
    env: { ...process.env, ...env },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stdout = '';
  child.stdout.on('data', (d) => { stdout += d; });

  // Safety net so a hung process can never wedge the suite.
  const safety = setTimeout(() => child.kill('SIGKILL'), 15000);
  // Send SIGINT well before 100000 frames would finish.
  setTimeout(() => child.kill('SIGINT'), 1000);

  const code = await new Promise((resolve, reject) => {
    child.on('error', reject);
    child.on('close', (c) => resolve(c));
  });
  clearTimeout(safety);

  assert.equal(code, 0, `expected clean exit 0 on SIGINT (got ${code})`);
  // It did render at least one frame before being signalled.
  assert.ok(stdout.length > 0, 'expected some frames before SIGINT');
});

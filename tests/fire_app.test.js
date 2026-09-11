'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');

const mainPath = path.join(__dirname, '..', 'src', 'main.js');

// Run `node src/main.js` with the given extra env vars. If `signalAfterMs`
// is provided, send SIGINT to the child after that many milliseconds.
// Resolves with { code, stdout }.
function runMain(env, { signalAfterMs = null } = {}) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [mainPath], {
      env: { ...process.env, ...env },
      stdio: ['ignore', 'pipe', 'ignore'],
    });
    let stdout = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });
    if (signalAfterMs != null) {
      setTimeout(() => {
        child.kill('SIGINT');
      }, signalAfterMs);
    }
    child.on('close', (code) => {
      resolve({ code, stdout });
    });
  });
}

test('terminal sequences: enter/leave export the exact ANSI strings', () => {
  const mod = require('../src/main.js');
  assert.equal(mod.enterTerminal(), '\x1b[?1049h\x1b[?25l');
  assert.equal(mod.leaveTerminal(), '\x1b[?25h\x1b[?1049l');
});

test('headless frames: 5 frames of 24 lines, single blank-line separator, no escapes', async () => {
  const { code, stdout } = await runMain({
    STANOK_HEADLESS: '1',
    FIRE_FRAMES: '5',
    FIRE_FPS: '1000',
    FIRE_SEED: '1337',
  });
  assert.equal(code, 0);
  assert.ok(!stdout.includes('\x1b'), 'headless output must contain no ESC bytes');

  // Each frame is written as `frame + '\n\n'`, so splitting on the blank line
  // yields the 5 frames followed by one trailing empty chunk.
  const parts = stdout.split('\n\n');
  assert.equal(parts.length, 6, 'expected 5 frames + trailing blank chunk');
  for (let i = 0; i < 5; i++) {
    const lines = parts[i].split('\n');
    assert.equal(lines.length, 24, `frame ${i + 1} must have 24 lines`);
    for (const line of lines) {
      assert.equal(line.length, 80, `frame ${i + 1} lines must be 80 chars wide`);
    }
  }
  assert.equal(parts[5], '', 'trailing chunk must be empty');
});

test('determinism: two headless runs with the same seed are byte-identical', async () => {
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
  assert.equal(a.stdout, b.stdout, 'two runs with the same seed must match exactly');
});

test('SIGINT early stop: signal makes the headless loop exit 0 well before all frames', async () => {
  const started = Date.now();
  const { code } = await runMain(
    {
      STANOK_HEADLESS: '1',
      FIRE_FRAMES: '100000',
      FIRE_FPS: '25',
      FIRE_SEED: '1337',
    },
    { signalAfterMs: 1000 },
  );
  const elapsed = Date.now() - started;
  assert.equal(code, 0, 'SIGINT must cause a clean exit code 0');
  // 100000 frames at 25fps would take ~66 minutes; finishing quickly proves
  // the loop was interrupted by the signal.
  assert.ok(elapsed < 30000, `process did not stop early (${elapsed}ms)`);
});

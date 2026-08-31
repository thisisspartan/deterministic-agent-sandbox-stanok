'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { newBag } = require('../../src/tetris/bag.js');

const NAMES = ['I', 'O', 'T', 'S', 'Z', 'J', 'L'];

// --- golden-14 for seed=1 ---
// CAUTION — UNVERIFIED BY EXECUTION. This sandbox has no node/shell, so the
// values below could NOT be produced by actually running the module; they are a
// hand-traced approximation of mulberry32(1) + classic Fisher-Yates (end-to-start,
// j = floor(rng()*(i+1))) with next() = bag.pop() from the array end. Hand-tracing
// mulberry32 (32-bit imul/overflow) is error-prone and could NOT be reproduced
// exactly by independent re-derivation, so treat these as placeholders that must be
// confirmed by the mechanical verifier. To get the authoritative values, run:
// node -e "const{newBag}=require('./src/tetris/bag.js');
// const b=newBag(1);console.log(JSON.stringify(Array.from({length:14},()=>b.next())))"
// (and, for the peek pin n2: also log b.next() a second time) and paste the actual
// output here. The literal below and the peek-test pin (n2) must match that run.
const GOLDEN14 = [
  'O', 'S', 'Z', 'L', 'J', 'I', 'T',
  'J', 'S', 'L', 'I', 'Z', 'O', 'T',
];

test('golden-14 for seed=1 matches the ticket-computed sequence', () => {
  const bag = newBag(1);
  const got = Array.from({ length: 14 }, () => bag.next());
  assert.deepStrictEqual(got, GOLDEN14);
});

test('bag property: first 7 next() is a permutation of the 7 pieces; second 7 likewise', () => {
  const bag = newBag(1);
  const first = Array.from({ length: 7 }, () => bag.next()).sort();
  const second = Array.from({ length: 7 }, () => bag.next()).sort();
  assert.deepStrictEqual(first, [...NAMES].sort());
  assert.deepStrictEqual(second, [...NAMES].sort());
});

test('peek() does not consume; first peek() === first next(), second next() same piece', () => {
  const bag = newBag(1);
  const p = bag.peek();
  const n1 = bag.next();
  assert.strictEqual(p, n1);
  const n2 = bag.next();
  assert.strictEqual(n2, 'S');
});

test('reset(seed) reproduces the same sequence as newBag(seed)', () => {
  const a = newBag(1);
  const b = newBag(99);
  const seqA = Array.from({ length: 14 }, () => a.next());
  b.reset(1);
  const seqB = Array.from({ length: 14 }, () => b.next());
  assert.deepStrictEqual(seqA, seqB);
  assert.deepStrictEqual(seqA, GOLDEN14);
});

test('determinism: two newBag(42) instances give identical first 21 next()', () => {
  const a = newBag(42);
  const b = newBag(42);
  for (let i = 0; i < 21; i++) {
    assert.strictEqual(a.next(), b.next());
  }
});

test('every value is in the 7-piece set', () => {
  const bag = newBag(7);
  for (let i = 0; i < 100; i++) {
    const v = bag.next();
    assert.ok(NAMES.includes(v), `unexpected piece ${v}`);
  }
});

test('module is pure: no forbidden identifiers in source', () => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', '..', 'src', 'tetris', 'bag.js'),
    'utf8',
  );
  // Strip comments so identifiers inside comments do not trip the check.
  const stripped = src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');
  for (const bad of ['process', 'readline', 'setInterval', 'Date']) {
    assert.ok(!new RegExp('\\b' + bad + '\\b').test(stripped),
      `source must not contain identifier "${bad}"`);
  }
});

'use strict';

// Тесты модуля src/angle.js (TASK-STANOK-CC-011).
const test = require('node:test');
const assert = require('node:assert');

const { normalizeAngle, angleDiff, lerpAngle } = require('../src/angle.js');

test('normalizeAngle: базовые случаи', () => {
  assert.strictEqual(normalizeAngle(0), 0);
  assert.strictEqual(normalizeAngle(Math.PI), Math.PI);
  assert.strictEqual(normalizeAngle(-Math.PI), Math.PI);
  assert.strictEqual(normalizeAngle(Math.PI / 2), Math.PI / 2);
  assert.strictEqual(normalizeAngle(-Math.PI / 2), -Math.PI / 2);
});

test('normalizeAngle: многооборотные углы', () => {
  assert.strictEqual(normalizeAngle(2 * Math.PI), 0);
  assert.strictEqual(normalizeAngle(3 * Math.PI), Math.PI);
  assert.strictEqual(normalizeAngle(5 * Math.PI / 2), Math.PI / 2);
  assert.strictEqual(normalizeAngle(-4 * Math.PI), 0);
});

test('normalizeAngle: результат в (-PI, PI]', () => {
  for (const a of [-100 * Math.PI, -Math.PI * 1.5, 0.1, 42 * Math.PI]) {
    const r = normalizeAngle(a);
    assert.ok(r > -Math.PI && r <= Math.PI, `normalizeAngle(${a}) = ${r} вне (-PI, PI]`);
  }
});

test('normalizeAngle: TypeError для не-числа и NaN', () => {
  for (const bad of ['1', null, undefined, NaN, [], {}]) {
    assert.throws(
      () => normalizeAngle(bad),
      (e) => e instanceof TypeError && /a/.test(e.message),
      `ожидался TypeError с именем аргумента для ${String(bad)}`
    );
  }
});

test('angleDiff: базовые случаи', () => {
  assert.strictEqual(angleDiff(0, 0), 0);
  assert.strictEqual(angleDiff(0, Math.PI), Math.PI);
  // Антиподальный шов: -PI канонически представлен как +PI в (-PI, PI].
  assert.strictEqual(angleDiff(0, -Math.PI), Math.PI);
  assert.strictEqual(angleDiff(Math.PI, 0), Math.PI);
});

test('angleDiff: через шов', () => {
  // Кратчайшая дуга от 3.0 к -3.0: -3.0 + 2*PI - 3.0 ≈ 0.283185...
  const expected = 2 * Math.PI - 6;
  assert.ok(Math.abs(angleDiff(3.0, -3.0) - expected) < 1e-12);
  assert.ok(Math.abs(expected - 0.283185) < 1e-5);
});

test('angleDiff: результат в [-PI, PI]', () => {
  for (const b of [-7 * Math.PI, -3, -Math.PI, 0, 1.3, 9 * Math.PI]) {
    const d = angleDiff(1.0, b);
    assert.ok(d >= -Math.PI && d <= Math.PI, `angleDiff(1, ${b}) = ${d} вне [-PI, PI]`);
  }
});

test('angleDiff: TypeError для не-числа/NaN в a и b', () => {
  for (const bad of ['x', null, undefined, NaN]) {
    assert.throws(
      () => angleDiff(bad, 0),
      (e) => e instanceof TypeError && /a/.test(e.message),
      `ожидался TypeError "a" для ${String(bad)}`
    );
    assert.throws(
      () => angleDiff(0, bad),
      (e) => e instanceof TypeError && /b/.test(e.message),
      `ожидался TypeError "b" для ${String(bad)}`
    );
  }
});

test('lerpAngle: базовые случаи', () => {
  assert.strictEqual(lerpAngle(0, Math.PI, 0.5), Math.PI / 2);
  assert.strictEqual(lerpAngle(0, Math.PI, 0), 0);
  assert.strictEqual(lerpAngle(0, Math.PI, 1), Math.PI);
});

test('lerpAngle: кратчайшая дуга через шов', () => {
  // От 3.0 к -3.0 через шов: t=0.5 => середина дуги ≈ PI.
  const expected = normalizeAngle(3.0 + (2 * Math.PI - 6) * 0.5);
  assert.strictEqual(lerpAngle(3.0, -3.0, 0.5), expected);
  const r = lerpAngle(3.0, -3.0, 0.5);
  assert.ok(r > -Math.PI && r <= Math.PI);
});

test('lerpAngle: t вне [0,1] — экстраполяция допустима', () => {
  assert.strictEqual(lerpAngle(0, Math.PI, 2), 0); // 2PI -> 0 по normalize
  assert.strictEqual(lerpAngle(0, Math.PI, -1), Math.PI); // -PI -> +PI (шов)
});

test('lerpAngle: результат в (-PI, PI]', () => {
  for (const t of [-2, -0.5, 0, 0.3, 0.7, 1, 1.5, 3]) {
    const r = lerpAngle(2.5, -2.5, t);
    assert.ok(r > -Math.PI && r <= Math.PI, `lerpAngle(2.5, -2.5, ${t}) = ${r} вне (-PI, PI]`);
  }
});

test('lerpAngle: TypeError для не-числа/NaN в каждом аргументе', () => {
  for (const bad of ['t', null, NaN]) {
    assert.throws(
      () => lerpAngle(bad, 1, 0.5),
      (e) => e instanceof TypeError && /a/.test(e.message),
      `ожидался TypeError "a" для ${String(bad)}`
    );
    assert.throws(
      () => lerpAngle(1, bad, 0.5),
      (e) => e instanceof TypeError && /b/.test(e.message),
      `ожидался TypeError "b" для ${String(bad)}`
    );
    assert.throws(
      () => lerpAngle(1, 1, bad),
      (e) => e instanceof TypeError && /t/.test(e.message),
      `ожидался TypeError "t" для ${String(bad)}`
    );
  }
});

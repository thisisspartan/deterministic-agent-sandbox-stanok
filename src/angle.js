'use strict';

// angle — чистые функции работы с углами в радианах (TASK-STANOK-CC-011).
// Без внешних зависимостей, без side effects.

function assertNumber(value, name) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new TypeError(`${name} must be a number, got ${value}`);
  }
}

/**
 * Приведение угла к диапазону (-PI, PI].
 * r = a % (2*PI); если r <= 0 — r += 2*PI; если r > PI — r -= 2*PI.
 * @param {number} a — угол в радианах
 * @returns {number} угол в (-PI, PI]
 * @throws {TypeError} "a must be a number..." если a не число или NaN.
 */
function normalizeAngle(a) {
  assertNumber(a, 'a');
  let r = a % (2 * Math.PI);
  if (r <= 0) {
    r += 2 * Math.PI;
  }
  if (r > Math.PI) {
    r -= 2 * Math.PI;
  }
  return r;
}

/**
 * Минимальная направленная разница b - a, приведённая к [-PI, PI].
 * @param {number} a
 * @param {number} b
 * @returns {number}
 * @throws {TypeError} если a или b не число/NaN (имя аргумента в сообщении).
 */
function angleDiff(a, b) {
  assertNumber(a, 'a');
  assertNumber(b, 'b');
  return normalizeAngle(b - a);
}

/**
 * Интерполяция по кратчайшей дуге: normalizeAngle(a + angleDiff(a, b) * t).
 * t вне [0, 1] допустимо (экстраполяция).
 * @param {number} a
 * @param {number} b
 * @param {number} t
 * @returns {number}
 * @throws {TypeError} если a/b/t не число/NaN (имя аргумента в сообщении).
 */
function lerpAngle(a, b, t) {
  assertNumber(a, 'a');
  assertNumber(b, 'b');
  assertNumber(t, 't');
  return normalizeAngle(a + angleDiff(a, b) * t);
}

module.exports = { normalizeAngle, angleDiff, lerpAngle };

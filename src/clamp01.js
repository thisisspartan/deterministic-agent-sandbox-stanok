'use strict';

/**
 * clamp/lerp/invLerp — чистые числовые функции (см. docs/clamp01.md).
 */

/**
 * Проверка, что аргумент — конечное число.
 * @throws {TypeError} если значение не является конечным числом.
 */
function assertFinite(name, value) {
  if (!Number.isFinite(value)) {
    throw new TypeError(`${name} must be a finite number`);
  }
}

/**
 * Ограничивает значение диапазоном [lo, hi].
 * @param {number} v — значение.
 * @param {number} lo — нижняя граница.
 * @param {number} hi — верхняя граница.
 * @returns {number}
 * @throws {RangeError} "lo > hi", если lo > hi.
 */
function clamp(v, lo, hi) {
  assertFinite('v', v);
  assertFinite('lo', lo);
  assertFinite('hi', hi);
  if (lo > hi) {
    throw new RangeError('lo > hi');
  }
  return Math.min(hi, Math.max(lo, v));
}

/**
 * Линейная интерполяция между a и b.
 * @param {number} a — начальная точка.
 * @param {number} b — конечная точка.
 * @param {number} t — параметр (НЕ клампится, экстраполяция допустима).
 * @returns {number} a + (b - a) * t
 */
function lerp(a, b, t) {
  assertFinite('a', a);
  assertFinite('b', b);
  assertFinite('t', t);
  return a + (b - a) * t;
}

/**
 * Обратная интерполяция: позиция v на отрезке [a, b] в координатах [0, 1]
 * (и за его пределами).
 * @param {number} a — начальная точка.
 * @param {number} b — конечная точка.
 * @param {number} v — значение.
 * @returns {number} (v - a) / (b - a)
 * @throws {RangeError} "a === b", если a === b.
 */
function invLerp(a, b, v) {
  assertFinite('a', a);
  assertFinite('b', b);
  assertFinite('v', v);
  if (a === b) {
    throw new RangeError('a === b');
  }
  return (v - a) / (b - a);
}

module.exports = { clamp, lerp, invLerp };

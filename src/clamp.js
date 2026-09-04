'use strict';

// clamp — чистые функции ограничения значений диапазонами (TASK-STANOK-CC-014).
// Без внешних зависимостей, без side effects.

function assertNumber(value, name) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new TypeError(`${name} must be a number, got ${value}`);
  }
}

function assertVecObject(value, name) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object with numeric "x" and "y"`);
  }
}

function clampComponent(v, min, max, name) {
  assertNumber(v, name);
  assertNumber(min, name);
  assertNumber(max, name);
  if (min > max) {
    throw new RangeError('min > max');
  }
  return Math.min(Math.max(v, min), max);
}

/**
 * Ограничивает число v диапазомом [min, max].
 * v < min -> min; v > max -> max; иначе -> v.
 * @param {number} v
 * @param {number} min
 * @param {number} max
 * @returns {number}
 * @throws {RangeError} "min > max" — если min > max.
 * @throws {TypeError} если v/min/max не число/NaN (имя аргумента в сообщении).
 */
function clamp(v, min, max) {
  assertNumber(v, 'v');
  assertNumber(min, 'min');
  assertNumber(max, 'max');
  if (min > max) {
    throw new RangeError('min > max');
  }
  return Math.min(Math.max(v, min), max);
}

/**
 * Частный случай clamp: ограничение v диапазоном [0, 1].
 * @param {number} v
 * @returns {number}
 * @throws {TypeError} если v не число/NaN ("v" в сообщении).
 */
function clamp01(v) {
  return clamp(v, 0, 1);
}

/**
 * Покомпонентное ограничение 2D-вектора {x, y} диапазомами {x, y}.
 * Результат: {x: clamp(v.x, min.x, max.x), y: clamp(v.y, min.y, max.y)}.
 * @param {{x: number, y: number}} v
 * @param {{x: number, y: number}} min
 * @param {{x: number, y: number}} max
 * @returns {{x: number, y: number}} новый объект; аргументы не мутируются.
 * @throws {RangeError} "min > max" — если для какой-то компоненты min > max.
 * @throws {TypeError} если v/min/max не объект, либо компонента не число/NaN
 *   (имя компоненты "x"/"y" в сообщении).
 */
function clampVec(v, min, max) {
  assertVecObject(v, 'v');
  assertVecObject(min, 'min');
  assertVecObject(max, 'max');
  return {
    x: clampComponent(v.x, min.x, max.x, 'x'),
    y: clampComponent(v.y, min.y, max.y, 'y'),
  };
}

module.exports = { clamp, clamp01, clampVec };

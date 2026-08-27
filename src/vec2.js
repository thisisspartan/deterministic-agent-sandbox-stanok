'use strict';

// vec2 — чистые функции 2D-векторной алгебры (TASK-STANOK-CC-010).
// Без внешних зависимостей, без side effects.

function assertFiniteNumber(value, name) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new TypeError(`${name} must be a finite number, got ${value}`);
  }
}

/**
 * Длина вектора: Math.hypot(x, y).
 * @param {number} x
 * @param {number} y
 * @returns {number}
 * @throws {TypeError} если x или y не число/NaN (имя аргумента в сообщении).
 */
function length(x, y) {
  assertFiniteNumber(x, 'x');
  assertFiniteNumber(y, 'y');
  return Math.hypot(x, y);
}

/**
 * Нормализованный вектор: { x: x / L, y: y / L }, L = Math.hypot(x, y).
 * @param {number} x
 * @param {number} y
 * @returns {{x: number, y: number}}
 * @throws {Error} "normalize: zero vector" для нулевого вектора.
 * @throws {TypeError} если x или y не число/NaN.
 */
function normalize(x, y) {
  assertFiniteNumber(x, 'x');
  assertFiniteNumber(y, 'y');
  const L = Math.hypot(x, y);
  if (L === 0) {
    throw new Error('normalize: zero vector');
  }
  return { x: x / L, y: y / L };
}

function assertVec2(obj, name) {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new TypeError(`${name} must be an object { x, y }, got ${obj}`);
  }
  assertFiniteNumber(obj.x, `${name}.x`);
  assertFiniteNumber(obj.y, `${name}.y`);
}

/**
 * Покомпонентное сложение: { x: a.x + b.x, y: a.y + b.y }.
 * @param {{x: number, y: number}} a
 * @param {{x: number, y: number}} b
 * @returns {{x: number, y: number}}
 * @throws {TypeError} если a/b не объект или поля не числа/NaN.
 */
function add(a, b) {
  assertVec2(a, 'a');
  assertVec2(b, 'b');
  return { x: a.x + b.x, y: a.y + b.y };
}

module.exports = { length, normalize, add };

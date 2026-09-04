'use strict';

// dist — чистые функции расстояний и длин дуг (TASK-STANOK-CC-015).
// Без внешних зависимостей, без side effects.

function assertNumber(value, name) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new TypeError(`${name} must be a number, got ${value}`);
  }
}

function assertPoint(obj, name, components) {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new TypeError(
      `${name} must be an object { ${components.join(', ')} }, got ${obj}`
    );
  }
  for (const c of components) {
    assertNumber(obj[c], `${name}.${c}`);
  }
}

/**
 * Евклидово расстояние между двумя 2D-точками:
 * Math.hypot(b.x - a.x, b.y - a.y).
 * @param {{x: number, y: number}} a
 * @param {{x: number, y: number}} b
 * @returns {number}
 * @throws {TypeError} если a/b не объект или компонента не число/NaN
 *   (имя компоненты "x"/"y" в сообщении).
 */
function dist2d(a, b) {
  assertPoint(a, 'a', ['x', 'y']);
  assertPoint(b, 'b', ['x', 'y']);
  return Math.hypot(b.x - a.x, b.y - a.y);
}

/**
 * Евклидово расстояние между двумя 3D-точками:
 * Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z).
 * @param {{x: number, y: number, z: number}} a
 * @param {{x: number, y: number, z: number}} b
 * @returns {number}
 * @throws {TypeError} если a/b не объект или компонента не число/NaN
 *   (имя компоненты "x"/"y"/"z" в сообщении).
 */
function dist3d(a, b) {
  assertPoint(a, 'a', ['x', 'y', 'z']);
  assertPoint(b, 'b', ['x', 'y', 'z']);
  return Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z);
}

/**
 * Длина дуги окружности: r * theta (theta в радианах).
 * @param {number} r — радиус (>= 0)
 * @param {number} theta — угол в радианах (>= 0)
 * @returns {number}
 * @throws {TypeError} если r или theta не число/NaN ("r" / "theta").
 * @throws {RangeError} "negative radius" при r < 0,
 *   "negative angle" при theta < 0.
 */
function arcLength(r, theta) {
  assertNumber(r, 'r');
  assertNumber(theta, 'theta');
  if (r < 0) {
    throw new RangeError('negative radius');
  }
  if (theta < 0) {
    throw new RangeError('negative angle');
  }
  return r * theta;
}

module.exports = { dist2d, dist3d, arcLength };

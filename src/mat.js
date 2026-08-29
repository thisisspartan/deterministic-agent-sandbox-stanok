'use strict';

// mat — чистые функции над матрицами 2x2 (TASK-STANOK-CC-016).
// Матрица — объект { a, b, c, d }, строки: [a, b], [c, d].
// Без внешних зависимостей, без side effects.

function assertFiniteNumber(value, name) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new TypeError(`${name} must be a number, got ${value}`);
  }
}

function assertMatrix(obj, name) {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new TypeError(`${name} must be an object { a, b, c, d }, got ${obj}`);
  }
  assertFiniteNumber(obj.a, `${name}.a`);
  assertFiniteNumber(obj.b, `${name}.b`);
  assertFiniteNumber(obj.c, `${name}.c`);
  assertFiniteNumber(obj.d, `${name}.d`);
}

function assertVec2(obj, name) {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new TypeError(`${name} must be an object { x, y }, got ${obj}`);
  }
  assertFiniteNumber(obj.x, `${name}.x`);
  assertFiniteNumber(obj.y, `${name}.y`);
}

/**
 * Единичная матрица 2x2.
 * @returns {{a: number, b: number, c: number, d: number}}
 */
function identity() {
  return { a: 1, b: 0, c: 0, d: 1 };
}

/**
 * Произведение двух матриц 2x2: m * n.
 * @param {{a: number, b: number, c: number, d: number}} m
 * @param {{a: number, b: number, c: number, d: number}} n
 * @returns {{a: number, b: number, c: number, d: number}}
 * @throws {TypeError} если a/b/c/d любого аргумента не число/NaN
 *         (имя компоненты в сообщении).
 */
function mul(m, n) {
  assertMatrix(m, 'm');
  assertMatrix(n, 'n');
  return {
    a: m.a * n.a + m.b * n.c,
    b: m.a * n.b + m.b * n.d,
    c: m.c * n.a + m.d * n.c,
    d: m.c * n.b + m.d * n.d,
  };
}

/**
 * Умножение матрицы 2x2 на 2D-вектор { x, y }.
 * @param {{a: number, b: number, c: number, d: number}} m
 * @param {{x: number, y: number}} v
 * @returns {{x: number, y: number}}
 * @throws {TypeError} если компоненты m или v не числа/NaN
 *         (имя компоненты в сообщении).
 */
function mulVec(m, v) {
  assertMatrix(m, 'm');
  assertVec2(v, 'v');
  return {
    x: m.a * v.x + m.b * v.y,
    y: m.c * v.x + m.d * v.y,
  };
}

/**
 * Определитель матрицы 2x2: a*d - b*c.
 * @param {{a: number, b: number, c: number, d: number}} m
 * @returns {number}
 * @throws {TypeError} если компоненты m не числа/NaN
 *         (имя компоненты в сообщении).
 */
function det(m) {
  assertMatrix(m, 'm');
  return m.a * m.d - m.b * m.c;
}

/**
 * Транспонирование матрицы 2x2: {a, b, c, d} -> {a, c, b, d}.
 * @param {{a: number, b: number, c: number, d: number}} m
 * @returns {{a: number, b: number, c: number, d: number}}
 * @throws {TypeError} если компоненты m не числа/NaN
 *         (имя компоненты в сообщении).
 */
function transpose(m) {
  assertMatrix(m, 'm');
  return { a: m.a, b: m.c, c: m.b, d: m.d };
}

module.exports = { identity, mul, mulVec, det, transpose };

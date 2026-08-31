'use strict';

// grid — чистые функции над прямоугольными сетками (массивы строк) (TASK-STANOK-CC-017).
// Сетка — массив строк, каждая строка — массив ячеек; все строки одной длины.
// Без внешних зависимостей, без side effects (кроме set — мутация по спецификации).

function assertGrid(grid) {
  if (!Array.isArray(grid)) {
    throw new TypeError(`grid must be an array of rows, got ${grid}`);
  }
}

function assertIndex(value, name) {
  if (typeof value !== 'number' || Number.isNaN(value) || !Number.isInteger(value)) {
    throw new TypeError(`${name} must be an integer, got ${value}`);
  }
}

function assertDimension(value, name) {
  if (typeof value !== 'number' || Number.isNaN(value) || !Number.isInteger(value)) {
    throw new TypeError(`${name} must be an integer, got ${value}`);
  }
}

function assertCellIndex(grid, r, c) {
  assertGrid(grid);
  assertIndex(r, 'r');
  assertIndex(c, 'c');
  if (r < 0 || r >= grid.length || c < 0 || c >= grid[0].length) {
    throw new RangeError('out of bounds');
  }
}

/**
 * Создаёт сетку rows x cols, все ячейки = value.
 * @param {number} rows целое > 0
 * @param {number} cols целое > 0
 * @param {*} value любое значение
 * @returns {Array<Array>}
 * @throws {TypeError} если rows/cols не целые ("rows"/"cols" в сообщении).
 * @throws {RangeError} "invalid dimensions" — если rows/cols <= 0.
 */
function create(rows, cols, value) {
  assertDimension(rows, 'rows');
  assertDimension(cols, 'cols');
  if (rows <= 0 || cols <= 0) {
    throw new RangeError('invalid dimensions');
  }
  const grid = [];
  for (let r = 0; r < rows; r++) {
    const row = [];
    for (let c = 0; c < cols; c++) {
      row.push(value);
    }
    grid.push(row);
  }
  return grid;
}

/**
 * Значение ячейки (r, c) (0-based).
 * @throws {TypeError} если grid не массив / r,c не целые.
 * @throws {RangeError} "out of bounds" — если (r, c) вне сетки.
 */
function at(grid, r, c) {
  assertCellIndex(grid, r, c);
  return grid[r][c];
}

/**
 * Присваивает значение ячейке (r, c); мутирует сетку, возвращает её.
 * @throws {TypeError} если grid не массив / r,c не целые.
 * @throws {RangeError} "out of bounds" — если (r, c) вне сетки.
 */
function set(grid, r, c, value) {
  assertCellIndex(grid, r, c);
  grid[r][c] = value;
  return grid;
}

/**
 * Количество столбцов (длина первой строки).
 * @throws {TypeError} если grid не массив.
 */
function width(grid) {
  assertGrid(grid);
  return grid[0].length;
}

/**
 * Количество строк.
 * @throws {TypeError} если grid не массив.
 */
function height(grid) {
  assertGrid(grid);
  return grid.length;
}

/**
 * true, если (r, c) внутри сетки; иначе false. Без исключений за пределами
 * валидации аргументов.
 * @throws {TypeError} если grid не массив / r,c не целые.
 */
function inBounds(grid, r, c) {
  assertGrid(grid);
  assertIndex(r, 'r');
  assertIndex(c, 'c');
  return r >= 0 && r < grid.length && c >= 0 && c < grid[0].length;
}

/**
 * Глубокое копирование структуры сетки: новые строки, значения ячеек
 * копируются (объекты — по ссылке на тот же объект).
 * @throws {TypeError} если grid не массив.
 */
function clone(grid) {
  assertGrid(grid);
  return grid.map((row) => row.slice());
}

module.exports = { create, at, set, width, height, inBounds, clone };

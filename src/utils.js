'use strict';

/**
 * Округляет значение вниз до сотых: Math.floor(v * 100) / 100.
 * @param {number} v
 * @returns {number}
 */
function floorToHundredth(v) {
  return Math.floor(v * 100) / 100;
}

/**
 * Форматирует координаты игрока в строку "x=<X> y=<Y>".
 * Значения округляются вниз до сотых (например, -1.005 -> -1.01).
 * @param {number} x
 * @param {number} y
 * @returns {string}
 */
function formatPos(x, y) {
  return `x=${floorToHundredth(x)} y=${floorToHundredth(y)}`;
}

module.exports = { formatPos };

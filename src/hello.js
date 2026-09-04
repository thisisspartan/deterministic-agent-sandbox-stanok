'use strict';

/**
 * Возвращает приветствие для заданного имени.
 * @param {string} name — непустая строка.
 * @returns {string} строка вида `Hello, <name>!`.
 * @throws {TypeError} если `name` не строка или пустая строка.
 */
function greet(name) {
  if (typeof name !== 'string' || name.length === 0) {
    throw new TypeError('name must be a non-empty string');
  }
  return `Hello, ${name}!`;
}

module.exports = { greet };

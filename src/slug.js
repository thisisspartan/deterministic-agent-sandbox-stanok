'use strict';

// slug — нормализация строк в URL-слаг (TASK-STANOK-CC-047).
// Без внешних зависимостей, без side effects.

/**
 * Приводит строку к URL-слаг.
 *
 * Порядок шагов:
 *   1. toLowerCase;
 *   2. каждый пробел (пробел, \t, \n, \r) и любой другой ASCII-символ,
 *      не входящий в [a-z0-9] (напр. '.', ':', '!', '-'), заменяется на sep;
 *   3. все небуквенно-цифровые НЕ-ASCII символы (акценты, кириллица и т.п.)
 *      удаляются (не транслитерируются);
 *   4. повторяющиеся sep схлопываются в один;
 *   5. sep обрезается в начале и в конце.
 *
 * Пустая или только-мусорная строка -> ''.
 *
 * @param {string} str — исходная строка.
 * @param {string} [sep='-'] — разделитель, строка длиной 1.
 * @returns {string}
 * @throws {TypeError} если str не строка (null/undefined/число/...).
 * @throws {TypeError} если sep передан, но не строка длиной 1.
 */
function slugify(str, sep = '-') {
  if (typeof str !== 'string') {
    throw new TypeError(`str must be a string, got ${str === null ? 'null' : typeof str}`);
  }
  if (sep !== undefined && (typeof sep !== 'string' || sep.length !== 1)) {
    throw new TypeError(`sep must be a single-character string, got ${JSON.stringify(sep)}`);
  }

  const kept = [];
  for (const ch of str.toLowerCase()) {
    const code = ch.codePointAt(0);
    if (ch === sep || (code >= 0x61 && code <= 0x7a) || (code >= 0x30 && code <= 0x39)) {
      kept.push(ch); // [a-z0-9] и сам sep сохраняются
    } else if (code < 0x80) {
      kept.push(sep); // пробелы и ASCII-пунктуация -> sep
    }
    // всё остальное (э/кириллица/...) — удаляется
  }

  // Шаги 4–5: split на sep, отбрасываем пустые куски (хлопание + обрезка краёв).
  return kept.join('').split(sep).filter((part) => part.length > 0).join(sep);
}

module.exports = { slugify };

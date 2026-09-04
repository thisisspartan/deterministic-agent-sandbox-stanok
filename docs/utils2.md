# utils2

Модуль-обёртка над `src/utils.js`: добавляет строковый префикс к формату
координат, которые формирует `formatPos` (см. [`docs/utils.md`](./utils.md)).

## API

```js
const { formatPosPrefixed } = require('./utils2.js');

/**
 * @param {string} prefix — строковый префикс
 * @param {number} x — координата X (number, не NaN)
 * @param {number} y — координата Y (number, не NaN)
 * @returns {string} prefix + "x=<X> y=<Y>"
 * @throws {TypeError} если prefix не string, либо x/y не number или NaN
 */
function formatPosPrefixed(prefix, x, y)
```

Чистая функция: без `process`, `Date`, side effects и внешних зависимостей.
Валидация аргументов выполняется до вызова `formatPos`.

## Примеры

```js
formatPosPrefixed('pos ', 1, 2);            // -> "pos x=1 y=2"
formatPosPrefixed('p', -1.005, -0.001);     // -> "px=-1.01 y=-0.01"
formatPosPrefixed(123, 1, 2);               // -> TypeError
formatPosPrefixed('p', NaN, 2);             // -> TypeError
formatPosPrefixed('p', 1, '2');             // -> TypeError
```

## Зависимости

- `src/utils.js` — `formatPos(x, y)` (основной формат "x=<X> y=<Y>").

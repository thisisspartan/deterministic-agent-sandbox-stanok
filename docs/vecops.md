# vecops — векторные утилиты (2D)

Модуль `src/vecops.js` (CommonJS, `module.exports`). Чистые, детерминированные
функции над 2D-векторами `{x, y}`. Без внешних зависимостей, без side effects
(нет `process`, `Date`, мутабельного состояния).

## Экспорт

```js
const { dist, mid, normalize2, project } = require('./vecops.js');
```

### `dist(a, b) -> number`

Евклидово расстояние между двумя 2D-векторами:
`Math.hypot(a.x - b.x, a.y - b.y)`.

```js
dist({ x: 0, y: 0 }, { x: 3, y: 4 }); // 5
```

### `mid(a, b) -> {x, y}`

Середина отрезка: `{x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}`.

```js
mid({ x: 0, y: 0 }, { x: 2, y: 4 }); // { x: 1, y: 2 }
```

### `normalize2(v) -> {x, y}`

Приведение к единичной длине: `{x: v.x / len, y: v.y / len}`,
где `len = Math.hypot(v.x, v.y)`.

```js
normalize2({ x: 3, y: 4 }); // { x: 0.6, y: 0.8 }
```

- `RangeError` с сообщением `"zero vector"` для нулевого вектора
  (`{x: 0, y: 0}`), т.к. длина делителем быть не может.

### `project(a, b) -> {x, y}`

Ортогональная проекция `a` на `b`:
`scale(b, dot(a, b) / dot(b, b))`, где `dot(u, w) = u.x*w.x + u.y*w.y`,
`scale(v, k) = {x: v.x*k, y: v.y*k}`.

```js
project({ x: 1, y: 1 }, { x: 1, y: 0 }); // { x: 1, y: 0 }
```

- `RangeError` с сообщением `"zero basis"`, если `dot(b, b) === 0`
  (нулевой базис — направление не определено).

## Валидация аргументов

Для всех функций каждый аргумент-вектор проверяется:

- должен быть объектом (не `null`, не массив);
- компоненты `x` и `y` — числа, не `NaN`.

Нечисловая (включая `NaN`, `undefined`, отсутствующую) компонента —
`TypeError`; в сообщении указывается имя дефектной компоненты (`"x"` / `"y"`,
при отсутствии обеих — обе). Примеры сообщений:

- `"a must be an object { x, y }, got null"`
- `"v must have numeric component(s) x (got x=oops, y=1)"`
- `"b must have numeric component(s) x, y (got x=undefined, y=undefined)"`

## Инварианты

- `dist({x:0,y:0}, {x:3,y:4}) === 5`
- `mid({x:0,y:0}, {x:2,y:4}) === {x:1, y:2}`
- `normalize2({x:3,y:4}) ≈ {x:0.6, y:0.8}` (eps `1e-9`)
- `project({x:1,y:1}, {x:1,y:0}) ≈ {x:1, y:0}`

## Тесты

`tests/vecops.test.js` — запуск: `node --test tests/vecops.test.js`.
Числовые сравнения дробных результатов — через `Math.abs(a-b) < 1e-9`.

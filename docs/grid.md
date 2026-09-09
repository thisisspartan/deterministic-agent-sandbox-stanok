# grid — сеточные операции (TASK-STANOK-CC-017)

Чистые функции над прямоугольными сетками. Сетка — массив строк, каждая
строка — массив ячеек; все строки одной длины. Модуль `src/grid.js`,
CommonJS. Без внешних зависимостей, без side effects (кроме `set`).

## Экспорт

`create(rows, cols, value)`, `at(grid, r, c)`, `set(grid, r, c, value)`,
`width(grid)`, `height(grid)`, `inBounds(grid, r, c)`, `clone(grid)`

## Функции

### `create(rows, cols, value)` → `Array<Array>`
Создаёт сетку `rows x cols`, все ячейки = `value` (объекты — по ссылке).

```js
grid.create(2, 3, 0); // [[0, 0, 0], [0, 0, 0]]
```

### `at(grid, r, c)` → `*`
Значение ячейки `(r, c)` (0-based). Чистая функция.

### `set(grid, r, c, value)` → `grid`
Присваивает значение ячейке, мутирует сетку, возвращает её (единственная
не-чистая функция).

### `width(grid)` → `number`
Количество столбцов (длина первой строки).

### `height(grid)` → `number`
Количество строк.

### `inBounds(grid, r, c)` → `boolean`
`true`, если `(r, c)` внутри сетки, иначе `false`. Отрицательные индексы —
`false`, исключение не бросается.

```js
grid.inBounds(grid.create(2, 3, 0), 1, 2); // true
grid.inBounds(grid.create(2, 3, 0), 2, 0); // false
```

### `clone(grid)` → `Array<Array>`
Глубокое копирование структуры: новые строки, значения копируются
(объекты — по ссылке на тот же объект). Мутация копии не влияет на оригинал.

```js
const g = grid.create(2, 3, 1);
const c = grid.clone(g);
c !== g;       // true
c[0] !== g[0]; // true
c[0][0] === g[0][0]; // true
```

## Семантика ошибок

| Ошибка | Сообщение | Когда |
| --- | --- | --- |
| `TypeError` | `rows must be an integer...` | `rows` не целое число (`create`) |
| `TypeError` | `cols must be an integer...` | `cols` не целое число (`create`) |
| `TypeError` | `grid must be an array of rows...` | `grid` не массив |
| `TypeError` | `r must be an integer...` | `r` не целое число |
| `TypeError` | `c must be an integer...` | `c` не целое число |
| `RangeError` | `invalid dimensions` | `rows <= 0` или `cols <= 0` (`create`) |
| `RangeError` | `out of bounds` | `(r, c)` вне сетки (`at`, `set`) |

Не-числовые и дробные значения `rows`/`cols`/`r`/`c` (включая `NaN`) —
`TypeError` с именем аргумента в сообщении; отрицательные целые индексы
проходят валидацию и ловятся как `out of bounds` в `at`/`set`.

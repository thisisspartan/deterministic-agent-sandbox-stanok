# Tetris

Консольный тетрис (Node.js, без внешних зависимостей).

## Module: pieces (`src/tetris/pieces.js`)

Первый модуль проекта — фигуры и вращение (SRS). Чистый модуль: без IO, таймеров, `Date`.

### Экспорт

- `PIECES` — 7 фигур `I, O, T, S, Z, J, L`. Каждая — 4 SRS-состояния
  `A` (spawn), `R` (CW), `D` (180), `L` (CCW); состояние = массив клеток
  `[col, row]`, relative от якоря (col+ = право, row+ = вниз).
  Спавн-состояние A зафиксировано под absolute-клетки спеки при якоре `(3,0)`.
- `SPAWN` — `{ piece, col, row }` spawn-позиция каждой фигуры;
  `SPAWN[p].col/row + PIECES[p].A` дают ровно absolute-клетки спеки.
- `KICKS` — SRS kick-таблицы числами `[dCol, dRow]` в порядке перебора:
  - `KICKS.JLSTZ[from][to]` — таблица для J/L/S/T/Z;
  - `KICKS.I[from][to]` — отдельная таблица для I;
  - `KICKS.O[from][to]` — только `[[0,0]]`.
- `collides(board, piece, state, col, row)` → boolean: true, если любая клетка
  (state-клетка + (col,row)) вне границ (`col<0`, `col>9`, `row>21`) или занята;
  `row < 0` (скрытые ряды) — не коллизия.
- `rotate(piece, fromState, dir, board, col, row)` →
  `{ piece, state, col, row, kick }` или `null`, если все kick-варианты невалидны.
  `dir`: `'CW'` (A→R→D→L→A) или `'CCW'` (A→L→D→R→A). O — no-op: state не
  меняется, kick `(0,0)`. Иначе kick-таблица `I`/`JLSTZ` перебирается по
  порядку; первый валидный kick — результат.

### Тесты

`tests/tetris/pieces.test.js` — `node --test tests/tetris/pieces.test.js`.

## Module: board (`src/tetris/board.js`)

Доска 10×22, фиксация фигур, очистка рядов. Чистый модуль: без IO, таймеров,
`Date` и импорта `pieces.js` (таблица клеток продублирована внутри — board
работает с клетками, а не с фигурами).

Сетка: `grid[row][col]`, row 0 = верх (скрытый), row 21 = дно; `0` = пусто,
`>0` = занято (значение = id фигуры для цвета). Все функции чистые: вход не
мутируется, новый board возвращается объектом.

### Экспорт

- `newBoard()` → `{ grid }` — 22 ряда × 10 колонок, все `0`, ряды независимы.
- `inBounds(col, row)` → boolean: `0<=col<10 && 0<=row<22`.
- `isFullRow(grid, row)` → boolean: все 10 клеток ряда заняты.
- `clearLines(grid)` → `{ board, n }` — удаляет полные ряды, сдвигает верх
  вниз, дополняет сверху пустыми; `n` = число удалённых рядов.
- `lock(grid, piece, state, col, row)` → `{ board, clearedRows }` — записывает
  клетки фигуры (значение = piece-id) в grid (клетки со `row < 0` пропускаются),
  затем делает то же, что `clearLines`. score/level/lines не трогает
  (это game.js, тикет 021).

### Тесты

`tests/tetris/board.test.js` — `node --test tests/tetris/board.test.js`.

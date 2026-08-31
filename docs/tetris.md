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

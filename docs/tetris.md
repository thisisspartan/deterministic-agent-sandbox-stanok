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

## Module: bag (`src/tetris/bag.js`)

Генератор последовательности фигур по правилу 7-bag (модуль 020). Чистый модуль:
без IO, таймеров, `Date`; seed передаётся явно как number.

### Экспорт

- `newBag(seed)` → bag-объект:
  - `next()` → string `'I'|'O'|'T'|'S'|'Z'|'J'|'L'` — вернуть и удалить
    следующую фигуру; если мешок пуст, сгенерировать новый (перемешать все 7).
  - `peek()` → string — вернуть следующую фигуру **без удаления**.
  - `reset(seed)` → void — сброс bag с новым seed.
- `mulberry32(seed)` → PRNG-функция (фиксированный алгоритм из тикета).
- `fisherYates(arr, rng)` → arr — классический Fisher-Yates (от конца к началу,
  `j = floor(rng()*(i+1))`), in-place.
- `PIECES` — массив `['I','O','T','S','Z','J','L']`.

### Свойства

- Детерминированно: один seed → одна и та же последовательность.
- 7-bag: каждые 7 подряд `next()` — перестановка всех 7 фигур (каждая ровно по
  одному разу).
- `newBag(1)`, `reset(1)`, два `newBag(42)` дают воспроизводимые, идентичные
  последовательности.

### Тесты

`tests/tetris/bag.test.js` — `node --test tests/tetris/bag.test.js`:
golden-14 для seed=1 (первые 14 `next()` = 2 мешка), 7-bag property (первые 7 и
8–14 = перестановки всех 7), `peek()` не расходует мешок, `reset(1)` = `newBag(1)`,
детерминизм (два `newBag(42)`, 21 `next()`), все значения ∈ 7 фигур, чистота
модуля в исходнике (нет `process`/`readline`/`setInterval`/`Date`).

## Module: game (`src/tetris/game.js`)

Состояние игры (state machine, тикет 021): гравитация, движение/поворот,
soft/hard drop, lock + line-clear + score/level, pause/resume, reset. Чистый
модуль: время — только через `now()`/`dt`, нет `process`/`readline`/
`setInterval`/`Date`. Зависимости: `pieces.js` (collides/rotate), `board.js`
(newBoard/lock), `bag.js` (newBag).

### Экспорт

- `newGame({ seed, now })` → game-объект. `now` — функция `() => ms` (инъекция
  времени; по умолчанию `() => 0`). Инициализация: `board=newBoard()`,
  `bag=newBag(seed)`, `score=0`, `lines=0`, `level=1`, `over=false`,
  `paused=false`, spawn первой фигуры, `next=bag.peek()`.
- `dropInterval(level)` → `max(80, 812 - level*82)` мс (level 1 = 730,
  level 9 = 80, level 10 = 80; кривая подобрана под закреплённые точками
  730/80/80 значения тикета — rough-формула `800 - level*70` даёт 170 на
  level 9 и противоречит закреплённому 80).

### Поля game

`{ piece, state, col, row, board, score, lines, level, next, over, paused }`
(внутренний аккумулятор `_acc` не часть публичного контракта).

### Методы

- `tick(dt)` — накопление `acc += dt`; пока `acc >= dropInterval(level)`:
  `acc -= interval`, шаг вниз (при коллизии — lock). No-op при over/paused.
- `move(dir)` dir∈{−1,+1} → сдвинуть col, если не коллизия; true если сдвинул.
- `rotate(dir)` dir∈{'CW','CCW'} → `pieces.rotate`; если null — не менять;
  true если повернул.
- `softDrop()` — 1 шаг вниз если можно, `score += 1`.
- `hardDrop()` — вниз до упора, `score += 2*cells`, затем lock.
- `pause()` / `resume()` — flag; при паузе сброс `_acc=0`.
- `reset(newSeed)` — полный сброс (board/score/lines/level/bag/over/paused),
  новый seed, spawn.

### Lock + score/level

После hardDrop или когда гравитация упёрлась (упрощённый lock-delay):
`board.lock` → `{board, clearedRows n}`; `score += [0,100,300,500,800][n]*level`
(СТАРЫЙ level); `lines += n`; `level = floor(lines/10)+1`. Lock-out: зафиксированная
фигура имела ≥1 клетки в row 0–1 ПОСЛЕ clear → `over=true`. Spawn следующей;
если spawn коллизит → `over=true`.

### Тесты

`tests/tetris/game.test.js` — `node --test tests/tetris/game.test.js`:
spawn, гравитация tick, dropInterval, move/rotate, softDrop, hardDrop,
line-clear, level-up (old level), lock-out, top-out, pause/resume, reset,
чистота модуля.

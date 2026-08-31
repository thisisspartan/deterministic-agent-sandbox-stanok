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

## Module: ui (`src/tetris/ui.js`)

Консольный UI (тикет 022): чистый ANSI-рендер + тонкий слой `attach()`
(raw-mode, ввод, DAS, 30 FPS-цикл). Зависимость: `game.js` (021) + `pieces.js`.
Две части (DI-граница): `render` — чистая функция без io/process; `attach` —
единственный модуль с raw-mode и `now()`.

### Экспорт

- `render(frame, columns?)` → string — ЧИСТАЯ функция. `frame` = снапшот
  `{ board, piece, state, col, row, score, lines, level, next, over, paused }`.
  Возвращает ANSI-строку: поле 10 колонок × 22 ряда (клетка = 2 display-колонки
  `█ ` / `▓ ` / `∙ `), HUD `score/lines/level/next`, оверлей `PAUSED` (центр)
  или `GAME OVER` + статистика + «R — заново, Q — выход». `columns` — ширина
  терминала для clamp: на узком frame лишние правые колонки отбрасываются
  (не crash). `columns` по умолчанию = полное поле.
- `attach(io, game, { now, onQuit })` → `{ stop }` — тонкий слой. `io = { stdin,
  stdout, columns }` (DI, не `process` напрямую). Включает raw-mode на `io.stdin`,
  polling ввода, DAS, цикл 30 FPS (33мс): каждый кадр `game.tick(dt)` +
  `io.stdout.write(render(gameSnapshot(game), io.columns))`. `stop()` — raw-mode
  off, курсор показать, остановить цикл. `now` — инъекция времени (по умолчанию
  `() => 0`); внутри `attach` время читается только через `now()`.
  Input/DAS читают `over`/`paused` через тот же accessor, что `gameSnapshot()`:
  `game._state ? game._state : game` (real `newGame()` — flat, mock — `_state`).
- `gameSnapshot(game)` → frame — снапшот game (или mock с `_state`) в render-frame.
- `COLS` (=10), `ROWS` (=22), `idForPiece`, `visibleCells` — вспомогательные.

### Ввод

`←`/`→` — move; `↓` — softDrop; `↑`/`X` — rotate CW; `Z` — rotate CCW;
`Space` — hardDrop; `P` — pause/resume; `Q` — `onQuit`; `R` — reset (только если
`over`); `ESC` — осознанный no-op (сбрасывает DAS-держку, ничего не делает).
Стрелки приходят escape-последовательностями `\x1b[A..D` (CSI/SS3).

### DAS

Задержка 170мс, затем автоповтор каждые 50мс в то же направление. Реальные
терминалы не шлют key-up: каждое событие `←`/`→` держит направление; цикл
кадров по `now()-heldSince` запускает повторы. DAS вызывает `game.move`
(НЕ `softDrop`) — очки не начисляет.

### Управление (тикеты 025/028/029: сброс DAS при отпускании стрелки)

Факт поведения терминала (проверен, НЕ на веру): raw-mode Linux-терминал
(VT100/xterm-класс) НЕ шлёт key-up для стрелок — отпускание генерирует те же
байты, что нажатие (`\x1b[D` и т.д.). Доказательств альтернативной
key-up-последовательности нет — применён **Вариант A** (таймаут тишины),
не B.

Механизм (после фикса тикета 029) — три уровня, по нарастающей силе:

1. **Гейт «тап не повторяется» (`events`, фикс тикета 029, основная причина
   дрейфа).** Состояние `events` считает, сколько arrow-событий (`←`/`→`)
   видела текущая держка. `dasStep()` НЕ fire'ит автоповтор, пока
   `events < 2`. Разница между тапом и удержанием видна именно в этом
   счётчике: одиночное нажатие (тап) даёт ровно **одно** событие и затем
   тишину, тогда как реально удерживаемая стрелка продолжает приносить
   автоповторы терминала (OS auto-repeat каждые ~30–80мс в типичных
   настройках) и растит `events` до 2 и выше ещё до того, как
   `DAS_DELAY` (170мс) истекает. До фикса `dasStep()` смотрел только на
   `now() - heldSince` и не знал, сколько событий было — поэтому тап
   (одно событие) после 170мс начинал бесконечно повторять, пока окно
   тишины не схлопывало держку на границе кадра: фигура «уезжала» сама
   собой. Гейт `events < 2` закрывает эту дыру: тап физически не может
   повториться, а удержание — может.
2. **Таймаут тишины** (тикет 028, вариант A; расширен в 029): константа
   `KEY_UP_TIMEOUT = 500` мс (в `ui.js` рядом с `DAS_DELAY`/`ARR`).
   В `dasStep()` окно тишины меряется **до последнего события**
   (`now() - lastArrowEventT`); при `> 500` держка считается отпущенной:
   `heldDir`/`repeatsFired`/`heldSince`/`events` сбрасываются, DAS
   останавливается. Это эмулирует key-up по тишине и работает на ЛЮБОМ
   терминале без изменения байт-протокола.
3. **Явный key-up** (тикет 025, публичный хук): `handleKeyUp(k)` сбрасывает
   держку мгновенно — для драйверов, которые реально эмитят key-up
   (PTY/SSH bridge). См. примечание ниже.

Обоснование 500мс (тикеты 028+029): автоповтор стрелки (ОС/терминал) может
приходить **реже**, чем каждые 200мс — Linux/GNOME `repeat_delay` обычно
250–500мс, на SSH/медленных настройках ещё дольше. При `KEY_UP_TIMEOUT = 200`
длинное удержание с медленным автоповтором накапливало >200мс «тишины» между
событиями и держку сбрасывали посреди удержания — DAS замирал (симптом той же
семьи: «я тяну фигуру, а она застывает»). `500мс` > максимально разумного
интервала автоповтора, поэтому нормальное удержание (повторные события
каждые <500мс) никогда не сбрасывается ложно, а реальное отпускание
(тишина) гасит DAS в пределах одного кадра (~33мс) после окна.

`handleKeyUp` (тикет 025) оставлен как публичный хук: драйверы, которые
реально эмитят key-up (PTY/SSH bridge), зовут его через возвращаемый
объект `attach` — сброс мгновенный, не дожидаясь ни таймаута, ни гейта
событий. **Примечание о wiring (гипотеза 5, тикет 029):** `main.js`
НЕ вызывает `handleKeyUp` — это не баг, а ограничение дизайна: основной
драйвер (raw-mode stdin) не эмитит key-up вообще, а PTY/SSH-мосты, которые
бы могли, в текущем `main.js` не подключены. Если в будущем появится
драйвер с явными key-up — подключить через возвращаемый объект `attach`.

Поведение после фикса (тикет 029):
- нажал `←` и отпустил (тап) → ровно **один** шаг влево, DAS не запускается
  (`events` не дорастает до 2) — симптом оператора устранён;
- удержание `←` (автоповтор терминала каждые 30–80мс, а на медленных
  `repeat_delay` до 250–500мс) → `events` дорастает до 2, DAS работает,
  держка не сбрасывается ложно (окно 500мс перекрывает максимальный
  разумный интервал автоповтора);
- нажал и отпустил, тишина >500мс → держка гасится в `dasStep`, DAS
  останавливается в пределах одного кадра;
- смена направления (`←` держать → нажал `→`) → новое событие пере-армирует
  держку в новое направление; старая держка не «оживает», потому что
  `heldDir` перезаписан, а `events` обнулён на любом отпускном пути.

### Аудит управления (тикет 025)

- **Key-up (фикс).** Raw-mode stdin шлёт key-down и key-up стрелки идентичными
  байтами, так что сам терминал key-up не различает. `attach` отдаёт
  `handleKeyUp(dir)`: если driver (PTY/SSH bridge) эмитит key-up, он сбрасывает
  `heldDir`/`heldSince`/`repeatsFired` — DAS останавливается немедленно.
  Для терминалов БЕЗ key-up (обычный raw-mode stdin) добавлен (тикет 028)
  таймаут тишины `KEY_UP_TIMEOUT` — см. «Управление» выше.
- **Soft-drop.** Удержание `↓` даёт повтор по каждому key-down-повтору терминала
  (raw-mode); DAS для `↓` нет — по одному cell на событие. Поведение корректно.
- **Повороты.** `↑`/`X` = CW, `Z` = CCW — совпадает с этими доками (раздел «Ввод»
  main/ui) — расхождений нет.
- **Пауза/рестарт.** При `paused`/`over` все действия и `dasStep()` gated через
  `flags()`. `P` toggle, `R` только при `over`, `Q` всегда. Тупика «пауза поверх
  game-over» нет.
- **ESC.** `parseKeys` эмитит `'esc'` на одиночный ESC; `handleKey` обрабатывает
  его через явный `case 'esc':` (фикс 029/H1) — сбрасывает `heldDir`/
  `repeatsFired` (осознанный no-op для игры, но сброс держки по ESC сохранён).
  Мусорные/control-байты НЕ в эту ветку: они уходят в `default:` и держку
  НЕ трогают (см. Гипотеза 1 ниже).
- **Аудит гипотез тикета 029 (поиск дрейфа после отпускания ←/→):**
  - **B1 — подтверждено, фикс (детерминированная причина дрейфа).** До
    фикса `dasStep()` решал, fire'ить ли автоповтор, только по
    `now() - heldSince`; понятие «сколько событий было у этой держки» не
    было. Одиночное нажатие (тап) оставляло `heldDir` заданным, и через
    `DAS_DELAY` (170мс) `dasStep` начинал fire'ить повторы до тех пор, пока
    окно тишины `KEY_UP_TIMEOUT` не схлопнуло держку на границе кадра.
    Тап и удержание были неразличимы. Фикс: счётчик `events` + гейт
    `if (events < 2) return;` в `dasStep()` — тап (1 событие) физически не
    может повториться. Тест (красная фаза при старом коде: move улетает в
    2; зелёная: move === 1): `DAS (ticket 029, B1): a single tap must not
    auto-repeat — the operator drift`.
  - **B2 — подтверждено, фикс (вторая причина, «freeze посреди
    удержания»).** `KEY_UP_TIMEOUT = 200` мс было меньше максимального
    разумного интервала автоповтора стрелки (Linux `repeat_delay` 250–500мс,
    на SSH ещё медленнее), поэтому медленное удержание ложно сбрасывалось
    посреди: между событиями копилось >200мс «тишины» и `dasStep` убивал
    держку. Фикс: окно расширено до 500мс. Тест (красная фаза при 200мс:
    держка убита, move==1; зелёная: 500мс + `events` гейт, move>=3):
    `DAS (ticket 029, B2): a 250ms auto-repeat gap does not kill a held
    arrow`. Третий тест `DAS (ticket 029, B3): a released key still stops
    DAS within one frame past the window` — регрессия: тишина >500мс всё
    ещё гасит DAS (move === 1).
  - **Гипотеза 1 (`default:` сбрасывает DAS) — подтверждена как дефект ввода,
    фикс (регрессия тикета 029, H1).** `default:` сбрасывал `heldDir`/
    `repeatsFired` на ЛЮБОМ неизвестном байте (мусор, control-байты, случайный
    `'esc'` из неполной ESC-последовательности в середине буфера). В raw-mode
    терминале такие байты реально приходят (split-чунки, не распознанные
    `parseKeys` последовательности), и сброс на мусорном байте **гасит живое
    удержание раньше времени** — DAS замирает посреди drag'а, а фигура
    «тормозит» не по отпусканию, а по чужому байту. Фикс: `default:` — чистый
    no-op (`break;` без сброса), новый явный `case 'esc':` — единственный
    byte-level путь сброса держки (помимо `handleKeyUp`). Мусор больше не
    отменяет удержание, ESC — по-прежнему отменяет (осознанный no-op для игры,
    но сброс по ESC сохранён). Тест (красная фаза при старом `default:`: junk
    обнуляет `heldDir`, move не растёт; зелёная: junk → `default:` no-op,
    удержание живо, DAS fire'ит move > 3): `DAS (ticket 029, H1): unknown/junk
    bytes must not cancel a held arrow (default: drift)`.
  - **Гипотеза 3 (`lastArrowEventT` не обновляется) — опровергнута.**
    Каждый `left`/`right` в `handleKey` обновляет `lastArrowEventT`; пути,
    где реальное нажатие не обновляет его, нет. `dasStep` корректно НЕ
    обновляет его (автоповтор ≠ новое нажатие).
  - **Гипотеза 4 (split-чунки ESC-последовательностей) — опровергнута.**
    `parseKeys` на `\x1b` в конце буфера (неполная последовательность) делает
    `break` и НЕ эмитит `'esc'` + мусор — стрелка не теряется и не порождает
    ложный сброс. Следующий чанк с остатком `[C` будет распознан отдельно;
    в худшем случае одно событие потеряется, но это НЕ дрейф.
  - **Гипотеза 5 (`handleKeyUp` не подключён в main.js) — ограничение
    дизайна, не баг.** См. примечание в разделе «Управление» выше.

### Чистота

`render` не трогает `process`/`Date` (чистая функция). `attach` — единственный
владелец raw-mode и `now()`.

### Тесты

`tests/tetris/ui.test.js` — `node --test tests/tetris/ui.test.js`:
render (пустой frame, фигура, next-превью, PAUSED, GAME OVER, узкий frame),
attach lifecycle (raw-mode on/off, ≥1 render, stop()), ввод (каждая клавиша),
DAS (автоповтор ≥2, без softDrop/score), чистота модуля.

## Module: main (`src/tetris/main.js`)

Точка входа и сборка (тикет 023, модуль 6/6): собирает чистую игру (021) с
консольным UI (022), подключает `process.stdin`/`process.stdout` и владеет
process-level жизненным циклом: Q → `stop()` + `exit(0)`; R (из game-over) →
`game.reset(Date.now())`; SIGINT/SIGTERM → `stop()` (raw-mode off, курсор
показать) + exit (SIGINT = 130, SIGTERM = 0).

Запуск: `node src/tetris/main.js`. Внешних зависимостей нет (package.json
без `dependencies` — только stdlib + локальные модули).

### Экспорт

- `createApp({ io, game, now, onQuit, seed })` → `{ stop }` — DI-фабрика:
  оборачивает `game.reset` так, что вызов `game.reset()` (без аргумента,
  как делает ui.attach по R из game-over) становится `game.reset(Date.now())`
  (или `seed()` если передана функция `seed`); `Q` маршрутизируется через
  `onQuit` ui.attach — сначала `stop()`, потом `onQuit()`. `stop()` — raw-mode
  off, listener снят, цикл остановлен, курсор показан.
- `start()` — реальная сборка: `newGame({ seed: Date.now(), now: () => Date.now() })`
  + `io = { stdin: process.stdin, stdout: process.stdout, columns: process.stdout.columns }`
  + `createApp({ io, game, now: () => Date.now(), onQuit: () => process.exit(0) })`
  + обработчики SIGINT/SIGTERM. Вызывается ТОЛЬКО из `require.main === module`,
  поэтому `require()` этого файла в тестах НЕ запускает интерактивный цикл.

### Управление (см. также «Ввод» в module ui)

`←`/`→` — move; `↓` — softDrop; `↑`/`X` — rotate CW; `Z` — rotate CCW;
`Space` — hardDrop; `P` — pause/resume; `Q` — выход (exit 0);
`R` (только из game-over) — заново (новый seed = `Date.now()`).

### Тесты

`tests/tetris/main.test.js` — `node --test tests/tetris/main.test.js`:
source-hygiene (newGame/attach/SIGINT/process.stdin в исходнике); smoke e2e
(запуск child-процесса, render 'TETRIS', Q → exit 0; SIGINT → exit 0/130);
Q (child, 'q' → exit 0 с таймаутом); R из game-over (mock io/game через
createApp: 'r' → `game.reset` вызван ровно 1 раз с числовым seed, quit НЕ
вызван).

## Запуск и правила

- Запуск: `node src/tetris/main.js` (или `npm start`, если в package.json
  есть script — см. требование 7 тикета; без внешних зависимостей).
- Управление: см. выше (клавиши ui + Q/R/SIGINT/SIGTERM от main).
- Модули: pieces → board → bag → game → ui → main (каждый предыдущий —
  чистая функция/модуль, только main владет process-level жизненным циклом).
- Правила: см. «Lock + score/level» в module game (line-clear score,
  level-up по floor(lines/10)+1, lock-out, top-out); «Ввод»/«DAS» в module ui.

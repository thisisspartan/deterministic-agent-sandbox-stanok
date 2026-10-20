# minesweeper_render — текстовый рендер кадра «Сапёра» (CC-307, R1..R3)

`src/minesweeper_render.py` — чистая функция `render(state) -> tuple[str, ...]`:
превращает `GameState` (duck-typed, из `src/minesweeper_engine.py`) в текстовый
кадр консольного «Сапёра». Модуль НЕ импортирует ничего, не выполняет I/O,
не использует ANSI/escape-кодов и цвета. State только читается (ни мутации,
ни сохранения); один и тот же state → байт-идентичный кадр; результат —
неизменяемый кортеж строк. Координаты 1-based: `x` — колонка `1..width`,
`y` — строка `1..height`.

## Формат кадра (R1)

1. `mines {mines_total - len(flagged)}/{mines_total}  open {len(opened)}/{safe_total}  {word}`
   где `safe_total = width*height - mines_total`, `word` = `"playing" | "won" | "lost"`
   по `status`. Секции разделены ДВОЙНЫМ пробелом.
2. пустая строка `""`.
3. ruler-десятков — только если `width > 9`: `" " * (Hh + 1)` + для `x=1..width`
   символ `str(x // 10)` если `x >= 10`, иначе `" "`; `Hh = len(str(height))`.
4. ruler-единиц: `" " * (Hh + 1)` + для `x=1..width` `str(x % 10)`.
5. для каждой строки `y = 1..height`: `f"{y:>{Hh}} "` + символы клеток подряд,
   без разделителей.

Символ клетки, приоритет сверху вниз:

| приоритет | условие | символ |
|---|---|---|
| 1 | `status != "playing"` и клетка в `mines` | `"*"` |
| 2 | клетка в `flagged` | `"F"` |
| 3 | клетка в `opened` | `" "` если `adj[y-1][x-1] == 0`, иначе `str(adj)` |
| 4 | иначе | `"#"` |

## Инварианты

- **R2 (чистота/детерминизм):** `render` не мутирует `state` (deep-snapshot
  идентичен до и после); повторный вызов на том же state даёт идентичный
  кадр; возвращаемый кадр — кортеж.
- **R3 (полнота финала):** после `"lost"`/`"won"` кадр показывает ВСЕ мины
  (`*`); флаги на не-миновых клетках остаются `F` там, где стояли (флаг на
  мине перекрывается `*` приоритетом 1).

## Тесты

- `tests/minesweeper_render_test.py` — unit-покрытие R1..R3 с негативами
  (byte-точные кадры на зафиксированных полях: seed 179 — 3×3/4 с нулевым
  flood/цифрами/флагом/закрытыми `#`, seed 5 — 3×3/1 центр; rulers width 10+
  против ≤9; префиксы строк при height 10+; AST-проверка «ноль import»).
- `tests/minesweeper_render_contract_test.py` — provided-оракул (no-regression).

Прогон: `bash scripts/run.sh test tests/minesweeper_render_test.py`,
`bash scripts/run.sh test --all`.

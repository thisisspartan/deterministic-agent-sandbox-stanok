# minesweeper_engine — движок консольного «Сапёра» (CC-306, M1..M7)

`src/minesweeper_engine.py` — чистые детерминированные функции (stdlib-only:
`random`, `dataclasses`, `collections.deque`). Нет времени, I/O, threading,
глобального состояния. Каждая операция принимает `GameState` и возвращает НОВЫЙ
`GameState` (или `None` для недопустимого хода); входной state никогда не
мутируется. Координаты 1-based: `x` — колонка `1..width`, `y` — строка `1..height`.

## Тип состояния

```python
@dataclasses.dataclass(frozen=True)
class GameState:
    seed: int; width: int; height: int; mines_total: int
    mines:   frozenset[(x, y)]              # мины
    adj:     tuple[tuple[int, ...], ...]    # height строк × width ints: число мин в 8-окрестности
    opened:  frozenset[(x, y)]
    flagged: frozenset[(x, y)]
    status:  str                            # "playing" | "won" | "lost"
    first_done: bool
```

## API

| функция | контракт |
|---|---|
| `new_game(seed, width, height, mines_count)` | `ValueError` при `width<1`, `height<1`, `width>64`, `height>32`, `mines_count<0`, `mines_count>width*height-1`. Размещение: `random.Random(seed).sample(cells, mines_count)`, `cells` — row-major обход (`y=1..height`, `x=1..width`). Одинаковый seed → идентичное поле. `status="playing"`, `first_done=False`, opened/flagged пусты. |
| `open_cell(state, x, y)` | `None` при game-over, вне поля, по flagged или уже открытой клетке. Иначе — новый state (см. «Вскрытие»). |
| `toggle_flag(state, x, y)` | Только closed-клетки при `status=="playing"`; toggle on/off. Иначе `None`. |
| `is_won(state)` / `is_lost(state)` | Предикаты `status == "won"` / `"lost"`. |

## Вскрытие (`open_cell`)

1. **Safe first open (M5).** При первом open (`first_done==False`), если
   клетка — мина: мина переносится в первую клетку row-major-обхода, не
   являющуюся миной (после снятия кликнутой) и не совпадающую с кликнутой;
   `adj` пересчитывается. Первый open никогда не вскрывает мину;
   `first_done=True` после любого первого open. После первого open переносов нет.
2. **Мина (после первого open):** `status="lost"`; мина НЕ добавляется в `opened`.
3. **Число (adj>0):** вскрывается только сама клетка.
4. **Ноль (adj==0):** итеративный BFS (deque) по 4-связным (N/S/E/W) клеткам
   с `adj==0`, плюс все НЕминовые клетки в 8-окрестности любой вскрытой
   нулевой клетки («цифровая граница»).
5. **Победа:** после вскрытия, если все non-mine клетки в `opened` →
   `status="won"`. Флаги для победы не обязательны.

## Непустые инварианты

- Все возвращаемые `GameState` — новые объекты; аргумент не меняется
  (реализация — `dataclasses.replace` поверх неизменяемых полей).
- `adj` корректна на углах/краях (соседи за пределами поля не считаются).
- BFS явный (deque), рекурсии нет.

## Тесты

- `tests/minesweeper_engine_test.py` — unit-покрытие M1..M7 с негативами
  (фикстуры зафиксированы в файле: seed 5/2/6 — ручные поля 3×3 с одиночной
  миной в центре/углу/на краю и эталонными `adj`; seed 6/16 — safe-first
  переносы на 9×9; seed 2 — partial-flood на 6×6).
- `tests/minesweeper_engine_contract_test.py` — provided-оракул (no-regression).

Прогон: `bash scripts/run.sh test tests/minesweeper_engine_test.py`,
`bash scripts/run.sh test --all`.

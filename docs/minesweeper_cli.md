# minesweeper_cli — консольный вход игры «Сапёр» (CC-308, C1..C5)

`src/minesweeper_cli.py` — консольный вход игры поверх `src/minesweeper_engine.py`
(правила) и `src/minesweeper_render.py` (кадры). CLI НЕ reimplement'ит правила:
каждая принятая state-команда делегирует движку и печатает ровно один полный
кадр `render(state)`; каждая отвергнутая — ровно одну строку `rejected: ...`,
поле не мутирует. Единственное место записи кадров — цикл. stdlib-only
(`argparse`, `sys`); никаких ANSI, prompt-приглашений, termios, escape-кодов.

## C1 — flags и exit codes

`main(argv) -> int` (argv без имени программы); entry point
`python3 -m src.minesweeper_cli` из корня дерева (import pattern:
`try: from src import ...` / `except ImportError:` bare import — работает и
`python3 src/minesweeper_cli.py`). Флаг: `--seed N` (int, default 0).
Неизвестный флаг / не-int seed / лишний позиционный аргумент → usage-строка
в stderr, rc=2, stdout пуст. Чистый выход (quit или EOF) → rc=0.

## C2 — единственный цикл

При старте: баннер (одна строка, пин):

```
commands: open X Y | flag X Y | new | difficulty beginner|medium|expert | custom W H MINES | help | quit
```

затем начальный кадр difficulty=beginner (9×9, 10 мин). Игровой seed:
`seed + games_played`; `games_played` (стартует с 0) растёт ПОСЛЕ создания
игры на `new` / `difficulty` / `custom` (начальный кадр и первая `new`
используют `games_played = 0`). Строки stdin читаются построчно до EOF или
`quit` → rc=0.

## C3 — команды и отказы

Команды lowercase, токены по whitespace. Разрешены: `open X Y`, `flag X Y`,
`new`, `difficulty beginner|medium|expert` (presets-пин: beginner 9×9/10,
medium 16×16/40, expert 30×16/99), `custom W H MINES`, `help`, `quit`.
Bad input никогда не мутирует поле и не роняет игру (rc всё ещё 0).
Отказ — ровно одна строка, кадр НЕ печатается:

| строка отказа | условие |
|---|---|
| `rejected: unknown command` | команда не из списка |
| `rejected: bad arguments` | некорректная arity или не-int координаты/размеры |
| `rejected: out of range` | координаты вне поля (1-based) |
| `rejected: already open` | `open` по открытой клетке |
| `rejected: cell is flagged` | `open` по флагу |
| `rejected: cell is open` | `flag` по открытой клетке |
| `rejected: game over` | `open`/`flag` после конца игры |
| `rejected: unknown difficulty` | имя вне presets |
| `rejected: invalid size` | `custom` вне валидации движка (`ValueError` из `new_game`) |

Пустая/пробельная строка игнорируется. Порядок проверок для open/flag:
arity/int → game over → out of range → уже открыта/флаг/открытая клетка.

## C4 — кадры

Принятая state-команда (open/flag/new/difficulty/custom) → новый полный кадр
`render(state)`. Кадр перехода в won/lost печатается той же командой
(финальный кадр показан автоматически). `help` → баннер. Отказ → только
rejected-строка.

## Тесты

- `tests/minesweeper_cli_test.py` — покрытие C1..C5 на реальном subprocess
  stdin-boundary (`sys.executable -m src.minesweeper_cli`, cwd=корень,
  input=pipe): usage rc=2; `--seed` honored / default 0; баннер+начальный
  кадр; quit/EOF → rc 0; seed-арифметика `seed + games_played` (frames
  сверяются с own-tree engine+render); полная победа beginner (seed 1) и
  проигрыш open-по-мине (финальный кадр со всеми `*`); все pinned
  rejected-строки, поле не изменилось; flag/open-взаимодействия; смена
  размера difficulty/custom (ruler/счётчики); help/blank lines; нет ANSI и
  prompt; детерминизм (два identical прогона байт-идентичны); AST-проверка
  тонкости main (правила только через engine/render, своих правил нет).
- `tests/minesweeper_cli_contract_test.py` — provided-оракул (no-regression).

Прогон: `bash scripts/run.sh test tests/minesweeper_cli_test.py`,
`bash scripts/run.sh test --all`.

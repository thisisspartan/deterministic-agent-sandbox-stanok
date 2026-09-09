# dist — расстояния и длины дуг (TASK-STANOK-CC-015)

Модуль `src/dist.js`: чистые детерминированные функции вычисления расстояний.
Без внешних зависимостей, без side effects (CommonJS, `module.exports`).

## API

### `dist2d(a, b) → number`

Евклидово расстояние между двумя 2D-точками: `Math.hypot(b.x - a.x, b.y - a.y)`.

```js
dist2d({ x: 0, y: 0 }, { x: 3, y: 4 }); // 5
dist2d({ x: 1, y: 1 }, { x: 1, y: 1 }); // 0
```

### `dist3d(a, b) → number`

Евклидово расстояние между двумя 3D-точками: `Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z)`.

```js
dist3d({ x: 0, y: 0, z: 0 }, { x: 2, y: 3, z: 6 }); // 7
```

### `arcLength(r, theta) → number`

Длина дуги окружности радиуса `r` при угле `theta` (радианы): `r * theta`.

```js
arcLength(1, Math.PI);        // Math.PI
arcLength(2, Math.PI / 2);    // Math.PI
```

## Семантика ошибок

| Условие | Ошибка | Сообщение |
|---|---|---|
| компонента точки не число / `NaN` | `TypeError` | имя компоненты: `"x"`, `"y"`, `"z"` (через `${a/b}.<компонента>`) |
| `a`/`b` не объект | `TypeError` | имя аргумента `"a"` / `"b"` в сообщении |
| `r` не число / `NaN` | `TypeError` | имя `"r"` в сообщении |
| `theta` не число / `NaN` | `TypeError` | имя `"theta"` в сообщении |
| `r < 0` | `RangeError` | `"negative radius"` |
| `theta < 0` | `RangeError` | `"negative angle"` |

Проверки `arcLength` выполняются в порядке: `TypeError` (r, theta) →
`RangeError` (r) → `RangeError` (theta); при и `r < 0`, и `theta < 0`
бросается `"negative radius"`.

Сравнение дробных результатов в тестах — через `Math.abs(actual - expected) < 1e-9`.

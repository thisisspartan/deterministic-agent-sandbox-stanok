# angle — работа с углами в радианах

Модуль `src/angle.js` (CommonJS). Чистые детерминированные функции: без внешних
зависимостей, без `process`, `Date`, side effects.

## API

### `normalizeAngle(a)`

Приведение угла к диапазону **`(-PI, PI]`** (верхняя граница включена, `-PI`
канонически мапится в `+PI`).

Алгоритм: `r = a % (2*PI)`; если `r <= 0` — `r += 2*PI`; если `r > PI` —
`r -= 2PI`.

```js
normalizeAngle(0)               // 0
normalizeAngle(3 * Math.PI)     // Math.PI
normalizeAngle(5 * Math.PI / 2) // Math.PI / 2
normalizeAngle(-4 * Math.PI)    // 0
normalizeAngle(-Math.PI)        // Math.PI
```

Ошибки: `TypeError` (`"a must be a number, got …"`) если `a` не `number` или `NaN`.

### `angleDiff(a, b)`

Минимальная направленная разница `b - a`, приведённая через
`normalizeAngle(b - a)`; результат в **`(-PI, PI]`** ⊆ `[-PI, PI]`.

```js
angleDiff(0, Math.PI)  // Math.PI
angleDiff(0, -Math.PI) // Math.PI  (антиподальный шов: -PI -> +PI)
angleDiff(3.0, -3.0)   // ≈ 0.283185 — через «шов», а не назад через 0
```

Ошибки: `TypeError` для нечислового `a` (`"a …"`) или `b` (`"b …"`).

### `lerpAngle(a, b, t)`

Интерполяция по кратчайшей дуге: `normalizeAngle(a + angleDiff(a, b) * t)`.
`a + d*t` лежит на кратчайшей окружности между `a` и `b`, поэтому
`lerpAngle(a, b, 0.5)` — середина кратчайшей дуги, а `t` вне `[0, 1]` —
экстраполяция по той же окружности (НЕ ошибка).

```js
lerpAngle(0, Math.PI, 0.5)   // Math.PI / 2
lerpAngle(3.0, -3.0, 0.5)    // ≈ Math.PI — середина через шов
lerpAngle(0, Math.PI, 2)     // 0      (2PI -> 0)
lerpAngle(0, Math.PI, -1)    // Math.PI (-PI -> +PI, шов)
```

Ошибки: `TypeError` для нечислового `a` / `b` / `t` (имя аргумента в сообщении).

## Семантика диапазонов

- `normalizeAngle`: выход всегда в `(-PI, PI]`; `-PI` как выход невозможен
  (алгоритм мапит его в `+PI`).
- `angleDiff` / `lerpAngle`: выход наследует диапазон `normalizeAngle`.
- «Шов» окружности находится в точке `±PI`; антиподальная точка представлена
  единственным каноническим значением `+PI`.

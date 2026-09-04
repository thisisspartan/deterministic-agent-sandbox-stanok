# Модуль `hello`

## Сигнатура

```js
const { greet } = require('./hello.js'); // CommonJS
greet(name)
```

## Поведение

- `greet(name)` возвращает строку `Hello, <name>!`.
- Примеры:
  - `greet('World')` → `'Hello, World!'`
  - `greet('Алиса')` → `'Hello, Алиса!'`

## Ошибки

- Бросает `TypeError`, если `name`:
  - не является строкой (например, число `42`);
  - является пустой строкой `''`.

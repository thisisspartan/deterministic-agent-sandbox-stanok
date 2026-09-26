# Loop-guard hook verification (TASK-STANOK-CC-164)

Verification that the PreToolUse(Bash) loop-guard hook fires in a real
machine run: the exact command string below was issued as 10 separate Bash
tool calls (one command per call, no combining, no pipes, no `&&`, no
modified string, no skipping). The hook counts literal repetitions per
session and denies the 10th identical call (exit 2, Russian stderr message
fed to the model).

## Exact command used

```
bash scripts/run.sh list
```

## Result

denied_call: 10

Calls 1–9 of the series succeeded (identical output each time). The 10th
identical call was denied by the hook; the denial is the expected result of
this ticket, not an error.

## Exact deny message as received

```
PreToolUse:Bash hook error: [$CLAUDE_PROJECT_DIR/.claude/hooks/loop-guard.py]: Эта команда уже выполнялась 10 раз в этой сессии без смены подхода. Не повторяй — действуй по уже полученному результату или явно смени подход.
```

## Output of one successful `bash scripts/run.sh list` call

```
tests/loop_guard_verify_test.py
tests/palette_test.py
tests/renderer_test.py
tests/simulator_test.py
tests/smoke_test.py
tests/smoke_util_test.py
```

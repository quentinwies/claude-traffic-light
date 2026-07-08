# Claude Code Traffic Light

Desktop widget showing Claude Code's status at a glance:

| Light | Meaning |
|---|---|
| 🟢 Green | Idle — nothing running, safe to ignore |
| 🟡 Yellow | Working — Claude is processing or running a tool |
| 🔴 Red | Needs your input — permission prompt waiting |

Always-on-top, draggable, with an X button to close.

## Files

- `traffic_light.py` — the GUI widget (shared, cross-platform, no OS-specific code)
- `status_updater_win.py` — Windows-only backend (uses `tasklist`/`taskkill`)
- `status_updater_mac.py` — macOS-only backend (uses `ps`/`kill`)

Use the updater script matching your OS. Do not mix them.

## A note on the red-light lag

Claude Code has no hook event for "the user just approved this." The only
permission-related events are `PermissionRequest` (dialog shown) and
`PermissionDenied` (user said no). There is nothing that fires the instant
you click "yes."

Because of this, mapping only the six obvious lifecycle events
(`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`,
`Stop`, `SessionEnd`) leaves the light stuck on red after you approve,
until the *next* unrelated event happens to fire.

The fix used below: also map `PostToolUse` and `PostToolUseFailure` to
yellow. This isn't instant — it fires after the approved tool finishes
running, not the moment you click — but it guarantees the light returns
to yellow rather than staying red indefinitely. For fast tool calls the
delay is imperceptible; for long-running commands, expect red to persist
until the command completes.

---

## Windows Install

**Requirements:** Windows 10/11, Python 3.8+ with tkinter, Claude Code CLI.

1. Clone or copy this folder somewhere permanent, e.g. `C:\Users\<you>\claude-traffic-light\`.
2. Open `~/.claude/settings.json` (i.e. `C:\Users\<you>\.claude\settings.json`) and add the `hooks` block below, merging with any existing keys. **Use forward slashes in paths** — backslashes get corrupted by JSON escaping.

```json
{
  "hooks": {
    "SessionStart":       [{"matcher":"","hooks":[{"type":"command","command":"pythonw C:/Users/<you>/claude-traffic-light/status_updater_win.py start"}]}],
    "UserPromptSubmit":   [{"matcher":"","hooks":[{"type":"command","command":"python C:/Users/<you>/claude-traffic-light/status_updater_win.py yellow"}]}],
    "PreToolUse":         [{"matcher":"","hooks":[{"type":"command","command":"python C:/Users/<you>/claude-traffic-light/status_updater_win.py yellow"}]}],
    "PermissionRequest":  [{"matcher":"","hooks":[{"type":"command","command":"python C:/Users/<you>/claude-traffic-light/status_updater_win.py red"}]}],
    "PostToolUse":        [{"matcher":"","hooks":[{"type":"command","command":"python C:/Users/<you>/claude-traffic-light/status_updater_win.py yellow"}]}],
    "PostToolUseFailure": [{"matcher":"","hooks":[{"type":"command","command":"python C:/Users/<you>/claude-traffic-light/status_updater_win.py yellow"}]}],
    "PermissionDenied":   [{"matcher":"","hooks":[{"type":"command","command":"python C:/Users/<you>/claude-traffic-light/status_updater_win.py yellow"}]}],
    "Stop":               [{"matcher":"","hooks":[{"type":"command","command":"python C:/Users/<you>/claude-traffic-light/status_updater_win.py green"}]}],
    "SessionEnd":         [{"matcher":"","hooks":[{"type":"command","command":"python C:/Users/<you>/claude-traffic-light/status_updater_win.py stop"}]}]
  }
}
```

3. Replace `<you>` with your actual username.
4. If `python`/`pythonw` aren't resolving inside the hook shell (e.g. you're on Miniconda/Anaconda and it's not on PATH there), use full interpreter paths instead, e.g. `C:/Users/<you>/Miniconda3/pythonw.exe` and `C:/Users/<you>/Miniconda3/python.exe`. This is the more reliable default — don't assume the hook shell inherits your interactive terminal's PATH.
5. Restart Claude Code. Hooks load at session start only.

**Windows-specific notes:**
- `pythonw` suppresses the console window for the GUI process; `python` (no `w`) is used for the quick one-shot status writes.
- Process management uses `tasklist`/`taskkill`, which are Windows-only — this is why the Mac version needs a separate script.

---

## macOS Install

**Requirements:** macOS, Python 3.8+ (with tkinter — check via `python3 -m tkinter`), Claude Code CLI.

1. Clone or copy this folder somewhere permanent, e.g. `~/claude-traffic-light/`.
2. Open `~/.claude/settings.json` and add the `hooks` block below, merging with any existing keys.

```json
{
  "hooks": {
    "SessionStart":       [{"matcher":"","hooks":[{"type":"command","command":"python3 /Users/<you>/claude-traffic-light/status_updater_mac.py start"}]}],
    "UserPromptSubmit":   [{"matcher":"","hooks":[{"type":"command","command":"python3 /Users/<you>/claude-traffic-light/status_updater_mac.py yellow"}]}],
    "PreToolUse":         [{"matcher":"","hooks":[{"type":"command","command":"python3 /Users/<you>/claude-traffic-light/status_updater_mac.py yellow"}]}],
    "PermissionRequest":  [{"matcher":"","hooks":[{"type":"command","command":"python3 /Users/<you>/claude-traffic-light/status_updater_mac.py red"}]}],
    "PostToolUse":        [{"matcher":"","hooks":[{"type":"command","command":"python3 /Users/<you>/claude-traffic-light/status_updater_mac.py yellow"}]}],
    "PostToolUseFailure": [{"matcher":"","hooks":[{"type":"command","command":"python3 /Users/<you>/claude-traffic-light/status_updater_mac.py yellow"}]}],
    "PermissionDenied":   [{"matcher":"","hooks":[{"type":"command","command":"python3 /Users/<you>/claude-traffic-light/status_updater_mac.py yellow"}]}],
    "Stop":               [{"matcher":"","hooks":[{"type":"command","command":"python3 /Users/<you>/claude-traffic-light/status_updater_mac.py green"}]}],
    "SessionEnd":         [{"matcher":"","hooks":[{"type":"command","command":"python3 /Users/<you>/claude-traffic-light/status_updater_mac.py stop"}]}]
  }
}
```

3. Replace `<you>` with your actual username.
4. **Strongly recommended: use a full interpreter path instead of bare `python3`.** The hook shell may not resolve `python3` the same way your interactive terminal does, especially if you're relying on a `PATH` entry added to `~/.zshrc` (e.g. after installing Python from python.org). Find your path with `which python3` and use the full path in every hook command, e.g. `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
5. Restart Claude Code. Hooks load at session start only.

**macOS-specific notes:**
- No `pythonw` equivalent exists — `python3` is used for both the GUI launch and one-shot status writes. Since the hook has no visible terminal, no console flashes either way.
- Process management uses `os.kill()` (signal 0 for existence check, `SIGTERM` to stop) instead of `tasklist`/`taskkill`.
- **Apple's system Python (`/usr/bin/python3`) ships an old Tk 8.5 build that can fail with an OS-version check error** (`macOS 14 (1408) or later required, have instead 14 (1406)!`) even on a fully up-to-date system — this is a known Tcl/Tk bug, not a real deficiency in your OS. Fix: install Python from python.org (not Homebrew, which lags more often on this) and confirm `which python3` points into `/Library/Frameworks/Python.framework/...` before proceeding. Verify with `python3 -m tkinter` — a small blank window should open without error.
- If Tkinter windows don't render correctly even after that, confirm you're using a "framework build" of Python (the python.org installer provides this by default).

---

## Known Limitations (both platforms)

- **Single session only.** One shared status/PID file. Running two Claude Code sessions simultaneously will cause them to overwrite each other's status and fight over the GUI process.
- **`SessionStart` only fires at session launch.** If you close the widget manually mid-session, it will not respawn until the next Claude Code restart.
- **Stale PID handling.** If the GUI process crashes independently of a clean `stop`, the PID file may go stale; `stop` will fail silently rather than error. Cosmetic issue, not a functional blocker.
- **Approval-to-yellow lag.** See "A note on the red-light lag" above — this is a ceiling imposed by Claude Code's hook set, not a bug in this project.

## Troubleshooting

- **Widget doesn't appear:** restart Claude Code — hooks only load at session start.
- **"can't open file" errors on Windows:** check for backslashes in your settings.json paths — use `/` instead.
- **`macOS 14 (...) or later required` error on Mac:** see the Apple system Python note above — install Python from python.org.
- **Two widgets appear:** kill stray `pythonw`/`python3` processes running `traffic_light.py` and restart.
- **Light stuck on red after approving:** confirm `PostToolUse` and `PostToolUseFailure` are both present in your hooks block — see "A note on the red-light lag" above.

## License

MIT
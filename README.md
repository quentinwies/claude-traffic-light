# Claude Code Traffic Light

Desktop widget showing Claude Code's status at a glance:

| Light | Meaning |
|---|---|
| 🟢 Green | Idle — nothing running, safe to ignore |
| 🟡 Yellow | Working — Claude is processing or running a tool |
| 🔴 Red | Needs your input — permission prompt waiting |

Always-on-top, draggable, with an X button to close.

**One light per Claude Code session.** Open three sessions and you get three
lights, placed side by side, each labelled with its project folder and each
showing only its own session's state. Close a session and its light closes
with it.

## Files

- `traffic_light.py` — the GUI widget (shared, cross-platform, no OS-specific code)
- `status_updater_win.py` — Windows-only backend (Win32 process handles, `taskkill`)
- `status_updater_mac.py` — macOS-only backend (`os.kill`)

Use the updater script matching your OS. Do not mix them.

## How sessions are kept apart

Claude Code pipes a JSON payload into every hook containing `session_id` and
`cwd` (with `CLAUDE_CODE_SESSION_ID`, `CLAUDE_PROJECT_DIR` and `CLAUDE_PID` in
the environment as a fallback). The updater keys everything off that:

```
~/.claude_traffic/sessions/<session_id>.json
    {"color": "yellow", "label": "backend-api", "slot": 0,
     "claude_pid": 55133, "gui_pid": 55137, "ts": ...}
```

- **Placement.** Each session claims the lowest free *slot*; slot *n* sits at
  `x = 80 + n * 88`, wrapping to a second row at the screen edge. Closing a
  session frees its slot for the next one.
- **Label.** The basename of the session's `cwd`, shown under the lights and
  truncated to 11 characters.
- **`SessionStart` is idempotent.** It also fires on resume, `/clear` and
  compaction, so a session that already has a live light never gets a second.
- **Hard-killed terminals.** If you kill a terminal outright, `SessionEnd`
  never fires. Each widget therefore also watches its session's `CLAUDE_PID`
  and closes itself once that process is gone.
- **Closing a light by hand** dismisses that widget only — the session keeps
  running, and later hooks will not resurrect the light. Restart that session
  to get it back.

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

- **One process per light.** Each session's widget is its own Python/Tk
  process (~20–30 MB). Five parallel sessions means five processes. Fine in
  practice, but it is the simple design rather than the frugal one.
- **A manually closed light stays closed** for the rest of that session, by
  design — see above.
- **Long project names are truncated** to 11 characters in the label. Two
  sessions in similarly-named folders can look alike.
- **Approval-to-yellow lag.** See "A note on the red-light lag" above — this is a ceiling imposed by Claude Code's hook set, not a bug in this project.

## Troubleshooting

- **Widget doesn't appear:** restart Claude Code — hooks only load at session start.
- **"can't open file" errors on Windows:** check for backslashes in your settings.json paths — use `/` instead.
- **`macOS 14 (...) or later required` error on Mac:** see the Apple system Python note above — install Python from python.org.
- **Two widgets for one session:** kill stray `pythonw`/`python3` processes running `traffic_light.py` and restart. (Widgets for *different* sessions are expected — that's the point.)
- **Widgets overlap:** a slot is only freed when its session ends cleanly or its Claude Code process dies. Delete stale files in `~/.claude_traffic/sessions/` to reset.
- **Upgrading from the single-session version:** no hook changes needed, the commands are unchanged. The first `SessionStart` retires the old `status.json`/`gui.pid` widget automatically.
- **Light stuck on red after approving:** confirm `PostToolUse` and `PostToolUseFailure` are both present in your hooks block — see "A note on the red-light lag" above.

## License

MIT
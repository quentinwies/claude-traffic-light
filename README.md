# claude-traffic-light

An always-on-top desktop traffic light for Windows that shows what [Claude Code](https://claude.com/claude-code) is doing right now:

- 🟢 **Green** — idle
- 🟡 **Yellow** — working (pulses)
- 🔴 **Red** — waiting on your approval

It's a small Tkinter widget plus a set of Claude Code hooks that update it as your session moves through prompts, tool calls, and permission requests.

## How it works

- `traffic_light.py` — the GUI. A borderless, always-on-top window with a real traffic-light housing (stacked red/yellow/green, dimmed when inactive, soft glow on the active light). Polls `~/.claude_traffic/status.json` every 300ms and updates the lit color. Right-click for orientation (vertical/horizontal), opacity, and always-on-top options. Position, size, orientation, and opacity persist across restarts in `~/.claude_traffic/config.json`. Exits automatically if the status file disappears.
- `status_updater.py` — a small CLI that writes `status.json` and manages the GUI process (`start` launches it, `stop` kills it and cleans up). Called from Claude Code hooks with a color argument (`green`, `yellow`, `red`).

## Setup

1. Clone this repo somewhere permanent, e.g. `C:\Users\<you>\claude-traffic-light`.
2. Add hooks to your Claude Code settings (`~/.claude/settings.json`) so it drives the light through a session:

```json
{
  "hooks": {
    "SessionStart":      [{"matcher": "", "hooks": [{"type": "command", "command": "<python> <path>\\status_updater.py start"}]}],
    "UserPromptSubmit":  [{"matcher": "", "hooks": [{"type": "command", "command": "<python> <path>\\status_updater.py yellow"}]}],
    "PreToolUse":        [{"matcher": "", "hooks": [{"type": "command", "command": "<python> <path>\\status_updater.py yellow"}]}],
    "PermissionRequest": [{"matcher": "", "hooks": [{"type": "command", "command": "<python> <path>\\status_updater.py red"}]}],
    "PermissionDenied":  [{"matcher": "", "hooks": [{"type": "command", "command": "<python> <path>\\status_updater.py yellow"}]}],
    "PostToolUse":       [{"matcher": "", "hooks": [{"type": "command", "command": "<python> <path>\\status_updater.py yellow"}]}],
    "PostToolUseFailure":[{"matcher": "", "hooks": [{"type": "command", "command": "<python> <path>\\status_updater.py yellow"}]}],
    "Stop":              [{"matcher": "", "hooks": [{"type": "command", "command": "<python> <path>\\status_updater.py green"}]}],
    "SessionEnd":        [{"matcher": "", "hooks": [{"type": "command", "command": "<python> <path>\\status_updater.py stop"}]}]
  }
}
```

Replace `<python>` with the **full path** to a real Python interpreter (e.g. `C:/Python312/pythonw.exe` or `C:/Users/<you>/Miniconda3/pythonw.exe`) and `<path>` with the full path to this repo.

> **Windows gotcha:** don't just use `python`/`pythonw` on their own. Windows ships a PATH shim at `...\AppData\Local\Microsoft\WindowsApps\python.exe` that, if no real Python is installed or it's earlier on PATH, prints a "Python wurde nicht gefunden" / "install from the Microsoft Store" message and does nothing — silently breaking every hook that uses it. Run `where python` and use the real interpreter's full path instead.

3. Restart Claude Code (or open `/hooks` once) so the new hooks are picked up.

## Requirements

- Windows (uses `tasklist`/`taskkill` for process management)
- Python 3 with Tkinter (bundled with standard CPython installs)

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)

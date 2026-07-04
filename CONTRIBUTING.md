# Contributing

This is a small, single-purpose utility, so the bar for changes is "does it make the light work better."

## Setup

No dependencies beyond the Python standard library (Tkinter included). Just:

```
python traffic_light.py
```

To exercise the full hook-driven flow, wire up `status_updater.py` per the README and drive it from a real Claude Code session, or simulate it manually:

```
python status_updater.py start
python status_updater.py red
python status_updater.py green
python status_updater.py stop
```

## Guidelines

- Keep it dependency-free (stdlib only) unless there's a strong reason not to.
- Windows is the primary supported platform today; macOS support is planned (see open issues) — code that hard-codes Windows-only behavior (`tasklist`/`taskkill`, `-transparentcolor`, etc.) should be gated behind `sys.platform` checks rather than assumed.
- If you change the on-disk `status.json`/`config.json` schema, keep it backward compatible or note the break clearly in your PR.

## Submitting changes

Open a PR against `main`. Describe what you tested and on which OS — this project only has a couple of maintainers with limited hardware to verify on, so manual test notes matter more than usual here.

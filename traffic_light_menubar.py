"""
traffic_light_menubar.py
macOS-only: shows a Claude Code session's status as a colored dot in the
system menu bar instead of a floating window. Requires `rumps`
(pip install rumps).

Polls the same state files as traffic_light.py and applies the same
liveness rules (missing-file grace period, dead/zombie Claude process
detection). Exits the same way -- when the session file disappears or
the Claude Code process it belongs to is gone.
"""
import argparse
import json
import os
import subprocess

import rumps

BASE_DIR = os.path.join(os.path.expanduser("~"), ".claude_traffic")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")

ICON = {"green": "\U0001F7E2", "yellow": "\U0001F7E1", "red": "\U0001F534"}
POLL_S = 0.3
MISSING_GRACE_POLLS = 5
DEAD_PARENT_GRACE_POLLS = 2
ZOMBIE_CHECK_EVERY = 10  # polls; ~3s between the more expensive ps probes

MAX_LABEL_CHARS = 24


def session_file(session_id):
    return os.path.join(SESSIONS_DIR, session_id + ".json")


def read_state(path):
    """Parsed state dict, None if the file is gone, or {} if it is
    momentarily unreadable -- a partial write must not kill the widget."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, ValueError, OSError):
        return {}


def pid_alive(pid):
    """True if the process exists. An absent pid means 'nothing to watch',
    which must never read as dead."""
    if not pid:
        return True
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    except OSError:
        return True


def pid_zombie(pid):
    """A process that was killed but not yet reaped by its parent still
    answers os.kill(pid, 0). ps knows the difference."""
    if not pid:
        return False
    try:
        result = subprocess.run(["ps", "-o", "state=", "-p", str(int(pid))],
                                capture_output=True, text=True, timeout=2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return result.stdout.strip().startswith("Z")


def shorten(text):
    if len(text) <= MAX_LABEL_CHARS:
        return text
    return text[: MAX_LABEL_CHARS - 1] + "…"


class MenuBarLight(rumps.App):
    def __init__(self, state_path, label):
        super().__init__(name="Claude Traffic Light", title=ICON["green"], quit_button=None)
        self.state_path = state_path
        self.missing_count = 0
        self.dead_parent_count = 0
        self.poll_count = 0
        self.claude_pid = None
        self.last = None

        self.label_item = rumps.MenuItem(shorten(label) if label else "Claude Code session")
        self.close_item = rumps.MenuItem("Close", callback=self.close)
        self.menu = [self.label_item, None, self.close_item]

        self.timer = rumps.Timer(self.poll, POLL_S)
        self.timer.start()

    def close(self, _sender=None):
        """Closing the light dismisses the widget only -- the Claude Code
        session keeps running. Dropping the state file frees the slot and
        stops the updater writing status nobody is displaying."""
        try:
            os.remove(self.state_path)
        except OSError:
            pass
        rumps.quit_application()

    def poll(self, _timer):
        self.poll_count += 1
        state = read_state(self.state_path)

        if state is None:
            self.missing_count += 1
            if self.missing_count >= MISSING_GRACE_POLLS:
                rumps.quit_application()
            return

        self.missing_count = 0

        if state:
            self.claude_pid = state.get("claude_pid", self.claude_pid)
            label = state.get("label")
            if label:
                shortened = shorten(label)
                if self.label_item.title != shortened:
                    self.label_item.title = shortened
            color = state.get("color", "green")
            if color not in ICON:
                color = "green"
            if color != self.last:
                self.title = ICON[color]
                self.last = color

        # Terminal killed outright: SessionEnd never fires, so watch the
        # Claude Code process itself rather than stranding a dead light.
        alive = pid_alive(self.claude_pid)
        if alive and self.poll_count % ZOMBIE_CHECK_EVERY == 0:
            alive = not pid_zombie(self.claude_pid)
        if alive:
            self.dead_parent_count = 0
        else:
            self.dead_parent_count += 1
            if self.dead_parent_count >= DEAD_PARENT_GRACE_POLLS:
                try:
                    os.remove(self.state_path)
                except OSError:
                    pass
                rumps.quit_application()


def main():
    parser = argparse.ArgumentParser(description="Claude Code traffic light menu bar widget")
    parser.add_argument("--session", default="default",
                        help="Claude Code session id this light belongs to")
    parser.add_argument("--label", default="", help="text shown in the menu")
    parser.add_argument("--slot", type=int, default=0,
                        help="accepted for interface parity with traffic_light.py; "
                             "unused here since the menu bar places items itself")
    args = parser.parse_args()

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    MenuBarLight(session_file(args.session), args.label).run()


if __name__ == "__main__":
    main()

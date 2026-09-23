"""
traffic_light_controller.py
macOS-only: a single, session-independent menu bar item -- a fixed traffic
light icon that never changes color -- for switching the display mode
(window / menu bar / notification) that every tracked Claude Code session
uses. Requires `rumps` (pip install rumps).

Unlike traffic_light.py and traffic_light_menubar.py, this isn't a session
light: it doesn't watch any particular session or Claude Code process, and
it isn't spawned per-session. Exactly one instance is meant to run at a
time; status_updater_mac.py starts it (if not already running, tracked via
~/.claude_traffic/controller.pid) on every SessionStart and whenever
`display` is run by hand, and it keeps running until quit from its own
menu or the machine restarts.

Picking a mode here calls status_updater_mac.switch_all_sessions(), which
applies it to every currently tracked session immediately -- no restart of
Claude Code needed.
"""
import os

import rumps

import status_updater_mac as backend

ICON = "\U0001F6A6"  # traffic light -- fixed, this is the switcher, not a status light

MODE_LABELS = {
    "window": "Window",
    "menubar": "Menu Bar",
    "notification": "Notification",
}


class Controller(rumps.App):
    def __init__(self):
        super().__init__(name="Claude Traffic Light Controller", title=ICON, quit_button=None)
        self.mode_items = {}
        for mode in backend.DISPLAY_MODES:
            item = rumps.MenuItem(MODE_LABELS[mode], callback=self._make_selector(mode))
            self.mode_items[mode] = item
        self.menu = list(self.mode_items.values()) + [
            None, rumps.MenuItem("Quit Controller", callback=self.quit)
        ]
        self.refresh_checks()

    def _make_selector(self, mode):
        def select(_sender):
            backend.set_display_mode(mode)
            backend.switch_all_sessions(mode)
            self.refresh_checks()
        return select

    def refresh_checks(self):
        current = backend.display_mode()
        for mode, item in self.mode_items.items():
            item.state = (mode == current)

    def quit(self, _sender=None):
        try:
            os.remove(backend.CONTROLLER_PID_FILE)
        except OSError:
            pass
        rumps.quit_application()


def main():
    Controller().run()


if __name__ == "__main__":
    main()

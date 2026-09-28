"""
traffic_light_controller.py
macOS-only: a single, session-independent menu bar item -- a fixed traffic
light icon that never changes color -- for choosing which display mode(s)
(window / menu bar / notification) every tracked Claude Code session uses.
Requires `rumps` (pip install rumps).

The three modes are independent checkboxes, not a radio choice: menu bar
+ notification together is a normal combination, and toggling one never
clears the others.

Unlike traffic_light.py and traffic_light_menubar.py, this isn't a session
light: it doesn't watch any particular session or Claude Code process, and
it isn't spawned per-session. Exactly one instance is meant to run at a
time; status_updater_mac.py starts it (if not already running, tracked via
~/.claude_traffic/controller.pid) on every SessionStart and whenever
`display` is run by hand, and it keeps running until quit from its own
menu, the last session ends (status_updater_mac.stop_gui stops it), or
its own idle check finds no session left -- the fallback for terminals
that were killed outright and never ran SessionEnd.

Toggling a mode here calls status_updater_mac.switch_active_modes(), which
applies the new set to every currently tracked session immediately -- no
restart of Claude Code needed.
"""
import os
import time

import rumps

import status_updater_mac as backend

# How often to look for remaining sessions, and how long after launch to
# wait before the first look -- the controller is started just before the
# first session writes its state file, and by hand via `display`.
IDLE_CHECK_S = 10
STARTUP_GRACE_S = 60

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
            item = rumps.MenuItem(MODE_LABELS[mode], callback=self._make_toggle(mode))
            self.mode_items[mode] = item
        self.menu = list(self.mode_items.values()) + [
            None, rumps.MenuItem("Quit Controller", callback=self.quit)
        ]
        self.refresh_checks()
        self.started = time.time()
        self.idle_timer = rumps.Timer(self.check_idle, IDLE_CHECK_S)
        self.idle_timer.start()

    def check_idle(self, _timer):
        if time.time() - self.started < STARTUP_GRACE_S:
            return
        with backend.slot_lock():
            backend.sweep()
            idle = not backend.any_sessions()
        if idle:
            self.quit()

    def _make_toggle(self, mode):
        def toggle(_sender):
            current = backend.active_modes()
            current = (current - {mode}) if mode in current else (current | {mode})
            backend.set_active_modes(current)
            backend.switch_active_modes(current)
            self.refresh_checks()
        return toggle

    def refresh_checks(self):
        current = backend.active_modes()
        for mode, item in self.mode_items.items():
            item.state = mode in current

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

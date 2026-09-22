"""
traffic_light.py
Always-on-top widget with a real traffic-light housing (red/yellow/green
stacked, inactive lights dimmed) and an X button to close.

One widget per Claude Code session. The session is named with
--session <id>; state is read from ~/.claude_traffic/sessions/<id>.json,
which the status_updater for your OS writes. --slot <n> positions the
widget so several sessions' lights sit side by side instead of stacking
on the same spot.

The widget exits when its session file disappears (SessionEnd/stop), or
when the Claude Code process it belongs to is gone -- the latter covers
a terminal killed hard enough that SessionEnd never fired.
"""
import argparse
import json
import os
import subprocess
import sys
import tkinter as tk

BASE_DIR = os.path.join(os.path.expanduser("~"), ".claude_traffic")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")

LIT = {"green": "#2ecc71", "yellow": "#f1c40f", "red": "#e74c3c"}
DIM = {"green": "#1e3d2c", "yellow": "#3d3419", "red": "#3d1f1c"}
HOUSING_BG = "#1c1c1c"
POLL_MS = 300
MISSING_GRACE_POLLS = 5
DEAD_PARENT_GRACE_POLLS = 2
ZOMBIE_CHECK_EVERY = 10  # polls; ~3s between the more expensive ps probes

WIDTH = 78
HEIGHT = 150
CIRCLE_D = 38
PAD_X = (WIDTH - CIRCLE_D) // 2
GAP = 8
TITLEBAR_H = 22
LABELBAR_H = 16

# Where slot 0 sits, and how far apart consecutive slots are placed.
ORIGIN_X = 80
ORIGIN_Y = 80
SLOT_GAP_X = 10
SLOT_GAP_Y = 12

MAX_LABEL_CHARS = 11


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
    if os.name == "nt":
        # os.kill() on Windows TERMINATES the target even with signal 0,
        # so the liveness probe has to go through OpenProcess instead.
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
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
    answers os.kill(pid, 0), which would strand this widget next to a dead
    session. ps knows the difference. Cheap enough every few seconds, too
    costly on every poll."""
    if os.name == "nt" or not pid:
        return False  # GetExitCodeProcess already reports exited processes
    try:
        result = subprocess.run(["ps", "-o", "state=", "-p", str(int(pid))],
                                capture_output=True, text=True, timeout=2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return result.stdout.strip().startswith("Z")


def slot_geometry(root, slot):
    """Place slot n in a left-to-right row, wrapping onto a second row
    once the screen runs out of width."""
    total_h = HEIGHT + TITLEBAR_H + LABELBAR_H
    step_x = WIDTH + SLOT_GAP_X
    step_y = total_h + SLOT_GAP_Y
    usable = max(root.winfo_screenwidth() - ORIGIN_X, step_x)
    per_row = max(1, usable // step_x)
    col = slot % per_row
    row = slot // per_row
    return ORIGIN_X + col * step_x, ORIGIN_Y + row * step_y


def shorten(text):
    if len(text) <= MAX_LABEL_CHARS:
        return text
    return text[: MAX_LABEL_CHARS - 1] + "…"


class TrafficLight:
    def __init__(self, root, state_path, label, slot):
        self.root = root
        self.state_path = state_path
        self.missing_count = 0
        self.dead_parent_count = 0
        self.poll_count = 0
        self.claude_pid = None

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        x, y = slot_geometry(root, slot)
        root.geometry(f"{WIDTH}x{HEIGHT + TITLEBAR_H + LABELBAR_H}+{x}+{y}")
        root.configure(bg=HOUSING_BG)

        # --- title bar with drag + close button ---
        titlebar = tk.Frame(root, bg="#111111", height=TITLEBAR_H)
        titlebar.pack(fill="x", side="top")
        titlebar.pack_propagate(False)

        close_btn = tk.Label(titlebar, text="✕", fg="#999999", bg="#111111",
                              font=("Segoe UI", 10, "bold"), cursor="hand2")
        close_btn.pack(side="right", padx=6)
        close_btn.bind("<Button-1>", lambda e: self.close())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg="#ffffff"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg="#999999"))

        drag_label = tk.Label(titlebar, text="", bg="#111111")
        drag_label.pack(side="left", fill="both", expand=True)
        for widget in (titlebar, drag_label):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)

        # --- housing with three lights ---
        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT,
                                 highlightthickness=0, bg=HOUSING_BG)
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.do_drag)

        self.lights = {}
        order = ["red", "yellow", "green"]
        for i, color in enumerate(order):
            y0 = GAP + i * (CIRCLE_D + GAP)
            y1 = y0 + CIRCLE_D
            oval = self.canvas.create_oval(PAD_X, y0, PAD_X + CIRCLE_D, y1,
                                            fill=DIM[color], outline="#0a0a0a", width=2)
            self.lights[color] = oval

        # --- which session this light belongs to ---
        labelbar = tk.Frame(root, bg="#111111", height=LABELBAR_H)
        labelbar.pack(fill="x", side="bottom")
        labelbar.pack_propagate(False)
        self.label_var = tk.StringVar(value=shorten(label))
        self.label_widget = tk.Label(labelbar, textvariable=self.label_var,
                                      fg="#888888", bg="#111111",
                                      font=("TkDefaultFont", 8))
        self.label_widget.pack(fill="both", expand=True)
        for widget in (labelbar, self.label_widget):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)

        self._drag = (0, 0)
        self.last = None
        self.set_active("green")
        self.poll()

    def set_active(self, active_color):
        for color, oval_id in self.lights.items():
            self.canvas.itemconfig(oval_id, fill=LIT[color] if color == active_color else DIM[color])

    def start_drag(self, event):
        self._drag = (event.x, event.y)

    def do_drag(self, event):
        x = self.root.winfo_pointerx() - self._drag[0]
        y = self.root.winfo_pointery() - self._drag[1]
        self.root.geometry(f"+{x}+{y}")

    def close(self):
        """Closing the light dismisses the widget only -- the Claude Code
        session keeps running. Dropping the state file frees the slot and
        stops the updater writing status nobody is displaying."""
        try:
            os.remove(self.state_path)
        except OSError:
            pass
        self.root.destroy()

    def poll(self):
        self.poll_count += 1
        state = read_state(self.state_path)

        if state is None:
            self.missing_count += 1
            if self.missing_count >= MISSING_GRACE_POLLS:
                self.root.destroy()
                sys.exit(0)
            self.root.after(POLL_MS, self.poll)
            return

        self.missing_count = 0

        if state:
            self.claude_pid = state.get("claude_pid", self.claude_pid)
            label = state.get("label")
            if label and shorten(label) != self.label_var.get():
                self.label_var.set(shorten(label))
            color = state.get("color", "green")
            if color not in LIT:
                color = "green"
            if color != self.last:
                self.set_active(color)
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
                self.root.destroy()
                sys.exit(0)

        self.root.after(POLL_MS, self.poll)


def main():
    parser = argparse.ArgumentParser(description="Claude Code traffic light widget")
    parser.add_argument("--session", default="default",
                        help="Claude Code session id this light belongs to")
    parser.add_argument("--label", default="", help="text shown under the lights")
    parser.add_argument("--slot", type=int, default=0,
                        help="position index, so parallel sessions don't overlap")
    args = parser.parse_args()

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    root = tk.Tk()
    TrafficLight(root, session_file(args.session), args.label, args.slot)
    root.mainloop()


if __name__ == "__main__":
    main()

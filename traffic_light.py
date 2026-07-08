"""
traffic_light.py
Always-on-top widget with a real traffic-light housing (red/yellow/green
stacked, inactive lights dimmed) and an X button to close.
Polls status.json every 300ms. Also exits if the status file disappears
(SessionEnd/stop).
"""
import tkinter as tk
import json
import os
import sys

BASE_DIR = os.path.join(os.path.expanduser("~"), ".claude_traffic")
STATUS_FILE = os.path.join(BASE_DIR, "status.json")

LIT = {"green": "#2ecc71", "yellow": "#f1c40f", "red": "#e74c3c"}
DIM = {"green": "#1e3d2c", "yellow": "#3d3419", "red": "#3d1f1c"}
HOUSING_BG = "#1c1c1c"
POLL_MS = 300
MISSING_GRACE_POLLS = 5

WIDTH = 60
HEIGHT = 150
CIRCLE_D = 38
PAD_X = (WIDTH - CIRCLE_D) // 2
GAP = 8
TITLEBAR_H = 22


def read_status():
    try:
        with open(STATUS_FILE, "r") as f:
            data = json.load(f)
        color = data.get("color", "green")
        return color if color in LIT else "green"
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return None


class TrafficLight:
    def __init__(self, root):
        self.root = root
        self.missing_count = 0
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.geometry(f"{WIDTH}x{HEIGHT + TITLEBAR_H}+80+80")
        root.configure(bg=HOUSING_BG)

        # --- title bar with drag + close button ---
        titlebar = tk.Frame(root, bg="#111111", height=TITLEBAR_H)
        titlebar.pack(fill="x", side="top")
        titlebar.pack_propagate(False)

        close_btn = tk.Label(titlebar, text="\u2715", fg="#999999", bg="#111111",
                              font=("Segoe UI", 10, "bold"), cursor="hand2")
        close_btn.pack(side="right", padx=6)
        close_btn.bind("<Button-1>", lambda e: root.destroy())
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

    def poll(self):
        status = read_status()
        if status is None:
            self.missing_count += 1
            if self.missing_count >= MISSING_GRACE_POLLS:
                self.root.destroy()
                sys.exit(0)
        else:
            self.missing_count = 0
            if status != self.last:
                self.set_active(status)
                self.last = status
        self.root.after(POLL_MS, self.poll)


if __name__ == "__main__":
    root = tk.Tk()
    TrafficLight(root)
    root.mainloop()
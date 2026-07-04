"""
traffic_light.py
Always-on-top widget with a real traffic-light housing (red/yellow/green
stacked, inactive lights dimmed), rounded corners, a soft glow on the
active light (pulsing while yellow), and a resize grip. Right-click for
orientation / opacity / always-on-top. Position, size, orientation and
opacity persist across restarts.
Polls status.json every 300ms. Also exits if the status file disappears
(SessionEnd/stop).
"""
import tkinter as tk
from tkinter import Menu
import json
import math
import os
import sys

BASE_DIR = os.path.join(os.path.expanduser("~"), ".claude_traffic")
STATUS_FILE = os.path.join(BASE_DIR, "status.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

LIT = {"green": "#2ecc71", "yellow": "#f1c40f", "red": "#e74c3c"}
DIM = {"green": "#1e3d2c", "yellow": "#3d3419", "red": "#3d1f1c"}
HOUSING_BG = "#1c1c1c"
TITLEBAR_BG = "#111111"
BORDER_COLOR = "#0a0a0a"
TRANSPARENT_KEY = "#ff00fe"  # chroma-key color; window corners cut to this become see-through

ORDER = ["red", "yellow", "green"]
POLL_MS = 300
PULSE_MS = 60
MISSING_GRACE_POLLS = 5

TITLEBAR_H = 22
CORNER_R = 12
GRIP_SIZE = 14
MIN_DIM = 50
MAX_DIM = 500

DEFAULT_CONFIG = {
    "x": 80, "y": 80,
    "width": 60, "height": 172,
    "orientation": "vertical",
    "opacity": 1.0,
    "topmost": True,
}


def read_status():
    try:
        with open(STATUS_FILE, "r") as f:
            data = json.load(f)
        color = data.get("color", "green")
        return color if color in LIT else "green"
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return None


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f)
    except OSError:
        pass


def blend(hex1, hex2, t):
    """Mix hex1 and hex2, t=1 -> hex1, t=0 -> hex2."""
    r1, g1, b1 = int(hex1[1:3], 16), int(hex1[3:5], 16), int(hex1[5:7], 16)
    r2, g2, b2 = int(hex2[1:3], 16), int(hex2[3:5], 16), int(hex2[5:7], 16)
    r = round(r1 * t + r2 * (1 - t))
    g = round(g1 * t + g2 * (1 - t))
    b = round(b1 * t + b2 * (1 - t))
    return f"#{r:02x}{g:02x}{b:02x}"


GLOW = {c: blend(LIT[c], HOUSING_BG, 0.35) for c in LIT}


def rounded_rect_points(x0, y0, x1, y1, radii, steps=8):
    """radii = (top-left, top-right, bottom-right, bottom-left); 0 = square corner."""
    r_tl, r_tr, r_br, r_bl = radii
    pts = []

    def arc(cx, cy, r, start_deg, end_deg):
        for i in range(steps + 1):
            ang = math.radians(start_deg + (end_deg - start_deg) * i / steps)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))

    arc(x0 + r_tl, y0 + r_tl, r_tl, 180, 270)
    arc(x1 - r_tr, y0 + r_tr, r_tr, 270, 360)
    arc(x1 - r_br, y1 - r_br, r_br, 0, 90)
    arc(x0 + r_bl, y1 - r_bl, r_bl, 90, 180)
    flat = []
    for x, y in pts:
        flat.extend((x, y))
    return flat


class TrafficLight:
    def __init__(self, root):
        self.root = root
        self.missing_count = 0
        self.cfg = load_config()
        self.width = self.cfg["width"]
        self.height = self.cfg["height"]
        self.orientation = self.cfg["orientation"]
        self.last = None
        self.pulse_phase = 0.0
        self.mode = None  # "drag" | "resize" | None
        self.drag_origin = (0, 0)
        self.glow_ids = {}
        self.circle_ids = {}
        self.close_bbox = (0, 0, 0, 0)
        self.grip_bbox = (0, 0, 0, 0)

        root.overrideredirect(True)
        root.attributes("-topmost", self.cfg["topmost"])
        root.attributes("-transparentcolor", TRANSPARENT_KEY)
        root.attributes("-alpha", self.cfg["opacity"])
        root.geometry(f"{self.width}x{self.height}+{self.cfg['x']}+{self.cfg['y']}")

        self.canvas = tk.Canvas(root, width=self.width, height=self.height,
                                 highlightthickness=0, bg=TRANSPARENT_KEY)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_hover)
        self.canvas.bind("<Button-3>", self.show_menu)

        self.orientation_var = tk.StringVar(value=self.orientation)
        self.opacity_var = tk.DoubleVar(value=self.cfg["opacity"])
        self.topmost_var = tk.BooleanVar(value=self.cfg["topmost"])
        self._build_menu()

        self.relayout()
        self.set_active("green")
        self.poll()
        self.animate()

    # ---------- menu ----------
    def _build_menu(self):
        self.menu = Menu(self.root, tearoff=0)

        orient_menu = Menu(self.menu, tearoff=0)
        for label, value in (("Vertical", "vertical"), ("Horizontal", "horizontal")):
            orient_menu.add_radiobutton(label=label, value=value, variable=self.orientation_var,
                                         command=self.set_orientation)
        self.menu.add_cascade(label="Orientation", menu=orient_menu)

        opacity_menu = Menu(self.menu, tearoff=0)
        for pct in (100, 85, 70, 55):
            opacity_menu.add_radiobutton(label=f"{pct}%", value=pct / 100,
                                          variable=self.opacity_var, command=self.set_opacity)
        self.menu.add_cascade(label="Opacity", menu=opacity_menu)

        self.menu.add_checkbutton(label="Always on top", variable=self.topmost_var,
                                   command=self.toggle_topmost)
        self.menu.add_separator()
        self.menu.add_command(label="Close", command=self.root.destroy)

    def show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def set_orientation(self):
        new_orientation = self.orientation_var.get()
        if new_orientation != self.orientation:
            self.orientation = new_orientation
            self.width, self.height = self.height, self.width
            win_x, win_y = self.root.winfo_x(), self.root.winfo_y()
            self.root.geometry(f"{self.width}x{self.height}+{win_x}+{win_y}")
            self.relayout()
            self.set_active(self.last or "green")
            self._save()

    def set_opacity(self):
        self.root.attributes("-alpha", self.opacity_var.get())
        self._save()

    def toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get())
        self._save()

    def _save(self):
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        save_config({
            "x": x, "y": y, "width": self.width, "height": self.height,
            "orientation": self.orientation, "opacity": self.opacity_var.get(),
            "topmost": self.topmost_var.get(),
        })

    # ---------- layout ----------
    def relayout(self):
        self.canvas.config(width=self.width, height=self.height)
        self.canvas.delete("all")

        bg_points = rounded_rect_points(1, 1, self.width - 1, self.height - 1,
                                         (CORNER_R,) * 4)
        self.canvas.create_polygon(bg_points, fill=HOUSING_BG, outline=BORDER_COLOR, width=1)

        title_points = rounded_rect_points(1, 1, self.width - 1, TITLEBAR_H,
                                            (CORNER_R, CORNER_R, 0, 0))
        self.canvas.create_polygon(title_points, fill=TITLEBAR_BG, outline="")

        cx0, cy0 = self.width - 18, 4
        cx1, cy1 = self.width - 6, 16
        self.close_bbox = (cx0 - 3, cy0 - 3, cx1 + 3, cy1 + 3)
        self.canvas.create_line(cx0, cy0, cx1, cy1, fill="#999999", width=2, tags="close")
        self.canvas.create_line(cx0, cy1, cx1, cy0, fill="#999999", width=2, tags="close")

        gx0, gy0 = self.width - GRIP_SIZE, self.height - GRIP_SIZE
        self.grip_bbox = (gx0, gy0, self.width, self.height)
        for off in (4, 8, 12):
            self.canvas.create_line(self.width - off, self.height - 2,
                                     self.width - 2, self.height - off,
                                     fill="#555555", width=1)

        self.glow_ids = {}
        self.circle_ids = {}
        housing_h = self.height - TITLEBAR_H
        if self.orientation == "vertical":
            pad = max(6, int(self.width * 0.15))
            avail_w = self.width - 2 * pad
            gap = max(4, int(housing_h * 0.04))
            d = max(10, min(avail_w, (housing_h - gap * 4) / 3))
            total_h = 3 * d + 4 * gap
            start_y = TITLEBAR_H + gap + max(0, (housing_h - total_h) / 2)
            for i, color in enumerate(ORDER):
                cx = self.width / 2
                cy = start_y + d / 2 + i * (d + gap)
                self._make_light(color, cx, cy, d)
        else:
            pad = max(6, int(housing_h * 0.15))
            avail_h = housing_h - 2 * pad
            gap = max(4, int(self.width * 0.04))
            d = max(10, min(avail_h, (self.width - gap * 4) / 3))
            total_w = 3 * d + 4 * gap
            start_x = gap + max(0, (self.width - total_w) / 2)
            for i, color in enumerate(ORDER):
                cx = start_x + d / 2 + i * (d + gap)
                cy = TITLEBAR_H + housing_h / 2
                self._make_light(color, cx, cy, d)

    def _make_light(self, color, cx, cy, d):
        glow_r = d * 0.65
        self.glow_ids[color] = self.canvas.create_oval(
            cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r,
            fill=HOUSING_BG, outline="")
        self.circle_ids[color] = self.canvas.create_oval(
            cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2,
            fill=DIM[color], outline=BORDER_COLOR, width=2)
        self.canvas.tag_raise(self.circle_ids[color], self.glow_ids[color])

    # ---------- state ----------
    def set_active(self, active_color):
        for color, oval_id in self.circle_ids.items():
            lit = color == active_color
            self.canvas.itemconfig(oval_id, fill=LIT[color] if lit else DIM[color])
            self.canvas.itemconfig(self.glow_ids[color], fill=GLOW[color] if lit else HOUSING_BG)

    def animate(self):
        active = self.last
        if active and active in self.glow_ids:
            cx0, cy0, cx1, cy1 = self.canvas.coords(self.circle_ids[active])
            d = cx1 - cx0
            cx, cy = (cx0 + cx1) / 2, (cy0 + cy1) / 2
            if active == "yellow":
                self.pulse_phase += 0.25
                scale = 0.55 + 0.15 * (1 + math.sin(self.pulse_phase))
            else:
                scale = 0.65
            r = d * scale
            self.canvas.coords(self.glow_ids[active], cx - r, cy - r, cx + r, cy + r)
        self.root.after(PULSE_MS, self.animate)

    # ---------- mouse ----------
    def _hit(self, bbox, x, y):
        x0, y0, x1, y1 = bbox
        return x0 <= x <= x1 and y0 <= y <= y1

    def on_press(self, event):
        if self._hit(self.close_bbox, event.x, event.y):
            self.root.destroy()
            return
        if self._hit(self.grip_bbox, event.x, event.y):
            self.mode = "resize"
            self.drag_origin = (event.x_root, event.y_root, self.width, self.height,
                                 self.root.winfo_x(), self.root.winfo_y())
        else:
            self.mode = "drag"
            self.drag_origin = (event.x, event.y)

    def on_motion(self, event):
        if self.mode == "drag":
            x = self.root.winfo_pointerx() - self.drag_origin[0]
            y = self.root.winfo_pointery() - self.drag_origin[1]
            self.root.geometry(f"+{x}+{y}")
        elif self.mode == "resize":
            ox, oy, ow, oh, win_x, win_y = self.drag_origin
            new_w = min(MAX_DIM, max(MIN_DIM, ow + (event.x_root - ox)))
            new_h = min(MAX_DIM, max(MIN_DIM, oh + (event.y_root - oy)))
            if new_w != self.width or new_h != self.height:
                self.width, self.height = new_w, new_h
                # pin top-left explicitly: Windows DPI virtualization can drift
                # window position when only WxH is given to geometry()
                self.root.geometry(f"{int(self.width)}x{int(self.height)}+{win_x}+{win_y}")
                self.relayout()
                self.set_active(self.last or "green")

    def on_release(self, event):
        if self.mode in ("drag", "resize"):
            self._save()
        self.mode = None

    def on_hover(self, event):
        if self._hit(self.grip_bbox, event.x, event.y):
            self.canvas.config(cursor="size_nw_se")
        elif self._hit(self.close_bbox, event.x, event.y):
            self.canvas.config(cursor="hand2")
        else:
            self.canvas.config(cursor="")

    # ---------- polling ----------
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

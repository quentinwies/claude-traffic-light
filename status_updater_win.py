"""
status_updater.py
Writes traffic-light state to a JSON file and manages the GUI process.

Usage:
    pythonw status_updater.py start          # launch GUI, set green
    python  status_updater.py yellow         # working
    python  status_updater.py red            # needs your input
    python  status_updater.py green          # idle
    python  status_updater.py stop           # kill GUI

State file: %USERPROFILE%\\.claude_traffic\\status.json
PID file:   %USERPROFILE%\\.claude_traffic\\gui.pid
"""
import sys
import os
import json
import subprocess
import time

BASE_DIR = os.path.join(os.path.expanduser("~"), ".claude_traffic")
STATUS_FILE = os.path.join(BASE_DIR, "status.json")
PID_FILE = os.path.join(BASE_DIR, "gui.pid")
GUI_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traffic_light.py")

os.makedirs(BASE_DIR, exist_ok=True)


def write_status(color):
    with open(STATUS_FILE, "w") as f:
        json.dump({"color": color, "ts": time.time()}, f)


def gui_running():
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        # Windows: check if process with this PID exists
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def start_gui():
    if gui_running():
        write_status("green")
        return
    proc = subprocess.Popen(
        ["pythonw", GUI_SCRIPT],
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    write_status("green")


def stop_gui():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        except Exception:
            pass
        finally:
            os.remove(PID_FILE)
    if os.path.exists(STATUS_FILE):
        os.remove(STATUS_FILE)


def main():
    if len(sys.argv) < 2:
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "start":
        start_gui()
    elif cmd == "stop":
        stop_gui()
    elif cmd in ("green", "yellow", "red"):
        write_status(cmd)
    # unknown command: no-op, never block Claude Code


if __name__ == "__main__":
    main()
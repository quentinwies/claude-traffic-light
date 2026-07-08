"""
status_updater_mac.py
macOS version. Writes traffic-light state to a JSON file and manages
the GUI process using ps/kill instead of tasklist/taskkill.

Usage:
    python3 status_updater_mac.py start          # launch GUI, set green
    python3 status_updater_mac.py yellow         # working
    python3 status_updater_mac.py red            # needs your input
    python3 status_updater_mac.py green          # idle
    python3 status_updater_mac.py stop           # kill GUI

State file: ~/.claude_traffic/status.json
PID file:   ~/.claude_traffic/gui.pid
"""
import sys
import os
import json
import subprocess
import time
import signal

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
        os.kill(pid, 0)  # signal 0: existence check only, raises if no such process
        return True
    except (ProcessLookupError, ValueError, OSError):
        return False


def start_gui():
    if gui_running():
        write_status("green")
        return
    proc = subprocess.Popen(
        ["python3", GUI_SCRIPT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    write_status("green")


def stop_gui():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, ValueError, OSError):
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


if __name__ == "__main__":
    main()
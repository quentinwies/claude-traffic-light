"""
status_updater_win.py
Windows version. Writes traffic-light state and manages the GUI process
using Win32 process handles and taskkill.

One light per Claude Code session: the session id arrives on stdin as
part of the hook payload (falling back to %CLAUDE_CODE_SESSION_ID%), and
each session gets its own state file, its own GUI process and its own
screen slot.

Usage:
    pythonw status_updater_win.py start          # launch this session's light
    python  status_updater_win.py yellow         # working
    python  status_updater_win.py red            # needs your input
    python  status_updater_win.py green          # idle
    python  status_updater_win.py stop           # close this session's light

State files: %USERPROFILE%\\.claude_traffic\\sessions\\<session_id>.json
"""
import contextlib
import ctypes
import json
import os
import subprocess
import sys
import time

BASE_DIR = os.path.join(os.path.expanduser("~"), ".claude_traffic")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
LOCK_FILE = os.path.join(BASE_DIR, "slots.lock")
GUI_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traffic_light.py")

# Pre-1.1 single-session layout, cleaned up on first start.
LEGACY_STATUS_FILE = os.path.join(BASE_DIR, "status.json")
LEGACY_PID_FILE = os.path.join(BASE_DIR, "gui.pid")

# A session file with no gui_pid yet is being started by another process;
# leave it alone until it is older than this.
STARTUP_GRACE_S = 30

os.makedirs(SESSIONS_DIR, exist_ok=True)


def gui_python():
    """pythonw.exe next to the interpreter running this hook: keeps the
    widget console-free without depending on PATH, which the hook shell
    may not resolve the way an interactive terminal does."""
    exe = sys.executable or ""
    directory, name = os.path.split(exe)
    if name.lower() == "python.exe":
        candidate = os.path.join(directory, "pythonw.exe")
        if os.path.exists(candidate):
            return candidate
    return exe or "pythonw"


# --- hook payload -----------------------------------------------------

def hook_payload():
    """Claude Code pipes a JSON payload (session_id, cwd, ...) into every
    hook. Absent or malformed input must never break the hook."""
    if sys.stdin is None:
        return {}
    try:
        if sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def session_identity(payload):
    session_id = payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "default"
    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    claude_pid = os.environ.get("CLAUDE_PID")
    # Keep the id filesystem-safe; real ids are uuids, but don't trust that.
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(session_id))
    return safe_id, os.path.basename(os.path.normpath(cwd)) or cwd, claude_pid


def session_file(session_id):
    return os.path.join(SESSIONS_DIR, session_id + ".json")


# --- state files ------------------------------------------------------

def load_state(path):
    try:
        with open(path, "r") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return None


def save_state(path, state):
    """Write atomically -- the widget polls this file 3x a second and must
    never catch it half-written."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def update_state(path, **fields):
    state = load_state(path) or {}
    state.update(fields)
    state["ts"] = time.time()
    save_state(path, state)
    return state


def iter_states():
    try:
        names = os.listdir(SESSIONS_DIR)
    except OSError:
        return
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(SESSIONS_DIR, name)
        state = load_state(path)
        if state is not None:
            yield path, state


# --- processes --------------------------------------------------------

def pid_alive(pid):
    """Probe via OpenProcess. os.kill() is not an option here: on Windows
    it terminates the target even with signal 0, and tasklist would spawn
    a subprocess on every single hook."""
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False

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


def kill_pid(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"],
                       capture_output=True)
    except (OSError, ValueError):
        pass


@contextlib.contextmanager
def slot_lock(timeout=2.0):
    """Serialize sweep+allocate so two sessions starting at once can't
    claim the same slot. Never blocks a session start for good: a lock
    held too long is assumed stale and taken over."""
    fd = None
    deadline = time.time() + timeout
    while fd is None:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.time() > deadline:
                try:
                    os.remove(LOCK_FILE)
                except OSError:
                    pass
                try:
                    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except OSError:
                    break  # give up on locking rather than hang the hook
            else:
                time.sleep(0.05)
        except OSError:
            break
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
            try:
                os.remove(LOCK_FILE)
            except OSError:
                pass


def sweep(skip=None):
    """Drop state files whose widget or whose Claude Code session is gone,
    so their slots become available again."""
    now = time.time()
    for path, state in iter_states():
        if skip and os.path.basename(path) == skip + ".json":
            continue
        gui_pid = state.get("gui_pid")
        if gui_pid:
            if not pid_alive(gui_pid):
                _discard(path)
                continue
        elif now - state.get("ts", 0) > STARTUP_GRACE_S:
            _discard(path)
            continue
        claude_pid = state.get("claude_pid")
        if claude_pid and not pid_alive(claude_pid):
            if gui_pid and pid_alive(gui_pid):
                kill_pid(gui_pid)
            _discard(path)


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass


def allocate_slot():
    used = set()
    for _, state in iter_states():
        slot = state.get("slot")
        if isinstance(slot, int):
            used.add(slot)
    slot = 0
    while slot in used:
        slot += 1
    return slot


def clear_legacy():
    """Retire a widget left over from the pre-multi-session layout."""
    if os.path.exists(LEGACY_PID_FILE):
        try:
            with open(LEGACY_PID_FILE) as f:
                kill_pid(f.read().strip())
        except OSError:
            pass
        _discard(LEGACY_PID_FILE)
    _discard(LEGACY_STATUS_FILE)


# --- commands ---------------------------------------------------------

def start_gui(session_id, label, claude_pid):
    clear_legacy()
    path = session_file(session_id)

    existing = load_state(path)
    if existing and pid_alive(existing.get("gui_pid")):
        # SessionStart also fires on resume/clear/compact -- don't spawn a
        # second light for a session that already has one.
        update_state(path, color="green", label=label, claude_pid=claude_pid)
        return

    with slot_lock():
        sweep(skip=session_id)
        slot = allocate_slot()
        update_state(path, color="green", label=label, slot=slot,
                     claude_pid=claude_pid, gui_pid=None)

    creationflags = 0
    for flag in ("CREATE_NO_WINDOW", "DETACHED_PROCESS"):
        creationflags |= getattr(subprocess, flag, 0)
    proc = subprocess.Popen(
        [gui_python(), GUI_SCRIPT, "--session", session_id,
         "--label", label, "--slot", str(slot)],
        creationflags=creationflags
    )
    update_state(path, gui_pid=proc.pid)


def stop_gui(session_id):
    path = session_file(session_id)
    state = load_state(path)
    if state:
        gui_pid = state.get("gui_pid")
        if gui_pid and pid_alive(gui_pid):
            kill_pid(gui_pid)
    _discard(path)
    sweep()


def write_status(session_id, color):
    """No-op when the session has no state file: either the session never
    started a light, or the user closed it by hand and shouldn't get it
    resurrected on the next tool call."""
    path = session_file(session_id)
    if not os.path.exists(path):
        return
    update_state(path, color=color)


def main():
    if len(sys.argv) < 2:
        sys.exit(0)
    cmd = sys.argv[1]
    session_id, label, claude_pid = session_identity(hook_payload())

    if cmd == "start":
        start_gui(session_id, label, claude_pid)
    elif cmd == "stop":
        stop_gui(session_id)
    elif cmd in ("green", "yellow", "red"):
        write_status(session_id, cmd)
    # unknown command: no-op, never block Claude Code


if __name__ == "__main__":
    main()

"""
status_updater_mac.py
macOS version. Writes traffic-light state and manages the GUI process
using os.kill instead of tasklist/taskkill.

One light per Claude Code session: the session id arrives on stdin as
part of the hook payload (falling back to $CLAUDE_CODE_SESSION_ID), and
each session gets its own state file, its own GUI process (if the
display mode uses one) and its own screen slot.

Usage:
    python3 status_updater_mac.py start          # launch this session's light
    python3 status_updater_mac.py yellow         # working
    python3 status_updater_mac.py red            # needs your input
    python3 status_updater_mac.py green          # idle
    python3 status_updater_mac.py stop           # close this session's light
    python3 status_updater_mac.py display              # print the active display modes
    python3 status_updater_mac.py display <mode...>    # set them, e.g. "display menubar notification"
    python3 status_updater_mac.py controller start|stop  # the menu bar switcher

Display modes -- any combination is valid, applied live to every tracked
session (see switch_active_modes):
    window       floating always-on-top widget (default)
    menubar      colored dot in the macOS menu bar (needs `pip install rumps`)
    notification a macOS notification each time the light turns red or green

A fixed traffic-light icon (traffic_light_controller.py) lives in the menu
bar whenever `rumps` is installed, independent of the chosen display
mode(s) -- it's the switcher, not a session light. Its dropdown is a set of
independent checkboxes, so e.g. menubar + notification together is a normal
combination, not just one mode at a time. status_updater_mac.py starts it
automatically on the first SessionStart it sees (and whenever `display` is
run by hand) and keeps exactly one instance alive via controller.pid.

State files: ~/.claude_traffic/sessions/<session_id>.json
Config file: ~/.claude_traffic/config.json
"""
import contextlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time

PYTHON_EXE = sys.executable  # guarantees we relaunch with the SAME interpreter
                              # that ran this script, bypassing PATH lookup

BASE_DIR = os.path.join(os.path.expanduser("~"), ".claude_traffic")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
LOCK_FILE = os.path.join(BASE_DIR, "slots.lock")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
GUI_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traffic_light.py")
MENUBAR_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traffic_light_menubar.py")
CONTROLLER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traffic_light_controller.py")
CONTROLLER_PID_FILE = os.path.join(BASE_DIR, "controller.pid")

DISPLAY_MODES = ("window", "menubar", "notification")

# Pre-1.1 single-session layout, cleaned up on first start.
LEGACY_STATUS_FILE = os.path.join(BASE_DIR, "status.json")
LEGACY_PID_FILE = os.path.join(BASE_DIR, "gui.pid")

# A session file with no gui_pid yet is being started by another process;
# leave it alone until it is older than this.
STARTUP_GRACE_S = 30

os.makedirs(SESSIONS_DIR, exist_ok=True)


# --- hook payload -----------------------------------------------------

def hook_payload():
    """Claude Code pipes a JSON payload (session_id, cwd, ...) into every
    hook. Absent or malformed input must never break the hook."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
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
    return safe_id, os.path.basename(os.path.normpath(cwd)) or cwd, claude_pid, cwd


def repo_name(cwd):
    """Name of the git repository containing `cwd` (so a session opened in
    a subfolder still reports the repo), else the folder name itself. Only
    called on SessionStart, never on the per-tool-call colour writes."""
    try:
        result = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True, timeout=2)
        top = result.stdout.strip()
        if result.returncode == 0 and top:
            return os.path.basename(top)
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.basename(os.path.normpath(cwd)) or cwd


def session_file(session_id):
    return os.path.join(SESSIONS_DIR, session_id + ".json")


# --- display mode -------------------------------------------------------

def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        return config if isinstance(config, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return {}


def save_config(config):
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(config, f)
    os.replace(tmp, CONFIG_FILE)


def active_modes():
    """The set of currently enabled display modes. Any combination of
    DISPLAY_MODES is valid, including empty (deliberately silenced) --
    only a missing/corrupt config falls back to the {"window"} default."""
    modes = load_config().get("display_modes")
    if not isinstance(modes, list):
        return {"window"}
    return {m for m in modes if m in DISPLAY_MODES}


def set_active_modes(modes):
    config = load_config()
    config["display_modes"] = sorted(set(modes) & set(DISPLAY_MODES))
    save_config(config)


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

def pid_zombie(pid):
    """A process killed but not yet reaped by its parent still answers
    os.kill(pid, 0). ps knows the difference. Only reached from start/stop,
    never from the per-tool-call colour writes, so the cost is fine."""
    try:
        result = subprocess.run(["ps", "-o", "state=", "-p", str(int(pid))],
                                capture_output=True, text=True, timeout=2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return result.stdout.strip().startswith("Z")


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (TypeError, ValueError):
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    except OSError:
        return False
    return not pid_zombie(pid)


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
    """Drop state files whose widget(s) or whose Claude Code session is
    gone, so their slots become available again. A session can have zero,
    one or two widget processes (window and/or menubar) depending on its
    modes; notification needs none at all."""
    now = time.time()
    for path, state in iter_states():
        if skip and os.path.basename(path) == skip + ".json":
            continue

        modes = state.get("modes") or []
        widgets = state.get("widgets") or {}
        wanted = [k for k in ("window", "menubar") if k in modes]
        recorded = {k: widgets.get(k) for k in wanted}

        # A widget that should exist but died unexpectedly (not via its own
        # close(), which deletes this file itself) orphans the session.
        if any(pid and not pid_alive(pid) for pid in recorded.values()):
            _discard(path)
            continue
        # Still waiting for a widget this session is supposed to have --
        # give the spawning process a moment before assuming it failed.
        if wanted and not all(recorded.values()) and now - state.get("ts", 0) > STARTUP_GRACE_S:
            _discard(path)
            continue

        claude_pid = state.get("claude_pid")
        if claude_pid and not pid_alive(claude_pid):
            for pid in widgets.values():
                if pid and pid_alive(pid):
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                    except (OSError, ValueError):
                        pass
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
                os.kill(int(f.read().strip()), signal.SIGTERM)
        except (OSError, ValueError):
            pass
        _discard(LEGACY_PID_FILE)
    _discard(LEGACY_STATUS_FILE)


# --- commands ---------------------------------------------------------

def reconcile_widgets(path, state, modes):
    """Make this session's running widget processes match `modes`: stop any
    widget whose kind fell out of the set, start any missing one whose kind
    is now wanted, leave one already running alone. Idempotent -- safe to
    call on every SessionStart and every mode change. Notification has no
    process of its own; write_status() checks `modes` at fire time."""
    widgets = dict(state.get("widgets") or {})
    session_id = os.path.basename(path)[: -len(".json")]
    label = state.get("label", "")
    slot = state.get("slot")

    for kind in ("window", "menubar"):
        pid = widgets.get(kind)
        if kind not in modes:
            if pid and pid_alive(pid):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (OSError, ValueError):
                    pass
            widgets[kind] = None
            continue
        if pid and pid_alive(pid):
            continue  # already running as wanted
        if slot is None:
            with slot_lock():
                sweep(skip=session_id)
                slot = allocate_slot()
        proc = subprocess.Popen(
            [PYTHON_EXE, MENUBAR_SCRIPT if kind == "menubar" else GUI_SCRIPT,
             "--session", session_id, "--label", label, "--slot", str(slot)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        widgets[kind] = proc.pid

    update_state(path, modes=sorted(modes), widgets=widgets, slot=slot)


def start_gui(session_id, label, claude_pid, cwd):
    clear_legacy()
    ensure_controller()
    path = session_file(session_id)
    modes = active_modes()
    repo = repo_name(cwd)

    if load_state(path) is None:
        with slot_lock():
            sweep(skip=session_id)
            update_state(path, color="green", label=label, repo=repo, claude_pid=claude_pid,
                         modes=sorted(modes), widgets={})
    else:
        # SessionStart also fires on resume/clear/compact -- refresh the
        # header fields, then let reconcile bring widgets up to date
        # rather than assuming a stale one is still alive.
        update_state(path, color="green", label=label, repo=repo, claude_pid=claude_pid)

    reconcile_widgets(path, load_state(path), modes)


def stop_gui(session_id):
    path = session_file(session_id)
    state = load_state(path)
    if state:
        for pid in (state.get("widgets") or {}).values():
            if pid and pid_alive(pid):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (OSError, ValueError):
                    pass
    _discard(path)
    sweep()
    if not any_sessions():
        stop_controller()  # last session gone -- take the switcher with it


def any_sessions():
    return next(iter_states(), None) is not None


def switch_active_modes(new_modes):
    """Re-point every currently tracked session at a new set of display
    modes right away, instead of waiting for its next SessionStart. Used
    by the menu bar controller so toggling a mode there applies live."""
    for path, state in iter_states():
        reconcile_widgets(path, state, new_modes)


def _controller_available():
    return importlib.util.find_spec("rumps") is not None


def ensure_controller():
    """Keep exactly one mode-switcher menu bar item alive, independent of
    any single session. Best-effort and silent: a missing `rumps` just
    means no controller, never a blocked hook."""
    if not _controller_available():
        return
    pid = None
    try:
        with open(CONTROLLER_PID_FILE) as f:
            pid = f.read().strip()
    except OSError:
        pass
    if pid and pid_alive(pid):
        return
    try:
        proc = subprocess.Popen(
            [PYTHON_EXE, CONTROLLER_SCRIPT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    except OSError:
        return
    try:
        with open(CONTROLLER_PID_FILE, "w") as f:
            f.write(str(proc.pid))
    except OSError:
        pass


def stop_controller():
    pid = None
    try:
        with open(CONTROLLER_PID_FILE) as f:
            pid = f.read().strip()
    except OSError:
        pass
    if pid and pid_alive(pid):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError):
            pass
    _discard(CONTROLLER_PID_FILE)


ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
NOTIFY_EMOJI = {"red": "\U0001F534", "green": "\U0001F7E2"}
NOTIFY_MESSAGE = {"red": "Claude needs your input", "green": "Claude finished"}

# macOS shows the *sending app's* icon on a notification, and plain
# osascript notifications come from Script Editor. So notify() goes through
# a tiny AppleScript droplet of our own, built on first use with tools that
# ship with macOS (osacompile, sips, iconutil, codesign -- no Xcode), whose
# app icon is assets/traffic-light.png. It can't take command-line
# arguments, so each notification is a small text file handed to its
# `on open` handler: title, message, sound name, one per line.
NOTIFIER_NAME = "Claude Traffic Light"
NOTIFIER_APP = os.path.join(BASE_DIR, NOTIFIER_NAME + ".app")
NOTIFIER_ICON = os.path.join(ASSETS_DIR, "traffic-light.png")
NOTIFY_QUEUE_DIR = os.path.join(BASE_DIR, "notify")
# Bump when the droplet's script or icon changes -- the app is rebuilt
# whenever its stamp doesn't match. It's also part of the bundle id:
# Notification Center caches app icons per bundle id and never notices a
# new icon under an old id (macOS then asks for permission once more).
NOTIFIER_VERSION = "2"
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
              "LaunchServices.framework/Support/lsregister")
NOTIFIER_STAMP = os.path.join(NOTIFIER_APP, "Contents", "Resources", "ctl-version")
NOTIFIER_SOURCE = """\
on open theFiles
	repeat with f in theFiles
		set lns to paragraphs of (read f as «class utf8»)
		try
			do shell script "rm -f " & quoted form of (POSIX path of f)
		end try
		if (count of lns) >= 2 then
			set snd to ""
			if (count of lns) >= 3 then set snd to item 3 of lns
			if snd is "" then
				display notification (item 2 of lns) with title (item 1 of lns)
			else
				display notification (item 2 of lns) with title (item 1 of lns) sound name snd
			end if
		end if
	end repeat
end open
"""


def _notifier_ready():
    try:
        with open(NOTIFIER_STAMP) as f:
            return f.read().strip() == NOTIFIER_VERSION
    except OSError:
        return False


def build_notifier():
    """Build the droplet in a scratch dir and move it into place, so a
    half-built app is never used and two hooks building at once can't
    trample each other. Returns whether a usable app is in place."""
    import shutil
    import tempfile

    if _notifier_ready():
        return True
    work = tempfile.mkdtemp(prefix="notifier-", dir=BASE_DIR)
    try:
        src = os.path.join(work, "notifier.applescript")
        with open(src, "w", encoding="utf-8") as f:
            f.write(NOTIFIER_SOURCE)
        app = os.path.join(work, NOTIFIER_NAME + ".app")
        contents = os.path.join(app, "Contents")
        resources = os.path.join(contents, "Resources")
        plist = os.path.join(contents, "Info.plist")

        def run(*cmd):
            subprocess.run(cmd, check=True, capture_output=True, timeout=30)

        run("osacompile", "-o", app, src)

        iconset = os.path.join(work, "applet.iconset")
        os.mkdir(iconset)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png"
                px = str(size * scale)
                run("sips", "-z", px, px, NOTIFIER_ICON, "--out", os.path.join(iconset, name))
        run("iconutil", "-c", "icns", iconset, "-o", os.path.join(resources, "applet.icns"))
        # A droplet points CFBundleIconFile at droplet.icns, and newer
        # osacompile also bundles an asset catalog that takes precedence
        # over both -- point everything at our applet.icns.
        _discard(os.path.join(resources, "droplet.icns"))
        _discard(os.path.join(resources, "Assets.car"))
        subprocess.run(["plutil", "-remove", "CFBundleIconName", plist], capture_output=True)
        run("plutil", "-replace", "CFBundleIconFile", "-string", "applet", plist)

        run("plutil", "-replace", "CFBundleIdentifier", "-string",
            "local.claude-traffic-light.notifier.v" + NOTIFIER_VERSION, plist)
        run("plutil", "-replace", "LSUIElement", "-bool", "YES", plist)  # no Dock icon
        with open(os.path.join(resources, "ctl-version"), "w") as f:
            f.write(NOTIFIER_VERSION)
        run("codesign", "--force", "--deep", "--sign", "-", app)

        if _notifier_ready():
            return True  # another hook finished first
        shutil.rmtree(NOTIFIER_APP, ignore_errors=True)
        try:
            os.rename(app, NOTIFIER_APP)
        except OSError:
            pass
        subprocess.run([LSREGISTER, "-f", NOTIFIER_APP], capture_output=True, timeout=30)
        return _notifier_ready()
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _notify_via_app(title, message, sound):
    import uuid

    if not build_notifier():
        return False
    os.makedirs(NOTIFY_QUEUE_DIR, exist_ok=True)
    request = os.path.join(NOTIFY_QUEUE_DIR, uuid.uuid4().hex + ".txt")
    try:
        with open(request, "w", encoding="utf-8") as f:
            f.write("\n".join(s.replace("\n", " ") for s in (title, message, sound or "")))
        result = subprocess.run(["open", "-g", "-a", NOTIFIER_APP, request],
                                capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        _discard(request)
        return False
    if result.returncode != 0:
        _discard(request)
        return False
    return True


def notify(color, repo):
    """Fire a macOS notification for a red/green transition: a colored dot
    plus the repo name as the title, one short line underneath, the
    traffic-light app icon. Best-effort -- a notification that doesn't show
    (e.g. permission not granted) must never block the hook. Falls back to
    plain osascript (Script Editor's icon) if the droplet can't be built."""
    title = NOTIFY_EMOJI[color] + " " + (repo or "Claude Code")
    message = NOTIFY_MESSAGE[color]
    sound = "Ping" if color == "red" else None

    if _notify_via_app(title, message, sound):
        return

    def esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    if sound:
        script += f' sound name "{sound}"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def write_status(session_id, color):
    """No-op when the session has no state file: either the session never
    started a light, or the user closed it by hand and shouldn't get it
    resurrected on the next tool call."""
    path = session_file(session_id)
    if not os.path.exists(path):
        return
    prev_color = (load_state(path) or {}).get("color")
    state = update_state(path, color=color)
    modes = state.get("modes") or []
    if "notification" in modes and color != prev_color and color in ("red", "green"):
        notify(color, state.get("repo") or state.get("label"))


def main():
    if len(sys.argv) < 2:
        sys.exit(0)
    cmd = sys.argv[1]

    if cmd == "display":
        if len(sys.argv) >= 3:
            modes = sys.argv[2:]
            invalid = [m for m in modes if m not in DISPLAY_MODES]
            if invalid:
                print(f"Unknown display mode(s): {', '.join(invalid)}. Choose from: {', '.join(DISPLAY_MODES)}",
                      file=sys.stderr)
                sys.exit(1)
            modes = set(modes)
            set_active_modes(modes)
            switch_active_modes(modes)
            print(f"Display modes set to {{{', '.join(sorted(modes)) or '(none)'}}} "
                  f"and applied to every running session.")
        else:
            print(", ".join(sorted(active_modes())) or "(none)")
        ensure_controller()
        return

    if cmd == "controller":
        sub = sys.argv[2] if len(sys.argv) >= 3 else "start"
        if sub == "stop":
            stop_controller()
        else:
            ensure_controller()
        return

    session_id, label, claude_pid, cwd = session_identity(hook_payload())

    if cmd == "start":
        start_gui(session_id, label, claude_pid, cwd)
    elif cmd == "stop":
        stop_gui(session_id)
    elif cmd in ("green", "yellow", "red"):
        write_status(session_id, cmd)
    # unknown command: no-op, never block Claude Code


if __name__ == "__main__":
    main()

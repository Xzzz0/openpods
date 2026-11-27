"""Updates from GitHub releases.

A release is a git tag `vX.Y.Z` on `main` with a GitHub release (tools/release.sh makes both). OpenPods asks the GitHub
API for the latest release now and then; `openpods update` fast-forwards this checkout's `main` to that tag and runs
install.sh again. Unreleased commits on `main` are never installed by an update.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from . import __version__

log = logging.getLogger("update")

REPO = "Xzzz0/openpods"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "openpods")
UPDATE_LOG = os.path.join(STATE_DIR, "update.log")


def parse_version(v: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(candidate: str, current: str = __version__) -> bool:
    c, cur = parse_version(candidate), parse_version(current)
    return c is not None and cur is not None and c > cur


def fetch_latest(timeout: float = 10) -> dict | None:
    """{'version': '1.2.0', 'url': release page} of the latest release, or None (no release / offline)."""
    req = urllib.request.Request(API_LATEST, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": f"OpenPods/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404 = no release published yet
            log.info("update check failed: HTTP %s", e.code)
        return None
    except (OSError, ValueError) as e:
        log.info("update check failed: %s", e)
        return None
    tag = data.get("tag_name") if isinstance(data, dict) else None
    if not isinstance(tag, str) or parse_version(tag) is None or data.get("draft") or data.get("prerelease"):
        return None
    return {"version": tag.lstrip("v"), "url": data.get("html_url") or RELEASES_URL}


class Checker:
    """Checks in a thread and hands the result to `on_result(info | None)` on the GLib main loop."""

    def __init__(self, on_result):
        self.on_result = on_result
        self.busy = False
        self.last_check = 0.0

    def check(self):
        if self.busy:
            return
        self.busy = True
        from gi.repository import GLib

        def run():
            info = fetch_latest()

            def deliver():
                self.busy = False
                self.last_check = time.time()
                self.on_result(info)
                return False
            GLib.idle_add(deliver)
        threading.Thread(target=run, name="update-check", daemon=True).start()


def start_background_update() -> bool:
    """Runs `openpods update --no-deps` outside this process (it restarts OpenPods). Output -> update.log."""
    os.makedirs(STATE_DIR, exist_ok=True)
    cmd = [os.path.join(ROOT, "bin", "openpods"), "update", "--no-deps"]
    try:
        out = open(UPDATE_LOG, "a", encoding="utf-8")
        out.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} update from {__version__}\n")
        out.flush()
        if shutil.which("systemd-run"):
            # own unit: survives OpenPods quitting during the install
            cmd = ["systemd-run", "--user", "--collect", "--quiet", f"--unit=openpods-update-{int(time.time())}",
                   "-p", f"StandardOutput=append:{UPDATE_LOG}", "-p", f"StandardError=append:{UPDATE_LOG}", *cmd]
            subprocess.Popen(cmd, stdout=out, stderr=out, stdin=subprocess.DEVNULL)
        else:
            subprocess.Popen(cmd, stdout=out, stderr=out, stdin=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError as e:
        log.warning("could not start the update: %s", e)
        return False


# ---------------------------------------------------------------------------------------------- `openpods update`
def _git(*args, check=True) -> str:
    r = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"git {' '.join(args)} failed")
    return r.stdout.strip()


def _tell_app_failed(code: str):
    from . import ctl
    try:
        ctl.send("update.failed", code)
    except Exception:  # noqa: BLE001 - only a courtesy message to a running instance
        pass


def cli(argv: list[str]) -> int:
    """openpods update [--check] [--no-deps]"""
    rc = _cli(argv)
    if rc != 0 and "--check" not in argv:
        _tell_app_failed(str(rc))
    return rc


def _cli(argv: list[str]) -> int:
    check_only = "--check" in argv
    info = fetch_latest()
    if info is None:
        print("Could not get the latest release from GitHub (offline, or no release yet).", file=sys.stderr)
        return 2
    print(f"Installed: {__version__} · latest release: {info['version']}")
    if not is_newer(info["version"]):
        print("OpenPods is up to date.")
        return 0
    if check_only:
        print(f"Update available: {info['url']}\nRun `openpods update` to install it.")
        return 0
    try:
        if not os.path.isdir(os.path.join(ROOT, ".git")):
            raise RuntimeError(f"{ROOT} is not a git checkout – download the new release from {info['url']}")
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        if branch != "main":
            raise RuntimeError(f"the checkout is on branch '{branch}', not 'main' – switch with `git checkout main`")
        if _git("status", "--porcelain", "--untracked-files=no"):
            raise RuntimeError("the checkout has local changes – commit or stash them first")
        tag = f"v{info['version']}"
        print(f"Fetching {tag} …")
        _git("fetch", "--quiet", "--tags", "origin")
        _git("merge", "--ff-only", "--quiet", tag)
    except (RuntimeError, OSError) as e:
        print(f"Update failed: {e}", file=sys.stderr)
        return 3
    print("Installing …")
    args = [os.path.join(ROOT, "install.sh")]
    if "--no-deps" in argv or not sys.stdin.isatty():
        args.append("--no-deps")  # no terminal for the sudo password
    return subprocess.call(args)

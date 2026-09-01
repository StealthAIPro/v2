"""Runtime safety, timing offset, HidHide status, and first-run setup helpers."""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

SETUP_VERSION = 1


def app_data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    path = root / "GameConnectionStabilizer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_state_path() -> Path:
    return app_data_dir() / "setup.json"


def setup_complete() -> bool:
    try:
        data = json.loads(setup_state_path().read_text(encoding="utf-8"))
        return int(data.get("version", 0)) >= SETUP_VERSION
    except Exception:
        return False


def mark_setup_complete() -> None:
    setup_state_path().write_text(json.dumps({"version": SETUP_VERSION}), encoding="utf-8")


def reset_setup() -> None:
    try:
        setup_state_path().unlink(missing_ok=True)
    except OSError:
        pass


def hidhide_status() -> dict[str, object]:
    """Return non-destructive HidHide/app-registration status."""
    result: dict[str, object] = {
        "installed": False,
        "registered": False,
        "cloaking": None,
        "cli": None,
        "message": "HidHide not installed",
    }
    if sys.platform != "win32":
        result["message"] = "HidHide is Windows-only"
        return result
    try:
        from hidhide_integration import find_hidhide_cli
        cli = find_hidhide_cli()
    except Exception as exc:
        result["message"] = f"HidHide check failed: {exc}"
        return result
    if cli is None:
        return result
    result["installed"] = True
    result["cli"] = str(cli)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        listed = subprocess.run([str(cli), "--app-list"], capture_output=True, text=True,
                                timeout=5, check=False, creationflags=flags)
        if getattr(sys, "frozen", False):
            exe = os.path.normcase(str(Path(sys.executable).resolve()))
            result["registered"] = listed.returncode == 0 and any(
                exe in os.path.normcase(line) for line in listed.stdout.splitlines()
            )
        else:
            result["registered"] = False
        cloak = subprocess.run([str(cli), "--cloak-state"], capture_output=True, text=True,
                               timeout=5, check=False, creationflags=flags)
        if cloak.returncode == 0:
            text = (cloak.stdout + " " + cloak.stderr).strip().lower()
            result["cloaking"] = any(x in text for x in ("true", "enabled", "on"))
        result["message"] = "HidHide detected"
    except Exception as exc:
        result["message"] = f"HidHide detected; status unavailable: {exc}"
    return result


class SafeController:
    """Wrap ControllerManager with guaranteed cleanup and health monitoring."""
    def __init__(self, manager):
        self.manager = manager
        self._closing = False
        self._monitor = None
        atexit.register(self.disconnect)

    @property
    def kind(self):
        return self.manager.kind

    @property
    def error(self):
        return self.manager.error

    @property
    def proxy(self):
        return self.manager.proxy

    def connect_auto(self):
        ok = self.manager.connect_auto()
        if ok:
            self._closing = False
            if not self._monitor or not self._monitor.is_alive():
                self._monitor = threading.Thread(target=self._watch, daemon=True, name="controller-failsafe")
                self._monitor.start()
        return ok

    def flick(self,delay_ms=0):
        try:
            self.manager.flick(delay_ms)
        except Exception:
            self.disconnect()

    def disconnect(self):
        self._closing = True
        try:
            self.manager.disconnect()
        except Exception:
            pass

    def _watch(self):
        while not self._closing:
            proxy = self.manager.proxy
            if proxy is None:
                return
            # A proxy thread that stops unexpectedly must release/reset the virtual pad.
            if hasattr(proxy, "running") and not proxy.running:
                try:
                    proxy.cleanup()
                except Exception:
                    pass
                self.manager.proxy = None
                self.manager.kind = "None"
                return
            time.sleep(0.25)


class OffsetFlick:
    """Apply a signed calibration offset to a flick callback.

    Positive values delay the controller action. Negative values are exposed to the
    vision layer through ``early_ms`` so detection can compensate before threshold.
    """
    def __init__(self, settings, callback):
        self.settings = settings
        self.callback = callback

    @property
    def early_ms(self) -> int:
        return max(0, -int(self.settings.get("timing_offset_ms", 0)))

    def __call__(self,delay_ms=0):
        offset = int(self.settings.get("timing_offset_ms", 0))
        self.callback(delay_ms=max(0,int(delay_ms))+max(0,min(offset,100)))

"""Reversible Windows scheduling and QoS tweaks used by Game Connection Stabilizer."""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)

PROCESS_PRIORITY_CLASSES = {
    "normal": 0x00000020,
    "high": 0x00000080,
    "realtime": 0x00000100,
}

QOS_POLICY_NAME = "2KStabilizer-Chiaki"
QOS_DSCP = 46


def set_process_priority(level: str) -> str:
    """Apply and verify the selected Windows process priority class."""
    normalized=str(level).strip().lower().replace(" ","").replace("-","")
    if normalized=="real":normalized="realtime"
    if normalized not in PROCESS_PRIORITY_CLASSES:
        raise SystemTweaksError(f"Unknown process priority: {level}")
    if sys.platform!="win32":raise SystemTweaksError("Process priority selection requires Windows.")
    from ctypes import wintypes
    kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel32.GetCurrentProcess.argtypes=[];kernel32.GetCurrentProcess.restype=wintypes.HANDLE
    kernel32.SetPriorityClass.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel32.SetPriorityClass.restype=wintypes.BOOL
    kernel32.GetPriorityClass.argtypes=[wintypes.HANDLE];kernel32.GetPriorityClass.restype=wintypes.DWORD
    process=kernel32.GetCurrentProcess();requested=PROCESS_PRIORITY_CLASSES[normalized];previous=kernel32.GetPriorityClass(process)
    if not kernel32.SetPriorityClass(process,requested):raise SystemTweaksError(str(ctypes.WinError(ctypes.get_last_error())))
    actual=kernel32.GetPriorityClass(process)
    if actual!=requested:
        if previous:kernel32.SetPriorityClass(process,previous)
        raise SystemTweaksError(f"Windows applied priority class 0x{actual:X} instead of 0x{requested:X}")
    LOGGER.info("Process priority changed to %s",normalized)
    return normalized


def _powershell(script: str) -> str:
    if sys.platform != "win32":
        raise SystemTweaksError("Windows QoS requires Windows.")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=creationflags,
            check=False,
        )
    except Exception as exc:
        raise SystemTweaksError(f"Could not run Windows QoS command: {exc}") from exc
    if result.returncode != 0:
        detail=(result.stderr or result.stdout or "Windows rejected the QoS request.").strip()
        raise SystemTweaksError(detail)
    return (result.stdout or "").strip()


def configure_chiaki_qos(executable: str, dscp: int = QOS_DSCP) -> str:
    """Create an active Windows Policy-based QoS rule for the selected Chiaki executable.

    The rule marks Chiaki traffic with DSCP EF (46). Windows/network equipment may
    use that marking for preferential queueing, but routers that ignore DSCP will
    not provide an upstream priority benefit. ActiveStore keeps the change
    temporary/reversible rather than installing a permanent machine policy.
    """
    path=Path(str(executable).strip().strip('"')).expanduser()
    if not path.is_file():
        raise SystemTweaksError("Select a valid Chiaki NG executable before enabling QoS.")
    if not 0 <= int(dscp) <= 63:
        raise SystemTweaksError("DSCP must be between 0 and 63.")
    safe_path=str(path.resolve()).replace("'","''")
    safe_name=QOS_POLICY_NAME.replace("'","''")
    script=(
        f"$n='{safe_name}'; $p='{safe_path}'; "
        "Get-NetQosPolicy -PolicyStore ActiveStore -Name $n -ErrorAction SilentlyContinue | "
        "Remove-NetQosPolicy -PolicyStore ActiveStore -Confirm:$false -ErrorAction SilentlyContinue; "
        f"New-NetQosPolicy -PolicyStore ActiveStore -Name $n -AppPathNameMatchCondition $p -DSCPAction {int(dscp)} -NetworkProfile All -ErrorAction Stop | Out-Null; "
        "$q=Get-NetQosPolicy -PolicyStore ActiveStore -Name $n -ErrorAction Stop; "
        "Write-Output ($q.Name + '|' + $q.AppPathNameMatchCondition + '|' + $q.DSCPAction)"
    )
    output=_powershell(script)
    LOGGER.info("Chiaki QoS enabled for %s with DSCP %d",path,dscp)
    return output or f"{QOS_POLICY_NAME}|{path}|{dscp}"


def remove_chiaki_qos() -> None:
    """Remove the temporary Chiaki QoS policy if it exists."""
    if sys.platform != "win32":
        return
    safe_name=QOS_POLICY_NAME.replace("'","''")
    script=(
        f"$n='{safe_name}'; "
        "Get-NetQosPolicy -PolicyStore ActiveStore -Name $n -ErrorAction SilentlyContinue | "
        "Remove-NetQosPolicy -PolicyStore ActiveStore -Confirm:$false -ErrorAction SilentlyContinue"
    )
    _powershell(script)
    LOGGER.info("Chiaki QoS disabled")


def chiaki_qos_status() -> dict[str, str | int | bool]:
    """Return the active Chiaki QoS policy state without changing it."""
    if sys.platform != "win32":
        return {"enabled":False,"message":"Windows only","path":"","dscp":QOS_DSCP}
    safe_name=QOS_POLICY_NAME.replace("'","''")
    script=(
        f"$q=Get-NetQosPolicy -PolicyStore ActiveStore -Name '{safe_name}' -ErrorAction SilentlyContinue; "
        "if($null -eq $q){Write-Output 'OFF'}else{Write-Output ('ON|' + $q.AppPathNameMatchCondition + '|' + $q.DSCPAction)}"
    )
    try:out=_powershell(script)
    except Exception as exc:return {"enabled":False,"message":str(exc),"path":"","dscp":QOS_DSCP}
    if out.startswith("ON|"):
        parts=out.split("|",2)
        try:dscp=int(parts[2])
        except Exception:dscp=QOS_DSCP
        return {"enabled":True,"message":"Active","path":parts[1] if len(parts)>1 else "","dscp":dscp}
    return {"enabled":False,"message":"Off","path":"","dscp":QOS_DSCP}


class SystemTweaksError(RuntimeError):
    """Raised when Windows performance settings cannot be changed safely."""


class SystemTweaks:
    HIGH_PRIORITY_CLASS = 0x00000080
    THREAD_SET_INFORMATION = 0x0020
    THREAD_PRIORITY_HIGHEST = 2
    THREAD_PRIORITY_NORMAL = 0

    def __init__(self, *, kernel32: Any | None = None, winmm: Any | None = None) -> None:
        self._enabled = False
        self._timer_enabled = False
        self._previous_priority: int | None = None
        self._boosted_threads: list[threading.Thread] = []
        self._kernel32 = kernel32
        self._winmm = winmm

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self, threads: tuple[threading.Thread, ...] = ()) -> None:
        if self._enabled:
            self.boost_threads(threads)
            return
        if sys.platform != "win32":
            raise SystemTweaksError("System performance tweaks require Windows.")

        kernel32, winmm = self._get_windows_apis()
        process = kernel32.GetCurrentProcess()
        previous_priority = kernel32.GetPriorityClass(process)
        if not previous_priority:
            raise SystemTweaksError(self._last_windows_error())

        try:
            timer_result = winmm.timeBeginPeriod(1)
            if timer_result != 0:
                raise SystemTweaksError(
                    f"Windows rejected the 1 ms timer request (code {timer_result})."
                )
            self._timer_enabled = True

            if not kernel32.SetPriorityClass(process, self.HIGH_PRIORITY_CLASS):
                raise SystemTweaksError(self._last_windows_error())

            self._previous_priority = previous_priority
            self._enabled = True
            self.boost_threads(threads)
            LOGGER.info("System performance tweaks enabled")
        except Exception:
            if self._timer_enabled:
                winmm.timeEndPeriod(1)
                self._timer_enabled = False
            raise

    def boost_threads(self, threads: tuple[threading.Thread, ...]) -> None:
        if not self._enabled:
            return
        for thread in threads:
            if thread in self._boosted_threads or not thread.native_id:
                continue
            if self._set_thread_priority(thread, self.THREAD_PRIORITY_HIGHEST):
                self._boosted_threads.append(thread)

    def disable(self) -> None:
        if sys.platform != "win32":
            self._clear_state()
            return

        kernel32, winmm = self._get_windows_apis()
        for thread in self._boosted_threads:
            self._set_thread_priority(thread, self.THREAD_PRIORITY_NORMAL)

        if self._previous_priority is not None:
            process = kernel32.GetCurrentProcess()
            if not kernel32.SetPriorityClass(process, self._previous_priority):
                LOGGER.error("Unable to restore process priority: %s", ctypes.WinError())

        if self._timer_enabled:
            result = winmm.timeEndPeriod(1)
            if result != 0:
                LOGGER.error("Unable to restore timer period (code %s)", result)

        self._clear_state()
        LOGGER.info("System performance tweaks disabled")

    def _set_thread_priority(self, thread: threading.Thread, priority: int) -> bool:
        if not thread.native_id:
            return False
        kernel32, _winmm = self._get_windows_apis()
        handle = kernel32.OpenThread(self.THREAD_SET_INFORMATION, False, thread.native_id)
        if not handle:
            LOGGER.warning("Unable to open worker thread for priority update")
            return False
        try:
            if not kernel32.SetThreadPriority(handle, priority):
                LOGGER.warning("Unable to update worker thread priority")
                return False
            return True
        finally:
            kernel32.CloseHandle(handle)

    def _get_windows_apis(self) -> tuple[Any, Any]:
        if self._kernel32 is not None and self._winmm is not None:
            return self._kernel32, self._winmm

        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        winmm = ctypes.WinDLL("winmm", use_last_error=True)

        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]
        kernel32.GetPriorityClass.restype = wintypes.DWORD
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        kernel32.SetThreadPriority.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        winmm.timeBeginPeriod.argtypes = [wintypes.UINT]
        winmm.timeBeginPeriod.restype = wintypes.UINT
        winmm.timeEndPeriod.argtypes = [wintypes.UINT]
        winmm.timeEndPeriod.restype = wintypes.UINT

        self._kernel32 = kernel32
        self._winmm = winmm
        return kernel32, winmm

    @staticmethod
    def _last_windows_error() -> str:
        error_code = ctypes.get_last_error()
        return str(ctypes.WinError(error_code))

    def _clear_state(self) -> None:
        self._enabled = False
        self._timer_enabled = False
        self._previous_priority = None
        self._boosted_threads.clear()

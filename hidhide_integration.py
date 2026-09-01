"""Best-effort HidHide application registration for packaged Windows builds."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)


def _candidate_cli_paths() -> list[Path]:
    candidates: list[Path] = []

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        root = Path(program_files) / "Nefarius Software Solutions" / "HidHide"
        candidates.extend(
            [
                root / "HidHideCLI.exe",
                # Older HidHide packages placed the CLI in an x64 subfolder.
                root / "x64" / "HidHideCLI.exe",
            ]
        )

    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if program_files_x86:
        root = Path(program_files_x86) / "Nefarius Software Solutions" / "HidHide"
        candidates.extend([root / "HidHideCLI.exe", root / "x64" / "HidHideCLI.exe"])

    on_path = shutil.which("HidHideCLI.exe") or shutil.which("HidHideCLI")
    if on_path:
        candidates.append(Path(on_path))

    # Preserve order while removing duplicates.
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(str(candidate)))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def find_hidhide_cli() -> Path | None:
    """Return the installed HidHide CLI path when available."""
    for candidate in _candidate_cli_paths():
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def register_current_executable() -> tuple[bool, str]:
    """Add this packaged executable to HidHide's allowed applications.

    The source/development build deliberately does not register ``python.exe``;
    whitelisting the interpreter would grant every Python process access through
    the HidHide cloak. Registration is best-effort and never prevents startup.
    """
    if sys.platform != "win32":
        return False, "HidHide is only available on Windows"

    if not getattr(sys, "frozen", False):
        return False, "Skipped HidHide registration for source-mode Python"

    executable = Path(sys.executable).resolve()
    if executable.suffix.lower() != ".exe" or not executable.is_file():
        return False, "Current packaged executable path is invalid"

    cli = find_hidhide_cli()
    if cli is None:
        return False, "HidHideCLI.exe was not found"

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        # app-list lets us avoid unnecessary writes on every launch.
        listed = subprocess.run(
            [str(cli), "--app-list"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=creation_flags,
        )
        normalized_executable = os.path.normcase(str(executable))
        registered = False
        if listed.returncode == 0:
            for line in listed.stdout.splitlines():
                if normalized_executable in os.path.normcase(line):
                    registered = True
                    break

        if registered:
            return True, "Already registered with HidHide"

        result = subprocess.run(
            [str(cli), "--app-reg", str(executable)],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=creation_flags,
        )
        if result.returncode == 0:
            return True, "Registered application with HidHide"

        detail = (result.stderr or result.stdout or "unknown HidHide error").strip()
        return False, f"HidHide registration failed: {detail}"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"HidHide registration failed: {exc}"


def auto_register_current_executable() -> bool:
    """Register with HidHide and log the result without interrupting startup."""
    success, message = register_current_executable()
    if success:
        LOGGER.info(message)
    else:
        LOGGER.info(message)
    return success

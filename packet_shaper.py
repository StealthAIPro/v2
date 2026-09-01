"""Game Connection Stabilizer application entry point."""
from __future__ import annotations
import ctypes, importlib.util, logging, os, subprocess, sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from hidhide_integration import auto_register_current_executable
APP_NAME="GameConnectionStabilizer"; APP_VERSION="1.0.0"; PROJECT_ROOT=Path(__file__).resolve().parent; SRC=PROJECT_ROOT/"src"

def is_admin():
    if sys.platform!="win32": return False
    try:return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError,OSError):return False

def configure_logging():
    if is_admin():
        r=logging.getLogger();r.setLevel(logging.INFO);r.handlers.clear();r.addHandler(logging.NullHandler());return None
    try:
        d=Path(os.environ.get("LOCALAPPDATA",Path.home()))/APP_NAME/"logs";d.mkdir(parents=True,exist_ok=True);p=d/"packetshaper.log";h=RotatingFileHandler(p,maxBytes=1_000_000,backupCount=3,encoding="utf-8");h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"));r=logging.getLogger();r.setLevel(logging.INFO);r.handlers.clear();r.addHandler(h);return p
    except OSError:logging.basicConfig(level=logging.INFO);return None

def show_native_error(title,message):
    if sys.platform=="win32":ctypes.windll.user32.MessageBoxW(None,message,title,0x10)
    else:print(f"{title}: {message}",file=sys.stderr)

def ensure_admin():
    if sys.platform!="win32" or not getattr(sys,"frozen",False):return True
    try:
        if is_admin():return True
        result=ctypes.windll.shell32.ShellExecuteW(None,"runas",sys.executable,subprocess.list2cmdline(sys.argv[1:]),str(Path(sys.executable).resolve().parent),1)
        if result<=32:show_native_error("Administrator access required","2K Stabilizer needs administrator access. Allow the Windows permission prompt and start it again.")
        return False
    except (AttributeError,OSError) as exc:show_native_error("Elevation failed",f"Could not request administrator access:\n\n{exc}");return False

def dependency_available(package):return importlib.util.find_spec(package) is not None

def main():
    if not ensure_admin():return 0
    log_path=configure_logging();logging.info("Starting %s %s with Python %s",APP_NAME,APP_VERSION,sys.version);auto_register_current_executable()
    if not dependency_available("pydivert"):
        show_native_error("Missing dependency","A required traffic component is missing. Install requirements.txt and start 2K Stabilizer again.");return 1
    try:
        sys.path.insert(0,str(SRC))
        from runtime_safety import setup_complete
        if not setup_complete():
            from setup_wizard import run_first_setup
            run_first_setup()
        from ui import App
        from ui_features import install_features
        install_features(App)
        app=App(log_path=log_path);app.mainloop();return 0
    except Exception as exc:
        logging.exception("Unhandled application error");hint=f"\n\nLog: {log_path}" if log_path else "";show_native_error("2K Stabilizer stopped",f"An unexpected error stopped 2K Stabilizer:\n\n{exc}{hint}");return 1
if __name__=="__main__":
    exit_code=main()
    # Cleanup is performed by App.on_close before main() returns. A frozen app
    # must not remain invisible because a third-party native reader owns a
    # lingering Python thread; terminate the PyInstaller child deterministically.
    if getattr(sys,"frozen",False):os._exit(exit_code)
    raise SystemExit(exit_code)

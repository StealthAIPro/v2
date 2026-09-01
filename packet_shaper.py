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

def choose_game():
    """Show a small startup picker before game-specific modules are imported.

    2K27 intentionally routes to the 2K26 module folder for now. Once a
    src/2k27 implementation exists, only the mapping below needs to change.
    """
    try:
        import tkinter as tk
    except Exception:
        return "2k26"
    selected={"game":None}
    root=tk.Tk();root.title("2K Stabilizer");root.geometry("430x245");root.resizable(False,False);root.configure(bg="#0a0e27")
    try:root.eval("tk::PlaceWindow . center")
    except Exception:pass
    tk.Label(root,text="SELECT GAME",bg="#0a0e27",fg="#94a3b8",font=("Segoe UI",9,"bold")).pack(anchor="w",padx=24,pady=(22,4))
    tk.Label(root,text="Which game are you launching?",bg="#0a0e27",fg="#e2e8f0",font=("Segoe UI",16,"bold")).pack(anchor="w",padx=24,pady=(0,16))
    buttons=tk.Frame(root,bg="#0a0e27");buttons.pack(fill="x",padx=24)
    def pick(game):selected["game"]=game;root.destroy()
    for game in ("2K26","2K27"):
        tk.Button(buttons,text=game,command=lambda g=game.lower():pick(g),bd=0,relief="flat",bg="#2563eb",fg="white",activebackground="#1d4ed8",activeforeground="white",font=("Segoe UI",11,"bold"),cursor="hand2",padx=20,pady=14).pack(side="left",expand=True,fill="x",padx=(0,8) if game=="2K26" else (8,0))
    tk.Label(root,text="2K27 currently uses the 2K26 module until the 2K27 version is added.",bg="#0a0e27",fg="#64748b",font=("Segoe UI",8),wraplength=375,justify="left").pack(anchor="w",padx=24,pady=(16,0))
    root.protocol("WM_DELETE_WINDOW",root.destroy);root.mainloop();return selected["game"]

def main():
    if not ensure_admin():return 0
    log_path=configure_logging();logging.info("Starting %s %s with Python %s",APP_NAME,APP_VERSION,sys.version);auto_register_current_executable()
    game=choose_game()
    if not game:return 0
    game_folder={"2k26":"2k26","2k27":"2k26"}.get(game,"2k26")

    # Source runs use src/<game>. PyInstaller one-file builds bundle these
    # modules into the executable/PYZ, so no literal src/2k26 directory exists
    # under the temporary _MEI extraction directory. Hidden imports make the
    # modules directly importable in frozen mode.
    if not getattr(sys,"frozen",False):
        game_src=SRC/game_folder
        if not game_src.exists():
            show_native_error("Missing game files",f"Could not find the selected game module:\n\n{game_src}");return 1
        sys.path.insert(0,str(game_src))
    else:
        bundle_root=Path(getattr(sys,"_MEIPASS",PROJECT_ROOT))
        if str(bundle_root) not in sys.path:
            sys.path.insert(0,str(bundle_root))

    if not dependency_available("pydivert"):
        show_native_error("Missing dependency","A required traffic component is missing. Install requirements.txt and start 2K Stabilizer again.");return 1
    try:
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
    if getattr(sys,"frozen",False):os._exit(exit_code)
    raise SystemExit(exit_code)

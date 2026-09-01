"""First-run setup wizard for 2K Stabilizer."""
from __future__ import annotations

import importlib.util
import tkinter as tk

from pluto_core import ControllerManager, default_settings, make_source
from runtime_safety import mark_setup_complete

BG="#0a0e27"; CARD="#0f172a"; TEXT="#e2e8f0"; SUB="#94a3b8"; BLUE="#2563eb"; GREEN="#10b981"; RED="#ef4444"


def run_first_setup() -> bool:
    root=tk.Tk(); root.title("2K Stabilizer Setup"); root.geometry("520x440"); root.resizable(False,False); root.configure(bg=BG)
    settings=default_settings(); controller=ControllerManager(settings); done={"ok":False}
    title=tk.Label(root,text="First-time setup",bg=BG,fg=TEXT,font=("Segoe UI",20,"bold")); title.pack(anchor="w",padx=24,pady=(24,4))
    tk.Label(root,text="Check the pieces needed for Vision + controller passthrough.",bg=BG,fg=SUB,font=("Segoe UI",9)).pack(anchor="w",padx=24,pady=(0,16))
    box=tk.Frame(root,bg=CARD); box.pack(fill="both",expand=True,padx=24,pady=(0,16))
    labels={}
    for name in ("Dependencies","Controller","Camera"):
        row=tk.Frame(box,bg=CARD); row.pack(fill="x",padx=16,pady=10)
        tk.Label(row,text=name,bg=CARD,fg=TEXT,font=("Segoe UI",10,"bold")).pack(side="left")
        labels[name]=tk.Label(row,text="Not checked",bg=CARD,fg=SUB,font=("Segoe UI",9)); labels[name].pack(side="right")
    status=tk.Label(root,text="Run checks, then finish setup.",bg=BG,fg=SUB,font=("Segoe UI",9)); status.pack(anchor="w",padx=24)
    buttons=tk.Frame(root,bg=BG); buttons.pack(fill="x",padx=24,pady=18)

    def checks():
        required=("cv2","numpy","vgamepad","pydualsense")
        missing=[x for x in required if importlib.util.find_spec(x) is None]
        labels["Dependencies"].configure(text="Ready" if not missing else "Missing: "+", ".join(missing),fg=GREEN if not missing else RED)
        if controller.connect_auto():
            labels["Controller"].configure(text="Ready · "+controller.kind,fg=GREEN); controller.disconnect()
        else: labels["Controller"].configure(text="Not detected",fg=SUB)
        cap=make_source(settings); opened=getattr(cap,"status","idle")!="idle" or cap.open()
        labels["Camera"].configure(text=getattr(cap,"status","Ready") if opened else "Unavailable",fg=GREEN if opened else RED)
        try: cap.release()
        except Exception: pass
        status.configure(text="Checks complete. You can change these later in the main app.")

    def finish():
        mark_setup_complete(); done["ok"]=True; root.destroy()

    tk.Button(buttons,text="Run checks",command=checks,bg="#273451",fg="white",bd=0,padx=16,pady=8,font=("Segoe UI",9,"bold")).pack(side="left")
    tk.Button(buttons,text="Finish setup",command=finish,bg=BLUE,fg="white",bd=0,padx=16,pady=8,font=("Segoe UI",9,"bold")).pack(side="right")
    root.protocol("WM_DELETE_WINDOW",root.destroy); root.mainloop()
    try: controller.disconnect()
    except Exception: pass
    return done["ok"]

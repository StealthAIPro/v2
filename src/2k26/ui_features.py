"""Optional UI/runtime enhancements kept separate from the main aesthetic module."""
from __future__ import annotations

import json
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import pluto_core
from runtime_safety import OffsetFlick, SafeController, app_data_dir
from system_tweaks import configure_chiaki_qos, remove_chiaki_qos, chiaki_qos_status
from widgets import Card, Section, DelaySlider, ToggleSwitch

CARD="#0f172a"; TEXT="#e2e8f0"; SUB="#94a3b8"; MUTED="#64748b"; BLUE="#2563eb"
_INSTALLED=False


def _content_frame(parent):
    """Find the existing scroll-page content frame created by App._scroll_page."""
    for body in parent.winfo_children():
        for child in body.winfo_children():
            if isinstance(child, tk.Canvas):
                for item in child.find_all():
                    name=child.itemcget(item,"window")
                    if name:
                        try:return child.nametowidget(name)
                        except Exception:pass
    return None


def _launcher_settings_path():
    return app_data_dir()/"launcher.json"


def _load_launcher_settings():
    try:
        p=_launcher_settings_path()
        if p.exists():
            data=json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data,dict) else {}
    except Exception:
        pass
    return {}


def _save_launcher_settings(data):
    try:
        p=_launcher_settings_path();p.parent.mkdir(parents=True,exist_ok=True)
        current=_load_launcher_settings();current.update(data)
        p.write_text(json.dumps(current,indent=2),encoding="utf-8")
        return True
    except Exception:
        return False


def install_features(App):
    global _INSTALLED
    if _INSTALLED:return
    _INSTALLED=True

    original_process=pluto_core.CVWorker.process
    def offset_process(worker,frame,captured_at=None):
        original_target=float(worker.s.get("target_height",52)); offset=int(worker.s.get("timing_offset_ms",0))
        if offset<0:
            velocity=float(getattr(worker,"velocity",0.0))
            worker.s["target_height"]=max(1.0,original_target-velocity*(abs(offset)/1000.0))
        try:out=original_process(worker,frame,captured_at)
        finally:worker.s["target_height"]=original_target
        try:
            parts=worker.state.split(":")
            parts[2]=f"{original_target:.1f}";worker.state=":".join(parts)
        except Exception:pass
        return out
    pluto_core.CVWorker.process=offset_process

    original_poll=App._poll
    def enhanced_poll(self):
        preview_enabled=bool(getattr(self,"_preview_enabled",True))
        original_tab=getattr(self,"_active_tab",None)
        if not preview_enabled and original_tab=="Vision":
            self._active_tab="VisionPreviewDisabled"
        try:
            return original_poll(self)
        finally:
            if original_tab is not None:self._active_tab=original_tab
    App._poll=enhanced_poll

    original_close=App.on_close
    def enhanced_close(self):
        if getattr(self,"_qos_enabled",False):
            try:remove_chiaki_qos()
            except Exception:pass
            self._qos_enabled=False
        return original_close(self)
    App.on_close=enhanced_close

    original_init=App.__init__
    def enhanced_init(self,*args,**kwargs):
        self._preview_enabled=True;self._qos_enabled=False
        original_init(self,*args,**kwargs)
        self._settings.setdefault("timing_offset_ms",0)
        old=self._controller; self._controller=SafeController(old)
        offset_flick=OffsetFlick(self._settings,self._controller.flick); self._vision.flick=offset_flick
        if self._vision.worker:self._vision.worker.set_flick_callback(offset_flick)
        p=_content_frame(self._tab_frames["Controller"])
        if p is not None:_append_controller_features(self,p)
        vp=_content_frame(self._tab_frames["Vision"])
        if vp is not None:_append_vision_features(self,vp)
        np=_content_frame(self._tab_frames["Network"])
        if np is not None:_append_network_features(self,np)
    App.__init__=enhanced_init


def _append_controller_features(app,p):
    Section(p,"Timing Calibration").pack(fill="x")
    c=Card(p);c.pack(fill="x",pady=(4,12))
    tk.Label(c,text="Shot timing offset",bg=CARD,fg=TEXT,font=("Segoe UI",9,"bold")).pack(anchor="w",padx=12,pady=(10,0))
    app._timing_value=tk.Label(c,text="0 ms",bg=CARD,fg=SUB,font=("Segoe UI",9));app._timing_value.pack(anchor="e",padx=12)
    def timing(v):
        offset=int(v)-50;app._settings["timing_offset_ms"]=offset;app._timing_value.configure(text=f"{offset:+d} ms")
    app._timing_slider=DelaySlider(c,min_val=0,max_val=100,value=50,on_change=timing);app._timing_slider.pack(fill="x",padx=8,pady=(0,5))
    tk.Label(c,text="Negative = earlier release · Positive = later release. Vision learns meter speed for early offsets.",bg=CARD,fg=SUB,font=("Segoe UI",8),wraplength=480,justify="left").pack(anchor="w",padx=12,pady=(0,10))


def _append_vision_features(app,p):
    Section(p,"Preview Display").pack(fill="x")
    c=Card(p);c.pack(fill="x",pady=(4,12))
    row=tk.Frame(c,bg=CARD);row.pack(fill="x",padx=12,pady=12)
    tk.Label(row,text="OpenCV Preview",bg=CARD,fg=TEXT,font=("Segoe UI",9,"bold")).pack(side="left")

    def preview_changed(state):
        app._preview_enabled=bool(state)
        if not state:
            app._preview_image=None
            try:app._preview.configure(image="",text="Preview off · detection still running")
            except Exception:pass
        else:
            try:app._preview.configure(text="Preview enabled")
            except Exception:pass

    app._preview_toggle=ToggleSwitch(row,state=True,on_toggle=preview_changed);app._preview_toggle.pack(side="right")
    tk.Label(c,text="Turn this off after calibration to reduce preview rendering overhead. OpenCV shot detection keeps running.",bg=CARD,fg=SUB,font=("Segoe UI",8),wraplength=300,justify="left").pack(anchor="w",padx=12,pady=(0,10))

    Section(p,"Chiaki NG").pack(fill="x")
    c=Card(p);c.pack(fill="x",pady=(4,12))
    saved=_load_launcher_settings();app._chiaki_path_var=tk.StringVar(value=str(saved.get("chiaki_path","")))
    tk.Label(c,text="Chiaki NG executable",bg=CARD,fg=TEXT,font=("Segoe UI",9,"bold")).pack(anchor="w",padx=12,pady=(10,5))
    entry=tk.Entry(c,textvariable=app._chiaki_path_var,bg="#111936",fg=TEXT,insertbackground="white",relief="flat",bd=0,font=("Segoe UI",8));entry.pack(fill="x",padx=12,pady=(0,8),ipady=5)
    app._chiaki_status=tk.Label(c,text="Path saved locally" if app._chiaki_path_var.get() else "Select Chiaki NG once; the path will be remembered.",bg=CARD,fg=SUB,font=("Segoe UI",8),wraplength=300,justify="left");app._chiaki_status.pack(anchor="w",padx=12,pady=(0,8))
    buttons=tk.Frame(c,bg=CARD);buttons.pack(fill="x",padx=12,pady=(0,12))

    def save_path(path):
        app._chiaki_path_var.set(path)
        ok=_save_launcher_settings({"chiaki_path":path})
        app._chiaki_status.configure(text="Chiaki NG path saved." if ok else "Could not save Chiaki NG path.",fg="#10b981" if ok else "#ef4444")

    def browse():
        path=filedialog.askopenfilename(parent=app,title="Select Chiaki NG",filetypes=[("Applications","*.exe"),("All files","*.*")])
        if path:save_path(path)

    def launch():
        path=app._chiaki_path_var.get().strip().strip('"')
        if not path:
            browse();path=app._chiaki_path_var.get().strip().strip('"')
        exe=Path(path)
        if not path or not exe.is_file():
            app._chiaki_status.configure(text="Select a valid Chiaki NG .exe first.",fg="#ef4444");return
        save_path(str(exe))
        try:
            subprocess.Popen([str(exe)],cwd=str(exe.parent))
            app._chiaki_status.configure(text="Chiaki NG launched.",fg="#10b981")
        except Exception as exc:
            app._chiaki_status.configure(text=f"Launch failed: {exc}",fg="#ef4444")

    tk.Button(buttons,text="Select Path",command=browse,bd=0,bg="#273451",fg="white",activebackground="#334155",activeforeground="white",font=("Segoe UI",9,"bold"),cursor="hand2",padx=12,pady=7).pack(side="left")
    tk.Button(buttons,text="Launch Chiaki NG",command=launch,bd=0,bg=BLUE,fg="white",activebackground="#1d4ed8",activeforeground="white",font=("Segoe UI",9,"bold"),cursor="hand2",padx=12,pady=7).pack(side="left",padx=(8,0))


def _append_network_features(app,p):
    Section(p,"Chiaki Traffic Priority").pack(fill="x")
    c=Card(p);c.pack(fill="x",pady=(4,12))
    row=tk.Frame(c,bg=CARD);row.pack(fill="x",padx=12,pady=(12,6))
    tk.Label(row,text="Windows QoS / DSCP Priority",bg=CARD,fg=TEXT,font=("Segoe UI",9,"bold")).pack(side="left")
    status=chiaki_qos_status();app._qos_enabled=bool(status.get("enabled",False))
    app._qos_status=tk.Label(c,text="Active · DSCP 46 (EF)" if app._qos_enabled else "Off · select Chiaki NG path first",bg=CARD,fg="#10b981" if app._qos_enabled else SUB,font=("Segoe UI",8),wraplength=760,justify="left");app._qos_status.pack(anchor="w",padx=12,pady=(0,5))

    def qos_changed(state):
        if state:
            saved=_load_launcher_settings();path=str(saved.get("chiaki_path","")).strip()
            if not path or not Path(path).is_file():
                app._qos_enabled=False;app._qos_toggle.set_state(False)
                app._qos_status.configure(text="Select and save a valid Chiaki NG path in the Vision tab first.",fg="#ef4444");return
            try:
                configure_chiaki_qos(path);app._qos_enabled=True
                app._qos_status.configure(text="Active · Chiaki traffic marked DSCP 46 (EF). Router support determines upstream priority.",fg="#10b981")
            except Exception as exc:
                app._qos_enabled=False;app._qos_toggle.set_state(False)
                app._qos_status.configure(text=f"QoS failed: {exc}",fg="#ef4444")
        else:
            try:remove_chiaki_qos();app._qos_enabled=False;app._qos_status.configure(text="Off",fg=SUB)
            except Exception as exc:app._qos_status.configure(text=f"Could not remove QoS policy: {exc}",fg="#ef4444")

    app._qos_toggle=ToggleSwitch(row,state=app._qos_enabled,on_toggle=qos_changed);app._qos_toggle.pack(side="right")
    tk.Label(c,text="Prioritizes Chiaki at the Windows QoS layer by marking its traffic as Expedited Forwarding (DSCP 46). This can help when your router/network honors DSCP; it does not create bandwidth or reduce ISP latency by itself.",bg=CARD,fg=SUB,font=("Segoe UI",8),wraplength=760,justify="left").pack(anchor="w",padx=12,pady=(0,12))

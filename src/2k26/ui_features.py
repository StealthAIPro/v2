"""Optional UI/runtime enhancements kept separate from the main aesthetic module."""
from __future__ import annotations

import tkinter as tk

import pluto_core
from runtime_safety import OffsetFlick, SafeController
from widgets import Card, Section, DelaySlider

CARD="#0f172a"; TEXT="#e2e8f0"; SUB="#94a3b8"
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


def install_features(App):
    global _INSTALLED
    if _INSTALLED:return
    _INSTALLED=True

    # Signed CV timing calibration. Positive offset delays the final controller
    # action. Negative offset advances the visual threshold using the measured
    # meter growth rate, so -8 ms can actually fire before the original target.
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
            # Keep displayed target truthful even when the internal early threshold changed.
            parts[2]=f"{original_target:.1f}";worker.state=":".join(parts)
        except Exception:pass
        return out
    pluto_core.CVWorker.process=offset_process

    original_init=App.__init__
    def enhanced_init(self,*args,**kwargs):
        original_init(self,*args,**kwargs)
        self._settings.setdefault("timing_offset_ms",0)
        old=self._controller; self._controller=SafeController(old)
        offset_flick=OffsetFlick(self._settings,self._controller.flick); self._vision.flick=offset_flick
        if self._vision.worker:self._vision.worker.set_flick_callback(offset_flick)
        p=_content_frame(self._tab_frames["Controller"])
        if p is not None:_append_controller_features(self,p)
    App.__init__=enhanced_init


def _append_controller_features(app,p):
    Section(p,"Timing Calibration").pack(fill="x")
    c=Card(p);c.pack(fill="x",pady=(4,12))
    tk.Label(c,text="Shot timing offset",bg=CARD,fg=TEXT,font=("Segoe UI",9,"bold")).pack(anchor="w",padx=12,pady=(10,0))
    app._timing_value=tk.Label(c,text="0 ms",bg=CARD,fg=SUB,font=("Segoe UI",9));app._timing_value.pack(anchor="e",padx=12)
    # DelaySlider is 0-based, so map 0..100 to -50..+50 ms.
    def timing(v):
        offset=int(v)-50;app._settings["timing_offset_ms"]=offset;app._timing_value.configure(text=f"{offset:+d} ms")
    app._timing_slider=DelaySlider(c,min_val=0,max_val=100,value=50,on_change=timing);app._timing_slider.pack(fill="x",padx=8,pady=(0,5))
    tk.Label(c,text="Negative = earlier release · Positive = later release. Vision learns meter speed for early offsets.",bg=CARD,fg=SUB,font=("Segoe UI",8),wraplength=480,justify="left").pack(anchor="w",padx=12,pady=(0,10))

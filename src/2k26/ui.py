"""2kStabilizer UI with Pluto-style Vision, Controller, and Network tabs."""
from __future__ import annotations
import ctypes, logging, sys, tkinter as tk
from pathlib import Path
from packet_capture import PacketCapture
from overlay import VisionOverlay
from pluto_core import ControllerManager, VisionAssist, default_settings
from system_tweaks import SystemTweaks, SystemTweaksError, set_process_priority
from widgets import ToggleSwitch, DelaySlider, SpreadGraph, StatDisplay, Section, Card, StatusIndicator, VerticalScrollbar
try:
    from PIL import Image, ImageTk
except Exception: Image=ImageTk=None
BG='#0a0e27'; CARD='#0f172a'; TEXT='#e2e8f0'; MUTED='#64748b'; SUB='#94a3b8'; BLUE='#2563eb'
class App(tk.Tk):
    def __init__(self,log_path:Path|None=None):
        super().__init__(); self.withdraw(); self.title('2K Stabilizer'); self.geometry('1040x700'); self.minsize(920,620); self.resizable(True,True); self.overrideredirect(True); self.configure(bg=BG); self.option_add('*Font','{Segoe UI} 10'); self._titlebar_drag_origin=None; self._closing=False; self._poll_id=None; self._preview_image=None; self._active_tab='Vision'; self._overlay=None; self._log_path=log_path; self._engine=None; self._running=False; self._system_tweaks=SystemTweaks(); self._settings=default_settings(); self._controller=ControllerManager(self._settings); self._vision=VisionAssist(self._settings,self._controller.flick); self._tab_frames={}; self._tab_buttons={}; self._build(); self.protocol('WM_DELETE_WINDOW',self.on_close); self._poll(); self.update_idletasks(); self._apply_taskbar_style(); self.deiconify(); self._overlay=VisionOverlay(self,self._settings,self._vision)
    def _build(self):
        self._build_titlebar(); self._build_tabs()
        for n in ('Vision','Controller','Network'): self._tab_frames[n]=tk.Frame(self,bg=BG)
        self._build_vision(self._tab_frames['Vision']); self._build_controller(self._tab_frames['Controller']); self._build_network(self._tab_frames['Network']); self._show_tab('Vision')
    def _build_titlebar(self):
        bar=tk.Frame(self,height=34,bg=BG); bar.pack(fill='x'); bar.pack_propagate(False); title=tk.Label(bar,text='2K Stabilizer',bg=BG,fg='#cbd5e1',font=('Segoe UI',9,'bold')); title.pack(side='left',padx=12)
        for t,c,h in [('×',self.on_close,'#ef4444'),('−',self._minimize,'#17213d')]: b=tk.Button(bar,text=t,command=c,bd=0,relief='flat',bg=BG,fg='#cbd5e1',activebackground=h,activeforeground='white',font=('Segoe UI',14),cursor='hand2'); b.pack(side='right',fill='y',ipadx=9)
        for w in (bar,title): w.bind('<ButtonPress-1>',self._begin_drag); w.bind('<B1-Motion>',self._drag)
    def _build_tabs(self):
        nav=tk.Frame(self,bg=BG); nav.pack(fill='x',padx=16,pady=(4,10))
        for n in ('Vision','Controller','Network'): b=tk.Button(nav,text=n,command=lambda x=n:self._show_tab(x),bd=0,relief='flat',bg='#111936',fg=SUB,activebackground='#17213d',activeforeground='white',font=('Segoe UI',9,'bold'),cursor='hand2',padx=22,pady=8); b.pack(side='left',padx=(0,6)); self._tab_buttons[n]=b
    def _show_tab(self,n):
        self._active_tab=n
        for f in self._tab_frames.values(): f.pack_forget()
        self._tab_frames[n].pack(fill='both',expand=True)
        for x,b in self._tab_buttons.items(): b.configure(bg=BLUE if x==n else '#111936',fg='white' if x==n else SUB)
    def _scroll_page(self,parent):
        body=tk.Frame(parent,bg=BG); body.pack(fill='both',expand=True); canvas=tk.Canvas(body,bg=BG,highlightthickness=0); scroll=VerticalScrollbar(body,command=canvas.yview_moveto); scroll.pack(side='right',fill='y'); canvas.pack(side='left',fill='both',expand=True); canvas.configure(yscrollcommand=scroll.set); main=tk.Frame(canvas,bg=BG,padx=16,pady=4); wid=canvas.create_window(0,0,window=main,anchor='nw'); main.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all'))); canvas.bind('<Configure>',lambda e:canvas.itemconfigure(wid,width=e.width))
        def wheel(e):
            widget=e.widget
            while widget is not None:
                if widget is body:canvas.yview_scroll((-1 if e.delta>0 else 1)*3,'units');return 'break'
                widget=getattr(widget,'master',None)
        self.bind_all('<MouseWheel>',wheel,add='+');return main
    def _label(self,p,t,fg=SUB,size=9,**kw): return tk.Label(p,text=t,bg=CARD,fg=fg,font=('Segoe UI',size),**kw)
    def _entry(self,p,v,width=12): return tk.Entry(p,textvariable=v,width=width,bg='#111936',fg=TEXT,insertbackground='white',relief='flat',bd=0,font=('Segoe UI',9))
    def _option(self,p,v,vals,cmd=None,width=12): m=tk.OptionMenu(p,v,*vals,command=cmd); m.configure(bg='#111936',fg=TEXT,activebackground='#17213d',activeforeground='white',highlightthickness=0,bd=0,width=width); m['menu'].configure(bg='#111936',fg=TEXT,activebackground=BLUE); return m
    def _button(self,p,t,c,primary=False): return tk.Button(p,text=t,command=c,bd=0,bg=BLUE if primary else '#273451',fg='white',activebackground='#1d4ed8' if primary else '#334155',activeforeground='white',font=('Segoe UI',9,'bold'),cursor='hand2',padx=12,pady=7)
    def _build_vision(self,parent):
        ws=tk.Frame(parent,bg=BG); ws.pack(fill='both',expand=True,padx=16,pady=(0,14)); ws.grid_columnconfigure(0,minsize=350); ws.grid_columnconfigure(1,weight=1); ws.grid_rowconfigure(0,weight=1); left=tk.Frame(ws,bg=BG,width=350); left.grid(row=0,column=0,sticky='nsew',padx=(0,14)); left.grid_propagate(False); p=self._scroll_page(left)
        Section(p,'Vision Assist').pack(fill='x'); c=Card(p); c.pack(fill='x',pady=(4,12)); r=tk.Frame(c,bg=CARD); r.pack(fill='x',padx=12,pady=12); self._label(r,'OpenCV Shot Detection',TEXT,10).pack(side='left'); self._vision_toggle=ToggleSwitch(r,on_toggle=self._vision_toggle_changed); self._vision_toggle.pack(side='right'); self._vision_status=self._label(c,'Off',MUTED,8,anchor='w'); self._vision_status.pack(fill='x',padx=12,pady=(0,10))
        Section(p,'Camera Preview').pack(fill='x'); c=Card(p); c.pack(fill='x',pady=(4,12)); g=tk.Frame(c,bg=CARD); g.pack(fill='x',padx=12,pady=10); g.columnconfigure(1,weight=1); self._preview_mode_var=tk.StringVar(value='Balanced'); self._priority_var=tk.StringVar(value='Normal')
        self._label(g,'OpenCV preview').grid(row=0,column=0,sticky='w',pady=5); self._option(g,self._preview_mode_var,['Performance','Balanced','Quality'],lambda v:self._set('preview_mode',v.lower())).grid(row=0,column=1,sticky='e')
        self._label(g,'Performance: 270p/15 FPS · Balanced: 405p/30 FPS · Quality: 720p/60 FPS',MUTED,7,wraplength=300,justify='left').grid(row=1,column=0,columnspan=2,sticky='w',pady=(0,5))
        self._label(g,'App priority').grid(row=2,column=0,sticky='w',pady=5); self._option(g,self._priority_var,['Normal','High','Real Time'],self._priority_changed).grid(row=2,column=1,sticky='e')
        self._priority_status=self._label(g,'Normal is recommended with Chiaki. Real Time can reduce Windows/audio responsiveness.', '#f59e0b',7,wraplength=300,justify='left'); self._priority_status.grid(row=3,column=0,columnspan=2,sticky='w',pady=(0,5))
        Section(p,'Meter + ROI').pack(fill='x'); c=Card(p); c.pack(fill='x',pady=(4,12)); g=tk.Frame(c,bg=CARD); g.pack(fill='x',padx=12,pady=10); g.columnconfigure(1,weight=1); self._meter_var=tk.StringVar(value='Arrow2'); self._color_var=tk.StringVar(value='Purple'); self._target_var=tk.StringVar(value='52'); self._roi_w_var=tk.StringVar(value='1870'); self._roi_h_var=tk.StringVar(value='800')
        for i,(lab,var,vals,key) in enumerate([('Meter',self._meter_var,['Arrow2','Funnel','Pill','Straight','Tube'],'meter_type'),('Color',self._color_var,['Purple','Yellow','Red','Orange','Blue','White','Custom'],'color_name')]): self._label(g,lab).grid(row=i,column=0,sticky='w',pady=5); self._option(g,var,vals,lambda v,k=key:self._set(k,v)).grid(row=i,column=1,sticky='e')
        for i,(lab,var,key,d) in enumerate([('Target height',self._target_var,'target_height',52),('ROI width',self._roi_w_var,'roi_w',1870),('ROI height',self._roi_h_var,'roi_h',800)],2): self._label(g,lab).grid(row=i,column=0,sticky='w',pady=5); e=self._entry(g,var,8); e.grid(row=i,column=1,sticky='e'); e.bind('<FocusOut>',lambda _,v=var,k=key,x=d:self._set_int(k,v.get(),x))
        for text,key in [('Show ROI box','show_roi_box'),('Show detector HUD','show_hud')]: r=tk.Frame(c,bg=CARD); r.pack(fill='x',padx=12,pady=(0,9)); self._label(r,text,TEXT,9).pack(side='left'); t=ToggleSwitch(r,state=True,on_toggle=lambda s,k=key:self._set(k,s)); t.pack(side='right'); setattr(self,'_roi_toggle' if key=='show_roi_box' else '_hud_toggle',t)
        right=tk.Frame(ws,bg=BG); right.grid(row=0,column=1,sticky='nsew'); right.grid_columnconfigure(0,weight=1); right.grid_rowconfigure(1,weight=1); tk.Label(right,text='LIVE OPENCV PREVIEW',bg=BG,fg=SUB,font=('Segoe UI',9,'bold')).grid(row=0,column=0,sticky='w',pady=(4,7)); pc=tk.Frame(right,bg=CARD,highlightbackground='#1e293b',highlightthickness=1); pc.grid(row=1,column=0,sticky='nsew'); pc.grid_columnconfigure(0,weight=1); pc.grid_rowconfigure(0,weight=1); self._preview=tk.Label(pc,text='Enable Vision Assist to start preview',bg='#070b1c',fg=MUTED,font=('Segoe UI',10)); self._preview.grid(row=0,column=0,sticky='nsew',padx=10,pady=(10,5)); self._vision_state=self._label(pc,'No meter detected',MUTED,8,anchor='w'); self._vision_state.grid(row=1,column=0,sticky='ew',padx=12,pady=(3,10))
    def _build_controller(self,parent):
        p=self._scroll_page(parent); Section(p,'Controller Bridge').pack(fill='x'); c=Card(p); c.pack(fill='x',pady=6); r=tk.Frame(c,bg=CARD); r.pack(fill='x',padx=12,pady=12); self._label(r,'Controller Proxy',TEXT,10).pack(side='left'); self._controller_toggle=ToggleSwitch(r,on_toggle=self._controller_toggle_changed); self._controller_toggle.pack(side='right'); self._controller_status=self._label(c,'Disconnected',MUTED,8,anchor='w'); self._controller_status.pack(fill='x',padx=12,pady=(0,10)); Section(p,'Shot Control').pack(fill='x'); c=Card(p); c.pack(fill='x',pady=6); self._mode_var=tk.StringVar(value='Stick Rhythm'); g=tk.Frame(c,bg=CARD); g.pack(fill='x',padx=12,pady=10); self._label(g,'Shooting mode').pack(side='left'); self._option(g,self._mode_var,['Stick Rhythm','Button','Stick'],lambda v:self._set('shooting_mode',v),16).pack(side='right'); self._rhythm=DelaySlider(c,min_val=4,max_val=200,value=46,on_change=self._set_rhythm); self._rhythm.pack(fill='x',padx=8,pady=12)
    def _build_network(self,parent):
        p=self._scroll_page(parent); Section(p,'Network Stabilizer').pack(fill='x'); c=Card(p); c.pack(fill='x',pady=6); r=tk.Frame(c,bg=CARD); r.pack(fill='x',padx=12,pady=12); self._label(r,'Turn Stabilizer On',TEXT,10).pack(side='left'); self._net_toggle=ToggleSwitch(r,on_toggle=self._network_toggle_changed); self._net_toggle.pack(side='right'); self._net_dot=StatusIndicator(r); self._net_dot.pack(side='right',padx=12); self._net_status=self._label(c,'Off',MUTED,8,anchor='w'); self._net_status.pack(fill='x',padx=12,pady=(0,10)); Section(p,'Shot Network Hold').pack(fill='x'); c=Card(p); c.pack(fill='x',pady=6); r=tk.Frame(c,bg=CARD); r.pack(fill='x',padx=12,pady=12); self._label(r,'500 ms Shot Hold',TEXT,10).pack(side='left'); self._shot_toggle=ToggleSwitch(r,on_toggle=self._shot_changed); self._shot_toggle.pack(side='right'); Section(p,'Performance Mode').pack(fill='x'); c=Card(p); c.pack(fill='x',pady=6); r=tk.Frame(c,bg=CARD); r.pack(fill='x',padx=12,pady=12); self._label(r,'High Performance Mode',TEXT,10).pack(side='left'); self._perf_toggle=ToggleSwitch(r,on_toggle=self._perf_changed); self._perf_toggle.pack(side='right'); Section(p,'Activity').pack(fill='x'); c=Card(p); c.pack(fill='x',pady=6); s=tk.Frame(c,bg=CARD); s.pack(fill='x',padx=12,pady=12); self._stat_mean=StatDisplay(s,'Average Delay'); self._stat_std=StatDisplay(s,'Delay Variation'); self._stat_count=StatDisplay(s,'Traffic Handled'); self._stat_shot=StatDisplay(s,'Waiting (Shots)'); self._stat_bypass=StatDisplay(s,'Sent Without Delay'); [w.pack(fill='x',pady=3) for w in (self._stat_mean,self._stat_std,self._stat_count,self._stat_shot,self._stat_bypass)]; self._graph=SpreadGraph(c,width=850,height=80); self._graph.pack(fill='x',padx=10,pady=10)
    def _set(self,k,v): self._settings[k]=v
    def _set_int(self,k,v,d):
        try:self._settings[k]=int(v)
        except:self._settings[k]=d
    def _set_rhythm(self,v): self._settings['rhythm_ms']=v; self._settings['tempo_ms']=v
    def _priority_changed(self,value):
        previous=str(self._settings.get('process_priority','normal'))
        try:
            applied=set_process_priority(value);self._settings['process_priority']=applied
            shown='Real Time' if applied=='realtime' else applied.title();self._priority_status.configure(text=f'{shown} priority active'+(' · Use only while testing; it can starve Chiaki/Windows.' if applied=='realtime' else ''),fg='#10b981' if applied!='realtime' else '#f59e0b')
        except Exception as exc:
            self._priority_var.set('Real Time' if previous=='realtime' else previous.title());self._priority_status.configure(text=f'Priority change failed: {exc}',fg='#ef4444')
    def _vision_toggle_changed(self,s):
        if s:
            try:self._vision.start(); self._vision_status.configure(text=f'On · {self._vision.status}',fg='#10b981')
            except Exception as e:self._vision_toggle.set_state(False); self._vision_status.configure(text=str(e),fg='#ef4444')
        else:self._vision.stop(); self._vision_status.configure(text='Off',fg=MUTED); self._preview.configure(image='',text='Enable Vision Assist to start preview'); self._preview_image=None
    def _controller_toggle_changed(self,s):
        if s:self._connect_controller()
        else:self._controller.disconnect(); self._controller_status.configure(text='Disconnected',fg=MUTED)
    def _connect_controller(self):
        if self._controller.connect_auto():self._controller_toggle.set_state(True); self._controller_status.configure(text=f'Connected · {self._controller.kind}',fg='#10b981')
        else:
            self._controller_toggle.set_state(False)
            detail=getattr(self._controller,'error','') or 'Controller unavailable'
            self._controller_status.configure(text=detail,fg='#ef4444',wraplength=780,justify='left')
    def _network_toggle_changed(self,s): self._start_network() if s else self._stop_network()
    def _start_network(self):
        if self._running:return
        try:e=PacketCapture('udp',delay_ms=0,shot_delay_ms=500 if self._shot_toggle.get_state() else 0); e.start(); self._engine=e; self._running=True; self._net_dot.set_active(True); self._net_status.configure(text='Running',fg='#10b981')
        except Exception as x:self._net_toggle.set_state(False); self._net_status.configure(text=str(x),fg='#ef4444')
    def _stop_network(self):
        if self._engine:
            try:self._engine.stop()
            except:pass
        self._engine=None; self._running=False; self._net_dot.set_active(False); self._net_status.configure(text='Off',fg=MUTED)
    def _shot_changed(self,s):
        if self._engine:self._engine.set_shot_delay(500 if s else 0)
    def _perf_changed(self,s):
        try:
            self._system_tweaks.enable(self._engine.threads if self._engine else ()) if s else self._system_tweaks.disable()
            self._priority_changed(self._priority_var.get())
        except SystemTweaksError:self._perf_toggle.set_state(False)
    def _poll(self):
        if self._closing:return
        if self._engine:
            try:s=self._engine.get_stats(); self._stat_mean.set_value(f"{s['mean']:.1f} ms"); self._stat_std.set_value(f"{s['std']:.1f} ms"); self._stat_count.set_value(str(s['count'])); self._stat_shot.set_value(str(s['shot_depth'])); self._stat_bypass.set_value(str(s['bypassed'])); self._graph.push(float(s['mean']))
            except:pass
        if self._vision.running and self._active_tab=='Vision':
            self._vision_state.configure(text=self._vision.state() or 'Scanning for meter'); frame=self._vision.frame()
            if frame is not None and Image and ImageTk:
                try:
                    import cv2
                    im=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)); im.thumbnail((max(400,self._preview.winfo_width()-20),max(300,self._preview.winfo_height()-20))); self._preview_image=ImageTk.PhotoImage(im); self._preview.configure(image=self._preview_image,text='')
                except:pass
        poll_ms={"performance":67,"balanced":33,"quality":16}.get(str(self._settings.get("preview_mode","balanced")).lower(),33)
        self._poll_id=self.after(poll_ms,self._poll)
    def _begin_drag(self,e):self._titlebar_drag_origin=(e.x_root,e.y_root,self.winfo_x(),self.winfo_y())
    def _drag(self,e):
        if self._titlebar_drag_origin:sx,sy,wx,wy=self._titlebar_drag_origin; self.geometry(f'+{wx+e.x_root-sx}+{wy+e.y_root-sy}')
    def _minimize(self):self.overrideredirect(False); self.iconify(); self.bind('<Map>',self._restore,add='+')
    def _restore(self,_=None):
        if self.state()=='normal':self.overrideredirect(True); self._apply_taskbar_style(); self.unbind('<Map>')
    def _apply_taskbar_style(self):
        if sys.platform!='win32':return
        try:u=ctypes.WinDLL('user32',use_last_error=True); h=u.GetAncestor(self.winfo_id(),2); s=u.GetWindowLongW(h,-20); u.SetWindowLongW(h,-20,(s&~0x80)|0x40000); u.SetWindowPos(h,None,0,0,0,0,0x37)
        except:logging.exception('Taskbar style setup failed')
    def on_close(self):
        if self._closing:return
        self._closing=True
        if self._poll_id:
            try:self.after_cancel(self._poll_id)
            except Exception:pass
            self._poll_id=None
        if self._overlay:
            try:self._overlay.close()
            except Exception:pass
            self._overlay=None
        for f in (self._vision.stop,self._controller.disconnect,self._stop_network,self._system_tweaks.disable):
            try:f()
            except:pass
        try:set_process_priority('normal')
        except Exception:pass
        try:self.quit()
        finally:self.destroy()

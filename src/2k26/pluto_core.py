"""Pluto-style CV shot assist + controller bridge, without Pluto's auth/UI."""
from __future__ import annotations

import ctypes
import importlib
import threading
import time
from typing import Any, Callable

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = None
    np = None

DEFAULTS = {
    "target_height": 52,
    "meter_type": "Arrow2",
    "color_name": "Purple",
    "custom_color_bgr": [125, 136, 140],
    "roi_enabled": True,
    "roi_w": 1870,
    "roi_h": 800,
    "roi_color": [255, 210, 0],
    "roi_thickness": 2,
    "show_roi_box": True,
    "bbox_thickness": 2,
    "show_hud": True,
    "cam_index": 0,
    "cam_w": 1920,
    "cam_h": 1080,
    # The detector still runs at capture_fps.  Only the UI preview is reduced,
    # keeping image conversion/rendering from competing with Chiaki.
    "preview_fps": 30,
    "preview_w": 720,
    "preview_h": 405,
    "preview_mode": "balanced",
    "process_priority": "normal",
    "shooting_mode": "Stick Rhythm",
    "tempo_ms": 46,
    "rhythm_ms": 46,
}


def default_settings() -> dict[str, Any]:
    return dict(DEFAULTS)


class CameraCapture:
    def __init__(self, settings):
        self.s, self.cap, self.status = settings, None, "idle"

    def open(self):
        if cv2 is None:
            self.status = "OpenCV missing"; return False
        idx = int(self.s.get("cam_index", 0))
        for candidate in ([idx] if idx == 0 else [idx, 0]):
            try:
                cap = cv2.VideoCapture(candidate, cv2.CAP_DSHOW)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.s.get("cam_w", 1920)))
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.s.get("cam_h", 1080)))
                    self.cap, self.status = cap, f"Camera {candidate}"; return True
                cap.release()
            except Exception:
                pass
        self.status = "Camera unavailable"; return False

    def read(self):
        if self.cap is None: return False, None
        try: return self.cap.read()
        except Exception: return False, None

    def release(self):
        try:
            if self.cap: self.cap.release()
        except Exception: pass
        self.cap = None


def make_source(settings):
    return CameraCapture(settings)


class CVAccelerator:
    """CPU-only mask preparation to avoid competing with Chiaki's renderer."""
    def __init__(self, settings):
        self.backend="CPU";self.error=""

    @staticmethod
    def _operations(meter_type,straight):
        if meter_type=="Pill":return [(cv2.MORPH_CLOSE,(3,9))]
        if straight:return [(cv2.MORPH_DILATE,(3,3)),(cv2.MORPH_CLOSE,(3,15))]
        return [(cv2.MORPH_CLOSE,(7,7))]

    def make_mask(self,roi,size,lo,hi,meter_type,straight):
        operations=self._operations(meter_type,straight)
        small=cv2.resize(roi,size,interpolation=cv2.INTER_NEAREST);mask=cv2.inRange(small,lo,hi)
        for op,shape in operations:mask=cv2.morphologyEx(mask,op,cv2.getStructuringElement(cv2.MORPH_RECT,shape))
        return mask


class CVWorker:
    """Meter-height detector using Pluto's ROI lock/trigger/rearm behavior."""
    def __init__(self, settings):
        if cv2 is None or np is None: raise RuntimeError("opencv-python and numpy are required")
        self.s = settings; self.flick_cb = None; self.frame = None; self.state = "";self.accelerator=CVAccelerator(settings)
        self.smooth_cx = self.smooth_bot = None; self.locked = None; self.peak = 0.0
        self.fired = False; self.rearm = False; self.rising = 0; self.prev_h = 0.0; self.lost = 0
        self.vy1 = self.vy2 = None; self.last_t = None; self.fps = 60
        self.last_process_t=None;self.process_fps=0.0
        self.velocity=0.0;self.rising_samples=0;self.motion_h=None;self.motion_t=None

    def set_flick_callback(self, callback): self.flick_cb = callback

    def _range(self):
        name = self.s.get("color_name", "Purple")
        if name == "Custom":
            b,g,r = [int(v) for v in self.s.get("custom_color_bgr", [200,200,200])]
            return np.array([max(0,b-30),max(0,g-30),max(0,r-30)],np.uint8), np.array([min(255,b+30),min(255,g+30),min(255,r+30)],np.uint8)
        ranges = {
            "Purple":([150,0,150],[255,100,255]), "Yellow":([0,150,150],[120,255,255]),
            "Red":([0,0,150],[120,120,255]), "Orange":([0,70,150],[120,190,255]),
            "Blue":([150,40,0],[255,180,120]), "White":([175,175,175],[255,255,255])}
        lo,hi = ranges.get(name,ranges["Purple"]); return np.array(lo,np.uint8),np.array(hi,np.uint8)

    def _reset(self):
        self.fired=False; self.peak=0.0; self.rearm=False; self.rising=0; self.prev_h=0.0
        self.velocity=0.0;self.rising_samples=0;self.motion_h=self.motion_t=None

    def process(self, frame, captured_at=None):
        now=time.perf_counter();sample_t=float(captured_at) if captured_at is not None else now
        if self.last_process_t:
            process_dt=now-self.last_process_t
            if process_dt>0:
                instant_fps=min(240.0,1.0/process_dt)
                self.process_fps=instant_fps if self.process_fps<=0 else .2*instant_fps+.8*self.process_fps
        self.last_process_t=now
        if self.last_t:
            dt=sample_t-self.last_t
            if dt>0: self.fps=max(15,min(240,int(.25*(1/dt)+.75*self.fps)))
        self.last_t=sample_t
        fh,fw=frame.shape[:2]; rw=min(fw,max(64,int(self.s.get("roi_w",1870)))); rh=min(fh,max(64,int(self.s.get("roi_h",800))))
        if not self.s.get("roi_enabled",True): rw,rh=fw,fh
        rx1=(fw-rw)//2; rx2=rx1+rw; base_y=(fh-rh)//2
        if self.vy1 is None: self.vy1,self.vy2=base_y,base_y+rh
        roi=frame[self.vy1:self.vy2,rx1:rx2]
        if roi.size == 0: self.vy1,self.vy2=base_y,base_y+rh; return frame
        straight=self.s.get("meter_type","Arrow2")=="Straight"; ds=1 if straight else 2
        size=(max(1,roi.shape[1]//ds),max(1,roi.shape[0]//ds));lo,hi=self._range()
        mask=self.accelerator.make_mask(roi,size,lo,hi,self.s.get("meter_type"),straight)
        cnts,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE); best=None; area=0
        for c in cnts:
            x,y,w,h=cv2.boundingRect(c); W,H=w*ds,h*ds
            if W<2 or H<8 or W>100 or H>320 or H/max(W,1)<1.0: continue
            a=cv2.contourArea(c)
            if a>area: best,area=c,a
        trig=False; height=0.0
        if best is not None and area>4:
            x,y,w,h=cv2.boundingRect(best); x=x*ds+rx1; y=y*ds+self.vy1; w*=ds; h*=ds; height=float(h)
            cx=x+w*.5; bot=float(y+h)
            if self.smooth_cx is None: self.smooth_cx,self.smooth_bot=cx,bot
            else: self.smooth_cx=.7*cx+.3*self.smooth_cx; self.smooth_bot=.7*bot+.3*self.smooth_bot
            scx,sbot=int(self.smooth_cx),int(self.smooth_bot); self.locked=(max(0,scx-w//2-12),max(0,sbot-h-12),min(fw,scx+w//2+12),min(fh,sbot+12))
            self.vy1=max(base_y,self.locked[1]-20); self.vy2=min(base_y+rh,self.locked[3]+20); self.lost=0
            if self.fired and self.peak>0 and height<=self.peak*.3: self.fired=False; self.peak=0; self.rearm=True; self.rising=0; self.prev_h=height
            if self.rearm:
                self.rising=self.rising+1 if height>self.prev_h else 0; self.prev_h=height
                if self.rising>=2: self.rearm=False; self.rising=0
            self.peak=max(self.peak,height)
            if self.motion_t is not None and sample_t>self.motion_t:
                motion_dt=sample_t-self.motion_t;instant=(height-self.motion_h)/motion_dt
                if instant>0:
                    self.velocity=instant if self.velocity<=0 else .35*instant+.65*self.velocity
                    self.rising_samples+=1
                else:self.rising_samples=0
            self.motion_h=height;self.motion_t=sample_t
            target=float(self.s.get("target_height",52));delay_ms=0
            should_fire=height>=target
            if not should_fire and self.rising_samples>=2 and self.velocity>30:
                eta=(target-height)/self.velocity;lookahead=min(.035,1.5/max(self.fps,1))
                if 0<eta<=lookahead:should_fire=True;delay_ms=max(0,int(round(eta*1000)))
            if not self.rearm and not self.fired and should_fire:
                self.fired=True;trig=True
                if self.flick_cb:
                    try:self.flick_cb(delay_ms=delay_ms)
                    except TypeError:self.flick_cb()
        else:
            self.locked=None; self.lost+=1
            if self.lost >= (5 if straight else 3): self.vy1,self.vy2=base_y,base_y+rh; self.smooth_cx=self.smooth_bot=None; self._reset()
        rc=tuple(int(v) for v in self.s.get("roi_color",[255,210,0]))
        if self.s.get("show_roi_box",True) and self.s.get("roi_enabled",True): cv2.rectangle(frame,(rx1,base_y),(rx2,base_y+rh),rc,max(1,int(self.s.get("roi_thickness",2))))
        if self.s.get("show_hud",True) and self.locked:
            cv2.rectangle(frame,(self.locked[0],self.locked[1]),(self.locked[2],self.locked[3]),rc,max(1,int(self.s.get("bbox_thickness",2))))
            cv2.putText(frame,f"{int(height)}px {self.fps}fps",(rx1+4,max(20,base_y+22)),cv2.FONT_HERSHEY_SIMPLEX,.55,(160,100,255),1,cv2.LINE_AA)
        self.frame=frame; self.state=f"{'1' if trig else '0'}:{int(height)}:{float(self.s.get('target_height',52)):.1f}:{self.fps}:{self.accelerator.backend}"; return frame


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_=[("wButtons",ctypes.c_ushort),("bLeftTrigger",ctypes.c_ubyte),("bRightTrigger",ctypes.c_ubyte),("sThumbLX",ctypes.c_short),("sThumbLY",ctypes.c_short),("sThumbRX",ctypes.c_short),("sThumbRY",ctypes.c_short)]
class XINPUT_STATE(ctypes.Structure): _fields_=[("dwPacketNumber",ctypes.c_ulong),("Gamepad",XINPUT_GAMEPAD)]
_XI=None
def _xget(port,state):
    global _XI
    try:
        if _XI is None:
            for name in ("XInput1_4","XInput1_3","XInput9_1_0"):
                try: _XI=getattr(ctypes.windll,name); break
                except Exception: pass
        return 1 if _XI is None else _XI.XInputGetState(port,ctypes.byref(state))
    except Exception: return 1

def xbox_port():
    st=XINPUT_STATE()
    for i in range(4):
        if _xget(i,st)==0: return i
    return None


class ControllerTicker:
    """One-millisecond controller clock using Windows' high-resolution timer."""
    def __init__(self,period_ms=1):
        self.period_ms=max(1,int(period_ms));self.handle=None;self.kernel32=None;self.winmm=None;self.deadline=0.0
    def __enter__(self):
        self.deadline=time.perf_counter()+self.period_ms/1000
        if not hasattr(ctypes,"WinDLL"):return self
        try:
            from ctypes import wintypes
            self.kernel32=ctypes.WinDLL("kernel32",use_last_error=True);self.winmm=ctypes.WinDLL("winmm")
            k=self.kernel32;k.CreateWaitableTimerExW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD];k.CreateWaitableTimerExW.restype=wintypes.HANDLE
            k.SetWaitableTimer.argtypes=[wintypes.HANDLE,ctypes.POINTER(ctypes.c_longlong),wintypes.LONG,ctypes.c_void_p,ctypes.c_void_p,wintypes.BOOL];k.SetWaitableTimer.restype=wintypes.BOOL
            k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];k.WaitForSingleObject.restype=wintypes.DWORD;k.CancelWaitableTimer.argtypes=[wintypes.HANDLE];k.CloseHandle.argtypes=[wintypes.HANDLE]
            # Keep the accurate timer, but leave the thread at normal priority.
            # Raising it can steal decode/render time from Chiaki and make the
            # controller feel delayed even when forwarding itself is timely.
            self.winmm.timeBeginPeriod(1)
            self.handle=k.CreateWaitableTimerExW(None,None,0x2,0x1F0003);due=ctypes.c_longlong(-self.period_ms*10_000)
            if not self.handle or not k.SetWaitableTimer(self.handle,ctypes.byref(due),self.period_ms,None,None,False):self.handle=None
        except Exception:self.handle=None
        return self
    def wait(self):
        if self.handle:
            self.kernel32.WaitForSingleObject(self.handle,max(10,self.period_ms*10));return
        remaining=self.deadline-time.perf_counter()
        if remaining>0:time.sleep(remaining)
        now=time.perf_counter();self.deadline=self.deadline+self.period_ms/1000 if now<self.deadline+self.period_ms/1000 else now+self.period_ms/1000
    def __exit__(self,*_):
        if self.handle:
            try:self.kernel32.CancelWaitableTimer(self.handle);self.kernel32.CloseHandle(self.handle)
            except Exception:pass
        if self.winmm:
            try:self.winmm.timeEndPeriod(1)
            except Exception:pass


class RhythmFlick:
    def __init__(self,settings): self.s=settings; self.rd=0; self.phase=None; self.ramp=self.hold=0.0; self.fv=0; self.center=0.0; self.block=False; self.block_t=0.0;self.pending_at=None
    def track(self,ry):
        if self.phase is None:
            if ry < -8000: self.rd=1
            elif ry > 8000: self.rd=0
    def schedule(self,delay_ms=0):
        due=time.perf_counter()+max(0,float(delay_ms))/1000
        if self.pending_at is None or due<self.pending_at:self.pending_at=due
    def fire(self):self.schedule(0)
    def advance(self):
        now=time.perf_counter()
        if self.pending_at is None or now<self.pending_at:return
        self.pending_at=None;mode=self.s.get("shooting_mode","Stick Rhythm");tempo=max(4,min(200,int(self.s.get("rhythm_ms",46))))/1000
        if mode=="Button": self.block=True; self.block_t=now
        elif mode=="Stick": self.center=now+.1
        else: self.fv=32767 if self.rd else -32767; self.phase="ramp"; self.ramp=now+tempo; self.hold=self.ramp+.3
    def button_blocked(self,pressed):
        if not pressed or time.perf_counter()-self.block_t>.55: self.block=False
        return self.block
    def override(self,ry):
        now=time.perf_counter()
        if now<self.center: return 0
        if self.phase=="ramp":
            if now<self.ramp: return int(self.fv*.5)
            self.phase="hold"
        if self.phase=="hold":
            if now<self.hold: return self.fv
            self.phase=None
        return ry


class XboxProxy:
    def __init__(self,port,settings):
        self.port,self.s,self.running=port,settings,False; self.rf=RhythmFlick(settings); self.lock=threading.Lock(); self.err=""; self.pad=self.vg=None;self._last_report=None;self.thread=None
        try:
            import vgamepad as vg
            self.vg=vg; self.pad=vg.VX360Gamepad(); self.pad.update()
        except Exception as e: self.err=str(e)
    def ready(self): return self.pad is not None
    def start(self):self.running=True;self.thread=threading.Thread(target=self._loop,daemon=True,name="xinput-proxy");self.thread.start()
    def cleanup(self):
        self.running=False
        try:
            if self.pad: self.pad.reset(); self.pad.update()
        except Exception: pass
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=.15)
        self.thread=None
    def flick(self,delay_ms=0):
        with self.lock:self.rf.schedule(delay_ms)
    def _loop(self):
        with ControllerTicker(1) as ticker:
            while self.running:self._tick();ticker.wait()
    def _tick(self):
        st=XINPUT_STATE()
        if _xget(self.port,st)!=0 or not self.pad:return
        g=st.Gamepad; dz=7849; lx=g.sThumbLX if abs(g.sThumbLX)>dz else 0; ly=g.sThumbLY if abs(g.sThumbLY)>dz else 0; rx=g.sThumbRX if abs(g.sThumbRX)>dz else 0; ry=g.sThumbRY if abs(g.sThumbRY)>dz else 0; shoot=bool(g.wButtons&16384)
        with self.lock:self.rf.advance();self.rf.track(ry);ry=self.rf.override(ry);blocked=self.s.get("shooting_mode")=="Button" and self.rf.button_blocked(shoot)
        pressed_mask=int(g.wButtons)&~(16384 if blocked else 0);report=(lx,ly,rx,ry,int(g.bLeftTrigger),int(g.bRightTrigger),pressed_mask)
        if report==self._last_report:return
        try:
            self.pad.left_joystick(x_value=lx,y_value=ly); self.pad.right_joystick(x_value=rx,y_value=ry); self.pad.left_trigger(value=int(g.bLeftTrigger)); self.pad.right_trigger(value=int(g.bRightTrigger))
            for bit in [1,2,4,8,16,32,64,128,256,512,4096,8192,16384,32768]:
                b=self.vg.XUSB_BUTTON(bit);pressed=bool(pressed_mask&bit);self.pad.press_button(button=b) if pressed else self.pad.release_button(button=b)
            self.pad.update();self._last_report=report
        except Exception: pass


class DualSenseProxy:
    def __init__(self,settings):
        self.s=settings; self.running=False; self.rf=RhythmFlick(settings); self.lock=threading.Lock(); self.err=""; self.ds=self.pad=self.vg=None;self._last_report=None;self.thread=None
        try:
            import pydualsense
        except Exception as e:
            self.err=f"DualSense HID library failed: {e}";return
        try:
            self.ds=pydualsense.pydualsense()
            # pydualsense creates a blocking HID reader without daemon=True.
            # Make that library-owned reader unable to keep a frozen app alive.
            implementation=importlib.import_module("pydualsense.pydualsense");thread_api=implementation.threading
            class DaemonThreadFactory:
                @staticmethod
                def Thread(*args,**kwargs):kwargs["daemon"]=True;return threading.Thread(*args,**kwargs)
            implementation.threading=DaemonThreadFactory
            try:self.ds.init()
            finally:implementation.threading=thread_api
        except Exception as e:
            self.ds=None;self.err=f"DualSense device failed: {e}";return
        try:
            import vgamepad
            self.vg=vgamepad;self.pad=vgamepad.VX360Gamepad();self.pad.update()
        except Exception as e:
            self.err=f"Virtual Xbox controller failed: {e}";self.cleanup();self.pad=None
    def ready(self): return self.ds is not None and self.pad is not None
    def start(self):self.running=True;self.thread=threading.Thread(target=self._loop,daemon=True,name="dualsense-proxy");self.thread.start()
    def cleanup(self):
        self.running=False
        try:
            if self.pad:self.pad.reset();self.pad.update()
        except Exception:pass
        ds=self.ds;self.ds=None
        if ds:
            try:ds.ds_thread=False
            except Exception:pass
            report_thread=getattr(ds,"report_thread",None)
            if report_thread and report_thread is not threading.current_thread():report_thread.join(timeout=.15)
            device=getattr(ds,"device",None)
            if device:
                try:device.close()
                except Exception:pass
            if report_thread and report_thread is not threading.current_thread() and report_thread.is_alive():report_thread.join(timeout=.25)
            try:ds.connected=False
            except Exception:pass
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=.15)
        self.thread=None
    def flick(self,delay_ms=0):
        with self.lock:self.rf.schedule(delay_ms)
    @staticmethod
    def scale(v): return min(32767,int(v*32767/127)) if v>=0 else max(-32767,int(v*32767/128))
    def _loop(self):
        with ControllerTicker(1) as ticker:
            while self.running:self._tick();ticker.wait()
    def _tick(self):
        if not self.ds or not self.pad:return
        try:
            s=self.ds.state; lx=self.scale(s.LX);ly=self.scale(-s.LY);rx=self.scale(s.RX);ry=self.scale(-s.RY);shoot=bool(s.square)
            with self.lock:self.rf.advance();self.rf.track(ry);ry=self.rf.override(ry);blocked=self.s.get("shooting_mode")=="Button" and self.rf.button_blocked(shoot)
            buttons=[(bool(getattr(s,attr)) and not blk,name) for attr,name,blk in [("square","XUSB_GAMEPAD_X",blocked),("cross","XUSB_GAMEPAD_A",False),("circle","XUSB_GAMEPAD_B",False),("triangle","XUSB_GAMEPAD_Y",False),("L1","XUSB_GAMEPAD_LEFT_SHOULDER",False),("R1","XUSB_GAMEPAD_RIGHT_SHOULDER",False),("L3","XUSB_GAMEPAD_LEFT_THUMB",False),("R3","XUSB_GAMEPAD_RIGHT_THUMB",False),("options","XUSB_GAMEPAD_START",False),("share","XUSB_GAMEPAD_BACK",False)]]
            report=(lx,ly,rx,ry,int(s.L2_value),int(s.R2_value),tuple(v for v,_ in buttons))
            if report==self._last_report:return
            self.pad.left_joystick(x_value=lx,y_value=ly);self.pad.right_joystick(x_value=rx,y_value=ry);self.pad.left_trigger(value=int(s.L2_value));self.pad.right_trigger(value=int(s.R2_value))
            for pressed,name in buttons:
                b=getattr(self.vg.XUSB_BUTTON,name);self.pad.press_button(button=b) if pressed else self.pad.release_button(button=b)
            self.pad.update();self._last_report=report
        except Exception:pass


class ControllerManager:
    def __init__(self,settings): self.s=settings;self.proxy=None;self.kind="None";self.error=""
    def connect_auto(self):
        self.disconnect(); self.error=""; errors=[]; port=xbox_port()
        if port is not None:
            p=XboxProxy(port,self.s)
            if p.ready(): self.proxy,self.kind=p,f"XInput {port}";p.start();return True
            errors.append(f"XInput detected, but virtual controller failed: {p.err or 'unknown error'}")
        p=DualSenseProxy(self.s)
        if p.ready(): self.proxy,self.kind=p,"DualSense";p.start();return True
        if "No device detected" in p.err:
            errors.append("DualSense is not visible to this app (check HidHide application access and reconnect the controller)")
        else:
            errors.append(f"DualSense failed: {p.err or 'unknown error'}")
        self.error="; ".join(errors);return False
    def flick(self,delay_ms=0):
        if self.proxy:self.proxy.flick(delay_ms)
    def disconnect(self):
        if self.proxy:
            try:self.proxy.cleanup()
            except Exception:pass
        self.proxy=None;self.kind="None"


class VisionAssist:
    def __init__(self,settings,flick_callback:Callable[[],None]):
        self.s=settings;self.flick=flick_callback;self.source=self.worker=None;self.running=False;self.thread=None;self.lock=threading.Lock();self.latest=None;self.status="Off";self.error="";self._next_preview=0.0
    def start(self):
        if self.running:return
        if cv2 is None or np is None:raise RuntimeError("Install opencv-python and numpy")
        self.source=make_source(self.s)
        if getattr(self.source,"status","idle")=="idle" and not self.source.open():raise RuntimeError(getattr(self.source,"status","Capture failed"))
        self.worker=CVWorker(self.s);self.worker.set_flick_callback(self.flick);self.running=True;self._next_preview=0.0;self.status=f"{getattr(self.source,'status','On')} · {self.worker.accelerator.backend}";self.thread=threading.Thread(target=self._loop,daemon=True,name="vision-assist");self.thread.start()
    def stop(self):
        self.running=False
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=.4)
        if self.source:
            try:self.source.release()
            except Exception:pass
        self.source=self.worker=self.thread=None;self.status="Off"
        self._next_preview=0.0
        with self.lock:self.latest=None
    def frame(self):
        with self.lock:return None if self.latest is None else self.latest.copy()
    def state(self):return self.worker.state if self.worker else ""
    def metrics(self):
        worker=self.worker
        if not worker:return {"process_fps":0.0,"capture_fps":0.0,"backend":"Off"}
        return {"process_fps":float(worker.process_fps),"capture_fps":float(worker.fps),"backend":worker.accelerator.backend}
    def _publish_preview(self,frame,now):
        profiles={
            "performance":(15,480,270),
            "balanced":(30,720,405),
            "quality":(60,1280,720),
        }
        mode=str(self.s.get("preview_mode","balanced")).lower();fps,max_w,max_h=profiles.get(mode,profiles["balanced"])
        if now<self._next_preview:return
        h,w=frame.shape[:2];scale=min(1.0,max_w/max(w,1),max_h/max(h,1))
        if scale<1.0:
            preview=cv2.resize(frame,(max(1,int(w*scale)),max(1,int(h*scale))),interpolation=cv2.INTER_AREA)
        else:preview=frame.copy()
        with self.lock:self.latest=preview
        self._next_preview=now+1.0/fps
    def _loop(self):
        while self.running and self.source and self.worker:
            ok,frame=self.source.read()
            if not ok or frame is None:time.sleep(.004);continue
            try:
                out=self.worker.process(frame,getattr(self.source,"frame_timestamp",None))
                self._publish_preview(out,time.perf_counter())
            except Exception as e:self.error=str(e);self.status="Error";self.running=False

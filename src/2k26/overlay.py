"""Per-pixel-alpha VISION 2K HUD with softly glowing snow."""
from __future__ import annotations

import ctypes
import math
import os
import random
import time
import tkinter as tk
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


class _Point(ctypes.Structure):
    _fields_=[("x",ctypes.c_long),("y",ctypes.c_long)]


class _Size(ctypes.Structure):
    _fields_=[("cx",ctypes.c_long),("cy",ctypes.c_long)]


class _Blend(ctypes.Structure):
    _fields_=[("BlendOp",ctypes.c_ubyte),("BlendFlags",ctypes.c_ubyte),("SourceConstantAlpha",ctypes.c_ubyte),("AlphaFormat",ctypes.c_ubyte)]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_=[("biSize",ctypes.c_uint32),("biWidth",ctypes.c_long),("biHeight",ctypes.c_long),("biPlanes",ctypes.c_ushort),("biBitCount",ctypes.c_ushort),("biCompression",ctypes.c_uint32),("biSizeImage",ctypes.c_uint32),("biXPelsPerMeter",ctypes.c_long),("biYPelsPerMeter",ctypes.c_long),("biClrUsed",ctypes.c_uint32),("biClrImportant",ctypes.c_uint32)]


class _BitmapInfo(ctypes.Structure):
    _fields_=[("bmiHeader",_BitmapInfoHeader),("bmiColors",ctypes.c_uint32*3)]


class _LayeredSurface:
    """32-bit premultiplied DIB presented through UpdateLayeredWindow."""
    def __init__(self,hwnd,width,height):
        self.hwnd=ctypes.c_void_p(hwnd);self.width=width;self.height=height
        self.user32=ctypes.WinDLL("user32",use_last_error=True);self.gdi32=ctypes.WinDLL("gdi32",use_last_error=True)
        self.user32.GetDC.argtypes=[ctypes.c_void_p];self.user32.GetDC.restype=ctypes.c_void_p
        self.user32.ReleaseDC.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
        self.gdi32.CreateCompatibleDC.argtypes=[ctypes.c_void_p];self.gdi32.CreateCompatibleDC.restype=ctypes.c_void_p
        self.gdi32.CreateDIBSection.argtypes=[ctypes.c_void_p,ctypes.POINTER(_BitmapInfo),ctypes.c_uint,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p,ctypes.c_uint];self.gdi32.CreateDIBSection.restype=ctypes.c_void_p
        self.gdi32.SelectObject.argtypes=[ctypes.c_void_p,ctypes.c_void_p];self.gdi32.SelectObject.restype=ctypes.c_void_p
        self.gdi32.DeleteObject.argtypes=[ctypes.c_void_p];self.gdi32.DeleteDC.argtypes=[ctypes.c_void_p]
        self.user32.UpdateLayeredWindow.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(_Point),ctypes.POINTER(_Size),ctypes.c_void_p,ctypes.POINTER(_Point),ctypes.c_uint32,ctypes.POINTER(_Blend),ctypes.c_uint32]
        screen_dc=self.user32.GetDC(None);self.memory_dc=self.gdi32.CreateCompatibleDC(screen_dc)
        info=_BitmapInfo();info.bmiHeader.biSize=ctypes.sizeof(_BitmapInfoHeader);info.bmiHeader.biWidth=width
        info.bmiHeader.biHeight=-height;info.bmiHeader.biPlanes=1;info.bmiHeader.biBitCount=32;info.bmiHeader.biCompression=0
        self.bits=ctypes.c_void_p();self.bitmap=self.gdi32.CreateDIBSection(screen_dc,ctypes.byref(info),0,ctypes.byref(self.bits),None,0)
        self.old_bitmap=self.gdi32.SelectObject(self.memory_dc,self.bitmap);self.user32.ReleaseDC(None,screen_dc)
        if not self.memory_dc or not self.bitmap or not self.bits.value:raise OSError("Unable to create alpha overlay surface")

    def present(self,bgra):
        ctypes.memmove(self.bits.value,bgra.ctypes.data,bgra.nbytes)
        dst=_Point(0,0);src=_Point(0,0);size=_Size(self.width,self.height);blend=_Blend(0,0,255,1)
        screen_dc=self.user32.GetDC(None)
        try:self.user32.UpdateLayeredWindow(self.hwnd,screen_dc,ctypes.byref(dst),ctypes.byref(size),self.memory_dc,ctypes.byref(src),0,ctypes.byref(blend),2)
        finally:self.user32.ReleaseDC(None,screen_dc)

    def close(self):
        if self.memory_dc and self.old_bitmap:self.gdi32.SelectObject(self.memory_dc,self.old_bitmap)
        if self.bitmap:self.gdi32.DeleteObject(self.bitmap)
        if self.memory_dc:self.gdi32.DeleteDC(self.memory_dc)
        self.memory_dc=self.bitmap=self.old_bitmap=None


def _font(name,size):
    path=Path(os.environ.get("WINDIR",r"C:\Windows"))/"Fonts"/name
    try:return ImageFont.truetype(str(path),size)
    except OSError:return ImageFont.load_default()


def _glowing_text(text,font,top,bottom,glow,blur=8,padding=16,glow_opacity=.6):
    bbox=font.getbbox(text);width=bbox[2]-bbox[0]+padding*2;height=bbox[3]-bbox[1]+padding*2
    mask=Image.new("L",(width,height));draw=ImageDraw.Draw(mask);draw.text((padding-bbox[0],padding-bbox[1]),text,font=font,fill=255)
    halo=mask.filter(ImageFilter.GaussianBlur(blur)).point(lambda value:round(value*glow_opacity))
    result=Image.new("RGBA",mask.size);light=Image.new("RGBA",mask.size,glow);light.putalpha(halo);result.alpha_composite(light)
    face=Image.new("RGBA",mask.size)
    face_draw=ImageDraw.Draw(face);den=max(1,height-1)
    for y in range(height):
        t=y/den;color=tuple(round(top[i]*(1-t)+bottom[i]*t) for i in range(3))
        face_draw.line((0,y,width,y),fill=(*color,255))
    face.putalpha(mask);result.alpha_composite(face)
    # A restrained top-edge highlight makes the letters look polished, not neon-flat.
    shine=mask.filter(ImageFilter.GaussianBlur(.55));shine=shine.transform(shine.size,Image.AFFINE,(1,0,0,0,1,1))
    highlight=Image.new("RGBA",mask.size,(255,255,255,0));highlight.putalpha(shine.point(lambda value:value//5));result.alpha_composite(highlight)
    return result


def _flake_sprite(radius):
    glow=10;size=int((radius+glow)*2+4);center=size/2
    core=Image.new("L",(size,size));d=ImageDraw.Draw(core);d.ellipse((center-radius,center-radius,center+radius,center+radius),fill=235)
    halo=core.filter(ImageFilter.GaussianBlur(5.2)).point(lambda value:value*3//4)
    sprite=Image.new("RGBA",(size,size));blue=Image.new("RGBA",(size,size),(40,168,255,0));blue.putalpha(halo);sprite.alpha_composite(blue)
    bright=Image.new("RGBA",(size,size),(175,239,255,0));bright.putalpha(core);sprite.alpha_composite(bright)
    return sprite


def _premultiplied_bgra(image):
    rgba=np.asarray(image,dtype=np.uint8);bgra=rgba[:,:,[2,1,0,3]].copy();alpha=bgra[:,:,3].astype(np.uint16)
    for channel in range(3):bgra[:,:,channel]=((bgra[:,:,channel].astype(np.uint16)*alpha+127)//255).astype(np.uint8)
    return bgra


def _alpha_over(target,source,x,y):
    """Composite a small premultiplied BGRA sprite into a BGRA target."""
    h,w=source.shape[:2];x1=max(0,x);y1=max(0,y);x2=min(target.shape[1],x+w);y2=min(target.shape[0],y+h)
    if x1>=x2 or y1>=y2:return
    src=source[y1-y:y2-y,x1-x:x2-x];dst=target[y1:y2,x1:x2];inv=(255-src[:,:,3:4].astype(np.uint16))
    dst[:,:,:3]=np.minimum(255,src[:,:,:3].astype(np.uint16)+(dst[:,:,:3].astype(np.uint16)*inv+127)//255).astype(np.uint8)
    dst[:,:,3]=np.minimum(255,src[:,:,3].astype(np.uint16)+(dst[:,:,3].astype(np.uint16)*inv[:,:,0]+127)//255).astype(np.uint8)


class VisionOverlay:
    def __init__(self,owner,settings,vision):
        self.owner=owner;self.settings=settings;self.vision=vision;self._after=None;self._closed=False
        self._last_wall=time.perf_counter();self._last_cpu=time.process_time();self._cpu=0.0;self._stats="";self.stats_sprite=None
        self.window=tk.Toplevel(owner);self.window.withdraw();self.window.overrideredirect(True);self.window.attributes("-topmost",True)
        self.width=max(640,self.window.winfo_screenwidth());self.height=max(480,self.window.winfo_screenheight())
        self.window.geometry(f"{self.width}x{self.height}+0+0");self.window.update_idletasks()
        self.hwnd=self._window_handle();self._configure_window();self.surface=_LayeredSurface(self.hwnd,self.width,self.height)
        self.title_sprite=_glowing_text("VISION 2K",_font("seguisb.ttf",28),(255,255,255),(39,193,255),(21,158,255,255),12,25,.7)
        self.stats_font=_font("consolab.ttf",14);self._flakes=[];self._sprites={};self.buffer=np.zeros((self.height,self.width,4),dtype=np.uint8)
        rng=random.Random(time.time_ns());count=max(12,min(22,self.width//100))
        for _ in range(count):
            radius=rng.choice((1.5,2.0,2.5));self._sprites.setdefault(radius,_premultiplied_bgra(_flake_sprite(radius)))
            self._flakes.append({"x":rng.uniform(10,self.width-10),"y":rng.uniform(110,self.height),"r":radius,"speed":rng.uniform(.45,.9),"drift":rng.uniform(-.18,.18),"phase":rng.uniform(0,math.tau)})
        self._refresh_stats();self._draw_flakes();self.window.deiconify();self.window.update_idletasks();self._configure_window();self._render();self._after=self.window.after(100,self._tick)

    def _window_handle(self):
        user32=ctypes.WinDLL("user32",use_last_error=True);user32.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint];user32.GetAncestor.restype=ctypes.c_void_p
        return user32.GetAncestor(ctypes.c_void_p(self.window.winfo_id()),2) or self.window.winfo_id()

    def _configure_window(self):
        user32=ctypes.WinDLL("user32",use_last_error=True);get_style=getattr(user32,"GetWindowLongPtrW",user32.GetWindowLongW);set_style=getattr(user32,"SetWindowLongPtrW",user32.SetWindowLongW)
        get_style.argtypes=[ctypes.c_void_p,ctypes.c_int];get_style.restype=ctypes.c_ssize_t;set_style.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_ssize_t];set_style.restype=ctypes.c_ssize_t
        style=get_style(ctypes.c_void_p(self.hwnd),-20);set_style(ctypes.c_void_p(self.hwnd),-20,style|0x20|0x80|0x80000|0x08000000)
        user32.SetWindowPos(ctypes.c_void_p(self.hwnd),ctypes.c_void_p(-1),0,0,0,0,0x0013)
        try:user32.SetWindowDisplayAffinity(ctypes.c_void_p(self.hwnd),0x11)
        except Exception:pass

    def _refresh_stats(self):
        now=time.perf_counter();cpu_now=time.process_time();wall=max(.001,now-self._last_wall);cores=max(1,os.cpu_count() or 1)
        self._cpu=max(0.0,min(100.0,(cpu_now-self._last_cpu)*100/(wall*cores)));self._last_wall=now;self._last_cpu=cpu_now
        m=self.vision.metrics();backend=str(m["backend"])
        priority=str(self.settings.get("process_priority","normal")).replace("realtime","real time").upper()
        self._stats=(f"PROCESS {m['process_fps']:5.1f} FPS   CAPTURE {m['capture_fps']:5.1f} FPS   APP CPU {self._cpu:4.1f}%   "
                     f"BACKEND {backend}   PRIORITY {priority}")
        self.stats_sprite=_glowing_text(self._stats,self.stats_font,(235,251,255),(140,221,255),(12,105,180,255),4,9)
        self._draw_hud()

    def _draw_hud(self):
        self.buffer[:96,:,:]=0
        title=_premultiplied_bgra(self.title_sprite);_alpha_over(self.buffer,title,round((self.width-title.shape[1])/2),-8)
        if self.stats_sprite:
            stats=_premultiplied_bgra(self.stats_sprite);_alpha_over(self.buffer,stats,round((self.width-stats.shape[1])/2),48-stats.shape[0]//2)

    def _flake_rect(self,flake):
        sprite=self._sprites[flake["r"]];return round(flake["x"]-sprite.shape[1]/2),round(flake["y"]-sprite.shape[0]/2),sprite.shape[1],sprite.shape[0]

    def _clear_flakes(self):
        for flake in self._flakes:
            x,y,w,h=self._flake_rect(flake);x1=max(0,x);y1=max(96,y);x2=min(self.width,x+w);y2=min(self.height,y+h)
            if x1<x2 and y1<y2:self.buffer[y1:y2,x1:x2]=0

    def _draw_flakes(self):
        for flake in self._flakes:
            sprite=self._sprites[flake["r"]];x,y,_,_=self._flake_rect(flake);_alpha_over(self.buffer,sprite,x,y)

    def _render(self):
        self.surface.present(self.buffer)

    def _tick(self):
        if self._closed:return
        try:
            now=time.perf_counter()
            self._clear_flakes()
            if now-self._last_wall>=.5:self._refresh_stats()
            for flake in self._flakes:
                flake["x"]+=flake["drift"]+math.sin(now*.7+flake["phase"])*.1;flake["y"]+=flake["speed"]
                if flake["y"]>self.height+12:flake["y"]=110;flake["x"]=random.uniform(10,self.width-10)
            self._draw_flakes();self._render();self._after=self.window.after(100,self._tick)
        except (tk.TclError,OSError):self._after=None

    def close(self):
        self._closed=True
        if self._after:
            try:self.window.after_cancel(self._after)
            except tk.TclError:pass
            self._after=None
        try:self.surface.close()
        except Exception:pass
        try:self.window.destroy()
        except tk.TclError:pass

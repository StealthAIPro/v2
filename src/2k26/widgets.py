"""
Custom Tkinter widgets with modern, dark-themed styling.
"""

import tkinter as tk
import collections
import ctypes
import time


def _system_animations_enabled():
    """Honor Windows' "Show animations in Windows" accessibility setting."""
    try:
        enabled = ctypes.c_bool()
        result = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0  # SPI_GETCLIENTAREAANIMATION
        )
        return bool(result and enabled.value)
    except (AttributeError, OSError):
        return True


def _blend_color(start, end, amount):
    """Interpolate between two #RRGGBB colors."""
    start_rgb = tuple(int(start[i:i + 2], 16) for i in (1, 3, 5))
    end_rgb = tuple(int(end[i:i + 2], 16) for i in (1, 3, 5))
    mixed = tuple(round(a + (b - a) * amount) for a, b in zip(start_rgb, end_rgb))
    return '#{:02x}{:02x}{:02x}'.format(*mixed)


class ToggleSwitch(tk.Canvas):
    """Modern pill-shaped toggle switch."""

    ANIMATION_MS = 160
    FRAME_MS = 12

    def __init__(self, parent, on_toggle=None, state=False, **kw):
        kw.setdefault('takefocus', True)
        super().__init__(
            parent, width=50, height=28,
            bg='#0a0e27', highlightthickness=0, **kw
        )
        self._state = state
        self._position = 1.0 if state else 0.0
        self._on_toggle = on_toggle
        self._animation_id = None
        self._has_focus = False
        self._redraw()
        self.bind('<Button-1>', lambda _event: self._activate())
        self.bind('<space>', lambda _event: self._activate())
        self.bind('<Return>', lambda _event: self._activate())
        self.bind('<FocusIn>', self._on_focus_change)
        self.bind('<FocusOut>', self._on_focus_change)

    def _redraw(self, blur_direction=0):
        self.delete('all')
        W, H = 50, 28
        r = H // 2
        track_col = _blend_color('#3f4660', '#2563eb', self._position)
        thumb_x = (r + 3) + ((W - r - 3) - (r + 3)) * self._position

        # Track
        self.create_oval(0, 0, H, H, fill=track_col, outline='')
        self.create_oval(W - H, 0, W, H, fill=track_col, outline='')
        self.create_rectangle(r, 0, W - r, H, fill=track_col, outline='')

        # Opaque Tk canvases cannot blur pixels, so closely spaced, track-tinted
        # echoes create a restrained motion trail during the slide.
        if blur_direction:
            for offset, blend in ((6, 0.78), (4, 0.64), (2, 0.48)):
                trail_x = thumb_x - blur_direction * offset
                trail_color = _blend_color('#ffffff', track_col, blend)
                self.create_oval(
                    trail_x - r + 5, 5,
                    trail_x + r - 5, H - 5,
                    fill=trail_color, outline=''
                )

        # Thumb
        self.create_oval(
            thumb_x - r + 4, 4,
            thumb_x + r - 4, H - 4,
            fill='white',
            outline='#bfdbfe' if self._has_focus else '',
            width=2 if self._has_focus else 1
        )

    def _activate(self):
        self.focus_set()
        self._set_state(not self._state, animate=True)
        if self._on_toggle:
            self._on_toggle(self._state)

    def _set_state(self, state, animate):
        if self._animation_id is not None:
            self.after_cancel(self._animation_id)
            self._animation_id = None

        self._state = bool(state)
        target = 1.0 if self._state else 0.0
        if not animate or not _system_animations_enabled():
            self._position = target
            self._redraw()
            return

        start = self._position
        direction = 1 if target > start else -1
        started_at = time.perf_counter()

        def draw_frame():
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            progress = min(1.0, elapsed_ms / self.ANIMATION_MS)
            eased = 1 - (1 - progress) ** 3
            self._position = start + (target - start) * eased
            self._redraw(direction if progress < 0.82 else 0)

            if progress < 1.0:
                self._animation_id = self.after(self.FRAME_MS, draw_frame)
            else:
                self._position = target
                self._animation_id = None
                self._redraw()

        draw_frame()

    def _on_focus_change(self, event):
        self._has_focus = event.type == tk.EventType.FocusIn
        self._redraw()

    def set_state(self, state: bool):
        """Set state without triggering callback."""
        self._set_state(state, animate=True)
    
    def get_state(self) -> bool:
        """Get current state."""
        return self._state

    def destroy(self):
        if self._animation_id is not None:
            try:
                self.after_cancel(self._animation_id)
            except tk.TclError:
                pass
            self._animation_id = None
        super().destroy()


class DelaySlider(tk.Frame):
    """Slider widget for delay adjustment with live value display."""

    def __init__(self, parent, min_val=0, max_val=500, value=0, on_change=None, **kw):
        super().__init__(parent, **kw)
        self.configure(bg='#0a0e27')
        
        self._on_change = on_change
        self._min = min_val
        self._max = max_val
        self._value = max(min_val, min(max_val, int(value)))
        
        self._slider = tk.Canvas(
            self, height=28, bg='#0a0e27',
            highlightthickness=0,
            cursor='hand2', takefocus=True
        )
        self._slider.pack(fill='x', padx=4, pady=4)
        self._slider.bind('<Configure>', lambda _event: self._redraw())
        self._slider.bind('<Button-1>', self._set_from_pointer)
        self._slider.bind('<B1-Motion>', self._set_from_pointer)
        self._slider.bind('<Left>', lambda _event: self._step(-1))
        self._slider.bind('<Right>', lambda _event: self._step(1))
        self._slider.bind('<Home>', lambda _event: self.set(self._min))
        self._slider.bind('<End>', lambda _event: self.set(self._max))
        
        # Value display
        self._label = tk.Label(
            self, text=f'{self._value} ms',
            bg='#0a0e27', fg='#94a3b8',
            font=('Segoe UI', 9)
        )
        self._label.pack()

    def _set_from_pointer(self, event):
        self._slider.focus_set()
        width = max(1, self._slider.winfo_width() - 20)
        ratio = max(0.0, min(1.0, (event.x - 10) / width))
        self.set(round(self._min + ratio * (self._max - self._min)))

    def _step(self, amount):
        self.set(self._value + amount)

    def set(self, value):
        value = max(self._min, min(self._max, int(value)))
        if value == self._value:
            return
        self._value = value
        self._label.configure(text=f'{value} ms')
        self._redraw()
        if self._on_change:
            self._on_change(value)

    def _redraw(self):
        canvas = self._slider
        canvas.delete('all')
        width = max(20, canvas.winfo_width())
        ratio = (self._value - self._min) / max(1, self._max - self._min)
        thumb_x = 10 + ratio * (width - 20)

        canvas.create_rectangle(10, 12, width - 10, 16, fill='#263451', outline='')
        canvas.create_rectangle(10, 12, thumb_x, 16, fill='#2563eb', outline='')
        canvas.create_oval(
            thumb_x - 7, 7, thumb_x + 7, 21,
            fill='#60a5fa', outline='#bfdbfe', width=1
        )

    def get(self) -> int:
        return self._value


class VerticalScrollbar(tk.Canvas):
    """Slim dark scrollbar with a draggable thumb."""

    def __init__(self, parent, command, **kw):
        kw.setdefault('takefocus', True)
        super().__init__(
            parent, width=10, bg='#0a0e27',
            highlightthickness=0, cursor='hand2', **kw
        )
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._drag_offset = 0
        self.bind('<Configure>', lambda _event: self._redraw())
        self.bind('<Button-1>', self._press)
        self.bind('<B1-Motion>', self._drag)
        self.bind('<Up>', lambda _event: self._move(-0.05))
        self.bind('<Down>', lambda _event: self._move(0.05))
        self.bind('<Prior>', lambda _event: self._move(-max(0.05, self._last - self._first)))
        self.bind('<Next>', lambda _event: self._move(max(0.05, self._last - self._first)))
        self.bind('<Home>', lambda _event: self._command(0.0))
        self.bind('<End>', lambda _event: self._command(1.0))
        self.bind('<FocusIn>', lambda _event: self._redraw())
        self.bind('<FocusOut>', lambda _event: self._redraw())

    def set(self, first, last):
        self._first = float(first)
        self._last = float(last)
        self._redraw()

    def _thumb_bounds(self):
        height = max(1, self.winfo_height())
        top = self._first * height
        bottom = self._last * height
        if bottom - top < 28:
            center = (top + bottom) / 2
            top = max(0, min(height - 28, center - 14))
            bottom = top + 28
        return top, bottom

    def _press(self, event):
        top, bottom = self._thumb_bounds()
        if top <= event.y <= bottom:
            self._drag_offset = event.y - top
        else:
            visible = self._last - self._first
            self._command(max(0.0, event.y / max(1, self.winfo_height()) - visible / 2))
            top, _ = self._thumb_bounds()
            self._drag_offset = event.y - top

    def _drag(self, event):
        height = max(1, self.winfo_height())
        self._command(max(0.0, min(1.0, (event.y - self._drag_offset) / height)))

    def _move(self, amount):
        self._command(max(0.0, min(1.0, self._first + amount)))

    def _redraw(self):
        self.delete('all')
        if self._first <= 0.0 and self._last >= 1.0:
            return
        top, bottom = self._thumb_bounds()
        focused = self.focus_get() is self
        self.create_rectangle(
            3, top, 8, bottom,
            fill='#60a5fa' if focused else '#334155',
            outline='',
        )


class SpreadGraph(tk.Canvas):
    """Real-time latency spread bar graph."""

    MAX_SAMPLES = 60

    def __init__(self, parent, **kw):
        # Original line hardcoded height=80 while callers may also pass height,
        # which can cause: TypeError: got multiple values for keyword 'height'.
        # super().__init__(parent, bg='#0a0e27', highlightthickness=0, height=80, **kw)
        height = kw.pop('height', 80)
        super().__init__(
            parent, bg='#0a0e27', highlightthickness=0,
            height=height, **kw
        )
        self._data = collections.deque(maxlen=self.MAX_SAMPLES)
        self.pack_propagate(False)

    def push(self, value: float):
        """Add a new latency sample."""
        self._data.append(value)
        self._redraw()

    def clear(self):
        """Clear all data."""
        self._data.clear()
        self._redraw()

    def _redraw(self):
        self.delete('all')
        W = int(self['width'])
        H = int(self['height'])

        if not self._data:
            return

        mx = max(self._data) or 1
        bar_w = W / self.MAX_SAMPLES

        for i, v in enumerate(self._data):
            h = int((v / mx) * (H - 20))
            x0 = i * bar_w + 1
            x1 = x0 + bar_w - 2
            y0 = H - h - 10
            y1 = H - 10

            # Color gradient: green → yellow → red
            if v < 20:
                color = '#10b981'  # green
            elif v < 50:
                color = '#f59e0b'  # amber
            else:
                color = '#ef4444'  # red

            self.create_rectangle(x0, y0, x1, y1, fill=color, outline='')


class StatDisplay(tk.Frame):
    """Label + value display for stats."""

    def __init__(self, parent, label: str, **kw):
        super().__init__(parent, bg='#0a0e27', **kw)
        
        tk.Label(
            self, text=label,
            bg='#0a0e27', fg='#64748b',
            font=('Segoe UI', 9)
        ).pack(side='left', anchor='w')
        
        self._value = tk.Label(
            self, text='—',
            bg='#0a0e27', fg='#e2e8f0',
            font=('Segoe UI', 11, 'bold')
        )
        self._value.pack(side='right', anchor='e')

    def set_value(self, text: str):
        """Update the displayed value."""
        self._value.configure(text=text)


class Section(tk.Frame):
    """Section header with title."""

    def __init__(self, parent, title: str, **kw):
        super().__init__(parent, bg='#0a0e27', **kw)
        
        tk.Label(
            self, text=title.upper(),
            bg='#0a0e27', fg='#6366f1',
            font=('Segoe UI', 8, 'bold')
        ).pack(anchor='w', pady=(8, 4))


class Card(tk.Frame):
    """Content card with subtle border."""

    def __init__(self, parent, **kw):
        super().__init__(
            parent, bg='#0f172a',
            relief='solid', bd=1,
            highlightcolor='#1e293b',
            **kw
        )


class Button(tk.Button):
    """Styled action button."""

    def __init__(self, parent, text: str, primary=False, **kw):
        bg = '#2563eb' if primary else '#3f4660'
        fg = 'white'
        hover_bg = '#1d4ed8' if primary else '#4a5578'
        
        super().__init__(
            parent, text=text,
            bg=bg, fg=fg,
            activebackground=hover_bg, activeforeground='white',
            relief='flat', padx=16, pady=8,
            font=('Segoe UI', 10),
            cursor='hand2', **kw
        )


class StatusIndicator(tk.Canvas):
    """Live status dot (green when active, gray when inactive)."""

    def __init__(self, parent, **kw):
        super().__init__(
            parent, width=12, height=12,
            bg='#0a0e27', highlightthickness=0, **kw
        )
        self._active = False
        self._redraw()

    def set_active(self, active: bool):
        """Update status."""
        self._active = active
        self._redraw()

    def _redraw(self):
        self.delete('all')
        color = '#10b981' if self._active else '#4b5563'
        self.create_oval(1, 1, 11, 11, fill=color, outline='')

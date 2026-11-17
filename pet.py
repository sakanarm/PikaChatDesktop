"""
The Pika mascot: a frameless, always-on-top, transparent Tk window that plays the
pre-rendered sprites in assets/pika/<size>/<pose>.png (made by sprites.py at build time,
so no image library is needed at runtime).

Animation priority:
    drag > reaction (wave / happy / sad / surprised) > talking (TTS playing)
    > activity (hearing / thinking / searching / answering) > idle life
Idle life: blink, glance around, walk along the bottom of the screen, fall asleep
after a while without attention.
"""
import ctypes
import random
import time
import tkinter as tk

from config import resource_path

TRANSPARENT = "#010101"
SIZES = (110, 150, 200)
POSES = ("idle", "blink", "look_l", "look_r", "curious", "walk1", "walk2", "wave1", "wave2",
         "listen1", "listen2", "think1", "think2", "think3", "search1", "search2",
         "talk1", "talk2", "talk3", "explain1", "explain2", "happy1", "happy2",
         "sleep1", "sleep2", "sad", "surprised", "drag")
FONT = "Leelawadee UI"
ICON_FONT = "Segoe UI Emoji"
BLUE, BLUE_DARK, BLUE_PALE = "#2563EB", "#1E3A8A", "#EFF6FF"
RED, RED_DARK = "#EF4444", "#B91C1C"

ACTIVITY = {
    "hearing": (("listen1", "listen2"), 0.35),
    "thinking": (("think1", "think2", "think3"), 0.4),
    "searching": (("search1", "search2"), 0.35),
    "answering": (("explain1", "talk1", "explain2", "talk3"), 0.25),
}
REACTIONS = {   # frames, seconds per frame, duration
    "wave": (("wave1", "wave2"), 0.25, 1.5),
    "happy": (("happy1", "happy2"), 0.22, 1.3),
    "sad": (("sad",), 1.0, 2.2),
    "surprised": (("surprised",), 1.0, 0.7),
}
SLEEP_AFTER_S = 90
TICK_MS = 50


# ─── screen geometry (Windows work area, per monitor) ─────────────
class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT), ("rcWork", _RECT),
                ("dwFlags", ctypes.c_ulong)]


def work_area(root, x=None, y=None):
    """(left, top, right, bottom) of the usable desktop (minus taskbar) at point x,y."""
    try:
        user32 = ctypes.windll.user32
        if x is not None:
            user32.MonitorFromPoint.argtypes = [_POINT, ctypes.c_ulong]
            user32.MonitorFromPoint.restype = ctypes.c_void_p
            user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
            hmon = user32.MonitorFromPoint(_POINT(int(x), int(y)), 2)   # nearest monitor
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                r = mi.rcWork
                return r.left, r.top, r.right, r.bottom
        r = _RECT()
        if user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):   # SPI_GETWORKAREA
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def ui_scale(root):
    return max(1.0, root.winfo_fpixels("1i") / 96.0)


def auto_size(root, setting=0):
    try:
        setting = int(setting or 0)
    except (TypeError, ValueError):
        setting = 0
    if setting in SIZES:
        return setting
    target = 150 * ui_scale(root)
    return min(SIZES, key=lambda h: abs(h - target))


def rounded_rect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def _frameless(win):
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=TRANSPARENT)
    win.attributes("-transparentcolor", TRANSPARENT)


# ─── speech bubble ────────────────────────────────────────────────
class Bubble:
    def __init__(self, pet):
        self.pet = pet
        s = pet.scale
        self.win = tk.Toplevel(pet.root)
        self.win.withdraw()
        _frameless(self.win)
        self.cv = tk.Canvas(self.win, bg=TRANSPARENT, highlightthickness=0, bd=0, cursor="hand2")
        self.cv.pack()
        self.cv.bind("<Button-1>", self._click)
        self.font = (FONT, 10)
        self.maxw = int(230 * s)
        self.pad, self.tail, self.radius = int(10 * s), int(10 * s), int(12 * s)
        self.line = max(1, round(1.5 * s))
        self.visible = False
        self.text = ""
        self.on_click = None
        self._job = None
        self._size = (0, 0)
        self._below = None

    def show(self, text, seconds=None):
        """seconds=None: auto from length; 0: stay until replaced/hidden."""
        text = (text or "").strip()
        if not text:
            return self.hide()
        if seconds is None:
            seconds = min(14.0, 2.5 + len(text) * 0.06)
        if self._job:
            self.pet.root.after_cancel(self._job)
            self._job = None
        if seconds:
            self._job = self.pet.root.after(int(seconds * 1000), self.hide)
        if text != self.text or not self.visible:
            self.text = text
            self._below = None
            self.place()
        if not self.visible:
            self.visible = True
            self.win.deiconify()
            self.win.lift()

    def hide(self):
        if self._job:
            self.pet.root.after_cancel(self._job)
            self._job = None
        if self.visible:
            self.visible = False
            self.win.withdraw()
        self.text = ""

    def _click(self, _e):
        self.hide()
        if self.on_click:
            self.on_click()

    def _measure(self):
        tid = self.cv.create_text(0, 0, text=self.text, font=self.font, width=self.maxw, anchor="nw")
        x1, y1, x2, y2 = self.cv.bbox(tid)
        self.cv.delete(tid)
        w = max(x2 - x1, int(40 * self.pet.scale)) + 2 * self.pad
        h = (y2 - y1) + 2 * self.pad
        return w, h

    def place(self):
        """Position above the pet's head (or below if there is no room) and redraw."""
        if not self.text:
            return
        pet = self.pet
        bw, bh = self._measure()
        total_h = bh + self.tail
        cx = pet.x + pet.w // 2
        head_top = pet.y + pet.pad
        l, t, r, b = work_area(pet.root, cx, head_top)
        below = head_top - total_h + int(6 * pet.scale) < t
        y = (pet.y + pet.pad + pet.h - int(4 * pet.scale)) if below else (head_top - total_h + int(6 * pet.scale))
        x = min(max(cx - bw // 2, l + 2), r - bw - 2)
        if (bw, bh) != self._size or below != self._below or getattr(self, "_drawn", "") != self.text \
                or abs(getattr(self, "_tx", 0) - (cx - x)) > 1:
            self._draw(bw, bh, below, cx - x)
        self.win.geometry(f"{bw + 2}x{total_h + 2}+{int(x)}+{int(y)}")

    def _draw(self, bw, bh, below, tail_x):
        cv, tl, p = self.cv, self.tail, self.pad
        cv.delete("all")
        cv.configure(width=bw + 2, height=bh + tl + 2)
        top = 1 + (tl if below else 0)
        rounded_rect(cv, 1, top, bw, top + bh - 1, self.radius, fill=BLUE_PALE, outline=BLUE,
                     width=self.line)
        tx = min(max(tail_x, self.radius + tl), bw - self.radius - tl)
        half = int(tl * 0.8)
        if below:
            pts = (tx - half, top + self.line, tx, 1, tx + half, top + self.line)
            seam_y = top + self.line
        else:
            base = top + bh - 1 - self.line
            pts = (tx - half, base, tx, top + bh + tl - 1, tx + half, base)
            seam_y = base
        cv.create_polygon(pts, fill=BLUE_PALE, outline=BLUE, width=self.line)
        cv.create_line(tx - half + self.line + 1, seam_y, tx + half - self.line, seam_y,
                       fill=BLUE_PALE, width=self.line + 2)
        cv.create_text(1 + p, top + p, text=self.text, font=self.font, fill=BLUE_DARK,
                       width=self.maxw, anchor="nw")
        self._size, self._below, self._drawn, self._tx = (bw, bh), below, self.text, tail_x


# ─── hover toolbar (chat / mic / settings) ────────────────────────
class Toolbar:
    ITEMS = (("chat", "💬", "แชท"), ("mic", "🎤", "คุยด้วยเสียง"), ("settings", "⚙", "ตั้งค่า"))

    def __init__(self, pet, actions):
        self.pet = pet
        s = pet.scale
        self.win = tk.Toplevel(pet.root)
        self.win.withdraw()
        _frameless(self.win)
        self.d, gap = int(30 * s), int(6 * s)
        self.line = max(1, round(1.5 * s))
        n = len(self.ITEMS)
        self.cv = tk.Canvas(self.win, width=self.d + 4, height=n * self.d + (n - 1) * gap + 4,
                            bg=TRANSPARENT, highlightthickness=0, bd=0, cursor="hand2")
        self.cv.pack()
        self.w, self.h = self.d + 4, n * self.d + (n - 1) * gap + 4
        self.buttons = {}
        for i, (key, icon, _tip) in enumerate(self.ITEMS):
            y = 2 + i * (self.d + gap)
            oval = self.cv.create_oval(2, y, 2 + self.d, y + self.d, fill="white", outline=BLUE,
                                       width=self.line)
            txt = self.cv.create_text(2 + self.d / 2, y + self.d / 2, text=icon, fill=BLUE,
                                      font=(ICON_FONT, 11))
            self.buttons[key] = (oval, txt)
            for item in (oval, txt):
                self.cv.tag_bind(item, "<ButtonRelease-1>", lambda e, k=key: actions[k]())
                self.cv.tag_bind(item, "<Enter>", lambda e, k=key: self._hover(k, True))
                self.cv.tag_bind(item, "<Leave>", lambda e, k=key: self._hover(k, False))
        self.cv.bind("<Enter>", pet._enter)
        self.cv.bind("<Leave>", pet._leave)
        self.visible = False
        self.mic_on = False

    def _colors(self, key, hover):
        if key == "mic" and self.mic_on:
            return (RED_DARK if hover else RED), RED_DARK, "white"
        return ("#DBEAFE" if hover else "white"), BLUE, BLUE

    def _hover(self, key, on):
        fill, outline, fg = self._colors(key, on)
        oval, txt = self.buttons[key]
        self.cv.itemconfigure(oval, fill=fill, outline=outline)
        self.cv.itemconfigure(txt, fill=fg)

    def set_mic(self, on):
        self.mic_on = on
        self._hover("mic", False)

    def show(self):
        self.place()
        if not self.visible:
            self.visible = True
            self.win.deiconify()
            self.win.lift()

    def hide(self):
        if self.visible:
            self.visible = False
            self.win.withdraw()

    def place(self):
        pet = self.pet
        l, t, r, b = work_area(pet.root, pet.x + pet.w // 2, pet.y + pet.h // 2)
        x = pet.x + pet.w - int(4 * pet.scale)
        if x + self.w > r:
            x = pet.x - self.w + int(4 * pet.scale)
        y = pet.y + pet.pad + int(pet.h * 0.22)
        y = min(max(y, t), b - self.h)
        self.win.geometry(f"{self.w}x{self.h}+{int(x)}+{int(y)}")


# ─── the pet ──────────────────────────────────────────────────────
class PetWindow:
    """app must provide: is_talking(), mic_on, chat_visible(), on_pet_click(), toggle_chat(),
    toggle_mic(), open_settings(), set_walk(bool), show_chat(), quit()."""

    def __init__(self, root, app, size=0, walk=True):
        self.root, self.app = root, app
        self.scale = ui_scale(root)
        _frameless(root)
        self.pad = int(10 * self.scale)           # headroom for hops
        self.label = tk.Label(root, bd=0, highlightthickness=0, bg=TRANSPARENT, cursor="hand2")
        self.frames, self.size = {}, None
        self.w = self.h = 0
        self.x = self.y = 0
        self.walk_enabled = walk
        self.minimized = False
        self.head = tk.PhotoImage(file=resource_path("assets", "pika", "head48.png"))

        self.activity = None
        self.reaction = None
        self.dragging = False
        self.sleeping = False
        now = time.time()
        self.last_touch = now
        self._last_talk = 0.0
        self.next_blink = now + 2
        self.next_glance = now + 7
        self.next_walk = now + 10
        self.blink_until = self.glance_until = self.walk_until = 0.0
        self.glance_pose, self.walk_dir = "look_l", -1
        self._pose, self._bob = None, None
        self._press_at = None
        self._click_job = None
        self._after_double = False
        self._hide_bar_job = None

        self.set_size(auto_size(root, size), initial=True)
        self.bubble = Bubble(self)
        self.bubble.on_click = app.show_chat
        self.toolbar = Toolbar(self, {"chat": app.toggle_chat, "mic": app.toggle_mic,
                                      "settings": app.open_settings})

        lbl = self.label
        lbl.bind("<ButtonPress-1>", self._press)
        lbl.bind("<B1-Motion>", self._motion)
        lbl.bind("<ButtonRelease-1>", self._release)
        lbl.bind("<Double-Button-1>", self._double)
        lbl.bind("<Button-3>", self._menu)
        lbl.bind("<Enter>", self._enter)
        lbl.bind("<Leave>", self._leave)
        root.after(TICK_MS, self._tick)

    # ── size / geometry ───────────────────────────────────────────
    def set_size(self, height, initial=False):
        height = auto_size(self.root, height)
        if height == self.size:
            return
        frames = {n: tk.PhotoImage(file=resource_path("assets", "pika", str(height), n + ".png"))
                  for n in POSES}
        old_bottom, old_cx = self.y + self.pad + self.h, self.x + self.w // 2
        self.frames, self.size = frames, height
        self.w, self.h = frames["idle"].width(), frames["idle"].height()
        if initial:
            l, t, r, b = work_area(self.root)
            self.x = r - self.w - int(70 * self.scale)
            self.y = b - self.h - self.pad
        else:
            self.x, self.y = old_cx - self.w // 2, old_bottom - self.h - self.pad
        self._pose = self._bob = None
        if not self.minimized:
            self._apply_geometry()
            self._show_frame("idle", 0)

    def _apply_geometry(self):
        if self.minimized:
            hw = self.head.width()
            self.root.geometry(f"{hw}x{hw}+{int(self.x + (self.w - hw) // 2)}"
                               f"+{int(self.y + self.pad + self.h - hw)}")
        else:
            self.root.geometry(f"{self.w}x{self.h + self.pad}+{int(self.x)}+{int(self.y)}")

    def _clamp(self):
        l, t, r, b = work_area(self.root, self.x + self.w // 2, self.y + self.pad + self.h // 2)
        self.x = min(max(self.x, l - self.w // 4), r - self.w + self.w // 4)
        self.y = min(max(self.y, t - self.pad), b - self.h - self.pad)

    def _follow(self):
        if self.bubble.visible:
            self.bubble.place()
        if self.toolbar.visible:
            self.toolbar.place()

    def screen_rect(self):
        """(x, y, w, h) of the mascot on screen - used to place the chat window."""
        return self.x, self.y + self.pad, self.w, self.h

    def _show_frame(self, pose, bob):
        if pose != self._pose:
            self.label.configure(image=self.frames[pose])
            self._pose = pose
        if bob != self._bob:
            self.label.place(x=0, y=self.pad + bob)
            self._bob = bob

    # ── public API for the app ────────────────────────────────────
    def say(self, text, seconds=None):
        if self.sleeping:
            self.touch()
        self.bubble.show(text, seconds)

    def hush(self):
        self.bubble.hide()

    def set_activity(self, name):
        self.activity = name if name in ACTIVITY else None
        if self.activity:
            self.walk_until = 0
            self.touch()

    def react(self, kind):
        if kind in REACTIONS:
            seq, step, dur = REACTIONS[kind]
            now = time.time()
            self.reaction = {"seq": seq, "step": step, "t0": now, "until": now + dur}
            self.walk_until = 0
            self.sleeping = False
            self.last_touch = now

    def touch(self):
        """Any interaction: resets the sleep timer and wakes the pet up."""
        self.last_touch = time.time()
        if self.sleeping:
            self.sleeping = False
            self.react("surprised")

    def set_mic(self, on):
        self.toolbar.set_mic(on)
        if on:
            self.toolbar.show()
            self.touch()
        elif not self._hovering():
            self._schedule_hide_bar()

    def set_walk(self, on):
        self.walk_enabled = on
        if not on:
            self.walk_until = 0

    def toggle_minimize(self):
        self.minimized = not self.minimized
        self.walk_until = 0
        if self.minimized:
            self.label.configure(image=self.head)
            self.label.place(x=0, y=0)
            self._pose = self._bob = None
            self.toolbar.hide()
            self.bubble.hide()
        else:
            self._pose = self._bob = None
            self._show_frame("idle", 0)
            self.react("wave")
        self._apply_geometry()

    # ── animation ─────────────────────────────────────────────────
    def _tick(self):
        try:
            if not self.minimized:
                moved = self._update(time.time())
                if moved:
                    self._apply_geometry()
                    self._follow()
        except Exception as ex:          # never let the animation loop die
            print(f"[pet] tick error: {ex}")
        self.root.after(TICK_MS, self._tick)

    def _update(self, now):
        pose, bob, moved = self._choose(now)
        self._show_frame(pose, bob)
        return moved

    def _choose(self, now):
        if self.dragging:
            return "drag", 0, False
        r = self.reaction
        if r and now < r["until"]:
            pose = r["seq"][int((now - r["t0"]) / r["step"]) % len(r["seq"])]
            return pose, (-int(7 * self.scale) if pose == "happy1" else 0), False
        self.reaction = None
        if self.app.is_talking():
            self._last_talk = now
            self.last_touch = now
        if now - self._last_talk < 0.35:
            self.sleeping = False
            if now % 2.8 > 1.8:         # a hand gesture now and then
                return ("explain1", "explain2")[int(now / 0.25) % 2], 0, False
            return ("talk1", "talk2", "talk3", "talk2")[int(now / 0.12) % 4], 0, False
        if self.activity:
            seq, step = ACTIVITY[self.activity]
            return seq[int(now / step) % len(seq)], 0, False
        return self._idle_life(now)

    def _idle_life(self, now):
        quiet = not self.app.mic_on and not self.app.chat_visible() and not self.toolbar.visible
        if not self.sleeping and quiet and now - self.last_touch > SLEEP_AFTER_S:
            self.sleeping = True
            self.walk_until = 0
            self.bubble.hide()
        if self.sleeping:
            return ("sleep1", "sleep2")[int(now / 0.9) % 2], 0, False
        if now < self.walk_until:
            if not quiet:
                self.walk_until = 0
            else:
                return self._walk_step(now)
        if now < self.glance_until:
            return self.glance_pose, 0, False
        if now < self.blink_until:
            return "blink", 0, False
        if now >= self.next_blink:
            self.blink_until = now + 0.15
            self.next_blink = now + random.uniform(2.5, 5.0)
            return "blink", 0, False
        if now >= self.next_glance:
            self.glance_pose = random.choice(("look_l", "look_r", "curious", "look_l", "look_r"))
            self.glance_until = now + random.uniform(1.0, 2.2)
            self.next_glance = now + random.uniform(6.0, 12.0)
            return self.glance_pose, 0, False
        if now >= self.next_walk:
            self.next_walk = now + random.uniform(14.0, 28.0)
            if self.walk_enabled and quiet:
                self.walk_until = now + random.uniform(2.5, 6.0)
                self.walk_dir = random.choice((-1, 1))     # bounces off the screen edges
        return "idle", 0, False

    def _walk_step(self, now):
        s = self.scale
        i = int(now / 0.18) % 2
        l, t, r, b = work_area(self.root, self.x + self.w // 2, self.y + self.h)
        nx = self.x + self.walk_dir * max(1, round(1.6 * s))
        if nx < l or nx + self.w > r:
            self.walk_dir = -self.walk_dir
        else:
            self.x = nx
        return ("walk1", "walk2")[i], (-max(1, int(2 * s)) if i else 0), True

    # ── mouse ─────────────────────────────────────────────────────
    def _hovering(self):
        try:
            w = self.root.winfo_containing(*self.root.winfo_pointerxy())
        except Exception:
            return False
        return w is not None and (w is self.label or w is self.toolbar.cv)

    def _enter(self, _e=None):
        if self._hide_bar_job:
            self.root.after_cancel(self._hide_bar_job)
            self._hide_bar_job = None
        if not self.minimized and not self.dragging:
            self.toolbar.show()
            self.walk_until = 0

    def _leave(self, _e=None):
        self._schedule_hide_bar()

    def _schedule_hide_bar(self):
        if self._hide_bar_job:
            self.root.after_cancel(self._hide_bar_job)
        self._hide_bar_job = self.root.after(1200, self._maybe_hide_bar)

    def _maybe_hide_bar(self):
        self._hide_bar_job = None
        if self.app.mic_on and not self.minimized:
            return
        if self._hovering():
            return self._schedule_hide_bar()
        self.toolbar.hide()

    def _press(self, e):
        self._press_at = (e.x_root, e.y_root, self.x, self.y)

    def _motion(self, e):
        if not self._press_at:
            return
        sx, sy, wx, wy = self._press_at
        dx, dy = e.x_root - sx, e.y_root - sy
        if not self.dragging and abs(dx) + abs(dy) < 5:
            return
        if not self.dragging:
            self.dragging = True
            self.walk_until = 0
            self.sleeping = False
            self.toolbar.hide()
        self.x, self.y = wx + dx, wy + dy
        self._apply_geometry()
        self._follow()

    def _release(self, _e):
        self._press_at = None
        if self.dragging:
            self.dragging = False
            self._clamp()
            self._apply_geometry()
            self._follow()
            self.react("surprised")
            return
        if self._after_double:
            self._after_double = False
            return
        if self._click_job:
            self.root.after_cancel(self._click_job)
        self._click_job = self.root.after(260, self._single_click)

    def _single_click(self):
        self._click_job = None
        self.touch()
        if self.minimized:
            self.toggle_minimize()
            return
        self.app.on_pet_click()

    def _double(self, _e):
        if self._click_job:
            self.root.after_cancel(self._click_job)
            self._click_job = None
        self._after_double = True
        self.toggle_minimize()

    def _menu(self, e):
        self.touch()
        app = self.app
        m = tk.Menu(self.root, tearoff=0, font=(FONT, 10))
        m.add_command(label="ซ่อนแชท" if app.chat_visible() else "เปิดแชท", command=app.toggle_chat)
        m.add_command(label="หยุดฟังเสียง" if app.mic_on else "คุยด้วยเสียง", command=app.toggle_mic)
        m.add_command(label="ตั้งค่า…", command=app.open_settings)
        m.add_separator()
        walk = tk.BooleanVar(value=self.walk_enabled)
        m.add_checkbutton(label="เดินเล่น", variable=walk,
                          command=lambda: app.set_walk(bool(walk.get())))
        m.add_command(label="แสดงตัวเต็ม" if self.minimized else "ย่อเป็นไอคอน",
                      command=self.toggle_minimize)
        m.add_separator()
        m.add_command(label="ออกจากโปรแกรม", command=app.quit)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

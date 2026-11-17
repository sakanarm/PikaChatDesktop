"""
Mini chat window next to the mascot. Closing it only hides it; Pika keeps running.
Answers stream in as plain text and are re-rendered as light markdown when complete
(headings, bold, bullets, code, links), followed by the Pika sources.
"""
import re
import tkinter as tk
import webbrowser
from tkinter import ttk

from config import APP_TITLE, resource_path
from pika_client import clean_title

FONT = "Leelawadee UI"
ICON_FONT = "Segoe UI Emoji"
BLUE, BLUE_DEEP, BLUE_DARK, BLUE_SOFT = "#2563EB", "#1D4ED8", "#1E3A8A", "#DBEAFE"
RED, RED_DARK = "#EF4444", "#B91C1C"
BG, INK, MUTED, LINE = "#F8FAFC", "#0F172A", "#64748B", "#E2E8F0"

STATUS = {
    "hearing": "กำลังฟัง…",
    "thinking": "กำลังคิด…",
    "searching": "กำลังค้นในคลังความรู้ Pika…",
    "answering": "กำลังตอบ…",
}
PLACEHOLDER = "พิมพ์คำถาม แล้วกด Enter…"

_INLINE = re.compile(r"(\*\*[^*\n]+?\*\*|__[^_\n]+?__|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\))")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*•+]\s+(.*)$")
_NUMBER = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


class ChatWindow:
    def __init__(self, app, root, scale=1.0):
        self.app = app
        self.scale = scale
        self.visible = False
        self._open = False          # a Pika answer is streaming into the log
        self._raw = ""
        self._typing = False
        self._sources = []
        self._notices = []
        self._links = 0
        self._history = []
        self._hist_i = 0
        self._placeholder_on = False

        w = self.win = tk.Toplevel(root)
        w.withdraw()
        w.title(f"Pika — {APP_TITLE}")
        w.configure(bg=BG)
        w.attributes("-toolwindow", True)
        w.protocol("WM_DELETE_WINDOW", self.hide)
        w.minsize(int(280 * scale), int(300 * scale))
        w.bind("<Escape>", lambda e: self.hide())

        # header
        hdr = tk.Frame(w, bg=BLUE)
        hdr.pack(fill="x")
        self.icon = tk.PhotoImage(file=resource_path("assets", "pika", "head48.png"))
        tk.Label(hdr, image=self.icon, bg=BLUE, bd=0).pack(side="left", padx=(8, 6), pady=6)
        titles = tk.Frame(hdr, bg=BLUE)
        titles.pack(side="left", fill="y", pady=6)
        tk.Label(titles, text="Pika", font=(FONT, 12, "bold"), fg="white", bg=BLUE).pack(anchor="w")
        self.status = tk.Label(titles, text="", font=(FONT, 9), fg=BLUE_SOFT, bg=BLUE, anchor="w")
        self.status.pack(anchor="w")
        self.mic_btn = self._head_button(hdr, "🎤", app.toggle_mic)
        self._head_button(hdr, "⚙", app.open_settings)
        self._head_button(hdr, "🗑", self._clear)
        self.mic_on = False

        # input (packed before the log so it never gets squeezed out)
        foot = tk.Frame(w, bg="white", highlightbackground=LINE, highlightthickness=1)
        foot.pack(side="bottom", fill="x")
        self.entry = tk.Entry(foot, font=(FONT, 10), bd=0, relief="flat", bg="white", fg=INK,
                              insertbackground=INK)
        self.entry.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=8, ipady=3)
        self.send_btn = tk.Button(foot, text="ส่ง", font=(FONT, 10, "bold"), bg=BLUE, fg="white",
                                  activebackground=BLUE_DEEP, activeforeground="white", bd=0,
                                  relief="flat", padx=14, pady=2, cursor="hand2",
                                  command=self._send_or_stop)
        self.send_btn.pack(side="right", padx=(0, 8), pady=6)
        self.entry.bind("<Return>", lambda e: self._send())
        self.entry.bind("<Up>", lambda e: self._recall(-1))
        self.entry.bind("<Down>", lambda e: self._recall(1))
        self.entry.bind("<FocusIn>", lambda e: self._placeholder(False))
        self.entry.bind("<FocusOut>", lambda e: self._placeholder(True))
        self._busy = False

        # log
        body = tk.Frame(w, bg=BG)
        body.pack(fill="both", expand=True)
        t = self.text = tk.Text(body, wrap="word", bg=BG, fg=INK, font=(FONT, 10), bd=0,
                                padx=10, pady=8, highlightthickness=0, spacing1=1, spacing3=1)
        sb = ttk.Scrollbar(body, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        t.tag_configure("you_name", font=(FONT, 8), foreground=MUTED, justify="right", spacing1=10)
        t.tag_configure("you", foreground=BLUE_DARK, justify="right", lmargin1=50, lmargin2=50)
        t.tag_configure("bot_name", font=(FONT, 9, "bold"), foreground=BLUE, spacing1=10)
        t.tag_configure("bot", lmargin1=2, lmargin2=2, rmargin=16)
        t.tag_configure("typing", foreground=MUTED, font=(FONT, 10, "italic"))
        t.tag_configure("b", font=(FONT, 10, "bold"))
        t.tag_configure("h", font=(FONT, 11, "bold"), spacing1=4)
        t.tag_configure("li", lmargin1=8, lmargin2=22)
        t.tag_configure("quote", foreground="#475569", lmargin1=12, lmargin2=12)
        t.tag_configure("code", font=("Consolas", 9), background="#EEF2F7")
        t.tag_configure("src_head", font=(FONT, 8, "bold"), foreground=MUTED, spacing1=6)
        t.tag_configure("src", font=(FONT, 9), foreground="#475569", lmargin1=8, lmargin2=20)
        t.tag_configure("src_path", font=(FONT, 8), foreground="#94A3B8")
        t.tag_configure("notice", font=(FONT, 9, "italic"), foreground=MUTED, justify="center",
                        spacing1=6, spacing3=2)
        t.tag_configure("error", foreground=RED_DARK)
        t.tag_configure("link", foreground=BLUE, underline=True)
        t.configure(state="disabled")
        t.bind("<Button-3>", self._text_menu)

        self._placeholder(True)
        self.set_status(None)
        self.add_bot_message("สวัสดี! เราคือ Pika 👋 ถามอะไรเกี่ยวกับคลังความรู้ของคุณได้เลย "
                             "พิมพ์ด้านล่าง หรือกด 🎤 เพื่อคุยด้วยเสียง")

    # ── widgets helpers ───────────────────────────────────────────
    def _head_button(self, parent, icon, command):
        b = tk.Label(parent, text=icon, font=(ICON_FONT, 12), fg="white", bg=BLUE, padx=6,
                     cursor="hand2")
        b.bind("<Button-1>", lambda e: command())
        b.bind("<Enter>", lambda e: b.configure(bg=BLUE_DEEP if b is not self.mic_btn or not self.mic_on
                                                else RED_DARK))
        b.bind("<Leave>", lambda e: b.configure(bg=RED if b is self.mic_btn and self.mic_on else BLUE))
        b.pack(side="right", padx=1)
        return b

    def _placeholder(self, show):
        if show and not self.entry.get():
            self.entry.insert(0, PLACEHOLDER)
            self.entry.configure(fg="#94A3B8")
            self._placeholder_on = True
        elif not show and self._placeholder_on:
            self.entry.delete(0, "end")
            self.entry.configure(fg=INK)
            self._placeholder_on = False

    def _ins(self, s, tags=()):
        self.text.configure(state="normal")
        self.text.insert("end", s, tags)
        self.text.configure(state="disabled")

    def _scroll(self):
        self.text.see("end")

    def _text_menu(self, e):
        m = tk.Menu(self.win, tearoff=0, font=(FONT, 10))
        m.add_command(label="คัดลอก", command=lambda: self.text.event_generate("<<Copy>>"))
        m.add_command(label="คัดลอกทั้งหมด", command=self._copy_all)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _copy_all(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.text.get("1.0", "end-1c"))

    # ── show / hide ───────────────────────────────────────────────
    def show(self, near=None):
        if not self.visible:
            self._place(near)
            self.win.deiconify()
            self.visible = True
        self.win.lift()
        self.win.after(50, self._focus)

    def _focus(self):
        try:
            self.win.focus_force()
            self.entry.focus_set()
        except tk.TclError:
            pass

    def hide(self):
        if self.visible:
            self.visible = False
            self.win.withdraw()
            self.app.on_chat_hidden()

    def toggle(self, near=None):
        if self.visible:
            self.hide()
        else:
            self.show(near)

    def _place(self, near):
        s = self.scale
        cw, ch = int(360 * s), int(500 * s)
        if near is None:
            self.win.geometry(f"{cw}x{ch}")
            return
        from pet import work_area
        px, py, pw, ph = near
        l, t, r, b = work_area(self.win, px + pw // 2, py + ph // 2)
        ch = min(ch, b - t - 20)
        x = px - cw - int(16 * s)
        if x < l + 4:
            x = px + pw + int(16 * s)
        x = min(max(x, l + 4), r - cw - 4)
        y = min(max(py + ph - ch, t + 4), b - ch - 4)
        self.win.geometry(f"{cw}x{ch}+{int(x)}+{int(y)}")

    def set_topmost(self, on):
        self.win.attributes("-topmost", bool(on))

    # ── status / buttons ──────────────────────────────────────────
    def set_status(self, activity, extra=None):
        if extra:
            text = extra
        elif activity in STATUS:
            text = STATUS[activity]
        else:
            text = self.app.ready_text()
        self.status.configure(text=text)

    def set_mic(self, on):
        self.mic_on = on
        self.mic_btn.configure(bg=RED if on else BLUE)

    def set_busy(self, busy):
        self._busy = busy
        if busy:
            self.send_btn.configure(text="หยุด", bg=RED, activebackground=RED_DARK)
        else:
            self.send_btn.configure(text="ส่ง", bg=BLUE, activebackground=BLUE_DEEP)

    # ── input ─────────────────────────────────────────────────────
    def _send_or_stop(self):
        if self._busy:
            self.app.interrupt()
        else:
            self._send()

    def _send(self):
        if self._placeholder_on:
            return "break"
        q = self.entry.get().strip()
        if not q:
            return "break"
        self.entry.delete(0, "end")
        if not self._history or self._history[-1] != q:
            self._history.append(q)
        self._hist_i = len(self._history)
        self.app.submit(q, "chat")
        return "break"

    def _recall(self, step):
        if not self._history:
            return "break"
        self._placeholder(False)
        self._hist_i = min(max(self._hist_i + step, 0), len(self._history))
        self.entry.delete(0, "end")
        if self._hist_i < len(self._history):
            self.entry.insert(0, self._history[self._hist_i])
        return "break"

    def _clear(self):
        if self._open:
            self.app.interrupt()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.app.clear_history()
        self.add_notice("เริ่มบทสนทนาใหม่แล้ว")

    # ── log ───────────────────────────────────────────────────────
    def add_user(self, text, voice=False):
        self.finish_open(cancelled=True)
        self._ins("คุณ (เสียง)\n" if voice else "คุณ\n", "you_name")
        self._ins(text.strip() + "\n", "you")
        self._scroll()

    def add_bot_message(self, text):
        self.finish_open(cancelled=True)
        self._ins("Pika\n", "bot_name")
        self._render(text)
        self._scroll()

    def add_notice(self, text):
        if self._open:
            self._notices.append(text)
        else:
            self._ins(text.strip() + "\n", "notice")
            self._scroll()

    def begin_bot(self):
        self.finish_open(cancelled=True)
        self._ins("Pika\n", "bot_name")
        self.text.mark_set("bot_start", "end-1c")
        self.text.mark_gravity("bot_start", "left")
        self._ins("…\n", ("bot", "typing"))
        self._open, self._raw, self._typing = True, "", True
        self._sources, self._notices = [], []
        self._scroll()

    def bot_delta(self, delta):
        if not self._open or not delta:
            return
        self.text.configure(state="normal")
        if self._typing:
            self.text.delete("bot_start", "end-1c")
            self._typing = False
        self.text.insert("end", delta, ("bot",))
        self.text.configure(state="disabled")
        self._raw += delta
        self._scroll()

    def set_sources(self, citations):
        if self._open:
            self._sources = citations or []

    def finish_open(self, ok=True, error="", cancelled=False):
        """Re-render the streaming answer (if one is open) as formatted text."""
        if not self._open:
            return
        self._open = False
        self.text.configure(state="normal")
        self.text.delete("bot_start", "end-1c")
        self.text.configure(state="disabled")
        raw = self._raw.strip()
        if raw:
            self._render(raw)
        if cancelled:
            self._ins("(หยุดแล้ว)\n" if raw else "(ยกเลิก)\n", "notice")
        elif not ok:
            self._ins("⚠ " + (error or "เกิดข้อผิดพลาด") + "\n", ("bot", "error"))
        elif not raw:
            self._ins("(ไม่มีคำตอบ)\n", "notice")
        self._render_sources(self._sources)
        for n in self._notices:
            self._ins(n.strip() + "\n", "notice")
        self._sources, self._notices, self._raw = [], [], ""
        self._scroll()

    def _render_sources(self, cites):
        seen, rows = set(), []
        for c in cites or []:
            title = clean_title(c.get("title")) or (c.get("file_path") or "").rsplit("/", 1)[-1]
            key = (title, c.get("file_path"))
            if title and key not in seen:
                seen.add(key)
                rows.append((title, c.get("file_path") or ""))
        if not rows:
            return
        self._ins("แหล่งข้อมูลจาก Pika\n", "src_head")
        for title, path in rows[:6]:
            self._ins("• " + title, "src")
            if path and not path.endswith(title):
                self._ins("  " + path, ("src", "src_path"))
            self._ins("\n", "src")

    # ── light markdown ────────────────────────────────────────────
    def _render(self, md):
        in_code, blank = False, True
        for line in md.strip("\n").splitlines():
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                self._ins(line + "\n", ("bot", "code"))
                continue
            if not line.strip():
                if not blank:
                    self._ins("\n", "bot")
                blank = True
                continue
            blank = False
            if _RULE.match(line) or _TABLE_SEP.match(line):
                continue
            m = _HEADING.match(line)
            if m:
                self._inline(m.group(1), ("bot", "h"))
            elif (m := _BULLET.match(line)):
                pad = "   " * min(len(m.group(1).expandtabs(4)) // 2, 3)
                self._ins(pad + "• ", ("bot", "li"))
                self._inline(m.group(2), ("bot", "li"))
            elif (m := _NUMBER.match(line)):
                self._ins(m.group(1) + ". ", ("bot", "li"))
                self._inline(m.group(2), ("bot", "li"))
            elif (m := _QUOTE.match(line)):
                self._inline(m.group(1), ("bot", "quote"))
            elif line.strip().startswith("|") and line.strip().endswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                self._inline("  ·  ".join(c for c in cells if c), ("bot", "li"))
            else:
                self._inline(line, ("bot",))
            self._ins("\n", "bot")

    def _inline(self, text, tags):
        for part in _INLINE.split(text):
            if not part:
                continue
            if (part.startswith("**") and part.endswith("**")) or \
                    (part.startswith("__") and part.endswith("__")):
                self._ins(part[2:-2], tags + ("b",))
            elif part.startswith("`") and part.endswith("`"):
                self._ins(part[1:-1], tags + ("code",))
            elif part.startswith("[") and part.endswith(")") and "](" in part:
                label, url = part[1:-1].split("](", 1)
                if url.startswith(("http://", "https://")):
                    self._links += 1
                    tag = f"link{self._links}"
                    self.text.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
                    self.text.tag_bind(tag, "<Enter>", lambda e: self.text.configure(cursor="hand2"))
                    self.text.tag_bind(tag, "<Leave>", lambda e: self.text.configure(cursor="xterm"))
                    self._ins(label, tags + ("link", tag))
                else:
                    self._ins(label, tags)
            else:
                self._ins(part, tags)

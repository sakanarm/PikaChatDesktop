"""
Settings: Pika (API key, project, strategy, answer mode), LLM (OpenAI-compatible URL, key,
model), voice (speech-to-text engine, Pika's voice) and general options.
Network checks run on worker threads; results come back through app.call_ui().
"""
import copy
import os
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

import config
import stt
from llm_client import LLMClient
from pika_client import PikaClient

FONT = "Leelawadee UI"
OK, BAD, MUTED = "#15803D", "#B91C1C", "#64748B"

VOICES = [("th-TH-NiwatNeural", "นิวัฒน์ — เสียงผู้ชาย"),
          ("th-TH-PremwadeeNeural", "เปรมวดี — เสียงผู้หญิง"),
          ("th-TH-AcharaNeural", "อัจฉรา — เสียงผู้หญิง")]
RATES = ["-10%", "+0%", "+10%", "+20%", "+30%"]
PITCHES = ["-10Hz", "+0Hz", "+10Hz", "+20Hz", "+30Hz"]
MODES = [("auto", "อัตโนมัติ (แนะนำ) — LLM คุยเอง และค้น Pika เมื่อเป็นคำถามเรื่องข้อมูล · ต้องมี LLM key"),
         ("always", "ค้น Pika ทุกคำถาม แล้วให้ LLM เรียบเรียงคำตอบ · ต้องมี LLM key"),
         ("direct", "Pika ตอบตรงๆ — ไม่ต้องใช้ LLM key"),
         ("off", "ไม่ใช้ Pika — คุยกับ LLM อย่างเดียว")]
STT_CHOICES = [("auto", "อัตโนมัติ — ใช้โมเดลในเครื่องถ้ามี ไม่งั้นใช้ผ่าน server"),
               ("cloud", "ผ่าน LLM server (/audio/transcriptions) — ไม่ต้องติดตั้งอะไรเพิ่ม"),
               ("local", "ในเครื่อง — OpenThai ASR (ต้องติดตั้งเพิ่ม ~1 GB, มีคำบรรยายสด)")]
SIZES = [(0, "อัตโนมัติ"), (110, "เล็ก"), (150, "กลาง"), (200, "ใหญ่")]
DEFAULT_STRATEGY = "ค่าเริ่มต้นของ Pika"


class SettingsWindow:
    def __init__(self, app, root, cfg):
        self.app = app
        self.cfg = copy.deepcopy(cfg)
        self._strategy_ids = {DEFAULT_STRATEGY: ""}
        w = self.win = tk.Toplevel(root)
        w.withdraw()
        w.title(f"ตั้งค่า — {config.APP_TITLE}")
        w.attributes("-topmost", True)
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda e: self.close())
        if getattr(app, "icon_image", None) is not None:
            w.iconphoto(False, app.icon_image)

        outer = ttk.Frame(w, padding=(12, 12, 12, 10))
        outer.pack(fill="both", expand=True)
        nb = self.nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True)
        self._build_pika(nb)
        self._build_llm(nb)
        self._build_voice(nb)
        self._build_general(nb)

        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Label(bar, text=f"v{config.VERSION}", foreground=MUTED).pack(side="left")
        ttk.Button(bar, text="ยกเลิก", command=self.close).pack(side="right")
        ttk.Button(bar, text="บันทึก", style="Accent.TButton", command=self.save).pack(side="right", padx=8)

        w.update_idletasks()
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
        w.geometry(f"+{max(0, (sw - ww) // 2)}+{max(0, (sh - wh) // 3)}")
        w.deiconify()
        w.lift()
        w.focus_force()

        if self.v_pika_key.get().strip():       # refresh project / strategies quietly
            self._check_pika(quiet=True)

    # ── helpers ───────────────────────────────────────────────────
    def focus(self, tab=None):
        if tab is not None:
            self.nb.select(tab)
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _bg(self, work, done):
        def run():
            try:
                res, err = work(), None
            except Exception as ex:
                res, err = None, str(ex)
            self.app.call_ui(lambda: self.alive() and done(res, err))
        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _tab(nb, title):
        f = ttk.Frame(nb, padding=14)
        f.columnconfigure(1, weight=1)
        nb.add(f, text=title)
        return f

    @staticmethod
    def _row(parent, r, label, widget, **grid):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))
        widget.grid(row=r, column=1, sticky="ew", pady=4, **grid)
        return widget

    def _key_entry(self, parent, r, label, var):
        box = ttk.Frame(parent)
        e = ttk.Entry(box, textvariable=var, show="•", width=46)
        e.pack(side="left", fill="x", expand=True)
        show = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="แสดง", variable=show,
                        command=lambda: e.configure(show="" if show.get() else "•")
                        ).pack(side="left", padx=(8, 0))
        self._row(parent, r, label, box)
        return e

    @staticmethod
    def _status(parent, r, col=1):
        lbl = ttk.Label(parent, text="", foreground=MUTED, wraplength=430, justify="left")
        lbl.grid(row=r, column=col, sticky="w", pady=(0, 4))
        return lbl

    @staticmethod
    def _say(lbl, text, color=MUTED):
        lbl.configure(text=text, foreground=color)

    @staticmethod
    def _link(parent, text, url):
        lbl = ttk.Label(parent, text=text, foreground="#2563EB", cursor="hand2")
        lbl.bind("<Button-1>", lambda e: webbrowser.open(url))
        return lbl

    # ── Pika ──────────────────────────────────────────────────────
    def _build_pika(self, nb):
        p = self.cfg["pika"]
        f = self._tab(nb, "  Pika  ")
        self.v_pika_url = tk.StringVar(value=p["base_url"])
        self.v_pika_key = tk.StringVar(value=p["api_key"])
        self.v_project = tk.StringVar(value=p["project_id"])
        self.v_project_name = tk.StringVar(value=p.get("project_name", ""))
        self.v_mode = tk.StringVar(value=p.get("mode", "auto"))

        self._key_entry(f, 0, "Pika API key", self.v_pika_key)
        self._row(f, 1, "Pika URL", ttk.Entry(f, textvariable=self.v_pika_url))
        btns = ttk.Frame(f)
        ttk.Button(btns, text="ตรวจสอบ key และโหลดโปรเจกต์", command=self._check_pika).pack(side="left")
        self._link(btns, "ขอ API key ที่หน้าโปรเจกต์ Pika ↗",
                   (p["base_url"] or config.DEFAULTS["pika"]["base_url"]).rstrip("/") + "/#projects"
                   ).pack(side="left", padx=12)
        btns.grid(row=2, column=1, sticky="w", pady=(4, 2))
        self.pika_status = self._status(f, 3)

        self._row(f, 4, "Project ID", ttk.Entry(f, textvariable=self.v_project))
        ttk.Label(f, textvariable=self.v_project_name, foreground=MUTED).grid(row=5, column=1, sticky="w")
        cur = p.get("strategy") or ""
        if cur:
            self._strategy_ids[cur] = cur
        self.cb_strategy = ttk.Combobox(f, state="readonly", values=list(self._strategy_ids))
        self.cb_strategy.set(cur or DEFAULT_STRATEGY)
        self._row(f, 6, "วิธีค้น (strategy)", self.cb_strategy)

        box = ttk.LabelFrame(f, text=" วิธีตอบคำถาม ", padding=(10, 6))
        box.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        for value, text in MODES:
            ttk.Radiobutton(box, text=text, value=value, variable=self.v_mode).pack(anchor="w", pady=2)

    def _check_pika(self, quiet=False):
        url, key = self.v_pika_url.get().strip(), self.v_pika_key.get().strip()
        if not key:
            return self._say(self.pika_status, "ใส่ Pika API key ก่อน", BAD)
        self._say(self.pika_status, "กำลังตรวจสอบ…")

        def work():
            c = PikaClient(url, key)
            me = c.me() or {}
            proj = me.get("project") or {}
            pid = proj.get("id") or self.v_project.get().strip()
            return me, proj, pid, (c.strategies(pid) if pid else [])

        def done(res, err):
            if err:
                return self._say(self.pika_status, "✗ " + err, BAD)
            me, proj, pid, strategies = res
            if pid:
                self.v_project.set(pid)
            name = proj.get("name") or ""
            self.v_project_name.set(f"โปรเจกต์: {name}" if name else "")
            ids = {DEFAULT_STRATEGY: ""}
            for s in strategies:
                ids[f"{s.get('label') or s['id']}  ({s['id']})"] = s["id"]
            current = self._strategy_ids.get(self.cb_strategy.get(), "")
            self._strategy_ids = ids
            self.cb_strategy.configure(values=list(ids))
            self.cb_strategy.set(next((k for k, v in ids.items() if v == current), DEFAULT_STRATEGY))
            scopes = (me.get("api_key") or {}).get("scopes") or []
            days = (me.get("api_key") or {}).get("expires_in_days")
            msg = f"✓ ใช้ได้ — {name or pid}"
            if scopes and "ask" not in scopes:
                return self._say(self.pika_status, msg + " แต่ key นี้ไม่มีสิทธิ์ 'ask'", BAD)
            if days is not None:
                msg += f" · key หมดอายุในอีก {days} วัน"
            self._say(self.pika_status, msg, OK)

        if quiet:
            self._say(self.pika_status, "")
        self._bg(work, done)

    # ── LLM ───────────────────────────────────────────────────────
    def _build_llm(self, nb):
        c = self.cfg["llm"]
        f = self._tab(nb, "  LLM  ")
        self.v_llm_url = tk.StringVar(value=c["base_url"])
        self.v_llm_key = tk.StringVar(value=c["api_key"])
        self.v_model = tk.StringVar(value=c["model"])
        ttk.Label(f, text="ใช้กับ API แบบ OpenAI-compatible ได้ทุกเจ้า เช่น LiteLLM ของบริษัท "
                          "(ถ้าไม่มี key ให้เลือกโหมด \"Pika ตอบตรงๆ\" ในแท็บ Pika)",
                  foreground=MUTED, wraplength=520, justify="left").grid(row=0, column=0, columnspan=2,
                                                                       sticky="w", pady=(0, 8))
        self._row(f, 1, "Base URL", ttk.Entry(f, textvariable=self.v_llm_url))
        self._key_entry(f, 2, "API key", self.v_llm_key)
        box = ttk.Frame(f)
        self.cb_model = ttk.Combobox(box, textvariable=self.v_model, values=[c["model"]])
        self.cb_model.pack(side="left", fill="x", expand=True)
        ttk.Button(box, text="โหลดรายชื่อโมเดล", command=self._load_models).pack(side="left", padx=(8, 0))
        self._row(f, 3, "โมเดล", box)
        ttk.Button(f, text="ทดสอบการเชื่อมต่อ", command=self._test_llm).grid(row=4, column=1, sticky="w",
                                                                            pady=(8, 2))
        self.llm_status = self._status(f, 5)

    def _llm(self):
        return LLMClient(self.v_llm_url.get().strip(), self.v_llm_key.get().strip(),
                         self.v_model.get().strip())

    def _load_models(self):
        llm = self._llm()
        if not llm.api_key:
            return self._say(self.llm_status, "ใส่ API key ก่อน", BAD)
        self._say(self.llm_status, "กำลังโหลดรายชื่อโมเดล…")

        def done(models, err):
            if err:
                return self._say(self.llm_status, "✗ " + err, BAD)
            self.cb_model.configure(values=models)
            self._say(self.llm_status, f"✓ พบ {len(models)} โมเดล", OK)
        self._bg(llm.models, done)

    def _test_llm(self):
        llm = self._llm()
        if not llm.configured:
            return self._say(self.llm_status, "ใส่ URL, API key และโมเดลให้ครบก่อน", BAD)
        self._say(self.llm_status, "กำลังทดสอบ…")

        def done(res, err):
            if err:
                return self._say(self.llm_status, "✗ " + err, BAD)
            text, secs = res
            self._say(self.llm_status, f"✓ ใช้ได้ — ตอบใน {secs:.1f} วินาที ({text[:30]})", OK)
        self._bg(llm.ping, done)

    # ── voice ─────────────────────────────────────────────────────
    def _build_voice(self, nb):
        v = self.cfg["voice"]
        f = self._tab(nb, "  เสียง  ")
        self.v_stt = tk.StringVar(value=v.get("stt", "auto"))
        self.v_stt_model = tk.StringVar(value=v.get("stt_model", "whisper-1"))
        self.v_silence = tk.StringVar(value=str(v.get("silence_ms", 700)))
        self.v_voice = tk.StringVar(value=v.get("tts_voice", VOICES[0][0]))
        self.v_rate = tk.StringVar(value=v.get("tts_rate", "+10%"))
        self.v_pitch = tk.StringVar(value=v.get("tts_pitch", "+20Hz"))
        self.v_speak_chat = tk.BooleanVar(value=bool(v.get("speak_chat_replies", False)))
        self.v_max_speech = tk.StringVar(value=str(v.get("max_speech_chars", 400)))

        box = ttk.LabelFrame(f, text=" ฟังเสียงพูด (speech-to-text) ", padding=(10, 6))
        box.grid(row=0, column=0, columnspan=2, sticky="ew")
        box.columnconfigure(1, weight=1)
        for i, (value, text) in enumerate(STT_CHOICES):
            ttk.Radiobutton(box, text=text, value=value, variable=self.v_stt).grid(
                row=i, column=0, columnspan=2, sticky="w", pady=1)
        have_local = stt.local_available()
        ttk.Label(box, text=("✓ ติดตั้งโมเดลในเครื่องแล้ว" if have_local else
                             "ยังไม่ได้ติดตั้งโมเดลในเครื่อง (ดู README หัวข้อ Local ASR)"),
                  foreground=OK if have_local else MUTED).grid(row=3, column=0, columnspan=2,
                                                               sticky="w", pady=(2, 6))
        row = ttk.Frame(box)
        ttk.Entry(row, textvariable=self.v_stt_model, width=22).pack(side="left")
        ttk.Button(row, text="ทดสอบ", command=self._test_stt).pack(side="left", padx=(8, 0))
        self._row(box, 4, "โมเดลถอดเสียง", row, columnspan=1)
        self.stt_status = self._status(box, 5)
        self._row(box, 6, "เงียบนานเท่าไรถือว่าพูดจบ (ms)",
                  ttk.Spinbox(box, from_=300, to=2000, increment=100, textvariable=self.v_silence, width=8),
                  columnspan=1).grid(sticky="w")

        box = ttk.LabelFrame(f, text=" เสียงของ Pika (text-to-speech) ", padding=(10, 6))
        box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        box.columnconfigure(1, weight=1)
        names = [n for _, n in VOICES]
        self.cb_voice = ttk.Combobox(box, state="readonly", values=names, width=28)
        self.cb_voice.set(next((n for vid, n in VOICES if vid == self.v_voice.get()), names[0]))
        self._row(box, 0, "เสียง", self.cb_voice).grid(sticky="w")
        row = ttk.Frame(box)
        ttk.Label(row, text="ความเร็ว").pack(side="left")
        ttk.Combobox(row, textvariable=self.v_rate, values=RATES, width=7).pack(side="left", padx=(6, 14))
        ttk.Label(row, text="ระดับเสียง").pack(side="left")
        ttk.Combobox(row, textvariable=self.v_pitch, values=PITCHES, width=7).pack(side="left", padx=(6, 14))
        ttk.Button(row, text="🔊 ลองฟัง", command=self._preview_voice).pack(side="left")
        self._row(box, 1, "", row).grid(sticky="w")
        ttk.Checkbutton(box, text="อ่านออกเสียงคำตอบที่พิมพ์ถามในแชทด้วย",
                        variable=self.v_speak_chat).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        self._row(box, 3, "พูดยาวสุด (ตัวอักษร)",
                  ttk.Spinbox(box, from_=100, to=3000, increment=100, textvariable=self.v_max_speech,
                              width=8)).grid(sticky="w")

    def _voice_id(self):
        return next((vid for vid, n in VOICES if n == self.cb_voice.get()), VOICES[0][0])

    def _preview_voice(self):
        self.app.preview_voice("สวัสดีครับ เราชื่อพิก้า มีอะไรให้ช่วยค้นบอกได้เลยนะ",
                               self._voice_id(), self.v_rate.get().strip(), self.v_pitch.get().strip())

    def _test_stt(self):
        llm = self._llm()
        if not llm.api_key:
            return self._say(self.stt_status, "การถอดเสียงผ่าน server ต้องใช้ LLM API key (แท็บ LLM)", BAD)
        model = self.v_stt_model.get().strip() or "whisper-1"
        self._say(self.stt_status, "กำลังทดสอบ…")
        silence = bytes(16000)       # 0.5 s of silence, 16 kHz s16

        def done(_text, err):
            if err:
                return self._say(self.stt_status, "✗ " + err, BAD)
            self._say(self.stt_status, f"✓ server ถอดเสียงด้วย {model} ได้", OK)
        self._bg(lambda: llm.transcribe(silence, model), done)

    # ── general ───────────────────────────────────────────────────
    def _build_general(self, nb):
        pc = self.cfg["pet"]
        f = self._tab(nb, "  ทั่วไป  ")
        self.v_size = tk.IntVar(value=int(pc.get("size") or 0))
        self.v_walk = tk.BooleanVar(value=bool(pc.get("walk", True)))
        self.v_top = tk.BooleanVar(value=bool(pc.get("chat_on_top", True)))
        self.v_autostart = tk.BooleanVar(value=bool(pc.get("autostart", False)))
        row = ttk.Frame(f)
        for value, text in SIZES:
            ttk.Radiobutton(row, text=text, value=value, variable=self.v_size).pack(side="left", padx=(0, 12))
        self._row(f, 0, "ขนาดตัว Pika", row).grid(sticky="w")
        ttk.Checkbutton(f, text="ให้ Pika เดินเล่นบนจอ", variable=self.v_walk).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Checkbutton(f, text="หน้าต่างแชทอยู่บนสุดเสมอ", variable=self.v_top).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Checkbutton(f, text="เปิด Pika อัตโนมัติเมื่อเข้า Windows", variable=self.v_autostart).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Separator(f).grid(row=4, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(f, text="ไฟล์ตั้งค่า (เก็บ key ไว้ในเครื่องนี้เท่านั้น)").grid(row=5, column=0, columnspan=2,
                                                                         sticky="w")
        row = ttk.Frame(f)
        ttk.Label(row, text=config.CONFIG_PATH, foreground=MUTED).pack(side="left")
        ttk.Button(row, text="เปิดโฟลเดอร์", command=self._open_folder).pack(side="left", padx=(10, 0))
        row.grid(row=6, column=0, columnspan=2, sticky="w", pady=4)
        tips = ("วิธีใช้: คลิกที่ Pika = เปิด/ซ่อนแชท (หรือหยุดพูด) · ดับเบิลคลิก = ย่อเป็นไอคอน · "
                "ลากเพื่อย้ายที่ · คลิกขวา = เมนู")
        ttk.Label(f, text=tips, foreground=MUTED, wraplength=520, justify="left").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(12, 0))

    @staticmethod
    def _open_folder():
        os.makedirs(config.CONFIG_DIR, exist_ok=True)
        try:
            os.startfile(config.CONFIG_DIR)
        except Exception as ex:
            print(f"[settings] open folder: {ex}")

    # ── save ──────────────────────────────────────────────────────
    @staticmethod
    def _int(var, default, lo, hi):
        try:
            return min(max(int(float(var.get())), lo), hi)
        except (TypeError, ValueError, tk.TclError):
            return default

    def collect(self):
        c = copy.deepcopy(self.cfg)
        p = c["pika"]
        p["base_url"] = self.v_pika_url.get().strip().rstrip("/") or config.DEFAULTS["pika"]["base_url"]
        p["api_key"] = self.v_pika_key.get().strip()
        p["project_id"] = self.v_project.get().strip()
        p["project_name"] = self.v_project_name.get().replace("โปรเจกต์: ", "").strip()
        p["strategy"] = self._strategy_ids.get(self.cb_strategy.get(), "")
        p["mode"] = self.v_mode.get()
        lc = c["llm"]
        lc["base_url"] = self.v_llm_url.get().strip().rstrip("/")
        lc["api_key"] = self.v_llm_key.get().strip()
        lc["model"] = self.v_model.get().strip() or config.DEFAULTS["llm"]["model"]
        v = c["voice"]
        v["stt"] = self.v_stt.get()
        v["stt_model"] = self.v_stt_model.get().strip() or "whisper-1"
        v["silence_ms"] = self._int(self.v_silence, 700, 300, 2000)
        v["tts_voice"] = self._voice_id()
        v["tts_rate"] = self.v_rate.get().strip() or "+10%"
        v["tts_pitch"] = self.v_pitch.get().strip() or "+20Hz"
        v["speak_chat_replies"] = bool(self.v_speak_chat.get())
        v["max_speech_chars"] = self._int(self.v_max_speech, 400, 100, 3000)
        pc = c["pet"]
        pc["size"] = self._int(self.v_size, 0, 0, 200)
        pc["walk"] = bool(self.v_walk.get())
        pc["chat_on_top"] = bool(self.v_top.get())
        pc["autostart"] = bool(self.v_autostart.get())
        return c

    def save(self):
        cfg = self.collect()
        self.close()
        self.app.apply_config(cfg)

    def close(self):
        if self.alive():
            self.win.destroy()
        self.app.on_settings_closed(self)

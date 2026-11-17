"""
Pika Chat Desktop — a desktop mascot that answers from your Pika knowledge base,
in a mini chat or by voice.

    python main.py            (or pythonw main.py / the built PikaChatDesktop.exe)

Modules: pet.py (mascot window) · chat_window.py · settings_window.py · assistant.py
(turn logic) · pika_client.py / llm_client.py (HTTP) · audio.py (mic + TTS) · stt.py
"""
import ctypes
import os
import queue
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk

import config
from assistant import Assistant
from chat_window import ChatWindow
from llm_client import LLMClient
from pet import FONT, PetWindow
from settings_window import SettingsWindow
from textutil import shorten


# ─── process setup ────────────────────────────────────────────────
def setup_logging():
    """The .exe (and pythonw) have no console: write prints to %APPDATA%\\PikaChatDesktop\\pika.log."""
    if getattr(sys, "frozen", False) or sys.stdout is None or sys.stderr is None:
        try:
            os.makedirs(config.CONFIG_DIR, exist_ok=True)
            path = os.path.join(config.CONFIG_DIR, "pika.log")
            if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
                os.replace(path, path + ".old")
            log = open(path, "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = log
        except Exception:
            class _Null:
                def write(self, *_a):
                    pass

                def flush(self):
                    pass
            sys.stdout = sys.stderr = _Null()
    else:
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    print(f"=== {config.APP_TITLE} v{config.VERSION} start {time.strftime('%Y-%m-%d %H:%M:%S')}")


def dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # system DPI aware: crisp text
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def single_instance():
    """Returns a handle to keep, or None if Pika is already running."""
    try:
        k = ctypes.windll.kernel32
        k.CreateMutexW.restype = ctypes.c_void_p
        handle = k.CreateMutexW(None, False, "Local\\PikaChatDesktop.SingleInstance")
        if k.GetLastError() == 183:          # ERROR_ALREADY_EXISTS
            ctypes.windll.user32.MessageBoxW(
                None, "Pika Chat Desktop เปิดอยู่แล้ว\n(ดู Pika ที่มุมขวาล่างของจอ)", config.APP_TITLE, 0x40)
            return None
        return handle
    except Exception:
        return True


def message_box(text, title=config.APP_TITLE, icon=0x10):
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, icon)
    except Exception:
        print(text)


# ─── assistant -> UI bridge ───────────────────────────────────────
class _Sink:
    """Assistant callbacks arrive on a worker thread; replay them on the Tk thread,
    dropping anything from a turn that was cancelled or replaced."""

    def __init__(self, app):
        self.app = app

    def _post(self, t, fn):
        def run():
            if t is self.app.assistant.turn and not t.cancelled:
                fn()
        self.app.call_ui(run)

    def state(self, t, name, detail):
        self._post(t, lambda: self.app.on_turn_state(t, name, detail))

    def text(self, t, delta):
        self._post(t, lambda: self.app.on_turn_text(t, delta))

    def speak(self, t, segment):
        self._post(t, lambda: self.app.speaker and self.app.speaker.say(segment))

    def sources(self, t, citations):
        self._post(t, lambda: self.app.chat.set_sources(citations))

    def notice(self, t, message):
        self._post(t, lambda: self.app.on_turn_notice(t, message))

    def done(self, t, ok, error):
        self._post(t, lambda: self.app.on_turn_done(t, ok, error))


# ─── the app ──────────────────────────────────────────────────────
class App:
    def __init__(self):
        self.cfg = config.load()
        self.ui_q = queue.Queue()
        self.speaker = None
        self.mic = None
        self.mic_on = False
        self._mic_starting = False
        self.settings = None
        self._bubble_job = None

        root = self.root = tk.Tk()
        root.withdraw()
        root.title(config.APP_TITLE)
        root.report_callback_exception = self._tk_error
        self._style()
        self.icon_image = tk.PhotoImage(file=config.resource_path("assets", "pika", "icon.png"))
        root.iconphoto(True, self.icon_image)

        self.assistant = Assistant(lambda: self.cfg, _Sink(self))
        pc = self.cfg["pet"]
        self.pet = PetWindow(root, self, pc.get("size", 0), pc.get("walk", True))
        self.chat = ChatWindow(self, root, self.pet.scale)
        self.chat.set_topmost(pc.get("chat_on_top", True))
        root.deiconify()

        root.after(30, self._drain)
        root.after(700, self._greet)
        threading.Thread(target=self._init_speaker, daemon=True).start()
        self._sync_autostart()

    def run(self):
        self.root.mainloop()

    def _style(self):
        r = self.root
        r.option_add("*Font", (FONT, 10))
        r.option_add("*TCombobox*Listbox.font", (FONT, 10))
        r.option_add("*Menu.font", (FONT, 10))
        st = ttk.Style(r)
        try:
            st.theme_use("vista")
        except tk.TclError:
            pass
        st.configure(".", font=(FONT, 10))
        st.configure("TNotebook.Tab", padding=(12, 4))
        st.configure("Accent.TButton", font=(FONT, 10, "bold"))

    def _tk_error(self, exc, val, tb):
        print("[ui] error:\n" + "".join(traceback.format_exception(exc, val, tb)))

    # ── thread -> Tk ──────────────────────────────────────────────
    def call_ui(self, fn):
        self.ui_q.put(fn)

    def _drain(self):
        try:
            while True:
                fn = self.ui_q.get_nowait()
                try:
                    fn()
                except Exception:
                    print("[ui] callback error:\n" + traceback.format_exc())
        except queue.Empty:
            pass
        self.root.after(30, self._drain)

    # ── startup ───────────────────────────────────────────────────
    def _init_speaker(self):
        try:
            from audio import Speaker
            v = self.cfg["voice"]
            sp = Speaker(v["tts_voice"], v["tts_rate"], v["tts_pitch"])
            sp.warmup()
            self.call_ui(lambda: setattr(self, "speaker", sp))
        except Exception as ex:
            print(f"[tts] unavailable: {type(ex).__name__}: {ex}")

    def _greet(self):
        p, lc = self.cfg["pika"], self.cfg["llm"]
        self.pet.react("wave")
        if not p["api_key"] and not lc["api_key"]:
            self.pet.say("สวัสดี! เราคือ Pika 👋 ใส่ Pika API key ในหน้าตั้งค่าก่อนนะ", 9)
            self.root.after(1500, self.open_settings)
        else:
            self.pet.say("สวัสดี! คลิกที่เราเพื่อเปิดแชท หรือกด 🎤 เพื่อคุยด้วยเสียงนะ", 6)

    # ── state used by the windows ─────────────────────────────────
    def is_talking(self):
        sp = self.speaker
        return sp is not None and sp.playing

    def chat_visible(self):
        return self.chat.visible

    def ready_text(self):
        p, lc = self.cfg["pika"], self.cfg["llm"]
        if not p["api_key"] and not lc["api_key"]:
            return "ยังไม่ได้ตั้งค่า — กด ⚙"
        if p.get("mode") == "off" or not p["api_key"]:
            return "คุยกับ LLM"
        name = p.get("project_name") or p.get("project_id")
        return f"คลังความรู้: {name}" if name else "พร้อมคุย"

    # ── pet / chat actions ────────────────────────────────────────
    def on_pet_click(self):
        if self.assistant.busy or (self.speaker and self.speaker.active):
            self.interrupt()
            self.pet.say("โอเค หยุดแล้ว", 1.5)
            return
        self.toggle_chat()
        if self.chat.visible:
            self.pet.react("wave")

    def toggle_chat(self):
        self.chat.toggle(self.pet.screen_rect())

    def show_chat(self):
        self.chat.show(self.pet.screen_rect())

    def on_chat_hidden(self):
        self.pet.touch()

    def open_settings(self, tab=None):
        if self.settings is not None and self.settings.alive():
            self.settings.focus(tab)
            return
        self.settings = SettingsWindow(self, self.root, self.cfg)
        if tab is not None:
            self.settings.focus(tab)

    def on_settings_closed(self, win):
        if self.settings is win:
            self.settings = None

    def set_walk(self, on):
        self.cfg["pet"]["walk"] = bool(on)
        self.pet.set_walk(bool(on))
        self._save()

    def clear_history(self):
        self.assistant.clear_history()

    def quit(self):
        try:
            self.assistant.cancel()
            if self.mic:
                self.mic.stop()
            if self.speaker:
                self.speaker.stop()
        finally:
            self.root.destroy()

    # ── conversation ──────────────────────────────────────────────
    def submit(self, text, channel="chat"):
        text = (text or "").strip()
        if not text:
            return
        if self.speaker:
            self.speaker.stop()
        if self.mic:
            self.mic.pause()
        speak = self.speaker is not None and (
            channel == "voice" or bool(self.cfg["voice"].get("speak_chat_replies")))
        self.chat.add_user(text, voice=channel == "voice")
        self.chat.begin_bot()
        self.chat.set_busy(True)
        self.pet.touch()
        if channel == "voice":
            self.pet.say("“" + shorten(text, 90) + "”", 0)
        else:
            self.pet.hush()
        self.assistant.submit(text, channel, speak)

    def interrupt(self):
        self.assistant.cancel()
        if self.speaker:
            self.speaker.stop()
        self.chat.finish_open(cancelled=True)
        self.chat.set_busy(False)
        self.chat.set_status(None)
        self.pet.set_activity(None)
        self.pet.hush()
        self._resume_mic_if_idle()

    def _shows_bubble(self, t):
        return t.channel == "voice" or not self.chat.visible

    def on_turn_state(self, t, name, _detail):
        self.pet.set_activity(name)
        self.chat.set_status(name)
        if name == "searching" and self._shows_bubble(t):
            self.pet.say("กำลังค้นในคลังความรู้ Pika…", 0)

    def on_turn_text(self, t, delta):
        self.chat.bot_delta(delta)
        if self._shows_bubble(t) and self._bubble_job is None:
            # refresh the bubble a few times a second, not on every token
            self._bubble_job = self.root.after(200, lambda: self._bubble_answer(t))

    def _bubble_answer(self, t, final=False):
        self._bubble_job = None
        if t is self.assistant.turn and not t.cancelled and t.answer.strip():
            self.pet.say(shorten(t.answer, 200), None if final else 0)

    def on_turn_notice(self, _t, message):
        if message == "overflow":
            self.chat.add_notice("คำตอบยาว — Pika พูดแค่ส่วนแรก รายละเอียดทั้งหมดอยู่ในแชทนี้")
            self.show_chat()
        else:
            self.chat.add_notice(message)

    def on_turn_done(self, t, ok, error):
        if self._bubble_job:
            self.root.after_cancel(self._bubble_job)
            self._bubble_job = None
        self.chat.finish_open(ok, error)
        self.chat.set_busy(False)
        if ok:
            if self._shows_bubble(t):
                self._bubble_answer(t, final=True)
        else:
            self.pet.react("sad")
            self.pet.say(shorten(error, 160), 8)
        if t.speak and self.speaker:
            self.chat.set_status("answering")
            self.speaker.end_turn(lambda: self.call_ui(lambda: self._turn_finished(t)))
        else:
            self._turn_finished(t)

    def _turn_finished(self, t):
        if t is not self.assistant.turn:
            return
        self.pet.set_activity(None)
        self.chat.set_status(None)
        self._resume_mic_if_idle()

    # ── microphone ────────────────────────────────────────────────
    def toggle_mic(self):
        if self.mic_on or self._mic_starting:
            self.stop_mic()
        else:
            self.start_mic()

    def start_mic(self):
        import stt
        self._mic_starting = True
        v, lc = dict(self.cfg["voice"]), dict(self.cfg["llm"])
        local = v.get("stt") == "local" or (v.get("stt") == "auto" and stt.local_available())
        self.pet.say("กำลังโหลดโมเดลถอดเสียง…" if local else "กำลังเปิดไมค์…", 0)

        def work():
            try:
                from audio import MicListener
                engine = stt.create(v, LLMClient(lc["base_url"], lc["api_key"], lc["model"]))
                mic = MicListener(
                    engine,
                    on_speech_start=lambda: self.call_ui(self._heard_start),
                    on_partial=lambda text: self.call_ui(lambda: self._heard_partial(text)),
                    on_final=lambda text: self.call_ui(lambda: self._heard_final(text)),
                    on_error=lambda msg: self.call_ui(lambda: self._heard_error(msg)),
                    silence_ms=int(v.get("silence_ms", 700)))
                try:
                    mic.start()
                except Exception as ex:
                    raise RuntimeError(f"เปิดไมโครโฟนไม่ได้: {ex}") from None
                self.call_ui(lambda: self._mic_ready(mic, engine))
            except Exception as ex:
                msg = str(ex) or type(ex).__name__
                print(f"[mic] start failed: {msg}")
                self.call_ui(lambda: self._mic_failed(msg))
        threading.Thread(target=work, daemon=True).start()

    def _mic_ready(self, mic, engine):
        if not self._mic_starting:          # turned off while starting
            mic.stop()
            return
        self._mic_starting = False
        self.mic, self.mic_on = mic, True
        self.pet.set_mic(True)
        self.chat.set_mic(True)
        self.pet.say("ฟังอยู่นะ พูดมาได้เลย" + ("" if engine.realtime else " (พูดจบแล้วรอแป๊บนึง)"), 4)
        if self.assistant.busy or (self.speaker and self.speaker.active):
            mic.pause()

    def _mic_failed(self, msg):
        self._mic_starting = False
        self.pet.react("sad")
        self.pet.say(msg, 9)
        self.chat.add_notice("🎤 " + msg)

    def stop_mic(self, quiet=False):
        self._mic_starting = False
        mic, self.mic, self.mic_on = self.mic, None, False
        if mic:
            mic.stop()
        self.pet.set_mic(False)
        self.chat.set_mic(False)
        if self.pet.activity == "hearing":
            self.pet.set_activity(None)
            self.chat.set_status(None)
        if not quiet:
            self.pet.say("ปิดไมค์แล้ว", 1.5)

    def _resume_mic_if_idle(self):
        if self.mic_on and self.mic and not self.assistant.busy:
            self.mic.resume()

    def _heard_start(self):
        if not self.mic_on or self.assistant.busy:
            return
        self.pet.set_activity("hearing")
        self.chat.set_status("hearing")
        self.pet.say("🎤 …", 0)

    def _heard_partial(self, text):
        if self.mic_on and not self.assistant.busy:
            self.pet.say("🎤 " + text, 0)

    def _heard_final(self, text):
        if not self.mic_on:
            return
        if not text.strip():
            if self.pet.activity == "hearing":
                self.pet.set_activity(None)
                self.chat.set_status(None)
                self.pet.hush()
            return
        self.submit(text, "voice")

    def _heard_error(self, msg):
        self.pet.set_activity(None)
        self.chat.set_status(None)
        self.pet.react("sad")
        self.pet.say("ถอดเสียงไม่สำเร็จ: " + shorten(msg, 120), 7)
        if "key" in msg.lower() or "endpoint" in msg.lower():
            self.chat.add_notice("🎤 " + msg)
            self.stop_mic(quiet=True)

    def preview_voice(self, text, voice, rate, pitch):
        if not self.speaker:
            self.pet.say("ระบบเสียงยังไม่พร้อม (ต้องต่ออินเทอร์เน็ต)", 4)
            return
        self.speaker.stop()
        if self.mic:
            self.mic.pause()
        self.speaker.say(text, voice, rate, pitch)
        self.speaker.end_turn(lambda: self.call_ui(self._resume_mic_if_idle))

    # ── settings ──────────────────────────────────────────────────
    def _save(self):
        try:
            config.save(self.cfg)
        except Exception as ex:
            print(f"[config] save failed: {ex}")
            self.pet.say(f"บันทึกการตั้งค่าไม่สำเร็จ: {ex}", 8)
            return False
        return True

    def apply_config(self, cfg):
        old, self.cfg = self.cfg, cfg
        saved = self._save()
        v, pc = cfg["voice"], cfg["pet"]
        if self.speaker:
            self.speaker.configure(v["tts_voice"], v["tts_rate"], v["tts_pitch"])
        self.pet.set_size(pc.get("size", 0))
        self.pet.set_walk(pc.get("walk", True))
        self.chat.set_topmost(pc.get("chat_on_top", True))
        self.chat.set_status(None)
        self._sync_autostart()
        if (self.mic_on or self._mic_starting) and (old["voice"] != v or old["llm"] != cfg["llm"]):
            self.stop_mic(quiet=True)
            self.start_mic()
        if saved:
            self.pet.react("happy")
            self.pet.say("บันทึกการตั้งค่าแล้ว", 2.5)

    def _launch_command(self):
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        exe = sys.executable
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        return f'"{pyw if os.path.exists(pyw) else exe}" "{os.path.abspath(__file__)}"'

    def _sync_autostart(self):
        try:
            import winreg
            run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as k:
                if self.cfg["pet"].get("autostart"):
                    winreg.SetValueEx(k, config.APP_NAME, 0, winreg.REG_SZ, self._launch_command())
                else:
                    try:
                        winreg.DeleteValue(k, config.APP_NAME)
                    except FileNotFoundError:
                        pass
        except Exception as ex:
            print(f"[autostart] {ex}")


def main():
    setup_logging()
    dpi_aware()
    lock = single_instance()
    if lock is None:
        return
    try:
        App().run()
    except Exception:
        err = traceback.format_exc()
        print(err)
        message_box("Pika Chat Desktop หยุดทำงานเพราะข้อผิดพลาด:\n\n" + err[-1500:])
    finally:
        print(f"=== exit {time.strftime('%H:%M:%S')}")
        _ = lock


if __name__ == "__main__":
    main()

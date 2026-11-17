"""
One conversation turn: user text (typed or spoken) -> streamed reply (+ speech).

Routing (config pika.mode):
  auto    LLM chats, and calls the ask_pika tool for anything that may be in the knowledge base
  always  every question is asked to Pika first, then the LLM turns it into a reply
  direct  Pika answers by itself (no LLM key needed)
  off     LLM only
If the LLM key is missing or rejected, Pika answers directly.

Runs on a worker thread and reports through a sink object (see App in main.py):
  sink.state(turn, name, detail)   name: thinking | searching | answering
  sink.text(turn, delta)           answer text as it streams
  sink.speak(turn, segment)        text to say (voice turns / speak_chat_replies)
  sink.sources(turn, citations)    Pika citations
  sink.notice(turn, message)       small info line (fallbacks)
  sink.done(turn, ok, error)       always called last
"""
import json
import random
import threading

from llm_client import LLMClient, LLMError
from pika_client import PikaClient, PikaError
from textutil import pop_segment

PERSONA = (
    "คุณคือ Pika (พิก้า) ผู้ช่วยดูแลคลังความรู้ PIKAWIKI ของผู้ใช้ "
    "หน้าตาเป็นเด็กผู้ชายดินปั้นตัวกลม ผมหยิก ใส่เสื้อยืดสีขาว นิสัยร่าเริง สุภาพ เป็นกันเอง "
    "แทนตัวเองว่า \"เรา\" ตอบเป็นภาษาเดียวกับผู้ใช้ (ส่วนใหญ่เป็นภาษาไทย)"
)
RULES_TOOL = (
    "กติกา:\n"
    "- ถ้าผู้ใช้ถามข้อมูล ข้อเท็จจริง เอกสาร โปรเจกต์ ลูกค้า ทีม นโยบาย หรืออะไรที่อาจอยู่ในคลังความรู้ "
    "ให้เรียกเครื่องมือ ask_pika ก่อนตอบเสมอ ห้ามเดาเอง\n"
    "- ตอบจากผลของ ask_pika ถ้าไม่พบข้อมูลให้บอกตรงๆ ว่าไม่เจอในคลังความรู้\n"
    "- ทักทาย คุยเล่น หรือเรื่องทั่วไปที่ไม่เกี่ยวกับข้อมูลในคลัง ตอบเองได้เลย"
)
RULES_CONTEXT = (
    "กติกา: ใช้ข้อมูลจากคลังความรู้ Pika ที่แนบมาเป็นหลัก ถ้าข้อมูลที่แนบมาไม่ตรงคำถาม "
    "ให้บอกว่าไม่เจอในคลังความรู้ แล้วค่อยตอบจากความรู้ทั่วไปถ้าทำได้"
)
VOICE_STYLE = (
    "ตอนนี้คุยกันด้วยเสียงแบบสดๆ: ตอบภาษาพูด สั้นๆ 1-3 ประโยค ห้ามใช้ markdown ห้ามใช้อีโมจิ "
    "ห้ามอ่าน URL หรือชื่อไฟล์ยาวๆ ข้อความของผู้ใช้มาจากระบบถอดเสียงอาจสะกดผิด ให้เดาความหมายที่ใกล้ที่สุด"
)
CHAT_STYLE = (
    "ตอนนี้คุยผ่านหน้าต่างแชท: ตอบกระชับ อ่านง่าย ใช้หัวข้อย่อยหรือตัวหนาได้เมื่อช่วยให้อ่านง่าย "
    "ไม่ต้องใส่รายการแหล่งอ้างอิงเอง (แอปแสดงให้แล้ว)"
)
FILLERS = ["แป๊บนึงนะ เราขอค้นในคลังความรู้ก่อน", "ขอเช็กใน Pika แป๊บนึงนะ",
           "รอแป๊บนะ เรากำลังหาข้อมูลให้"]

ASK_PIKA_TOOL = {
    "type": "function",
    "function": {
        "name": "ask_pika",
        "description": ("ถามคลังความรู้ PIKAWIKI ของผู้ใช้ (เอกสาร โปรเจกต์ proposal TOR/RFP "
                        "meeting notes incident นโยบาย ข้อมูลทีม/ลูกค้า ฯลฯ) ได้คำตอบพร้อมแหล่งอ้างอิง"),
        "parameters": {
            "type": "object",
            "properties": {"question": {
                "type": "string",
                "description": "คำถามที่สมบูรณ์ในตัวเอง (เติมบริบทจากบทสนทนาก่อนหน้าให้ครบ)"}},
            "required": ["question"],
        },
    },
}
HISTORY_MESSAGES = 12


class Turn:
    def __init__(self, tid, text, channel, speak, max_speech):
        self.id, self.text, self.channel, self.speak = tid, text, channel, speak
        self.max_speech = max_speech
        self.cancelled = False
        self.finished = False
        self.answer = ""
        self.citations = []
        self.answering = False
        self._speech_buf = ""
        self._first_seg = True
        self._spoken = 0
        self._speech_over = False
        self._filler_said = False


class Assistant:
    def __init__(self, get_cfg, sink):
        self.get_cfg = get_cfg
        self.sink = sink
        self.history = []
        self.turn = None
        self._n = 0
        self._rejected_llm_key = None    # a 401'd key is not retried until it changes

    @property
    def busy(self):
        return self.turn is not None and not self.turn.finished

    def submit(self, text, channel="chat", speak=False):
        self.cancel()
        self._n += 1
        cfg = self.get_cfg()
        t = Turn(self._n, text.strip(), channel, speak, int(cfg["voice"].get("max_speech_chars", 400)))
        self.turn = t
        threading.Thread(target=self._run, args=(t, cfg), daemon=True).start()
        return t

    def cancel(self):
        if self.turn is not None:
            self.turn.cancelled = True

    def clear_history(self):
        self.history = []

    # ── streaming helpers ─────────────────────────────────────────
    def _emit(self, t, delta):
        if t.cancelled or not delta:
            return
        if not t.answering:
            t.answering = True
            self.sink.state(t, "answering", "")
        t.answer += delta
        self.sink.text(t, delta)
        if t.speak and not t._speech_over:
            t._speech_buf += delta
            while not t._speech_over and (seg := pop_segment(t._speech_buf, t._first_seg)):
                piece, t._speech_buf = seg
                self._say(t, piece)

    def _say(self, t, piece):
        if not piece.strip() or t._speech_over:
            return
        if t._spoken and t._spoken + len(piece) > t.max_speech:
            t._speech_over = True
            self.sink.speak(t, "รายละเอียดที่เหลืออยู่ในหน้าแชทนะ")
            self.sink.notice(t, "overflow")
            return
        t._spoken += len(piece)
        t._first_seg = False
        self.sink.speak(t, piece)

    def _filler(self, t):
        if t.speak and not t._filler_said:
            t._filler_said = True
            self.sink.speak(t, random.choice(FILLERS))

    def _messages(self, t, rules):
        style = VOICE_STYLE if t.channel == "voice" else CHAT_STYLE
        system = "\n".join(x for x in (PERSONA, rules, style) if x)
        return ([{"role": "system", "content": system}] + self.history[-HISTORY_MESSAGES:]
                + [{"role": "user", "content": t.text}])

    def _llm_opts(self, t):
        return {"max_tokens": 260 if t.channel == "voice" else 1200, "temperature": 0.6,
                "on_text": lambda d: self._emit(t, d), "should_stop": lambda: t.cancelled}

    # ── routes ────────────────────────────────────────────────────
    def _ask_pika(self, t, pika, pk, question, stream_to_answer=False):
        self.sink.state(t, "searching", question)
        self._filler(t)

        def on_cites(c):
            t.citations = c
            self.sink.sources(t, c)
        ans, cites = pika.ask(pk["project_id"], question, pk.get("strategy") or None,
                              on_delta=(lambda d: self._emit(t, d)) if stream_to_answer else None,
                              on_citations=on_cites, should_stop=lambda: t.cancelled)
        if cites and cites is not t.citations:
            on_cites(cites)
        return ans

    def _pika_direct(self, t, pika, pk):
        ans = self._ask_pika(t, pika, pk, t.text, stream_to_answer=True)
        if not ans and not t.cancelled:
            self._emit(t, "ไม่เจอข้อมูลเรื่องนี้ในคลังความรู้นะ")

    def _pika_then_llm(self, t, pika, pk, llm):
        ans = self._ask_pika(t, pika, pk, t.text)
        if t.cancelled:
            return
        self.sink.state(t, "thinking", "")
        msgs = self._messages(t, RULES_CONTEXT)
        msgs.insert(-1, {"role": "system", "content":
                         "ข้อมูลจากคลังความรู้ Pika สำหรับคำถามนี้:\n" + (ans or "(ไม่พบข้อมูล)")[:6000]})
        try:
            llm.chat_stream(msgs, **self._llm_opts(t))
        except LLMError as ex:
            if t.answer:
                raise
            if ex.status == 401:
                self._rejected_llm_key = llm.api_key
            self.sink.notice(t, f"{ex} — แสดงคำตอบจาก Pika โดยตรง")
            self._emit(t, ans or "ไม่เจอข้อมูลเรื่องนี้ในคลังความรู้นะ")

    def _llm_with_tool(self, t, pika, pk, llm):
        msgs = self._messages(t, RULES_TOOL)
        tools = [ASK_PIKA_TOOL]
        try:
            text, calls = llm.chat_stream(msgs, tools=tools, **self._llm_opts(t))
        except LLMError as ex:
            if t.answer or t.cancelled:
                raise
            if ex.status == 400:     # model/proxy without tool support
                return self._pika_then_llm(t, pika, pk, llm)
            if ex.status == 401:
                self._rejected_llm_key = llm.api_key
            self.sink.notice(t, f"{ex} — ถาม Pika โดยตรงแทน")
            return self._pika_direct(t, pika, pk)
        if not calls or t.cancelled:
            return
        msgs.append({"role": "assistant", "content": text or None, "tool_calls": [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}} for c in calls]})
        for c in calls[:3]:
            try:
                q = json.loads(c["arguments"] or "{}").get("question") or t.text
            except ValueError:
                q = t.text
            try:
                ans = self._ask_pika(t, pika, pk, q)
                result = {"answer": (ans or "(ไม่พบข้อมูลในคลังความรู้)")[:6000],
                          "sources": [x.get("title") or x.get("file_path") for x in t.citations[:6]]}
            except PikaError as ex:
                result = {"error": str(ex)}
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": json.dumps(result, ensure_ascii=False)})
            if t.cancelled:
                return
        self.sink.state(t, "thinking", "")
        if t.answer and not t.answer.endswith("\n"):
            self._emit(t, "\n")
        llm.chat_stream(msgs, tools=tools, tool_choice="none", **self._llm_opts(t))

    def _llm_only(self, t, llm):
        llm.chat_stream(self._messages(t, ""), **self._llm_opts(t))

    def _run(self, t, cfg):
        pk, lc = cfg["pika"], cfg["llm"]
        llm = LLMClient(lc["base_url"], lc["api_key"], lc["model"])
        pika = PikaClient(pk["base_url"], pk["api_key"])
        pika_ok = pika.configured and bool(pk.get("project_id"))
        mode = pk.get("mode", "auto")
        if pika_ok and llm.api_key and llm.api_key == self._rejected_llm_key:
            llm.api_key = ""                     # known-bad key: go straight to Pika
        ok, error = True, ""
        try:
            self.sink.state(t, "thinking", "")
            if not llm.configured and not pika_ok:
                raise RuntimeError("ยังไม่ได้ตั้งค่า — เปิด ⚙ ตั้งค่า แล้วใส่ Pika API key (และ LLM key ถ้ามี)")
            if pika_ok and (mode == "direct" or not llm.configured):
                self._pika_direct(t, pika, pk)
            elif pika_ok and mode == "always":
                self._pika_then_llm(t, pika, pk, llm)
            elif pika_ok and mode == "auto":
                self._llm_with_tool(t, pika, pk, llm)
            else:
                self._llm_only(t, llm)
        except (LLMError, PikaError, RuntimeError) as ex:
            ok, error = False, str(ex)
        except Exception as ex:                       # never leave the pet stuck
            ok, error = False, f"{type(ex).__name__}: {ex}"
            print(f"[assistant] unexpected error: {error}")
        if ok and not t.cancelled:
            if t.speak and t._speech_buf.strip():
                self._say(t, t._speech_buf)
            if t.answer.strip():
                self.history += [{"role": "user", "content": t.text},
                                 {"role": "assistant", "content": t.answer.strip()[:1500]}]
                self.history = self.history[-HISTORY_MESSAGES:]
        t.finished = True
        self.sink.done(t, ok, error)

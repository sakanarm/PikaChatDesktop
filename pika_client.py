"""
Client for the Pika App-to-app API (https://dmhub.mfec.dev/Pika/api/v1/docs).
Read-only: it only asks / searches the knowledge base and never changes anything in Pika.

    pika = PikaClient(base_url, api_key)
    pika.me()                      -> key info + project {id, name, ...}
    pika.ask(project, "question", on_delta=print)   -> (answer, citations)

/ask streams Server-Sent Events:
    event: citations   data: [{"file_path", "title", "snippet", "node_type"}, ...]
    event: delta       data: "<JSON string chunk of the markdown answer>"
    event: done        data: {}
"""
import json
import urllib.parse

import net


class PikaError(Exception):
    pass


def _friendly(ex):
    if isinstance(ex, net.HTTPError):
        if ex.status == 401:
            return "Pika API key ไม่ถูกต้องหรือถูกยกเลิกแล้ว"
        if ex.status == 403:
            return "Pika API key นี้ไม่มีสิทธิ์ใช้งาน (ต้องมี scope 'ask')"
        if ex.status == 404:
            return "ไม่พบโปรเจกต์ใน Pika (ตรวจ Project ID)"
        return f"Pika ตอบกลับผิดพลาด ({ex.status}): {ex.message}"
    if isinstance(ex, net.NetworkError):
        return f"ติดต่อ Pika ไม่ได้: {ex}"
    return str(ex)


def clean_title(t):
    t = (t or "").strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    return t


class PikaClient:
    def __init__(self, base_url, api_key, timeout=120):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.base_url and self.api_key)

    def _url(self, path):
        return f"{self.base_url}/api/v1{path}"

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    def _project_path(self, project_id, tail):
        return f"/projects/{urllib.parse.quote(project_id, safe='')}{tail}"

    def me(self):
        try:
            return net.get_json(self._url("/me"), self._headers(), timeout=20)
        except Exception as ex:
            raise PikaError(_friendly(ex)) from None

    def strategies(self, project_id):
        try:
            j = net.get_json(self._url(self._project_path(project_id, "/strategies")),
                             self._headers(), timeout=20)
        except Exception as ex:
            raise PikaError(_friendly(ex)) from None
        items = j.get("strategies", j) if isinstance(j, dict) else j
        return [s for s in (items or []) if isinstance(s, dict) and s.get("ask", True)]

    def search(self, project_id, query, top_k=5, strategy=None):
        payload = {"query": query, "top_k": top_k}
        if strategy:
            payload["strategy"] = strategy
        try:
            return net.post_json(self._url(self._project_path(project_id, "/search")), payload,
                                 self._headers(), timeout=60)
        except Exception as ex:
            raise PikaError(_friendly(ex)) from None

    def ask(self, project_id, question, strategy=None, on_delta=None, on_citations=None,
            should_stop=None):
        """Streams the answer. Returns (answer_markdown, citations)."""
        if not self.configured:
            raise PikaError("ยังไม่ได้ใส่ Pika API key (เปิด ⚙ ตั้งค่า)")
        if not project_id:
            raise PikaError("ยังไม่ได้เลือกโปรเจกต์ Pika (เปิด ⚙ ตั้งค่า แล้วกด ตรวจสอบ)")
        payload = {"question": question, "stream": True}
        if strategy:
            payload["strategy"] = strategy
        answer, citations = [], []
        url = self._url(self._project_path(project_id, "/ask"))
        try:
            for event, data in net.post_sse(url, payload, self._headers(), self.timeout, should_stop):
                if event == "json":                       # non-streaming fallback
                    j = json.loads(data or "{}")
                    text = j.get("answer") or j.get("text") or j.get("content") or ""
                    citations = j.get("citations") or j.get("sources") or []
                    answer.append(text)
                    if on_delta and text:
                        on_delta(text)
                    break
                if event == "citations":
                    try:
                        items = json.loads(data)
                    except ValueError:
                        items = []
                    if isinstance(items, dict):
                        items = items.get("citations") or items.get("items") or []
                    citations = [dict(c, title=clean_title(c.get("title"))) for c in items
                                 if isinstance(c, dict)]
                    if on_citations:
                        on_citations(citations)
                elif event in ("delta", "message", "token"):
                    try:
                        piece = json.loads(data)
                    except ValueError:
                        piece = data
                    if isinstance(piece, dict):
                        piece = piece.get("text") or piece.get("delta") or piece.get("content") or ""
                    if isinstance(piece, str) and piece:
                        answer.append(piece)
                        if on_delta:
                            on_delta(piece)
                elif event == "error":
                    try:
                        err = json.loads(data)
                        msg = err.get("message") or err.get("error") if isinstance(err, dict) else err
                    except ValueError:
                        msg = data
                    raise PikaError(f"Pika แจ้งข้อผิดพลาด: {msg}")
                elif event == "done":
                    break
        except PikaError:
            raise
        except Exception as ex:
            raise PikaError(_friendly(ex)) from None
        return "".join(answer).strip(), citations

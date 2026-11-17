"""
Minimal OpenAI-compatible client (LiteLLM proxy) on the standard library:
streaming chat completions with tool calls, model list, and speech-to-text.
"""
import io
import json
import time
import wave

import net


class LLMError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _friendly(ex):
    if isinstance(ex, net.HTTPError):
        if ex.status == 401:
            return LLMError("LLM API key ไม่ถูกต้องหรือหมดอายุแล้ว (เปิด ⚙ ตั้งค่า)", 401)
        if ex.status == 404:
            return LLMError(f"ไม่พบ endpoint/โมเดลนี้บน LLM server: {ex.message}", 404)
        if ex.status == 429:
            return LLMError("LLM ถูกจำกัดการใช้งานชั่วคราว (rate limit / budget)", 429)
        return LLMError(f"LLM ตอบกลับผิดพลาด ({ex.status}): {ex.message}", ex.status)
    if isinstance(ex, net.NetworkError):
        return LLMError(f"ติดต่อ LLM server ไม่ได้: {ex}")
    return LLMError(str(ex))


def pcm16_to_wav(pcm, sample_rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class LLMClient:
    def __init__(self, base_url, api_key, model, timeout=60):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = model
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.base_url and self.api_key and self.model)

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def models(self):
        try:
            j = net.get_json(self.base_url + "/models", self._headers(), timeout=20)
        except Exception as ex:
            raise _friendly(ex) from None
        return sorted({m.get("id") for m in (j or {}).get("data", []) if m.get("id")})

    def chat_stream(self, messages, tools=None, tool_choice=None, max_tokens=None,
                    temperature=None, on_text=None, should_stop=None):
        """Returns (text, tool_calls). tool_calls: [{"id", "name", "arguments"(str)}]."""
        payload = {"model": self.model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        text, calls = [], {}
        try:
            for _event, data in net.post_sse(self.base_url + "/chat/completions", payload,
                                             self._headers(), self.timeout, should_stop):
                if data.strip() == "[DONE]":
                    break
                try:
                    j = json.loads(data)
                except ValueError:
                    continue
                if isinstance(j, dict) and j.get("error"):
                    err = j["error"]
                    raise LLMError(err.get("message", str(err)) if isinstance(err, dict) else str(err))
                for ch in (j.get("choices") or [])[:1]:
                    delta = ch.get("delta") or ch.get("message") or {}
                    piece = delta.get("content")
                    if piece:
                        text.append(piece)
                        if on_text:
                            on_text(piece)
                    for tc in delta.get("tool_calls") or []:
                        c = calls.setdefault(tc.get("index", len(calls)),
                                             {"id": "", "name": "", "arguments": ""})
                        c["id"] = tc.get("id") or c["id"]
                        fn = tc.get("function") or {}
                        c["name"] = fn.get("name") or c["name"]
                        c["arguments"] += fn.get("arguments") or ""
        except LLMError:
            raise
        except Exception as ex:
            raise _friendly(ex) from None
        out = [calls[k] for k in sorted(calls)]
        for i, c in enumerate(out):
            c["id"] = c["id"] or f"call_{int(time.time())}_{i}"
        return "".join(text), out

    def ping(self):
        t = time.time()
        text, _ = self.chat_stream([{"role": "user", "content": "ตอบคำว่า OK"}], max_tokens=5)
        return text.strip(), time.time() - t

    def transcribe(self, pcm16, model, language="th", prompt=None, sample_rate=16000):
        fields = {"model": model, "response_format": "json"}
        if language:
            fields["language"] = language
        if prompt:
            fields["prompt"] = prompt
        files = {"file": ("speech.wav", pcm16_to_wav(pcm16, sample_rate), "audio/wav")}
        try:
            j = net.post_multipart(self.base_url + "/audio/transcriptions", fields, files,
                                   self._headers(), timeout=60)
        except Exception as ex:
            raise _friendly(ex) from None
        return ((j or {}).get("text") or "").strip()

"""
Tiny HTTP helpers on the standard library only (no requests/httpx/openai), so the app
stays small. urllib picks up the Windows proxy settings and the Windows certificate store.
"""
import io
import json
import urllib.error
import urllib.request
import uuid

from config import APP_NAME, VERSION

USER_AGENT = f"{APP_NAME}/{VERSION}"


class HTTPError(Exception):
    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class NetworkError(Exception):
    pass


def _error_message(raw, default=""):
    try:
        j = json.loads(raw)
        err = j.get("error", j) if isinstance(j, dict) else j
        if isinstance(err, dict):
            return str(err.get("message") or err.get("detail") or json.dumps(err, ensure_ascii=False))
        if isinstance(err, str):
            return err
        if isinstance(j, dict) and "detail" in j:
            return str(j["detail"])
    except Exception:
        pass
    text = raw[:300].decode("utf-8", "replace").strip() if raw else ""
    return text or str(default)


def open_url(method, url, headers=None, body=None, timeout=30):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", USER_AGENT)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except Exception:
            raw = b""
        raise HTTPError(e.code, _error_message(raw, e.reason)) from None
    except urllib.error.URLError as e:
        raise NetworkError(str(e.reason)) from None
    except (TimeoutError, OSError) as e:
        raise NetworkError(str(e) or type(e).__name__) from None


def get_json(url, headers=None, timeout=20):
    with open_url("GET", url, headers, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def post_json(url, payload, headers=None, timeout=60):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    with open_url("POST", url, h, body, timeout) as r:
        return json.loads(r.read() or b"null")


def post_sse(url, payload, headers=None, timeout=90, should_stop=None):
    """POST and iterate a text/event-stream: yields (event, data) strings.
    If the server answers with plain JSON instead, yields ("json", body)."""
    h = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    h.update(headers or {})
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = open_url("POST", url, h, body, timeout)
    try:
        ctype = resp.headers.get("Content-Type", "")
        if "event-stream" not in ctype and "json" in ctype:
            yield "json", resp.read().decode("utf-8", "replace")
            return
        event, data = None, []
        while True:
            if should_stop and should_stop():
                return
            try:
                raw = resp.readline()
            except (TimeoutError, OSError) as e:
                raise NetworkError(str(e) or "read timed out") from None
            if not raw:
                if data:
                    yield event or "message", "\n".join(data)
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                if data:
                    yield event or "message", "\n".join(data)
                event, data = None, []
            elif line.startswith(":"):
                continue
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:][1:] if line[5:6] == " " else line[5:])
    finally:
        resp.close()


def post_multipart(url, fields, files, headers=None, timeout=60):
    """files: {name: (filename, bytes, content_type)}"""
    boundary = "----pika" + uuid.uuid4().hex
    buf = io.BytesIO()
    for k, v in fields.items():
        buf.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        buf.write(str(v).encode("utf-8") + b"\r\n")
    for k, (fname, data, ctype) in files.items():
        buf.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'
                  f"Content-Type: {ctype}\r\n\r\n".encode())
        buf.write(data + b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    h = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    h.update(headers or {})
    with open_url("POST", url, h, buf.getvalue(), timeout) as r:
        return json.loads(r.read() or b"null")

"""Text helpers: split streamed text into speakable pieces, clean markdown/emoji for TTS."""
import re

_HARD_BREAK = re.compile(r"[.!?。！？\n~]+")
_NOT_SPEAKABLE = re.compile(r"[^฀-๿a-zA-Z0-9\s.,!?%:+\-]")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_MD_MARKS = re.compile(r"(\*\*|__|`{1,3}|^#{1,6}\s*|^\s*[-*•]\s+|^\s*\d+\.\s+|^>\s*)", re.M)


def pop_segment(buf, first):
    """Split streamed LLM text into speakable pieces. Returns (segment, rest) or None.
    Thai has no full stop, so besides punctuation we also cut at a space once the piece
    is long enough (shorter for the first piece so the pet starts talking sooner)."""
    m = _HARD_BREAK.search(buf)
    if m and len(buf[:m.start()].strip()) >= 2:
        return buf[:m.end()], buf[m.end():]
    limit = 12 if first else 40
    if len(buf) >= limit:
        i = buf.rfind(" ")
        if i >= 6:
            return buf[:i], buf[i + 1:]
    return None


def strip_markdown(text):
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    return _MD_MARKS.sub("", text)


def clean_for_tts(text):
    text = strip_markdown(text).replace("~", " ")
    text = _NOT_SPEAKABLE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def shorten(text, n):
    text = re.sub(r"\s+", " ", strip_markdown(text)).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"

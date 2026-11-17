"""
User settings, stored per Windows user in %APPDATA%\\PikaChatDesktop\\config.json.
API keys live only there (or in env vars) - never in the source tree.
"""
import copy
import json
import os
import sys

APP_NAME = "PikaChatDesktop"
APP_TITLE = "Pika Chat Desktop"
VERSION = "1.0.0"


def _config_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME)


CONFIG_DIR = _config_dir()
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "pika": {
        "base_url": "https://dmhub.mfec.dev/Pika",
        "api_key": "",
        "project_id": "",
        "project_name": "",
        "strategy": "",          # "" = server default
        # auto   : the LLM decides when to look things up in Pika (needs an LLM key)
        # always : every question goes to Pika first, the LLM turns it into a short reply
        # direct : Pika answers by itself (no LLM key needed)
        # off    : LLM only
        "mode": "auto",
    },
    "llm": {
        "base_url": "https://gpt.mfec.co.th/litellm",
        "api_key": "",
        "model": "gpt-4.1-mini",
    },
    "voice": {
        # auto  : local OpenThai model if installed, otherwise cloud
        # cloud : OpenAI-compatible /audio/transcriptions on the LLM server (lite, no download)
        # local : OpenThai2.0 ASR on this PC (optional ~1 GB download, live captions)
        "stt": "auto",
        "stt_model": "whisper-1",
        "tts_voice": "th-TH-NiwatNeural",
        "tts_rate": "+10%",
        "tts_pitch": "+20Hz",
        "silence_ms": 700,
        "speak_chat_replies": False,
        "max_speech_chars": 400,
    },
    "pet": {
        "size": 0,               # 0 = auto (by screen DPI), or 110 / 150 / 200
        "walk": True,
        "chat_on_top": True,
        "autostart": False,
    },
}

ENV_KEYS = {("llm", "api_key"): "LITELLM_API_KEY", ("pika", "api_key"): "PIKA_API_KEY"}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    data = {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        pass
    except Exception as ex:
        print(f"[config] could not read {CONFIG_PATH}: {ex}")
    cfg = _merge(DEFAULTS, data)
    for (sec, key), env in ENV_KEYS.items():
        if not cfg[sec][key] and os.environ.get(env):
            cfg[sec][key] = os.environ[env]
    return cfg


def save(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def resource_path(*parts):
    """Path to bundled files (works from source and from a PyInstaller exe)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def mask_key(key):
    return (key[:10] + "…" + key[-4:]) if key and len(key) > 16 else ("…" if key else "")

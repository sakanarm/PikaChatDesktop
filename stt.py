"""
Speech-to-text engines for MicListener.

CloudSTT  OpenAI-compatible /audio/transcriptions on the LLM server (LiteLLM).
          Nothing to download - the default for the lite build.
LocalSTT  iApp OpenThai2.0-ASR on this PC (asr.py). Optional: needs
          `pip install -r requirements-local-asr.txt` + `python download_models.py`
          (~1 GB). Gives live captions while you talk.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_MODEL = os.path.join(HERE, "models", "openthai2-asr-int8", "decoder_joint.onnx")


class CloudSTT:
    realtime = False
    name = "cloud"

    def __init__(self, llm, model, language="th"):
        self.llm, self.model, self.language = llm, model, language

    def transcribe(self, pcm16):
        return self.llm.transcribe(pcm16, self.model, self.language, prompt="Pika, PIKAWIKI")


class LocalSTT:
    realtime = True
    name = "local"

    def __init__(self):
        import numpy as np
        from asr import OpenThaiASR
        self._np = np
        self.asr = OpenThaiASR(num_threads=4)

    def transcribe(self, pcm16):
        np = self._np
        return self.asr.transcribe(np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0)


def local_available():
    return (os.path.exists(LOCAL_MODEL) and importlib.util.find_spec("onnxruntime") is not None
            and importlib.util.find_spec("numpy") is not None)


def create(voice_cfg, llm):
    """Returns an engine or raises RuntimeError with a Thai message for the user."""
    choice = voice_cfg.get("stt", "auto")
    if choice == "local" or (choice == "auto" and local_available()):
        if not local_available():
            raise RuntimeError("ยังไม่ได้ติดตั้งโมเดลถอดเสียงในเครื่อง (ดู README: local ASR)")
        return LocalSTT()
    if not llm.configured:
        raise RuntimeError("การฟังเสียงต้องใช้ LLM API key (ถอดเสียงผ่าน server) - ใส่ใน ⚙ ตั้งค่า")
    return CloudSTT(llm, voice_cfg.get("stt_model") or "whisper-1")

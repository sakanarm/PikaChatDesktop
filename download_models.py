"""Download the speech models into ./models (run once: python download_models.py)."""
import os
import urllib.request
import zipfile

from huggingface_hub import hf_hub_download

BASE = os.path.dirname(os.path.abspath(__file__))
ASR_DIR = os.path.join(BASE, "models", "openthai2-asr-int8")
VAD_PATH = os.path.join(BASE, "models", "silero_vad.onnx")
VAD_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"

os.makedirs(ASR_DIR, exist_ok=True)
if not os.path.exists(os.path.join(ASR_DIR, "encoder.int8.onnx")):
    repo = "iapp/OpenThai2.0-ASR-Streaming-ONNX"
    hf_hub_download(repo, "encoder.int8.onnx.data", local_dir=ASR_DIR)  # ~0.9 GB
    zip_path = hf_hub_download(repo, "openthai2.0-asr-streaming-int8.asr.zip", local_dir=ASR_DIR)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(ASR_DIR)  # encoder.int8.onnx, decoder_joint.onnx, tokens.txt
    os.remove(zip_path)
if not os.path.exists(VAD_PATH):
    urllib.request.urlretrieve(VAD_URL, VAD_PATH)
print("models ready:", sorted(os.listdir(ASR_DIR)), os.path.basename(VAD_PATH))

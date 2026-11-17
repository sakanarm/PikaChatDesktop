"""
Thai streaming speech recognition for the desktop pet.

- OpenThai2.0-ASR-Streaming (iApp) ONNX int8 export, run with onnxruntime on CPU
  https://huggingface.co/iapp/OpenThai2.0-ASR-Streaming-ONNX
- Silero VAD (models/silero_vad.onnx) to cut speech at pauses

The ONNX encoder attends over the whole segment (it is not the cache-aware NeMo graph),
so "streaming" here means: VAD cuts the mic audio into utterances, and the growing
utterance is re-transcribed every few hundred ms for live partial text.

No torch / NeMo needed: the log-mel front end is re-implemented in numpy to match
NeMo's AudioToMelSpectrogramPreprocessor (16 kHz, 128 mels, 25 ms Hann, 10 ms hop,
pre-emphasis 0.97, n_fft 512, slaney mel, log(x + 2^-24), no normalisation).
"""
import os
import numpy as np
import onnxruntime as ort

SAMPLE_RATE = 16000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_DIR = os.path.join(BASE_DIR, "models", "openthai2-asr-int8")

PROMPT_THAI = 32       # "th-TH": Thai script
PROMPT_THAI_MIX = 63   # "th-mix": English words kept in Latin letters


# ─── Log-mel front end (NeMo compatible) ─────────────────────────
def _hz_to_mel(f):
    f = np.asarray(f, dtype=np.float64)
    f_sp, min_log_hz, min_log_mel = 200.0 / 3, 1000.0, 15.0
    logstep = np.log(6.4) / 27.0
    mel = f / f_sp
    return np.where(f >= min_log_hz,
                    min_log_mel + np.log(np.maximum(f, 1e-10) / min_log_hz) / logstep, mel)


def _mel_to_hz(m):
    m = np.asarray(m, dtype=np.float64)
    f_sp, min_log_hz, min_log_mel = 200.0 / 3, 1000.0, 15.0
    logstep = np.log(6.4) / 27.0
    f = f_sp * m
    return np.where(m >= min_log_mel, min_log_hz * np.exp(logstep * (m - min_log_mel)), f)


def _slaney_mel_filterbank(sr, n_fft, n_mels, fmin=0.0, fmax=None):
    """Same as librosa.filters.mel(sr, n_fft, n_mels, fmin, fmax, htk=False, norm='slaney')."""
    fmax = fmax or sr / 2
    fftfreqs = np.linspace(0, sr / 2, 1 + n_fft // 2)
    mel_f = _mel_to_hz(np.linspace(_hz_to_mel(fmin), _hz_to_mel(fmax), n_mels + 2))
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fftfreqs[None, :]
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    weights = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (mel_f[2:n_mels + 2] - mel_f[:n_mels])
    return (weights * enorm[:, None]).astype(np.float32)


class LogMel:
    def __init__(self, sr=SAMPLE_RATE, n_fft=512, win=400, hop=160, n_mels=128, preemph=0.97):
        self.n_fft, self.hop, self.preemph = n_fft, hop, preemph
        # NeMo: torch.hann_window(400, periodic=False), zero padded (centred) to n_fft
        w = np.hanning(win).astype(np.float32)
        left = (n_fft - win) // 2
        self.window = np.zeros(n_fft, dtype=np.float32)
        self.window[left:left + win] = w
        self.fb = _slaney_mel_filterbank(sr, n_fft, n_mels)

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        """audio float32 [-1, 1] mono 16 kHz -> features [128, T]."""
        x = audio.astype(np.float32)
        x = np.concatenate([x[:1], x[1:] - self.preemph * x[:-1]])
        pad = self.n_fft // 2  # torch.stft(center=True, pad_mode="constant")
        x = np.pad(x, (pad, pad))
        n_frames = 1 + (len(x) - self.n_fft) // self.hop
        idx = np.arange(self.n_fft)[None, :] + self.hop * np.arange(n_frames)[:, None]
        frames = x[idx] * self.window
        power = np.abs(np.fft.rfft(frames, n=self.n_fft, axis=1)) ** 2
        mel = power.astype(np.float32) @ self.fb.T
        return np.log(mel + 2 ** -24).T.astype(np.float32)


# ─── OpenThai 2.0 ASR (RNN-T, greedy) ─────────────────────────────
class OpenThaiASR:
    def __init__(self, model_dir=DEFAULT_MODEL_DIR, num_threads=4, prompt_index=PROMPT_THAI):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = num_threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        enc_path = os.path.join(model_dir, "encoder.int8.onnx")
        if not os.path.exists(enc_path):
            enc_path = os.path.join(model_dir, "encoder.onnx")
        self.encoder = ort.InferenceSession(enc_path, opts, providers=["CPUExecutionProvider"])
        dopts = ort.SessionOptions()
        dopts.intra_op_num_threads = 1
        dopts.inter_op_num_threads = 1
        self.decoder = ort.InferenceSession(os.path.join(model_dir, "decoder_joint.onnx"), dopts,
                                            providers=["CPUExecutionProvider"])
        with open(os.path.join(model_dir, "tokens.txt"), encoding="utf-8") as f:
            self.tokens = [line.rstrip("\n") for line in f]
        self.blank = len(self.tokens)  # 14988, last joint output
        self.prompt_index = prompt_index
        self.frontend = LogMel()

    def transcribe(self, audio: np.ndarray, blank_bias=None) -> str:
        if len(audio) < SAMPLE_RATE // 5:
            return ""
        if blank_bias is None:
            # values from the model card: -1.0 normally, -2.5 for clips under 2 s
            blank_bias = -2.5 if len(audio) < 2 * SAMPLE_RATE else -1.0
        feats = self.frontend(audio)[None]  # [1, 128, T]
        enc, enc_len = self.encoder.run(None, {
            "audio_signal": feats,
            "length": np.array([feats.shape[2]], dtype=np.int64),
            "prompt_index": np.array([self.prompt_index], dtype=np.int64),
        })
        return self._decode(enc[0, :int(enc_len[0])], blank_bias)

    def _decode(self, enc: np.ndarray, blank_bias: float, max_symbols=8) -> str:
        s1 = np.zeros((2, 1, 640), dtype=np.float32)
        s2 = np.zeros((2, 1, 640), dtype=np.float32)
        last = self.blank
        target_len = np.array([1], dtype=np.int32)
        out_ids = []
        for t in range(enc.shape[0]):
            frame = enc[t][None, :, None]  # [1, 1024, 1]
            for _ in range(max_symbols):
                logits, _, n1, n2 = self.decoder.run(None, {
                    "encoder_outputs": frame,
                    "targets": np.array([[last]], dtype=np.int32),
                    "target_length": target_len,
                    "input_states_1": s1,
                    "input_states_2": s2,
                })
                scores = logits.reshape(-1)
                scores[self.blank] += blank_bias
                k = int(scores.argmax())
                if k == self.blank:
                    break
                out_ids.append(k)
                last, s1, s2 = k, n1, n2
        return self._detokenize(out_ids)

    def _detokenize(self, ids) -> str:
        pieces = []
        for i in ids:
            p = self.tokens[i] if i < len(self.tokens) else ""
            if p.startswith("<") and p.endswith(">"):  # language tags / <unk>
                continue
            pieces.append(p)
        return "".join(pieces).replace("▁", " ").strip()


# ─── Silero VAD (ONNX, no torch) ──────────────────────────────────
class SileroVAD:
    CHUNK = 512    # 32 ms at 16 kHz
    CONTEXT = 64

    def __init__(self, path=os.path.join(BASE_DIR, "models", "silero_vad.onnx")):
        if not os.path.exists(path):  # fall back to the copy inside the silero-vad pip package
            import silero_vad
            path = os.path.join(os.path.dirname(silero_vad.__file__), "data", "silero_vad.onnx")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
        self.sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def __call__(self, chunk: np.ndarray) -> float:
        """chunk: 512 float32 samples -> speech probability."""
        x = np.concatenate([self.context, chunk.reshape(1, -1).astype(np.float32)], axis=1)
        out, self.state = self.session.run(None, {"input": x, "state": self.state, "sr": self.sr})
        self.context = x[:, -self.CONTEXT:]
        return float(out[0, 0])

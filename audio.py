"""
Audio for the pet, on miniaudio only (one small wheel: capture + playback + mp3 decode,
no numpy / sounddevice needed).

Player       16-bit mono PCM -> speakers. The device is opened on demand and closed when
             idle, so it never keeps Windows awake.
Speaker      text -> edge-tts (Thai neural voice) -> Player. Pieces are synthesised
             concurrently and played strictly in order.
MicListener  microphone -> VAD -> utterances -> speech-to-text engine (see stt.py).
             Uses Silero VAD when the optional local-ASR extras are installed, otherwise
             a light adaptive energy VAD in pure Python.
"""
import array
import asyncio
import math
import queue
import threading
import time
from collections import deque

import miniaudio

from textutil import clean_for_tts

MIC_RATE = 16000
CHUNK = 512            # 32 ms at 16 kHz
TTS_RATE = 24000


# ─── playback ─────────────────────────────────────────────────────
class Player:
    def __init__(self, sample_rate=TTS_RATE, idle_close_s=2.0):
        self.rate = sample_rate
        self.idle_close_s = idle_close_s
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._dev = None
        self._last_audio = 0.0
        self.playing = False
        threading.Thread(target=self._reaper, daemon=True).start()

    def _pump(self):
        frames = yield b""
        while True:
            with self._lock:
                n = frames * 2
                chunk = bytes(self._buf[:n])
                del self._buf[:n]
            if chunk:
                self._last_audio = time.time()
            self.playing = bool(chunk)
            frames = yield chunk

    def _ensure_device(self):
        if self._dev is None:
            dev = miniaudio.PlaybackDevice(output_format=miniaudio.SampleFormat.SIGNED16,
                                           nchannels=1, sample_rate=self.rate,
                                           buffersize_msec=40, app_name="Pika")
            gen = self._pump()
            next(gen)
            dev.start(gen)
            self._dev = dev

    def play(self, pcm):
        """Queue PCM bytes (s16 mono at self.rate); returns immediately."""
        with self._lock:
            self._buf += pcm
            self._last_audio = time.time()
            self.playing = True
            self._ensure_device()

    def busy(self):
        with self._lock:
            return bool(self._buf)

    def wait(self, cancelled=lambda: False):
        while self.busy() and not cancelled():
            time.sleep(0.02)
        if not cancelled():
            time.sleep(0.09)       # let the device buffer drain
        self.playing = False

    def stop(self):
        with self._lock:
            self._buf.clear()
        self.playing = False

    def _reaper(self):
        while True:
            time.sleep(0.5)
            with self._lock:
                if self._dev is not None and not self._buf and \
                        time.time() - self._last_audio > self.idle_close_s:
                    dev, self._dev = self._dev, None
                else:
                    dev = None
            if dev is not None:
                try:
                    dev.close()
                except Exception:
                    pass


# ─── text-to-speech ───────────────────────────────────────────────
class Speaker:
    """say() text pieces; end_turn(cb) runs cb after everything queued has played."""

    def __init__(self, voice="th-TH-NiwatNeural", rate="+10%", pitch="+20Hz",
                 timeout_s=5.0, retries=2):
        import edge_tts
        self._edge_tts = edge_tts
        self.voice, self.rate, self.pitch = voice, rate, pitch
        self.timeout_s, self.retries = timeout_s, retries
        self.player = Player(TTS_RATE)
        self._gen = 0
        self._pending = 0
        self._play_q = queue.Queue()
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()

    @property
    def playing(self):
        return self.player.playing

    @property
    def active(self):
        """True while anything is queued or playing."""
        return self._pending > 0 or self.player.busy()

    def configure(self, voice, rate, pitch):
        self.voice, self.rate, self.pitch = voice, rate, pitch

    def warmup(self):
        asyncio.run_coroutine_threadsafe(
            self._synth("สวัสดี", (self.voice, self.rate, self.pitch)), self._loop)

    def say(self, text, voice=None, rate=None, pitch=None):
        text = clean_for_tts(text)
        if text:
            opts = (voice or self.voice, rate or self.rate, pitch or self.pitch)
            fut = asyncio.run_coroutine_threadsafe(self._synth(text, opts), self._loop)
            self._pending += 1
            self._play_q.put((self._gen, fut))

    def end_turn(self, callback):
        self._play_q.put((self._gen, callback))

    def stop(self):
        self._gen += 1
        self.player.stop()

    async def _synth_once(self, text, opts):
        voice, rate, pitch = opts
        data = bytearray()
        comm = self._edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        async for c in comm.stream():
            if c["type"] == "audio":
                data += c["data"]
        dec = miniaudio.decode(bytes(data), output_format=miniaudio.SampleFormat.SIGNED16,
                               nchannels=1, sample_rate=TTS_RATE)
        return dec.samples.tobytes()

    async def _synth(self, text, opts):
        for attempt in range(self.retries):
            t = time.time()
            try:
                pcm = await asyncio.wait_for(self._synth_once(text, opts), self.timeout_s * (attempt + 1))
                print(f"[tts] {time.time() - t:.2f}s  {text}")
                return pcm
            except Exception as ex:
                print(f"[tts] attempt {attempt + 1} failed ({type(ex).__name__}): {text}")
        return None

    def _play_loop(self):
        while True:
            gen, item = self._play_q.get()
            if callable(item):
                if gen == self._gen:
                    try:
                        item()
                    except Exception as ex:
                        print(f"[tts] callback error: {ex}")
                continue
            try:
                pcm = item.result(timeout=30) if gen == self._gen else None
            except Exception:
                pcm = None
            finally:
                if gen != self._gen:
                    item.cancel()
            if pcm and gen == self._gen:
                self.player.play(pcm)
                self.player.wait(lambda: gen != self._gen)
            self._pending = max(0, self._pending - 1)


# ─── voice activity detection ─────────────────────────────────────
class EnergyVAD:
    """Adaptive loudness gate (pure Python). Returns a pseudo speech probability."""

    def __init__(self, ratio=3.2, min_level=420.0):
        self.ratio, self.min_level = ratio, min_level
        self.floor = 250.0

    def reset(self):
        pass  # keep the learned noise floor

    def __call__(self, chunk):
        rms = math.sqrt(sum(s * s for s in chunk) / max(1, len(chunk)))
        thr = max(self.floor * self.ratio, self.min_level)
        if rms < thr:   # learn the background: quick to go down, slow to go up
            k = 0.15 if rms < self.floor else 0.02
            self.floor = max(40.0, (1 - k) * self.floor + k * rms)
        return 1.0 if rms >= thr else (0.4 if rms >= 0.7 * thr else 0.0)


def make_vad():
    try:
        import numpy as np
        from asr import SileroVAD
        silero = SileroVAD()

        def vad(chunk):
            return silero(np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0)
        vad.reset = silero.reset
        print("[mic] Silero VAD")
        return vad
    except Exception:
        return EnergyVAD()


# ─── microphone ───────────────────────────────────────────────────
class _Utterance:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.n = sum(len(c) for c in self.chunks)
        self.last_voice = self.n
        self.voiced = 0
        self.ended = False
        self.end_len = 0
        self.decoded_len = 0
        self.last_text = None
        self.t_end = 0.0

    def pcm(self, n):
        a = array.array("h")
        for c in self.chunks:
            a.extend(c)
        return a[:n].tobytes()


class MicListener:
    """Continuous listening. stt.transcribe(pcm16_bytes) -> text; if stt.realtime, the
    growing utterance is re-transcribed for live captions. Callbacks run on worker threads."""

    def __init__(self, stt, on_speech_start=None, on_partial=None, on_final=None,
                 on_error=None, silence_ms=700, max_utterance_s=15.0, partial_step_s=0.3):
        self.stt = stt
        self.on_speech_start = on_speech_start or (lambda: None)
        self.on_partial = on_partial or (lambda text: None)
        self.on_final = on_final or (lambda text: None)
        self.on_error = on_error or (lambda msg: None)
        self.silence = int(silence_ms / 1000 * MIC_RATE)
        self.max_samples = int(max_utterance_s * MIC_RATE)
        self.partial_step = int(partial_step_s * MIC_RATE)
        self.tail = int(0.2 * MIC_RATE)
        self.min_voiced = int(0.25 * MIC_RATE)
        self.vad = make_vad()
        self._q = queue.Queue()
        self._cond = threading.Condition()
        self._utt = None
        self._running = False
        self._run_id = 0
        self._paused = False
        self._reset = False
        self._dev = None

    @property
    def running(self):
        return self._running

    def start(self):
        if self._running:
            return
        dev = miniaudio.CaptureDevice(input_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                                      sample_rate=MIC_RATE, buffersize_msec=32, app_name="Pika")
        gen = self._sink()
        next(gen)
        dev.start(gen)
        self._dev = dev
        self._run_id += 1
        self._running = True
        self._paused = False
        self._reset = True
        for target in (self._vad_loop, self._asr_loop):
            threading.Thread(target=target, args=(self._run_id,), daemon=True).start()

    def stop(self):
        self._running = False
        self._run_id += 1
        with self._cond:
            self._utt = None
            self._cond.notify_all()
        dev, self._dev = self._dev, None
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass

    def pause(self):
        self._paused = True
        with self._cond:
            self._utt = None

    def resume(self):
        self._reset = True
        self._paused = False

    def _sink(self):
        while True:
            data = yield
            if data is not None and not self._paused:
                self._q.put(data)

    def _alive(self, run_id):
        return self._running and run_id == self._run_id

    def _vad_loop(self, run_id):
        preroll = deque(maxlen=10)
        speech_run = 0
        pending = array.array("h")
        while self._alive(run_id):
            try:
                data = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._reset:
                self._reset = False
                self.vad.reset()
                preroll.clear()
                speech_run = 0
                pending = array.array("h")
                while not self._q.empty():
                    self._q.get_nowait()
                continue
            if self._paused:
                continue
            pending.extend(data)
            while len(pending) >= CHUNK:
                chunk, pending = pending[:CHUNK], pending[CHUNK:]
                speech_run = self._step(chunk, preroll, speech_run)

    def _step(self, chunk, preroll, speech_run):
        p = self.vad(chunk)
        started = False
        with self._cond:
            u = self._utt
            if u is None:
                preroll.append(chunk)
                speech_run = speech_run + 1 if p >= 0.5 else 0
                if speech_run >= 3:
                    self._utt = _Utterance(preroll)
                    self._utt.voiced = 3 * CHUNK
                    preroll.clear()
                    speech_run = 0
                    started = True
            elif not u.ended:
                u.chunks.append(chunk)
                u.n += len(chunk)
                if p >= 0.35:
                    u.last_voice = u.n
                    u.voiced += len(chunk)
                if u.n - u.last_voice >= self.silence or u.n >= self.max_samples:
                    u.ended = True
                    u.t_end = time.time()
                    u.end_len = min(u.n, u.last_voice + self.tail)
                self._cond.notify()
        if started:
            self.on_speech_start()
        return speech_run

    def _asr_loop(self, run_id):
        realtime = getattr(self.stt, "realtime", False)

        def ready():
            u = self._utt
            return not self._alive(run_id) or (
                u is not None and (u.ended or (realtime and u.n - u.decoded_len >= self.partial_step)))

        last_partial = ""
        while self._alive(run_id):
            with self._cond:
                self._cond.wait_for(ready, timeout=0.5)
                u = self._utt
                if u is None or not self._alive(run_id) or not (u.ended or realtime):
                    continue
                ended = u.ended
                target = u.end_len if ended else u.n
                if ended and u.voiced < self.min_voiced:      # a click / cough: ignore
                    self._utt = None
                    self.on_final("")
                    continue
                reuse = u.last_text is not None and u.decoded_len >= target
                pcm = None if reuse else u.pcm(target)
            if reuse:
                text = u.last_text
            else:
                try:
                    text = self.stt.transcribe(pcm)
                except Exception as ex:
                    print(f"[stt] error: {ex}")
                    if ended:
                        self.on_error(str(ex))
                    text = ""
                u.last_text, u.decoded_len = text, target
            if ended:
                with self._cond:
                    if self._utt is not u:
                        continue
                    self._utt = None
                last_partial = ""
                print(f"[stt] final {time.time() - u.t_end:.2f}s after speech "
                      f"({target / MIC_RATE:.1f}s audio): {text}")
                self.on_final(text)
            elif text and text != last_partial and self._utt is u:
                last_partial = text
                self.on_partial(text)

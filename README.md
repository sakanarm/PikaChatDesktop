# Pika Chat Desktop

น้อง **Pika** (MFEC Clay Boy) มาอยู่บนหน้าจอ Windows ของคุณ — ถามข้อมูลจาก **คลังความรู้ Pika** ได้ทั้ง
**พิมพ์แชท** หรือ **พูดคุยด้วยเสียง** แล้ว Pika จะตอบกลับเป็นข้อความพร้อมแหล่งอ้างอิง และพูดตอบได้

![poses](docs/poses.png)

## จุดเด่น

- **ตัวละครมีชีวิต** — 28 ท่า: ยืน กะพริบตา มองซ้ายขวา เดินเล่น โบกมือ ฟัง คิด ค้นหา พูด อธิบาย ดีใจ เสียใจ ตกใจ หลับ ถูกลาก
- **มินิแชทบนเดสก์ท็อป** — คลิกที่ Pika เพื่อเปิด/ซ่อน, คำตอบแบบ streaming, แสดงแหล่งอ้างอิงจาก Pika
- **คุยด้วยเสียง** — กด 🎤 แล้วพูดได้เลย (ภาษาไทย), Pika พูดตอบด้วยเสียง Microsoft Edge TTS
- **เบาที่สุด** — ใช้ Python stdlib + Tk, dependency แค่ `edge-tts` และ `miniaudio`; ไฟล์ .exe เดียว ไม่ต้องติดตั้ง Python
- **หน้าตั้งค่า** — ใส่ Pika key / เลือกโปรเจกต์ / strategy, LLM (OpenAI-compatible เช่น LiteLLM), เสียง, ขนาดตัว, เปิดพร้อม Windows
- **อ่านอย่างเดียว (read-only) กับ Pika** — แอปเรียกแค่ `GET /me`, `GET /projects/{id}/strategies`, `POST /projects/{id}/ask`, `POST /search`
  ไม่มีการสร้าง/แก้ไข/ลบ อะไรใน Pika ทั้งสิ้น

## ติดตั้ง

### แบบ .exe (แนะนำสำหรับผู้ใช้ทั่วไป)

1. ดาวน์โหลด `PikaChatDesktop.exe` (หรือ build เองด้วย `build.bat`)
2. ดับเบิลคลิกเปิดได้เลย ไม่ต้องติดตั้งอะไรเพิ่ม

### แบบรันจาก source

ต้องมี Python 3.10+ (Windows)

```bat
pip install -r requirements.txt
run.bat            :: หรือ  pythonw main.py
```

## ตั้งค่าครั้งแรก

เปิดครั้งแรกหน้าตั้งค่าจะขึ้นมาเอง (หรือคลิกขวาที่ Pika → ⚙ ตั้งค่า)

1. **แท็บ Pika** — ใส่ **Pika API key** (`pika_live_…`) ขอได้ที่ [หน้าโปรเจกต์ Pika](https://dmhub.mfec.dev/Pika/#projects)
   แล้วกด **ตรวจสอบ key และโหลดโปรเจกต์** — ระบบจะเติม Project ID และรายการ strategy ให้
2. **แท็บ LLM** — ใส่ URL / API key ของ LLM server (ค่าเริ่มต้น `https://gpt.mfec.co.th/litellm`) กด **โหลดรายชื่อโมเดล** และ **ทดสอบการเชื่อมต่อ**
3. กด **บันทึก**

> ⚠️ `dmhub.mfec.dev` อยู่ในเครือข่ายภายใน MFEC — ต้องต่อ **เน็ตบริษัทหรือ VPN** ก่อนใช้งาน

### วิธีตอบคำถาม

| โหมด | ทำงานอย่างไร | ต้องมี |
|---|---|---|
| อัตโนมัติ (แนะนำ) | LLM คุยเอง และเรียกค้น Pika เมื่อเป็นคำถามเรื่องข้อมูล | Pika key + LLM key |
| ค้น Pika ทุกคำถาม | ค้น Pika ก่อนทุกครั้ง แล้วให้ LLM เรียบเรียงคำตอบสั้นๆ | Pika key + LLM key |
| Pika ตอบตรงๆ | ใช้คำตอบจาก Pika โดยตรง | Pika key อย่างเดียว |
| ไม่ใช้ Pika | คุยกับ LLM อย่างเดียว | LLM key |

ถ้า LLM key ยังไม่ได้ใส่หรือหมดอายุ แอปจะสลับไปใช้ "Pika ตอบตรงๆ" ให้อัตโนมัติ

### เสียง

- **ฟังเสียง (speech-to-text)** — ค่าเริ่มต้นส่งเสียงไปถอดความที่ LLM server (`/audio/transcriptions`, เช่น `whisper-1`) ไม่ต้องดาวน์โหลดอะไร
- **ถอดเสียงในเครื่อง (ไม่บังคับ, รันจาก source เท่านั้น)** — ใช้โมเดล iApp OpenThai2.0-ASR (~1 GB) มีคำบรรยายสดระหว่างพูด
  ```bat
  pip install -r requirements-local-asr.txt
  python download_models.py
  ```
- **เสียงพูดของ Pika** — Edge TTS เสียงไทย (นิวัฒน์ / เปรมวดี / อัจฉรา) ปรับความเร็วและระดับเสียงได้

## วิธีใช้

| ทำอะไร | ผลลัพธ์ |
|---|---|
| คลิกที่ Pika | เปิด/ซ่อนหน้าแชท |
| เอาเมาส์ไปชี้ | แสดงปุ่ม 💬 แชท · 🎤 พูด · ⚙ ตั้งค่า |
| ลากตัว Pika | ย้ายตำแหน่ง |
| ดับเบิลคลิก | ย่อเหลือหัวเล็กๆ (ดับเบิลคลิกอีกครั้งเพื่อขยาย) |
| คลิกขวา | เมนู: แชท, พูด, ตั้งค่า, เดินเล่น, ย่อ, ออก |
| ในแชท: `Enter` / `↑` `↓` / `Esc` | ส่ง / เรียกคำถามก่อนหน้า / ซ่อนแชท |

ระหว่าง Pika ตอบอยู่ กดปุ่ม ■ ในแชทเพื่อหยุดคำตอบ (ไมค์จะพักฟังระหว่างที่ Pika พูด แล้วกลับมาฟังต่อเอง)

## ความปลอดภัยของข้อมูล

- API key เก็บไว้ในเครื่องที่ `%APPDATA%\PikaChatDesktop\config.json` เท่านั้น (ไม่อยู่ใน repo)
- ใช้ environment variable แทนได้: `PIKA_API_KEY`, `LITELLM_API_KEY`
- log อยู่ที่ `%APPDATA%\PikaChatDesktop\pika.log` (ไม่บันทึก key)

## สำหรับนักพัฒนา

| ไฟล์ | หน้าที่ |
|---|---|
| `main.py` | จุดเริ่มต้น, เชื่อมทุกส่วนเข้าด้วยกัน |
| `pet.py` | หน้าต่างตัวละครโปร่งใส, animation, bubble, toolbar |
| `chat_window.py` | หน้าแชท (markdown แบบเบา + แหล่งอ้างอิง) |
| `settings_window.py` | หน้าตั้งค่า |
| `assistant.py` | ลำดับการตอบ (LLM + tool `ask_pika`, โหมดต่างๆ) |
| `pika_client.py` | Pika API (read-only) |
| `llm_client.py`, `net.py` | OpenAI-compatible client (SSE) ด้วย urllib |
| `audio.py`, `stt.py`, `asr.py` | ไมค์ / VAD / ถอดเสียง / TTS |
| `sprites.py` | สร้างภาพท่าทางทั้งหมดใน `assets/pika/` (ต้องใช้ Pillow + numpy) |

```bat
pip install -r requirements-dev.txt
python sprites.py          :: สร้าง sprite ใหม่
build.bat                  :: ได้ dist\PikaChatDesktop.exe
```

---

### English summary

Pika Chat Desktop puts the Pika mascot on your Windows desktop. Ask questions about your Pika knowledge base by typing
in a mini chat or by talking; Pika answers with citations and can speak the reply. Runtime dependencies are only
`edge-tts` and `miniaudio` (Tk UI, stdlib HTTP); `build.bat` produces a single small `.exe`. The app is **read-only toward
Pika** — it only calls `/me`, `/projects/{id}/strategies`, `/projects/{id}/ask` and `/search`. Keys live in
`%APPDATA%\PikaChatDesktop\config.json`, never in the repository. `dmhub.mfec.dev` requires the MFEC network or VPN.

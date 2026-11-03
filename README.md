# muse-local

![oke pahlawan datang!](docs/pahlawan.jpeg)

**muse-local** adalah backend lokal yang membungkus webchat [muse.ai](https://muse.ai) menjadi API **OpenAI-compatible** (`/v1/chat/completions`), sehingga alat apa pun yang bisa bicara ke API OpenAI — termasuk opencode — bisa memakai akun muse.ai Anda **tanpa API key, tanpa VPS, tanpa worker eksternal**. Autentikasi dilakukan lewat **cookie sesi browser** (`session.json`) dan seluruh interaksi ke muse.ai dijalankan oleh Chromium headless (CDP) yang hidup di mesin yang sama.

**Status: berjalan dan sudah diuji end-to-end.** Latensi nyata untuk satu balasan: ±28 detik — dominasi waktu generasi muse.ai sendiri plus polling "selesai mengetik", bukan overhead relay.

---

## Daftar Isi

- [Apa Ini Sebenarnya](#apa-ini-sebenarnya)
- [Fitur Utama](#fitur-utama)
- [Tech Stack](#tech-stack)
- [Prasyarat](#prasyarat)
- [Persiapan Awal](#persiapan-awal)
- [Cara Pakai](#cara-pakai)
- [Menyambungkan ke opencode](#menyambungkan-ke-opencode)
- [Arsitektur](#arsitektur)
- [Cara Mendapatkan Cookie Baru (Refresh session.json)](#cara-mendapatkan-cookie-baru-refresh-sessionjson)
- [Environment Variables](#environment-variables)
- [API yang Tersedia](#api-yang-tersedia)
- [Troubleshooting](#troubleshooting)
- [Keamanan & Batasan](#keamanan--batasan)

---

## Apa Ini Sebenarnya

muse.ai adalah layanan chat berbasis AI yang diakses lewat **webchat biasa** — satu kotak teks, satu thread, tanpa API resmi untuk publik. Proyek ini menjembatani celah itu:

```
opencode / klien OpenAI mana pun
        │  POST http://127.0.0.1:20233/v1/chat/completions
        ▼
muse-local (FastAPI relay, loopback only)          ← di mesin Anda
        │  prompt diratakan (flatten), system prompt dibuang
        ▼
Chromium headless (CDP port 19211)                 ← di mesin Anda
        │  buka webchat muse.ai, kirim prompt, baca jawaban
        ▼
muse.ai (webchat asli, diotentikasi pakai cookie)
```

Karena browser-nya jalan lokal dan cookie ada di mesin Anda, **tidak ada komponen pihak ketiga di jalur data**. Relay hanya mendengarkan `127.0.0.1` — tidak bisa diakses dari jaringan luar.

**Kenapa tanpa API key?** Karena tidak perlu. Cookie `hatch_sess` milik Anda adalah otentikasi yang muse.ai perlukan. Setelah `session.json` terisi cookie valid, seluruh sistem hidup tanpa satu pun kredensial tambahan.

## Fitur Utama

- **Kompatibel protokol OpenAI** — `/v1/chat/completions` dan `/v1/models`, format request/response standar.
- **Otentikasi berbasis cookie** — tidak ada registrasi upstream; cukup cookie sesi muse.ai.
- **Driver browser CDP-native** — bukan Selenium; berkomunikasi langsung lewat Chrome DevTools Protocol (WebSocket: `Page`, `Runtime`, `DOM`).
- **Pembersihan system prompt** — prompt `system`/`developer` (misal AGENTS.md dari opencode) dibuang otomatis agar tidak bocor ke webchat muse.ai.
- **Follow-up pintar** — bila percakapan sudah terbuka di tab muse.ai dan history cocok, hanya teks baru yang dikirim, bukan seluruh percakapan.
- **Konkurensi serial** — `account_max_concurrency=1`; satu tab dipakai bergantian (menjaga rate limit muse.ai).
- **Launcher satu perintah** (`start.ps1`) — bootstrap venv, pribebeaskan port, jalankan server.

## Tech Stack

| Komponen | Teknologi | Peran |
|---|---|---|
| Runtime | Python 3.10+ | Bahasa inti |
| Framework API | FastAPI ≥ 0.115 | Server HTTP OpenAI-compatible |
| HTTP server | uvicorn[standard] ≥ 0.32 | Serve aplikasi FastAPI |
| Validasi | pydantic ≥ 2.9, pydantic-settings ≥ 2.5 | Model request/response + konfigurasi `MUSE2API_*` |
| HTTP client | httpx[socks] ≥ 0.27 | Pembaruan sesi + driver non-browser |
| Protokol browser | websockets ≥ 13.0 | Koneksi CDP ke Chromium |
| Browser | Chrome / Edge | Mengoperasikan webchat muse.ai |

> muse-local **bukan** paket yang diinstal via `pip install museai`. Kode dijalankan lewat `PYTHONPATH`; `pyproject.toml` dipakai untuk metadata dan tooling dev (ruff, pytest).

## Prasyarat

1. **Python 3.10+** — cek: `python --version`.
2. **Chrome atau Edge** — lokasinya otomatis dideteksi oleh `chromium.py`.
3. **Akun muse.ai** yang bisa memakai webchat.
4. **PowerShell** (bawaan Windows) untuk menjalankan `start.ps1`.

Tidak butuh: Docker, Node.js, Redis, atau database apa pun. Semua state disimpan di file JSON lokal.

## Persiapan Awal

Pastikan struktur folder root terlihat seperti ini:

```powershell
Set-Location D:\project\muse-local
Get-ChildItem
```

```
.venv\           ← venv Python (dibuat otomatis oleh start.ps1)
data\            ← state runtime: media, profil browser, tasks.json
docs\
  └── pahlawan.jpeg
src\
  └── museai\    ← seluruh kode Python
session.json     ← cookie muse.ai (RAHASIA — jangan dipush ke git)
start.ps1        ← launcher
pyproject.toml
README.md
```

File `session.json` adalah kunci otentikasi. Pastikan ada dan terisi cookie:

```powershell
Get-Item session.json | Select-Object Name, Length
```

Formatnya:

```json
{
  "accounts": [
    {
      "label": "local",
      "cookies": {
        "hatch_sess": "eyJ...",
        "hatch_gw": "...",
        "hatch_native_auth_device": "..."
      }
    }
  ]
}
```

Bila belum ada atau cookie telah mati, lihat bagian [Cara Mendapatkan Cookie Baru](#cara-mendapatkan-cookie-baru-refresh-sessionjson).

## Cara Pakai

```powershell
Set-Location D:\project\muse-local
.\start.ps1
```

`start.ps1` melakukan empat hal:

1. **Venv** — bila `.venv\Scripts\python.exe` belum ada, dibuat dan diinstal: fastapi, uvicorn[standard], pydantic, pydantic-settings, httpx[socks], websockets.
2. **Cek `session.json`** — bila tidakt ada, muncul peringatan bahwa chat akan 503 sampai file ada.
3. **Pribebeaskan port 20233** — proses lama yang mendengarkan 20233 dihentikan otomatis (mencegah `[Errno 10048]`).
4. **Set `PYTHONPATH` ke `src`** lalu jalankan `python -m museai`.

Output awal yang diharapkan:

```
muse-local -> http://127.0.0.1:20233/v1  (model: muse-chat)
INFO:     Started server process [12345]
INFO:     Uvicorn running on http://127.0.0.1:20233 (Press CTRL+C to quit)
```

### Uji cepat

```powershell
# daftar model
(Invoke-WebRequest http://127.0.0.1:20233/v1/models).Content

# lanjutkan chat
$body = @'
{
  "model": "muse-chat",
  "messages": [
    {"role": "system", "content": "PANJANG-SEKALI-AGENTSMD-TEST"},
    {"role": "user", "content": "ping kecepatan"}
  ]
}
'@
Invoke-RestMethod -Uri http://127.0.0.1:20233/v1/chat/completions -Method Post -ContentType 'application/json' -Body $body
```

Harapannya: muse.ai menjawab tentang ping-nya saja — prompt system tidak bocor — dengan latensi sekitar 25–35 detik.

### Perilaku penting

| Kondisi | Perilaku |
|---|---|
| Chrome sudah hidup di CDP 19211 | Driver menempel ke instance yang ada |
| Chrome belum hidup | Relay meluncurkan Chromium sendiri (headless, profil `data/browser-profile`) |
| `session.json` tidak ada / cookie mati | `/v1/chat/completions` menjawab `503` |
| Port 20233 terisi proses lama | `start.ps1` membunuhnya otomatis |

### Port yang dipakai

```
20233  ← HTTP relay (loopback) — tujuan semua klien
19211  ← CDP DevTools (loopback) — antarmuka ke Chromium
```

## Menyambungkan ke opencode

Tambahkan provider ini di `C:\Users\NABIL\.config\opencode\opencode.json`:

```json
"provider": {
  "muse-local": {
    "npm": "@ai-sdk/openai-compatible",
    "name": "Muse Local",
    "options": {
      "baseURL": "http://127.0.0.1:20233/v1",
      "apiKey": "dummy"
    },
    "models": {
      "muse-chat": { "name": "Muse chat" }
    }
  }
}
```

`apiKey` mengisi saja `dummy` — relay loopback ini tidak memeriksa key.

> ⚠️ **Jangan set `small_model` opencode ke `muse-local`.** opencode memakai `small_model` untuk generate judul sesi; kalau lewat muse-local, setiap mulai percakapan akan menambah jeda 25+ detik dan membajak tab browser. Konfigurasi yang dipakai proyek ini: `"small_model": "9router/dahl/zai-org/GLM-5.3-Flash"`.

Setelah disetel, restart opencode lalu pilih model `muse-local/muse-chat`.

## Arsitektur

### Struktur direktori

```
D:\project\muse-local\
├── .venv\                        # venv lokal
├── data\
│   ├── browser-profile\          # profil Chromium permanen
│   ├── media\                    # media yang diunggah ke webchat
│   ├── tasks.json                # tugas asinkron (image/video)
│   └── accounts.json             # pool akun (dalam layout ini tidak aktif)
├── docs\
│   └── pahlawan.jpeg             # gambar hero README
├── src\museai\
│   ├── __main__.py               # entrypoint: python -m museai
│   ├── config.py                 # konfigurasi MUSE2API_*
│   ├── core\
│   │   └── prompt.py             # flattening messages OpenAI → satu prompt text
│   ├── drivers\browser\
│   │   ├── driver.py             # driver CDP: tab, poll, stable, stall
│   │   ├── chromium.py           # deteksi Chrome/Edge, Windows-aware
│   │   └── dom\                  # ekspresi DOM: tulis, kirim, baca tail
│   ├── accounts\
│   │   └── store.py              # SessionFileStore — baca session.json
│   └── api\
│       ├── app.py
│       ├── deps.py               # auth di-nonaktifkan untuk loopback
│       └── routes\
│           ├── chat.py           # POST /v1/chat/completions
│           └── models.py         # GET /v1/models
├── session.json
├── start.ps1
├── pyproject.toml
└── README.md
```

### Konversi Pesan — `core/prompt.py`

Klien OpenAI mengirim `messages` (array `{role, content}`); webchat muse.ai menerima **satu kotak teks**. `flatten_messages()` menata:

1. **Ekstraksi teks** dari tiap pesan — menangani string biasa dan array `content` (bagian `image_url` ditarik terpisah untuk driver).
2. **Buang `system` dan `developer`** — opencode memasukkan AGENTS.md/persona di sini; jika masuk webchat, muse.ai membalas hal-hal yang salah. **Sudah diperbaiki dan diverifikasi end-to-end.**
3. **Follow-up**: bila history cocok dengan percakapan di tab, hanya teks user baru yang dikirim (`followup_text`).
4. **Role header** `[User]`/`[Assistant]` untuk percakapan multi-turn, ditutup instruksi baku.

> **Peringatan**: `message_turns()` sengaja **tidak** membuang system/developer — ia dipakai untuk pencocokan history tab lewat `followup_text`. Hanya `flatten_messages()` yang membuang. Jangan "perbaiki" ini lagi.

### Driver CDP — `drivers/browser/driver.py**

Kenapa CDP dan bukan Selenium: Selenium naik di atas WebDriver Protocol yang menambah lapisan dan tidak nyaman untuk async; CDP bicara langsung ke Chrome lewat WebSocket di tingkat rendah.

Mekaniknya:

1. **Sambungkan CDP** (port 19211) — WebSocket ke browser target.
2. **Kelola tab** — halaman webchat muse.ai dibuka; percakapan lanjutan memakai tab yang sama bila history cocok.
3. **`_begin_chat`** — tulis teks ke textarea webchat, klik kirim (ekspresi DOM di `dom/`).
4. **Polling loop** (konstanta di `driver.py`):

```python
POLL_INTERVAL      = 0.15   # cek tiap 150 ms
STABLE_POLLS_DONE  = 4      # 4 poll berturut-turut tanpa pertumbuhan teks = selesai
STABLE_POLLS_FORCE = 12     # safety net: paksa selesai setelah 12 poll stabil
```

- **first_token_timeout** = 45 detik
- **chat_timeout** (total) = 300 detik
- **stall detection**: `dom.STALL_HINTS` berisi string galat muse.ai; bila muncul di tail DOM, ditangani.

5. **Hasil** dikembalikan dalam format OpenAI (`choices[0].message.content`, `finish_reason: "stop"`).

### Siklus satu request

```
POST /v1/chat/completions
 1. routes/chat.py → flatten_messages(messages)
      system/developer = dibuang; user/assistant = dipertahankan
 2. SessionFileStore membaca session.json → cookie valid?
 3. Driver mengambil/menempel tab webchat muse.ai
      → tulis teks ke textarea → klik kirim
 4. Poll tiap 150 ms → teks stabil 4 poll berturut-turut = balasan selesai
 5. Format balasan jadi response OpenAI → kirim ke klien
```

**Latensi**: ±25–35 detik per balasan. Sebagian besar adalah generasi muse.ai sendiri. Polling sendiri hanya ~2 detik total. Driver dibangun **satu tab sekali pakai**; request bersamaan otomatis diserialisasi, bukan error.

## Cara Mendapatkan Cookie Baru (Refresh session.json)

Gejala cookie mati:

- Balasan kosong atau `503`.
- Log driver menunjukkan halaman login muse.ai.

Langkahnya:

1. Buka **Chrome normal**, masuk ke [muse.ai](https://muse.ai), pastikan sudah login.
2. `F12` → tab **Application** → **Cookies** → domain `muse.ai`.
3. Salin nilai cookie **`hatch_sess`**, **`hatch_gw`**, **`hatch_native_auth_device`**.
4. Tulis ke `session.json` memakai format di [Persiapan Awal](#persiapan-awal).
5. Restart server (`.\start.ps1`).

> ⚠️ **Jangan commit `session.json` ke git.** File itu adalah kredensial masuk ke akun muse.ai Anda.

## Environment Variables

Semua variabel berprefix **`MUSE2API_*`**, dimuat oleh pydantic-settings, bisa juga dibaca dari file `.env` di root.

| Variabel | Default | Deskripsi |
|---|---|---|
| `MUSE2API_HOST` | `127.0.0.1` | Bind host. **Jangan dibuat `0.0.0.0`** — auth dinonaktifkan di layout ini. |
| `MUSE2API_PORT` | `20233` | Port relay HTTP. |
| `MUSE2API_LOG_LEVEL` | `INFO` | `DEBUG` untuk melihat langkah CDP. |
| `MUSE2API_DRIVER` | `browser` | `browser` (CDP) / `mock` (uji tanpa browser) / `http`. |
| `MUSE2API_CDP_PORT` | `19211` | Port DevTools Chromium. |
| `MUSE2API_HEADLESS` | `true` | Set `false` untuk melihat window browser saat debug. |
| `MUSE2API_SITE_URL` | `https://muse.ai` | Domain upstream. |
| `MUSE2API_DATA_DIR` | `data` | Folder media, profil browser, tasks. |
| `MUSE2API_BROWSER_PROFILE_DIR` | (otomatis) | Path profil Chromium; default absolut ke `data/browser-profile`. |
| `MUSE2API_PAGE_READY_TIMEOUT` | `45.0` | Detik tunggu webchat siap. |
| `MUSE2API_CHAT_TIMEOUT` | `300.0` | Total detik per chat sebelum timeout. |
| `MUSE2API_FIRST_TOKEN_TIMEOUT` | `45.0` | Detik tanpa teks pertama sebelum dianggap gagal. |
| `MUSE2API_ACCOUNT_MAX_CONCURRENCY` | `1` | **Sengaja 1** — satu tab. Naikkan dengan paham risiko rate limit. |
| `MUSE2API_KEEPALIVE_ENABLED` | `false` | Pembaruan cookie otomatis — off di layout ini; refresh manual via `session.json`. |

Contoh debug:

```powershell
$env:MUSE2API_HEADLESS = "false"
$env:MUSE2API_LOG_LEVEL = "DEBUG"
.\start.ps1
```

## API yang Tersedia

### `GET /v1/models`

```powershell
(Invoke-WebRequest http://127.0.0.1:20233/v1/models).Content
```

```json
{"object":"list","data":[{"id":"muse-chat","object":"model","created":...,"owned_by":"muse-local"}]}
```

### `POST /v1/chat/completions`

Request standar OpenAI:

```json
{
  "model": "muse-chat",
  "messages": [
    {"role": "user", "content": "berapa harga kopi?"}
  ]
}
```

Response:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "muse-chat",
  "choices": [
    {"index": 0, "message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}
  ],
  "usage": {"prompt_tokens": 12, "completion_tokens": 48, "total_tokens": 60}
}
```

| Kode | Kondisi | Solusi |
|---|---|---|
| `503` | Tidak ada sesi valid / cookie mati | Refresh cookie, restart server |
| `504` | chat_timeout (300s) tercapai | Cek gangguan muse.ai; naikkan `MUSE2API_CHAT_TIMEOUT` |
| `500` | Driver gagal membaca DOM / UI muse.ai berubah | Log `DEBUG`; cek selector di `drivers/browser/dom/` |

## Troubleshooting

### `[Errno 10048]` — port 20233 sudah terpakai

```powershell
Get-NetTCPConnection -LocalPort 20233 -State Listen |
  Select-Object -ExpandProperty OwningProcess | Stop-Process -Force
```

Bila masih gagal, kill semua Chrome lalu jalankan ulang `start.ps1`:

```powershell
Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force
.\start.ps1
```

### DevTools gagal startup (semacam "DevToolsActivePort file doesn't exist")

Profil Chromium lama masih terkunci atau Chrome lain menguasai port 19211:

```powershell
Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item -Recurse -Force data\browser-profile\Singleton* -ErrorAction SilentlyContinue
.\start.ps1
```

### Respons kosong atau 503

1. Buka muse.ai di Chrome biasa; login kalau diminta.
2. Refresh cookie ke `session.json` (lihat bagian di atas).
3. Restart server.

### Balasan lambat (>60 detik)

- Wajar untuk jawaban panjang. Prompt pendek yang selalu >60 detik berarti muse.ai sedang sibuk — coba lagi nanti.
- Bila ingin debug: `MUSE2API_LOG_LEVEL=DEBUG`.

### Chat terasa terpotong

Driver menunggu 4 poll stabil (≈0.6 detik tanpa pertumbuhan teks) sebelum menyatakan selesai. Untuk jawaban yang mengetiknya sangat panjang, naikkan `STABLE_POLLS_DONE` di `driver.py` menjadi `6` atau `8`.

### opencode masih mengirim prompt system ke muse.ai

Sudah diperbaiki lewat filter di `core/prompt.py`. Bila terulang: pastikan `flatten_messages` dipanggil di `api/routes/chat.py` sebelum membangun prompt.

## Keamanan & Batasan

- **Semua loopback.** Relay di `127.0.0.1:20233`, DevTools di `127.0.0.1:19211`. Auth dinonaktifkan — sekali lagi: **jangan** set host ke `0.0.0.0`.
- **`session.json` = kredensial.** Siapa pun yang punya file itu punya akses akun muse.ai Anda. Jangan share, jangan commit.
- **Cookie rot tidak terdeterministik** — muse.ai bisa memutar pola cookie kapan pun; refresh manual adalah jalannya.
- **Konkurensi 1 tab** — request bersamaan diantrikan, bukan error.
- **Tidak ada API resmi** — proyek memakai webchat via browser. Bila muse.ai mengubah UI, driver bisa rusak; perbaikannya ada di `drivers/browser/driver.py` dan `drivers/browser/dom/`.

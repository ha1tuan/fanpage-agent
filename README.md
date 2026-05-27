# Lớn Rồi Đừng Lười — Multi-Agent AI Production System

> **Cỗ máy sản xuất nội dung tự động** cho Fanpage _"Lớn Rồi Đừng Lười"_.
> Chỉ cần nhắn một topic vào Telegram — hệ thống tự động nghiên cứu, viết kịch bản Gen-Z, dựng video AI 45 giây, rồi tự đăng lên Facebook. Không cần chạm tay.

Kiến trúc Multi-Agent (6 Agent) vận hành trên **FastAPI + LangGraph**, triển khai hoàn toàn trong **Docker**, giao tiếp với **Ollama** chạy trên host thật qua `host.docker.internal`, nhận lệnh qua **Telegram Webhook** (đường hầm Ngrok), và xuất bản qua **Meta Graph API**.

---

## Sơ Đồ Workflow

> Toàn bộ luồng vận hành từ lệnh Telegram đến bài đăng Facebook — bao gồm vòng lặp duyệt nội dung Human-in-the-Loop.

    ADMIN      -->|"/vietbai [topic]"| NGROK
    NGROK      -->|"HTTPS POST Webhook"| FASTAPI
    FASTAPI    -->|"Khởi chạy graph"| N1

    N1         -->|"Tối ưu truy vấn"| EXA
    EXA        -->|"Bài viết + Insights"| N1
    N1         -->|"raw_materials"| N2

    N2         -->|"LLM Inference"| OLLAMA
    OLLAMA     -->|"caption · content · script"| N2
    N2         -->|"review_status: pending"| HITL

    HITL       -->|"Gửi inline buttons"| TGBOT
    TGBOT      -->|"✅ Duyệt  /  ❌ Chê"| ADMIN
    ADMIN      -->|"approved / rejected + feedback"| FASTAPI
    FASTAPI    -->|"Tiếp tục graph"| HITL
    HITL       -.->|"rejected → viết lại"| N2
    HITL       -->|"approved"| N3

    N3         -->|"Kịch bản 3 cảnh"| KLING
    KLING      -->|"MP4 clips"| N3
    N3         -->|"Video + TTS đã ghép"| N4

    N4         -->|"Lưu Checkpoint"| PG
    N4         -->|"POST video / photo / text"| META
    META       -->|"post_url"| N4
    N4         -->                             N5
    N5         -->|"Thành công ✅ / Thất bại ❌"| TGBOT
    TGBOT      -->|"Thông báo kết quả"| ADMIN

```

---

## Kiến Trúc Thư Mục

```

fanpage-agent/
│
├── main.py # Entry point — FastAPI app + route mounting
├── Dockerfile # Python 3.11-slim, cài FFmpeg & ImageMagick
├── docker-compose.yml # Orchestrate: postgres · ngrok · agent_app
├── entrypoint.sh # Khởi động Uvicorn bên trong container
├── requirements.txt
├── .env # ← KHÔNG commit (xem mục Bảo mật)
├── .env.example # Template biến môi trường
└── .gitignore
│
├── app/
│ ├── core/
│ │ └── settings.py # Pydantic Settings — load toàn bộ .env
│ │
│ ├── services/
│ │ └── llm_service.py # Adapter: Ollama (local) hoặc Gemini (cloud)
│ │
│ ├── agents/
│ │ ├── states.py # ContentProductionState — schema trạng thái graph
│ │ ├── graph.py # Build + compile LangGraph workflow
│ │ │
│ │ └── nodes/
│ │ ├── scrapers/
│ │ │ ├── scraper.py # Exa AI search + LLM extract insights
│ │ │ └── prompt.py # System prompts cho Scraper
│ │ ├── writers/
│ │ │ ├── writer.py # Sinh caption / content / video_script (JSON)
│ │ │ └── prompt.py # System prompts giọng Gen-Z tiếng Việt
│ │ ├── video_compose/
│ │ │ └── video_compose.py # Kling AI + MoviePy + Edge TTS (vi-VN-NamMinhNeural)
│ │ ├── image_gen/
│ │ │ └── image_gen.py # Gemini Imagen 3 (tích hợp, chưa kích hoạt trong graph)
│ │ ├── publisher/
│ │ │ └── publisher.py # Meta Graph API — đăng video/ảnh/text lên Fanpage
│ │ └── notifier/
│ │ └── notifier.py # Telegram sendMessage — thông báo kết quả cuối
│ │
│ └── api/
│ ├── routes.py # REST endpoints quản lý Agent (/agents/\*)
│ └── telegram_routes.py # Webhook handler nhận lệnh từ Telegram Bot
│
└── assets/
├── images/ # Ảnh sinh ra bởi Imagen 3
├── videos/ # Video MP4 hoàn chỉnh sau khi dựng
└── music/ # Nhạc nền (tùy chọn)

````

---

## Thành Phần Công Nghệ

| Tầng | Công nghệ |
|---|---|
| **API Framework** | [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn |
| **Agent Orchestration** | [LangGraph](https://langchain-ai.github.io/langgraph/) (AsyncPostgresSaver) |
| **LLM — Local** | [Ollama](https://ollama.com/) · Qwen (chạy trên Host, kết nối qua `host.docker.internal`) |
| **LLM — Cloud** | Google Gemini 2.5 Flash (fallback / writer) |
| **Nghiên cứu** | [Exa AI](https://exa.ai/) Neural Search |
| **Sinh Video** | [Kling AI](https://klingai.com/) v2-6 · 9:16 · Text-to-Video |
| **Sinh Ảnh** | Google Imagen 3 (Generative Language API) |
| **TTS Tiếng Việt** | Edge TTS · `vi-VN-NamMinhNeural` |
| **Dựng Video** | MoviePy · ImageIO-FFmpeg · FFmpeg · ImageMagick |
| **Mạng Xã Hội** | Meta Graph API v20.0 (video · photo · feed) |
| **Nhắn Tin** | Telegram Bot API (Webhook + Inline Buttons) |
| **Database** | PostgreSQL 15 (LangGraph checkpoint storage) |
| **Đường Hầm** | [Ngrok](https://ngrok.com/) (HTTPS tunnel cho Telegram webhook) |
| **Container** | Docker · Docker Compose |

---

## Cấu Hình Biến Môi Trường

Tạo file `.env` ở thư mục gốc dựa trên `.env.example`:

```bash
# ── LLM Provider ──────────────────────────────────
LLM_PROVIDER=ollama             # hoặc "gemini"
OLLAMA_MODEL=qwen2.5:latest
OLLAMA_BASE_URL=http://host.docker.internal:11434
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.5-flash

# ── Nghiên cứu ────────────────────────────────────
EXA_API_KEY=...

# ── Sinh Video (Kling AI) ─────────────────────────
KLING_ACCESS_KEY=...
KLING_SECRET_KEY=...

# ── Database ──────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://postgres:password@postgres:5432/fanpage-agent

# ── Meta (Facebook) ───────────────────────────────
META_APP_ID=...
META_APP_SECRET=...
META_PAGE_ID=...
META_PAGE_ACCESS_TOKEN=...      # Page Token dài hạn (dùng /agents/token-exchange để lấy)

# ── Telegram ──────────────────────────────────────
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# ── Ngrok ─────────────────────────────────────────
NGROK_AUTHTOKEN=...

# ── Output ────────────────────────────────────────
IMAGE_OUTPUT_DIR=assets/images
VIDEO_OUTPUT_DIR=assets/videos
````

> [!WARNING]
> **Bảo mật tuyệt đối:** File `.env` chứa toàn bộ API key và token nhạy cảm (Meta, Telegram, Kling, Gemini, Ngrok). File này **đã được thêm vào `.gitignore`** và **tuyệt đối không được commit** lên bất kỳ repository nào — kể cả private. Chỉ commit file `.env.example` (không có giá trị thật).

> [!IMPORTANT]
> **Ollama phải chạy trên máy Host** trước khi khởi động Docker. Container kết nối tới Ollama qua `host.docker.internal:11434`. Trên Linux, bạn cần thêm `extra_hosts: ["host.docker.internal:host-gateway"]` trong `docker-compose.yml` (thường đã được cấu hình sẵn).

---

## Hướng Dẫn Triển Khai

### Yêu Cầu

- Docker Engine 24+ và Docker Compose v2+
- Ollama đang chạy trên máy host với model đã tải (`ollama pull qwen2.5:latest`)
- File `.env` đã được tạo và điền đầy đủ

### Khởi Động "Một Chạm"

```bash
# Bước 1: Clone dự án
git clone <repo-url> fanpage-agent
cd fanpage-agent

# Bước 2: Tạo file cấu hình
cp .env.example .env
# Điền các API key vào .env ...

# Bước 3: Build và khởi động toàn bộ stack
docker compose up -d --build
```

Sau khi khởi động, Docker Compose sẽ tự động:

1. Khởi chạy **PostgreSQL** và chờ healthcheck sẵn sàng
2. Khởi chạy **Ngrok** tạo đường hầm HTTPS công khai
3. Build và khởi chạy **agent_app** (FastAPI) trên cổng `8000`

### Theo Dõi Log Thời Gian Thực

```bash
# Xem log toàn bộ stack (Ctrl+C để thoát)
docker compose logs -f

# Chỉ xem log của Agent (các Node cày cuốc)
docker compose logs -f agent_app

# Xem địa chỉ HTTPS public do Ngrok cấp
docker compose logs ngrok | grep "url="
```

---

## API Endpoints

Base URL: `http://localhost:8000/api/v1`

### Quản Lý Agent (`/agents`)

| Method | Endpoint                     | Mô tả                                                                  |
| ------ | ---------------------------- | ---------------------------------------------------------------------- |
| `POST` | `/agents/start`              | Khởi chạy graph với topic. Chạy đến Writer rồi tự dừng chờ duyệt.      |
| `GET`  | `/agents/review/{thread_id}` | Xem trước caption + kịch bản video đang chờ duyệt.                     |
| `POST` | `/agents/action/{thread_id}` | Duyệt (`approved`) hoặc bắt sửa (`rejected` + feedback).               |
| `GET`  | `/agents/status/{thread_id}` | Kiểm tra tiến độ, lỗi, URL media, link bài đăng.                       |
| `POST` | `/agents/token-exchange`     | Đổi User Token ngắn hạn → Page Token dài hạn (chạy một lần khi setup). |

**Ví dụ khởi chạy:**

```bash
curl -X POST http://localhost:8000/api/v1/agents/start \
  -H "Content-Type: application/json" \
  -d '{"topic": "Tại sao người trẻ ngại học kỹ năng mới"}'
```

**Duyệt nội dung:**

```bash
# Xem bản nháp
curl http://localhost:8000/api/v1/agents/review/{thread_id}

# Duyệt
curl -X POST http://localhost:8000/api/v1/agents/action/{thread_id} \
  -H "Content-Type: application/json" \
  -d '{"action": "approved"}'

# Bắt sửa
curl -X POST http://localhost:8000/api/v1/agents/action/{thread_id} \
  -H "Content-Type: application/json" \
  -d '{"action": "rejected", "feedback": "Caption chưa đủ gai góc, thêm số liệu thực tế vào"}'
```

### Telegram Webhook (`/telegram`)

| Method | Endpoint            | Mô tả                                                      |
| ------ | ------------------- | ---------------------------------------------------------- |
| `POST` | `/telegram/webhook` | Nhận lệnh từ Telegram Bot (inline buttons + text commands) |

**Lệnh Telegram được hỗ trợ:**

| Lệnh                          | Chức năng                                       |
| ----------------------------- | ----------------------------------------------- |
| `/vietbai [topic]`            | Ra lệnh cho AI làm bài theo chủ đề              |
| `/sua [thread_id] [feedback]` | Yêu cầu AI sửa lại bài với feedback qua chat    |
| Nút `✅ Duyệt & Lên Sóng`     | Duyệt nội dung, tiếp tục dựng video và đăng bài |
| Nút `❌ Chê, Bắt Sửa Lại`     | Từ chối, đưa về Writer để viết lại              |

---

## Luồng Human-in-the-Loop

```
[Telegram: /vietbai topic]
        │
        ▼
[Scraper] ──► [Writer] ──► ⏸️ INTERRUPT (chờ duyệt)
                                  │
               ┌──────────────────┼──────────────────┐
               ▼                  ▼                   ▼
          ❌ rejected          ✅ approved        (timeout)
               │                  │
               ▼                  ▼
          [Writer]         [Video Compose]
          (viết lại)             │
                                 ▼
                           [Publisher] ──► Facebook Fanpage
                                 │
                                 ▼
                           [Notifier] ──► Telegram: kết quả
```

Mỗi trạng thái của graph được lưu vào **PostgreSQL Checkpointer** — đảm bảo không mất tiến trình nếu container khởi động lại.

---

## Xử Lý Lỗi & Độ Bền

| Tình huống                    | Hành vi hệ thống                                                   |
| ----------------------------- | ------------------------------------------------------------------ |
| Kling AI timeout / lỗi render | Publisher tự động fallback sang đăng bài text thuần                |
| LLM trả JSON sai định dạng    | Writer có 4 tầng fallback parser (markdown strip → repair → regex) |
| Meta token hết hạn            | Publisher tự động exchange lấy Page Token mới trước khi đăng       |
| Container khởi động lại       | LangGraph tiếp tục từ checkpoint PostgreSQL cuối cùng              |

> [!NOTE]
> Node `image_gen` (Gemini Imagen 3) đã được tích hợp trong code nhưng **chưa kết nối vào graph**. Chỉ có luồng sinh video (Kling AI) đang hoạt động. Để kích hoạt sinh ảnh, cần cập nhật `graph.py` và bổ sung trường `image_prompt` vào Writer output.

---

## Giấy Phép

Dự án phát triển nội bộ cho Fanpage **Lớn Rồi Đừng Lười**. Không phân phối lại khi chưa có sự cho phép.

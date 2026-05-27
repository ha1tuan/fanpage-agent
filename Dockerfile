# ── Base Image ──
# python:3.11-slim: phiên bản Slim loại bỏ tài liệu và debug tools không cần thiết
# → Giảm kích thước image xuống ~60% so với image đầy đủ
FROM python:3.11-slim

# ── Thư mục làm việc ──
# Tất cả lệnh COPY, RUN, CMD tiếp theo đều thực thi tương đối với /app
WORKDIR /app

# ── Thư viện hệ thống ──
# build-essential : compiler GCC/G++ để build các gói có C extension (psycopg, numpy, moviepy...)
# libpq-dev        : header files kết nối PostgreSQL (bắt buộc cho psycopg/asyncpg)
# curl             : dùng trong entrypoint.sh để gọi Ngrok API và Telegram setWebhook API
# --no-install-recommends : bỏ qua các gói "gợi ý" để image nhỏ gọn hơn
# rm -rf /var/lib/apt/lists/* : xóa cache apt sau khi cài để không phồng layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Cài đặt Python Dependencies ──
# COPY requirements.txt riêng TRƯỚC khi copy code → khai thác Docker Layer Cache:
# Nếu chỉ sửa code (không đổi requirements.txt), bước pip install được cache lại → build nhanh hơn
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Copy mã nguồn ──
# COPY thực hiện SAU pip install để tối ưu cache (xem giải thích trên)
COPY . .

# ── Tạo thư mục tài nguyên ──
# Tạo sẵn các thư mục media để Agent không gặp lỗi "FileNotFoundError" khi ghi file lần đầu
# Dùng -p để không báo lỗi nếu thư mục đã tồn tại
RUN mkdir -p assets/videos assets/photos assets/images assets/music

# ── Cấp quyền entrypoint ──
# chmod +x là bắt buộc - nếu thiếu, Docker sẽ báo "Permission denied" khi chạy ENTRYPOINT
RUN chmod +x entrypoint.sh

# ── Expose Port ──
# Khai báo cổng 8000 để Docker biết container lắng nghe ở đây (dùng cho networking và documentation)
EXPOSE 8000

# ── Điểm chạy chính ──
# Dùng ENTRYPOINT dạng JSON array (exec form) thay vì shell form
# → exec form không tạo tiến trình shell con, đảm bảo signal handling đúng khi docker stop
# Dùng bash để gọi entrypoint.sh → không bị lỗi permission denied ngay cả khi volume mount ghi đè quyền
ENTRYPOINT ["bash", "./entrypoint.sh"]

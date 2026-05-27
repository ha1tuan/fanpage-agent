#!/bin/bash
# Tắt chế độ "chạy tiếp dù lỗi" để có thể tự xử lý lỗi trong vòng lặp
set +e

echo "============================================================"
echo "  Hệ thống Multi-Agent AI - Luồng Khởi Động Tự Động"
echo "============================================================"

# ════════════════════════════════════════════════════════════════
# BƯỚC 1: CHỜ NGROK KHỞI ĐỘNG VÀ LẤY PUBLIC URL
# ════════════════════════════════════════════════════════════════
echo ""
echo "[BƯỚC 1/3] ⏳ Đang chờ Ngrok sẵn sàng..."

NGROK_URL=""
MAX_RETRIES=40        # Số lần thử tối đa (40 lần x 3 giây = 2 phút)
RETRY_COUNT=0

while [ -z "$NGROK_URL" ] && [ "$RETRY_COUNT" -lt "$MAX_RETRIES" ]; do
    sleep 3
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "  🔄 Lần thử $RETRY_COUNT/$MAX_RETRIES - Đang polling API Ngrok nội bộ..."

    # Gọi vào Dashboard API của Ngrok (cổng 4040 chỉ mở trong Docker network nội bộ)
    # agent_ngrok là tên SERVICE trong docker-compose.yml, Docker DNS tự phân giải
    NGROK_RESPONSE=$(curl -sf --max-time 5 "http://agent_ngrok:4040/api/tunnels" 2>/dev/null || true)

    if [ -n "$NGROK_RESPONSE" ]; then
        # Dùng python3 (có sẵn trong image) để bóc tách URL HTTPS từ JSON response
        # Lấy tunnel đầu tiên có proto = "https"
        NGROK_URL=$(echo "$NGROK_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for tunnel in data.get('tunnels', []):
        if tunnel.get('proto') == 'https':
            print(tunnel['public_url'])
            sys.exit(0)
except Exception:
    pass
" 2>/dev/null || true)
    fi
done

# Kiểm tra nếu sau tất cả các lần thử vẫn không lấy được URL
if [ -z "$NGROK_URL" ]; then
    echo "❌ LỖI NGHIÊM TRỌNG: Không thể lấy URL từ Ngrok sau $MAX_RETRIES lần thử."
    echo "   → Kiểm tra lại biến NGROK_AUTHTOKEN trong file .env"
    exit 1
fi

echo "  ✅ Thành công! Ngrok Public URL: $NGROK_URL"


# ════════════════════════════════════════════════════════════════
# BƯỚC 2: TỰ ĐỘNG CẤU HÌNH WEBHOOK TELEGRAM
# ════════════════════════════════════════════════════════════════
echo ""
echo "[BƯỚC 2/3] 🔗 Đang cấu hình Telegram Webhook..."

# Ghép đường dẫn Webhook đầy đủ theo cấu trúc route của FastAPI
# Đường dẫn này phải khớp với route @router.post("/telegram/webhook") trong app/api/telegram_routes.py
WEBHOOK_FULL_URL="${NGROK_URL}/api/v1/telegram/webhook"
echo "  📡 Telegram sẽ gửi update tới: $WEBHOOK_FULL_URL"

# Gọi Telegram Bot API để đăng ký địa chỉ Webhook mới
# ${TELEGRAM_BOT_TOKEN} được nạp tự động từ file .env thông qua env_file trong docker-compose.yml
TELEGRAM_RESPONSE=$(curl -sf -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"${WEBHOOK_FULL_URL}\"}" 2>/dev/null || true)

echo "  📨 Phản hồi từ Telegram: $TELEGRAM_RESPONSE"

# Kiểm tra trường "ok": true trong JSON response để xác nhận thành công
WEBHOOK_OK=$(echo "$TELEGRAM_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print('true' if data.get('ok') else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")

if [ "$WEBHOOK_OK" = "true" ]; then
    echo "  ✅ Telegram Webhook đã được cấu hình thành công!"
else
    # Không thoát - server vẫn cần chạy, cảnh báo để người dùng biết
    echo "  ⚠️  CẢNH BÁO: Telegram webhook báo lỗi - kiểm tra TELEGRAM_BOT_TOKEN trong .env"
    echo "     → Tiếp tục khởi động server để không mất toàn bộ dịch vụ..."
fi


# ════════════════════════════════════════════════════════════════
# BƯỚC 3: BÓP CÒ KHỞI ĐỘNG FASTAPI SERVER
# ════════════════════════════════════════════════════════════════
echo ""
echo "[BƯỚC 3/3] 🚀 Đang khởi động FastAPI / Uvicorn server..."
echo "============================================================"
echo ""

# 'exec' thay thế tiến trình hiện tại bằng uvicorn
# → Đảm bảo signal SIGTERM/SIGINT từ Docker được chuyển thẳng tới uvicorn (graceful shutdown)
exec uvicorn main:app --host 0.0.0.0 --port 8000

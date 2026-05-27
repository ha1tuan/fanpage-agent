import os
import time
import httpx
from app.agents.states import ContentProductionState
from app.core.settings import get_settings

# ============================================================
# CONFIG
# ============================================================
settings = get_settings()
APP_ID = settings.META_APP_ID
APP_SECRET = settings.META_APP_SECRET
FB_PAGE_ID = settings.META_PAGE_ID

# Token được load động mỗi lần dùng, không cache ở module level
# để tránh stale token sau khi .env được cập nhật
def _load_token() -> str:
    return os.getenv("META_PAGE_ACCESS_TOKEN", settings.META_PAGE_ACCESS_TOKEN)


# ============================================================
# TOKEN MANAGEMENT
# ============================================================

async def exchange_to_long_lived_page_token(short_lived_user_token: str) -> str:
    """
    Đổi Short-lived User Token → Permanent Page Access Token.

    Flow:
        Short-lived User Token (~1-2h)
            → Long-lived User Token (~60 ngày)
                → Permanent Page Token (expires_at = 0, vô hạn)

    Args:
        short_lived_user_token: User Token lấy từ Graph API Explorer

    Returns:
        Permanent Page Access Token

    Raises:
        ValueError: Nếu bất kỳ bước exchange nào thất bại
    """
    async with httpx.AsyncClient(timeout=30.0) as client:

        # --- Bước 1: Short-lived User → Long-lived User Token (~60 ngày) ---
        # Nếu token đã là long-lived, Facebook trả 500 khi cố exchange lại
        # → bắt lỗi và dùng thẳng token gốc cho Bước 2
        print("[TOKEN] Bước 1/3: Exchange Long-lived User Token...")
        try:
            r1 = await client.get(
                "https://graph.facebook.com/v20.0/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": APP_ID,
                    "client_secret": APP_SECRET,
                    "fb_exchange_token": short_lived_user_token,
                }
            )
            r1.raise_for_status()
            data1 = r1.json()
            if "error" in data1:
                raise ValueError(data1["error"]["message"])
            long_lived_user_token = data1["access_token"]
            expires_in_days = int(data1.get("expires_in", 0)) // 86400
            print(f"[TOKEN] ✅ Long-lived User Token (~{expires_in_days} ngày): {long_lived_user_token[:25]}...")
        except (httpx.HTTPStatusError, ValueError) as e:
            # Token đã long-lived rồi → dùng thẳng, không cần exchange
            print(f"[TOKEN] ℹ️  Token đã là long-lived (bỏ qua exchange: {e}) → dùng thẳng.")
            long_lived_user_token = short_lived_user_token

        # --- Bước 2: Long-lived User Token → Page Access Token ---
        print("[TOKEN] Bước 2/3: Lấy Page Access Token...")
        r2 = await client.get(
            f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}",
            params={
                "fields": "access_token,name",
                "access_token": long_lived_user_token,
            }
        )
        r2.raise_for_status()
        data2 = r2.json()
        if "error" in data2:
            raise ValueError(f"Bước 2 thất bại: {data2['error']['message']}")

        page_token = data2["access_token"]
        page_name = data2.get("name", "Unknown Page")
        print(f"[TOKEN] ✅ Page Token cho '{page_name}': {page_token[:25]}...")

        # --- Bước 3: Verify expires_at = 0 ---
        print("[TOKEN] Bước 3/3: Verify Permanent Page Token...")
        r3 = await client.get(
            "https://graph.facebook.com/v20.0/debug_token",
            params={
                "input_token": page_token,
                "access_token": f"{APP_ID}|{APP_SECRET}",
            }
        )
        r3.raise_for_status()
        debug = r3.json().get("data", {})

        expires_at  = debug.get("expires_at", -1)
        is_valid    = debug.get("is_valid", False)
        scopes      = debug.get("scopes", [])

        if not is_valid:
            raise ValueError("Token không hợp lệ sau khi exchange!")

        status = "✅ vĩnh viễn" if expires_at == 0 else f"⚠️ hết hạn lúc {expires_at}"
        print(f"[TOKEN] Valid={is_valid} | Expires={status} | Scopes={scopes}")
        print(f"\n[TOKEN] 🎉 Thành công! Dán vào .env:")
        print(f"META_PAGE_ACCESS_TOKEN={page_token}\n")

        return page_token


async def _inspect_token(token: str) -> dict:
    """Gọi debug_token và trả về raw data. Returns {} nếu API lỗi."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://graph.facebook.com/v20.0/debug_token",
                params={
                    "input_token": token,
                    "access_token": f"{APP_ID}|{APP_SECRET}",
                }
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
    except Exception as e:
        print(f"[TOKEN] ⚠️ Không thể gọi debug_token: {e}")
        return {}


async def _get_valid_page_token() -> tuple[str, str | None]:
    """
    Lấy Page Token hợp lệ để dùng cho request.

    Logic:
        1. Load token từ .env
        2. Inspect token qua debug_token API
        3a. Token là PAGE + còn hạn       → dùng luôn
        3b. Token là USER                  → tự động exchange sang Page Token
        3c. Token hết hạn hoặc invalid    → raise ValueError rõ ràng
        3d. Sắp hết hạn (< 7 ngày)        → dùng nhưng cảnh báo

    Returns:
        (valid_token, warning_message | None)
    """
    token = _load_token()

    if not token:
        raise ValueError(
            "META_PAGE_ACCESS_TOKEN chưa được cấu hình trong .env.\n"
            "→ Chạy script get_token.py để lấy Permanent Page Token."
        )

    debug = await _inspect_token(token)

    # Không gọi được debug_token API → thử dùng token trực tiếp
    if not debug:
        print("[TOKEN] ⚠️ Bỏ qua validate token — tiếp tục thử đăng bài.")
        return token, "Không thể validate token, tiếp tục với token hiện tại."

    is_valid   = debug.get("is_valid", False)
    token_type = debug.get("type", "UNKNOWN")
    expires_at = debug.get("expires_at", -1)
    scopes     = set(debug.get("scopes", []))

    # --- Token hết hạn hoặc bị revoke ---
    if not is_valid:
        expires_info = f"(expired at {expires_at})" if expires_at else ""
        raise ValueError(
            f"Token không hợp lệ hoặc đã hết hạn {expires_info}.\n"
            f"→ Vào Graph API Explorer lấy User Token mới → chạy lại get_token.py."
        )

    # --- Token là USER → tự động exchange ---
    if token_type == "USER":
        print("[TOKEN] 🔄 Phát hiện USER Token → tự động exchange sang Page Token...")
        page_token = await exchange_to_long_lived_page_token(token)
        warning = (
            f"Đã tự động exchange sang Page Token.\n"
            f"💾 Cập nhật .env:\nMETA_PAGE_ACCESS_TOKEN={page_token}"
        )
        return page_token, warning

    # --- Token là PAGE → kiểm tra scopes + thời hạn ---
    if token_type == "PAGE":
        required_scopes = {"pages_manage_posts", "pages_read_engagement"}
        missing = required_scopes - scopes
        if missing:
            raise ValueError(
                f"Page Token thiếu scope: {missing}.\n"
                f"→ Vào Meta Developer Console cấp thêm quyền → exchange lại token."
            )

        # Cảnh báo nếu token sắp hết hạn (< 7 ngày)
        warning = None
        if expires_at and expires_at > 0:
            days_left = (expires_at - int(time.time())) // 86400
            if days_left < 7:
                warning = f"Page Token còn {days_left} ngày nữa hết hạn. Nên exchange lại sớm."
                print(f"[TOKEN] ⚠️ {warning}")

        print(f"[TOKEN] ✅ Page Token hợp lệ | expires={'vĩnh viễn' if expires_at == 0 else expires_at} | scopes={scopes}")
        return token, warning

    # --- Token type không xác định ---
    raise ValueError(
        f"Token type không hợp lệ: '{token_type}' (cần 'PAGE').\n"
        f"→ Chạy get_token.py để lấy Page Token đúng loại."
    )


# ============================================================
# PUBLISHER NODE
# ============================================================

async def publisher_node(state: ContentProductionState) -> dict:
    """
    Agent Node: Xuất bản nội dung lên Facebook Fanpage.

    Ưu tiên xử lý:
        1. Video (.mp4)  → POST /{page_id}/videos
        2. Ảnh (.jpg)    → POST /{page_id}/photos
        3. Text chay     → POST /{page_id}/feed

    Tự động validate và exchange token nếu cần.
    Hỗ trợ đặt lịch qua schedule_time (Unix timestamp).
    """
    print("\n[NODE: PUBLISHER] Bắt đầu kết nối Meta Graph API...")

    if not FB_PAGE_ID:
        return {"errors": ["[PUBLISHER] Lỗi: META_PAGE_ID chưa cấu hình trong .env."]}

    # --- Validate và lấy token hợp lệ ---
    try:
        active_token, token_warning = await _get_valid_page_token()
        if token_warning:
            print(f"[PUBLISHER] ℹ️ {token_warning}")
    except ValueError as e:
        return {"errors": [f"[PUBLISHER] ❌ Token lỗi: {e}"]}

    # --- Lấy dữ liệu từ state ---
    caption: str | None       = state.get("caption")
    content: str | None       = state.get("content")
    video_path: str | None    = state.get("video_path")
    image_path: str | None    = state.get("image_path")
    schedule_time: int | None = state.get("schedule_time")

    if not caption:
        return {"errors": ["[PUBLISHER] Lỗi: State thiếu 'caption'."]}

    schedule_payload = _build_schedule_payload(schedule_time)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:

            if video_path and os.path.exists(video_path):
                print("[PUBLISHER] Chế độ: Đăng bài kèm VIDEO.")
                return await _post_video(
                    client, content or caption, video_path, schedule_payload, active_token
                )
            elif image_path and os.path.exists(image_path):
                print("[PUBLISHER] Chế độ: Đăng bài kèm ẢNH.")
                return await _post_image(
                    client, content or caption, image_path, schedule_payload, active_token
                )
            else:
                # Fallback: video/ảnh không có hoặc tạo thất bại → đăng text caption
                print("[PUBLISHER] Chế độ: Đăng bài TEXT THUẦN (video/ảnh không khả dụng).")
                return await _post_text(client, content, schedule_payload, active_token)

    except httpx.HTTPStatusError as e:
        error_msg = f"[PUBLISHER] Facebook từ chối request: HTTP {e.response.status_code} — {e.response.text}"
        print(error_msg)
        return {"errors": [error_msg]}

    except httpx.TimeoutException:
        error_msg = "[PUBLISHER] Request timeout — Facebook không phản hồi trong 120s."
        print(error_msg)
        return {"errors": [error_msg]}

    except Exception as e:
        error_msg = f"[PUBLISHER] Lỗi không xác định: {type(e).__name__}: {e}"
        print(error_msg)
        return {"errors": [error_msg]}


# ============================================================
# PRIVATE HELPERS
# ============================================================

def _build_schedule_payload(schedule_time: int | None) -> dict:
    """Tạo payload đặt lịch, validate min/max theo quy định Facebook."""
    if not schedule_time:
        return {}

    now = int(time.time())
    if schedule_time < now + 600:
        print("[PUBLISHER] ⚠️ schedule_time < 10 phút → ĐĂNG NGAY.")
        return {}
    if schedule_time > now + 6_480_000:
        print("[PUBLISHER] ⚠️ schedule_time > 75 ngày → ĐĂNG NGAY.")
        return {}

    print(f"[PUBLISHER] ⏰ ĐẶT LỊCH lúc Unix={schedule_time}")
    return {
        "published": "false",
        "scheduled_publish_time": str(schedule_time),
    }


async def _post_video(
    client: httpx.AsyncClient,
    description: str,
    video_path: str,
    schedule_payload: dict,
    access_token: str,
) -> dict:
    print(f"[PUBLISHER] 🎬 Upload video: {os.path.basename(video_path)}")
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/videos"
    with open(video_path, "rb") as f:
        resp = await client.post(
            url,
            data={"description": description, "access_token": access_token, **schedule_payload},
            files={"source": (os.path.basename(video_path), f, "video/mp4")},
        )
    resp.raise_for_status()
    video_id = resp.json().get("id")
    post_url = f"https://facebook.com/{FB_PAGE_ID}/videos/{video_id}"
    print(f"[NODE: PUBLISHER] ✅ Video đăng thành công! {post_url}")
    return {"post_url": post_url}


async def _post_image(
    client: httpx.AsyncClient,
    caption: str,
    image_path: str,
    schedule_payload: dict,
    access_token: str,
) -> dict:
    print(f"[PUBLISHER] 🖼️ Upload ảnh: {os.path.basename(image_path)}")
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"
    with open(image_path, "rb") as f:
        resp = await client.post(
            url,
            data={"message": caption, "access_token": access_token, **schedule_payload},
            files={"source": (os.path.basename(image_path), f, "image/jpeg")},
        )
    resp.raise_for_status()
    post_id = resp.json().get("post_id")
    post_url = f"https://facebook.com/{post_id}"
    print(f"[NODE: PUBLISHER] ✅ Ảnh đăng thành công! {post_url}")
    return {"post_url": post_url}


async def _post_text(
    client: httpx.AsyncClient,
    caption: str,
    schedule_payload: dict,
    access_token: str,
) -> dict:
    print("[PUBLISHER] 📝 Đăng Text chay...")
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/feed"
    resp = await client.post(
        url,
        data={"message": caption, "access_token": access_token, **schedule_payload},
    )
    resp.raise_for_status()
    post_id = resp.json().get("id")
    post_url = f"https://facebook.com/{post_id}"
    print(f"[NODE: PUBLISHER] ✅ Text đăng thành công! {post_url}")
    return {"post_url": post_url}
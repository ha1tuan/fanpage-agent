from app.agents.states import ContentProductionState
import httpx
from app.core.settings import get_settings

setting = get_settings()


def _h(text: str) -> str:
    """Escape các ký tự đặc biệt HTML để tránh Telegram parse lỗi."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def notifier_node(state: ContentProductionState) -> dict:
    """
    Agent 7: Tổng hợp kết quả từ luồng LangGraph và bắn báo cáo về Telegram của Boss.
    """
    print("\n[NODE: NOTIFIER] Đang soạn báo cáo gửi Sếp qua Telegram...")

    if not setting.TELEGRAM_BOT_TOKEN or not setting.TELEGRAM_CHAT_ID:
        error_msg = "[NOTIFIER] Bỏ qua: Chưa cấu hình TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID."
        print(error_msg)
        return {"errors": [error_msg]}

    topic    = state.get("topic", "Không xác định")
    post_url = state.get("post_url")
    errors   = state.get("errors", [])

    if post_url:
        message = (
            f"✅ <b>Đăng bài thành công!</b>\n"
            f"🎯 <b>Topic:</b> <code>{_h(topic)}</code>\n"
            f"🔗 {post_url}"
        )
    else:
        message = (
            f"❌ <b>Đăng bài thất bại!</b>\n"
            f"🎯 <b>Topic:</b> <code>{_h(topic)}</code>\n"
        )
        if errors:
            message += f"⚠️ <b>{len(errors)} lỗi:</b>\n"
            for i, err in enumerate(errors, 1):
                # Cắt bớt nếu quá dài, escape HTML để ký tự đặc biệt (_, *, <, >) không phá vỡ format
                raw = str(err)
                clean_err = (raw[:300] + "...") if len(raw) > 300 else raw
                message += f"{i}. <code>{_h(clean_err)}</code>\n"
        else:
            message += "Luồng bị dừng do lỗi không xác định."

    try:
        url = f"https://api.telegram.org/bot{setting.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": setting.TELEGRAM_CHAT_ID,
            "text": message,
            # HTML mode: dùng <b>, <code>, <i> thay Markdown
            # An toàn hơn với nội dung động chứa _, *, ` từ error messages và URLs
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

        print("[NODE: NOTIFIER] ✈️ Đã gửi báo cáo Telegram thành công!")
        return {}

    except httpx.HTTPStatusError as e:
        print(f"[NOTIFIER][ERROR] Telegram API từ chối: {e.response.text}")
        return {}
    except Exception as e:
        print(f"[NOTIFIER][ERROR] Lỗi hệ thống khi gửi tin: {str(e)}")
        return {}
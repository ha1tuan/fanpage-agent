import uuid
import httpx
from fastapi import APIRouter, Request, BackgroundTasks

from app.agents.graph import app_graph
from app.core.settings import get_settings

router = APIRouter(prefix="/telegram", tags=["Agent"])


def _h(text: str, limit: int = 0) -> str:
    """Escape ký tự đặc biệt HTML và tuỳ chọn cắt bớt nếu quá dài."""
    result = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if limit and len(result) > limit:
        result = result[:limit] + "..."
    return result


@router.post("/webhook", summary="Nhận lệnh trực tiếp từ Telegram Bot")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()

        # -------------------------------------------------------
        # XỬ LÝ CALLBACK QUERY (nút bấm Inline Keyboard)
        # -------------------------------------------------------
        if "callback_query" in data:
            cq = data["callback_query"]
            cq_id = cq["id"]
            chat_id = cq["message"]["chat"]["id"]
            message_id = cq["message"]["message_id"]
            callback_data = cq.get("data", "")

            if callback_data.startswith("approve_"):
                thread_id = callback_data[len("approve_"):]
                config = {"configurable": {"thread_id": thread_id}}

                await app_graph.aupdate_state(config, {"review_status": "approved"})
                await edit_telegram_msg(
                    chat_id, message_id,
                    "✅ Sếp đã duyệt! Đang xử lý lên sóng, chờ tí nhé Boss...",
                )
                await answer_callback_query(cq_id)

                async def _resume_approved(cfg=config):
                    await app_graph.ainvoke(None, config=cfg)

                background_tasks.add_task(_resume_approved)

            elif callback_data.startswith("reject_"):
                thread_id = callback_data[len("reject_"):]
                await answer_callback_query(cq_id)
                await send_telegram_msg(
                    chat_id,
                    f"📝 Oke Boss! Gõ lệnh dưới đây để chê cho đệ tử sửa lại:\n\n"
                    f"<code>/sua {_h(thread_id)} [lời chê của sếp]</code>\n\n"
                    f"Ví dụ: <code>/sua {_h(thread_id)} Caption nhạt quá, thêm câu hook mạnh hơn</code>"
                )

            return {"status": "ok"}

        # -------------------------------------------------------
        # XỬ LÝ TIN NHẮN VĂN BẢN
        # -------------------------------------------------------
        if "message" not in data or "text" not in data["message"]:
            return {"status": "ok"}

        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"].strip()

        # --- LỆNH /vietbai [topic] ---
        if text.startswith("/vietbai"):
            topic = text[len("/vietbai"):].strip()
            if not topic:
                await send_telegram_msg(
                    chat_id,
                    "⚠️ Boss quên nhập Topic rồi. Cú pháp: `/vietbai [Topic]`"
                )
                return {"status": "ok"}

            await send_telegram_msg(
                chat_id,
                f"🫡 Đã nhận lệnh! Đang cho đệ tử đi săn bài về topic: <b>{_h(topic)}</b>"
            )

            thread_id = f"thread_{uuid.uuid4().hex[:8]}"
            config = {"configurable": {"thread_id": thread_id}}
            initial_state = {
                "topic": topic,
                "review_status": "pending",
                "errors": [],
            }

            async def run_vietbai(cfg=config, tid=thread_id, cid=chat_id, s=initial_state):
                await app_graph.ainvoke(s, config=cfg)
                snapshot = await app_graph.aget_state(cfg)
                values = snapshot.values
                errors = values.get("errors", [])
                caption = values.get("caption")
                content = values.get("content")
                video_script = values.get("video_script")
                raw_materials = values.get("raw_materials", [])
                raw_material_text = raw_materials[0][:300] + "..." if raw_materials else "(chưa có)"

                # Nếu writer fail (không có content) → báo lỗi thay vì gửi draft trống
                if not caption or not content:
                    error_detail = "\n".join(errors) if errors else "Không rõ nguyên nhân."
                    await send_telegram_msg(
                        cid,
                        f"❌ <b>Đệ tử bị lỗi khi viết bài cho Thread</b> <code>{_h(tid)}</code>\n\n"
                        f"<b>Chi tiết:</b>\n<code>{_h(error_detail, 500)}</code>\n\n"
                        f"Thử lại bằng <code>/vietbai {_h(values.get('topic', ''))}</code>"
                    )
                    return

                review_text = (
                    f"📋 <b>DRAFT BÀI — Thread</b> <code>{_h(tid)}</code>\n\n"
                    f"📝 <b>NỘI DUNG CHÍNH:</b>\n{_h(content, 800)}\n\n"
                    f"📣 <b>CAPTION FACEBOOK:</b>\n{_h(caption, 400)}\n\n"
                    f"🎬 <b>KỊCH BẢN VIDEO:</b>\n<code>{_h(video_script or '(chưa có)', 500)}</code>\n\n"
                    f"📝 <b>NGUỒN:</b>\n<code>{_h(raw_material_text, 300)}</code>\n\n"
                    f"Sếp xem ổn chưa ạ?"
                )
                await send_telegram_msg_with_keyboard(cid, review_text, _review_keyboard(tid))

            background_tasks.add_task(run_vietbai)

        # --- LỆNH /sua [thread_id] [feedback] ---
        elif text.startswith("/sua"):
            parts = text[len("/sua"):].strip().split(" ", 1)
            if len(parts) < 2:
                await send_telegram_msg(
                    chat_id,
                    "⚠️ Sai cú pháp. Dùng: `/sua [thread_id] [lời chê]`"
                )
                return {"status": "ok"}

            thread_id, feedback = parts[0], parts[1]
            config = {"configurable": {"thread_id": thread_id}}

            await send_telegram_msg(chat_id, "📝 Đã nhận feedback! Đang bắt đệ tử sửa lại...")

            async def run_sua(cfg=config, tid=thread_id, cid=chat_id, fb=feedback):
                await app_graph.aupdate_state(cfg, {"review_status": "rejected", "human_feedback": fb})
                await app_graph.ainvoke(None, config=cfg)
                snapshot = await app_graph.aget_state(cfg)
                values = snapshot.values
                caption = values.get("caption") or "(chưa có caption)"
                content = values.get("content") or values.get("topic") or "(chưa có nội dung)"
                video_script = values.get("video_script") or "(chưa có kịch bản)"

                review_text = (
                    f"🔄 <b>BẢN SỬA — Thread</b> <code>{_h(tid)}</code>\n\n"
                    f"📝 <b>NỘI DUNG CHÍNH:</b>\n{_h(content, 800)}\n\n"
                    f"📣 <b>CAPTION FACEBOOK:</b>\n{_h(caption, 400)}\n\n"
                    f"🎬 <b>KỊCH BẢN VIDEO:</b>\n<code>{_h(video_script, 500)}</code>\n\n"
                    f"Đệ tử đã sửa theo ý sếp, xem lại nhé!"
                )
                await send_telegram_msg_with_keyboard(cid, review_text, _review_keyboard(tid))

            background_tasks.add_task(run_sua)

        return {"status": "ok"}

    except Exception as e:
        print(f"[WEBHOOK ERROR] {str(e)}")
        return {"status": "error"}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _review_keyboard(thread_id: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ Duyệt & Lên Sóng", "callback_data": f"approve_{thread_id}"},
            {"text": "❌ Chê, Bắt Sửa Lại", "callback_data": f"reject_{thread_id}"},
        ]]
    }


async def send_telegram_msg(chat_id: int, text: str):
    settings = get_settings()
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload)
        if not resp.is_success:
            print(f"[TELEGRAM] send_msg lỗi {resp.status_code}: {resp.text[:200]}")


async def send_telegram_msg_with_keyboard(chat_id: int, text: str, reply_markup: dict):
    settings = get_settings()
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload)
        if not resp.is_success:
            print(f"[TELEGRAM] send_msg_keyboard lỗi {resp.status_code}: {resp.text[:200]}")


async def edit_telegram_msg(chat_id: int, message_id: int, text: str):
    settings = get_settings()
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload)
        if not resp.is_success:
            print(f"[TELEGRAM] edit_msg lỗi {resp.status_code}: {resp.text[:200]}")


async def answer_callback_query(callback_query_id: str, text: str = ""):
    settings = get_settings()
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "text": text}
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

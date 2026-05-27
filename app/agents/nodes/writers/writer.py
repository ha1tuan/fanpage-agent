from app.services.llm_service import get_chat_model
from app.agents.states import ContentProductionState
import json
import re
from langchain_core.messages import SystemMessage, HumanMessage
from .prompt import WRITER_SYSTEM_PROMPT


def _repair_json(text: str) -> str:
    """Escape literal newlines and tabs inside JSON string values."""
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == "\\":
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch == "\n":
            result.append("\\n")
        elif in_string and ch == "\r":
            result.append("\\r")
        elif in_string and ch == "\t":
            result.append("\\t")
        else:
            result.append(ch)
    return "".join(result)


def _parse_llm_json(raw: str) -> dict:
    """
    Bóc tách JSON từ output LLM theo 4 tầng ưu tiên:
    1. Xóa markdown code block rồi parse.
    2. Repair literal newlines trong string values rồi parse.
    3. Tìm cặp ngoặc nhọn ngoài cùng { ... } (balanced) rồi parse + repair.
    4. Regex tìm từng trường content/caption/video_script trực tiếp.
    """
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)

    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # Tầng 2: repair newlines rồi thử lại
    try:
        return json.loads(_repair_json(stripped))
    except (json.JSONDecodeError, ValueError):
        pass

    # Tầng 3: Tìm JSON object đầu tiên có ngoặc balanced
    depth, start, end = 0, -1, -1
    for i, ch in enumerate(stripped):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if start != -1 and end != -1:
        candidate = stripped[start:end]
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            return json.loads(_repair_json(candidate))
        except (json.JSONDecodeError, ValueError):
            pass

    # Tầng 4: Regex fallback — tìm từng trường
    result = {}
    for key in ("content", "caption", "video_script"):
        m = re.search(
            rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"',
            stripped,
            re.DOTALL,
        )
        if m:
            result[key] = m.group(1).replace("\\n", "\n").replace('\\"', '"')
    if result:
        return result

    raise ValueError(f"Không thể bóc tách JSON. Raw (200 ký tự đầu): {raw[:200]!r}")


def _build_context(raw_materials: list[str]) -> str:
    """
    Chuyển raw_materials từ scraper thành context rõ ràng cho LLM.
    Scraper trả về mỗi item theo format:
      [Nguồn: title - url]
      Tóm tắt: ...
      Nỗi đau (Pain point): ...
      Tại sao chọn: ...
    """
    blocks = []
    for i, material in enumerate(raw_materials, 1):
        blocks.append(f"--- TÀI LIỆU {i} ---\n{material.strip()}")
    return "\n\n".join(blocks)


async def writer_node(state: ContentProductionState) -> dict:
    print("\n[NODE: WRITER] Đang mài mực viết content...")

    raw_materials: list[str] = state.get("raw_materials") or []
    topic: str = state.get("topic") or "Phát triển bản thân"
    human_feedback: str | None = state.get("human_feedback")

    # Log để debug
    print(f"[WRITER] Nhận được {len(raw_materials)} tài liệu từ Scraper.")
    for i, m in enumerate(raw_materials, 1):
        print(f"[WRITER] Tài liệu {i} (50 ký tự đầu): {m[:50]!r}")

    if not raw_materials:
        return {
            "errors": ["[WRITER] Không có data thô từ Scraper — kiểm tra lại node Scraper."],
            "review_status": "pending",
        }

    # Xây dựng context có cấu trúc từ dữ liệu scraper
    context_text = _build_context(raw_materials)
    user_content = f"TOPIC: {topic}\n\n{context_text}"

    if human_feedback:
        print(f"[WRITER] Boss feedback: '{human_feedback}'")
        user_content += (
            f"\n\n[BOSS FEEDBACK - BẮT BUỘC SỬA]: {human_feedback}"
            f"\nViết lại toàn bộ dựa trên góp ý này, không giữ lại bản cũ."
        )

    try:
        llm = get_chat_model()
        response = await llm.ainvoke([
            SystemMessage(content=WRITER_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ])
        final_text = response.content
        print(f"[WRITER] Raw LLM output (150 ký tự đầu): {final_text[:150]!r}")

        data = _parse_llm_json(final_text)

        content = data.get("content")
        caption = data.get("caption")
        video_script = data.get("video_script")

        # LLM đôi khi trả video_script là dict lồng nhau
        if isinstance(video_script, dict):
            video_script = json.dumps(video_script, ensure_ascii=False, indent=2)

        missing = [
            field for field, val in [
                ("content", content),
                ("caption", caption),
                ("video_script", video_script),
            ]
            if not val
        ]
        if missing:
            raise ValueError(f"LLM trả JSON nhưng thiếu các trường: {', '.join(missing)}.")

        print(f"[NODE: WRITER] Thành công! content={len(content)}c, caption={len(caption)}c")

        # Giữ lại raw_materials để Telegram và Notifier đọc được nguồn tham khảo
        return {
            "raw_materials": raw_materials,
            "content": content,
            "caption": caption,
            "video_script": video_script,
            "review_status": "pending",
            "human_feedback": None,
        }

    except Exception as e:
        error_msg = f"[WRITER][ERROR] {str(e)}"
        print(error_msg)
        # Giữ lại raw_materials ngay cả khi writer lỗi
        return {
            "raw_materials": raw_materials,
            "errors": [error_msg],
            "review_status": "pending",
        }

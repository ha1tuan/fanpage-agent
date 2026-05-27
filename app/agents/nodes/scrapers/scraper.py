from app.services.llm_service import get_chat_model
from app.agents.states import ContentProductionState
import json
from langchain_core.messages import HumanMessage
from exa_py import AsyncExa

from app.agents.nodes.scrapers.prompt import SCRAPER_SYSTEM_PROMPT, QUERRY_SEARCH_PROMPT
from app.core.settings import get_settings


settings = get_settings()
exa_client = AsyncExa(api_key=settings.EXA_API_KEY)

# Lazy-init: không khởi tạo ChatOllama ở module level để tránh đọc sai env var
# trước khi docker-compose inject OLLAMA_BASE_URL vào container
def _get_llm():
    return get_chat_model()


async def _build_search_query(topic: str) -> str:
    prompt = QUERRY_SEARCH_PROMPT.format(topic=topic)
    response = await _get_llm().ainvoke([HumanMessage(content=prompt)])
    return response.content.strip().strip('"')


async def _extract_insights(title: str, url: str, content: str, topic: str) -> dict:
    prompt = SCRAPER_SYSTEM_PROMPT.format(
        topic=topic,
        title=title,
        url=url,
        content=content,
    )
    response = await _get_llm().ainvoke([HumanMessage(content=prompt)])
    try:
        return json.loads(response.content.strip())
    except json.JSONDecodeError:
        return {
            "summary": "Không thể phân tích nội dung.",
            "pain_point": "Không xác định.",
            "why_chosen": "Không xác định.",
        }


async def scraper_node(state: ContentProductionState) -> dict:
    topic = state.get("topic", "").strip()

    if not topic:
        return {
            "raw_materials": [],
            "errors": ["[SCRAPER] Topic trống, không thể tìm kiếm."],
        }

    # ── Bước 1: Tối ưu query ──────────────────────────────────────────────────
    try:
        search_query = await _build_search_query(topic)
        print(f"[SCRAPER] Search query: {search_query!r}")
    except Exception as e:
        search_query = f"best in-depth article about {topic}"
        print(f"[SCRAPER] Build query thất bại ({e}), dùng fallback: {search_query!r}")

    # ── Bước 2: Gọi AsyncExa.search() ────────────────────────────────────────
    try:
        exa_response = await exa_client.search(
            query=search_query,
            type="auto",
            num_results=5,
            contents={"text": {"max_characters": 5000}},
            start_published_date="2023-01-01",
            exclude_domains=["pinterest.com", "quora.com"],
        )
        print(f"[SCRAPER] Exa trả về {len(exa_response.results)} kết quả.")
    except Exception as e:
        print(f"[SCRAPER][ERROR] Exa search thất bại: {e}")
        return {
            "raw_materials": [],
            "errors": [f"[SCRAPER] Exa search thất bại: {e}"],
        }

    # ── Bước 3: Chọn bài có score cao nhất, có nội dung ──────────────────────
    best_result = None
    best_score = -1.0

    for result in exa_response.results:
        content = (result.text or "").strip()
        if not content:
            continue
        score = getattr(result, "score", 0.0) or 0.0
        if score > best_score:
            best_score = score
            best_result = {
                "title": result.title or "Untitled",
                "url": result.url,
                "content": content[:3000],
            }

    if not best_result:
        print("[SCRAPER] Không có bài nào có nội dung text.")
        return {
            "raw_materials": [],
            "errors": ["[SCRAPER] Exa không tìm thấy bài viết nào có nội dung."],
        }

    # ── Bước 4: LLM extract insights ─────────────────────────────────────────
    insights = await _extract_insights(
        title=best_result["title"],
        url=best_result["url"],
        content=best_result["content"],
        topic=topic,
    )

    # ── Bước 5: Format theo chuẩn raw_materials ───────────────────────────────
    formatted = (
        f"[Nguồn: {best_result['title']} - {best_result['url']}]\n"
        f"Tóm tắt: {insights['summary']}\n"
        f"Nỗi đau (Pain point): {insights['pain_point']}\n"
        f"Tại sao chọn: {insights['why_chosen']}"
    )

    print(f"[NODE: SCRAPER] Thành công! Đã trích xuất 1 góc nhìn sắc sảo.")
    return {"raw_materials": [formatted]}

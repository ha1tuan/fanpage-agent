from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

# Import State và các Node function chúng ta đã viết
from app.agents.nodes.video_compose.video_compose import video_compose_node
from app.agents.nodes.publisher.publisher import publisher_node
from app.agents.nodes.notifier.notifier import notifier_node
from app.agents.states import ContentProductionState
from app.agents.nodes.writers.writer import writer_node
from app.agents.nodes.scrapers.scraper import scraper_node
from app.core.settings import get_settings

setting = get_settings()

# ==========================================
# 1. HÀM ĐIỀU HƯỚNG TỪ HITL (ROUTER)
# ==========================================
def human_review_router(state: ContentProductionState) -> str:
    """
    Hàm này quyết định Graph sẽ đi đâu sau khi được Resume từ điểm ngắt.
    Nó đọc trường 'review_status' do bạn (Boss) cập nhật qua API.
    """
    status = state.get("review_status")
    
    if status == "approved":
        return "approved"  # Đi tiếp xuống làm Media
    elif status == "rejected":
        return "rejected"  # Quay lại bắt AI viết lại
    else:
        # Nếu chưa có quyết định mà Graph vô tình bị gọi chạy tiếp, ép nó dừng lại an toàn
        return "pending"

# ==========================================
# 2. KHỞI TẠO VÀ LIÊN KẾT CÁC NODE
# ==========================================
workflow = StateGraph(ContentProductionState)

# Khai báo các Node (đặt tên cho từng Agent)
workflow.add_node("scraper", scraper_node)
workflow.add_node("writer", writer_node)
workflow.add_node("video_compose", video_compose_node)
workflow.add_node("publisher", publisher_node)
workflow.add_node("notifier", notifier_node)

# Thiết lập các đường nối cơ bản (Edges)
workflow.add_edge(START, "scraper")
workflow.add_edge("scraper", "writer")

# ==========================================
# 3. THIẾT LẬP RẼ NHÁNH VÀ ĐIỂM NGẮT
# ==========================================
# Từ Node "writer", luồng sẽ đi qua hàm Router để biết hướng đi tiếp
workflow.add_conditional_edges(
    "writer",
    human_review_router,
    {
        "approved": "video_compose",  # Nhánh 1: Sang làm video
        "rejected": "writer",      # Nhánh 2: Quay lại node writer
        "pending": END             # Fallback: Kết thúc luồng nếu có lỗi trạng thái
    }
)

# Nối nốt các chặng cuối
workflow.add_edge("video_compose", "publisher")
workflow.add_edge("publisher", "notifier")
workflow.add_edge("notifier", END)

# ==========================================
# 4 & 5. GRAPH PROXY + ASYNC SETUP
# ==========================================
DB_URI = setting.DATABASE_URL.replace("+asyncpg", "")

# _ref[0] sẽ được gán trong setup_graph() (gọi từ lifespan FastAPI)
# Không thể tạo AsyncPostgresSaver ở module-level vì nó cần running event loop
_ref: list = [None]

class _GraphProxy:
    """Cho phép `from graph import app_graph` hoạt động trước khi graph được khởi tạo."""
    def __getattr__(self, name: str):
        if _ref[0] is None:
            raise RuntimeError("Graph chưa được khởi tạo — server đang khởi động.")
        return getattr(_ref[0], name)

app_graph = _GraphProxy()

async def setup_graph():
    """Tạo pool, checkpointer async và compile graph. Gọi từ FastAPI lifespan."""
    pool = AsyncConnectionPool(conninfo=DB_URI, kwargs={"autocommit": True})
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    _ref[0] = workflow.compile(
        checkpointer=checkpointer,
        interrupt_after=["writer"]
    )
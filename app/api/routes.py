import uuid
from fastapi import HTTPException, BackgroundTasks
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

# Import Graph đã được compile cùng Checkpointer từ app/agents/graph.py
from app.agents.graph import app_graph
router = APIRouter(prefix="/agents", tags=["Agent"])

class StartJobRequest(BaseModel):
    topic: str
    schedule_time: Optional[int] = None # Unix timestamp nếu muốn hẹn giờ đăng

class HumanActionRequest(BaseModel):
    action: str  # Bắt buộc là "approved" hoặc "rejected"
    feedback: Optional[str] = None  # Lời chê/góp ý để Ollama viết lại


@router.post("/start", summary="1. Khởi động Agent săn bài và viết bài")
async def start_content_job(request: StartJobRequest, background_tasks: BackgroundTasks):
    """
    Nhập topic. Graph sẽ chạy qua Scraper -> Writer rồi tự động DỪNG lại chờ duyệt.
    """
    thread_id = f"thread_{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state = {
        "topic": request.topic,
        "schedule_time": request.schedule_time,
        "review_status": "pending",
        "errors": []
    }
    
    # Hàm chạy nền để API không bị treo chờ xử lý
    async def run_graph():
        print(f"\n[API] Đang chạy luồng ngầm cho Thread: {thread_id}")
        await app_graph.ainvoke(initial_state, config=config)
        print(f"[API] Thread {thread_id} đã chạm điểm dừng (Interrupt). Chờ duyệt!")

    background_tasks.add_task(run_graph)
    
    return {
        "status": "success",
        "message": f"Hệ thống đang săn bài cho topic: '{request.topic}'",
        "thread_id": thread_id
    }

@router.get("/review/{thread_id}", summary="2. Đọc bài viết đang chờ duyệt")
async def get_content_for_review(thread_id: str):
    """
    Xem lại Caption, Image Prompt và Video Script do Agent 2 (Ollama) vừa viết.
    """
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        graph_state = await app_graph.aget_state(config)
        if not graph_state.values:
            raise HTTPException(status_code=404, detail="Không tìm thấy Thread này.")

        values = graph_state.values
        return {
            "thread_id": thread_id,
            "topic": values.get("topic"),
            "review_status": values.get("review_status"),
            "content": {
                "caption": values.get("caption"),
                "image_prompt": values.get("image_prompt"),
                "video_script": values.get("video_script")
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi: {str(e)}")

@router.post("/action/{thread_id}", summary="3. Chốt duyệt hoặc Bắt sửa lại")
async def human_review_action(thread_id: str, request: HumanActionRequest, background_tasks: BackgroundTasks):
    """
    Gửi action "approved" để chạy tiếp làm hình/video/đăng bài.
    Gửi action "rejected" kèm feedback để quay lại bắt Ollama viết lại.
    """
    if request.action not in ["approved", "rejected"]:
        raise HTTPException(status_code=400, detail="Action phải là 'approved' hoặc 'rejected'.")
        
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        # Cập nhật State hiện tại
        update_data = {"review_status": request.action}
        if request.action == "rejected":
            if not request.feedback:
                raise HTTPException(status_code=400, detail="Cần có 'feedback' để AI biết đường sửa.")
            update_data["human_feedback"] = request.feedback
            
        # Ghi đè State vào Checkpoint
        await app_graph.aupdate_state(config, update_data, as_node="writer")

        # Khởi chạy tiếp Graph từ điểm đang dừng
        async def resume_graph():
            print(f"\n[API] Resume Thread: {thread_id} với quyết định: {request.action}")
            await app_graph.ainvoke(None, config=config)

        background_tasks.add_task(resume_graph)
        
        return {
            "status": "success",
            "message": f"Đã ghi nhận lệnh '{request.action}'. Hệ thống đang tiếp tục chạy ngầm."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý HITL: {str(e)}")

@router.post("/token-exchange", summary="0. Đổi User Token → Page Token (chạy 1 lần)")
async def exchange_token(body: dict):
    """
    Nhận short-lived User Token, trả về Permanent Page Access Token.
    Lưu token nhận được vào META_PAGE_ACCESS_TOKEN trong .env.

    Body: { "user_token": "EAA..." }
    """
    from app.agents.nodes.publisher.publisher import get_permanent_page_token
    user_token = body.get("user_token", "").strip()
    if not user_token:
        raise HTTPException(status_code=400, detail="Thiếu 'user_token' trong body.")
    try:
        page_token = await get_permanent_page_token(user_token)
        return {
            "status": "success",
            "page_access_token": page_token,
            "note": "Lưu giá trị này vào META_PAGE_ACCESS_TOKEN trong file .env"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status/{thread_id}", summary="4. Kiểm tra tiến độ & Lấy link Media")
async def check_thread_status(thread_id: str):
    """
    Kiểm tra xem hệ thống đã đăng bài xong chưa, có lỗi gì không, và lấy link xem trước file mp4/jpg.
    """
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        graph_state = await app_graph.aget_state(config)
        if not graph_state.values:
            raise HTTPException(status_code=404, detail="Không tìm thấy Thread này.")

        values = graph_state.values
        next_nodes = graph_state.next
        
        # Build URL cục bộ để xem ảnh/video
        base_url = "http://localhost:8000/" 
        image_url = base_url + values["image_path"] if values.get("image_path") else None
        video_url = base_url + values["video_path"] if values.get("video_path") else None

        return {
            "thread_id": thread_id,
            "topic": values.get("topic"),
            "status": values.get("review_status"),
            "is_waiting_for_approval": len(next_nodes) > 0, 
            "assets": {
                "image": image_url,
                "video": video_url
            },
            "facebook_post_url": values.get("post_url"),
            "errors": values.get("errors", [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi: {str(e)}")
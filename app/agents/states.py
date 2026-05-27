from typing import TypedDict, Annotated, List, Optional
from operator import add

class ContentProductionState(TypedDict):
    # 1. Input & Context (Khởi tạo ban đầu)
    topic: str
    target_audience: str
    
    # 2. Scraper Data
    raw_materials: List[str]  # Chứa các text/quote cào được
    
    # 3. Writer Output
    content: Optional[str]
    caption: Optional[str]
    video_script: Optional[str]
    affiliate_link: Optional[str]

    # 4. Human-In-The-Loop (HITL)
    review_status: str  # "pending", "approved", "rejected"
    human_feedback: Optional[str]
    schedule_time: Optional[int]  # Unix timestamp để đặt lịch đăng Facebook

    # 5. Generated Assets
    image_path: Optional[str]
    video_path: Optional[str]
    
    # 6. Publishing & Notifier
    post_url: Optional[str] # Link bài viết trên Facebook sau khi publish
    
    # 7. System / Debug
    # Sử dụng reducer 'add' để dồn lỗi từ các agent vào một list, không bị ghi đè
    errors: Annotated[List[str], add]
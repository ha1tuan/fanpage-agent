from app.core.settings import get_settings
from app.agents.states import ContentProductionState
import os
import uuid
import base64
import httpx

setting = get_settings()

async def image_gen_node(state: ContentProductionState) -> dict:
    """
    Agent 4: Sử dụng Gemini (Imagen 3) để vẽ ảnh.
    Ưu điểm: Render Text cực tốt, ảnh chân thực. Trả kết quả base64 ngay lập tức.
    """
    print("\n[NODE: IMAGE GEN] Gọi Gemini Imagen 3 vẽ ảnh...")
    
    prompt = state.get("image_prompt")
    if not prompt:
        return {"errors": ["[IMAGE GEN] Bỏ qua do không có image_prompt."]}

    if not setting.GEMINI_API_KEY:
        return {"errors": ["[IMAGE GEN] LỖI: Thiếu GOOGLE_API_KEY."]}

    try:
        # Endpoint chính thức của Imagen 3 qua Google Generative Language API
        url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-images:predict?key={setting.GEMINI_API_KEY}"
        
        payload = {
            "instances": [
                {"prompt": prompt}
            ],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "1:1" # Có thể đổi thành "16:9" hoặc "9:16" tùy nền tảng
            }
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            
            data = response.json()
            
            # Bóc tách chuỗi Base64 từ kết quả trả về
            predictions = data.get("predictions", [])
            if not predictions:
                raise ValueError("Gemini không trả về ảnh. Có thể prompt vi phạm Safety Filter.")
                
            b64_image = predictions[0].get("bytesBase64Encoded")
            
            # Giải mã Base64 và lưu ra file vật lý
            file_name = f"gemini_{uuid.uuid4().hex[:8]}.jpeg"
            file_path = os.path.join(setting.IMAGE_OUTPUT_DIR, file_name)
            
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64_image))
                
            print(f"[NODE: IMAGE GEN] Thành công! Ảnh đã lưu tại: {file_path}")
            return {"image_path": file_path}

    except Exception as e:
        error_msg = f"[IMAGE GEN][ERROR] Lỗi gọi Gemini API: {str(e)}"
        print(error_msg)
        return {"errors": [error_msg]}
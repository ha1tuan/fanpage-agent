import re
import time
import jwt
import json as _json
from app.agents.states import ContentProductionState
import os
import uuid
import asyncio
import httpx
from app.core.settings import get_settings

setting = get_settings()

POLL_INTERVAL = 5
MAX_POLL = 72
TTS_VOICE = "vi-VN-NamMinhNeural"


def encode_jwt_token(ak, sk):
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": ak,
        "exp": int(time.time()) + 1800,
        "nbf": int(time.time()) - 5,
    }
    return jwt.encode(payload, sk, headers=headers)


def _parse_kling_duration(seconds: int) -> str:
    return "10" if seconds >= 8 else "5"


def _extract_scenes(video_script) -> list[dict]:
    """
    Parse video_script và trả về:
      [{"prompt": ..., "duration": "5"|"10", "voiceover": ...}, ...]
    """
    if isinstance(video_script, dict):
        video_script = _json.dumps(video_script, ensure_ascii=False)

    scenes = []

    # --- Tầng 1: Parse đầy đủ [PHÂN CẢNH N - Xs-Ys] ---
    scene_blocks = re.finditer(
        r'\[PHÂN CẢNH \d+\s*[-–]\s*(\d+)s?\s*[-–]\s*(\d+)s\](.*?)(?=\[PHÂN CẢNH|\nÂm nhạc:|\Z)',
        video_script,
        re.DOTALL | re.IGNORECASE,
    )
    for m in scene_blocks:
        start_s, end_s = int(m.group(1)), int(m.group(2))
        block = m.group(3)
        duration = _parse_kling_duration(end_s - start_s)

        visual_m = re.search(
            r'Visual:\s*(.+?)(?=\nVoiceover:|\Z)',
            block, re.DOTALL | re.IGNORECASE,
        )
        voiceover_m = re.search(
            r'Voiceover:\s*(.+?)(?=\nVisual:|\n\[|\Z)',
            block, re.DOTALL | re.IGNORECASE,
        )
        prompt = visual_m.group(1).strip().replace("\n", " ") if visual_m else block.strip()
        voiceover = voiceover_m.group(1).strip().replace("\n", " ") if voiceover_m else ""
        if prompt:
            scenes.append({"prompt": prompt, "duration": duration, "voiceover": voiceover})

    if scenes:
        return scenes

    # --- Tầng 2: Không có timestamp, chỉ tìm "Visual:" ---
    visuals = re.findall(
        r'Visual:\s*(.+?)(?=\nVoiceover:|\n\[PHÂN CẢNH|\nÂm nhạc:|\Z)',
        video_script, re.DOTALL | re.IGNORECASE,
    )
    if visuals:
        return [
            {"prompt": v.strip().replace("\n", " "), "duration": "10", "voiceover": ""}
            for v in visuals if v.strip()
        ]

    # --- Tầng 3: Fallback hoàn toàn ---
    return [{"prompt": video_script.strip(), "duration": "10", "voiceover": ""}]


# ==========================================
# KLING API
# ==========================================

async def _submit_task(
    client: httpx.AsyncClient, prompt: str, duration: str, headers: dict, scene_idx: int
) -> str:
    payload = {
        "model_name": "kling-v2-6",
        "mode": "pro",
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": "9:16",
        "motion_has_audio": True,
    }
    resp = await client.post(
        "https://api.klingai.com/v1/videos/text2video",
        json=payload, headers=headers,
    )
    resp.raise_for_status()
    task_id = resp.json().get("data", {}).get("task_id")
    if not task_id:
        raise ValueError(f"Kling không trả về task_id cho cảnh {scene_idx + 1}.")
    print(f"  [Cảnh {scene_idx + 1}] {duration}s — Task ID: {task_id}")
    return task_id


async def _poll_task(client: httpx.AsyncClient, task_id: str, headers: dict, scene_idx: int) -> str:
    for attempt in range(MAX_POLL):
        await asyncio.sleep(POLL_INTERVAL)
        resp = await client.get(
            f"https://api.klingai.com/v1/videos/text2video/{task_id}",
            headers=headers,
        )
        resp.raise_for_status()
        task_data = resp.json().get("data", {})
        status = task_data.get("task_status")

        if status == "succeed":
            url = task_data.get("task_result", {}).get("videos", [{}])[0].get("url")
            if not url:
                raise ValueError(f"Kling không trả về URL clip cảnh {scene_idx + 1}.")
            return url
        elif status == "failed":
            raise ValueError(
                f"Kling lỗi cảnh {scene_idx + 1}: {task_data.get('task_status_msg', 'Unknown')}"
            )
        else:
            print(f"  [Cảnh {scene_idx + 1}] {status}... ({attempt + 1}/{MAX_POLL})")

    raise TimeoutError(f"Quá thời gian render cảnh {scene_idx + 1}.")


# ==========================================
# TTS (edge-tts)
# ==========================================

async def _generate_tts(text: str, output_path: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(output_path)


# ==========================================
# MOVIEPY HELPERS
# ==========================================

def _sync_mix_tts(clip_path: str, tts_path: str, output_path: str) -> None:
    """Overlay TTS tiếng Việt lên clip. Giữ audio gốc từ Kling ở 30% volume."""
    from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip

    video = VideoFileClip(clip_path)
    tts_full = AudioFileClip(tts_path)
    tts = tts_full.subclipped(0, min(tts_full.duration, video.duration))

    if video.audio:
        ambient = video.audio.multiply_volume(0.3)
        mixed = CompositeAudioClip([ambient, tts]).with_duration(video.duration)
    else:
        mixed = CompositeAudioClip([tts]).with_duration(video.duration)

    video.with_audio(mixed).write_videofile(
        output_path, codec="libx264", audio_codec="aac", logger=None
    )
    video.close()
    tts.close()
    tts_full.close()


def _sync_concat_clips(clip_paths: list[str], output_path: str) -> None:
    from moviepy import VideoFileClip, concatenate_videoclips

    clips = [VideoFileClip(p) for p in clip_paths]
    final = concatenate_videoclips(clips)
    final.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None)
    for c in clips:
        c.close()
    final.close()


async def _mix_tts_into_clip(clip_path: str, tts_path: str, output_path: str) -> None:
    await asyncio.to_thread(_sync_mix_tts, clip_path, tts_path, output_path)


async def _concat_clips(clip_paths: list[str], output_path: str) -> None:
    await asyncio.to_thread(_sync_concat_clips, clip_paths, output_path)


# ==========================================
# MAIN NODE
# ==========================================

async def video_compose_node(state: ContentProductionState) -> dict:
    print("\n[NODE: VIDEO COMPOSE] Khởi động Kling AI Studio...")

    clip_paths: list[str] = []
    voiced_paths: list[str] = []

    # Bọc TOÀN BỘ node (kể cả phần setup) trong try/except ngoài cùng.
    # Mục đích: đảm bảo mọi lỗi đều được bắt và trả về {"errors": [...]}
    # thay vì để exception thoát ra crash LangGraph và bỏ qua publisher.
    try:
        video_script = state.get("video_script")
        KLING_API_KEY = encode_jwt_token(setting.KLING_ACCESS_KEY, setting.KLING_SECRET_KEY)

        if not video_script:
            print("[VIDEO COMPOSE] Bỏ qua: Thiếu video_script → publisher sẽ đăng bài text.")
            return {"errors": ["[VIDEO COMPOSE] Bỏ qua: Thiếu video_script."]}
        if not KLING_API_KEY:
            print("[VIDEO COMPOSE] Bỏ qua: Thiếu KLING_API_KEY → publisher sẽ đăng bài text.")
            return {"errors": ["[VIDEO COMPOSE] LỖI: Thiếu KLING_API_KEY."]}

        scenes = _extract_scenes(video_script)
        for i, s in enumerate(scenes):
            print(f"[DEBUG] Scene {i+1} voiceover: '{s['voiceover'][:80]}'")
        total_duration = sum(int(s["duration"]) for s in scenes)
        print(
            f"[VIDEO COMPOSE] {len(scenes)} phân cảnh | "
            + " + ".join(f"{s['duration']}s" for s in scenes)
            + f" = {total_duration}s tổng."
        )

        headers = {
            "Authorization": f"Bearer {KLING_API_KEY}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            # 1. SUBMIT LÊN KLING
            print("[VIDEO COMPOSE] Đang submit các task lên Kling...")
            task_ids = []
            for i, scene in enumerate(scenes):
                print(f"  [Cảnh {i + 1}] Prompt: {scene['prompt'][:80]}...")
                task_id = await _submit_task(client, scene["prompt"], scene["duration"], headers, i)
                task_ids.append(task_id)
                if i < len(scenes) - 1:
                    await asyncio.sleep(2)

            # 2. POLLING
            print("[VIDEO COMPOSE] Đang chờ Kling render...")
            video_urls = []
            for i, task_id in enumerate(task_ids):
                url = await _poll_task(client, task_id, headers, i)
                video_urls.append(url)
                print(f"  [Cảnh {i + 1}] Render xong!")

            # 3. TẢI CLIP VỀ
            print("[VIDEO COMPOSE] Đang tải các clip về máy...")
            for i, url in enumerate(video_urls):
                clip_path = os.path.join(setting.VIDEO_OUTPUT_DIR, f"clip_{uuid.uuid4().hex[:6]}.mp4")
                resp = await client.get(url)
                resp.raise_for_status()
                with open(clip_path, "wb") as f:
                    f.write(resp.content)
                clip_paths.append(clip_path)
                print(f"  [Cảnh {i + 1}] Đã lưu: {clip_path}")

        # 4. GENERATE TTS + MIX VÀO TỪNG CLIP
        print("[VIDEO COMPOSE] Đang tạo voiceover...")
        for i, (clip_path, scene) in enumerate(zip(clip_paths, scenes)):
            voiceover = scene.get("voiceover", "").strip()
            if voiceover:
                tts_path = clip_path.replace(".mp4", "_tts.mp3")
                await _generate_tts(voiceover, tts_path)
                voiced_path = clip_path.replace(".mp4", "_voiced.mp4")
                await _mix_tts_into_clip(clip_path, tts_path, voiced_path)
                os.remove(tts_path)
                voiced_paths.append(voiced_path)
                print(f"  [Cảnh {i + 1}] Voiceover xong.")
            else:
                voiced_paths.append(clip_path)
                print(f"  [Cảnh {i + 1}] Không có voiceover, giữ clip câm.")

        # 5. CONCAT
        concat_path = os.path.join(setting.VIDEO_OUTPUT_DIR, f"concat_{uuid.uuid4().hex[:8]}.mp4")
        print(f"[VIDEO COMPOSE] Ghép {len(voiced_paths)} clip...")
        await _concat_clips(voiced_paths, concat_path)

        for p in voiced_paths:
            if p not in clip_paths:
                os.remove(p)
        for p in clip_paths:
            if os.path.exists(p):
                os.remove(p)

        print(f"[NODE: VIDEO COMPOSE] Hoàn tất! Video {total_duration}s tại: {concat_path}")
        return {"video_path": concat_path}

    except Exception as e:
        # Dọn dẹp file tạm nếu có
        for p in voiced_paths:
            if p not in clip_paths and os.path.exists(p):
                os.remove(p)
        for p in clip_paths:
            if os.path.exists(p):
                os.remove(p)

        error_msg = f"[VIDEO COMPOSE][ERROR] {str(e)}"
        print(f"{error_msg}")
        # Trả về errors nhưng KHÔNG raise → LangGraph tiếp tục chạy sang publisher_node
        # Publisher sẽ tự động đăng bài text (caption) vì video_path không được set
        print("[VIDEO COMPOSE] → Chuyển sang publisher để đăng bài text thay thế.")
        return {"errors": [error_msg]}

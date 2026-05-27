SCRAPER_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích nội dung cho hệ thống tạo video TikTok/Shorts.

Chủ đề video đang làm: "{topic}"

Bài viết cần phân tích:
Tiêu đề: {title}
URL: {url}
Nội dung:
\"\"\"
{content}
\"\"\"

Hãy phân tích và trả về JSON với đúng 4 trường sau:
{{
  "summary": "Tóm tắt nội dung chính của bài (5-6 câu, tiếng Việt)",
  "pain_point": "Nỗi đau / vấn đề cốt lõi mà bài viết này đề cập đến (1-2 câu, tiếng Việt)",
  "why_chosen": "Lý do bài viết này có giá trị cho chủ đề đang làm video (1-2 câu, tiếng Việt)"
}}

CHỈ trả về JSON, không giải thích, không markdown backtick."""


QUERRY_SEARCH_PROMPT = """"Bạn là chuyên gia viết search query cho Exa AI search engine.
Exa là neural search — hoạt động tốt nhất với câu mô tả đầy đủ, KHÔNG phải keyword ngắn.

Chủ đề cần nghiên cứu: "{topic}"

Hãy tạo 1 search query tiếng Anh tối ưu để tìm các bài viết chất lượng cao (blog, tutorial, research, case study).
Query nên:
- Là câu mô tả hoàn chỉnh (15-25 từ)
- Hướng đến bài viết chuyên sâu, được đánh giá cao
- Phù hợp với mục đích tạo nội dung TikTok/short video

CHỈ trả về query, không giải thích."""
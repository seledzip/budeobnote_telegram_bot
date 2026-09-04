"""
부업노트 자동 글감 생성 스크립트
- posts/ 폴더의 기존 글 제목을 읽어 겹치지 않는 새 주제를 Claude에게 정하게 함
- 사이트 템플릿에 맞는 HTML을 생성해서 drafts/ 폴더에 저장
- 텔레그램으로 미리보기 + [발행] 버튼 전송
"""

import os
import re
import json
import glob
import random
import string
import datetime
import requests
from anthropic import Anthropic

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SITE_BASE = "https://seledzip.github.io/Celedzip"
POSTS_DIR = "posts"
DRAFTS_DIR = "drafts"

client = Anthropic(api_key=ANTHROPIC_API_KEY)


def get_existing_titles():
    """posts/ 폴더 안의 모든 글에서 <h1> 제목을 추출"""
    titles = []
    for path in glob.glob(f"{POSTS_DIR}/*.html"):
        with open(path, encoding="utf-8") as f:
            content = f.read()
        m = re.search(r"<h1>(.*?)</h1>", content, re.DOTALL)
        if m:
            titles.append(m.group(1).strip())
    return titles


def get_random_link_target():
    """내부 링크로 걸 기존 글 하나를 무작위로 선택 (파일명, 제목)"""
    files = glob.glob(f"{POSTS_DIR}/*.html")
    if not files:
        return None, None
    path = random.choice(files)
    fname = os.path.basename(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"<h1>(.*?)</h1>", content, re.DOTALL)
    title = m.group(1).strip() if m else fname
    return fname, title


def slugify_english(text_hint: str) -> str:
    """Claude가 제안한 영문 slug를 안전하게 정리. 실패 시 랜덤 slug."""
    slug = re.sub(r"[^a-z0-9\-]", "", text_hint.lower().replace(" ", "-"))
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if len(slug) < 5:
        slug = "post-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return slug[:60]


def generate_post():
    existing_titles = get_existing_titles()
    link_fname, link_title = get_random_link_target()
    today = datetime.date.today().isoformat()

    system_prompt = """당신은 '부업노트'라는 한국어 재테크/부업 블로그의 필자입니다.
직장인 대상으로, 부업·재테크·절세·4대보험·계약 관련 실전 정보를 담백하고 정직한 톤으로 씁니다.
과장된 수익 주장이나 확인 안 된 법적 사실을 단정적으로 말하지 않고, 애매한 기준은 '정확한 기준은 OO에서 확인하세요' 식으로 안내합니다."""

    user_prompt = f"""아래는 이미 발행된 글 제목 목록입니다. 이 목록과 주제가 겹치지 않는 새로운 글 주제를 하나 정하고, 전체 글을 작성해주세요.

[기존 글 제목 목록]
{chr(10).join('- ' + t for t in existing_titles)}

[요구사항]
- 부업노트 사이트의 톤(직장인 대상 재테크/부업/절세 실전 정보)에 맞는 주제
- 위 목록과 절대 겹치지 않는 새로운 주제
- 아래 JSON 형식으로만 답하세요 (다른 텍스트 없이 JSON만):

{{
  "slug_hint": "영문 소문자와 하이픈으로 된 파일명용 slug (예: side-income-example)",
  "tag": "카테고리 (세금·절세 / 부업 추천 / 부업 입문 / 부업 준비물 중 하나)",
  "title": "글 제목 (브랜드명 없이, 30자 이내)",
  "meta_description": "메타 설명 (80~100자)",
  "read_minutes": 5,
  "h2_sections": [
    {{"heading": "소제목1", "body": "본문 내용 (2~4문장, 존댓말)"}},
    {{"heading": "소제목2", "body": "본문 내용"}},
    {{"heading": "소제목3", "body": "본문 내용"}}
  ],
  "callout": "확인이 필요한 사항이나 주의점 (한 문단, 없으면 빈 문자열)",
  "list_items": ["체크리스트 항목1", "항목2", "항목3"],
  "conclusion": "정리 문단 (2~3문장)"
}}

참고로 이 글 안에 자연스럽게 링크를 하나 걸 예정입니다 (파일명: {link_fname}, 제목: "{link_title}"). h2_sections 중 하나의 본문에서 이 글을 언급할 문장을 자연스럽게 포함해주세요 (예: '앞서 다룬 OOO 글에서는...' 형태). 실제 <a> 태그는 제가 나중에 삽입할 것이니, 본문 텍스트에는 그냥 자연스러운 문장만 써주세요."""

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```json|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(raw)

    slug = slugify_english(data["slug_hint"])

    # h2 섹션 HTML 조립
    sections_html = ""
    link_inserted = False
    for sec in data["h2_sections"]:
        body = sec["body"]
        if not link_inserted and link_fname and link_title in body:
            body = body.replace(link_title, f'<a href="{link_fname}">{link_title}</a>', 1)
            link_inserted = True
        sections_html += f"""
      <h2>{sec['heading']}</h2>
      <p>{body}</p>
"""
    if not link_inserted and link_fname:
        sections_html += f"""
      <p>관련해서 <a href="{link_fname}">{link_title}</a> 글도 참고해보시면 도움이 됩니다.</p>
"""

    callout_html = ""
    if data.get("callout"):
        callout_html = f'\n      <div class="callout">{data["callout"]}</div>\n'

    list_html = ""
    if data.get("list_items"):
        items = "\n".join(f"        <li>{item}</li>" for item in data["list_items"])
        list_html = f"""
      <ul>
{items}
      </ul>
"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{data['title']} | 부업노트</title>
<meta name="description" content="{data['meta_description']}">
<link rel="canonical" href="{SITE_BASE}/posts/{slug}.html">
<meta name="robots" content="index, follow">
<link rel="stylesheet" href="../css/style.css">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-6012798544021697"
     crossorigin="anonymous"></script>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "{data['title']}",
  "datePublished": "{today}",
  "author": {{ "@type": "Organization", "name": "부업노트" }}
}}
</script>
<!-- DRAFT_META: {json.dumps({
    'slug': slug,
    'tag': data['tag'],
    'title': data['title'],
    'meta_description': data['meta_description'],
    'read_minutes': data['read_minutes'],
    'date': today
}, ensure_ascii=False)} -->
</head>
<body>

<header class="site-header">
  <div class="wrap">
    <a href="../index.html" class="logo">부업노트<span class="dot">.</span></a>
    <nav class="nav">
      <a href="../index.html#posts">부업 정보</a>
      <a href="../index.html#calculator">수익 계산기</a>
      <a href="../about.html">소개</a>
      <a href="../disclosure.html">제휴 고지</a>
    </nav>
  </div>
</header>

<article class="article">
  <div class="wrap">
    <p class="article-tag">{data['tag']}</p>
    <h1>{data['title']}</h1>
    <p class="byline">{today.replace('-', '.')} · 부업노트 편집팀</p>

    <div class="article-body">
{sections_html}{callout_html}{list_html}
      <h2>정리</h2>
      <p>{data['conclusion']}</p>
    </div>
  </div>
</article>

<footer class="site-footer">
  <div class="wrap">
    <div class="cols">
      <div>
        <h4>콘텐츠</h4>
        <ul>
          <li><a href="../index.html#posts">부업 정보</a></li>
          <li><a href="../index.html#calculator">수익 계산기</a></li>
        </ul>
      </div>
      <div>
        <h4>사이트</h4>
        <ul>
          <li><a href="../about.html">소개</a></li>
          <li><a href="../disclosure.html">제휴 마케팅 고지</a></li>
          <li><a href="../privacy.html">개인정보처리방침</a></li>
        </ul>
      </div>
    </div>
    <p class="legal">본 사이트는 쿠팡파트너스 등 제휴 마케팅 프로그램에 참여하고 있으며, 이에 따라 일정액의 수수료를 제공받을 수 있습니다.</p>
  </div>
</footer>

</body>
</html>
"""

    os.makedirs(DRAFTS_DIR, exist_ok=True)
    draft_path = f"{DRAFTS_DIR}/{slug}.html"
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(html)

    return slug, data


def send_telegram_preview(slug, data):
    preview_url = f"{SITE_BASE}/drafts/{slug}.html"
    text = (
        f"📝 *새 초안이 생성됐습니다*\n\n"
        f"*제목*: {data['title']}\n"
        f"*카테고리*: {data['tag']}\n"
        f"*설명*: {data['meta_description']}\n\n"
        f"미리보기: {preview_url}\n\n"
        f"발행하시려면 아래 버튼을 눌러주세요."
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ 발행하기", "callback_data": f"publish:{slug}"},
            {"text": "❌ 삭제", "callback_data": f"discard:{slug}"},
        ]]
    }

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": keyboard,
    })
    resp.raise_for_status()


if __name__ == "__main__":
    slug, data = generate_post()
    send_telegram_preview(slug, data)
    print(f"완료: {slug}")

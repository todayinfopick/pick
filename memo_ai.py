# -*- coding: utf-8 -*-
"""특징메모 자동 작성: 구글 제미나이(무료 키)가 상품 캡처를 읽고 특징을 정리한다.

.env / 시트 '_설정'
  GEMINI_API_KEY=...            : aistudio.google.com에서 받은 키 (무료)
  GEMINI_MODEL=gemini-flash-lite-latest
  AUTO_MEMO=1                   : 0이면 끔
"""
import base64
import io
import json
import os
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
FALLBACK_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.8-flash"]
MAX_PARTS = 16      # 한 번에 보내는 이미지 조각 수
CHUNK_H = 1600      # 긴 상세페이지 캡처는 이 높이로 잘라서 보냄 (글씨가 읽히게)
MAX_W = 1000

PROMPT = """너는 쇼핑 상품 정보를 정리하는 도우미다. 아래 사진들은 한 상품의 쇼핑몰 화면 캡처다.
사진마다 앞에 '사진 N' 또는 '사진 N-조각' 표시가 붙어 있다.
{hint}
할 일
1. product_name: 캡처에 보이는 정확한 상품명 (브랜드 포함). 안 보이면 위에 준 상품명을 그대로.
2. memo: 이 상품의 실제 특징 3~6개를 쉼표로 구분한 한 줄.
   - 캡처에 보이는 사실만. 비슷한 다른 제품 정보나 추측은 넣지 마라.
   - 가격, 할인, 순위, 평점, 리뷰 수, 배송 정보는 빼라(자주 바뀜).
   - 효능·효과는 제조사가 쓴 표현 수준으로만.
   - 성분·기술 이름만 늘어놓지 말고, 그 덕분에 쓰는 사람이 느끼는 점을 함께 써라.
     예: "파우더인데 건조함·들뜸을 줄인 촉촉한 윤광 마무리, 히알루론산·시카 콤플렉스 함유"
   - 특징을 알 수 없으면 빈 문자열.
3. category: 이 상품이 어느 분류인지 {cats} 중 하나만. 화장품·피부·헤어·향수는 뷰티, 영양제·건강식품·
   다이어트·운동용품은 건강, 집안 살림·주방·청소·수납·욕실·생활용품은 생활, 먹고 마시는 것은 식품.
4. info_images: 상품 사진이 아니라 글씨 위주의 설명·상세페이지·표 캡처인 사진 번호 목록
   (게시물에 올리지 않을 사진). 상품이 크게 보이는 사진은 넣지 마라. 조각 번호가 아니라 사진 번호(N)로.

다른 말 없이 JSON만 출력:
{{"product_name": "...", "memo": "...", "category": "...", "info_images": [번호, ...]}}"""


def env(key, default=""):
    return (os.getenv(key) or default).strip().strip('"')


def enabled():
    return env("AUTO_MEMO", "1") != "0" and bool(env("GEMINI_API_KEY"))


def _jpeg(im, quality=85):
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def _pieces(images):
    """[(표시, base64 jpeg)]. 넓은 사진은 줄이고, 긴 캡처는 위에서부터 잘라 글씨가 읽히게."""
    out = []
    for n, im in enumerate(images, start=1):
        im = im.convert("RGB")
        if im.width > MAX_W:
            im = im.resize((MAX_W, round(im.height * MAX_W / im.width)))
        if im.height <= CHUNK_H * 1.3:
            out.append((f"사진 {n}", _jpeg(im)))
            continue
        for k, top in enumerate(range(0, im.height, CHUNK_H), start=1):
            out.append((f"사진 {n}-{k}", _jpeg(im.crop((0, top, im.width, min(top + CHUNK_H, im.height))))))
    if len(out) > MAX_PARTS:  # 너무 많으면 사진마다 앞부분 위주로 남김
        out = out[:MAX_PARTS]
    return out


def _call(model, body, timeout=120, api_key=None):
    """API key is provided per request; never overwrite the free key in the environment."""
    return requests.post(API.format(model=model), params={"key": api_key or env("GEMINI_API_KEY")},
                         json=body, timeout=timeout)


def _paid_fallback(models, body, timeout):
    """Only called after free-tier quota exhaustion; paid usage is explicitly opt-in via secret."""
    paid_key = env("GEMINI_PAID_API_KEY")
    if not paid_key or paid_key == env("GEMINI_API_KEY"):
        return None
    # Keep the same prompt, image parts, model preference and output format.
    # Do not retry paid 429 repeatedly (prepaid balance or paid quota may be exhausted).
    for model in models:
        response = _call(model, body, timeout, api_key=paid_key)
        if response.ok:
            print("  ↪ 무료 Gemini 한도 초과 → 선불 유료 키로 작성 완료", flush=True)
            return response
        if response.status_code not in (404, 429):
            raise RuntimeError(f"선불 Gemini 요청 실패 ({response.status_code}): {response.text[:250]}")
        if response.status_code == 429:
            raise RuntimeError("선불 Gemini도 사용량/잔액 한도(429)에 도달했습니다. 추가 과금 재시도 없이 중단합니다.")
    raise RuntimeError("선불 Gemini에서 사용 가능한 모델을 찾지 못했습니다.")


def generate(parts, json_out=True, temperature=0.2, search=False, timeout=120):
    """제미나이에 요청해 답 글자를 돌려준다 (모델 이름이 없어졌으면 다음 이름으로).
    search=True면 구글 검색으로 최신 정보를 찾아 보고 답한다 (이때는 JSON 형식 지정을 못 씀)."""
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature}}
    if search:
        body["tools"] = [{"google_search": {}}]
    elif json_out:
        body["generationConfig"]["responseMimeType"] = "application/json"
    models = [env("GEMINI_MODEL") or FALLBACK_MODELS[0]] + FALLBACK_MODELS
    r = None
    for model in dict.fromkeys(models):
        for wait in (0, 5, 20):  # 서버 일시 장애만 재시도; 429는 유료 대체 경로로 빠르게 전환
            if wait:
                time.sleep(wait)
            r = _call(model, body, timeout)
            if r.status_code == 429:
                break  # 일일/분당 한도는 재시도 폭주 없이 다른 모델·유료 키로 넘김
            if r.status_code not in (500, 502, 503, 504):
                break
        if r.status_code not in (404, 429, 500, 502, 503, 504):
            break
    if r.status_code == 429:
        paid_response = _paid_fallback(list(dict.fromkeys(models)), body, timeout)
        if paid_response is not None:
            r = paid_response
    if search and r.status_code == 429:  # 무료 등급은 Gemini 3 이후 모델의 구글 검색 한도가 0 → 검색 없이 다시
        print("  ↪ 제미나이 구글 검색 한도가 없어 검색 없이 씁니다", flush=True)
        return generate(parts, json_out=False, temperature=temperature, search=False)
    if r.status_code == 429:
        try:  # 구글이 알려 준 걸린 한도 이름 (예: ...PerMinute..., ...PerDay...)
            why = ", ".join(v.get("quotaId", "") for d in r.json()["error"].get("details", [])
                            for v in d.get("violations", []) if v.get("quotaId"))
        except Exception:
            why = ""
        raise RuntimeError("제미나이 무료 사용량 한도에 걸렸습니다 (분당 또는 하루 한도). 유료 키가 없거나 동일한 키입니다."
                           + (f" [{why[:200]}]" if why else ""))
    if r.status_code >= 400:
        raise RuntimeError(f"제미나이 요청 실패 ({r.status_code}): {r.text[:300]}")
    try:
        cand = r.json()["candidates"][0]
        return "".join(p.get("text", "") for p in cand["content"]["parts"])
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(f"제미나이 답을 읽지 못했습니다: {e}")


UNRELATED_PROMPT = """쇼핑 홍보 글에 쓸 사진을 고르고 있다. 상품명: {name}
아래 '사진 1'부터 '사진 {n}'까지 중에서 이 상품과 관계없는 사진의 번호만 골라라.
관계없음: 다른 상품 사진, 함께 사면 좋은 상품·추천 상품, 브랜드·쇼핑몰 홍보 배너, 배송·교환·반품·고객센터 안내,
쿠폰·이벤트·리뷰 이벤트, 판매자 공지, 빈 화면이나 장식만 있는 사진.
관계있음(빼지 말 것): 이 상품 사진, 사용하는 모습, 상품 특징·성분·사이즈·구성 설명.
헷갈리면 관계있는 것으로 둬라.
JSON으로만 답하라: {{"drop": [번호, ...]}}"""


def unrelated_photos(name, images):
    """상품과 관계없는 사진 번호(0부터)를 제미나이가 고른다. 한 번에 모든 사진을 보냄. 실패하면 RuntimeError."""
    parts = [{"text": UNRELATED_PROMPT.format(name=name, n=len(images))}]
    for n, im in enumerate(images, start=1):
        im = im.convert("RGB")
        im.thumbnail((320, 320))  # 작게: 사진이 많으면 제미나이 답이 늦어 시간 초과가 남
        parts += [{"text": f"사진 {n}"}, {"inline_data": {"mime_type": "image/jpeg", "data": _jpeg(im, 70)}}]
    text = generate(parts, timeout=60)
    try:
        data = json.loads(text[text.find("{"):text.rfind("}") + 1])
    except ValueError as e:
        raise RuntimeError(f"제미나이 답을 읽지 못했습니다: {e}")
    out = set()
    for v in data.get("drop") or []:
        try:
            i = int(v) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(images):
            out.add(i)
    return out


PAGE_TEXT_MAX = 20000  # 상품 페이지 글자는 앞에서 이만큼만 보냄 (전체는 사진 폴더 페이지글.txt에 저장)


def write_memo(images, name="", link="", cats=("뷰티", "건강", "생활", "식품"), page_text=""):
    """캡처 사진(PIL 이미지 목록)과 상품 페이지 글자(확장프로그램)로 상품명·메모·분류·설명캡처 번호를 얻는다.
    반환 {'name', 'memo', 'category', 'info': [0부터 시작하는 사진 번호]}. 실패하면 RuntimeError."""
    if not env("GEMINI_API_KEY"):
        raise RuntimeError("제미나이 키가 없습니다. 설정 → 특징메모에서 넣어 주세요.")
    page_text = (page_text or "").strip()
    if not images and not page_text:
        raise RuntimeError("읽을 캡처 사진이 없습니다.")
    hint = f"참고 상품명: {name}\n" if name else ""
    if page_text:
        hint += "맨 뒤의 '페이지 글'은 상품 페이지에서 그대로 가져온 글자다. 사진보다 정확하니 먼저 참고하라.\n"
    parts = [{"text": PROMPT.format(hint=hint, cats=", ".join(cats))}]
    for label, data in _pieces(images):
        parts += [{"text": label}, {"inline_data": {"mime_type": "image/jpeg", "data": data}}]
    if page_text:
        parts.append({"text": "페이지 글:\n" + page_text[:PAGE_TEXT_MAX]})
    text = generate(parts)
    try:
        data = json.loads(text[text.find("{"):text.rfind("}") + 1])
    except ValueError as e:
        raise RuntimeError(f"제미나이 답을 읽지 못했습니다: {e}")
    info = []
    for v in data.get("info_images") or []:
        try:
            i = int(str(v).split("-")[0]) - 1
        except ValueError:
            continue
        if 0 <= i < len(images) and i not in info:
            info.append(i)
    if len(info) >= len(images):  # 전부 설명 캡처라고 하면 게시할 사진이 없으니 무시
        info = []
    memo = " ".join(str(data.get("memo", "")).split())
    if "정보 부족" in memo or len(memo) < 4:
        memo = ""
    cat = str(data.get("category", "")).strip()
    return {"name": " ".join(str(data.get("product_name", "")).split()) or name,
            "memo": memo, "category": cat if cat in cats else "", "info": sorted(info)}

# -*- coding: utf-8 -*-
"""특징메모 자동 작성: 구글 제미나이(무료 키)가 상품 캡처를 읽고 특징을 정리한다.

.env / 시트 '_설정'
  GEMINI_API_KEY=...            : aistudio.google.com에서 받은 키 (무료)
  GEMINI_MODEL=gemini-flash-latest
  AUTO_MEMO=1                   : 0이면 끔
"""
import base64
import io
import json
import os

import requests

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-2.5-flash"]
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
3. info_images: 상품 사진이 아니라 글씨 위주의 설명·상세페이지·표 캡처인 사진 번호 목록
   (게시물에 올리지 않을 사진). 상품이 크게 보이는 사진은 넣지 마라. 조각 번호가 아니라 사진 번호(N)로.

다른 말 없이 JSON만 출력:
{{"product_name": "...", "memo": "...", "info_images": [번호, ...]}}"""


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


def _call(model, body):
    return requests.post(API.format(model=model), params={"key": env("GEMINI_API_KEY")},
                         json=body, timeout=120)


def write_memo(images, name="", link=""):
    """캡처 사진(PIL 이미지 목록)으로 상품명·메모·설명캡처 번호를 얻는다.
    반환 {'name': str, 'memo': str, 'info': [0부터 시작하는 사진 번호]}. 실패하면 RuntimeError."""
    if not env("GEMINI_API_KEY"):
        raise RuntimeError("제미나이 키가 없습니다. 설정 → 특징메모에서 넣어 주세요.")
    if not images:
        raise RuntimeError("읽을 캡처 사진이 없습니다.")
    hint = f"참고 상품명: {name}\n" if name else ""
    parts = [{"text": PROMPT.format(hint=hint)}]
    for label, data in _pieces(images):
        parts += [{"text": label}, {"inline_data": {"mime_type": "image/jpeg", "data": data}}]
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}

    models = [env("GEMINI_MODEL") or FALLBACK_MODELS[0]] + FALLBACK_MODELS
    r = None
    for model in dict.fromkeys(models):
        r = _call(model, body)
        if r.status_code != 404:  # 모델 이름이 없어졌으면 다음 이름으로
            break
    if r.status_code == 429:
        raise RuntimeError("제미나이 무료 사용량을 다 썼습니다. 내일 다시 시도해 주세요.")
    if r.status_code >= 400:
        raise RuntimeError(f"제미나이 요청 실패 ({r.status_code}): {r.text[:300]}")
    try:
        cand = r.json()["candidates"][0]
        text = "".join(p.get("text", "") for p in cand["content"]["parts"])
        data = json.loads(text[text.find("{"):text.rfind("}") + 1])
    except (KeyError, IndexError, ValueError) as e:
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
    return {"name": " ".join(str(data.get("product_name", "")).split()) or name,
            "memo": memo, "info": sorted(info)}

# -*- coding: utf-8 -*-
"""블로그 글감 키워드: 지금 뜨는 검색어 + 네이버 월 검색량 + 블로그 글 수(경쟁도).

- 지금 뜨는 검색어: 구글 트렌드 한국 인기 검색어 RSS (키 필요 없음)
- 월 검색량·연관 키워드: 네이버 검색광고 API (무료, 키 3개: NAVER_AD_CUSTOMER_ID, NAVER_AD_ACCESS_KEY, NAVER_AD_SECRET_KEY)
- 블로그 글 수: 네이버 검색 API (무료, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET)
키가 없으면 그 부분만 빠지고, 아무것도 없으면 빈 결과(글쓰기는 예전처럼 동작).

  python blog_keywords.py --site site   → site/keywords.json (새벽 Claude 글쓰기와 제미나이 글감 고르기가 읽음)
"""
import argparse
import base64
import datetime
import hashlib
import hmac
import json
import pathlib
import re
import time
import xml.etree.ElementTree as ET

import requests

from main import env, log

TRENDS_RSS = "https://trends.google.com/trending/rss?geo=KR"
MIN_VOLUME = 1000  # 이보다 적게 찾는 키워드는 글감 후보에서 뺌


def _norm(k):
    return re.sub(r"\s+", "", str(k or "")).lower()


def _num(v):
    """검색광고 API 숫자: 정수 또는 '< 10'."""
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"\d+", str(v or ""))
    return int(m.group()) if m and "<" not in str(v) else 5


def has_ad():
    return all(env(k) for k in ("NAVER_AD_CUSTOMER_ID", "NAVER_AD_ACCESS_KEY", "NAVER_AD_SECRET_KEY"))


def has_search():
    return bool(env("NAVER_CLIENT_ID") and env("NAVER_CLIENT_SECRET"))


def _ad_get(path, params):
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(env("NAVER_AD_SECRET_KEY").encode(), f"{ts}.GET.{path}".encode(),
                                    hashlib.sha256).digest()).decode()
    r = requests.get("https://api.searchad.naver.com" + path, params=params, timeout=30,
                     headers={"X-Timestamp": ts, "X-API-KEY": env("NAVER_AD_ACCESS_KEY"),
                              "X-Customer": str(env("NAVER_AD_CUSTOMER_ID")), "X-Signature": sig})
    r.raise_for_status()
    return r.json()


def lookup(words):
    """키워드들 → ({정규화한 키워드: 정보}, [연관 키워드 정보]). 정보: keyword, volume(PC+모바일 월), comp(낮음·중간·높음)."""
    found, related = {}, []
    if not has_ad():
        return found, related
    words = [w for w in dict.fromkeys(_norm(w) for w in words) if w][:50]
    for i in range(0, len(words), 5):  # 한 번에 5개까지
        try:
            data = _ad_get("/keywordstool", {"hintKeywords": ",".join(words[i:i + 5]), "showDetail": "1"})
        except Exception as e:
            log(f"    (검색량을 받지 못했습니다: {e})")
            continue
        for k in data.get("keywordList", []):
            info = {"keyword": k.get("relKeyword", ""),
                    "volume": _num(k.get("monthlyPcQcCnt")) + _num(k.get("monthlyMobileQcCnt")),
                    "comp": k.get("compIdx", "")}
            if _norm(info["keyword"]) in words[i:i + 5]:
                found[_norm(info["keyword"])] = info
            else:
                related.append(info)
        time.sleep(0.3)
    return found, related


def blog_docs(keyword):
    """네이버 블로그에 이 키워드로 나오는 글 수 (모르면 None)."""
    if not has_search():
        return None
    try:
        r = requests.get("https://openapi.naver.com/v1/search/blog.json", params={"query": keyword, "display": 1},
                         headers={"X-Naver-Client-Id": env("NAVER_CLIENT_ID"),
                                  "X-Naver-Client-Secret": env("NAVER_CLIENT_SECRET")}, timeout=20)
        r.raise_for_status()
        return int(r.json().get("total", 0))
    except Exception as e:
        log(f"    (블로그 글 수를 받지 못했습니다: {e})")
        return None


def grade(volume, docs):
    """경쟁도: 블로그 글 수 ÷ 월 검색량. 낮을수록 내 글이 노출되기 쉬움."""
    if not volume or docs is None:
        return ""
    ratio = docs / max(volume, 1)
    return "낮음" if ratio < 2 else "보통" if ratio < 10 else "높음"


def enrich(info):
    """검색량 정보에 블로그 글 수와 경쟁도를 붙인다."""
    info["docs"] = blog_docs(info["keyword"])
    info["level"] = grade(info.get("volume"), info["docs"])
    return info


def trending(limit=20):
    """구글 트렌드 한국 인기 검색어 → [{keyword, traffic, news}]."""
    try:
        r = requests.get(TRENDS_RSS, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        log(f"    (인기 검색어를 받지 못했습니다: {e})")
        return []
    ns = {"ht": "https://trends.google.com/trending/rss"}
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        news = [n.findtext("ht:news_item_title", default="", namespaces=ns).strip()
                for n in it.findall("ht:news_item", ns)][:2]
        out.append({"keyword": title, "traffic": it.findtext("ht:approx_traffic", default="", namespaces=ns),
                    "news": [x for x in news if x]})
        if len(out) >= limit:
            break
    return out


def build(cfg):
    """keywords.json 내용: 지금 뜨는 검색어(검색량·경쟁도 붙임) + 블로그마다 검색량 많은 연관 키워드 후보."""
    rep = {"updated": datetime.datetime.now().isoformat(timespec="minutes"), "trending": [], "blogs": {},
           "sources": {"trends": True, "volume": has_ad(), "docs": has_search()}}
    trend = trending()
    if trend:
        vols, _ = lookup([t["keyword"] for t in trend])
        for t in trend:
            v = vols.get(_norm(t["keyword"]))
            if v:
                t.update(volume=v["volume"], comp=v["comp"])
        rep["trending"] = trend
    if not has_ad():
        return rep
    for blog in cfg["blogs"]:
        seeds = blog.get("seed_keywords") or []
        if not seeds:
            continue
        found, rel = lookup(seeds)
        cands = {}
        for info in list(found.values()) + rel:
            if info["volume"] >= MIN_VOLUME and _norm(info["keyword"]) not in cands:
                cands[_norm(info["keyword"])] = info
        top = sorted(cands.values(), key=lambda x: -x["volume"])[:40]
        for info in top[:25]:  # 블로그 글 수는 검색량 많은 25개만 확인 (API 하루 한도 넉넉)
            enrich(info)
        top.sort(key=lambda x: ({"낮음": 0, "보통": 1, "": 2, "높음": 3}[x.get("level", "")], -x["volume"]))
        rep["blogs"][blog["key"]] = top[:25]
        log(f"  {blog['name']}: 키워드 후보 {len(top[:25])}개")
    rep["products"] = product_ideas(cfg.get("shop_seed_keywords") or [])
    log(f"  상품 추천 키워드 {len(rep['products'])}개")
    return rep


SHOPPY = re.compile(r"추천|비교|순위|가격|후기|브랜드|세트|용품|선물|기|기기|크림|세럼|패딩|이불|매트|청소기|가습기|영양제|텀블러|신발|가방")


def product_ideas(seeds, limit=20):
    """쇼핑커넥트·쿠팡파트너스로 올리면 좋은 상품 키워드: 상품 분야(blog_config shop_seed_keywords)의 연관 키워드 → 검색량 많고 경쟁 낮은 순."""
    if not has_ad() or not seeds:
        return []
    found, rel = lookup(seeds)
    pool = {}
    for info in list(found.values()) + rel:
        if info["volume"] >= MIN_VOLUME and (SHOPPY.search(info["keyword"]) or _norm(info["keyword"]) in found):
            pool.setdefault(_norm(info["keyword"]), info)
    top = sorted(pool.values(), key=lambda x: -x["volume"])[:30]
    for info in top:
        enrich(info)
    top.sort(key=lambda x: ({"낮음": 0, "보통": 1, "": 2, "높음": 3}[x.get("level", "")], -x["volume"]))
    return top[:limit]


def load(site):
    try:
        return json.loads((pathlib.Path(site) / "keywords.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def prompt_block(rep, blog_key):
    """글감 고르기 프롬프트에 넣을 키워드 안내 (데이터가 없으면 빈 글자)."""
    lines = []
    if rep.get("trending"):
        lines.append("지금 한국에서 많이 찾는 검색어(구글 트렌드, 블로그 주제와 맞는 것만 골라 써라):")
        for t in rep["trending"][:15]:
            v = f", 네이버 월 {t['volume']:,}회" if t.get("volume") else ""
            news = f" — {t['news'][0]}" if t.get("news") else ""
            lines.append(f"- {t['keyword']} (검색 {t.get('traffic') or '?'}{v}){news}")
    cands = rep.get("blogs", {}).get(blog_key) or []
    if cands:
        lines.append("이 블로그 주제에서 네이버 월 검색량이 많은 키워드 (경쟁 = 블로그 글 수÷검색량, 낮을수록 노출되기 쉬움):")
        for c in cands[:20]:
            lv = f", 경쟁 {c['level']}" if c.get("level") else ""
            lines.append(f"- {c['keyword']} (월 {c['volume']:,}회{lv})")
    if not lines:
        return ""
    return ("\n".join(lines) + "\n위 검색어·키워드 가운데 지금 시기와 블로그 주제에 맞고 검색량이 많은 것을 우선 글감으로 삼아라. "
            "경쟁이 낮은 키워드를 먼저 고르고, 글감마다 제목에 넣을 핵심 키워드(keyword) 하나를 정해라.\n")


def describe(keyword):
    """키워드 하나 → {keyword, volume, docs, level} (키가 없거나 못 찾으면 keyword만)."""
    keyword = (keyword or "").strip()
    if not keyword:
        return {}
    found, _ = lookup([keyword])
    info = found.get(_norm(keyword)) or {"keyword": keyword}
    info["keyword"] = keyword
    if has_search():
        enrich(info)
    return {k: v for k, v in info.items() if k in ("keyword", "volume", "docs", "level")}


def product_keywords(name, limit=8):
    """상품명 → 검색량 많은 연관 키워드 후보 (상품 글 제목용)."""
    if not has_ad():
        return []
    words = [w for w in re.sub(r"[\[\]()/,+]", " ", name).split() if len(w) >= 2 and not re.search(r"\d", w)]
    hints = [" ".join(words[i:i + 2]) for i in range(0, min(len(words), 6), 2)] or words[:3]
    _, rel = lookup(hints)
    rel = [r for r in rel if r["volume"] >= 300]
    return sorted(rel, key=lambda x: -x["volume"])[:limit]


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="site")
    a = ap.parse_args()
    cfg = json.loads((pathlib.Path(__file__).resolve().parent / "blog_config.json").read_text(encoding="utf-8"))
    log("키워드 모으기 (인기 검색어·검색량·경쟁도)")
    rep = build(cfg)
    out = pathlib.Path(a.site) / "keywords.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"✓ {out} (인기 검색어 {len(rep['trending'])}개, 검색량 {'O' if rep['sources']['volume'] else '키 없음'}, "
        f"글 수 {'O' if rep['sources']['docs'] else '키 없음'})")


if __name__ == "__main__":
    main_cli()

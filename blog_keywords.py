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
import os
import random
import urllib.parse
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
    if not info["level"]:  # 검색 API를 못 쓰면(네이버가 새 신청을 막음) 검색광고의 경쟁 정도로 대신함
        info["level"] = {"낮음": "낮음", "중간": "보통", "높음": "높음"}.get(info.get("comp", ""), "")
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


# Broad discovery is independent of the blog categories. Categories are used only
# after discovery to route candidates. No AI calls or new credentials required.
DISCOVERY_TOPICS = [
    "인공지능", "디지털", "스마트폰", "경제", "금융", "물가", "정부 정책",
    "지원금", "절약", "쇼핑", "할인", "신제품", "생활", "건강", "식품",
    "여행", "축제", "취미", "자동차", "가전", "뷰티", "패션", "육아",
    "반려동물", "스포츠", "문화", "부동산", "교육", "환경", "날씨",
]
PRODUCT_DISCOVERY = [
    "생활가전", "주방용품", "디지털기기", "컴퓨터주변기기", "스마트폰액세서리",
    "생활용품", "수납용품", "청소용품", "욕실용품", "주방가전", "식품",
    "간편식", "뷰티", "스킨케어", "패션잡화", "운동용품", "여행용품",
    "캠핑용품", "반려동물용품", "육아용품", "자동차용품", "건강용품",
]


def news_headlines(limit=35):
    """Google News KR RSS: headlines are issue candidates, NOT search volume."""
    out, seen = [], set()
    queries = ["경제 OR 생활", "IT OR AI", "쇼핑 OR 신제품", "여행 OR 문화"]
    for query in queries:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
            "q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                key = _norm(title)
                if title and key not in seen:
                    seen.add(key)
                    out.append({"title": title, "source": "Google News RSS",
                                "published": item.findtext("pubDate") or ""})
                if len(out) >= limit:
                    return out
        except Exception as e:
            log(f"    (뉴스 RSS 수집 실패: {e})")
    return out


def _history(site):
    try:
        return json.loads((pathlib.Path(site) / "keyword_history.json").read_text(encoding="utf-8"))
    except Exception:
        return {"recommended": {}, "products": {}}


def _rotate(words, count, day=None):
    """Rotate broad seeds each day; keep request volume bounded."""
    if not words:
        return []
    day = day or datetime.date.today()
    shift = (day.toordinal() * count) % len(words)
    return (words[shift:] + words[:shift])[:count]


def _rank_candidates(pool, seen, limit, min_volume=MIN_VOLUME):
    today = datetime.date.today()
    results = []
    for item in pool.values():
        if item.get("volume", 0) < min_volume:
            continue
        previous = seen.get(_norm(item["keyword"]))
        age = 999
        if previous:
            try:
                age = (today - datetime.date.fromisoformat(previous)).days
            except (TypeError, ValueError):
                pass
        item = dict(item)
        item["novelty"] = "신규" if age >= 30 else "최근 추천"
        # No made-up search metrics; recency only affects recommendation order.
        results.append((age < 7, age < 30, -item["volume"], item))
    results.sort(key=lambda row: row[:3])
    return [r[3] for r in results[:limit]]


def build(cfg, site="site"):
    """Discover broadly first, then route to blog themes. Preserve old JSON fields."""
    rep = {"updated": datetime.datetime.now().isoformat(timespec="minutes"),
           "trending": [], "news": [], "blogs": {}, "products": [],
           "sources": {"trends": True, "volume": has_ad(), "docs": has_search(), "news": True}}
    history = _history(site)
    trend = trending(limit=40)
    rep["news"] = news_headlines()
    if trend:
        vols, _ = lookup([t["keyword"] for t in trend])
        for t in trend:
            v = vols.get(_norm(t["keyword"]))
            if v:
                t.update(volume=v["volume"], comp=v["comp"])
        rep["trending"] = trend
    if not has_ad():
        return rep

    # Query multiple unrelated sectors, not only fixed blog seeds.
    broad = _rotate(DISCOVERY_TOPICS, 12)
    blog_seeds = [w for b in cfg.get("blogs", []) for w in (b.get("seed_keywords") or [])]
    found, related = lookup(broad + _rotate(blog_seeds, 8))
    pool = {}
    for info in list(found.values()) + related:
        if info.get("volume", 0) >= MIN_VOLUME:
            pool.setdefault(_norm(info["keyword"]), info)
    for t in trend:
        key = _norm(t["keyword"])
        if t.get("volume", 0) >= MIN_VOLUME and key not in pool:
            pool[key] = {"keyword": t["keyword"], "volume": t["volume"],
                         "comp": t.get("comp", ""), "source": "trends"}

    # All blog lists draw from broad pool. Themes influence ranking, not eligibility.
    for blog in cfg.get("blogs", []):
        seeds = blog.get("seed_keywords") or []
        hints = [_norm(x) for x in seeds]
        recent = history.get("recommended", {}).get(blog["key"], {})
        candidates = _rank_candidates(pool, recent, 75)
        # Broad-first with light theme preference, never hard-filter other sectors.
        candidates.sort(key=lambda x: (x.get("novelty") != "신규",
            not any(h in _norm(x["keyword"]) for h in hints), -x["volume"]))
        chosen = candidates[:25]
        for item in chosen[:15]:
            enrich(item)
        rep["blogs"][blog["key"]] = chosen
        log(f"  {blog['name']}: 전 분야 키워드 후보 {len(chosen)}개")

    product_seeds = _rotate(PRODUCT_DISCOVERY, 12) + _rotate(cfg.get("shop_seed_keywords") or [], 4)
    rep["products"] = product_ideas(product_seeds, limit=30,
                                     recent=history.get("products", {}))
    log(f"  상품 추천 키워드 {len(rep['products'])}개")
    return rep


def save_history(site, rep, keep_days=60):
    """Keep 60-day recommendation history with volume and frequency; read old date-only data."""
    path = pathlib.Path(site) / "keyword_history.json"
    data = _history(site)
    today = datetime.date.today()
    stamp = today.isoformat()
    cutoff = today - datetime.timedelta(days=keep_days)
    for blog, items in rep.get("blogs", {}).items():
        bucket = data.setdefault("recommended", {}).setdefault(blog, {})
        for item in items:
            bucket[_norm(item["keyword"])] = stamp
    bucket = data.setdefault("products", {})
    for item in rep.get("products", []):
        key = _norm(item["keyword"])
        old = bucket.get(key)
        if isinstance(old, dict):
            count = int(old.get("count", 0))
            first = old.get("first_seen", stamp)
        else:
            count = 1 if old else 0
            first = old or stamp
        bucket[key] = {"last_seen": stamp, "first_seen": first,
                       "count": count + 1, "volume": int(item.get("volume") or 0)}
    for group in list(data.get("recommended", {}).values()) + [bucket]:
        for key, entry in list(group.items()):
            date = entry.get("last_seen") if isinstance(entry, dict) else entry
            try:
                if datetime.date.fromisoformat(date) < cutoff:
                    del group[key]
            except (ValueError, TypeError):
                del group[key]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


SHOPPY = re.compile(r"추천|비교|순위|가격|후기|브랜드|세트|용품|선물|기|기기|크림|세럼|패딩|이불|매트|청소기|가습기|영양제|텀블러|신발|가방")
NOT_PRODUCT = re.compile(r"계산기|날씨|뜻|로그인|사이트|홈페이지|고객센터|번호|시간|일정|조회|신청|다운로드|게임|영화|드라마|주가|환율")  # 상품이 아닌 검색어


def product_ideas(seeds, limit=20, recent=None):
    """Prioritize new products; allow demonstrably strong repeats with an explicit reason.

    Strength uses observed Naver monthly volume (not invented sales figures).
    A repeat needs either >=30% volume growth against the prior observation
    or volume >= 20,000 and top-10% among this run's candidate pool.
    At most 20% of recommendations can be repeats; recent repeats cannot
    dominate the list. Existing date-only history is supported.
    """
    if not has_ad() or not seeds:
        return []
    found, rel = lookup(seeds)
    pool = {}
    for info in list(found.values()) + rel:
        if info["volume"] >= MIN_VOLUME and not NOT_PRODUCT.search(info["keyword"]) \
                and (SHOPPY.search(info["keyword"]) or _norm(info["keyword"]) in found):
            key = _norm(info["keyword"])
            if key not in pool or info["volume"] > pool[key]["volume"]:
                pool[key] = info
    if not pool:
        return []
    history = recent or {}
    today = datetime.date.today()
    volumes = sorted((x["volume"] for x in pool.values()), reverse=True)
    top_threshold = volumes[max(0, (len(volumes) - 1) // 10)]
    fresh, repeats = [], []
    for item in pool.values():
        entry = history.get(_norm(item["keyword"]))
        if not entry:
            fresh.append({**item, "novelty": "신규 발견", "recommend_reason": "신규 발견"})
            continue
        date = entry.get("last_seen", "") if isinstance(entry, dict) else entry
        old_volume = int(entry.get("volume") or 0) if isinstance(entry, dict) else 0
        count = int(entry.get("count") or 1) if isinstance(entry, dict) else 1
        try:
            age = (today - datetime.date.fromisoformat(date)).days
        except (ValueError, TypeError):
            age = 999
        growth = old_volume > 0 and item["volume"] >= old_volume * 1.30
        evergreen = item["volume"] >= max(20000, top_threshold)
        # Without prior volume evidence, don't label a repeat 'surging'.
        if growth:
            reason = "검색량 상승(이전 대비 30% 이상)"
        elif evergreen and (age >= 1 or count <= 1):
            reason = "꾸준한 인기(상위 검색량)"
        else:
            continue
        # Same-day repeats only for proven growth; prevent repeated manual refresh flooding.
        if age == 0 and not growth:
            continue
        repeats.append({**item, "novelty": "재추천", "recommend_reason": reason,
                        "previous_volume": old_volume or None, "recommend_count": count})
    fresh.sort(key=lambda x: -x["volume"])
    repeats.sort(key=lambda x: (x["recommend_reason"].startswith("꾸준한"), -x["volume"]))
    repeat_cap = max(1, limit // 5)
    chosen = fresh[:limit]
    if len(chosen) < limit:
        chosen.extend(repeats[:min(repeat_cap, limit - len(chosen))])
    # If there are plenty of fresh options, reserve up to 20% for truly strong repeats.
    elif repeats:
        selected_repeats = repeats[:repeat_cap]
        chosen = fresh[:limit - len(selected_repeats)] + selected_repeats
    for info in chosen[:20]:
        enrich(info)
    return chosen


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
        lines.append("이 블로그 주제에서 네이버 월 검색량이 많은 키워드 (경쟁 = 블로그 글 수÷검색량, 없으면 검색광고 경쟁 정도. 낮을수록 노출되기 쉬움):")
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
    rep = build(cfg, a.site)
    out = pathlib.Path(a.site) / "keywords.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    save_history(a.site, rep)
    log(f"✓ {out} (인기 검색어 {len(rep['trending'])}개, 검색량 {'O' if rep['sources']['volume'] else '키 없음'}, "
        f"글 수 {'O' if rep['sources']['docs'] else '키 없음'})")


if __name__ == "__main__":
    main_cli()

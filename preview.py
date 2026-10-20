# -*- coding: utf-8 -*-
"""다음에 올라갈 상품의 사진 미리보기 페이지 (docs/preview/).

서버가 게시할 때마다 계정별로 다음 상품 몇 개의 사진을 작게 줄여 올리고, 각 사진이 게시에 쓰일지 표시한다.
휴대폰·PC에서 열어 사진을 누르면 '뺌 ↔ 사용'이 바뀌고, 저장하면 저장소의 photo_exclude.json에 적혀
다음 게시부터 그대로 따른다. 안 열어 보면 AI 판정대로 자동 게시된다.

  python preview.py   # posted.json·사진 폴더를 보고 페이지를 다시 만든다
"""
import datetime
import html
import json
import pathlib

import image_tools as it

BASE = pathlib.Path(__file__).resolve().parent
PAGE_DIR = BASE / "docs" / "preview"
IMG_DIR = PAGE_DIR / "img"
PER_ACCOUNT = 3  # 계정마다 다음 상품 몇 개
REPO = "todayinfopick/pick"


def upcoming():
    """계정별 다음 게시 상품 [(계정 이름, [상품…])]."""
    import accounts
    import main as m
    posted = m.load_posted()
    items = m.load_products()
    now = datetime.datetime.now()
    out = []
    for n in accounts.listing():
        mine = [i for i in items if accounts.route(i["category"]) == n]
        todo = [i for i in m.queue(mine, now)
                if not any(ch in m.get_rec(posted, i) for ch in ("threads", "instagram"))]
        out.append((accounts.label(n), todo[:PER_ACCOUNT]))
    return out


def _thumb(im, mark):
    path = IMG_DIR / f"{mark}.jpg"
    if not path.exists():
        t = im.convert("RGB")
        t.thumbnail((360, 480))
        t.save(path, quality=72)
    return f"img/{mark}.jpg"


def build():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    used_files, sections = set(), []
    e = html.escape
    for label, items in upcoming():
        cards = []
        for item in items:
            photos = it.load_photos(item["source"], item["name"])
            details = it.detail_photos(item["name"])
            allp = photos + details
            if not allp:
                continue
            cells = []
            for k, (im, (mark, ok, why)) in enumerate(zip(allp, it.photo_marks(item["name"], allp))):
                src = _thumb(im, mark)
                used_files.add(pathlib.Path(src).name)
                kind = "대표" if k < len(photos) else "상세"
                cells.append(f'<div class="ph{"" if ok else " off"}" data-m="{mark}" data-ai="{int(why == "AI")}">'
                             f'<img src="{src}" loading="lazy"><i>{kind}</i><b>{e(why or "")}</b></div>')
            cards.append(f'<section class="card" data-k="{e(it.folder_name(item["name"]))}">'
                         f'<div class="name">{e(item["short"])}</div><div class="grid">{"".join(cells)}</div></section>')
        sections.append(f'<h2>{e(label)}</h2>' + ("".join(cards) or '<p class="empty">기다리는 상품이 없어요.</p>'))
    for f in IMG_DIR.glob("*.jpg"):  # 이제 안 보이는 사진은 지움
        if f.name not in used_files:
            f.unlink()
    stamp = datetime.datetime.now().strftime("%m-%d %H:%M")
    (PAGE_DIR / "index.html").write_text(PAGE.replace("{BODY}", "\n".join(sections)).replace("{STAMP}", stamp)
                                         .replace("{REPO}", REPO), encoding="utf-8")
    print(f"✓ 미리보기 페이지: 사진 {len(used_files)}장")


PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>게시 사진 미리보기</title><style>
body{margin:0;background:#f4f5f7;font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#111}
header{background:#0b0e1d;color:#ffe27a;padding:14px 16px;font-weight:800;font-size:19px;position:sticky;top:0;z-index:2}
header small{display:block;color:#cfd3e0;font-weight:400;font-size:12px;margin-top:4px}
h2{font-size:15px;margin:16px 12px 4px;color:#444}
.card{background:#fff;margin:10px 12px;padding:12px;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.name{font-weight:700;margin-bottom:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:6px}
.ph{position:relative;aspect-ratio:3/4;border-radius:8px;overflow:hidden;background:#eee;cursor:pointer;outline:3px solid #22c55e}
.ph img{width:100%;height:100%;object-fit:cover;display:block}
.ph i{position:absolute;left:4px;top:4px;font-style:normal;font-size:10px;background:rgba(0,0,0,.55);color:#fff;padding:1px 5px;border-radius:6px}
.ph b{position:absolute;right:4px;bottom:4px;font-size:10px;background:#fff;padding:1px 5px;border-radius:6px}
.ph b:empty{display:none}
.ph.off{outline-color:#ef4444}.ph.off img{opacity:.3}
.ph.off::after{content:'✕';position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#ef4444;font-size:40px;font-weight:900}
.bar{position:sticky;bottom:0;background:#fff;border-top:1px solid #ddd;padding:10px 12px;display:flex;gap:8px;align-items:center}
.bar span{flex:1;font-size:13px;color:#555}
button{padding:11px 16px;border:0;border-radius:10px;background:#2563eb;color:#fff;font-size:15px;font-weight:700}
button.sub{background:#e5e7eb;color:#111;font-weight:400}
.empty{color:#777;margin:8px 12px}
</style></head><body>
<header>게시 사진 미리보기<small>초록 = 게시에 씀 · 빨강 = 뺌 (AI = AI가 뺀 것). 사진을 누르면 바뀌어요. 안 고치면 그대로 자동 게시돼요. ({STAMP} 기준)</small></header>
{BODY}
<div class="bar"><span id="msg">바꾼 게 없어요</span><button class="sub" id="key">키</button><button id="save">저장</button></div>
<script>
const REPO='{REPO}', FILE='photo_exclude.json', API='https://api.github.com/repos/'+REPO+'/contents/'+FILE;
let data={}, sha=null, changed=0;
const msg=t=>document.getElementById('msg').textContent=t;
const tok=()=>{try{return localStorage.getItem('pick_token')||''}catch(e){return ''}};
function b64d(s){return decodeURIComponent(escape(atob(s.replace(/\\n/g,''))))}
function b64e(s){return btoa(unescape(encodeURIComponent(s)))}
async function load(){
  const h=tok()?{Authorization:'Bearer '+tok()}:{};
  try{const r=await fetch(API+'?ref=main&t='+Date.now(),{headers:h});if(r.ok){const j=await r.json();sha=j.sha;data=JSON.parse(b64d(j.content)||'{}')}}catch(e){}
  document.querySelectorAll('.card').forEach(c=>{const d=data[c.dataset.k]||{};c.querySelectorAll('.ph').forEach(p=>{
    const m=p.dataset.m;if((d.off||[]).includes(m))set(p,false,'직접 뺌');else if((d.on||[]).includes(m))set(p,true,'직접 살림')})});
}
function set(p,ok,why){p.classList.toggle('off',!ok);p.querySelector('b').textContent=why}
document.querySelectorAll('.ph').forEach(p=>p.onclick=()=>{
  const c=p.closest('.card'),k=c.dataset.k,m=p.dataset.m,ai=p.dataset.ai==='1',ok=p.classList.contains('off');
  const d=data[k]=data[k]||{off:[],on:[]};d.off=(d.off||[]).filter(x=>x!==m);d.on=(d.on||[]).filter(x=>x!==m);
  if(!ok)d.off.push(m);else if(ai)d.on.push(m);
  set(p,ok,ok?(ai?'직접 살림':''):'직접 뺌');changed++;msg('바꾼 것 '+changed+'개 · 저장을 눌러 주세요')});
document.getElementById('key').onclick=()=>{const t=prompt('깃허브 키를 붙여 넣어 주세요 (이 기기에만 저장돼요)',tok());if(t!==null){try{localStorage.setItem('pick_token',t.trim())}catch(e){}msg('키를 저장했어요')}};
document.getElementById('save').onclick=async()=>{
  if(!tok()){msg('먼저 키 버튼을 눌러 깃허브 키를 넣어 주세요');return}
  msg('저장 중…');
  for(let i=0;i<2;i++){
    const body={message:'미리보기에서 게시 사진 고침',content:b64e(JSON.stringify(data,null,1)),branch:'main'};if(sha)body.sha=sha;
    const r=await fetch(API,{method:'PUT',headers:{Authorization:'Bearer '+tok(),'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(r.ok){sha=(await r.json()).content.sha;changed=0;msg('✓ 저장했어요. 다음 게시부터 이대로 올라가요');return}
    if(r.status===409||r.status===422){const g=await fetch(API+'?ref=main&t='+Date.now(),{headers:{Authorization:'Bearer '+tok()}});if(g.ok)sha=(await g.json()).sha;continue}
    msg('⚠ 저장 실패 ('+r.status+'). 키에 Contents 쓰기 권한이 있는지 확인해 주세요');return}
  msg('⚠ 저장 실패. 새로고침 후 다시 해 주세요')};
load();
</script></body></html>"""


if __name__ == "__main__":
    import main  # noqa: F401  (.env를 불러옴)
    build()

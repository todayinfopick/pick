// 쿠팡 상품 페이지 오른쪽 아래에 [등록 도우미로 보내기] 버튼을 붙인다.
// 누르면 지금 화면에 있는 상품명·사진 주소·상세 글을 모아 PC 프로그램으로 보낸다. (AI·비용 없음)
(() => {
  if (document.getElementById("pick-send-btn")) return;

  const clean = (t) => (t || "").replace(/[ \t ]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();

  function productName() {
    const sels = ["h1.prod-buy-header__title", ".prod-buy-header__title", "h1[class*='title']", "h1"];
    for (const s of sels) {
      const el = document.querySelector(s);
      if (el && clean(el.innerText)) return clean(el.innerText);
    }
    const og = document.querySelector("meta[property='og:title']");
    if (og && og.content) return clean(og.content);
    return clean(document.title.replace(/\s*[-|:]\s*쿠팡.*$/, ""));
  }

  // 썸네일 크기(.../48x48ex/...)만 다른 같은 사진은 하나로
  const photoKey = (u) => u.replace(/\/\d{2,4}x\d{2,4}ex\//, "/").replace(/^https?:/, "").split("?")[0];

  // 이 상품 사진이 아닌 곳: 리뷰, 다른 상품 추천·광고, 배너. 영상은 아예 안 가져온다.
  const NOT_PRODUCT = [
    "[class*='review' i]", "[id*='review' i]", "[class*='recommend' i]", "[id*='recommend' i]",
    "[class*='banner' i]", "[class*='advert' i]", "[class*='other-seller' i]", "[class*='sdp-review']",
    "[class*='related' i]", "[class*='similar' i]", "[class*='together' i]",
  ].join(",");

  function imgUrl(img) {
    let u = img.getAttribute("data-src") || img.getAttribute("data-img-src") || img.currentSrc || img.src || "";
    if (u.startsWith("//")) u = "https:" + u;
    return u;
  }

  function usable(img, u) {
    if (!/^https?:/.test(u) || !/coupangcdn\.com/.test(u)) return false;
    if (/\.gif(\?|$)/i.test(u) || /icon|badge|logo|sprite|banner/i.test(u)) return false;
    if (img.closest(NOT_PRODUCT)) return false;
    return true;
  }

  // 대표 이미지 + 썸네일 갤러리 (원본 크기는 PC 프로그램이 더 큰 주소로 받아 옴)
  function productImages() {
    const urls = [];
    const add = (img, u) => {
      if (!usable(img, u)) return;
      if (!urls.some((x) => photoKey(x) === photoKey(u))) urls.push(u);
    };
    const og = document.querySelector("meta[property='og:image']");
    if (og && og.content) add(document.body, og.content.startsWith("//") ? "https:" + og.content : og.content);
    const sels = [
      ".prod-image__item img", ".prod-image__items img", "#repImageContainer img", ".prod-image img",
      "[class*='product-image'] img", "[class*='prod-image'] img",
    ];
    for (const s of sels) document.querySelectorAll(s).forEach((img) => add(img, imgUrl(img)));
    return urls.slice(0, 10);
  }

  // 상세페이지 이미지: 상세정보 영역 안의 이미지만 (리뷰·추천 영역 제외)
  function detailImages() {
    const urls = [];
    const sels = [
      "#productDetail img", ".product-detail-content-inside img", ".product-detail-content img",
      ".subType-IMAGE img", ".vendor-item img", "[class*='product-detail'] img", "[class*='productDetail'] img",
    ];
    for (const s of sels) {
      document.querySelectorAll(s).forEach((img) => {
        const u = imgUrl(img);
        if (!usable(img, u)) return;
        if (img.naturalWidth && img.naturalWidth < 300) return; // 작은 아이콘·버튼
        if (!urls.includes(u)) urls.push(u);
      });
    }
    return urls.slice(0, 40);
  }

  function detailText() {
    // 상품 정보 표 · 필수 표기정보 · 글자로 된 상세 설명 (화면에 불러와진 만큼)
    const sels = [
      ".prod-attr-list", ".prod-description", ".prod-item-attr", "#itemBrief", ".product-item__table",
      "#productDetail", ".product-detail-content", ".product-detail-content-inside",
      "[class*='product-detail']", "[class*='productDetail']", "[class*='essential-info']",
    ];
    const parts = [];
    for (const s of sels) {
      document.querySelectorAll(s).forEach((el) => {
        const t = clean(el.innerText);
        if (t.length < 5) return;
        if (parts.some((p) => p.includes(t))) return; // 이미 담은 글 안에 있으면 건너뜀
        for (let i = parts.length - 1; i >= 0; i--) if (t.includes(parts[i])) parts.splice(i, 1);
        parts.push(t);
      });
    }
    let text = parts.join("\n\n");
    if (text.length < 200) text = clean(document.body.innerText); // 페이지 구조가 바뀌었으면 전체 글
    return text;
  }

  const btn = document.createElement("button");
  btn.id = "pick-send-btn";
  btn.textContent = "📥 등록 도우미로 보내기";
  // 기본은 왼쪽 아래 (PC 프로그램 창이 오른쪽에 붙어 있어서). 끌어서 옮기면 그 자리를 기억함.
  let pos = { left: 20, bottom: 20 };
  try { pos = JSON.parse(localStorage.getItem("pick-btn-pos")) || pos; } catch (e) {}
  Object.assign(btn.style, {
    position: "fixed", left: pos.left + "px", bottom: pos.bottom + "px", zIndex: 2147483647, padding: "12px 16px",
    background: "#2563EB", color: "#fff", border: "none", borderRadius: "10px", fontSize: "15px",
    fontWeight: "bold", boxShadow: "0 4px 12px rgba(0,0,0,.25)", cursor: "pointer",
  });
  const show = (text, bg) => {
    btn.textContent = text;
    btn.style.background = bg;
    setTimeout(() => { btn.textContent = "📥 등록 도우미로 보내기"; btn.style.background = "#2563EB"; }, 4000);
  };

  let drag = null, moved = false;
  btn.addEventListener("mousedown", (e) => {
    drag = { x: e.clientX, y: e.clientY, left: btn.offsetLeft, top: btn.offsetTop };
    moved = false;
  });
  document.addEventListener("mousemove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!moved && Math.abs(dx) + Math.abs(dy) < 5) return;
    moved = true;
    const left = Math.max(0, Math.min(window.innerWidth - btn.offsetWidth, drag.left + dx));
    const top = Math.max(0, Math.min(window.innerHeight - btn.offsetHeight, drag.top + dy));
    pos = { left: Math.round(left), bottom: Math.round(window.innerHeight - top - btn.offsetHeight) };
    btn.style.left = pos.left + "px";
    btn.style.bottom = pos.bottom + "px";
  });
  document.addEventListener("mouseup", () => {
    if (drag && moved) try { localStorage.setItem("pick-btn-pos", JSON.stringify(pos)); } catch (e) {}
    drag = null;
  });

  function send(auto) {
    btn.textContent = "보내는 중…";
    const data = { name: productName(), images: productImages(), details: detailImages(), text: detailText(), url: location.href };
    chrome.runtime.sendMessage({ type: "send", data, close: auto }, (res) => {
      if (res && res.ok) show(`✓ 보냄 (사진 ${res.photos}장, 상세 ${res.details || 0}장, 글 ${data.text.length.toLocaleString()}자)`, "#16A34A");
      else if (res && res.error === "offline") show("⚠ PC 프로그램을 먼저 켜 주세요", "#DC2626");
      else show("⚠ 보내지 못했어요", "#DC2626");
    });
  }

  btn.addEventListener("click", () => {
    if (moved) { moved = false; return; } // 끌어서 옮긴 경우엔 보내지 않음
    send(false);
  });

  // 자동 수집: PC 프로그램이 제휴 링크로 이 페이지를 열었을 때만.
  // 끝까지 천천히 내려서 늦게 뜨는 내용을 불러오고, '상세정보 펼쳐보기'를 눌러 펼친 뒤 보내고 창을 닫는다.
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function scrollToEnd(maxSteps) {
    let last = -1, same = 0;
    for (let i = 0; i < maxSteps && same < 4; i++) {
      window.scrollBy(0, Math.round(window.innerHeight * 0.8));
      await sleep(350);
      const h = document.documentElement.scrollHeight;
      const atEnd = window.scrollY + window.innerHeight >= h - 5;
      same = atEnd && h === last ? same + 1 : 0;
      last = h;
    }
  }

  function clickExpand() {
    let n = 0;
    document.querySelectorAll("button, a, [role='button']").forEach((el) => {
      const t = clean(el.innerText);
      if (t.length > 20 || el.dataset.pickClicked) return;
      if (/상세\s*정보\s*펼쳐|펼쳐\s*보기|상품\s*정보\s*더\s*보기/.test(t)) {
        el.dataset.pickClicked = "1";
        el.click();
        n++;
      }
    });
    return n;
  }

  async function autoCollect() {
    btn.textContent = "⏳ 자동 수집 중…";
    btn.style.background = "#9333EA";
    await sleep(1500);
    await scrollToEnd(25);
    if (clickExpand()) { await sleep(1500); }
    await scrollToEnd(80);
    clickExpand();
    await sleep(800);
    send(true);
  }

  chrome.runtime.sendMessage({ type: "auto?" }, (res) => {
    if (res && res.auto) autoCollect();
  });

  document.body.appendChild(btn);
})();

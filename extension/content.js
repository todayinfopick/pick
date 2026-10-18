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

  function productImages() {
    const urls = [];
    const add = (u) => {
      if (!u) return;
      if (u.startsWith("//")) u = "https:" + u;
      if (!/^https?:/.test(u) || !/coupangcdn\.com/.test(u)) return;
      if (/\.gif(\?|$)/i.test(u) || /icon|badge|logo|sprite/i.test(u)) return;
      if (!urls.some((x) => photoKey(x) === photoKey(u))) urls.push(u);
    };
    const og = document.querySelector("meta[property='og:image']");
    if (og) add(og.content);
    const sels = [
      ".prod-image__item img", ".prod-image__items img", "#repImageContainer img", ".prod-image img",
      "[class*='product-image'] img", "[class*='thumbnail'] img", "[class*='Thumbnail'] img",
    ];
    for (const s of sels) {
      document.querySelectorAll(s).forEach((img) => add(img.getAttribute("data-src") || img.currentSrc || img.src));
    }
    return urls.slice(0, 10);
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
  Object.assign(btn.style, {
    position: "fixed", right: "20px", bottom: "20px", zIndex: 2147483647, padding: "12px 16px",
    background: "#2563EB", color: "#fff", border: "none", borderRadius: "10px", fontSize: "15px",
    fontWeight: "bold", boxShadow: "0 4px 12px rgba(0,0,0,.25)", cursor: "pointer",
  });
  const show = (text, bg) => {
    btn.textContent = text;
    btn.style.background = bg;
    setTimeout(() => { btn.textContent = "📥 등록 도우미로 보내기"; btn.style.background = "#2563EB"; }, 4000);
  };

  btn.addEventListener("click", () => {
    btn.textContent = "보내는 중…";
    const data = { name: productName(), images: productImages(), text: detailText(), url: location.href };
    chrome.runtime.sendMessage({ type: "send", data }, (res) => {
      if (res && res.ok) show(`✓ 보냄 (사진 ${res.photos}장, 글 ${data.text.length.toLocaleString()}자)`, "#16A34A");
      else if (res && res.error === "offline") show("⚠ PC 프로그램을 먼저 켜 주세요", "#DC2626");
      else show("⚠ 보내지 못했어요", "#DC2626");
    });
  });
  document.body.appendChild(btn);
})();

// 상품 페이지(content.js)에서 받은 내용을 PC 프로그램(127.0.0.1)으로 보낸다.
// 웹페이지에서 바로 보내면 크롬이 막기 때문에 확장프로그램 쪽에서 보냄.
const BRIDGE = "http://127.0.0.1:27183/page";
const AUTO = "http://127.0.0.1:27183/auto";

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "auto?") {
    // PC 프로그램이 방금 이 페이지를 열었는지 (자동 수집할지) 물어본다
    fetch(AUTO, { headers: { "X-Pick": "1" } })
      .then((r) => r.json())
      .then((res) => reply({ auto: !!res.auto }))
      .catch(() => reply({ auto: false }));
    return true;
  }
  if (msg.type !== "send") return;
  fetch(BRIDGE, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Pick": "1" },
    body: JSON.stringify(msg.data),
  })
    .then((r) => r.json())
    .then((res) => {
      reply(res);
      // 자동 수집으로 연 창은 잘 보낸 뒤 닫는다 (실패하면 그대로 둬서 직접 누를 수 있게)
      if (msg.close && res && res.ok && sender.tab) setTimeout(() => chrome.tabs.remove(sender.tab.id), 1500);
    })
    .catch(() => reply({ ok: false, error: "offline" }));
  return true; // 답을 나중에 보냄
});

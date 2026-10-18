// 상품 페이지(content.js)에서 받은 내용을 PC 프로그램(127.0.0.1)으로 보낸다.
// 웹페이지에서 바로 보내면 크롬이 막기 때문에 확장프로그램 쪽에서 보냄.
const BRIDGE = "http://127.0.0.1:27183/page";

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type !== "send") return;
  fetch(BRIDGE, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Pick": "1" },
    body: JSON.stringify(msg.data),
  })
    .then((r) => r.json())
    .then((res) => reply(res))
    .catch(() => reply({ ok: false, error: "offline" }));
  return true; // 답을 나중에 보냄
});

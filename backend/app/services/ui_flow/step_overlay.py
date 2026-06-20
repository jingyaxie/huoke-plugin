"""在浏览器页面右上角注入步骤提示条（调试 / 演示用，不阻挡点击）。"""
from __future__ import annotations

from datetime import datetime

from playwright.async_api import Page

OVERLAY_ELEMENT_ID = "__huoke_step_overlay__"
OVERLAY_TITLE = "Huoke"

_SET_STEP_OVERLAY_JS = """
({ text, title, detail }) => {
  const ID = "__huoke_step_overlay__";
  let root = document.getElementById(ID);
  if (!root) {
    root = document.createElement("div");
    root.id = ID;
    Object.assign(root.style, {
      position: "fixed",
      top: "12px",
      right: "12px",
      zIndex: "2147483646",
      maxWidth: "min(380px, 42vw)",
      padding: "10px 14px",
      borderRadius: "8px",
      background: "rgba(18, 18, 22, 0.88)",
      color: "#f5f5f5",
      fontSize: "13px",
      lineHeight: "1.5",
      fontFamily: 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
      boxShadow: "0 6px 20px rgba(0,0,0,0.38)",
      pointerEvents: "none",
      whiteSpace: "pre-wrap",
      wordBreak: "break-word",
      border: "1px solid rgba(255,255,255,0.12)",
    });
    const badge = document.createElement("div");
    badge.id = ID + "__badge";
    Object.assign(badge.style, {
      fontSize: "11px",
      fontWeight: "600",
      letterSpacing: "0.04em",
      opacity: "0.72",
      marginBottom: "6px",
      textTransform: "uppercase",
    });
    const body = document.createElement("div");
    body.id = ID + "__body";
    Object.assign(body.style, { fontWeight: "500" });
    const detailEl = document.createElement("div");
    detailEl.id = ID + "__detail";
    Object.assign(detailEl.style, {
      fontSize: "10px",
      opacity: "0.58",
      marginTop: "6px",
      letterSpacing: "0.02em",
    });
    root.appendChild(badge);
    root.appendChild(body);
    root.appendChild(detailEl);
    (document.body || document.documentElement).appendChild(root);
  }
  const badge = document.getElementById(ID + "__badge");
  const body = document.getElementById(ID + "__body");
  const detailEl = document.getElementById(ID + "__detail");
  if (badge) badge.textContent = title || "Huoke";
  if (body) body.textContent = text || "";
  if (detailEl) detailEl.textContent = detail || "";
  return true;
}
"""

_REMOVE_STEP_OVERLAY_JS = """
() => {
  const el = document.getElementById("__huoke_step_overlay__");
  if (el) el.remove();
  return true;
}
"""


async def set_page_step_hint(
    page: Page,
    message: str,
    *,
    sub: str = "",
    title: str = OVERLAY_TITLE,
    detail: str | None = None,
) -> None:
    """在页面右上角显示当前步骤说明（已存在则更新文案）。"""
    main = (message or "").strip()
    if sub:
        text = f"{main}\n{(sub or '').strip()}"
    else:
        text = main
    if not text:
        return
    if detail is None:
        detail = datetime.now().strftime("%H:%M:%S 更新")
    try:
        await page.evaluate(
            _SET_STEP_OVERLAY_JS,
            {
                "text": text[:600],
                "title": (title or OVERLAY_TITLE)[:40],
                "detail": (detail or "")[:120],
            },
        )
    except Exception:
        # 导航 / 刷新过程中 DOM 可能暂不可用
        pass


async def clear_page_step_hint(page: Page) -> None:
    try:
        await page.evaluate(_REMOVE_STEP_OVERLAY_JS)
    except Exception:
        pass

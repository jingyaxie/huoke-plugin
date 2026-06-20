from __future__ import annotations

from typing import Any


def _text_blob(items: list[dict[str, str]]) -> str:
    return " ".join((item.get("text") or "") for item in items).lower()


def _overlay_blob(overlays: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in overlays:
        parts.append(str(row.get("label") or ""))
        parts.append(str(row.get("preview") or ""))
    return " ".join(parts).lower()


def infer_page_context(
    *,
    url: str,
    title: str,
    interactive_elements: list[dict[str, str]],
    overlays: list[dict[str, Any]],
) -> dict[str, Any]:
    """根据 URL、标题、元素与弹层，推断当前页面语义（供 Agent 先理解再操作）。"""
    url_l = (url or "").lower()
    title_l = (title or "").lower()
    texts = _text_blob(interactive_elements)
    overlay_text = _overlay_blob(overlays)
    combined = f"{title_l} {texts} {overlay_text}"

    hints: list[str] = []
    scene = "unknown"
    active_layer = "overlay" if overlays else "main"

    if "验证码" in combined or "captcha" in combined:
        scene = "captcha"
        hints.append("人机验证中，需人工处理或等待通过")
    elif "登录" in combined and ("扫码" in combined or "登录后" in combined):
        scene = "login_wall"
        hints.append("未登录或登录墙，勿盲目点击业务按钮")
    elif "modal_id=" in url_l or ("/video/" in url_l and "douyin.com" in url_l):
        scene = "feed_with_comments"
        panel_open = "全部评论" in combined
        if panel_open:
            hints.append(
                "Feed 评论侧栏已打开；建议先 browser_press Space 暂停视频防自动切走，"
                "再滚侧栏 / browser_wait_api(comment/list) 采评论"
            )
        else:
            hints.append(
                "沉浸式 Feed 播放（评论侧栏未打开）：Feed 会自动切下一个视频，"
                "先 browser_press Space 或点视频区域暂停，"
                "再 browser_click `[data-e2e=\"feed-comment-icon\"]` 打开评论，"
                "最后滚侧栏 / browser_wait_api(comment/list)"
            )
    elif overlays and any(k in overlay_text for k in ("筛选", "filter", "时间", "排序")):
        scene = "filter_modal"
        hints.append("筛选弹层已打开，先在弹层内选条件并确认，再回主列表")
    elif overlays:
        scene = "modal_open"
        hints.append("有弹层/抽屉挡在前方，优先读 foreground_elements 在弹层内操作")
    elif "全部评论" in combined or "条评论" in combined:
        scene = "feed_with_comments"
        hints.append(
            "Feed 评论侧栏已可见；先 Space 暂停视频防自动切走，再滚侧栏并抓 comment/list"
        )
    elif "/search/" in url_l or "抖音搜索" in title_l or "search" in url_l:
        scene = "search_results"
        hints.append("搜索结果页保持综合 Tab；等待列表加载后点击视频封面进入 Feed")
    elif "searchbar" in texts or "搜索你感兴趣" in combined or url_l.rstrip("/").endswith("douyin.com"):
        scene = "home"
        hints.append("首页或顶栏可见，可发起搜索")

    return {
        "scene": scene,
        "active_layer": active_layer,
        "hints": hints,
    }


def build_action_guidance(
    *,
    page_context: dict[str, Any],
    overlays: list[dict[str, Any]],
) -> str | None:
    hints = list(page_context.get("hints") or [])
    if overlays:
        labels = ", ".join(str(o.get("label") or "弹层") for o in overlays[:3])
        hints.insert(0, f"当前前景弹层：{labels}；点击后已变化的 UI 以新一轮 page_info 为准")
    if not hints:
        return "先通读 page_context 与 interactive_elements，想清楚再动手"
    return "；".join(hints)

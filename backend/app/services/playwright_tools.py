from __future__ import annotations

import base64
import json
import time
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.core.antibot import human_click, human_delay, human_scroll, human_type
from app.core.config import Settings
from app.services.agent_browser_session import AgentBrowserSession
from app.services.agent_network_capture import extract_embedded_page_data
from app.services.browser_runtime import BrowserRuntime
from app.services.browser_workbench import should_skip_stable_goto
from app.services.page_understanding import build_action_guidance, infer_page_context

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "browser_goto",
            "description": "导航到指定 URL 并等待页面加载",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL"},
                    "wait_until": {
                        "type": "string",
                        "enum": ["load", "domcontentloaded", "networkidle"],
                        "description": "等待策略，默认 domcontentloaded",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "点击页面元素，selector 支持 CSS 选择器或 Playwright text= 语法",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "元素选择器"},
                    "timeout_ms": {"type": "integer", "description": "超时毫秒，默认 10000"},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "在输入框中填入文本（会先清空）",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "输入框选择器"},
                    "text": {"type": "string", "description": "要填入的文本"},
                    "timeout_ms": {"type": "integer", "description": "超时毫秒，默认 10000"},
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_press",
            "description": "在页面或指定元素上按键，如 Enter、Tab、Escape",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "按键名称，如 Enter"},
                    "selector": {"type": "string", "description": "可选，聚焦到该元素后按键"},
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "滚动页面；target=comment_sidebar 时只在评论侧栏内分页滚动（Feed/详情页采评论、找目标评论）",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["down", "up", "bottom", "top"],
                        "description": "滚动方向",
                    },
                    "amount": {"type": "integer", "description": "滚动像素，仅 up/down 时有效，默认 600"},
                    "target": {
                        "type": "string",
                        "enum": ["page", "comment_sidebar"],
                        "description": "滚动目标：page=整页，comment_sidebar=评论侧栏分页",
                    },
                    "rounds": {
                        "type": "integer",
                        "description": "comment_sidebar 模式下滚动轮次，默认 1",
                    },
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait",
            "description": "等待元素出现或等待指定毫秒",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "等待出现的元素选择器"},
                    "timeout_ms": {"type": "integer", "description": "超时毫秒，默认 10000"},
                    "state": {
                        "type": "string",
                        "enum": ["visible", "attached", "hidden"],
                        "description": "元素状态，默认 visible",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_text",
            "description": "获取元素文本或页面可见文本摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "元素选择器，留空则返回页面 body 文本摘要（最多 3000 字符）",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_page_info",
            "description": (
                "获取页面全局快照：page_context、overlays、foreground_elements、api_captures。"
                "有弹层时优先 foreground_elements。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_warmup",
            "description": "模拟真人：先访问平台首页滚动热身，建立正常浏览会话（底层能力，不含业务逻辑）",
            "parameters": {
                "type": "object",
                "properties": {
                    "home_url": {
                        "type": "string",
                        "description": "首页 URL，留空则使用当前平台默认首页",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_browse",
            "description": "模拟真人浏览：可选首页热身 → 打开目标 URL → 随机延迟与滚动，触发 SPA 接口请求",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标页面 URL"},
                    "warmup_first": {
                        "type": "boolean",
                        "description": "是否先访问首页热身，默认 true",
                    },
                    "home_url": {"type": "string", "description": "可选，自定义首页 URL"},
                    "scroll_rounds": {
                        "type": "integer",
                        "description": "滚动次数，默认 2",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait_api",
            "description": "等待浏览器拦截到匹配条件的 JSON 接口（XHR/Fetch），用于接口优先的数据获取",
            "parameters": {
                "type": "object",
                "properties": {
                    "url_contains": {
                        "type": "string",
                        "description": "URL/path 关键词，如 comment/list、search/notes、hotspot",
                    },
                    "min_count": {"type": "integer", "description": "最少匹配条数，默认 1"},
                    "timeout_ms": {"type": "integer", "description": "超时毫秒，默认 15000"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_network_data",
            "description": (
                "读取浏览器自动拦截的完整 JSON 接口响应（XHR/Fetch）。"
                "业务解析由 Skill/Agent 完成，底层只返回原始 data。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url_contains": {
                        "type": "string",
                        "description": "URL 或 path 包含的关键词，如 comment/list、search、aweme",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回最近匹配的接口数量，默认 5",
                    },
                    "clear_buffer": {
                        "type": "boolean",
                        "description": "读取后是否清空拦截缓存，默认 false",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "截取当前页面截图，用于视觉理解页面布局",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "任务已成功完成，停止执行并返回结果摘要；对外接口任务请在 result 中返回结构化 JSON",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "任务完成摘要"},
                    "result": {
                        "type": "object",
                        "description": "结构化交付结果（视频列表、评论等），供外部 API 直接消费",
                    },
                },
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_failed",
            "description": "任务无法完成，停止执行并说明原因",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "失败原因"},
                },
                "required": ["reason"],
            },
        },
    },
]


async def _interactive_summary(page: Page, limit: int = 40) -> list[dict[str, str]]:
    script = """
    () => {
      const items = [];
      const seen = new Set();
      const push = (tag, text, selectorHint, layer) => {
        const key = layer + '|' + tag + '|' + text;
        if (!text || seen.has(key)) return;
        seen.add(key);
        items.push({ tag, text, selector_hint: selectorHint, layer });
      };
      const collect = (root, layer) => {
        root.querySelectorAll('a[href], button, input, textarea, [role="button"], [role="tab"], label, [data-e2e]').forEach((el, idx) => {
          const tag = el.tagName.toLowerCase();
          const e2e = el.getAttribute('data-e2e') || '';
          const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.placeholder || e2e || '').trim().slice(0, 80);
          if (!text && tag !== 'input' && tag !== 'textarea') return;
          const id = el.id ? '#' + el.id : '';
          const cls = (el.className && typeof el.className === 'string')
            ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.')
            : '';
          const hint = e2e ? `[data-e2e="${e2e}"]` : (`${tag}${id}${cls}` || `nth=${idx}`);
          push(tag, text || `[${tag}]`, hint, layer);
        });
      };
      collect(document, 'main');
      return items.slice(0, """ + str(limit) + """);
    }
    """
    try:
        raw = await page.evaluate(script)
        return [{k: v for k, v in row.items() if k != "layer"} for row in raw]
    except Exception:
        return []


async def _overlay_layers(page: Page, limit: int = 6) -> list[dict[str, Any]]:
    script = """
    () => {
      const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 40 && rect.height > 40;
      };
      const selectors = [
        '[role="dialog"]',
        '[role="alertdialog"]',
        '[aria-modal="true"]',
        '[class*="modal" i]',
        '[class*="Modal" i]',
        '[class*="dialog" i]',
        '[class*="Dialog" i]',
        '[class*="popup" i]',
        '[class*="Popup" i]',
        '[class*="drawer" i]',
        '[class*="Drawer" i]',
        '[class*="filter" i]',
        '[class*="Filter" i]',
        '#captcha_container',
      ];
      const seen = new Set();
      const overlays = [];
      for (const sel of selectors) {
        document.querySelectorAll(sel).forEach((el) => {
          if (!isVisible(el) || seen.has(el)) return;
          seen.add(el);
          const text = (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 240);
          const label = text.split(' ').slice(0, 8).join(' ') || sel;
          const controls = [];
          el.querySelectorAll('button, a[href], input, [role="button"], [role="tab"], label').forEach((node, idx) => {
            const t = (node.innerText || node.value || node.getAttribute('aria-label') || '').trim().slice(0, 60);
            if (!t) return;
            const id = node.id ? '#' + node.id : '';
            controls.push({ tag: node.tagName.toLowerCase(), text: t, selector_hint: `${node.tagName.toLowerCase()}${id}` || `nth=${idx}` });
          });
          overlays.push({
            kind: sel,
            label,
            preview: text,
            controls: controls.slice(0, 20),
          });
        });
      }
      return overlays.slice(0, """ + str(limit) + """);
    }
    """
    try:
        return await page.evaluate(script)
    except Exception:
        return []


def _foreground_elements(
    interactive_elements: list[dict[str, str]],
    overlays: list[dict[str, Any]],
    *,
    limit: int = 40,
) -> list[dict[str, str]]:
    if not overlays:
        return interactive_elements[:limit]
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for overlay in overlays:
        for ctrl in overlay.get("controls") or []:
            if not isinstance(ctrl, dict):
                continue
            text = str(ctrl.get("text") or "")
            key = f"{ctrl.get('tag')}|{text}"
            if not text or key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "tag": str(ctrl.get("tag") or ""),
                    "text": text,
                    "selector_hint": str(ctrl.get("selector_hint") or ""),
                    "layer": "overlay",
                }
            )
    for row in interactive_elements:
        key = f"{row.get('tag')}|{row.get('text')}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged[:limit]


class PlaywrightToolExecutor:
    _PAGE_INFO_THROTTLE_SEC = 2.5

    def __init__(self, session: AgentBrowserSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.runtime = BrowserRuntime(session, settings)
        self._page_info_cache: dict[str, Any] | None = None
        self._page_info_cache_at: float = 0.0
        self._page_info_cache_url: str = ""

    def _invalidate_page_info_cache(self) -> None:
        self._page_info_cache = None
        self._page_info_cache_at = 0.0
        self._page_info_cache_url = ""

    async def execute(self, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        try:
            page = await self.session.ensure_started()
        except TimeoutError:
            return {"error": "浏览器启动超时，请稍后重试"}, None
        except Exception as exc:
            return {"error": f"浏览器启动失败: {exc}"}, None
        try:
            if name == "browser_goto":
                return await self._goto(page, arguments), None
            if name == "browser_click":
                return await self._click(page, arguments), None
            if name == "browser_fill":
                return await self._fill(page, arguments), None
            if name == "browser_press":
                return await self._press(page, arguments), None
            if name == "browser_scroll":
                return await self._scroll(page, arguments), None
            if name == "browser_wait":
                return await self._wait(page, arguments), None
            if name == "browser_get_text":
                return await self._get_text(page, arguments), None
            if name == "browser_get_page_info":
                return await self._get_page_info(page), None
            if name == "browser_warmup":
                return await self.runtime.warmup(arguments.get("home_url")), None
            if name == "browser_browse":
                return await self.runtime.browse(
                    arguments["url"],
                    warmup_first=bool(arguments.get("warmup_first", True)),
                    home_url=arguments.get("home_url"),
                    scroll_rounds=int(arguments.get("scroll_rounds", 2)),
                ), None
            if name == "browser_wait_api":
                return await self.runtime.wait_api(
                    url_contains=arguments.get("url_contains"),
                    min_count=int(arguments.get("min_count", 1)),
                    timeout_ms=int(arguments.get("timeout_ms", 15000)),
                ), None
            if name == "browser_get_network_data":
                return self.runtime.query_api(
                    url_contains=arguments.get("url_contains"),
                    limit=int(arguments.get("limit", 5)),
                    clear_buffer=bool(arguments.get("clear_buffer", False)),
                ), None
            if name == "browser_screenshot":
                return await self._screenshot(page), None
            if name == "task_complete":
                payload: dict[str, Any] = {
                    "status": "completed",
                    "summary": arguments.get("summary", ""),
                }
                if isinstance(arguments.get("result"), dict):
                    payload["result"] = arguments["result"]
                return payload, None
            if name == "task_failed":
                return {"status": "failed", "reason": arguments.get("reason", "")}, None
            return {"error": f"未知工具: {name}"}, None
        except PlaywrightTimeoutError as exc:
            return {"error": f"操作超时: {exc}"}, None
        except Exception as exc:
            return {"error": str(exc)}, None

    async def _goto(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        url = args["url"]
        wait_until = args.get("wait_until", "domcontentloaded")
        if wait_until == "networkidle":
            wait_until = "domcontentloaded"
        skip, reason = should_skip_stable_goto(
            self.session,
            url,
            force=bool(args.get("force")),
        )
        if skip:
            info = await self.session.page_info()
            return {
                "skipped": True,
                "reason": reason,
                "hint": "稳定基座：当前页已可用，未刷新。请先 browser_get_page_info 理解页面再操作。",
                "url": info["url"],
                "title": info["title"],
            }
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="page_load")
        response = await page.goto(url, wait_until=wait_until, timeout=45000)
        info = await self.session.page_info()
        return {
            "url": info["url"],
            "title": info["title"],
            "status": response.status if response else None,
            "wait_until": wait_until,
        }

    async def _click(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        selector = args["selector"]
        timeout = args.get("timeout_ms", 10000)
        await human_click(
            page,
            selector,
            self.settings,
            tenant_id=self.session.tenant_id,
            timeout=timeout,
        )
        self._invalidate_page_info_cache()
        info = await self.session.page_info()
        return {"clicked": selector, "url": info["url"], "title": info["title"]}

    async def _fill(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        selector = args["selector"]
        text = args["text"]
        timeout = args.get("timeout_ms", 10000)
        await human_type(
            page,
            selector,
            text,
            self.settings,
            tenant_id=self.session.tenant_id,
            timeout=timeout,
        )
        self._invalidate_page_info_cache()
        return {"filled": selector, "text_length": len(text)}

    async def _press(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        key = args["key"]
        selector = args.get("selector")
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="action")
        if selector:
            await page.locator(selector).first.press(key)
        else:
            await page.keyboard.press(key)
        self._invalidate_page_info_cache()
        info = await self.session.page_info()
        return {"pressed": key, "url": info["url"], "title": info["title"]}

    async def _scroll(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        target = str(args.get("target") or "page").strip().lower()
        direction = args["direction"]
        amount = args.get("amount", 600)
        if target == "comment_sidebar":
            from app.services.ui_flow.platforms.douyin.feed_ui import (
                activate_comment_sidebar_on_page,
                scroll_comment_sidebar_on_page,
            )

            rounds = max(1, int(args.get("rounds") or 1))
            if direction in {"down", "bottom"}:
                await activate_comment_sidebar_on_page(
                    page,
                    self.settings,
                    tenant_id=self.session.tenant_id,
                )
                scrolled = await scroll_comment_sidebar_on_page(
                    page,
                    self.settings,
                    tenant_id=self.session.tenant_id,
                    rounds=rounds if direction == "down" else max(rounds, 3),
                )
                self._invalidate_page_info_cache()
                return {
                    "scrolled": direction,
                    "target": "comment_sidebar",
                    "rounds": rounds,
                    "sidebar_scrolled": scrolled,
                    "hint": "评论侧栏分页滚动；配合 browser_wait_api(comment/list) 加载更多评论",
                }
            self._invalidate_page_info_cache()
            return {
                "error": "comment_sidebar 仅支持 direction=down 或 bottom",
                "target": "comment_sidebar",
            }
        if direction == "down":
            await human_scroll(
                page,
                self.settings,
                tenant_id=self.session.tenant_id,
                delta_y=amount,
            )
        elif direction == "up":
            await human_scroll(
                page,
                self.settings,
                tenant_id=self.session.tenant_id,
                delta_y=-amount,
            )
        elif direction == "bottom":
            await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="scroll")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "top":
            await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="scroll")
            await page.evaluate("window.scrollTo(0, 0)")
        self._invalidate_page_info_cache()
        return {"scrolled": direction, "amount": amount if direction in {"down", "up"} else None}

    async def _wait(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        selector = args.get("selector")
        timeout = args.get("timeout_ms", 10000)
        state = args.get("state", "visible")
        if selector:
            await page.locator(selector).first.wait_for(state=state, timeout=timeout)
            return {"waited_for": selector, "state": state}
        await page.wait_for_timeout(min(timeout, 30000))
        return {"waited_ms": timeout}

    async def _get_text(self, page: Page, args: dict[str, Any]) -> dict[str, Any]:
        selector = args.get("selector")
        if selector:
            text = await page.locator(selector).first.inner_text(timeout=10000)
            return {"selector": selector, "text": text[:5000]}
        body_text = await page.locator("body").inner_text(timeout=10000)
        return {"text": body_text[:3000], "truncated": len(body_text) > 3000}

    async def _get_page_info(self, page: Page) -> dict[str, Any]:
        current_url = (page.url or "").strip()
        now = time.monotonic()
        if getattr(self.session, "stable_mode", False) and self._page_info_cache:
            if (
                current_url == self._page_info_cache_url
                and now - self._page_info_cache_at < self._PAGE_INFO_THROTTLE_SEC
            ):
                cached = dict(self._page_info_cache)
                cached["throttled"] = True
                cached["hint"] = (
                    str(cached.get("hint") or "")
                    + "（同页短期内重复读页，沿用缓存；有操作后再读）"
                ).strip()
                return cached

        info = await self.session.page_info()
        overlays = await _overlay_layers(page)
        elements = await _interactive_summary(page)
        foreground = _foreground_elements(elements, overlays)
        embedded_data = await extract_embedded_page_data(page)
        api_captures = self.session.network_capture.list_summaries(limit=8)
        page_context = infer_page_context(
            url=str(info.get("url") or ""),
            title=str(info.get("title") or ""),
            interactive_elements=foreground,
            overlays=overlays,
        )
        guidance = build_action_guidance(
            page_context=page_context,
            overlays=overlays,
        )
        result = {
            "url": info["url"],
            "title": info["title"],
            "page_context": page_context,
            "overlays": overlays,
            "interactive_elements": elements,
            "foreground_elements": foreground,
            "interactive_elements_count": len(elements),
            "api_captures": api_captures,
            "api_capture_count": len(api_captures),
            "embedded_data": embedded_data,
            "action_guidance": guidance,
            "hint": guidance or "先读 page_context + action_guidance，想清楚再动手",
        }
        if getattr(self.session, "stable_mode", False):
            self._page_info_cache = result
            self._page_info_cache_at = now
            self._page_info_cache_url = current_url
        return result

    async def _screenshot(self, page: Page) -> dict[str, Any]:
        png_bytes = await page.screenshot(type="png", full_page=False)
        encoded = base64.b64encode(png_bytes).decode("ascii")
        return {
            "format": "png",
            "base64": encoded,
            "size_bytes": len(png_bytes),
        }


def parse_tool_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}

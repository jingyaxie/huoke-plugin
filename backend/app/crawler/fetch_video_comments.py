from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.async_api import async_playwright


COMMENT_PATH = "/aweme/v1/web/comment/list/"
DROP_QUERY_KEYS = {"a_bogus", "x-secsdk-web-signature", "msToken"}


def extract_aweme_id(video_url: str) -> str:
    match = re.search(r"/video/(\d+)", video_url)
    if not match:
        raise ValueError(f"无法从链接解析 aweme_id: {video_url}")
    return match.group(1)


def normalize_comment(item: dict, parent_comment_id: str | None = None) -> dict:
    user = item.get("user") or {}
    avatar = user.get("avatar_larger") or user.get("avatar_medium") or user.get("avatar_thumb") or {}
    avatar_url_list = avatar.get("url_list") or []
    return {
        "comment_id": str(item.get("cid") or ""),
        "parent_comment_id": parent_comment_id,
        "comment": item.get("text") or "",
        "create_time": item.get("create_time"),
        "digg_count": int(item.get("digg_count") or 0),
        "reply_comment_total": int(item.get("reply_comment_total") or 0),
        "username": user.get("nickname") or "",
        "user_id": str(user.get("uid") or ""),
        "sec_uid": user.get("sec_uid") or "",
        "avatar": avatar_url_list[0] if avatar_url_list else "",
    }


def build_next_url(base_url: str, cursor: int) -> str:
    split = urlsplit(base_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query["cursor"] = str(cursor)
    for key in DROP_QUERY_KEYS:
        query.pop(key, None)
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query, doseq=True), ""))


async def fetch_json(page, url: str) -> dict:
    payload = await page.evaluate(
        """async (url) => {
            const resp = await fetch(url, { credentials: 'include' });
            const text = await resp.text();
            return { status: resp.status, ok: resp.ok, text };
        }""",
        url,
    )
    text = (payload.get("text") or "").strip()
    if not text:
        raise RuntimeError(f"接口返回空内容: {url}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        preview = text[:300].replace("\n", " ")
        raise RuntimeError(f"接口返回非JSON: status={payload.get('status')} ok={payload.get('ok')} preview={preview}") from exc


async def fetch_all_comments(video_url: str, storage_state: Path, headless: bool = True) -> dict:
    aweme_id = extract_aweme_id(video_url)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1200},
            storage_state=str(storage_state),
        )
        page = await context.new_page()
        first_response: dict = {"url": None, "data": None}

        async def on_response(resp):
            if COMMENT_PATH in resp.url and first_response["url"] is None:
                try:
                    first_response["url"] = resp.url
                    first_response["data"] = await resp.json()
                except Exception:
                    return

        page.on("response", on_response)
        await page.goto(video_url, wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(12000)

        if not first_response["url"] or not first_response["data"]:
            raise RuntimeError("未捕获到评论接口响应，请检查 Cookie 是否失效。")

        comments_map: dict[str, dict] = {}
        top_comment_ids: set[str] = set()
        first_data: dict = first_response["data"]
        api_total = int(first_data.get("total") or 0)
        api_url = first_response["url"]

        cursor = 0
        has_more = 1
        guard = 0
        while has_more and guard < 50:
            guard += 1
            page_url = build_next_url(api_url, cursor)
            page_url = page_url.replace("count=5", "count=20")
            data = await fetch_json(page, page_url)
            for c in data.get("comments") or []:
                row = normalize_comment(c)
                if row["comment_id"]:
                    top_comment_ids.add(row["comment_id"])
                    comments_map[row["comment_id"]] = row
                for reply in c.get("reply_comment") or []:
                    reply_row = normalize_comment(reply, parent_comment_id=row["comment_id"])
                    if reply_row["comment_id"]:
                        comments_map[reply_row["comment_id"]] = reply_row
            cursor = int(data.get("cursor") or cursor)
            has_more = int(data.get("has_more") or 0)
            if not data.get("comments"):
                break

        await context.close()
        await browser.close()

    comments = list(comments_map.values())
    comments.sort(key=lambda x: x.get("create_time") or 0, reverse=True)
    top_rows = [row for row in comments if not row.get("parent_comment_id")]
    preview_reply_rows = [row for row in comments if row.get("parent_comment_id")]
    expected_reply_total = sum(int(row.get("reply_comment_total") or 0) for row in top_rows)
    return {
        "aweme_id": aweme_id,
        "video_url": video_url,
        "api_total_top_comments": api_total,
        "top_comments_captured": len(top_rows),
        "reply_comments_captured_preview": len(preview_reply_rows),
        "expected_reply_total_from_top_comments": expected_reply_total,
        "total_comments_captured": len(comments),
        "comments": comments,
    }


async def amain(args: argparse.Namespace) -> None:
    payload = await fetch_all_comments(
        video_url=args.video_url,
        storage_state=Path(args.storage_state),
        headless=not args.show_browser,
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    print(f"captured: {payload['total_comments_captured']} / api_total_top_comments: {payload['api_total_top_comments']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取抖音视频全量评论（用户名/头像/用户ID/评论正文）")
    parser.add_argument("--video-url", required=True)
    parser.add_argument("--storage-state", default="backend/storage/douyin/storage_state.json")
    parser.add_argument("--output", default="backend/reports/comments_full.json")
    parser.add_argument("--show-browser", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(amain(parse_args()))

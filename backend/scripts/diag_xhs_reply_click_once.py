#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUOKE_ROOT = ROOT.parent
if not os.environ.get("STORAGE_ROOT"):
    os.environ["STORAGE_ROOT"] = str((HUOKE_ROOT / "storage/sidecar-dev").resolve())
sys.path.insert(0, str(ROOT))

NOTE_URL = (
    "https://www.xiaohongshu.com/explore/68a2aa3b000000001d00eaaa"
    "?xsec_token=AB8ecVojqYkxXdqWlIpUvfQX7Lhwl7o4EHtAUvpCMPqHY%3D&xsec_source=pc_feed"
)


async def main() -> None:
    from app.core.config import get_settings
    from app.services.agent_browser_session import AgentBrowserSession

    settings = get_settings()
    browser = AgentBrowserSession("diag-reply-click", "default", "xiaohongshu", settings, headless=False)
    page = await browser.ensure_started()
    await page.goto(NOTE_URL, wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(4)

    before = await page.evaluate(
        """() => ({
          parent: document.querySelectorAll('.parent-comment').length,
          replyIcon: document.querySelectorAll('.reply.icon-container').length,
          sample: (document.querySelector('.parent-comment')?.innerHTML || '').slice(0, 800),
        })"""
    )
    print("before:", json.dumps(before, ensure_ascii=False)[:1200])

    clicked = await page.evaluate(
        """() => {
          const item = document.querySelector('.parent-comment');
          if (!item) return { ok: false, reason: 'no parent-comment' };
          const btn = item.querySelector('.reply.icon-container, .reply');
          if (!btn) return { ok: false, reason: 'no reply btn', html: item.innerHTML.slice(0, 400) };
          btn.click();
          return { ok: true, class: btn.className };
        }"""
    )
    print("clicked:", clicked)
    await asyncio.sleep(2)

    after = await page.evaluate(
        """() => {
          const hasReplyBanner = [...document.querySelectorAll('div, span, p')].some((el) => {
            const t = (el.textContent || '').trim();
            return /^回复\\s+\\S/.test(t) && t.length < 48;
          });
          const buttons = [...document.querySelectorAll('button, div, span')].map((el) => (el.textContent || '').trim());
          return {
            overlay: hasReplyBanner && buttons.includes('发送') && buttons.includes('取消'),
            banner: hasReplyBanner,
            send: buttons.includes('发送'),
            cancel: buttons.includes('取消'),
          };
        }"""
    )
    print("after:", after)
    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

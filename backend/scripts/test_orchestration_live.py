#!/usr/bin/env python3
"""编排 + Supervisor 联调测试（真实 LLM，dry_run 不抓数据）。

用法：
  ORCHESTRATION_LIVE=1 python3 scripts/test_orchestration_live.py
  # 或从 huoke 根目录加载 DEEPSEEK：
  HUOKE_ENV=/Users/macbook/project/ai/huoke/.env ORCHESTRATION_LIVE=1 python3 scripts/test_orchestration_live.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT
sys.path.insert(0, str(BACKEND))


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _settings():
    from app.core.config import Settings

    tmp = ROOT / "storage" / "orchestration-live-test"
    tmp.mkdir(parents=True, exist_ok=True)
    return Settings(storage_root=tmp)


def _require_live() -> None:
    if os.environ.get("ORCHESTRATION_LIVE") != "1":
        print("跳过：设置 ORCHESTRATION_LIVE=1 启用真实 LLM 联调")
        sys.exit(0)


def _require_deepseek(settings) -> None:
    if not settings.deepseek_api_key:
        print("失败：未找到 DEEPSEEK_API_KEY，请设置 HUOKE_ENV 或 .env.local")
        sys.exit(1)


async def test_llm_brief_and_plan(settings) -> None:
    from app.services.agent_job_plan_service import build_orchestration_plan
    from app.services.task_brief_service import generate_task_brief

    message = (
        "深圳餐饮老板线索任务：在抖音搜索关键词「团餐配送」，"
        "抓取近3天评论，目标50条有效线索；"
        "触达策略按日配额评论5条、私信3条、关注3条，"
        "任务可能分多天完成，配额用尽后次日继续。"
    )
    print("\n=== [1] LLM 任务简报 ===")
    brief = await generate_task_brief(
        message,
        settings=settings,
        tenant_id="default",
        provider="deepseek",
    )
    assert brief.llm_available, f"期望 LLM 可用，实际 llm_fallback={brief.llm_fallback}"
    assert brief.keyword, "简报应解析出 keyword"
    assert brief.brief_md, "应有 brief_md"
    print(f"  ✓ title={brief.title}")
    print(f"  ✓ keyword={brief.keyword} platform={brief.platform} confidence={brief.confidence:.0%}")
    print(f"  ✓ brief 前120字: {brief.brief_md[:120].replace(chr(10), ' ')}...")

    print("\n=== [2] 编排计划 ===")
    plan = await build_orchestration_plan(message, settings=settings, tenant_id="default", provider="deepseek")
    assert plan["execution_mode"] == "supervisor"
    assert plan["source"] == "supervisor"
    assert plan.get("task_brief", {}).get("keyword")
    steps = [s["id"] for s in plan.get("steps") or []]
    assert "observe" in steps and "dream" in steps
    print(f"  ✓ execution_mode=supervisor steps={steps}")
    print(f"  ✓ reasoning: {(plan.get('reasoning') or '')[:100]}...")


async def test_supervisor_dry_run_multiday(settings) -> None:
    from app.services.task_brief_service import TaskBrief
    from app.services.task_supervisor_service import TaskSupervisorService

    brief = TaskBrief(
        title="多日触达测试",
        brief_md="# 多日触达\n目标50条，日配额 reply=5 dm=3 follow=3",
        platform="douyin",
        keyword="团餐配送",
        region="深圳",
        goals={"target_leads": 50, "comment_days": 3},
        constraints={"daily_reply_limit": 5, "daily_follow_limit": 3, "daily_dm_limit": 3},
        success_criteria="累计触达50条",
        llm_available=True,
        llm_fallback=False,
    )

    svc = TaskSupervisorService(settings, "default", "douyin", "default", provider="deepseek")

    print("\n=== [3] Supervisor dry_run 第1天（已完成抓取，触达配额耗尽后挂起）===")
    exhausted_stats = {
        "reply": {"count": 5, "limit": 5, "can_do": False},
        "dm": {"count": 3, "limit": 3, "can_do": False},
        "follow": {"count": 3, "limit": 3, "can_do": False},
    }
    day1_result = await svc.run(
        brief=brief,
        job_result={
            "supervisor_state": {
                "day_index": 1,
                "crawl_done": True,
                "leads_collected": 11,
                "simulated_stats": exhausted_stats,
            }
        },
        timeout_seconds=120,
        dry_run=True,
    )
    assert day1_result["dry_run"] is True
    cycles1 = day1_result.get("supervisor_cycles") or []
    actions1 = [c.get("action") for c in cycles1]
    print(f"  ✓ 第1天 cycles={len(cycles1)} actions={actions1}")

    state1 = day1_result.get("supervisor_state") or {}
    status1 = day1_result.get("status")
    assert status1 in {"suspended", "completed"}, f"第1天配额耗尽应挂起或完成，实际 {status1}"
    if status1 == "suspended":
        print(f"  ✓ 第1天挂起: {day1_result.get('summary')}")
        print(f"  ✓ resume_at={state1.get('resume_at')}")
    else:
        print(f"  ~ 第1天直接完成: {day1_result.get('summary')}")

    print("\n=== [4] Supervisor dry_run 第2天唤醒（配额重置继续）===")
    fresh_stats = {
        "reply": {"count": 0, "limit": 5, "can_do": True},
        "dm": {"count": 0, "limit": 3, "can_do": True},
        "follow": {"count": 0, "limit": 3, "can_do": True},
    }
    state1["day_index"] = int(state1.get("day_index") or 1) + 1
    state1["suspended"] = False
    state1["simulated_stats"] = fresh_stats
    state1.pop("resume_at", None)

    day2_result = await svc.run(
        brief=brief,
        job_result={
            "supervisor_state": state1,
            "supervisor_cycles": cycles1,
        },
        timeout_seconds=120,
        dry_run=True,
    )
    cycles2 = day2_result.get("supervisor_cycles") or []
    new_cycles = cycles2[len(cycles1):]
    actions2 = [c.get("action") for c in new_cycles]
    print(f"  ✓ 第2天新增 cycles={len(new_cycles)} actions={actions2}")
    outreach = [a for a in actions2 if a in {"reply", "dm", "follow", "query_stats"}]
    assert outreach or day2_result.get("status") in {"completed", "suspended"}, "第2天应有触达或再次挂起/完成"
    print(f"  ✓ 第2天 status={day2_result.get('status')} summary={day2_result.get('summary', '')[:80]}")


async def test_job_api_dry_run(settings) -> None:
    import httpx

    port = os.environ.get("SIDECAR_PORT", "18000")
    base = f"http://127.0.0.1:{port}"
    tenant = os.environ.get("HUOKE_TENANT_ID", "default")

    print("\n=== [5] Sidecar API dry_run 提交 ===")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            health = await client.get(f"{base}/api/health")
            if health.status_code != 200:
                print("  ~ Sidecar 未运行，跳过 API 测试")
                return

            message = (
                "测试编排：深圳团餐配送线索，抖音，目标30条，"
                "评论私信关注分多天完成，今日仅模拟不真抓。"
            )
            payload = {
                "message": message,
                "provider": "deepseek",
                "run_mode": "dry_run",
                "auto_execute": True,
                "timeout_seconds": 120,
                "max_retries": 0,
            }
            resp = await client.post(
                f"{base}/api/agent/jobs",
                headers={
                    "Content-Type": "application/json",
                    "X-Tenant-Id": tenant,
                    "X-Platform-Id": "douyin",
                    "X-Account-Id": "default",
                },
                json=payload,
            )
            assert resp.status_code == 200, resp.text
            job = resp.json()
            job_id = job.get("job_id")
            orch = (job.get("result") or {}).get("orchestration") or {}
            assert job.get("result", {}).get("execution_mode") == "supervisor"
            assert orch.get("task_brief", {}).get("brief_md"), "API 应返回 task_brief"
            print(f"  ✓ POST /api/agent/jobs job_id={job_id}")
            print(f"  ✓ llm_compiled={orch.get('llm_compiled')} keyword={orch.get('input_summary', {}).get('keyword')}")

            for _ in range(40):
                await asyncio.sleep(2)
                get_resp = await client.get(
                    f"{base}/api/agent/jobs/{job_id}",
                    headers={"X-Tenant-Id": tenant},
                )
                loaded = get_resp.json()
                st = loaded.get("status")
                if st in {"completed", "failed", "pending", "dead_letter"}:
                    cycles = (loaded.get("result") or {}).get("supervisor_cycles") or []
                    print(f"  ✓ 执行结束 status={st} cycles={len(cycles)}")
                    if st == "pending":
                        resume = ((loaded.get("result") or {}).get("supervisor_state") or {}).get("resume_at")
                        print(f"  ✓ 策略挂起待唤醒 resume_at={resume}")
                    assert (loaded.get("result") or {}).get("dry_run") is True or st == "pending"
                    return
            print("  ✗ 等待 job 完成超时")
            sys.exit(1)
    except httpx.ConnectError:
        print("  ~ Sidecar 未连接，跳过 API 测试")


async def main() -> None:
    _require_live()
    huoke_env = os.environ.get("HUOKE_ENV", "/Users/macbook/project/ai/huoke/.env")
    _load_env_file(Path(huoke_env))
    _load_env_file(Path(__file__).resolve().parents[2] / ".env.local")

    settings = _settings()
    _require_deepseek(settings)
    print("=== Huoke 编排 LIVE 测试（dry_run，不真抓数据）===")
    print(f"DEEPSEEK_MODEL={settings.deepseek_model}")

    await test_llm_brief_and_plan(settings)
    await test_supervisor_dry_run_multiday(settings)
    await test_job_api_dry_run(settings)

    print("\n=== 全部 LIVE 测试通过 ===")


if __name__ == "__main__":
    asyncio.run(main())

"""任务创建 → 预检编排 → 执行 Supervisor 全流程自动化测试。"""
from __future__ import annotations

import uuid

import pytest

from app.services.agent_async_job_service import _JobKey
from tests.helpers import API_HEADERS
from tests.test_external_task_agent_e2e import (
    build_account_home_payload_like_frontend,
)
from tests.test_frontend_payload_alignment import (
    build_auto_task_payload_like_frontend,
    build_manual_task_payload_like_frontend,
)


def _unique_correlation(payload: dict, suffix: str) -> dict:
    token = f"flow-{suffix}-{uuid.uuid4().hex[:8]}"
    payload = dict(payload)
    correlation = dict(payload.get("correlation") or {})
    correlation["external_task_id"] = token
    correlation["idempotency_key"] = token
    payload["correlation"] = correlation
    payload["auto_execute"] = False
    return payload


def _orchestration_actions(preflight_body: dict) -> set[str]:
    orch = preflight_body.get("orchestration") or {}
    steps = orch.get("steps") if isinstance(orch.get("steps"), list) else []
    return {str(row.get("action") or "") for row in steps if isinstance(row, dict)}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder,expected_actions",
    [
        (build_auto_task_payload_like_frontend, {"crawl_keyword", "evaluate_leads"}),
        (build_manual_task_payload_like_frontend, {"crawl_content_url"}),
        (build_account_home_payload_like_frontend, {"crawl_profile"}),
    ],
)
async def test_external_task_preflight_orchestration_preview(
    flow_client,
    builder,
    expected_actions,
):
    client, _settings, _svc = flow_client
    payload = _unique_correlation(builder(), builder.__name__)

    resp = client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["ready"] is True
    assert body["blocking_count"] == 0
    actions = _orchestration_actions(body)
    assert expected_actions.issubset(actions), actions
    assert body.get("evaluation")
    assert body.get("orchestration", {}).get("agent_strategy")


@pytest.mark.asyncio
async def test_external_task_create_pending_with_supervisor_plan(flow_client):
    client, _settings, _svc = flow_client
    payload = _unique_correlation(build_auto_task_payload_like_frontend(), "create")

    resp = client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] == "pending"
    assert body["auto_execute"] is False
    result = body.get("result") or {}
    assert result.get("execution_mode") == "supervisor"
    orch = result.get("orchestration") or {}
    assert orch.get("source") == "supervisor"
    brief = orch.get("task_brief") or {}
    assert brief.get("keyword") == "团餐配送"
    assert brief.get("region") == "深圳"
    assert result.get("sandbox", {}).get("job_id") == body["job_id"]
    config = (result.get("config") or {}) if isinstance(result.get("config"), dict) else {}
    correlation = config.get("correlation") if isinstance(config.get("correlation"), dict) else {}
    if not correlation:
        correlation = (body.get("sync") or {}).get("correlation") or {}
    loaded = _svc.get_job("default", body["job_id"])
    assert loaded is not None
    assert loaded.correlation.get("external_task_id") == payload["correlation"]["external_task_id"]


@pytest.mark.asyncio
async def test_external_task_execute_completes_supervisor_flow(flow_client):
    client, settings, svc = flow_client
    payload = _unique_correlation(build_auto_task_payload_like_frontend(), "execute")

    create = client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert create.status_code == 200, create.text
    job_id = create.json()["job_id"]

    execute = client.post(f"/api/agent/jobs/{job_id}/execute", headers=API_HEADERS)
    assert execute.status_code == 200, execute.text
    assert execute.json()["status"] == "queued"

    await svc._run_job(_JobKey(tenant_id="default", job_id=job_id), settings)

    loaded = svc.get_job("default", job_id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.result.get("summary") == "flow test completed"
    cycles = loaded.result.get("supervisor_cycles") or []
    assert len(cycles) >= 1
    assert cycles[0].get("action") == "crawl_keyword"

    detail = client.get(f"/api/agent/jobs/{job_id}", headers=API_HEADERS)
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_external_task_auto_execute_runs_without_manual_execute(flow_client):
    client, settings, svc = flow_client
    payload = _unique_correlation(build_auto_task_payload_like_frontend(), "auto")
    payload["auto_execute"] = True

    create = client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert create.status_code == 200, create.text
    body = create.json()
    job_id = body["job_id"]
    assert body["status"] == "queued"

    await svc._run_job(_JobKey(tenant_id="default", job_id=job_id), settings)

    loaded = svc.get_job("default", job_id)
    assert loaded is not None
    assert loaded.status == "completed"


@pytest.mark.asyncio
async def test_full_flow_preflight_create_execute_get(flow_client):
    """端到端：预检 → 创建 → 手动执行 → 查询结果。"""
    client, settings, svc = flow_client
    payload = _unique_correlation(build_auto_task_payload_like_frontend(), "full")

    preflight = client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert preflight.status_code == 200
    assert preflight.json()["ready"] is True

    create = client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    job_id = create.json()["job_id"]

    execute = client.post(f"/api/agent/jobs/{job_id}/execute", headers=API_HEADERS)
    assert execute.json()["status"] == "queued"

    await svc._run_job(_JobKey(tenant_id="default", job_id=job_id), settings)

    final = client.get(f"/api/agent/jobs/{job_id}", headers=API_HEADERS).json()
    assert final["status"] == "completed"
    assert final["result"]["execution_mode"] == "supervisor"
    assert final["result"]["orchestration"]["task_brief"]["keyword"] == "团餐配送"
    loaded = svc.get_job("default", job_id)
    assert loaded is not None
    assert loaded.correlation.get("external_task_id") == payload["correlation"]["external_task_id"]

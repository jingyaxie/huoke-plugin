"""线索 LLM 评估：编译 evaluation spec、批量打分、触达筛选。

评估核心由大模型做「评论意向 vs 获客主题」语义判断，不做关键词匹配或写死话术规则。
用户可在创建任务时补充 accept_description 等约束；未补充时由 LLM 根据业务上下文自动判定。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.services.ai_client import AIClientFactory
from app.services.task_brief_service import TaskBrief

SCHEMA_VERSION = "huoke.lead_evaluation.v1"
RESULT_SCHEMA_VERSION = "huoke.lead_evaluation_result.v1"
EVALUATION_MODE_LLM_INTENT = "llm_intent"
EVALUATION_STYLE_USAGE_EXPERIENCE = "usage_experience"
_LLM_BATCH_SIZE = 12

DEFAULT_THRESHOLDS = {"precise": 0.60, "outreach": 0.55}
LEGACY_COMPILED_PRECISE = 0.72


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_spec_hash(spec: dict[str, Any]) -> str:
    payload = {k: v for k, v in spec.items() if k not in {"compiled_at", "spec_hash"}}
    digest = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def evaluation_draft_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    draft: dict[str, Any] = {}
    for key in (
        "target_customer",
        "product_or_service",
        "accept_description",
        "reject_description",
        "positive_examples",
        "negative_examples",
        "reject_signals",
        "precise_threshold",
        "outreach_threshold",
        "template_id",
    ):
        val = payload.get(key)
        if val is not None and val != "" and val != []:
            draft[key] = val
    return draft


def _business_context_from_brief(
    brief: TaskBrief,
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    draft = draft if isinstance(draft, dict) else {}
    keyword = str(brief.keyword or draft.get("keyword") or "").strip()
    region = str(brief.region or draft.get("region") or "").strip()
    return {
        "keyword": keyword or None,
        "region": region or None,
        "product_or_service": str(draft.get("product_or_service") or keyword or brief.title or "").strip() or None,
        "target_customer": str(draft.get("target_customer") or "").strip() or None,
        "task_title": str(brief.title or "").strip() or None,
    }


def evaluation_preview_text(spec: dict[str, Any]) -> str:
    """预检/展示用：说明评估如何工作（非写死话术规则）。"""
    mode = str(spec.get("evaluation_mode") or "").strip()
    ctx = spec.get("business_context") if isinstance(spec.get("business_context"), dict) else {}
    criteria = spec.get("criteria") if isinstance(spec.get("criteria"), dict) else {}
    user_accept = str(criteria.get("accept_description") or "").strip()
    if user_accept:
        return user_accept[:160]
    theme = str(ctx.get("product_or_service") or ctx.get("keyword") or "获客主题").strip()
    if mode == EVALUATION_MODE_LLM_INTENT:
        return f"大模型以「使用心得」方式评估：判断评论是否像真实用户围绕「{theme}」的体验、感受或实操疑问"
    return ""


def build_rule_based_spec(
    brief: TaskBrief,
    *,
    draft: dict[str, Any] | None = None,
    source: str = "auto_generated",
) -> dict[str, Any]:
    """生成 evaluation spec 骨架：业务上下文 + 用户草稿；判定逻辑交给 LLM。"""
    draft = draft if isinstance(draft, dict) else {}
    business_context = _business_context_from_brief(brief, draft)

    accept = str(draft.get("accept_description") or "").strip()
    reject = str(draft.get("reject_description") or "").strip()
    reject_signals = draft.get("reject_signals")
    if not reject and isinstance(reject_signals, list) and reject_signals:
        reject = "、".join(str(x) for x in reject_signals if str(x).strip())

    positive_examples = draft.get("positive_examples")
    negative_examples = draft.get("negative_examples")

    try:
        precise_threshold = float(draft.get("precise_threshold") or DEFAULT_THRESHOLDS["precise"])
    except (TypeError, ValueError):
        precise_threshold = DEFAULT_THRESHOLDS["precise"]
    try:
        outreach_threshold = float(draft.get("outreach_threshold") or DEFAULT_THRESHOLDS["outreach"])
    except (TypeError, ValueError):
        outreach_threshold = DEFAULT_THRESHOLDS["outreach"]

    spec: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "version": 1,
        "source": source,
        "evaluation_mode": EVALUATION_MODE_LLM_INTENT,
        "evaluation_style": EVALUATION_STYLE_USAGE_EXPERIENCE,
        "compiled_at": _utc_now_iso(),
        "business_context": business_context,
        "criteria": {
            "accept_description": accept,
            "reject_description": reject,
            "positive_examples": positive_examples if isinstance(positive_examples, list) else [],
            "negative_examples": negative_examples if isinstance(negative_examples, list) else [],
        },
        "thresholds": {
            "precise": round(max(0.0, min(1.0, precise_threshold)), 3),
            "outreach": round(max(0.0, min(1.0, outreach_threshold)), 3),
        },
        "llm": {"provider": "deepseek", "batch_size": _LLM_BATCH_SIZE},
    }
    if draft.get("template_id"):
        spec["template_id"] = str(draft["template_id"])
    spec["spec_hash"] = compute_spec_hash(spec)
    return spec


async def compile_lead_evaluation_spec(
    brief: TaskBrief,
    *,
    settings: Settings,
    draft: dict[str, Any] | None = None,
    provider: str | None = None,
    source: str = "auto_generated",
) -> dict[str, Any]:
    """编译 evaluation spec；用户未写 accept 时由 LLM 根据业务背景生成可执行 rubric。"""
    draft = draft if isinstance(draft, dict) else {}
    base = build_rule_based_spec(brief, draft=draft, source=source)
    criteria = base.setdefault("criteria", {})
    if str(criteria.get("accept_description") or "").strip():
        return base

    factory = AIClientFactory(settings)
    client = factory.llm_client()
    if client is None:
        return base

    model = factory.llm_model()
    system = (
        "你是获客线索评估规格编写助手。根据业务背景输出 JSON："
        "accept_description, reject_description, target_customer, product_or_service。"
        "评估采用「使用心得」视角：判断评论是否像真实用户围绕该主题的使用体验、感受、实操疑问或购买兴趣；"
        "不要要求出现关键词，不要罗列固定话术；positive_examples/negative_examples 可省略或留空数组。"
    )
    user = json.dumps(
        {
            "keyword": brief.keyword,
            "region": brief.region,
            "task_title": brief.title,
            "business_context": base.get("business_context"),
            "user_draft": draft,
        },
        ensure_ascii=False,
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = json.loads(raw)
        if isinstance(data, dict):
            for key in ("accept_description", "reject_description"):
                val = str(data.get(key) or "").strip()
                if val:
                    criteria[key] = val
            for key in ("positive_examples", "negative_examples"):
                val = data.get(key)
                if isinstance(val, list) and val:
                    criteria[key] = [str(x).strip() for x in val if str(x).strip()]
            ctx = base.setdefault("business_context", {})
            for key in ("target_customer", "product_or_service"):
                val = str(data.get(key) or "").strip()
                if val:
                    ctx[key] = val
            base["source"] = source if source != "auto_generated" else "llm_compiled"
            base["compiled_at"] = _utc_now_iso()
            base["spec_hash"] = compute_spec_hash(base)
    except Exception:
        pass
    return base


def lead_evaluation_from_brief(brief: TaskBrief) -> dict[str, Any]:
    raw = brief.constraints.get("lead_evaluation")
    if isinstance(raw, dict) and raw.get("schema") == SCHEMA_VERSION:
        spec = dict(raw)
        min_digg = min_comment_digg_from_brief(brief)
        if min_digg > 0:
            spec.setdefault("min_comment_digg", min_digg)
        return spec
    raise ValueError("lead_evaluation_missing")


def min_comment_digg_from_brief(brief: TaskBrief) -> int:
    for src in (brief.constraints, brief.goals):
        if not isinstance(src, dict):
            continue
        for key in ("min_comment_digg", "min_digg", "min_comment_likes"):
            val = src.get(key)
            if val is not None:
                try:
                    return max(0, int(val))
                except (TypeError, ValueError):
                    continue
    return 0


def precise_threshold_from_spec(spec: dict[str, Any]) -> float:
    """精准入库/展示阈值；未自定义的旧任务（编译默认 0.72）随产品默认值下调。"""
    thresholds = spec.get("thresholds") if isinstance(spec.get("thresholds"), dict) else {}
    try:
        raw = float(thresholds.get("precise") or DEFAULT_THRESHOLDS["precise"])
    except (TypeError, ValueError):
        raw = DEFAULT_THRESHOLDS["precise"]
    if abs(raw - LEGACY_COMPILED_PRECISE) < 0.001 and DEFAULT_THRESHOLDS["precise"] < LEGACY_COMPILED_PRECISE:
        raw = DEFAULT_THRESHOLDS["precise"]
    try:
        outreach = float(thresholds.get("outreach") or DEFAULT_THRESHOLDS["outreach"])
    except (TypeError, ValueError):
        outreach = DEFAULT_THRESHOLDS["outreach"]
    return max(outreach, raw)


def accept_evaluation_result(result: dict[str, Any], spec: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if not result.get("is_lead"):
        return False
    thresholds = spec.get("thresholds") if isinstance(spec.get("thresholds"), dict) else {}
    outreach_min = float(thresholds.get("outreach") or DEFAULT_THRESHOLDS["outreach"])
    try:
        score = float(result.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    if score < outreach_min:
        return False
    if result.get("worth_outreach") is False:
        return False
    return True


def is_precise_lead(result: dict[str, Any], spec: dict[str, Any]) -> bool:
    if not accept_evaluation_result(result, spec):
        return False
    precise_min = precise_threshold_from_spec(spec)
    try:
        score = float(result.get("score") or 0)
    except (TypeError, ValueError):
        return False
    return score >= precise_min


def evaluation_result_to_lead_fields(result: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    precise = is_precise_lead(result, spec)
    try:
        score = float(result.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "status": "precise" if precise else "raw",
        "match_score": round(score, 3),
        "precise_reason": str(result.get("reason") or ""),
        "evaluation": {
            "schema": RESULT_SCHEMA_VERSION,
            "is_lead": bool(result.get("is_lead")),
            "score": round(score, 3),
            "intent_type": str(result.get("intent_type") or ""),
            "confidence": float(result.get("confidence") or 0),
            "worth_outreach": bool(result.get("worth_outreach", result.get("is_lead"))),
            "reason": str(result.get("reason") or ""),
        },
    }


def _build_evaluate_system_prompt(spec: dict[str, Any], brief: TaskBrief) -> str:
    ctx = spec.get("business_context") if isinstance(spec.get("business_context"), dict) else {}
    criteria = spec.get("criteria") if isinstance(spec.get("criteria"), dict) else {}
    thresholds = spec.get("thresholds") if isinstance(spec.get("thresholds"), dict) else {}
    theme = str(ctx.get("product_or_service") or ctx.get("keyword") or brief.keyword or "当前获客主题").strip()
    user_accept = str(criteria.get("accept_description") or "").strip()
    user_reject = str(criteria.get("reject_description") or "").strip()
    pos_examples = criteria.get("positive_examples") if isinstance(criteria.get("positive_examples"), list) else []
    neg_examples = criteria.get("negative_examples") if isinstance(criteria.get("negative_examples"), list) else []

    lines = [
        "你是获客线索评估器，采用「使用心得」方式打分。",
        "把每条评论当作用户在看完视频后的真实反馈，判断其是否围绕获客主题产生了有价值的互动意向。",
        "【判定方式】结合 content_title（视频标题）理解语境，做语义判断，禁止关键词字面匹配。",
        "【有效线索（使用心得视角）】",
        "- 体验/感受：用过、装过、正在用、很喜欢、不错、推荐等真实态度（即使很短）",
        "- 实操疑问：怎么安装、多少钱、在哪买、能上门吗、材质/尺寸/售后等",
        "- 场景需求：我家也想装、卫生间小能用吗、漏水怎么办等",
        "【无效】纯表情刷屏、同行广告、招聘、与视频主题无关的灌水",
        f"【获客主题】{theme}",
        f"【任务关键词】{ctx.get('keyword') or brief.keyword or ''}",
        f"【地区偏好】{ctx.get('region') or brief.region or '不限'}",
        f"【目标客户】{ctx.get('target_customer') or ''}",
        f"【任务标题】{ctx.get('task_title') or brief.title or ''}",
    ]
    if user_accept:
        lines.append(f"【用户补充-接受原则】{user_accept}")
    if user_reject:
        lines.append(f"【用户补充-排除原则】{user_reject}")
    if pos_examples:
        lines.append(f"【用户补充-正向参考】{json.dumps(pos_examples, ensure_ascii=False)}")
    if neg_examples:
        lines.append(f"【用户补充-负向参考】{json.dumps(neg_examples, ensure_ascii=False)}")
    lines.extend(
        [
            f"【触达阈值】{thresholds.get('outreach', DEFAULT_THRESHOLDS['outreach'])} "
            f"【精准阈值】{precise_threshold_from_spec(spec)}",
            '输出 JSON：{"results":[{"comment_id","is_lead","score","intent_type",'
            '"confidence","worth_outreach","reason"}]}。',
            "intent_type 建议：usage_experience|practical_inquiry|interest_signal|social_gesture|spam_ad|off_topic。",
            "score 0~1：使用心得/实操咨询/明确兴趣应 ≥0.55；纯 social_gesture 通常 <0.55；reason 一句话说明判断依据。",
        ]
    )
    return "\n".join(lines)


def _comment_text_for_eval(row: dict[str, Any]) -> str:
    return str(row.get("comment") or row.get("comment_text") or "").strip()


async def evaluate_comments_batch(
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
    brief: TaskBrief,
    *,
    settings: Settings,
    provider: str | None = None,
) -> dict[str, dict[str, Any]]:
    """批量 LLM 意图评估；返回 comment_id -> 评估结果。"""
    if not rows:
        return {}

    llm_cfg = spec.get("llm") if isinstance(spec.get("llm"), dict) else {}
    factory = AIClientFactory(settings)
    client = factory.llm_client()
    if client is None:
        return {}

    model = factory.llm_model()
    system = _build_evaluate_system_prompt(spec, brief)
    batch_size = int(llm_cfg.get("batch_size") or _LLM_BATCH_SIZE)
    ctx = spec.get("business_context") if isinstance(spec.get("business_context"), dict) else {}

    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        payload_comments: list[dict[str, str]] = []
        for row in batch:
            if not isinstance(row, dict):
                continue
            comment_id = str(row.get("comment_id") or "").strip()
            text = _comment_text_for_eval(row)
            if not comment_id:
                continue
            if not text:
                out[comment_id] = {
                    "is_lead": False,
                    "score": 0.0,
                    "confidence": 0.0,
                    "intent_type": "empty",
                    "worth_outreach": False,
                    "reason": "评论为空",
                }
                continue
            title = str(
                row.get("content_title")
                or row.get("video_title")
                or row.get("title")
                or ""
            ).strip()
            payload_comments.append(
                {
                    "comment_id": comment_id,
                    "text": text[:500],
                    "content_title": title[:200],
                    "author_nickname": str(row.get("nickname") or "")[:80],
                }
            )

        if not payload_comments:
            continue

        user = json.dumps(
            {
                "business_context": ctx,
                "task_keyword": brief.keyword,
                "task_region": brief.region,
                "comments": payload_comments,
            },
            ensure_ascii=False,
        )
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            raw = (resp.choices[0].message.content or "").strip()
            data = json.loads(raw)
        except Exception:
            continue

        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            single = data if isinstance(data, dict) and data.get("comment_id") else None
            results = [single] if isinstance(single, dict) else []

        for item in results:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("comment_id") or "").strip()
            if not cid:
                continue
            try:
                score = float(item.get("score") or 0)
            except (TypeError, ValueError):
                score = 0.0
            try:
                confidence = float(item.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            out[cid] = {
                "is_lead": bool(item.get("is_lead")),
                "score": round(max(0.0, min(1.0, score)), 3),
                "confidence": round(max(0.0, min(1.0, confidence)), 3),
                "intent_type": str(item.get("intent_type") or ""),
                "worth_outreach": bool(item.get("worth_outreach", item.get("is_lead"))),
                "reason": str(item.get("reason") or ""),
            }

    return out


async def ensure_lead_evaluation_on_brief(
    brief: TaskBrief,
    *,
    settings: Settings,
    draft: dict[str, Any] | None = None,
    provider: str | None = None,
    force: bool = False,
) -> TaskBrief:
    """确保 brief.constraints.lead_evaluation 已编译冻结。"""
    existing = brief.constraints.get("lead_evaluation")
    if (
        not force
        and isinstance(existing, dict)
        and existing.get("schema") == SCHEMA_VERSION
        and existing.get("spec_hash")
    ):
        return brief
    source = "user_explicit" if draft else "auto_generated"
    if isinstance(draft, dict) and draft.get("template_id"):
        source = "tenant_template"
    spec = await compile_lead_evaluation_spec(
        brief,
        settings=settings,
        draft=draft,
        provider=provider,
        source=source,
    )
    brief.constraints["lead_evaluation"] = spec
    brief.constraints.pop("comment_match", None)
    brief.constraints.pop("match_keywords", None)
    return brief

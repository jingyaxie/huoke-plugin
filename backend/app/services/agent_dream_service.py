from __future__ import annotations

import json
import re
import uuid
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.schemas.agent_experience import AgentExperienceCreate, AgentDreamResult, ExperienceOutcome
from app.services.agent_experience_store import AgentExperienceStore, _tokenize
from app.services.agent_run_store import AgentRunRecord, AgentRunStore, run_title_from_messages


_SKILL_SLASH_RE = re.compile(r"/([a-z][a-z0-9_-]{1,63})")
_ERROR_HINTS = (
    ("验证码", "遇到验证码时暂停并提示人工介入，不要反复点击"),
    ("登录", "执行前先确认登录态，未登录时不要继续 DOM 操作"),
    ("timeout", "选择器可能失效或页面未加载完，先 browser_get_page_info 再操作"),
    ("超时", "选择器可能失效或页面未加载完，先 browser_wait 并检查页面"),
    ("network", "SPA 页面优先 browser_get_network_data 或内置 skill，少依赖 DOM 文本"),
    ("未搜索到", "搜索类任务优先用 /search-content 或 *-keyword-comments builtin"),
    ("comment", "评论抓取用 /content-comments；回复用 /reply-comment，不要手工翻页"),
)


def _slug_id(prefix: str, seed: str) -> str:
    base = re.sub(r"[^a-z0-9_-]+", "-", seed.lower()).strip("-")[:40]
    if not base:
        base = uuid.uuid4().hex[:8]
    return f"{prefix}-{base}"[:63]


def _first_user_goal(messages: list[dict[str, Any]]) -> str:
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = str(msg.get("content") or "").strip()
        if not content or content.startswith("【对话历史摘要】"):
            continue
        return content
    return run_title_from_messages(messages)


def _extract_skill_ids(text: str) -> list[str]:
    return list(dict.fromkeys(_SKILL_SLASH_RE.findall(text)))


def _parse_tool_payload(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


class AgentDreamService:
    def __init__(self, settings: Settings, tenant_id: str) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.run_store = AgentRunStore(settings)
        self.experience_store = AgentExperienceStore(settings)

    def _outcome_from_status(self, status: str) -> ExperienceOutcome:
        if status == "completed":
            return "success"
        if status == "failed":
            return "failure"
        return "partial"

    def _analyze_messages(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        errors: list[str] = []
        skills_ok: list[str] = []
        skills_fail: list[str] = []
        tools: list[str] = []
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            tool_name = str(msg.get("tool_name") or msg.get("name") or "")
            if tool_name:
                tools.append(tool_name)
            data = _parse_tool_payload(str(msg.get("content") or ""))
            if data.get("error"):
                errors.append(str(data["error"])[:240])
            if tool_name.startswith("skill_") or tool_name == "invoke_skill":
                if data.get("status") == "completed" or data.get("summary"):
                    label = data.get("skill_name") or data.get("skill_id") or tool_name
                    skills_ok.append(str(label))
                elif data.get("error"):
                    label = data.get("skill_id") or tool_name
                    skills_fail.append(f"{label}: {data['error'][:120]}")

        return {
            "errors": errors[:8],
            "skills_ok": skills_ok[:8],
            "skills_fail": skills_fail[:8],
            "tools": tools[:20],
        }

    def _build_keywords(self, goal: str, analysis: dict[str, Any], platform: str) -> list[str]:
        keywords = list(_extract_skill_ids(goal))
        keywords.extend(sorted(_tokenize(goal))[:12])
        for skill in analysis.get("skills_ok", []) + analysis.get("skills_fail", []):
            keywords.extend(_extract_skill_ids(skill))
            keywords.extend(sorted(_tokenize(skill))[:4])
        if platform:
            keywords.append(platform)
        dedup: list[str] = []
        seen: set[str] = set()
        for kw in keywords:
            kw = kw.strip()
            if not kw or kw in seen:
                continue
            seen.add(kw)
            dedup.append(kw)
        return dedup[:20]

    def _heuristic_tips(
        self,
        *,
        outcome: ExperienceOutcome,
        goal: str,
        analysis: dict[str, Any],
        summary: str,
    ) -> tuple[list[str], list[str], str]:
        do_tips: list[str] = []
        avoid_tips: list[str] = []
        blob = " ".join(analysis.get("errors", []) + [summary, goal]).lower()

        if outcome == "success":
            if analysis.get("skills_ok"):
                do_tips.append(
                    f"相似任务可优先使用已验证成功的技能：{', '.join(analysis['skills_ok'][:3])}"
                )
            if any("search" in t for t in analysis.get("tools", [])):
                do_tips.append("搜索视频列表用 /search-content 或 *-keyword-comments，比手工解析搜索页 DOM 更高效")
            if "browser_get_network_data" in analysis.get("tools", []) or "browser_get_page_info" in analysis.get("tools", []):
                do_tips.append("SPA 页面优先读 api_captures / browser_get_network_data，再决定是否截图")
        else:
            avoid_tips.append("不要重复已失败的路径；换用内置 skill 或调整参数后再试")
            if analysis.get("skills_fail"):
                avoid_tips.append(f"以下技能/调用曾失败：{'; '.join(analysis['skills_fail'][:2])}")

        for hint, tip in _ERROR_HINTS:
            if hint in blob:
                avoid_tips.append(tip)

        if "browser_screenshot" in analysis.get("tools", []) and "browser_get_text" not in analysis.get("tools", []):
            avoid_tips.append("当前模型不支持 Vision 时，截图无法被理解，应改用 browser_get_text 或接口数据")

        if "browser_get_text" in analysis.get("tools", []) and "browser_get_network_data" not in analysis.get("tools", []):
            if any(k in goal for k in ("搜索", "评论", "视频", "抖音", "douyin")):
                do_tips.append("抖音数据类任务优先接口拦截或内置 skill，DOM 文本往往不完整")

        do_tips = list(dict.fromkeys(do_tips))[:6]
        avoid_tips = list(dict.fromkeys(avoid_tips))[:6]

        outcome_word = {"success": "成功", "failure": "失败", "partial": "部分完成"}.get(outcome, outcome)
        lesson = summary.strip() if summary else ""
        if not lesson:
            if outcome == "success":
                lesson = f"任务「{goal[:80]}」已完成。"
            else:
                lesson = f"任务「{goal[:80]}」未完成。"
        if analysis.get("errors"):
            lesson += f" 主要错误：{analysis['errors'][0][:160]}"
        lesson = f"【{outcome_word}】{lesson}"
        return do_tips, avoid_tips, lesson

    def build_experience_from_run(
        self,
        run: AgentRunRecord,
        *,
        summary: str = "",
    ) -> AgentExperienceCreate | None:
        if run.status not in {"completed", "failed"}:
            return None
        messages = [m for m in run.messages if m.get("role") != "system"]
        if len(messages) < 2:
            return None
        goal = _first_user_goal(run.messages)
        if not goal or goal == "新对话":
            return None

        analysis = self._analyze_messages(run.messages)
        outcome = self._outcome_from_status(run.status)
        if not summary:
            summary = run_title_from_messages(run.messages)
            if outcome == "failure" and analysis.get("errors"):
                summary = analysis["errors"][0][:200]

        do_tips, avoid_tips, lesson = self._heuristic_tips(
            outcome=outcome,
            goal=goal,
            analysis=analysis,
            summary=summary,
        )
        keywords = self._build_keywords(goal, analysis, run.platform)
        title = goal[:80] + ("…" if len(goal) > 80 else "")
        exp_id = _slug_id("exp", f"{run.run_id[:8]}-{goal[:16]}")

        return AgentExperienceCreate(
            id=exp_id,
            title=title,
            task_keywords=keywords,
            outcome=outcome,
            lesson=lesson,
            do_tips=do_tips,
            avoid_tips=avoid_tips,
            platform=run.platform,
            agent_profile_id=(run.agent_profile_id or "").strip(),
            source_run_id=run.run_id,
            enabled=True,
        )

    async def _maybe_enhance_with_llm(
        self,
        experience: AgentExperienceCreate,
        run: AgentRunRecord,
        *,
        client: AsyncOpenAI,
        model: str,
    ) -> AgentExperienceCreate:
        trace_lines: list[str] = []
        for msg in run.messages[-24:]:
            role = msg.get("role")
            if role == "system":
                continue
            content = msg.get("content")
            if isinstance(content, list):
                content = "[multimodal]"
            text = str(content or "")[:400]
            if role == "tool":
                name = msg.get("tool_name") or msg.get("name") or "tool"
                trace_lines.append(f"tool:{name} -> {text[:280]}")
            else:
                trace_lines.append(f"{role}: {text}")
        prompt = (
            "你是智能体经验提炼器。根据以下任务执行轨迹，输出 JSON："
            '{"lesson":"一句话经验","do_tips":["..."],"avoid_tips":["..."],"task_keywords":["..."]}\n'
            f"任务目标：{experience.title}\n"
            f"结果：{experience.outcome}\n"
            f"轨迹：\n" + "\n".join(trace_lines[-18:])
        )
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "只输出 JSON，不要 markdown。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=600,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            data = json.loads(raw)
            if isinstance(data, dict):
                if data.get("lesson"):
                    experience.lesson = str(data["lesson"])[:800]
                if isinstance(data.get("do_tips"), list):
                    experience.do_tips = [str(x)[:200] for x in data["do_tips"][:6]]
                if isinstance(data.get("avoid_tips"), list):
                    experience.avoid_tips = [str(x)[:200] for x in data["avoid_tips"][:6]]
                if isinstance(data.get("task_keywords"), list):
                    merged = list(dict.fromkeys(experience.task_keywords + [str(x) for x in data["task_keywords"]]))
                    experience.task_keywords = merged[:20]
        except Exception:
            pass
        return experience

    async def dream_from_run(
        self,
        run_id: str,
        *,
        summary: str = "",
        use_llm: bool = False,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
    ) -> AgentExperienceCreate | None:
        if not self.settings.agent_dream_enabled:
            return None
        if self.experience_store.has_dreamed_run(self.tenant_id, run_id):
            return None
        run = self.run_store.get(self.tenant_id, run_id)
        if run is None:
            return None
        experience = self.build_experience_from_run(run, summary=summary)
        if experience is None:
            return None
        if use_llm and self.settings.agent_dream_use_llm and client is not None and model:
            experience = await self._maybe_enhance_with_llm(
                experience, run, client=client, model=model
            )
        try:
            self.experience_store.create(self.tenant_id, experience)
        except ValueError:
            experience.id = _slug_id("exp", run_id)
            self.experience_store.create(self.tenant_id, experience)
        self.experience_store.mark_dreamed_run(self.tenant_id, run_id)
        return experience

    async def consolidate_recent(
        self,
        *,
        limit: int = 30,
        use_llm: bool = False,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
    ) -> AgentDreamResult:
        result = AgentDreamResult()
        runs = self.run_store.list_for_tenant(self.tenant_id, limit=limit)
        for run in runs:
            if run.status not in {"completed", "failed"}:
                result.skipped.append(run.run_id)
                continue
            if self.experience_store.has_dreamed_run(self.tenant_id, run.run_id):
                result.skipped.append(run.run_id)
                continue
            try:
                created = await self.dream_from_run(
                    run.run_id,
                    use_llm=use_llm,
                    client=client,
                    model=model,
                )
                if created:
                    result.created.append(created.id)
                else:
                    result.skipped.append(run.run_id)
            except Exception as exc:
                result.errors.append(f"{run.run_id}: {exc}")
        return result

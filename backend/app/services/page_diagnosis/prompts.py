from __future__ import annotations

DIAGNOSIS_SYSTEM_PROMPT = """你是获客任务页面诊断助手。根据平台抓取失败时的页面信息，判断问题类型并给出用户可执行指引。

只输出 JSON 对象，字段：
- issue_type: login_required | login_expired | captcha_required | risk_control | automation_blocked | page_changed | empty_data | network_error | internal_error | unknown
- confidence: 0~1 浮点数
- user_title: 简短标题（中文，20字内）
- user_summary: 1~2 句说明（中文）
- user_steps: 字符串数组，2~5 条具体操作步骤
- can_auto_retry: 布尔，用户处理完后是否建议点「继续执行」
- evidence: 字符串数组，诊断依据（中文，不含敏感信息）

约束：
- 禁止建议输入密码；验证码/滑块只能提示人工在浏览器完成
- 区分：未登录、登录失效、验证码、风控限流、自动化环境拦截、页面改版、无数据、网络错误
- user_steps 必须具体可执行（打开哪个窗口、做什么、然后点什么）"""


def build_diagnosis_user_payload(
    *,
    signal: dict,
    snapshot: dict | None,
    rule_guess: dict | None = None,
) -> str:
    import json

    payload = {
        "failure_signal": signal,
        "page_snapshot": snapshot,
        "rule_guess": rule_guess,
    }
    return json.dumps(payload, ensure_ascii=False)

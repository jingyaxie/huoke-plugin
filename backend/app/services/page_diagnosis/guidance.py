from __future__ import annotations

from dataclasses import dataclass

from app.services.page_diagnosis.contracts import IssueType, Platform

PLATFORM_LABEL = {
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "kuaishou": "快手",
}

ISSUE_LABEL = {
    "login_required": "登录",
    "login_expired": "登录失效",
    "captcha_required": "验证",
    "risk_control": "风控",
    "automation_blocked": "环境拦截",
    "page_changed": "页面变化",
    "empty_data": "无数据",
    "network_error": "网络",
    "internal_error": "内部错误",
    "unknown": "未知",
}


@dataclass(frozen=True)
class GuidanceTemplate:
    user_title: str
    user_summary: str
    user_steps: tuple[str, ...]
    can_auto_retry: bool = True
    retry_after_seconds: int | None = None


GENERIC_GUIDANCE: dict[IssueType, GuidanceTemplate] = {
    "login_required": GuidanceTemplate(
        user_title="账号未登录",
        user_summary="当前会话未登录，无法继续抓取。",
        user_steps=(
            "打开「账号设置」，确认该平台账号已绑定",
            "在弹出的浏览器窗口完成扫码登录",
            "返回任务详情，点击「继续执行」",
        ),
    ),
    "login_expired": GuidanceTemplate(
        user_title="登录态已失效",
        user_summary="本地登录 Cookie 已过期或无效。",
        user_steps=(
            "在账号设置中重新绑定该平台账号",
            "完成登录后点击「继续执行」",
        ),
    ),
    "captcha_required": GuidanceTemplate(
        user_title="需要完成人机验证",
        user_summary="平台要求先完成验证码/滑块验证。",
        user_steps=(
            "打开绑定的浏览器窗口（不要关闭）",
            "手动完成页面上的验证",
            "验证通过后回到任务点击「继续执行」",
        ),
        can_auto_retry=True,
    ),
    "risk_control": GuidanceTemplate(
        user_title="触发平台风控或频率限制",
        user_summary="操作过于频繁或账号被临时限制。",
        user_steps=(
            "暂停任务 30–60 分钟",
            "降低单日抓取/触达频率",
            "稍后点击「继续执行」",
        ),
        can_auto_retry=True,
        retry_after_seconds=1800,
    ),
    "automation_blocked": GuidanceTemplate(
        user_title="浏览器环境被平台识别",
        user_summary="当前浏览器可能被识别为自动化环境。",
        user_steps=(
            "确认使用系统 Chrome（ANTIBOT_BROWSER_CHANNEL=chrome）",
            "或改用 headless 模式后重新绑定账号",
            "完成后点击「继续执行」",
        ),
    ),
    "page_changed": GuidanceTemplate(
        user_title="页面结构可能已变化",
        user_summary="自动化选择器未匹配到预期元素。",
        user_steps=(
            "确认平台页面可正常手动访问",
            "点击「继续执行」重试一次",
            "若仍失败请联系管理员更新适配",
        ),
    ),
    "empty_data": GuidanceTemplate(
        user_title="未找到符合条件的数据",
        user_summary="当前关键词/时间窗/链接下没有可抓取内容。",
        user_steps=(
            "放宽评论时间窗或评估标准",
            "更换关键词或博主链接",
            "调整后点击「继续执行」",
        ),
    ),
    "network_error": GuidanceTemplate(
        user_title="网络或页面加载异常",
        user_summary="请求超时或页面未加载完成。",
        user_steps=(
            "检查本机网络与代理设置",
            "点击「继续执行」重试",
        ),
    ),
    "internal_error": GuidanceTemplate(
        user_title="任务执行内部错误",
        user_summary="抓取组件返回异常，非平台登录/风控问题。",
        user_steps=(
            "点击「继续执行」重试",
            "若重复失败请查看任务日志并联系支持",
        ),
    ),
    "unknown": GuidanceTemplate(
        user_title="任务已暂停",
        user_summary="抓取遇到问题，请按下方步骤处理后继续。",
        user_steps=("查看任务日志中的错误摘要", "确认账号登录正常后点击「继续执行」"),
    ),
}


PLATFORM_OVERRIDES: dict[tuple[Platform, IssueType], GuidanceTemplate] = {
    ("douyin", "captcha_required"): GuidanceTemplate(
        user_title="需要完成抖音人机验证",
        user_summary="抖音当前页面处于验证码/风控中间页，自动化无法继续。",
        user_steps=(
            "打开账号设置中绑定的 Chrome 窗口（抖音页）",
            "完成滑块或验证码，直到能正常浏览视频",
            "返回任务详情，点击「继续执行」",
        ),
    ),
    ("douyin", "automation_blocked"): GuidanceTemplate(
        user_title="抖音识别为自动化浏览器",
        user_summary="页面被导向 so-landing 或类似拦截域。",
        user_steps=(
            "设置 ANTIBOT_BROWSER_CHANNEL=chrome 使用系统 Chrome",
            "或改用 headless 模式重新绑定抖音账号",
            "完成后点击「继续执行」",
        ),
    ),
    ("xiaohongshu", "login_required"): GuidanceTemplate(
        user_title="小红书未登录或为游客态",
        user_summary="当前会话不是已登录的真实账号。",
        user_steps=(
            "在账号设置点击「授权账号」绑定小红书",
            "在 Chrome 完成扫码登录，确认非游客态",
            "绑定成功后点击「继续执行」",
        ),
    ),
    ("kuaishou", "login_required"): GuidanceTemplate(
        user_title="快手账号未登录",
        user_summary="请先完成快手登录绑定。",
        user_steps=(
            "在账号设置中绑定快手账号并完成扫码登录",
            "返回任务点击「继续执行」",
        ),
    ),
}


def resolve_guidance(platform: Platform, issue_type: IssueType) -> GuidanceTemplate:
    override = PLATFORM_OVERRIDES.get((platform, issue_type))
    if override:
        return override
    return GENERIC_GUIDANCE.get(issue_type, GENERIC_GUIDANCE["unknown"])

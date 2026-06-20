from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


AgentMode = Literal["agent", "plan", "ask"]
RunMode = Literal["auto", "confirm", "dry_run"]


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = None
    run_id: str | None = None
    account_id: str | None = None
    agent_profile_id: str | None = Field(
        default=None,
        description="Agent 档案 ID，默认 default",
    )
    provider: Literal["openai", "deepseek"] = "deepseek"
    headless: bool | None = None
    explicit_skill_ids: list[str] = Field(default_factory=list)
    mode: AgentMode = "agent"
    run_mode: RunMode = "auto"


class AgentChatSyncRequest(AgentChatRequest):
    timeout_seconds: int = Field(default=600, ge=10, le=3600)


class AgentChatSyncResponse(BaseModel):
    run_id: str | None = None
    session_id: str | None = None
    status: str
    summary: str = ""
    final_message: str = ""
    task_snapshot: dict[str, Any] = Field(default_factory=dict)
    phase: str = ""
    message_count: int = 0
    updated_at: datetime | None = None


class AgentAsyncSubmitRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    config: dict[str, Any] | None = Field(
        default=None,
        description=(
            "结构化任务配置。支持顶层字段 keyword/platform/region/target_count/comment_days/"
            "crawl_video_limit，以及 constraints/goals/crawl。循环任务使用 "
            "`repeat_mode=round`、`round_target_count`、`max_rounds`：一轮可跨多天，"
            "当前轮达标后再开启下一轮。旧字段 video_limit/content_limit/limit/"
            "video_limit_per_batch 会归一为 crawl_video_limit。"
        ),
        examples=[
            {
                "task_name": "深圳团餐线索循环触达",
                "keyword": "团餐配送",
                "platform": "douyin",
                "region": "深圳",
                "target_count": 80,
                "crawl_video_limit": 5,
                "repeat_mode": "round",
                "round_target_count": 80,
                "max_rounds": 3,
                "constraints": {
                    "daily_reply_limit": 2,
                    "daily_follow_limit": 2,
                    "daily_dm_limit": 2,
                    "termination_resume_next_day": True,
                    "outreach_priority": ["reply"],
                },
            }
        ],
    )
    agent_profile_id: str | None = None
    agent_strategy: str | None = Field(
        default=None,
        description="任务执行策略 ID，如 skill-flow-douyin",
    )
    provider: Literal["openai", "deepseek"] = "deepseek"
    mode: AgentMode = "agent"
    run_mode: RunMode = "auto"
    auto_execute: bool = Field(default=True, description="创建后是否立即入队执行")
    auto_restart: bool = Field(default=True, description="失败时是否自动重试（最多 max_retries 次）")
    timeout_seconds: int = Field(default=600, ge=10, le=3600)
    max_retries: int = Field(default=1, ge=0, le=5)
    priority: int = Field(default=5, ge=1, le=10)
    webhook_url: str | None = None
    webhook_headers: dict[str, str] = Field(default_factory=dict)


class AgentJobConfigUpdateRequest(BaseModel):
    message: str | None = Field(
        default=None,
        max_length=8000,
        description="自然语言或 JSON 配置修改指令",
    )
    config: dict[str, Any] | None = Field(
        default=None,
        description="结构化配置 patch（goals/constraints/keyword 等）",
    )
    provider: Literal["openai", "deepseek"] | None = Field(
        default=None,
        description="可选：指定用于理解修改指令的模型",
    )


class AgentAsyncJobOut(BaseModel):
    job_id: str
    status: str
    stage: str = "plan"
    retry_count: int = 0
    run_id: str | None = None
    session_id: str | None = None
    message: str = ""
    provider: str = "deepseek"
    mode: str = "agent"
    run_mode: str = "auto"
    auto_execute: bool = True
    auto_restart: bool = True
    platform: str = ""
    account_id: str = ""
    timeout_seconds: int = 600
    max_retries: int = 1
    priority: int = 5
    result: dict[str, Any] = Field(default_factory=dict)
    sync: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    dead_letter_reason: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentResumeRunRequest(BaseModel):
    run_id: str


class AgentResumeRequest(BaseModel):
    run_id: str
    approved: bool


class AgentRunSummaryOut(BaseModel):
    run_id: str
    title: str
    status: str
    message_count: int
    platform: str
    updated_at: datetime | None = None
    created_at: datetime | None = None


class AgentRunListResponse(BaseModel):
    items: list[AgentRunSummaryOut]
    total: int


class AgentRunOut(BaseModel):
    run_id: str
    browser_session_id: str
    tenant_id: str
    platform: str
    provider: str
    status: str
    mode: str = "agent"
    run_mode: str = "auto"
    agent_profile_id: str = "default"
    message_count: int
    messages: list[dict[str, Any]] = Field(default_factory=list)
    pending_plan: dict[str, Any] | None = None
    pending_approval: dict[str, Any] | None = None
    review_report: dict[str, Any] = Field(default_factory=dict)
    validation_report: dict[str, Any] = Field(default_factory=dict)
    resumable: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentSessionCreateRequest(BaseModel):
    headless: bool | None = None


class AgentSessionOut(BaseModel):
    session_id: str
    platform: str
    tenant_id: str
    url: str | None = None
    title: str | None = None


class AgentMessageOut(BaseModel):
    role: Literal["user", "assistant", "tool", "system"]
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None


class AgentEvent(BaseModel):
    type: Literal[
        "session",
        "status",
        "message",
        "message_delta",
        "tool_start",
        "tool_result",
        "step",
        "screenshot",
        "plan",
        "approval_request",
        "checkpoint",
        "context_compressed",
        "skill_installed",
        "skill_install_failed",
        "cancelled",
        "done",
        "error",
    ]
    data: dict[str, Any] = Field(default_factory=dict)


class CheckpointOut(BaseModel):
    checkpoint_id: str
    run_id: str
    step: int
    tool: str
    url: str | None = None
    title: str | None = None
    created_at: datetime | None = None


class CheckpointListResponse(BaseModel):
    items: list[CheckpointOut] = Field(default_factory=list)
    total: int = 0


class RestoreCheckpointRequest(BaseModel):
    checkpoint_id: str


class AgentProviderInfo(BaseModel):
    configured: bool
    vision: bool = False
    model: str
    note: str | None = None


class AgentBindingStatusOut(BaseModel):
    ready: bool
    tenant_id: str
    account_id: str
    platform: str
    platform_label: str
    status: str
    message: str
    cookie_count: int = 0
    storage_state_path: str | None = None
    code: str | None = None
    bind_api: str | None = None
    bindings_api: str | None = None


class AgentConfigOut(BaseModel):
    default_provider: Literal["openai", "deepseek"]
    default_run_mode: RunMode = "auto"
    dream_enabled: bool = True
    dream_auto: bool = True
    providers: dict[str, AgentProviderInfo]


class AgentStrategyOut(BaseModel):
    id: str
    platform: str
    label: str
    description: str
    profile_id: str
    execution_mode: str
    crawl_skill_id: str
    is_default: bool = False

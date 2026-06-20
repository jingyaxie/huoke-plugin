from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ExternalTaskIntent = Literal["keyword_auto", "single_video", "account_home"]
ExternalPlatform = Literal["douyin", "xiaohongshu", "kuaishou"]


class ExternalTaskCorrelation(BaseModel):
    external_system: str = Field(default="aisales", max_length=32)
    external_task_id: str = Field(..., min_length=1, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ExternalTaskScope(BaseModel):
    keyword: str | None = None
    region: str | None = None
    input_url: str | None = None
    target_count: int | None = Field(default=None, ge=1)
    comment_days: int | None = Field(default=None, ge=0)
    publish_time_range: str | None = Field(
        default=None,
        description="unlimited | 1d | 3d | 7d | 180d",
    )
    repeat_mode: str | None = None
    round_target_count: int | None = Field(default=None, ge=1)
    max_rounds: int | None = Field(default=None, ge=1)
    crawl_video_limit: int | None = Field(default=None, ge=1)


class ExternalTaskCrawl(BaseModel):
    headless: bool | None = Field(
        default=None,
        description="true=无头后台运行，false=有头可见浏览器（调试用）",
    )
    force_refresh: bool | None = Field(
        default=None,
        description="true=忽略缓存，强制重新搜索抓取",
    )


class ExternalTaskOutreach(BaseModel):
    constraints: dict[str, Any] = Field(default_factory=dict)
    reply_templates: list[str] | None = None
    dm_templates: list[str] | None = None
    reply_template: str | None = None
    dm_template: str | None = None


class ExternalTaskEvaluation(BaseModel):
    template_id: str | None = Field(default=None, description="行业预设模板 ID")
    target_customer: str | None = None
    product_or_service: str | None = None
    accept_description: str | None = None
    reject_description: str | None = None
    positive_examples: list[str] | None = None
    negative_examples: list[str] | None = None
    reject_signals: list[str] | None = None
    precise_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    outreach_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class ExternalTaskCreateRequest(BaseModel):
    intent: ExternalTaskIntent
    name: str = Field(..., min_length=1, max_length=128)
    platform: ExternalPlatform = "douyin"
    scope: ExternalTaskScope = Field(default_factory=ExternalTaskScope)
    crawl: ExternalTaskCrawl | None = None
    evaluation: ExternalTaskEvaluation | None = None
    outreach: ExternalTaskOutreach = Field(default_factory=ExternalTaskOutreach)
    correlation: ExternalTaskCorrelation
    auto_execute: bool = True
    auto_restart: bool = True
    timeout_seconds: int = Field(default=600, ge=10, le=3600)
    max_retries: int = Field(default=1, ge=0, le=5)
    priority: int = Field(default=5, ge=1, le=10)
    webhook_url: str | None = None
    webhook_headers: dict[str, str] = Field(default_factory=dict)
    agent_strategy: str | None = None
    provider: Literal["openai", "deepseek"] = "deepseek"


class ExternalTaskFieldSpec(BaseModel):
    key: str
    type: str
    required: bool = False
    label: str = ""
    description: str = ""


class ExternalTaskFieldOption(BaseModel):
    value: str
    label: str


class ExternalTaskIntentSpec(BaseModel):
    intent: ExternalTaskIntent
    label: str
    description: str
    lead_task_types: list[str] = Field(default_factory=list)
    scope_fields: list[ExternalTaskFieldSpec] = Field(default_factory=list)
    default_comment_days: int = 3


class ExternalTaskCapabilitiesOut(BaseModel):
    schema_version: str = "huoke.external_task.v1"
    platforms: list[str] = Field(default_factory=lambda: ["douyin", "xiaohongshu"])
    sync_schema: str = "huoke.agent_job_sync.v1"
    intents: list[ExternalTaskIntentSpec] = Field(default_factory=list)
    field_options: dict[str, list[ExternalTaskFieldOption]] = Field(default_factory=dict)
    evaluation_fields: list[ExternalTaskFieldSpec] = Field(default_factory=list)
    evaluation_templates: list[dict[str, Any]] = Field(default_factory=list)


class ExternalTaskPreflightCheck(BaseModel):
    id: str
    label: str
    status: Literal["ok", "warning", "error"]
    message: str
    blocking: bool = False


class ExternalTaskPreflightOrchestrationPreview(BaseModel):
    summary: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    agent_strategy: str = ""
    execution_mode: str = ""


class ExternalTaskPreflightEvaluationPreview(BaseModel):
    ready: bool = False
    provider: str = ""
    llm_configured: bool = False
    accept_preview: str = ""


class ExternalTaskPreflightOut(BaseModel):
    schema_version: str = "huoke.external_task_preflight.v1"
    ready: bool
    blocking_count: int = 0
    warning_count: int = 0
    checks: list[ExternalTaskPreflightCheck] = Field(default_factory=list)
    orchestration: ExternalTaskPreflightOrchestrationPreview | None = None
    evaluation: ExternalTaskPreflightEvaluationPreview | None = None

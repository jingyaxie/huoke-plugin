from pydantic import BaseModel, Field


class AntibotDelayProfileOut(BaseModel):
    name: str
    min_ms: float
    max_ms: float


class AntibotGlobalConfigOut(BaseModel):
    scope: str = "global"
    enabled: bool
    stealth_enabled: bool
    require_login: bool
    delay_min_ms: float
    delay_max_ms: float
    user_agent: str
    viewport_width: int
    viewport_height: int
    locale: str
    timezone: str
    stealth_version: str
    delay_profiles: list[AntibotDelayProfileOut]


class TenantAntibotOverrideOut(BaseModel):
    enabled: bool | None = None
    stealth_enabled: bool | None = None
    require_login: bool | None = None
    delay_min_ms: float | None = Field(default=None, ge=0)
    delay_max_ms: float | None = Field(default=None, ge=0)
    delay_multiplier: float | None = Field(default=None, ge=0.1, le=10.0)


class TenantAntibotOverrideRequest(TenantAntibotOverrideOut):
    pass


class TenantAntibotConfigOut(BaseModel):
    tenant_id: str
    override_path: str
    has_override: bool
    override: TenantAntibotOverrideOut | None = None
    effective: AntibotGlobalConfigOut

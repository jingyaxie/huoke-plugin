from pydantic import BaseModel, Field


class CreateTenantKeyRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    label: str = ""


class CreateTenantKeyResponse(BaseModel):
    tenant_id: str
    api_key: str
    label: str
    message: str

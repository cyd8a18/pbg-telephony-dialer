from typing import Optional

from pydantic import BaseModel, Field


class WebhookEvent(BaseModel):
    seq: Optional[int] = None
    ts: Optional[str] = None
    event: str
    call_control_id: Optional[str] = None
    client_id: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    phone: Optional[str] = None
    matches: Optional[list[str]] = None
    code: Optional[int] = None
    message: Optional[str] = None

    class Config:
        extra = "allow"
        allow_population_by_field_name = True


class WebhookResult(BaseModel):
    processed: bool
    duplicate: bool = False
    event_key: str

from pydantic import BaseModel, Field
from typing import Any, Optional


class HealthzResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: int
    contexts_loaded: dict[str, int]


class MetadataResponse(BaseModel):
    team_name: str
    team_members: list[str] = Field(default_factory=lambda: ["Builder"])
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str


class ContextRequest(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


class ContextAcceptedResponse(BaseModel):
    accepted: bool = True
    ack_id: str
    stored_at: str


class ContextConflictResponse(BaseModel):
    accepted: bool = False
    reason: str = "stale_version"
    current_version: int


class ContextErrorResponse(BaseModel):
    accepted: bool = False
    reason: str
    details: Optional[str] = None


class TickRequest(BaseModel):
    now: str
    available_triggers: list[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: str
    trigger_id: str
    template_name: Optional[str] = "vera_generic_v1"
    template_params: Optional[list[str]] = None
    body: str
    cta: str
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: list[ActionItem] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


class ReplyResponse(BaseModel):
    action: str  # "send" | "wait" | "end"
    body: Optional[str] = None
    wait_seconds: Optional[int] = None
    cta: Optional[str] = None
    rationale: str

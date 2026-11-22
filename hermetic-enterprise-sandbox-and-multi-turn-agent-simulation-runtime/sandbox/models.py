from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Action(Strict):
    tool: Literal["ticket.create", "ticket.read", "ticket.update", "user.read", "document.search"]
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class Step(Strict):
    user: str
    action: Action
    expect: dict[str, Any] = Field(default_factory=dict)


class Scenario(Strict):
    name: str = Field(min_length=1, max_length=100)
    version: str = "1"
    mode: Literal["scripted", "live"] = "scripted"
    persona: str = "A concise employee requesting IT help."
    goal: str = "Create a ticket and verify its status."
    seed: int = 42
    max_turns: int = Field(default=8, ge=1, le=30)
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    retries: int = Field(default=2, ge=0, le=5)
    initial_users: list[dict] = Field(
        default_factory=lambda: [{"id": "employee-1", "name": "Demo Employee"}]
    )
    initial_documents: list[dict] = Field(
        default_factory=lambda: [
            {"id": "kb-1", "text": "Restart the VPN client before requesting IT help."}
        ]
    )
    steps: list[Step] = Field(default_factory=list, max_length=30)
    expected_tickets: int = Field(default=1, ge=0)
    expected_status: str | None = "open"
    inject_transient_after_create: bool = False

    @model_validator(mode="after")
    def check_steps(self):
        if self.mode == "scripted" and not self.steps:
            raise ValueError("scripted scenarios require steps")
        if len(self.steps) > self.max_turns:
            raise ValueError("steps exceed max_turns")
        return self

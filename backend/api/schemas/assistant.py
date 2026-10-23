"""
==============================================================================
API SCHEMA: ASSISTANT CHAT REQUEST (DTO)
==============================================================================
File: backend/api/schemas/assistant.py

Data Transfer Object (DTO) for the interactive conversational assistant endpoint.
Defines input contract containing user prompt and conversation thread ID.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.ia.chat_history import is_valid_thread_id


class AssistantRequest(BaseModel):
    """Payload for conversational assistant streaming requests."""

    model_config = ConfigDict(extra="ignore")

    thread_id: str = Field(..., min_length=1, description="Conversation thread identifier (e.g. username:ordinal)")
    prompt: str | None = Field(default=None, description="User prompt or query message")
    content: str | None = Field(default=None, description="Alias for user prompt")

    @field_validator("thread_id")
    @classmethod
    def thread_id_must_be_safe(cls, value: str) -> str:
        # The thread id becomes a file name, so it must not be able to leave the history folder.
        if not is_valid_thread_id(value):
            raise ValueError("Invalid thread_id.")
        return value

    @model_validator(mode="after")
    def validate_message_present(self) -> "AssistantRequest":
        msg = (self.prompt or self.content or "").strip()
        if not msg:
            raise ValueError("Either 'prompt' or 'content' must be provided and non-empty.")
        return self

    @property
    def message(self) -> str:
        return (self.prompt or self.content or "").strip()

"""
==============================================================================
API SCHEMA: CHAT INPUT PAYLOAD (DTO)
==============================================================================
File: backend/api/schemas/chat.py

Data Transfer Object (DTO) for the conversational chat endpoint.
Defines the strict JSON contract for incoming user messages.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.ia.chat_history import is_valid_thread_id


class ChatRequest(BaseModel):
    # Security: Rejects any JSON payload containing fields other than 'mensaje'
    # and 'thread_id', preventing injection attempts or malformed requests.
    model_config = ConfigDict(extra="forbid")

    # Cost Defense Strategy:
    # Validates input length before making expensive/slow network calls to the LLM.
    # Discards empty or accidental keystrokes (min_length=3) at the routing layer
    # (HTTP 422 Unprocessable Entity) without invoking the business logic.
    mensaje: str = Field(..., min_length=3)

    # Optional. With a thread id, a message that has no place in it (for example a
    # question about licences) is answered by the conversational assistant, which
    # keeps the memory of that thread. Without it, the chat asks for clarification.
    thread_id: str | None = Field(default=None, min_length=1, description="Conversation thread (username:ordinal)")

    @field_validator("thread_id")
    @classmethod
    def thread_id_must_be_safe(cls, value: str | None) -> str | None:
        # The thread id becomes a file name, so it must not be able to leave the history folder.
        if value is not None and not is_valid_thread_id(value):
            raise ValueError("Invalid thread_id.")
        return value

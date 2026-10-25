"""
==============================================================================
API SCHEMAS: CHAT HISTORY (DTOs)
==============================================================================
File: backend/api/schemas/history.py

Data Transfer Objects (DTOs) for retrieving chat conversation history files.
"""

from pydantic import BaseModel, ConfigDict, Field


class HistoryRequest(BaseModel):
    """Request payload or query parameters for retrieving conversation history."""

    model_config = ConfigDict(extra="ignore")

    thread_id: str = Field(
        ...,
        min_length=1,
        description="files named after it in REPO_ROOT/chat_history contain thread history",
    )


class HistoryResponse(BaseModel):
    """Response payload containing chat history for a thread."""

    model_config = ConfigDict(extra="ignore")

    thread_id: str = Field(
        ...,
        description="files named after it in REPO_ROOT/chat_history contain thread history",
    )
    content: str = Field(
        ...,
        description="Text content of the chat history file",
    )
    filename: str = Field(
        ...,
        description="Basename of the file in REPO_ROOT/chat_history",
    )

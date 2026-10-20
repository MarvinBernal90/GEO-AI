"""
==============================================================================
API SCHEMAS: USER AUTHENTICATION & SESSIONS (DTOs)
==============================================================================
File: backend/api/schemas/login.py

Data Transfer Objects (DTOs) for user authentication and session retrieval.
Defines input contract for login requests and structured output containing
user profile info and conversation history.
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Payload for user login request."""

    user: str = Field(..., min_length=1, description="Username or user identifier")


class ConversationOut(BaseModel):
    """Summary of a conversation thread."""

    id: str = Field(..., description="Unique conversation thread identifier")
    title: str = Field(..., description="Title or summary of the conversation")


class LoginResponse(BaseModel):
    """Response returned upon successful login verification."""

    user: str = Field(..., description="Verified username")
    conversations: list[ConversationOut] = Field(default_factory=list, description="List of user conversations")

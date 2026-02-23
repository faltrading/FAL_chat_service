import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class GroupMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    username: str
    role: str
    joined_at: datetime

    class Config:
        from_attributes = True


class GroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    is_default: bool
    is_public: bool
    invite_code: str | None = None
    created_by: uuid.UUID
    member_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GroupListResponse(BaseModel):
    groups: list[GroupResponse]
    total: int

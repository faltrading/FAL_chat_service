import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    message_type: str = Field(default="text")
    reply_to_id: uuid.UUID | None = None
    metadata: dict = Field(default_factory=dict)


class MessageUpdate(BaseModel):
    content: str = Field(..., min_length=1)


class MessageResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    sender_id: uuid.UUID | None
    sender_username: str | None
    content: str
    message_type: str
    reply_to_id: uuid.UUID | None
    reply_to_content: str | None = None
    reply_to_username: str | None = None
    metadata: dict = Field(default_factory=dict, validation_alias="extra_data")
    is_edited: bool
    edited_at: datetime | None
    is_deleted: bool
    is_pinned: bool = False
    pinned_at: datetime | None = None
    pinned_by: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    has_more: bool
    next_cursor: str | None = None


class ReadStatusCreate(BaseModel):
    message_ids: list[uuid.UUID]


class ReadStatusResponse(BaseModel):
    message_id: uuid.UUID
    user_id: uuid.UUID
    read_at: datetime

    class Config:
        from_attributes = True

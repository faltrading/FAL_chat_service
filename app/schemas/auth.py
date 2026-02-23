import uuid

from pydantic import BaseModel


class TokenPayload(BaseModel):
    sub: str
    username: str
    role: str
    exp: int | None = None


class CurrentUser(BaseModel):
    user_id: uuid.UUID
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

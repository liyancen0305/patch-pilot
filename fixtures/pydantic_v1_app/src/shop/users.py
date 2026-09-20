"""User model and field validation."""

from pydantic import validator

from .base import ShopModel


class User(ShopModel):
    id: int
    email: str
    name: str

    @validator("id")
    def positive_id(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("id must be positive")
        return value

    @validator("email")
    def normalized_email(cls, value: str) -> str:
        value = value.lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("invalid email")
        return value

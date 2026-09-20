"""Shared Pydantic v1 model configuration."""

from pydantic import BaseModel


class ShopModel(BaseModel):
    class Config:
        anystr_strip_whitespace = True
        extra = "forbid"
        validate_assignment = True

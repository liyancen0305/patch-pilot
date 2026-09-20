"""Order models with cross-field validation."""


from pydantic import root_validator, validator

from .base import ShopModel
from .users import User


class OrderItem(ShopModel):
    sku: str
    quantity: int
    unit_price_cents: int

    @validator("quantity", "unit_price_cents")
    def positive_amount(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("amount must be positive")
        return value


class Order(ShopModel):
    id: int
    customer: User
    items: list[OrderItem]
    total_cents: int

    @root_validator
    def total_matches_items(cls, values: dict[str, object]) -> dict[str, object]:
        items = values.get("items")
        total = values.get("total_cents")
        if isinstance(items, list) and isinstance(total, int):
            expected = sum(item.quantity * item.unit_price_cents for item in items)
            if total != expected:
                raise ValueError("total does not match items")
        return values

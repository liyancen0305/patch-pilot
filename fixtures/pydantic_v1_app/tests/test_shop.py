import pytest
from pydantic import ValidationError

from shop import Order, OrderItem, User


def test_valid_user_and_normalization() -> None:
    user = User(id=1, email=" ADA@EXAMPLE.COM ", name=" Ada ")
    assert user.email == "ada@example.com"
    assert user.name == "Ada"


@pytest.mark.parametrize("data", [
    {"id": 0, "email": "a@example.com", "name": "A"},
    {"id": 1, "email": "invalid", "name": "A"},
])
def test_invalid_user_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        User.parse_obj(data)


def test_shared_config_rejects_extra_and_validates_assignment() -> None:
    with pytest.raises(ValidationError):
        User.parse_obj({"id": 1, "email": "a@example.com", "name": "A", "unknown": True})
    user = User(id=1, email="a@example.com", name="A")
    with pytest.raises(ValidationError):
        user.id = -1


def test_item_field_validation() -> None:
    with pytest.raises(ValidationError):
        OrderItem(sku="x", quantity=0, unit_price_cents=100)


def test_nested_parse_and_serialization() -> None:
    order = Order.parse_obj({
        "id": 10,
        "customer": {"id": 1, "email": "ADA@EXAMPLE.COM", "name": " Ada "},
        "items": [
            {"sku": "pen", "quantity": 2, "unit_price_cents": 150},
            {"sku": "book", "quantity": 1, "unit_price_cents": 700},
        ],
        "total_cents": 1000,
    })
    assert isinstance(order.customer, User)
    assert isinstance(order.items[0], OrderItem)
    assert order.dict()["customer"] == {
        "id": 1, "email": "ada@example.com", "name": "Ada"
    }
    assert order.dict()["items"][0]["sku"] == "pen"


def test_order_total_matches_multiple_items() -> None:
    with pytest.raises(ValidationError, match="total does not match items"):
        Order.parse_obj({
            "id": 10,
            "customer": {"id": 1, "email": "a@example.com", "name": "A"},
            "items": [{"sku": "pen", "quantity": 2, "unit_price_cents": 150}],
            "total_cents": 299,
        })

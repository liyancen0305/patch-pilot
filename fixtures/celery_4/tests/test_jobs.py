import pytest

from jobs import add_tax, app


def test_eager_task_preserves_invoice_amount() -> None:
    assert app.conf.task_always_eager
    assert add_tax.delay(100, 10).get(timeout=2) == 110


def test_eager_errors_propagate() -> None:
    with pytest.raises(ValueError, match="nonnegative"):
        add_tax.delay(-1, 10)

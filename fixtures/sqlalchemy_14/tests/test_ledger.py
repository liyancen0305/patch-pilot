from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ledger.models import Base
from ledger.repository import add_account, find_account, total_balance


def test_account_round_trip_and_totals() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        add_account(session, " Ada ", 125)
        add_account(session, "Bo", 75)
        found = find_account(session, "Ada")
        assert found is not None and found.owner == "Ada"
        assert find_account(session, "Missing") is None
        assert total_balance(session) == 200

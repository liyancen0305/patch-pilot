from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account


def add_account(session: Session, owner: str, balance: int) -> Account:
    account = Account(owner=owner.strip(), balance=balance)
    session.add(account)
    session.commit()
    return account


def find_account(session: Session, owner: str) -> Account | None:
    return session.scalars(select(Account).where(Account.owner == owner)).one_or_none()


def total_balance(session: Session) -> int:
    return sum(cast(int, row.balance) for row in session.scalars(select(Account).order_by(Account.id)))

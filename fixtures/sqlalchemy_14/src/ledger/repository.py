from sqlalchemy.orm import Session

from .models import Account


def add_account(session: Session, owner: str, balance: int) -> Account:
    account = Account(owner=owner.strip(), balance=balance)
    session.add(account)
    session.commit()
    return account


def find_account(session: Session, owner: str) -> Account | None:
    return session.query(Account).filter(Account.owner == owner).one_or_none()


def total_balance(session: Session) -> int:
    return sum(row.balance for row in session.query(Account).order_by(Account.id).all())

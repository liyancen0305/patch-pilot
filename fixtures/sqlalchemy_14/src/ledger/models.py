from typing import Any

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base: Any = declarative_base()


class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True)
    owner = Column(String(80), nullable=False)
    balance = Column(Integer, nullable=False)

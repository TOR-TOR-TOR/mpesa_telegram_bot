"""
database/models.py — SQLAlchemy table definitions.
These are the 3 core tables the entire bot depends on.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean,
    DateTime, ForeignKey, BigInteger
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id   = Column(BigInteger, unique=True, nullable=False)  # Telegram user ID
    username      = Column(String, nullable=True)                    # @username (optional)
    full_name     = Column(String, nullable=True)                    # First + last name
    phone_number  = Column(String, nullable=True)                    # M-Pesa phone number
    is_banned     = Column(Boolean, default=False)
    created_at    = Column(DateTime, default=datetime.utcnow)

    # Relationships
    subscriptions = relationship("Subscription", back_populates="user")
    transactions  = relationship("Transaction", back_populates="user")

    def __repr__(self):
        return f"<User telegram_id={self.telegram_id} name={self.full_name}>"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan         = Column(String, nullable=False)       # weekly | monthly | quarterly
    is_active    = Column(Boolean, default=False)
    started_at   = Column(DateTime, nullable=True)
    expires_at   = Column(DateTime, nullable=True)
    reminded_3d  = Column(Boolean, default=False)       # 3-day reminder sent?
    reminded_1d  = Column(Boolean, default=False)       # 1-day reminder sent?
    created_at   = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user         = relationship("User", back_populates="subscriptions")

    def __repr__(self):
        return f"<Subscription user_id={self.user_id} plan={self.plan} active={self.is_active}>"


class Transaction(Base):
    __tablename__ = "transactions"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    user_id             = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan                = Column(String, nullable=False)
    amount              = Column(Integer, nullable=False)          # KES
    phone_number        = Column(String, nullable=False)           # number STK push was sent to
    checkout_request_id = Column(String, unique=True, nullable=True)  # Daraja's tracking ID
    mpesa_receipt       = Column(String, nullable=True)            # M-Pesa receipt number
    status              = Column(String, default="pending")        # pending | success | failed
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user                = relationship("User", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction id={self.id} status={self.status} amount={self.amount}>"
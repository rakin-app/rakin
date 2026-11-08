"""SQLAlchemy ORM models. API schemas live in `app.schemas`, never here."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

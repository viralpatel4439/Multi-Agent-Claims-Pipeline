from datetime import date
from typing import Optional

from sqlalchemy import String, Date
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Member(Base):
    __tablename__ = "members"

    member_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(String(1), nullable=False)
    relationship: Mapped[str] = mapped_column(String(20), nullable=False)
    join_date: Mapped[date] = mapped_column(Date, nullable=False)
    primary_member_id: Mapped[Optional[str]] = mapped_column(String(20))

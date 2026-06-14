from datetime import date
from typing import Optional
from pydantic import BaseModel


class MemberResponse(BaseModel):
    member_id: str
    name: str
    date_of_birth: date
    gender: str
    relationship: str
    join_date: date
    primary_member_id: Optional[str] = None

    class Config:
        from_attributes = True

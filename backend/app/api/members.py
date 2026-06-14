from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.member import Member

router = APIRouter()


@router.get("/members")
async def list_members(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Member).order_by(Member.member_id))
    members = result.scalars().all()
    return [
        {
            "member_id": m.member_id,
            "name": m.name,
            "date_of_birth": str(m.date_of_birth),
            "gender": m.gender,
            "relationship": m.relationship,
            "join_date": str(m.join_date),
            "primary_member_id": m.primary_member_id,
        }
        for m in members
    ]

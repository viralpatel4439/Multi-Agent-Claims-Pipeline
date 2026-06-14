"""Seed database with members from policy_terms.json and pre-existing claim history for TC009."""
import json
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings

settings = get_settings()


def seed():
    policy_file = Path(settings.policy_file_path)
    with open(policy_file) as f:
        policy = json.load(f)

    engine = create_engine(settings.sync_database_url)

    with Session(engine) as session:
        # Upsert members
        for m in policy["members"]:
            session.execute(
                text("""
                    INSERT INTO members (member_id, name, date_of_birth, gender, relationship, join_date, primary_member_id)
                    VALUES (:member_id, :name, :dob, :gender, :relationship, :join_date, :primary_member_id)
                    ON CONFLICT (member_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        date_of_birth = EXCLUDED.date_of_birth,
                        gender = EXCLUDED.gender,
                        relationship = EXCLUDED.relationship,
                        join_date = EXCLUDED.join_date,
                        primary_member_id = EXCLUDED.primary_member_id
                """),
                {
                    "member_id": m["member_id"],
                    "name": m["name"],
                    "dob": m["date_of_birth"],
                    "gender": m["gender"],
                    "relationship": m["relationship"],
                    "join_date": m.get("join_date", "2024-04-01"),
                    "primary_member_id": m.get("primary_member_id"),
                }
            )

        # Seed TC009 pre-existing claims for EMP008 on 2024-10-30
        existing_history = [
            {"claim_id": "CLM_0081", "amount": 1200, "provider": "City Clinic A"},
            {"claim_id": "CLM_0082", "amount": 1800, "provider": "City Clinic B"},
            {"claim_id": "CLM_0083", "amount": 2100, "provider": "Wellness Center"},
        ]

        # Check if already seeded
        count = session.execute(
            text("SELECT COUNT(*) FROM claim_history WHERE member_id = 'EMP008' AND treatment_date = '2024-10-30'")
        ).scalar()

        if count == 0:
            for h in existing_history:
                session.execute(
                    text("""
                        INSERT INTO claim_history (id, member_id, claim_id, treatment_date, claimed_amount, provider, decision)
                        VALUES (:id, :member_id, :claim_id, :treatment_date, :claimed_amount, :provider, :decision)
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "member_id": "EMP008",
                        "claim_id": str(uuid.uuid4()),
                        "treatment_date": "2024-10-30",
                        "claimed_amount": h["amount"],
                        "provider": h["provider"],
                        "decision": "APPROVED",
                    }
                )

        session.commit()
        print(f"Seeded {len(policy['members'])} members and TC009 claim history.")


if __name__ == "__main__":
    seed()

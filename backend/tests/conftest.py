import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

# Ensure backend is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

POLICY_FILE = Path(__file__).parent.parent.parent / "policy_terms.json"
TEST_CASES_FILE = Path(__file__).parent.parent.parent / "test_cases.json"


@pytest.fixture(scope="session")
def policy_data():
    with open(POLICY_FILE) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def policy(policy_data):
    from app.services.policy_service import load_policy
    # Patch env and load
    os.environ["POLICY_FILE_PATH"] = str(POLICY_FILE)
    return load_policy(str(POLICY_FILE))


@pytest.fixture(scope="session")
def test_cases():
    with open(TEST_CASES_FILE) as f:
        return json.load(f)["test_cases"]


@pytest.fixture
def member_emp001():
    return {
        "member_id": "EMP001",
        "name": "Rajesh Kumar",
        "join_date": date(2024, 4, 1),
    }


@pytest.fixture
def member_emp005():
    return {
        "member_id": "EMP005",
        "name": "Vikram Joshi",
        "join_date": date(2024, 9, 1),
    }

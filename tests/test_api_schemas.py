import pytest
from pydantic import ValidationError

from app.main import FarmingStartRequest, ReferralQualifyRequest, TaskReviewRequest, TaskSubmitRequest


def test_farming_reward_rate_is_not_client_configurable():
    with pytest.raises(ValidationError):
        FarmingStartRequest.model_validate(
            {"duration_hours": 8, "points_per_hour": 999999}
        )


def test_farming_duration_is_bounded():
    with pytest.raises(ValidationError):
        FarmingStartRequest.model_validate({"duration_hours": 25})


def test_task_submission_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        TaskSubmitRequest.model_validate({"task_id": "task-1", "reward_points": 999999})


def test_task_review_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        TaskReviewRequest.model_validate({"approved": True, "reviewer_id": "attacker"})


def test_referral_qualification_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ReferralQualifyRequest.model_validate({"reward_points": 10, "admin_id": "attacker"})

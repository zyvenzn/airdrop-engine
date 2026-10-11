import pytest
from pydantic import ValidationError

from app.main import FarmingStartRequest


def test_farming_reward_rate_is_not_client_configurable():
    with pytest.raises(ValidationError):
        FarmingStartRequest.model_validate(
            {"duration_hours": 8, "points_per_hour": 999999}
        )


def test_farming_duration_is_bounded():
    with pytest.raises(ValidationError):
        FarmingStartRequest.model_validate({"duration_hours": 25})

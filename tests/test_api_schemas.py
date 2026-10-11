from app.main import FarmingStartRequest


def test_farming_reward_rate_is_not_client_configurable():
    request = FarmingStartRequest.model_validate({"duration_hours": 8, "points_per_hour": 999999})
    assert request.duration_hours == 8
    assert not hasattr(request, "points_per_hour")


def test_farming_duration_is_bounded():
    try:
        FarmingStartRequest.model_validate({"duration_hours": 25})
    except Exception:
        pass
    else:
        raise AssertionError("duration above policy limit must be rejected")

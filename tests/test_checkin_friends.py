from app.services.checkin import STREAK_REWARDS, streak_reward
from app.services.referrals import BASE_DROP_PLAYS, bonus_drop_plays


def test_checkin_streak_reward_schedule():
    assert [streak_reward(day) for day in range(1, 8)] == list(STREAK_REWARDS)
    assert streak_reward(8) == STREAK_REWARDS[0]


def test_referral_drop_ticket_bonus_is_bounded():
    assert bonus_drop_plays(-1) == 0
    assert bonus_drop_plays(2) == 2
    assert bonus_drop_plays(100) == 5
    assert BASE_DROP_PLAYS == 3

from types import SimpleNamespace

import pytest

from app.services.referrals import attribute_referral


class FakeScalars:
    def all(self):
        return [
            SimpleNamespace(id="u1", status="active"),
            SimpleNamespace(id="u2", status="active"),
        ]


class FakeSession:
    def __init__(self, scalars=None, scalar=None):
        self.scalars_value = scalars
        self.scalar_value = scalar
        self.added = []

    def scalars(self, statement):
        return self.scalars_value

    def scalar(self, statement):
        return self.scalar_value

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass


def test_self_referral_is_rejected_before_database_access():
    with pytest.raises(ValueError, match="self-referral"):
        attribute_referral(FakeSession(), referrer_id="u1", referred_id="u1")


def test_referral_rejects_missing_users():
    with pytest.raises(ValueError, match="both users"):
        attribute_referral(FakeSession(scalars=SimpleNamespace(all=lambda: [])), referrer_id="u1", referred_id="u2")


def test_referral_attribution_creates_pending_record():
    db = FakeSession(scalars=FakeScalars(), scalar=None)
    referral = attribute_referral(db, referrer_id="u1", referred_id="u2")
    assert referral.status == "pending"
    assert referral.referrer_id == "u1"
    assert referral.referred_id == "u2"
    assert referral in db.added

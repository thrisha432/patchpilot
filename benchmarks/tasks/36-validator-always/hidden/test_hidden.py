from app.flags import FeatureFlags


def test_explicit_owner_kept():
    assert FeatureFlags(owner="ada").owner == "ada"


def test_default_env():
    assert FeatureFlags().owner == "team-dev"


def test_valid_rollout():
    assert FeatureFlags(rollout={"a": 0, "b": 100}).rollout == {"a": 0, "b": 100}

import pytest
from pydantic import ValidationError

from app.flags import FeatureFlags


def test_default_owner_from_env():
    assert FeatureFlags(env="prod").owner == "team-prod"


def test_rollout_checked():
    with pytest.raises(ValidationError):
        FeatureFlags(rollout={"new-ui": 120})

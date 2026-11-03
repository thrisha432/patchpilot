from app.profile_api import apply_patch

CURRENT = {"display_name": "Ada", "bio": "math", "newsletter": True}


def test_only_sent_fields_change():
    out = apply_patch(CURRENT, {"bio": None})
    assert out == {"display_name": "Ada", "bio": None, "newsletter": True, "_changed": ["bio"]}

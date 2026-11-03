from app.profile_api import apply_patch


def test_empty_patch():
    assert apply_patch({"bio": "x"}, {}) == {"bio": "x", "_changed": []}

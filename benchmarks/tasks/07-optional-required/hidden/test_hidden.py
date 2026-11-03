from app.profiles import Profile


def test_only_username_required():
    p = Profile(username="x")
    assert (p.bio, p.website, p.age, p.interests) == (None, None, None, [])


def test_none_explicitly_allowed():
    assert Profile(username="x", bio=None).bio is None

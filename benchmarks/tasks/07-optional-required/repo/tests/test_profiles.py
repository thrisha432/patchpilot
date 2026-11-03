from app.profiles import profile_from_form


def test_blank_fields_become_none():
    p = profile_from_form({"username": "ada", "bio": "", "age": "36"})
    assert (p.bio, p.age, p.website) == (None, 36, None)

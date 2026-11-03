from app.articles import Article


def test_comma_string_split_and_lowered():
    assert Article(title="x", tags="Python, AI ,").tags == ["python", "ai"]


def test_list_lowered():
    assert Article(title="x", tags=["ML", "Data"]).tags == ["ml", "data"]

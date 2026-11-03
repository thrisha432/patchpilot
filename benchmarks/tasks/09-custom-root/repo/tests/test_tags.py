from app.tags import dump_tags, parse_tags


def test_names():
    assert parse_tags([{"name": "a"}, {"name": "b", "color": "red"}]).names() == ["a", "b"]


def test_dump():
    assert dump_tags(parse_tags([{"name": "a"}])) == [{"name": "a", "color": "gray"}]

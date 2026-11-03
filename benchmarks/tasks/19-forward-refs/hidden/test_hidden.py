from app.categories import build_tree, depth


def test_leaf():
    assert depth(build_tree({"name": "leaf"})) == 1

from app.categories import Category, build_tree, depth


def test_nested():
    tree = build_tree({"name": "root", "children": [{"name": "a", "children": [{"name": "b"}]}]})
    assert depth(tree) == 3 and isinstance(tree.children[0], Category)
